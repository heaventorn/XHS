# -*- coding: utf-8 -*-
"""platforms/itjuzi.py — IT桔子平台采集器（联系池 · 融资数据）

能力：
  - 持久登录态复用（profile 目录保存 cookies，登录一次后续免登录）
  - IT桔子完全需要登录（未登录搜索无结果、详情页跳转登录）
  - 逐个公司搜索 → 进入详情页 → 文本提取融资字段（轮次/金额/投资方/行业/成立日期）
  - 输出联系池「公司档案」（与 core.aggregate 对接）

IT桔子主打创业投融资数据，特别契合「A-C 轮非上市公司」筛选需求。

合规边界：人工登录 / 人工过验证码 / 低频随机访问（绿区）；
不破解验证码、不建 IP 池高频访问（刑法 285 红线，不碰）。

运行方式：
  独立测试：  python platforms/itjuzi.py --company "公司名" --company "公司2"
  Worker：   python platforms/itjuzi.py --output data/results/itjuzi.json --company "公司名"

提取策略：IT桔子 DOM 为动态结构，以「页面文本 + 正则」为主提取，
联合大调整时可再精调选择器。
"""
import os
import sys
import json
import re
import time
import random
import argparse
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from playwright.sync_api import sync_playwright
from core import humanize as H
from core import network
from core import stealth as S
from core.browser import launch_browser_context
from config import settings

human_sleep = H.human_sleep
move_mouse_human = H.move_mouse_human
random_hover = H.random_hover
random_click_blank = H.random_click_blank
random_keyboard_activity = H.random_keyboard_activity

# ==================== 平台配置 ====================
PLATFORM = "IT桔子"
SEARCH_URL = "https://www.itjuzi.com/search?keyword={}"
LOGIN_PAGE = "https://www.itjuzi.com/login"
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".itjuzi_scraper_profile")

COMPANY_QUERIES = settings.TARGET_COMPANIES
DELAY_BETWEEN_COMPANIES = (8.0, 15.0)

# 融资轮次关键词
_ROUND_KEYWORDS = (
    "种子轮", "天使轮", "Pre-A轮", "A轮", "A+轮", "Pre-B轮", "B轮", "B+轮",
    "C轮", "C+轮", "D轮", "D+轮", "E轮", "F轮", "G轮",
    "战略融资", "战略投资", "股权投资", "并购", "IPO", "上市",
    "Pre-IPO", "新三板", "定向增发",
)
# 融资金额正则（含中文数字/单位）
_AMOUNT_RE = re.compile(
    r"(?:人民币|RMB|美元|USD|港币|HKD|欧元|EUR)?"
    r"\s*[\d一二三四五六七八九十百千万亿.]+\s*"
    r"(?:万|亿|万元|亿元|万美元|亿美元|万人民币|百万|千万)?"
)
# 日期正则
_DATE_RE = re.compile(r"\d{4}[-/年.]\d{1,2}[-/月.]\d{0,2}")
# 邮箱
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# 电话
_PHONE_RE = re.compile(r"(?:\+?86[-\s]?)?(?:1[3-9]\d{9}|0\d{2,3}[-\s]?\d{7,8})")


def _is_logged_in(page):
    """登录检测：检查 URL 和页面内容中的多个已登录标志。
    about:blank / 空 URL / login 页视为未登录；
    URL 不含 login 且页面有 退出/开通VIP/嗨~ 等标志，或无登录注册提示，视为已登录。"""
    try:
        url = page.url or ""
        if not url or "about:blank" in url:
            return False
        if "login" in url:
            return False
        # URL 已不含 login，进一步检查页面内容
        try:
            txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
            # 明确的已登录标志
            if "退出" in txt or "开通VIP" in txt or "嗨~" in txt:
                return True
            # 没有登录/注册提示，也视为已登录
            if "登录" not in txt and "注册" not in txt:
                return True
            return False
        except Exception:
            # page.evaluate 失败（页面还在跳转/渲染），只靠 URL 判断
            return True
    except Exception:
        return False


class ItjuziCrawler:
    """IT桔子平台采集器（联系池 · 融资数据）。run() 返回联系池行列表。"""

    platform = PLATFORM
    channel = "contact"

    def __init__(self, companies=None, max_per_company=1):
        self.companies = [c for c in (companies or COMPANY_QUERIES) if c]
        self.max_per_company = max(1, max_per_company)
        self.rows = []

    def run(self, login_timeout=300):
        if not self.companies:
            print("IT桔子采集器：未配置待查询公司（用 --company 传入或改 COMPANY_QUERIES）。")
            return []

        print("=" * 50)
        print(f"IT桔子采集器：待查询 {len(self.companies)} 家公司")
        print(f"登录态目录：{PROFILE_DIR}")
        print("=" * 50)

        with sync_playwright() as p:
            context, used_channel = launch_browser_context(p, PROFILE_DIR, viewport=H.VIEWPORT)
            # IT桔子不注入 stealth、不拦截资源：stealth 会破坏登录页交互，
            # 且纯净浏览器环境即可正常使用（与脉脉一致）。
            page = context.pages[0] if context.pages else context.new_page()

            # ---- 登录检测 / 引导（IT桔子必须登录） ----
            if not _is_logged_in(page):
                print("\n" + "!" * 50)
                print("检测到未登录！IT桔子必须登录才能搜索和查看公司详情。")
                print("请在弹出浏览器中完成登录（密码/短信/扫码均可），")
                print("脚本会自动检测登录状态，登录成功后自动继续...")
                print("!" * 50)
                # 登录页加载重试：5平台并行时系统资源紧张可能导致超时，重试3次
                login_loaded = False
                for attempt in range(3):
                    try:
                        page.goto(LOGIN_PAGE, wait_until="load", timeout=90000)
                        login_loaded = True
                        break
                    except Exception as e:
                        print(f"\n登录页加载失败（第{attempt+1}/3次）: {e}")
                        if attempt < 2:
                            print("5秒后重试...")
                            time.sleep(5)
                if not login_loaded:
                    print("\n登录页加载失败3次，IT桔子采集器退出。")
                    context.close()
                    return []
                time.sleep(2)  # 等待登录按钮/扫码框渲染完成
                waited = 0
                while waited < login_timeout:
                    time.sleep(3)
                    waited += 3
                    try:
                        if _is_logged_in(page):
                            print(f"\n检测到登录成功（等待约 {waited} 秒），继续执行...\n")
                            break
                    except Exception:
                        pass
                else:
                    print("\n等待登录超时，脚本退出。")
                    context.close()
                    return []

            # ---- 逐个公司采集 ----
            for idx, company in enumerate(self.companies):
                try:
                    self._crawl_company(page, company)
                except Exception as e:
                    print(f"  [IT桔子] 采集「{company}」出错：{e}")

                if idx < len(self.companies) - 1:
                    wait_sec = H._skewed_random(*DELAY_BETWEEN_COMPANIES)
                    print(f"  等待 {wait_sec:.1f} 秒后采集下一家...")
                    wait_end = time.time() + wait_sec
                    while time.time() < wait_end:
                        if random.random() < 0.5:
                            move_mouse_human(page)
                        if random.random() < 0.3:
                            random_keyboard_activity(page)
                        human_sleep((1.0, 2.5))

            context.close()
        return self.rows

    def _crawl_company(self, page, company):
        # 1. 搜索（IT桔子是 SPA，需要等待页面完全渲染）
        url = SEARCH_URL.format(urllib.parse.quote(company))
        page.goto(url, wait_until="load", timeout=60000)
        time.sleep(5)  # 等待 SPA 渲染搜索结果
        human_sleep(H.DELAY_AFTER_SEARCH)
        move_mouse_human(page)

        if "login" in page.url:
            print(f"  [IT桔子] 「{company}」登录态失效，跳过。")
            return
        if self._has_verify(page):
            print(f"  [IT桔子] 「{company}」触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 2. 取第一条匹配公司
        links = self._firm_links(page)
        if not links:
            print(f"  [IT桔子] 「{company}」未找到匹配公司，跳过。")
            return
        pick = links[0]

        # 3. 进详情页
        page.goto(pick["href"], wait_until="domcontentloaded", timeout=45000)
        human_sleep(H.DELAY_PAGE_LOAD)
        if random.random() < 0.5:
            random_hover(page)
        if random.random() < 0.3:
            random_click_blank(page)
        if "login" in page.url:
            print(f"  [IT桔子] 详情页登录态失效，跳过「{pick['name']}」。")
            return
        if self._has_verify(page):
            print(f"  [IT桔子] 详情页触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 4. 提取融资字段
        info = self._extract_detail(page)
        if not info.get("融资轮次") and not info.get("公司名"):
            print(f"  [IT桔子] 「{company}」详情页未提取到有效字段，跳过。")
            return

        row = self._to_contact_row(info, company, pick["name"])
        self.rows.append(row)
        print(f"  [IT桔子] 「{pick['name']}」→ 轮次 {row['融资轮次'] or '未知'} / 金额 {row.get('融资金额','') or '未知'}")

    def _firm_links(self, page):
        """搜索结果页提取 /company/{id} 公司链接（带名称）。"""
        links = page.query_selector_all("a")
        out = []
        for a in links:
            try:
                href = a.get_attribute("href") or ""
                # IT桔子公司链接是相对路径，如 /company/18092，不包含域名
                if "/company/" in href:
                    name = (a.text_content() or "").strip()
                    if not name or len(name) < 2:
                        continue
                    full = href if href.startswith("http") else "https://www.itjuzi.com" + href
                    out.append({"name": name, "href": full})
                    if len(out) >= self.max_per_company:
                        break
            except Exception:
                continue
        return out

    def _extract_detail(self, page):
        """详情页提取：以页面文本 + 正则为主。"""
        info = {}
        try:
            full = page.evaluate("() => document.body.innerText")
            full = re.sub(r"[ \t]+", " ", full)
        except Exception:
            full = ""

        if not full:
            return info

        # ---- 融资轮次（找页面中第一个出现的轮次关键词） ----
        for kw in _ROUND_KEYWORDS:
            if kw in full:
                info["融资轮次"] = kw
                break

        # ---- 融资金额（在轮次关键词附近找金额） ----
        if info.get("融资轮次"):
            idx = full.find(info["融资轮次"])
            nearby = full[max(0, idx - 50):idx + 100]
            am = _AMOUNT_RE.search(nearby)
            if am and len(am.group(0).strip()) > 1:
                info["融资金额"] = am.group(0).strip()

        # ---- 成立日期 ----
        dm = _DATE_RE.search(full)
        if dm:
            info["成立日期"] = dm.group(0)

        # ---- 行业/赛道（找"行业"标签后的值，或常见行业词） ----
        val = self._extract_label_value(full, "行业")
        if val:
            info["所属行业"] = val[:30]
        else:
            # 兜底：找常见行业标签
            for ind in ["人工智能", "大数据", "企业服务", "医疗健康", "生物医药",
                        "新能源", "智能制造", "半导体", "消费", "教育", "金融",
                        "物流", "文娱传媒", "汽车交通", "农业", "硬件", "区块链"]:
                if ind in full:
                    info["所属行业"] = ind
                    break

        # ---- 一句话简介（取页面前 200 字中非导航文本） ----
        # IT桔子详情页顶部通常有公司简介
        lines = [l.strip() for l in full.split("\n") if l.strip() and len(l.strip()) > 10]
        for line in lines[:15]:
            if any(kw in line for kw in ["是一家", "致力于", "专注于", "成立于", "主要从事", "提供"]):
                info["公司简介"] = line[:120]
                break

        # ---- 邮箱/电话（如果详情页有） ----
        em = _EMAIL_RE.search(full)
        if em and "example.com" not in em.group(0):
            info["公司邮箱"] = em.group(0)
        pm = _PHONE_RE.search(full)
        if pm:
            info["联系电话"] = pm.group(0)

        # ---- 法定代表人/创始人（IT桔子有团队信息） ----
        val = self._extract_label_value(full, "创始人")
        if val:
            nm = re.search(r"[\u4e00-\u9fa5·]{2,6}", val)
            if nm:
                info["法定代表人"] = nm.group(0) + "（创始人）"

        return info

    @staticmethod
    def _extract_label_value(text, label):
        """从文本中提取「label：值」或「label 值」格式的值部分。"""
        pattern = re.escape(label) + r"[：:\s]+([^\n\r]{1,80}?)(?=\s{2,}|[\u4e00-\u9fa5]{2,6}[：:]|$)"
        m = re.search(pattern, text)
        if m:
            val = m.group(1).strip()
            for stop in ["融资轮次", "融资金额", "成立日期", "行业", "创始人", "团队", "简介", "电话", "邮箱"]:
                idx = val.find(stop)
                if idx > 0:
                    val = val[:idx].strip()
            return val
        return ""

    def _has_verify(self, page):
        try:
            title = page.title()
            return ("验证" in title) or ("安全" in title) or ("captcha" in page.url.lower())
        except Exception:
            return False

    def _wait_verify_pass(self, page, company, timeout=300):
        waited = 0
        while waited < timeout:
            time.sleep(3)
            waited += 3
            try:
                page.goto(SEARCH_URL.format(urllib.parse.quote(company)),
                          wait_until="domcontentloaded", timeout=30000)
                if not self._has_verify(page):
                    print("  验证已通过，继续...")
                    return
            except Exception:
                pass
        print("  等待验证超时，跳过该公司。")

    def _to_contact_row(self, info, company, picked_name):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        return {
            "公司名": picked_name or info.get("公司名") or company,
            "统一社会信用代码": info.get("统一社会信用代码", ""),
            "所属板块": info.get("所属行业", ""),
            "融资轮次": info.get("融资轮次", ""),
            "法定代表人/董监高": info.get("法定代表人", ""),
            "联系电话": info.get("联系电话", ""),
            "公司邮箱": info.get("公司邮箱", ""),
            "注册地址": info.get("注册地址", ""),
            "公司官网": info.get("公司官网", ""),
            "融资新闻链接": "",
            "联系人角色": "",
            "跟进状态": "待联系",
            "采集时间": now,
            # IT桔子特有附加字段（联合大调整时可并入统一字段）
            "融资金额": info.get("融资金额", ""),
            "成立日期": info.get("成立日期", ""),
            "公司简介": info.get("公司简介", ""),
        }


def main():
    parser = argparse.ArgumentParser(description="IT桔子平台采集器（联系池 · 融资数据）")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（worker 并行模式）")
    parser.add_argument("--company", action="append", default=None, help="待查询公司名（可多次）")
    parser.add_argument("--max-per-company", type=int, default=1, help="每公司取前 N 条结果")
    args = parser.parse_args()

    companies = args.company if args.company else COMPANY_QUERIES
    crawler = ItjuziCrawler(companies=companies, max_per_company=args.max_per_company)
    rows = crawler.run()

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"IT桔子结果已写入：{args.output}（{len(rows)} 条）")
    else:
        if rows:
            print(f"\nIT桔子采集完成，联系池 {len(rows)} 条：")
            for r in rows:
                print(f"  - {r['公司名']} | 轮次 {r['融资轮次']} | 金额 {r.get('融资金额','')}")
        else:
            print("\n未采集到任何数据。")


if __name__ == "__main__":
    main()

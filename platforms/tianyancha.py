# -*- coding: utf-8 -*-
"""platforms/tianyancha.py — 天眼查平台采集器（联系池）

能力：
  - 持久登录态复用（profile 目录保存 cookies，登录一次后续免登录）
  - 未登录也可搜索 + 查看部分详情（邮箱/地址/法人/注册资本可见，电话脱敏）
  - 逐个公司搜索 → 进入详情页 → 文本提取工商字段（信用代码/法人/电话/邮箱/地址/注册资本等）
  - 输出联系池「公司档案」（与 core.aggregate 对接）

合规边界：人工登录 / 人工过验证码 / 低频随机访问（绿区）；
不破解验证码、不建 IP 池高频访问（刑法 285 红线，不碰）。

运行方式：
  独立测试：  python platforms/tianyancha.py --company "公司名" --company "公司2"
  Worker：   python platforms/tianyancha.py --output data/results/tianyancha.json --company "公司名"

提取策略：天眼查 DOM class 为动态 hash，故以「页面文本 + 正则」为主提取，
不依赖易变的 CSS 选择器，联合大调整时可再精调。
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
PLATFORM = "天眼查"
SEARCH_URL = "https://www.tianyancha.com/search?key={}"
LOGIN_PAGE = "https://www.tianyancha.com/login"
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".tianyancha_scraper_profile")

COMPANY_QUERIES = settings.TARGET_COMPANIES
DELAY_BETWEEN_COMPANIES = (6.0, 12.0)

# 统一社会信用代码正则（18位）
_USCC_RE = re.compile(r"[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}")
# 邮箱正则
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# 电话正则（固话/手机，含脱敏星号）
_PHONE_RE = re.compile(r"(?:\+?86[-\s]?)?(?:1[3-9]\d{9}|0\d{2,3}[-\s]?\d{7,8})(?:[-\s]?\d{1,5})?")
# 网址正则
_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9]{0,62}(?:\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+(?:/[^\s]*)?")


def _is_logged_in(page):
    """登录检测：访问搜索页，若被重定向到登录页或页面含'登录/注册'则视为未登录。
    天眼查现在未登录会被重定向到登录页，必须登录才能采集。"""
    try:
        page.goto(SEARCH_URL.format("测试公司"), wait_until="domcontentloaded", timeout=30000)
        human_sleep((1.5, 3.0))
        # 被重定向到登录页，说明未登录
        if "login" in page.url:
            return False
        # 页面内容含"登录/注册"且无用户信息，说明未登录
        try:
            txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
            if "登录/注册" in txt and "我的" not in txt and "退出" not in txt:
                return False
        except Exception:
            pass
        return True
    except Exception:
        return False


class TianyanchaCrawler:
    """天眼查平台采集器（联系池）。run() 返回联系池行列表。"""

    platform = PLATFORM
    channel = "contact"

    def __init__(self, companies=None, max_per_company=1):
        self.companies = [c for c in (companies or COMPANY_QUERIES) if c]
        self.max_per_company = max(1, max_per_company)
        self.rows = []

    def run(self, login_timeout=300):
        if not self.companies:
            print("天眼查采集器：未配置待查询公司（用 --company 传入或改 COMPANY_QUERIES）。")
            return []

        print("=" * 50)
        print(f"天眼查采集器：待查询 {len(self.companies)} 家公司")
        print(f"登录态目录：{PROFILE_DIR}")
        print("=" * 50)

        with sync_playwright() as p:
            context, used_channel = launch_browser_context(p, PROFILE_DIR, viewport=H.VIEWPORT)
            # 天眼查用纯净浏览器：不注入 stealth、不拦截资源，避免登录页二维码加载失败/无法交互
            page = context.pages[0] if context.pages else context.new_page()

            # 登录检测（天眼查现在未登录会被重定向到登录页，必须登录）
            if not _is_logged_in(page):
                print("\n检测到访问异常，尝试引导登录...")
                page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
                print("请在浏览器中登录（登录后电话等字段更完整），脚本 60 秒后自动继续...")
                time.sleep(60)

            for idx, company in enumerate(self.companies):
                try:
                    self._crawl_company(page, company)
                except Exception as e:
                    print(f"  [天眼查] 采集「{company}」出错：{e}")

                if idx < len(self.companies) - 1:
                    wait_sec = H._skewed_random(*DELAY_BETWEEN_COMPANIES)
                    print(f"  等待 {wait_sec:.1f} 秒后采集下一家...")
                    wait_end = time.time() + wait_sec
                    while time.time() < wait_end:
                        if random.random() < 0.5:
                            move_mouse_human(page)
                        if random.random() < 0.3:
                            random_keyboard_activity(page)
                        human_sleep((1.0, 2.0))

            context.close()
        return self.rows

    def _crawl_company(self, page, company):
        # 1. 搜索
        url = SEARCH_URL.format(urllib.parse.quote(company))
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        human_sleep(H.DELAY_AFTER_SEARCH)
        move_mouse_human(page)

        if self._has_verify(page):
            print(f"  [天眼查] 「{company}」触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 2. 取第一条匹配公司
        links = self._firm_links(page)
        if not links:
            print(f"  [天眼查] 「{company}」未找到匹配公司，跳过。")
            return
        pick = links[0]

        # 3. 进详情页
        page.goto(pick["href"], wait_until="domcontentloaded", timeout=45000)
        human_sleep(H.DELAY_PAGE_LOAD)
        if random.random() < 0.5:
            random_hover(page)
        if random.random() < 0.3:
            random_click_blank(page)
        if self._has_verify(page):
            print(f"  [天眼查] 详情页触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 4. 提取工商字段（文本提取为主）
        info = self._extract_detail(page)
        if not info.get("统一社会信用代码") and not info.get("公司邮箱"):
            print(f"  [天眼查] 「{company}」详情页未提取到有效字段，跳过。")
            return

        row = self._to_contact_row(info, company, pick["name"])
        self.rows.append(row)
        print(f"  [天眼查] 「{pick['name']}」→ 电话 {row['联系电话'] or '无/脱敏'} / 邮箱 {row['公司邮箱'] or '无'}")

    def _firm_links(self, page):
        """搜索结果页提取 /company/{id} 公司链接（带名称）。"""
        links = page.query_selector_all("a")
        out = []
        for a in links:
            try:
                href = a.get_attribute("href") or ""
                if "/company/" in href and "tianyancha.com" in href:
                    name = (a.text_content() or "").strip()
                    if not name or len(name) < 2:
                        continue
                    out.append({"name": name, "href": href})
                    if len(out) >= self.max_per_company:
                        break
            except Exception:
                continue
        return out

    def _extract_detail(self, page):
        """详情页提取：以页面文本 + 正则为主，不依赖动态 class。"""
        info = {}
        try:
            # 取页面纯文本（压缩空白）
            full = page.evaluate("() => document.body.innerText")
            full = re.sub(r"[ \t]+", " ", full)
        except Exception:
            full = ""

        if not full:
            return info

        # ---- 统一社会信用代码 ----
        m = _USCC_RE.search(full)
        if m:
            info["统一社会信用代码"] = m.group(0)

        # ---- 邮箱 ----
        m = _EMAIL_RE.search(full)
        if m and "example.com" not in m.group(0):
            info["公司邮箱"] = m.group(0)

        # ---- 电话（取"电话"标签后第一个） ----
        phone = self._extract_label_value(full, "电话")
        if phone:
            # 清理：只保留电话部分
            pm = _PHONE_RE.search(phone)
            if pm:
                info["联系电话"] = pm.group(0)
            elif "****" in phone or "登录查看" in phone:
                info["联系电话"] = phone[:30]  # 脱敏/需登录

        # ---- 法定代表人 ----
        val = self._extract_label_value(full, "法定代表人")
        if val:
            # 取前几个中文字（人名）
            nm = re.search(r"[\u4e00-\u9fa5·]{2,8}", val)
            if nm:
                info["法定代表人"] = nm.group(0)

        # ---- 注册资本 ----
        val = self._extract_label_value(full, "注册资本")
        if val:
            info["注册资本"] = val[:30]

        # ---- 成立日期 ----
        val = self._extract_label_value(full, "成立日期")
        if val:
            dm = re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", val)
            if dm:
                info["成立日期"] = dm.group(0)

        # ---- 地址 ----
        val = self._extract_label_value(full, "地址")
        if val:
            info["注册地址"] = val[:80]

        # ---- 网址 ----
        val = self._extract_label_value(full, "网址")
        if val:
            um = _URL_RE.search(val)
            if um:
                info["公司官网"] = um.group(0)

        # ---- 国标行业 ----
        val = self._extract_label_value(full, "国标行业")
        if val:
            info["所属行业"] = val[:30]

        # ---- 企业规模 ----
        val = self._extract_label_value(full, "企业规模")
        if val:
            info["企业规模"] = val[:10]

        # ---- 融资轮次（从简介中提取，如"已于2021年完成了战略融资"） ----
        fm = re.search(r"完成了?([\u4e00-\u9fa5]{2,8}?融资|IPO|上市)", full)
        if fm:
            info["融资轮次"] = fm.group(1)

        return info

    @staticmethod
    def _extract_label_value(text, label):
        """从文本中提取「label：值」或「label：\n值」格式的值部分。
        支持值在换行后的情况（天眼查详情页很多字段值在次行）。
        取 label 后到下一个已知标签/换行前的文本。"""
        STOP_WORDS = ["法定代表人", "注册资本", "成立日期", "电话", "邮箱", "地址", "网址",
                       "国标行业", "企业规模", "统一社会信用代码", "关联企业", "更多",
                       "附近企业", "同电话企业", "公众号", "员工人数", "简介", "企业集团"]

        def _clean(val):
            """清理值：去掉混入的下一个标签和噪音词。"""
            val = val.strip()
            for stop in STOP_WORDS:
                idx = val.find(stop)
                if idx > 0:
                    val = val[:idx].strip()
            return val

        # 1. 先尝试同行匹配：label：值（值在同一行）
        pattern = re.escape(label) + r"[：:]\s*([^\n\r]{1,100}?)(?=\s{2,}|[\u4e00-\u9fa5]{2,6}[：:]|$)"
        m = re.search(pattern, text)
        if m:
            val = _clean(m.group(1))
            if val and len(val) >= 1:
                return val

        # 2. 跨行匹配：label：\n值（值在次行，天眼查常见格式）
        pattern2 = re.escape(label) + r"[：:]\s*\n\s*([^\n\r]{1,100}?)(?=\n|$)"
        m2 = re.search(pattern2, text)
        if m2:
            val = _clean(m2.group(1))
            if val and len(val) >= 1:
                return val

        return ""

    def _has_verify(self, page):
        try:
            title = page.title()
            url = page.url
            return ("验证" in title) or ("安全" in title) or ("captcha" in url.lower()) or ("verify" in url.lower())
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
        }


def main():
    parser = argparse.ArgumentParser(description="天眼查平台采集器（联系池）")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（worker 并行模式）")
    parser.add_argument("--company", action="append", default=None, help="待查询公司名（可多次）")
    parser.add_argument("--max-per-company", type=int, default=1, help="每公司取前 N 条结果")
    args = parser.parse_args()

    companies = args.company if args.company else COMPANY_QUERIES
    crawler = TianyanchaCrawler(companies=companies, max_per_company=args.max_per_company)
    rows = crawler.run()

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"天眼查结果已写入：{args.output}（{len(rows)} 条）")
    else:
        if rows:
            print(f"\n天眼查采集完成，联系池 {len(rows)} 条：")
            for r in rows:
                print(f"  - {r['公司名']} | 电话 {r['联系电话']} | 邮箱 {r['公司邮箱']}")
        else:
            print("\n未采集到任何数据。")


if __name__ == "__main__":
    main()

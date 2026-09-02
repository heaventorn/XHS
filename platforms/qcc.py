# -*- coding: utf-8 -*-
"""platforms/qcc.py — 企查查平台采集器（联系池 · 完整版）

能力：
  - 持久登录态复用（profile 目录保存 cookies，登录一次后续免登录）
  - 逐个公司搜索 → 进入详情页 → 提取工商字段（信用代码/法人/电话/邮箱/官网/地址）
  - 底部填充联系池「公司档案」（与 core.aggregate 对接）

合规边界：人工登录 / 人工过验证码 / 低频随机访问（绿区）；
不破解验证码、不建 IP 池高频访问（刑法 285 红线，不碰）。

运行方式：
  独立测试：  python platforms/qcc.py --company "公司名" --company "公司2"
  Worker：   python platforms/qcc.py --output data/results/qcc.json --company "公司名"

选择器依据企查查真实 DOM（已验证）：
  - 搜索：GET https://www.qcc.com/web/search?key={公司}
  - 顶部信息区：.normal-company-info-part .rline（label:值 对：电话/邮箱/官网/信用代码/法人）
  - 基本信息表：table.app-data-table tr（LBL|VAL 对：注册地址/注册资本/成立日期等）
"""
import os
import sys
import json
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

human_sleep = H.human_sleep
move_mouse_human = H.move_mouse_human
random_hover = H.random_hover
random_click_blank = H.random_click_blank
random_keyboard_activity = H.random_keyboard_activity

# ==================== 平台配置 ====================
PLATFORM = "企查查"
SEARCH_URL = "https://www.qcc.com/web/search?key={}"
LOGIN_PAGE = "https://www.qcc.com/weblogin"

# 持久化登录态目录（保存 cookies，登录一次复用）
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".qcc_scraper_profile")

# 待查询公司（也可运行时 --company 传入）
COMPANY_QUERIES = []

# 公司间延迟（低频，企查查风控较严）
DELAY_BETWEEN_COMPANIES = (8.0, 15.0)


def _is_logged_in(page):
    """登录检测：访问搜索页 URL，若跳转到 weblogin 说明未登录。"""
    try:
        page.goto(SEARCH_URL.format("测试"), wait_until="domcontentloaded", timeout=30000)
        human_sleep((1.5, 3.0))
        return "weblogin" not in page.url
    except Exception:
        return False


class QCCCrawler:
    """企查查平台采集器（联系池）。run() 返回联系池行列表。"""

    platform = PLATFORM
    channel = "contact"  # 输出到联系池

    def __init__(self, companies=None, max_per_company=1):
        self.companies = [c for c in (companies or COMPANY_QUERIES) if c]
        self.max_per_company = max(1, max_per_company)
        self.rows = []

    # ---------- 主运行 ----------
    def run(self, login_timeout=300):
        """采集全部待查公司，返回联系池行列表。"""
        if not self.companies:
            print("企查查采集器：未配置待查询公司（用 --company 传入或改 COMPANY_QUERIES）。")
            return []

        print("=" * 50)
        print(f"企查查采集器：待查询 {len(self.companies)} 家公司")
        print(f"登录态目录：{PROFILE_DIR}")
        print("=" * 50)

        with sync_playwright() as p:
            context, used_channel = launch_browser_context(p, PROFILE_DIR, viewport=H.VIEWPORT)
            network.install_resource_route(context)

            page = context.pages[0] if context.pages else context.new_page()
            # stealth 注入 + 真实 UA
            real_ua = network.prepare_context(context, page, S.build_stealth_script, "")

            # ---- 登录检测 / 引导 ----
            if not _is_logged_in(page):
                print("\n" + "!" * 50)
                print("检测到未登录！请在弹出浏览器中扫码 / 微信 / 短信登录")
                print("脚本会自动检测登录状态，登录成功后自动继续...")
                print("!" * 50)
                page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
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
                    print(f"  [企查查] 采集「{company}」出错：{e}")

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

    # ---------- 单公司采集 ----------
    def _crawl_company(self, page, company):
        # 1. 搜索
        url = SEARCH_URL.format(urllib.parse.quote(company))
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        human_sleep(H.DELAY_AFTER_SEARCH)
        move_mouse_human(page)

        if "weblogin" in page.url:
            print(f"  [企查查] 「{company}」登录态失效，跳过。")
            return
        if self._has_verify(page):
            print(f"  [企查查] 「{company}」触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 2. 取第一条匹配公司
        links = self._firm_links(page)
        if not links:
            print(f"  [企查查] 「{company}」未找到匹配公司，跳过。")
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
            print(f"  [企查查] 详情页触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 4. 提取工商字段
        info = self._extract_detail(page)
        if not info.get("统一社会信用代码") and not info.get("电话"):
            print(f"  [企查查] 「{company}」详情页未提取到有效字段，跳过。")
            return

        row = self._to_contact_row(info, company)
        self.rows.append(row)
        print(f"  [企查查] 「{pick['name']}」→ 电话 {row['联系电话'] or '无'} / 邮箱 {row['公司邮箱'] or '无'}")

    # ---------- 页面解析 ----------
    def _firm_links(self, page):
        """搜索结果页提取 /firm/{hash}.html 公司链接（带名称）。"""
        links = page.query_selector_all("a")
        out = []
        for a in links:
            try:
                href = a.get_attribute("href") or ""
                if "/firm/" in href and ".html" in href:
                    name = (a.text_content() or "").strip()
                    if not name or len(name) < 2:
                        continue
                    full = href if href.startswith("http") else "https://www.qcc.com" + href
                    out.append({"name": name, "href": full})
                    if len(out) >= self.max_per_company:
                        break
            except Exception:
                continue
        return out

    def _extract_detail(self, page):
        """详情页提取：顶部 rline 区（电话/邮箱/官网/信用代码/法人）+ 基本信息表。"""
        info = {}
        # ---- 顶部信息区 .rline：label:值 ----
        try:
            rlines = page.query_selector_all(".normal-company-info-part .rline")
            for row in rlines:
                try:
                    le = row.query_selector("span.f .need-copy-field")
                    ve = row.query_selector("span.val")
                    if not le:
                        continue
                    label = (le.text_content() or "").strip().rstrip("：:")
                    val = (ve.text_content() or "").strip() if ve else ""
                    if label and val:
                        info[label] = val
                except Exception:
                    continue
        except Exception:
            pass

        # ---- 基本信息表 app-data-table：LBL|VAL 对 ----
        try:
            trs = page.query_selector_all("table.app-data-table tr")
            pending = []
            for tr in trs:
                try:
                    tds = tr.query_selector_all("td")
                    for td in tds:
                        cls = td.get_attribute("class") or ""
                        txt = (td.text_content() or "").strip()
                        if "tb" in cls:
                            pending.append(txt)
                        else:
                            if pending and txt:
                                info[pending.pop(0)] = txt
                except Exception:
                    continue
        except Exception:
            pass

        return info

    def _has_verify(self, page):
        """检测是否触发安全验证（页面标题含验证/安全）。"""
        try:
            title = page.title()
            return ("验证" in title) or ("安全" in title)
        except Exception:
            return False

    def _wait_verify_pass(self, page, company, timeout=300):
        """安全验证等待：提示人工处理，轮询直到通过或超时。"""
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

    # ---------- 结果映射 ----------
    def _to_contact_row(self, info, company):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        return {
            "公司名": info.get("企业名称") or company,
            "统一社会信用代码": info.get("统一社会信用代码", ""),
            "所属板块": "",  # 由主程序按搜索关键词/来源补，或后续人工填
            "融资轮次": "",  # 企查查创投库在独立 tab，后续可扩展
            "法定代表人/董监高": info.get("法定代表人", ""),
            "联系电话": info.get("电话", ""),
            "公司邮箱": info.get("邮箱", ""),
            "注册地址": info.get("注册地址") or info.get("地址", ""),
            "公司官网": info.get("官网", ""),
            "融资新闻链接": "",
            "联系人角色": "",  # 待人工补（CFO/融资负责人）
            "跟进状态": "待联系",
            "采集时间": now,
        }


def main():
    parser = argparse.ArgumentParser(description="企查查平台采集器（联系池）")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（worker 并行模式）")
    parser.add_argument("--company", action="append", default=None, help="待查询公司名（可多次）")
    parser.add_argument("--max-per-company", type=int, default=1, help="每公司取前 N 条结果")
    args = parser.parse_args()

    companies = args.company if args.company else COMPANY_QUERIES
    crawler = QCCCrawler(companies=companies, max_per_company=args.max_per_company)
    rows = crawler.run()

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"企查查结果已写入：{args.output}（{len(rows)} 条）")
    else:
        from core.storage import CONTACT_HEADERS
        if rows:
            print(f"\n企查查采集完成，联系池 {len(rows)} 条：")
            for r in rows:
                print(f"  - {r['公司名']} | 电话 {r['联系电话']} | 邮箱 {r['公司邮箱']}")
        else:
            print("\n未采集到任何数据。")


if __name__ == "__main__":
    main()

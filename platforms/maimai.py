# -*- coding: utf-8 -*-
"""platforms/maimai.py — 脉脉平台采集器（线索池 · 高管人脉）

能力：
  - 持久登录态复用（profile 目录保存 cookies，登录一次后续免登录）
  - 脉脉完全需要登录（未登录搜索即跳转登录页）
  - 按公司名搜索 → 提取该公司员工/高管名片（姓名/职位/公司）
  - 重点筛选 CFO / 董秘 / 融资负责人 / 财务总监 / 副总裁 等关键角色
  - 输出线索池（拿到人名+职位后，联系方式留空待人工补）

脉脉是国内最大职场实名社交平台，核心价值是「定位到具体的人」，
弥补工商平台只能拿到公司总机的不足。

合规边界：人工登录 / 人工过验证码 / 低频随机访问（绿区）；
不破解验证码、不建 IP 池高频访问（刑法 285 红线，不碰）。

运行方式：
  独立测试：  python platforms/maimai.py --company "公司名" --company "公司2"
  Worker：   python platforms/maimai.py --output data/results/maimai.json --company "公司名"

提取策略：脉脉 DOM 为动态结构（Next.js），以「页面文本 + 正则」为主提取，
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
PLATFORM = "脉脉"
# 脉脉搜索中心 URL（type=feed 为内容/动态搜索，结果中含人员名片）
SEARCH_URL = "https://maimai.cn/web/search_center?type=feed&query={}"
LOGIN_PAGE = "https://maimai.cn/platform/login"
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".maimai_scraper_profile")

COMPANY_QUERIES = settings.TARGET_COMPANIES
DELAY_BETWEEN_COMPANIES = (10.0, 18.0)

# 关键职位关键词（CFO/融资负责人等，命中则优先保留）
_KEY_POSITIONS = (
    "CFO", "首席财务官", "财务总监", "财务负责人", "董秘", "董事会秘书",
    "融资负责人", "融资总监", "资本总监", "投资者关系", "IR总监", "IR经理",
    "副总裁", "VP", "高级副总裁", "SVP", "执行副总裁", "EVP",
    "联合创始人", "合伙人", "总经理", "CEO", "首席执行官", "COO", "首席运营官",
)
# 排除职位（普通员工，不保留）
_EXCLUDE_POSITIONS = (
    "实习生", "实习", "助理", "专员", "主管", "经理", "工程师", "设计师",
    "产品经理", "运营", "销售", "市场", "HR", "人事", "行政", "前台",
    "客服", "顾问", "分析师", "研究员", "学生",
)
# 非人员噪音词（地点、导航、通用词，提取人员时排除）
_NOISE_NAMES = (
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安",
    "重庆", "苏州", "天津", "长沙", "郑州", "青岛", "大连", "厦门", "宁波",
    "搜索结果", "相关人员", "相关公司", "首页", "登录", "注册", "更多",
    "取消", "确定", "关闭", "展开", "收起", "查看", "详情", "简介",
    "动态", "文章", "问答", "职位", "公司", "学校", "技能", "标签",
    "全部", "筛选", "排序", "推荐", "热门", "最新", "加载", "没有",
)


def _is_logged_in(page):
    """登录检测：访问搜索页，若跳转到 platform/login 则未登录。"""
    try:
        page.goto(SEARCH_URL.format("测试"), wait_until="domcontentloaded", timeout=30000)
        human_sleep((1.5, 3.0))
        return "platform/login" not in page.url and "login" not in page.url
    except Exception:
        return False


class MaimaiCrawler:
    """脉脉平台采集器（线索池 · 高管人脉）。run() 返回线索池行列表。"""

    platform = PLATFORM
    channel = "clue"

    def __init__(self, companies=None, max_per_company=10):
        self.companies = [c for c in (companies or COMPANY_QUERIES) if c]
        self.max_per_company = max(1, max_per_company)
        self.rows = []

    def run(self, login_timeout=300):
        if not self.companies:
            print("脉脉采集器：未配置待查询公司（用 --company 传入或改 COMPANY_QUERIES）。")
            return []

        print("=" * 50)
        print(f"脉脉采集器：待查询 {len(self.companies)} 家公司")
        print(f"登录态目录：{PROFILE_DIR}")
        print("=" * 50)

        with sync_playwright() as p:
            context, used_channel = launch_browser_context(p, PROFILE_DIR, viewport=H.VIEWPORT)
            network.install_resource_route(context)
            page = context.pages[0] if context.pages else context.new_page()
            real_ua = network.prepare_context(context, page, S.build_stealth_script, "")

            # ---- 登录检测 / 引导（脉脉必须登录） ----
            if not _is_logged_in(page):
                print("\n" + "!" * 50)
                print("检测到未登录！脉脉必须登录才能搜索和查看人员名片。")
                print("请在弹出浏览器中完成登录（扫码 / 手机号+验证码均可），")
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
                    print(f"  [脉脉] 采集「{company}」出错：{e}")

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
        # 1. 搜索公司
        url = SEARCH_URL.format(urllib.parse.quote(company))
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        human_sleep(H.DELAY_AFTER_SEARCH)
        move_mouse_human(page)

        if "login" in page.url:
            print(f"  [脉脉] 「{company}」登录态失效，跳过。")
            return
        if self._has_verify(page):
            print(f"  [脉脉] 「{company}」触发安全验证，等待人工处理...")
            self._wait_verify_pass(page, company)

        # 2. 滚动加载更多结果（脉脉是无限滚动）
        self._scroll_load(page, max_scrolls=3)

        # 3. 提取人员名片
        persons = self._extract_persons(page, company)
        if not persons:
            print(f"  [脉脉] 「{company}」未找到相关人员，跳过。")
            return

        # 4. 筛选关键职位 + 去重
        key_persons = [p for p in persons if self._is_key_position(p.get("职位", ""))]
        # 如果关键职位少，补充普通高管（排除基层）
        if len(key_persons) < 3:
            for p in persons:
                if p not in key_persons and not self._is_exclude_position(p.get("职位", "")):
                    key_persons.append(p)
                    if len(key_persons) >= self.max_per_company:
                        break

        key_persons = key_persons[:self.max_per_company]
        for p in key_persons:
            row = self._to_clue_row(p, company)
            self.rows.append(row)
            print(f"  [脉脉] 「{company}」→ {p['姓名']} / {p['职位'] or '未知职位'}")

    def _scroll_load(self, page, max_scrolls=3):
        """脉脉无限滚动，滚动加载更多结果。"""
        for _ in range(max_scrolls):
            try:
                page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                human_sleep((1.5, 3.0))
                if random.random() < 0.5:
                    move_mouse_human(page)
            except Exception:
                break

    def _extract_persons(self, page, company):
        """从搜索结果页提取人员名片（姓名/职位/公司/链接）。
        策略：遍历页面中的链接，匹配人员 profile URL，提取附近文本。"""
        persons = []
        seen_names = set()
        try:
            full = page.evaluate("() => document.body.innerText") or ""
        except Exception:
            full = ""

        # 策略1：从页面文本中提取「姓名 + 职位 + 公司」模式
        # 脉脉搜索结果中人员卡片通常格式：姓名 \n 职位 @ 公司 \n 地点
        lines = [l.strip() for l in full.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            # 姓名必须是 2-5 个中文字（含·），且不是噪音词
            name_match = re.match(r"^[\u4e00-\u9fa5·]{2,5}$", line)
            if not name_match:
                continue
            name = line
            if name in _NOISE_NAMES:
                continue
            if i + 1 >= len(lines):
                continue
            position_line = lines[i + 1]
            # 职位行必须含 @（脉脉标准格式）或职位关键词，否则跳过
            if "@" not in position_line and not any(kw in position_line for kw in _KEY_POSITIONS):
                continue
            position = position_line
            comp = company
            if "@" in position_line:
                parts = position_line.split("@", 1)
                position = parts[0].strip()
                comp = parts[1].strip()
            # 过滤：职位太短/纯数字/噪音
            if len(position) < 2 or position.isdigit() or position in _NOISE_NAMES:
                continue
            if name not in seen_names:
                seen_names.add(name)
                persons.append({
                    "姓名": name,
                    "职位": position,
                    "公司": comp,
                    "链接": "",
                })

        # 策略2：从链接中提取人员 profile（补充链接）
        try:
            links = page.query_selector_all("a")
            person_urls = []
            for a in links:
                try:
                    href = a.get_attribute("href") or ""
                    if ("/web/user/" in href or "/ent/user/" in href or
                        "/user/" in href and "maimai" in href):
                        name = (a.text_content() or "").strip()
                        if name and 2 <= len(name) <= 10:
                            person_urls.append({"name": name, "href": href})
                except Exception:
                    continue
            # 把链接补充到已提取的人员
            for pu in person_urls:
                for p in persons:
                    if p["姓名"] == pu["name"] and not p["链接"]:
                        p["链接"] = pu["href"] if pu["href"].startswith("http") else "https://maimai.cn" + pu["href"]
                        break
        except Exception:
            pass

        return persons

    @staticmethod
    def _is_key_position(position):
        """判断是否为关键职位（CFO/融资负责人等）。"""
        if not position:
            return False
        return any(kw in position for kw in _KEY_POSITIONS)

    @staticmethod
    def _is_exclude_position(position):
        """判断是否为基层职位（排除）。"""
        if not position:
            return False
        return any(kw in position for kw in _EXCLUDE_POSITIONS)

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

    def _to_clue_row(self, person, company):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        return {
            "标题": f"{person['姓名']} - {person['职位'] or '未知职位'}",
            "正文": f"脉脉平台人员名片：{person['姓名']}，{person['职位'] or '未知职位'}，{person['公司'] or company}",
            "作者": person["姓名"],
            "作者ID": "",
            "内容链接": person["链接"] or "",
            "点赞数": "",
            "评论数": "",
            "收藏数": "",
            "发布时间": "",
            "来源平台": PLATFORM,
            "关联公司": person.get("公司") or company,
            "采集时间": now,
            # 脉脉特有附加字段
            "姓名": person["姓名"],
            "职位": person["职位"],
            "是否关键职位": "是" if self._is_key_position(person["职位"]) else "否",
        }


def main():
    parser = argparse.ArgumentParser(description="脉脉平台采集器（线索池 · 高管人脉）")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（worker 并行模式）")
    parser.add_argument("--company", action="append", default=None, help="待查询公司名（可多次）")
    parser.add_argument("--max-per-company", type=int, default=10, help="每公司最多保留人数")
    args = parser.parse_args()

    companies = args.company if args.company else COMPANY_QUERIES
    crawler = MaimaiCrawler(companies=companies, max_per_company=args.max_per_company)
    rows = crawler.run()

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"脉脉结果已写入：{args.output}（{len(rows)} 条）")
    else:
        if rows:
            print(f"\n脉脉采集完成，线索池 {len(rows)} 条：")
            for r in rows:
                print(f"  - {r['姓名']} | {r['职位']} | {r['关联公司']} | 关键职位:{r['是否关键职位']}")
        else:
            print("\n未采集到任何数据。")


if __name__ == "__main__":
    main()

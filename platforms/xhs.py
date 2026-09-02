# -*- coding: utf-8 -*-
"""platforms/xhs.py — 小红书平台采集器（接入大爬虫框架）

从原单文件脚本瘦身而来：平台特有逻辑保留（搜索 URL、卡片选择器、
详情页正文提取、随机互动、关键词采集循环），伪装层统一从 core 导入。

输出行结构对齐 core.storage 的「线索池」Sheet（联系方式留空待人工补）。
"""
import os
import re
import sys
import time
import random
from urllib.parse import urljoin, quote

from playwright.sync_api import sync_playwright

# ---- 公共核心 ----
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import humanize as H
from core import network, extract as X, blacklist as B
from core import adaptive, autothrottle, checkpoint, proxy
from core.browser import launch_browser_context
from core.storage import CLUE_HEADERS

# 从 humanize 复引用常用函数（保持代码可读性）
human_sleep = H.human_sleep
move_mouse_human = H.move_mouse_human
random_hover = H.random_hover
random_click_blank = H.random_click_blank
random_keyboard_activity = H.random_keyboard_activity
human_scroll = H.human_scroll
human_type = H.human_type
_skewed_random = H._skewed_random
VIEWPORT = H.VIEWPORT
DELAY_PAGE_LOAD = H.DELAY_PAGE_LOAD
DELAY_AFTER_SEARCH = H.DELAY_AFTER_SEARCH
DELAY_AFTER_SCROLL = H.DELAY_AFTER_SCROLL
DELAY_BETWEEN_KEYWORDS = H.DELAY_BETWEEN_KEYWORDS
DELAY_MOUSE_MOVE = H.DELAY_MOUSE_MOVE
DELAY_READ_PAUSE = H.DELAY_READ_PAUSE

# 通用提取 / 黑名单（沿用 core 的默认配置，可在本模块覆盖）
extract_note_id = X.extract_note_id
clean_author_name = X.clean_author_name
extract_publish_time = X.extract_publish_time
is_within_two_years = X.is_within_two_years
is_blacklisted = B.is_blacklisted
is_irrelevant_content = B.is_irrelevant_content
IRRELEVANT_KEYWORDS = B.IRRELEVANT_KEYWORDS
BLACKLIST_AUTHORS = B.BLACKLIST_AUTHORS
BLACKLIST_IDS = B.BLACKLIST_IDS


# ==================== 平台配置 ====================
PLATFORM = "小红书"
KEYWORDS = [
    "FA", "寻找FA", "一级市场", "融资顾问", "FA合作", "FA建联",
    "FA交流", "找FA", "一级市场融资", "FA服务", "FA业务",
]
MAX_PER_KEYWORD = 10
FILTER_WITHIN_TWO_YEARS = True
MAX_SCROLLS = 4
MAX_TOTAL_NOTES = 60
PROXY_URL = ""

# 持久化浏览器用户目录：保存登录态，避免每次重新扫码
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".xhs_scraper_profile")

# 帖子卡片链接选择器：兼容新旧格式，用 xsec_source=pc_search 区分搜索结果与推荐流
NOTE_LINK_SELECTOR = (
    "a[href*='/explore/'][href*='xsec_source=pc_search'], "
    "a[href*='/search_result/'], "
    "a[href*='/discovery/item/']"
)

# 卡片内常见发布时间元素（启发式；定位不到时回退到正则从卡片文本提取）
TIME_SELECTORS = [
    "span[class*='date']",
    "span[class*='time']",
    "time",
    "div[class*='date']",
]


# ==================== 采集器类 ====================
class XHSCrawler:
    """小红书平台采集器。run() 返回线索池行列表（对齐 core.storage 的线索池字段）。"""

    platform = PLATFORM

    def __init__(self, keywords=None, max_per_keyword=None, proxy_url="", live_sink=None,
                 resume=True, checkpoint_dir=None):
        """
        :param keywords: 覆盖默认关键词
        :param max_per_keyword: 覆盖每词上限
        :param proxy_url: 代理
        :param live_sink: 实时落盘回调 callable(rows)，采到一条立即调用
        :param resume: 是否启用断点续爬（中断后跳过已完成关键词/帖子）
        :param checkpoint_dir: 检查点目录（默认 <框架根>/data/checkpoints）
        """
        self.keywords = list(keywords or KEYWORDS)
        self.max_per_keyword = max_per_keyword or MAX_PER_KEYWORD
        self.proxy_url = proxy_url or PROXY_URL
        self.live_sink = live_sink
        self.resume = resume
        if checkpoint_dir is None:
            checkpoint_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "checkpoints")
        self.checkpoint_dir = checkpoint_dir
        self._all_rows = []
        self._seen_ids = set()
        # Scrapling 整合：断点续爬 / 流式导出 / 自适应节流 / 自适应定位 / 代理轮换
        self._ck = None
        self._exporter = None
        self.throttle = autothrottle.AutoThrottle(start_delay=3.0, max_delay=45.0)
        self.locator = adaptive.AdaptiveLocator()

    # ---------- 搜索 ----------
    def search_keyword(self, page, keyword):
        """搜索关键词：优先直连搜索结果 URL（带 Referer 伪装），失败退回搜索框。"""
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}"
        try:
            network.goto_with_referer(page, search_url)
        except Exception:
            print(f"  警告：搜索 URL 直连失败，尝试首页搜索框...")
            try:
                page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
                human_sleep(DELAY_PAGE_LOAD)
                if random.random() < 0.5:
                    random_hover(page)
                if random.random() < 0.3:
                    random_click_blank(page)
                search_input = page.wait_for_selector(
                    "input#search-input, input[placeholder*='搜索'], input[placeholder*='搜'], input[type='search']",
                    timeout=10000,
                )
                if search_input:
                    box = search_input.bounding_box()
                    if box:
                        move_mouse_human(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        human_sleep(DELAY_MOUSE_MOVE)
                        search_input.click()
                        human_sleep((0.3, 0.6))
                    search_input.fill("")
                    human_type(search_input, keyword)
                    human_sleep((0.5, 1.2))
                    search_input.press("Enter")
                else:
                    network.goto_with_referer(page, search_url)
            except Exception:
                print(f"  警告：首页搜索框也失败，关键词「{keyword}」将尝试直接打开搜索页")

        human_sleep(DELAY_AFTER_SEARCH)
        try:
            page.wait_for_selector(NOTE_LINK_SELECTOR, timeout=15000)
        except Exception:
            print(f"  警告：等待搜索结果超时")
        human_sleep((1.0, 2.5))
        move_mouse_human(page)
        if random.random() < 0.4:
            random_hover(page)

    # ---------- 详情页正文 ----------
    def extract_note_content_with_disguise(self, context, note_url):
        """随机打开帖子详情页读正文，带真人浏览伪装。失败/风控返回空串。"""
        detail_page = None
        try:
            # Referer 链：从当前搜索结果页"点击"进入详情
            referer_url = ""
            try:
                for pg in reversed(context.pages):
                    u = (pg.url or "")
                    if u and "about:blank" not in u:
                        referer_url = u
                        break
            except Exception:
                pass

            detail_page = context.new_page()
            if referer_url:
                try:
                    detail_page.set_extra_http_headers({"Referer": referer_url})
                except Exception:
                    pass

            try:
                detail_page.goto(note_url, wait_until="domcontentloaded", timeout=12000)
            except Exception:
                return ""

            # 风控检测
            try:
                cur_url = detail_page.url or ""
                if any(k in cur_url for k in ("website-login", "error_code", "verify")):
                    human_sleep((8.0, 15.0))
                    if self.throttle:
                        self.throttle.record("www.xiaohongshu.com", 0.0, ok=False)  # 被限→退避
                    return ""
                page_text = detail_page.inner_text("body")[:500]
                if any(kw in page_text for kw in ["访问频繁", "操作频繁", "安全验证", "请完成验证",
                                                   "滑动验证", "行为异常", "暂时无法", "触发风控"]):
                    human_sleep((8.0, 15.0))
                    if self.throttle:
                        self.throttle.record("www.xiaohongshu.com", 0.0, ok=False)  # 被限→退避
                    return ""
            except Exception:
                pass

            content_selectors = [
                "div[class*='note-content']",
                "div[class*='desc']",
                "div[class*='note-text']",
                "div.note-content",
                "span[class*='content']",
                "div.detail-container",
                "div#detail-desc",
            ]
            try:
                detail_page.wait_for_selector(", ".join(content_selectors), timeout=6000)
            except Exception:
                pass

            # 伪装阅读
            human_sleep((2.5, 6.0))
            scroll_times = random.randint(0, 2)
            for _ in range(scroll_times):
                try:
                    total = random.randint(200, 500)
                    steps = random.randint(3, 6)
                    remaining = total
                    for si in range(steps):
                        if si == steps - 1:
                            step = remaining
                        else:
                            ratio = 1.0 - (si / steps) * 0.6
                            step = int(remaining * ratio / (steps - si))
                            remaining -= step
                        detail_page.mouse.wheel(0, step)
                        time.sleep(random.uniform(0.03, 0.08))
                    human_sleep((0.5, 1.5))
                except Exception:
                    pass
            if random.random() < 0.6:
                try:
                    move_mouse_human(detail_page)
                except Exception:
                    pass

            # 读取正文（取最长匹配，多选择器兜底 + meta 兜底）
            content = ""
            for sel in content_selectors:
                try:
                    el = detail_page.query_selector(sel)
                    if el:
                        text = el.inner_text().strip()
                        if len(text) > len(content):
                            content = text
                        if len(text) >= 20:
                            break
                except Exception:
                    continue
            if not content:
                try:
                    meta = detail_page.query_selector("meta[name='description']")
                    if meta:
                        content = meta.get_attribute("content") or ""
                except Exception:
                    pass
            if content:
                content = re.sub(r"\n{3,}", "\n\n", content).strip()

            human_sleep((0.8, 2.0))
            return content
        except Exception:
            return ""
        finally:
            if detail_page:
                try:
                    detail_page.close()
                except Exception:
                    pass

    # ---------- 滚动采集 ----------
    def scroll_and_collect(self, page, context, keyword, max_count):
        collected = []
        seen_ids = set()
        last_count = 0
        no_new_count = 0
        unknown_kept = 0

        # 防护：确认当前在搜索结果页，被重定向回主页则重新进入
        try:
            cur = page.url or ""
            if "search_result" not in cur:
                print(f"    当前不在搜索结果页（{cur[:60]}），重新进入搜索...")
                network.goto_with_referer(
                    page, f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}")
                human_sleep(DELAY_AFTER_SEARCH)
        except Exception:
            pass

        for scroll_idx in range(MAX_SCROLLS):
            notes = page.query_selector_all(NOTE_LINK_SELECTOR)
            # 自适应定位兜底：主选择器失效（网站改版）时先用指纹重定位，再批量兜底
            if not notes:
                try:
                    self.locator.attach(page)
                    if self.locator.has("note_link"):
                        self.locator.locate("note_link", use_fallback=True)
                    notes = page.query_selector_all(NOTE_LINK_SELECTOR) or page.query_selector_all(
                        "a[href*='/explore/'], a[href*='/search_result/'], a[href*='/discovery/item/']")
                except Exception:
                    pass
            elif self.locator:
                try:
                    self.locator.attach(page)
                    if not self.locator.has("note_link"):
                        self.locator.save("note_link", notes[0])  # 保存首个卡片指纹
                except Exception:
                    pass
            for note_a in notes:
                try:
                    href = note_a.get_attribute("href") or ""
                    full_url = urljoin("https://www.xiaohongshu.com", href)
                    note_id = extract_note_id(full_url)
                    if note_id in seen_ids:
                        continue
                    if self._ck and self._ck.is_done(note_id):
                        continue  # 断点续爬：跳过历史已采帖子
                    title = note_a.inner_text().strip()
                    if not title:
                        continue

                    # 卡片容器：从链接向上找最近的含用户链接的祖先（不依赖固定类名）
                    card = note_a.evaluate_handle(
                        "el => {"
                        "  let n = el;"
                        "  while (n && n !== document.body) {"
                        "    if (n.querySelector && n.querySelector('a[href*=\"/user/profile/\"]')) return n;"
                        "    n = n.parentElement;"
                        "  }"
                        "  return null;"
                        "}"
                    )
                    author_name = ""
                    author_id = ""
                    publish_time = ""
                    card_el = card.as_element() if card else None
                    if card_el:
                        _card_text = card_el.inner_text()
                        publish_time = extract_publish_time(_card_text)
                        if not publish_time:
                            for tsel in TIME_SELECTORS:
                                try:
                                    tel = card_el.query_selector(tsel)
                                    if tel:
                                        _t = tel.inner_text().strip()
                                        if _t:
                                            publish_time = _t
                                            break
                                except Exception:
                                    continue
                        author_a = card_el.query_selector("a[href*='/user/profile/']")
                        if author_a:
                            author_name = clean_author_name(author_a.inner_text())
                            _ahref = author_a.get_attribute("href") or ""
                            _m = re.search(r"/user/profile/([a-zA-Z0-9]+)", _ahref)
                            if _m:
                                author_id = _m.group(1)

                    # 账号黑名单
                    if is_blacklisted(author_name, author_id):
                        print(f"    跳过黑名单账号：{author_name}")
                        continue

                    # 两年内过滤
                    if FILTER_WITHIN_TWO_YEARS:
                        within = is_within_two_years(publish_time)
                        if within is False:
                            continue
                        if within is None and unknown_kept < 3:
                            unknown_kept += 1
                            print(f"    提示：标题「{title[:20]}」发布时间[{publish_time or '未知'}]无法解析，默认保留")

                    # 内容不相关筛选
                    if is_irrelevant_content(title):
                        print(f"    跳过不相关内容：{title[:40]}...")
                        continue

                    seen_ids.add(note_id)

                    # 随机打开详情页（30%）
                    note_content = ""
                    if random.random() < 0.3:
                        note_content = self.extract_note_content_with_disguise(context, full_url)
                        human_sleep((1.5, 4.0))
                    else:
                        human_sleep((0.8, 2.0))

                    collected.append({
                        "来源平台": self.platform,
                        "搜索关键词": keyword,
                        "内容标题": title,
                        "内容链接": full_url,
                        "作者昵称": author_name,
                        "作者ID": author_id,
                        "角色推断": "",
                        "关联公司": "",
                        "匹配板块": "",
                        "联系方式": "",   # 留空待人工补
                        "跟进状态": "待联系",
                        "采集时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "帖子正文": note_content,   # 内部附加字段（不进线索池主表头，落盘时忽略）
                    })

                    # 实时落盘
                    if self.live_sink:
                        self.live_sink(collected)

                    if note_content:
                        print(f"    采集到：{title[:30]}... (已点开·正文{len(note_content)}字)")
                    else:
                        print(f"    采集到：{title[:30]}... (未点开)")

                    if len(collected) >= max_count:
                        return collected
                except Exception:
                    continue

            print(f"  第{scroll_idx + 1}次滚动，已采集 {len(collected)} 条")
            if len(collected) == last_count:
                no_new_count += 1
                if no_new_count >= 3:
                    print("  连续3次无新内容，停止滚动")
                    break
            else:
                no_new_count = 0
            last_count = len(collected)

            human_scroll(page, "down")
            human_sleep(DELAY_AFTER_SCROLL)
            if random.random() < 0.5:
                move_mouse_human(page)
            if random.random() < 0.3:
                random_hover(page)
            if random.random() < 0.15:
                random_click_blank(page)
            if random.random() < 0.2:
                random_keyboard_activity(page)
            if random.random() < 0.12 and len(collected) >= 3:
                self.random_interact_with_note(page)

        return collected

    # ---------- 随机互动（浏览+评论输入不发送） ----------
    def random_interact_with_note(self, page):
        try:
            notes = page.query_selector_all(NOTE_LINK_SELECTOR)
            if not notes:
                return False
            target_notes = [n for n in notes if n.inner_text().strip()]
            if not target_notes:
                return False
            note = random.choice(target_notes)
            title = note.inner_text().strip()[:30]
            print(f"  随机浏览帖子：{title}...")
            box = note.bounding_box()
            if box and box["y"] < VIEWPORT["height"] - 100:
                move_mouse_human(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                human_sleep((0.3, 0.7))
            note.click()
            human_sleep(DELAY_PAGE_LOAD)
            try:
                page.wait_for_selector(
                    "div.note-content, div.detail-container, textarea, input[placeholder*='评论'], input[placeholder*='说点什么']",
                    timeout=12000)
            except Exception:
                pass
            human_sleep((1.0, 2.5))
            move_mouse_human(page)
            human_sleep((0.3, 0.8))
            scroll_times = random.randint(1, 3)
            for _ in range(scroll_times):
                human_scroll(page, "down")
                human_sleep((0.8, 1.8))

            if random.random() < 0.6:
                try:
                    comment_input = page.query_selector(
                        "textarea, input[placeholder*='评论'], input[placeholder*='说点什么'], div[contenteditable='true']"
                    )
                    if comment_input:
                        box = comment_input.bounding_box()
                        if box:
                            move_mouse_human(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            human_sleep((0.3, 0.6))
                        comment_input.click()
                        human_sleep((0.3, 0.7))
                        random_texts = ["mark", "学习了", "谢谢分享", "666", "收藏了",
                                        "有用", "感谢", "m", "1", "看看", "不错"]
                        text = random.choice(random_texts)
                        for char in text:
                            comment_input.type(char, delay=random.randint(80, 220))
                            if random.random() < 0.1:
                                human_sleep((0.2, 0.5))
                        human_sleep((0.5, 1.3))
                        human_sleep((3.0, 7.0))
                        # 逐字删除（模拟人手退格，非 Ctrl+A）
                        for _ch_i in range(len(text)):
                            comment_input.press("Backspace")
                            time.sleep(random.uniform(0.08, 0.3))
                            if random.random() < 0.1:
                                time.sleep(random.uniform(0.4, 1.2))
                        human_sleep((0.6, 1.5))
                        random_click_blank(page)
                        print("  评论框已输入并逐字清空（未发送）")
                except Exception:
                    pass
            human_sleep((0.5, 1.5))
            page.go_back()
            human_sleep(DELAY_AFTER_SEARCH)
            try:
                page.wait_for_selector(NOTE_LINK_SELECTOR, timeout=10000)
            except Exception:
                pass
            human_sleep((0.5, 1.2))
            move_mouse_human(page)
            return True
        except Exception:
            try:
                page.go_back()
                human_sleep((1.0, 2.0))
            except Exception:
                pass
            return False

    # ---------- 登录检测 ----------
    @staticmethod
    def is_logged_in(page):
        try:
            for sel in ["div[class*='login-container']", "div[class*='login-modal']",
                        "div[class*='login-dialog']", "div[class*='login-panel']",
                        "div[class*='qrcode']"]:
                if page.query_selector(sel):
                    return False
            if page.query_selector("div[class*='avatar'], img[class*='avatar']"):
                return True
            for tag in ("a", "button"):
                try:
                    if page.query_selector(f"{tag} >> text=登录"):
                        return False
                except Exception:
                    continue
            search_input = page.query_selector(
                "input#search-input, input[placeholder*='搜索'], input[placeholder*='搜'], input[type='search']"
            )
            return bool(search_input)
        except Exception:
            return False

    # ---------- 主运行 ----------
    def run(self, wait_login=True, login_timeout=300):
        """运行采集，返回线索池行列表（每个元素为 dict，含 CLUE_HEADERS 字段 + 帖子正文）。"""
        # 断点续爬 / 流式导出初始化
        if self.resume:
            os.makedirs(self.checkpoint_dir, exist_ok=True)
            self._ck = checkpoint.CheckpointStore(self.checkpoint_dir, name="xhs", interval=30)
            self._exporter = checkpoint.StreamExporter(
                os.path.join(self.checkpoint_dir, "stream.jsonl"))
        with sync_playwright() as p:
            context, used_channel = launch_browser_context(
                p, PROFILE_DIR, proxy_url=self.proxy_url, viewport=VIEWPORT)
            network.install_resource_route(context)

            page = context.new_page()

            # stealth 注入
            from core import stealth
            from core.network import prepare_context
            real_ua = prepare_context(context, page, stealth.build_stealth_script, "")

            print("\n正在打开小红书...")
            page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
            human_sleep(DELAY_PAGE_LOAD)
            move_mouse_human(page)
            human_sleep((1.0, 2.5))
            if random.random() < 0.5:
                random_hover(page)
            if random.random() < 0.3:
                random_click_blank(page)

            if not self.is_logged_in(page):
                print("\n" + "!" * 50)
                print("检测到未登录！请在弹出的浏览器中手动完成登录")
                print("脚本会自动检测登录状态，登录成功后自动继续...")
                print("!" * 50)
                waited = 0
                while waited < login_timeout:
                    time.sleep(3)
                    waited += 3
                    try:
                        if self.is_logged_in(page):
                            print(f"\n检测到登录成功（等待约 {waited} 秒），继续执行...\n")
                            break
                    except Exception:
                        pass
                else:
                    print("\n等待登录超时，脚本退出。")
                    context.close()
                    return self._all_rows
                human_sleep(DELAY_PAGE_LOAD)

            print("登录状态确认，开始采集...\n")

            # 关键词随机打乱；启用断点续爬时跳过已完成关键词
            kws = list(self.keywords)
            random.shuffle(kws)
            done_kws = set()
            if self._ck:
                done_kws = set(self._ck.progress.get("done_keywords", []))
                kws = [k for k in kws if k not in done_kws]
                if done_kws:
                    print(f"断点续爬：跳过已完成的 {len(done_kws)} 个关键词 {sorted(done_kws)}")
            for idx, kw in enumerate(kws):
                print(f"【{kw}】正在搜索...")
                try:
                    self.search_keyword(page, kw)
                    cap = max(1, int(self.max_per_keyword * random.uniform(0.5, 1.0)))
                    results = self.scroll_and_collect(page, context, kw, cap)

                    new_count = 0
                    for item in results:
                        nid = extract_note_id(item["内容链接"])
                        if nid not in self._seen_ids:
                            self._seen_ids.add(nid)
                            if self._ck:
                                self._ck.mark_done(nid)
                            self._all_rows.append(item)
                            if self._exporter:
                                self._exporter.append(item)  # 流式导出：采到即存，中断不丢
                            new_count += 1
                    if self._ck:
                        done_kws.add(kw)
                        self._ck.progress["done_keywords"] = sorted(done_kws)
                        self._ck.save()
                    print(f"【{kw}】采集完成，本关键词 {len(results)} 条（目标{cap}），去重后新增 {new_count} 条\n")
                except Exception as e:
                    print(f"【{kw}】采集出错：{e}\n")
                    continue

                if MAX_TOTAL_NOTES and len(self._all_rows) >= MAX_TOTAL_NOTES:
                    print(f"\n已达单次总量上限 {MAX_TOTAL_NOTES} 条，提前结束采集。")
                    if self._ck:
                        self._ck.save(force=True)
                    break

                if idx < len(kws) - 1:
                    # 自适应节流关键词间隔：正常快、被限自动加长
                    wait_sec = self.throttle.delay_for("www.xiaohongshu.com") if self.throttle else _skewed_random(*DELAY_BETWEEN_KEYWORDS)
                    wait_sec = max(wait_sec, 5.0)
                    print(f"  等待 {wait_sec:.1f} 秒后继续...")
                    wait_end = time.time() + wait_sec
                    while time.time() < wait_end:
                        if random.random() < 0.6:
                            move_mouse_human(page)
                        if random.random() < 0.3:
                            random_hover(page)
                        if random.random() < 0.2:
                            human_scroll(page, random.choice(["down", "up"]))
                        if random.random() < 0.1:
                            random_click_blank(page)
                        human_sleep((1.5, 3.0))

            if self._ck:
                self._ck.save(force=True)
            context.close()
            return self._all_rows


def main():
    """命令行直跑（用于测试单个平台 / worker 并行模式）。"""
    import argparse
    parser = argparse.ArgumentParser(description="小红书平台采集器")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（worker 并行模式）")
    parser.add_argument("--keywords", default="", help="覆盖关键词（逗号分隔）")
    parser.add_argument("--max-per-keyword", type=int, default=0, help="覆盖每词采集上限")
    args = parser.parse_args()

    print("=" * 60)
    print("小红书平台采集器（框架版）")
    print("=" * 60)
    if args.keywords:
        print(f"覆盖关键词：{args.keywords}")
    else:
        print(f"关键词列表：{KEYWORDS}（顺序每次随机打乱）")
    print(f"每个关键词最多采集：{args.max_per_keyword or MAX_PER_KEYWORD} 条（实际随机浮动）")
    print(f"单次总采集上限：{MAX_TOTAL_NOTES} 条")
    print(f"代理：{PROXY_URL or '直连（本机 IP）'}")
    print("=" * 60)

    kwargs = {}
    if args.keywords:
        kwargs["keywords"] = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.max_per_keyword:
        kwargs["max_per_keyword"] = args.max_per_keyword
    crawler = XHSCrawler(**kwargs)
    rows = crawler.run()

    if args.output:
        import json as _json
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            _json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"结果已写入：{args.output}（{len(rows)} 条）")
    elif rows:
        from core.storage import save_two_sheets
        out = os.path.join(os.path.expanduser("~"), "Desktop",
                           f"小红书线索_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
        save_two_sheets(out, clue_rows=rows)
        print(f"\n已保存 {len(rows)} 条到：{out}")
    else:
        print("\n未采集到任何数据。")


if __name__ == "__main__":
    main()

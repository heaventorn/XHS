# -*- coding: utf-8 -*-
"""core/humanize.py — 人类化行为模拟（公共核心模块）
偏态延迟、贝塞尔曲线鼠标移动、人味滚动、随机悬停/点击/键盘活动、人类化打字。
所有平台采集器共用，模拟真实用户行为以降低风控识别。
"""
import time
import random
import math

# 视口与分层延迟（可按平台覆盖）
VIEWPORT = {"width": 1920, "height": 1080}
# 已整体下调（约 50-60%）以提升爬取速度；被风控时由 core.autothrottle 自动加长间隔兜底
DELAY_PAGE_LOAD = (4.0, 7.0)
DELAY_AFTER_SEARCH = (3.5, 6.0)
DELAY_AFTER_SCROLL = (2.0, 3.5)
DELAY_BETWEEN_KEYWORDS = (12.0, 22.0)
DELAY_MOUSE_MOVE = (0.4, 0.9)
DELAY_EXTRACT = (0.3, 0.7)
DELAY_READ_PAUSE = (1.5, 3.0)  # 阅读停顿

def _skewed_random(lo, hi):
    """人类长尾偏态随机：多数时候接近下限，偶尔出现长停顿。
    真实人类操作间隔近似长尾/幂律分布，均匀分布反而像机器。"""
    if hi <= lo:
        return lo
    # random()**k 偏向小值，k 越大越偏下限；k 本身带随机，避免模式固定
    p = random.random() ** random.uniform(1.8, 3.2)
    return lo + (hi - lo) * p

def human_sleep(delay_range):
    time.sleep(_skewed_random(*delay_range))

def move_mouse_human(page, target_x=None, target_y=None, jitter=True):
    """人类化鼠标移动：贝塞尔曲线+随机抖动+速度变化+中途停顿+末端微抖动"""
    try:
        if target_x is None or target_y is None:
            target_x = random.randint(100, VIEWPORT["width"] - 100)
            target_y = random.randint(100, VIEWPORT["height"] - 200)

        start_x = random.randint(300, 900)
        start_y = random.randint(200, 700)

        steps = random.randint(25, 45)
        cp1_x = random.randint(0, VIEWPORT["width"])
        cp1_y = random.randint(0, VIEWPORT["height"])
        cp2_x = random.randint(0, VIEWPORT["width"])
        cp2_y = random.randint(0, VIEWPORT["height"])

        # 随机选择一个中途停顿点（15%概率）
        pause_at = random.uniform(0.3, 0.7) if random.random() < 0.15 else None

        for i in range(steps + 1):
            t = i / steps
            # 三次贝塞尔曲线
            x = (1-t)**3 * start_x + 3*(1-t)**2 * t * cp1_x + 3*(1-t)*t**2 * cp2_x + t**3 * target_x
            y = (1-t)**3 * start_y + 3*(1-t)**2 * t * cp1_y + 3*(1-t)*t**2 * cp2_y + t**3 * target_y

            # 添加随机抖动
            if jitter and i > 0 and i < steps:
                x += random.uniform(-2, 2)
                y += random.uniform(-2, 2)

            # 速度变化：中间快，两端慢，加入随机扰动
            speed_factor = 0.015 + 0.035 * math.sin(t * math.pi) + random.uniform(-0.005, 0.005)
            page.mouse.move(x, y)
            time.sleep(max(0.005, speed_factor * random.uniform(0.8, 1.2)))

            # 中途停顿（模拟人看到内容后思考）
            if pause_at is not None and abs(t - pause_at) < 0.02:
                time.sleep(random.uniform(0.3, 0.8))
                pause_at = None

        # 末端微抖动（模拟人手到达目标后的不稳定）
        if random.random() < 0.4:
            for _ in range(random.randint(2, 5)):
                jx = target_x + random.uniform(-3, 3)
                jy = target_y + random.uniform(-3, 3)
                page.mouse.move(jx, jy)
                time.sleep(random.uniform(0.01, 0.03))
            # 最后回到目标点
            page.mouse.move(target_x, target_y)
    except Exception:
        pass

def random_hover(page):
    """随机悬停在页面某个元素上"""
    try:
        selectors = ["a", "div", "section", "img", "span"]
        sel = random.choice(selectors)
        elements = page.query_selector_all(sel)
        if elements:
            elem = random.choice(elements)
            box = elem.bounding_box()
            if box and box["x"] > 0 and box["y"] > 0:
                move_mouse_human(page, box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                human_sleep((0.5, 1.5))
    except Exception:
        pass

def random_click_blank(page):
    """随机点击页面空白处"""
    try:
        x = random.randint(50, VIEWPORT["width"] - 50)
        y = random.randint(50, VIEWPORT["height"] - 50)
        move_mouse_human(page, x, y)
        page.mouse.click(x, y)
        human_sleep((0.3, 0.8))
    except Exception:
        pass

def random_keyboard_activity(page):
    """随机键盘活动：方向键、Esc、空格等，模拟真实用户浏览习惯"""
    try:
        actions = [
            lambda: page.keyboard.press("ArrowDown"),
            lambda: page.keyboard.press("ArrowUp"),
            lambda: page.keyboard.press("ArrowRight"),
            lambda: page.keyboard.press("ArrowLeft"),
            lambda: page.keyboard.press(" "),  # 空格翻页
            lambda: page.keyboard.press("Home"),
            lambda: page.keyboard.press("End"),
        ]
        # 30%概率不做任何键盘活动
        if random.random() < 0.3:
            return
        action = random.choice(actions)
        action()
        time.sleep(random.uniform(0.1, 0.4))
        # 偶尔连续按2-3次
        if random.random() < 0.3:
            for _ in range(random.randint(1, 2)):
                random.choice(actions)()
                time.sleep(random.uniform(0.05, 0.15))
    except Exception:
        pass

def human_scroll(page, direction="down"):
    """人类化滚动：速度变化+阅读停顿+偶尔回滚+键盘滚动混合"""
    try:
        # 25%概率用键盘滚动（PageDown/ArrowDown），更像真实用户
        if random.random() < 0.25 and direction == "down":
            if random.random() < 0.6:
                page.keyboard.press("PageDown")
            else:
                for _ in range(random.randint(3, 6)):
                    page.keyboard.press("ArrowDown")
                    time.sleep(random.uniform(0.05, 0.12))
            time.sleep(random.uniform(0.3, 0.8))
            # 20%概率阅读停顿
            if random.random() < 0.2:
                human_sleep(DELAY_READ_PAUSE)
            return

        if direction == "down":
            scroll_amount = random.randint(400, 900)
        else:
            scroll_amount = -random.randint(150, 350)

        # 分多次滚动，速度先快后慢
        steps = random.randint(4, 10)
        remaining = scroll_amount
        for i in range(steps):
            if i == steps - 1:
                step = remaining
            else:
                # 先快后慢
                ratio = 1.0 - (i / steps) * 0.6
                step = int(remaining * ratio / (steps - i))
                remaining -= step
            page.mouse.wheel(0, step)
            time.sleep(random.uniform(0.03, 0.1))

        # 25%概率阅读停顿
        if random.random() < 0.25:
            human_sleep(DELAY_READ_PAUSE)

        # 15%概率向上回滚
        if random.random() < 0.15 and direction == "down":
            time.sleep(random.uniform(0.3, 0.8))
            back_amount = random.randint(80, 200)
            page.mouse.wheel(0, -back_amount)
            time.sleep(random.uniform(0.2, 0.5))
            # 回滚后再向下滚一点（模拟找位置）
            if random.random() < 0.5:
                time.sleep(random.uniform(0.2, 0.4))
                page.mouse.wheel(0, random.randint(30, 80))
                time.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass

def human_type(element, text):
    """人类化打字：随机间隔+偶尔删除重输"""
    try:
        element.click()
        human_sleep((0.2, 0.5))
        for i, char in enumerate(text):
            element.type(char, delay=random.randint(60, 180))
            # 5%概率停顿思考
            if random.random() < 0.05 and i < len(text) - 1:
                human_sleep((0.3, 0.8))
            # 2%概率打错删除重输
            if random.random() < 0.02 and i > 0:
                element.press("Backspace")
                time.sleep(random.uniform(0.1, 0.3))
                element.type(char, delay=random.randint(80, 150))
    except Exception:
        element.fill(text)

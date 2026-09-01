# -*- coding: utf-8 -*-
"""core/extract.py — 通用提取工具（公共核心模块）
URL/ID 提取、发布时间解析、作者名清理等。与具体平台解耦，各采集器共用。
"""
import re
from datetime import datetime, timedelta


_PUB_TIME_PATTERNS = [
    r"刚刚",
    r"\d+\s*分钟前",
    r"\d+\s*小时前",
    r"\d+\s*天前",
    r"昨天",
    r"前天",
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?",
    r"\d{1,2}[-/月]\d{1,2}日?",
]


def clean_author_name(text):
    if not text:
        return ""
    lines = text.strip().split("\n")
    return lines[0].strip() if lines else text.strip()


def extract_publish_time(text):
    """从整段文本中用正则提取发布时间，不依赖换行行号结构（原按行取第2行过于脆弱）。"""
    if not text:
        return ""
    for pat in _PUB_TIME_PATTERNS:
        m = re.search(pat, text)
        if m:
            return m.group(0).strip()
    return ""


def parse_xhs_time(time_str):
    if not time_str:
        return None
    now = datetime.now()
    time_str = time_str.strip()
    if time_str == "刚刚":
        return now
    m = re.match(r"(\d+)分钟前", time_str)
    if m:
        return now.replace(microsecond=0) - timedelta(minutes=int(m.group(1)))
    m = re.match(r"(\d+)小时前", time_str)
    if m:
        return now.replace(microsecond=0) - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)天前", time_str)
    if m:
        return now.replace(microsecond=0) - timedelta(days=int(m.group(1)))
    if time_str.startswith("昨天"):
        return now.replace(microsecond=0) - timedelta(days=1)
    if time_str.startswith("前天"):
        return now.replace(microsecond=0) - timedelta(days=2)
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", time_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", time_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # M月D日 / MM-DD：按今年解析，若晚于当前则视为去年（减少误判）
    m = re.match(r"(\d{1,2})月(\d{1,2})日?", time_str)
    if m:
        try:
            d = datetime(now.year, int(m.group(1)), int(m.group(2)))
            if d > now:
                d = d.replace(year=now.year - 1)
            return d
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})[-/](\d{1,2})", time_str)
    if m:
        try:
            d = datetime(now.year, int(m.group(1)), int(m.group(2)))
            if d > now:
                d = d.replace(year=now.year - 1)
            return d
        except ValueError:
            return None
    return None


def is_within_two_years(time_str):
    """True=两年内保留 / False=超过两年丢弃 / None=无法解析（由调用方决定，默认保留但不静默）。"""
    pub_time = parse_xhs_time(time_str)
    if pub_time is None:
        return None
    two_years_ago = datetime.now() - timedelta(days=730)
    return pub_time >= two_years_ago


def extract_note_id(url):
    match = re.search(r"/search_result/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/explore/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    return url


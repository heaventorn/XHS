# -*- coding: utf-8 -*-
"""core/autothrottle.py — 自适应节流（公共核心模块）

算法移植自 D4Vinci/Scrapling 的 AutoThrottle：
  - 首次请求用 start_delay；
  - 每次请求后按实际响应延迟平滑调整（新延迟 = (当前+目标)/2，目标 = 延迟/并发）；
  - 被拦截时强制退避：等待 Retry-After 或把延迟翻倍，且绝不让被拦截后的延迟变小；
  - 延迟始终夹在 [floor, max_delay] 之间。

作用：替代写死的固定延迟常量，网站快就自动提速、被风控就自动加长间隔，实现
"提速与安全自适应"。同步架构版本。
"""
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

BLOCK_BACKOFF_FACTOR = 2.0


def parse_retry_after(headers):
    """从响应头解析 Retry-After（秒数或 HTTP 日期），解析失败返回 None。"""
    value = ""
    if headers:
        for key, v in headers.items():
            if str(key).lower() == "retry-after":
                value = str(v).strip()
                break
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        pass
    try:
        return max((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None


class AutoThrottle:
    """按响应延迟和被拦截状态自适应调整每个域名的请求间隔。"""

    def __init__(self, start_delay=3.0, max_delay=45.0, target_concurrency=1.0,
                 block_backoff=True, min_delay=0.8):
        """
        :param start_delay: 首次请求某域名的间隔（秒）
        :param max_delay: 允许的最大间隔（秒）
        :param target_concurrency: 每域名目标并发数（1 = 串行）
        :param block_backoff: 被拦截时是否退避（翻倍或按 Retry-After）
        :param min_delay: 间隔下限（秒），即 floor
        """
        if target_concurrency <= 0:
            raise ValueError("target_concurrency 必须 > 0")
        if max_delay < start_delay:
            raise ValueError("max_delay 不能低于 start_delay")
        self.start_delay = start_delay
        self.max_delay = max_delay
        self.target_concurrency = target_concurrency
        self.block_backoff = block_backoff
        self.min_delay = min_delay
        self.delays = {}
        self.last_latency = {}   # 最近一次延迟（调试/统计）
        self.block_count = {}    # 每个域名的被拦截次数
        self.request_count = {}  # 每个域名的请求次数

    def delay_for(self, domain, floor=None):
        """返回某域名的当前间隔；首次访问初始化为 start_delay。"""
        if floor is None:
            floor = self.min_delay
        if domain not in self.delays:
            self.delays[domain] = min(max(floor, self.start_delay), self.max_delay)
        return self.delays[domain]

    def record(self, domain, latency, ok, floor=None, retry_after=None):
        """记录一次请求结果，返回该域名新的间隔。

        :param domain: 域名
        :param latency: 本次请求耗时（秒）
        :param ok: 是否健康响应（非拦截）
        :param floor: 间隔下限
        :param retry_after: 网站要求的等待秒数（被拦截时）
        """
        if floor is None:
            floor = self.min_delay
        current = self.delay_for(domain, floor)
        target = latency / self.target_concurrency
        new_delay = max((current + target) / 2, target)

        self.request_count[domain] = self.request_count.get(domain, 0) + 1
        if not ok:
            self.block_count[domain] = self.block_count.get(domain, 0) + 1
            penalty = current
            if self.block_backoff:
                penalty = retry_after if retry_after is not None else current * BLOCK_BACKOFF_FACTOR
            # 被拦截后绝不能比现在更快
            new_delay = max(new_delay, penalty, current)
        new_delay = min(max(new_delay, floor), self.max_delay)
        self.delays[domain] = new_delay
        self.last_latency[domain] = latency
        return new_delay

    def wait(self, domain, floor=None):
        """按当前间隔睡眠（用于串行爬虫的请求间隔），返回实际睡眠秒数。"""
        d = self.delay_for(domain, floor)
        time.sleep(d)
        return d

    def reset(self):
        self.delays.clear()
        self.last_latency.clear()
        self.block_count.clear()
        self.request_count.clear()

    def stats(self):
        """调试统计。"""
        return {
            "delays": dict(self.delays),
            "block_count": dict(self.block_count),
            "request_count": dict(self.request_count),
        }

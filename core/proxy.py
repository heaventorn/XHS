# -*- coding: utf-8 -*-
"""core/proxy.py — 代理轮换（公共核心模块）

思想来自 D4Vinci/Scrapling 的 ProxyRotator：
  - 线程安全的代理轮换（默认轮询策略，可插拔自定义策略）；
  - 支持字符串（"http://user:pass@host:port"）与 Playwright dict 两种代理格式；
  - 提供 is_proxy_error 判断代理类错误。

用法：
  rotator = ProxyRotator(["http://p1:8080", "http://p2:8080"])
  proxy = rotator.get_proxy()          # 依次轮换
  if is_proxy_error(exc): rotator.mark_bad()  # 代理出错可跳过
"""
import threading

_PROXY_ERROR_INDICATORS = (
    "net::err_proxy",
    "net::err_tunnel",
    "connection refused",
    "connection reset",
    "connection timed out",
    "failed to connect",
    "could not resolve proxy",
    "proxy authentication required",
)


def is_proxy_error(error):
    """判断异常是否为代理相关错误（兼容 HTTP 与浏览器错误）。"""
    try:
        msg = str(error).lower()
    except Exception:
        return False
    return any(ind in msg for ind in _PROXY_ERROR_INDICATORS)


def cyclic_rotation(proxies, current_index):
    """默认轮询策略：顺序迭代，到尾回绕。"""
    idx = current_index % len(proxies)
    return proxies[idx], (idx + 1) % len(proxies)


def _proxy_key(proxy):
    """生成代理唯一键（dict 用 server+username）。"""
    if isinstance(proxy, str):
        return proxy
    server = proxy.get("server", "")
    username = proxy.get("username", "")
    return f"{server}|{username}"


class ProxyRotator:
    """线程安全的代理轮换器。"""

    def __init__(self, proxies, strategy=cyclic_rotation):
        """
        :param proxies: 代理列表。
            - 字符串: "http://proxy:8080" 或 "http://user:pass@proxy:8080"
            - dict: {"server": "http://proxy:8080", "username": "u", "password": "p"}
        :param strategy: 轮换策略函数 (proxies, index) -> (proxy, next_index)
        """
        if not proxies:
            raise ValueError("至少需要一个代理")
        if not callable(strategy):
            raise TypeError("strategy 必须是可调用对象")
        self._strategy = strategy
        self._lock = threading.Lock()
        self._proxies = []
        self._proxy_to_index = {}
        for i, p in enumerate(proxies):
            if isinstance(p, str):
                self._proxy_to_index[_proxy_key(p)] = i
                self._proxies.append(p)
            elif isinstance(p, dict) and "server" in p:
                self._proxy_to_index[_proxy_key(p)] = i
                self._proxies.append(p)
            else:
                raise TypeError(f"无效代理类型: {type(p).__name__}，需为 str 或含 server 的 dict")
        self._current_index = 0
        self._bad_proxies = set()   # 出错被标记的代理键（本轮跳过）

    def get_proxy(self):
        """按策略获取下一个代理。"""
        with self._lock:
            # 跳过本轮已标记为坏的代理
            for _ in range(len(self._proxies)):
                proxy, self._current_index = self._strategy(self._proxies, self._current_index)
                if _proxy_key(proxy) not in self._bad_proxies:
                    return proxy
            # 全部坏掉则重置坏名单，返回当前
            self._bad_proxies.clear()
            proxy, self._current_index = self._strategy(self._proxies, self._current_index)
            return proxy

    def mark_bad(self, proxy):
        """标记某代理本轮不可用（调用方在 is_proxy_error 命中时调用）。"""
        with self._lock:
            self._bad_proxies.add(_proxy_key(proxy))

    def mark_good(self, proxy):
        """恢复某代理可用。"""
        with self._lock:
            self._bad_proxies.discard(_proxy_key(proxy))

    @property
    def proxies(self):
        return list(self._proxies)

    @property
    def bad_count(self):
        return len(self._bad_proxies)

    def __len__(self):
        return len(self._proxies)

    def __repr__(self):
        return f"ProxyRotator(proxies={len(self._proxies)}, bad={len(self._bad_proxies)})"

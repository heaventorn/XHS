# -*- coding: utf-8 -*-
"""core/ — 大爬虫框架公共核心层
各平台采集器（platforms/*.py）共享以下能力：
  auth        — 双密码验证（Argon2）
  stealth     — 深度反爬注入脚本
  humanize    — 人类化行为模拟（滚动/鼠标/打字/延迟）
  network     — Referer 跳转 / 资源拦截 / 硬件属性读取
  extract     — 通用提取（时间/URL/ID/作者名）
  blacklist   — 账号黑名单 / 内容关键词过滤
  storage     — 双层 EXCEL 落盘（线索池 + 联系池）
  adaptive    — 自适应元素定位（网站改版自动重定位）
  autothrottle— 自适应节流（被限自动退避 / 提速）
  checkpoint  — 断点续爬 + 流式导出
  proxy       — 代理轮换 / 多 session 支持
"""
from . import (
    auth, stealth, humanize, network, extract, blacklist, storage,
    adaptive, autothrottle, checkpoint, proxy,
)

__all__ = [
    "auth", "stealth", "humanize", "network", "extract", "blacklist", "storage",
    "adaptive", "autothrottle", "checkpoint", "proxy",
]

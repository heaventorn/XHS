# -*- coding: utf-8 -*-
"""core/browser.py — 浏览器启动（公共核心模块）
所有平台采集器共用：优先系统 Chrome/Edge（持久化登录态），
退回 Playwright 自带 Chromium。带 stealth 注入与资源拦截。
"""
import os
import sys

from playwright.sync_api import sync_playwright


def launch_browser_context(p, user_data_dir, proxy_url="", viewport=None,
                           geolocation=None, extra_args=None):
    """启动持久化浏览器上下文。

    :param p: sync_playwright 实例
    :param user_data_dir: 持久化用户目录（保存登录态）
    :param proxy_url: 代理地址（留空直连）
    :param viewport: 视口 dict
    :param geolocation: 定位 dict
    :param extra_args: 附加启动参数
    :return: (context, used_channel)
    """
    viewport = viewport or {"width": 1920, "height": 1080}
    geolocation = geolocation or {"latitude": 29.5630, "longitude": 106.5516}

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1920,1080",
        "--lang=zh-CN",
        "--no-first-run",
        "--disable-notifications",
        "--exclude-switches=enable-automation",
    ]
    if extra_args:
        launch_args += extra_args
    # --no-sandbox / --disable-dev-shm-usage 仅 Linux/容器环境需要，Windows 下无用
    if not sys.platform.startswith("win"):
        launch_args += ["--no-sandbox", "--disable-dev-shm-usage"]

    proxy_cfg = {"proxy": {"server": proxy_url}} if proxy_url else {}

    context = None
    used_channel = None
    # 优先使用系统 Chrome/Edge（登录态、指纹更接近真实用户）
    for channel in ["chrome", "msedge"]:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                channel=channel,
                args=launch_args,
                viewport=viewport,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                permissions=["notifications"],
                geolocation=geolocation,
                color_scheme="light",
                ignore_default_args=["--enable-automation"],
                **proxy_cfg,
            )
            used_channel = channel
            print(f"使用浏览器：{channel}")
            break
        except Exception:
            continue

    if not context:
        # 本机无 Chrome/Edge 时，尝试 Playwright 自带 Chromium
        print("\n未找到系统 Chrome/Edge，尝试 Playwright 自带 Chromium...")
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=launch_args,
                viewport=viewport,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                permissions=["notifications"],
                geolocation=geolocation,
                color_scheme="light",
                ignore_default_args=["--enable-automation"],
                **proxy_cfg,
            )
            used_channel = "playwright-chromium"
        except Exception:
            context = None

    if not context:
        raise RuntimeError(
            "未找到可用浏览器。请安装 Google Chrome 或 Microsoft Edge，"
            "或执行 'playwright install chromium' 安装 Playwright 自带浏览器后重试。"
        )
    return context, used_channel

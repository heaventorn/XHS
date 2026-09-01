# -*- coding: utf-8 -*-
"""core/network.py — 浏览器网络层伪装（公共核心模块）
带 Referer 跳转、资源拦截（favicon 时序 / 统计域名 / 媒体字体）、
真实 UA 与硬件属性读取。各平台采集器共用。
"""
import json


# ---------------- 带 Referer 的页面跳转 ----------------
def goto_with_referer(page, url, timeout=30000):
    """带 Referer 的页面跳转：模拟从当前页"点击"进入目标页，避免 Referer 为空被识别为程序化跳转。

    真实用户从 A 页点击链接进 B 页时，B 页请求必带 Referer=A。
    直接 page.goto() 会让 Referer 为空，服务器会将其判定为脚本直连。
    经实测，route.continue_ 无法覆盖 Referer（Chromium 忽略），必须用 set_extra_http_headers 才能发出。
    """
    referer_url = ""
    try:
        cur = page.url or ""
        if cur and "about:blank" not in cur:
            referer_url = cur
    except Exception:
        pass
    if referer_url:
        try:
            page.set_extra_http_headers({"Referer": referer_url})
        except Exception:
            pass
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    finally:
        # 用完即清，避免影响后续页面的 Referer 语义
        try:
            page.set_extra_http_headers({})
        except Exception:
            pass


# ---------------- 资源拦截 ----------------
def install_resource_route(context, keep_images=True):
    """安装资源拦截路由：拦截 favicon（消除跳转双峰时序）、统计/反爬域名、
    媒体与字体（保留图片便于观察采集的卡片）。
    返回安装的路由函数（一般无需引用）。"""
    def _resource_route(route):
        try:
            req = route.request
            rtype = req.resource_type
            url = req.url
            # 拦截 favicon.ico —— 真实浏览器 favicon 有缓存，不会每次跳转都重新请求。
            if "favicon" in url.lower() or url.rstrip("/").endswith(".ico"):
                route.abort()
                return
            if rtype in ("media", "font"):
                route.abort()
                return
            _blocked = ("hm.baidu.com", "sensorsdata.cn", "sensorsdata.com",
                        "log.snssdk.com", "xlog.snssdk.com", "applog.snssdk.com",
                        "byteoversea.com", "beacon.qq.com", "google-analytics.com",
                        "googletagmanager.com", "doubleclick.net", "scorecardresearch.com")
            if any(d in url for d in _blocked):
                route.abort()
                return
            route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    context.route("**/*", _resource_route)
    return _resource_route


# ---------------- 真实硬件/平台属性读取 ----------------
NAV_READ_JS = (
    "() => {"
    "  const c = document.createElement('canvas');"
    "  const gl = c.getContext('webgl') || c.getContext('experimental-webgl');"
    "  let v = '', r = '';"
    "  try {"
    "    if (gl) {"
    "      const dbg = gl.getExtension('WEBGL_debug_renderer_info');"
    "      if (dbg) {"
    "        v = gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) || '';"
    "        r = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || '';"
    "      }"
    "    }"
    "  } catch(e){}"
    "  const pl = [];"
    "  try { for (let i = 0; i < navigator.plugins.length; i++) {"
    "    const p = navigator.plugins[i];"
    "    pl.push({name: p.name, filename: p.filename, description: p.description});"
    "  } } catch(e){}"
    "  const mm = [];"
    "  try { for (let j = 0; j < navigator.mimeTypes.length; j++) {"
    "    const m = navigator.mimeTypes[j];"
    "    mm.push({type: m.type, suffixes: m.suffixes, description: m.description});"
    "  } } catch(e){}"
    "  return {"
    "    hw: navigator.hardwareConcurrency || 8,"
    "    mem: navigator.deviceMemory || 8,"
    "    mtp: navigator.maxTouchPoints || 0,"
    "    platform: navigator.platform || 'Win32',"
    "    vendor: navigator.vendor || 'Google Inc.',"
    "    webgl_vendor: v,"
    "    webgl_renderer: r,"
    "    plugins: pl,"
    "    mimes: mm"
    "  };"
    "}"
)


def prepare_context(context, page, build_stealth_script, fallback_ua):
    """在已创建的 context/page 上注入 stealth 脚本并预热 UA-CH。
    :param build_stealth_script: core.stealth 中的构建函数
    :param fallback_ua: 兜底 UA（各采集器提供）
    """
    page.goto("about:blank")
    real_ua = page.evaluate("navigator.userAgent") or fallback_ua
    try:
        real_nav = page.evaluate(NAV_READ_JS)
    except Exception:
        real_nav = {}
    context.add_init_script(build_stealth_script(real_ua, real_nav))

    # UA-CH 预热：主动请求 high-entropy 值，促使浏览器后续自然携带完整 Sec-CH-UA-* 头
    try:
        page.evaluate(
            "navigator.userAgentData && navigator.userAgentData.getHighEntropyValues ? "
            "navigator.userAgentData.getHighEntropyValues("
            "['architecture','bitness','platformVersion','fullVersionList']).catch(function(){}) : Promise.resolve()"
        )
    except Exception:
        pass
    return real_ua

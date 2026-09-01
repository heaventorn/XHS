# -*- coding: utf-8 -*-
"""core/stealth.py — 反爬伪装（公共核心模块）
深度 Stealth 注入脚本与构建器：掩盖 webdriver 痕迹、伪造 navigator/UA-CH、
Canvas/WebGL/Audio 指纹噪声、permissions/toString 伪装、时区/连接/字体/电池等。
所有平台采集器共用：启动浏览器后调用 build_stealth_script(real_ua, nav) 生成注入脚本。
"""
import re
import json

STEALTH_SCRIPT_TEMPLATE = r"""
// ===== 全局常量 =====
const __UA = "__UA_PLACEHOLDER__";

// 基于 seed 的伪随机数生成器（保证同一 canvas 多次调用结果一致，避免完全随机被检测）
function __seededRandom(seed) {
    let s = seed % 2147483647;
    if (s <= 0) s += 2147483646;
    return function() {
        s = (s * 16807) % 2147483647;
        return (s - 1) / 2147483646;
    };
}

// ===== 1. 核心自动化特征掩盖（含原型链）=====
const __wdDesc = { get: () => false, set: () => {}, configurable: true, enumerable: true };
Object.defineProperty(navigator, 'webdriver', __wdDesc);
try { Object.defineProperty(Navigator.prototype, 'webdriver', __wdDesc); } catch(e) {}
Object.defineProperty(navigator, 'automation', { get: () => undefined, configurable: true });
Object.defineProperty(navigator, 'controlledByAutomat', { get: () => undefined, configurable: true });

// 原型链注入痕迹清理
if (navigator.__proto__) {
    const __np = navigator.__proto__;
    ['__driver_evaluate','__webdriver_evaluate','__selenium_evaluate','__fxdriver_evaluate',
     '__driver_unwrapped','__webdriver_unwrapped','__selenium_unwrapped','__fxdriver_unwrapped',
     '__webdriver_script_fn','__webdriver_script_func','__webdriver_script_timeout',
     '_cdc_adoQpoasnfa76pfcZLmcfl_','_cdc_asdjflasutopfhvcZLmcfl_','_cdc_sdjflasutopfhvcZLmcfl_']
    .forEach(function(p){ try{ delete __np[p]; }catch(e){} });
}

// ===== 2. Navigator 完整属性伪造（plugins/mimeTypes 运行时透传真实值，避免数量/内容与真机不符）=====
const __plugins = __PLUGINS_JSON__;
__plugins.item = function(i){ return __plugins[i] || null; };
__plugins.namedItem = function(n){ return __plugins.find(function(p){return p.name===n;}) || null; };
__plugins.refresh = function(){};
Object.defineProperty(navigator, 'plugins', { get: function(){ return __plugins; }, configurable: true });

const __mimes = __MIMES_JSON__;
__mimes.item = function(i){ return __mimes[i] || null; };
__mimes.namedItem = function(n){ return __mimes.find(function(m){return m.type===n;}) || null; };
Object.defineProperty(navigator, 'mimeTypes', { get: function(){ return __mimes; }, configurable: true });

const __navProps = {
    languages: ['zh-CN','zh','en-US','en'],
    language: 'zh-CN',
    hardwareConcurrency: __HW_CONCURRENCY__,
    deviceMemory: __DEVICE_MEMORY__,
    maxTouchPoints: __MAX_TOUCH_POINTS__,
    vendor: '__VENDOR__',
    platform: '__PLATFORM__',
    cookieEnabled: true,
    onLine: true,
    doNotTrack: null,
    vendorSub: '',
    productSub: '20030107',
    product: 'Gecko',
    appVersion: __UA.replace('Mozilla/',''),
    userAgent: __UA,
    appName: 'Netscape',
    appCodeName: 'Mozilla',
};
Object.keys(__navProps).forEach(function(key){
    try { Object.defineProperty(navigator, key, { get: function(){ return __navProps[key]; }, configurable: true }); } catch(e){}
});

// ===== 2.5 userAgentData（UA Client Hints）伪造：与 navigator.userAgent 版本对齐 =====
try {
    if (!("userAgentData" in navigator)) {
        var __brands = [
            {brand: "Chromium", version: "__CHROME_MAJOR_PLACEHOLDER__"},
            {brand: "Google Chrome", version: "__CHROME_MAJOR_PLACEHOLDER__"},
            {brand: "Not.A/Brand", version: "24"}
        ];
        var __uaData = {
            brands: __brands,
            mobile: false,
            platform: "Windows",
            getHighEntropyValues: function() {
                return Promise.resolve({
                    architecture: "x86",
                    bitness: "64",
                    brands: __brands,
                    fullVersionList: [
                        {brand: "Chromium", version: "__CHROME_VERSION_PLACEHOLDER__"},
                        {brand: "Google Chrome", version: "__CHROME_VERSION_PLACEHOLDER__"},
                        {brand: "Not.A/Brand", version: "24.0.0.0"}
                    ],
                    mobile: false,
                    model: "",
                    platform: "Windows",
                    platformVersion: "15.0.0",
                    uaFullVersion: "__CHROME_VERSION_PLACEHOLDER__",
                    wow64: false
                });
            },
            toJSON: function() { return {brands: __brands, mobile: false, platform: "Windows"}; }
        };
        Object.defineProperty(navigator, "userAgentData", { get: function(){ return __uaData; }, configurable: true });
    }
} catch(e){}

// ===== 3. Screen 与窗口尺寸伪造 =====
const __screenProps = { width:1920, height:1080, availWidth:1920, availHeight:1040, availLeft:0, availTop:0, colorDepth:24, pixelDepth:24 };
Object.keys(__screenProps).forEach(function(key){
    try { Object.defineProperty(screen, key, { get: function(){ return __screenProps[key]; }, configurable: true }); } catch(e){}
});
try {
    Object.defineProperty(window, 'outerWidth', { get: function(){ return 1920; }, configurable: true });
    Object.defineProperty(window, 'outerHeight', { get: function(){ return 1080; }, configurable: true });
    Object.defineProperty(window, 'innerWidth', { get: function(){ return 1920; }, configurable: true });
    Object.defineProperty(window, 'innerHeight', { get: function(){ return 1040; }, configurable: true });
    Object.defineProperty(window, 'devicePixelRatio', { get: function(){ return 1; }, configurable: true });
} catch(e){}

// ===== 4. Chrome / Runtime 完整伪造 =====
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || { id:'', onMessage:{}, sendMessage:function(){}, onConnect:{}, connect:function(){}, onInstalled:{}, onStartup:{}, connectNative:function(){} };
window.chrome.app = window.chrome.app || { isInstalled:false, getDetails:function(){}, getIsInstalled:function(){return false;}, runningState:'cannot run' };
window.chrome.csi = window.chrome.csi || function(){ return { startE:Date.now(), onloadT:Date.now(), pageT:100, tran:15 }; };
window.chrome.loadTimes = window.chrome.loadTimes || function(){ return {
    requestTime:Date.now()/1000, startLoadTime:Date.now()/1000, commitLoadTime:Date.now()/1000,
    finishDocumentLoadTime:Date.now()/1000, finishLoadTime:Date.now()/1000, firstPaintTime:Date.now()/1000,
    connectionInfo:'h2', npnNegotiatedProtocol:'h2', wasAlternateProtocolAvailable:false, wasFetchedViaSpdy:true, wasNpnNegotiated:true
};};

// ===== 5. Permissions 完整伪造 =====
if (navigator.permissions && navigator.permissions.query) {
    const __origQuery = navigator.permissions.query.bind(navigator.permissions);
    const __query = function(parameters) {
        var name = parameters.name;
        if (name === 'notifications') return Promise.resolve({ state: Notification.permission, onchange:null });
        if (name === 'geolocation') return Promise.resolve({ state:'prompt', onchange:null });
        if (name === 'camera' || name === 'microphone') return Promise.resolve({ state:'prompt', onchange:null });
        if (name === 'midi') return Promise.resolve({ state:'prompt', onchange:null });
        return __origQuery(parameters);
    };
    // 保留原生函数名与 toString 特征，避免 toString() 暴露自定义函数体
    try { Object.defineProperty(__query, 'name', { value: 'query', configurable: true }); } catch(e){}
    try { window.__spoofedFns = window.__spoofedFns || []; window.__spoofedFns.push(__query); } catch(e){}
    navigator.permissions.query = __query;
}
try { Object.defineProperty(Notification, 'permission', { get: function(){ return 'default'; }, configurable: true }); } catch(e){}

// ===== 6. Canvas 指纹保护（基于 seed 的一致噪声，非完全随机）=====
const __origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (type === 'image/png' && this.width > 0 && this.height > 0) {
        try {
            var ctx = this.getContext('2d');
            if (ctx) {
                var imgData = ctx.getImageData(0, 0, this.width, this.height);
                var rand = __seededRandom(this.width * 31 + this.height * 17 + 7);
                for (var i = 0; i < imgData.data.length; i += 4) {
                    if (rand() < 0.008) {
                        var delta = rand() < 0.5 ? 1 : -1;
                        imgData.data[i] = Math.max(0, Math.min(255, imgData.data[i] + delta));
                    }
                }
                ctx.putImageData(imgData, 0, 0);
            }
        } catch(e){}
    }
    return __origToDataURL.apply(this, arguments);
};

const __origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
CanvasRenderingContext2D.prototype.getImageData = function() {
    var result = __origGetImageData.apply(this, arguments);
    if (result && result.data && result.width > 0 && result.height > 0) {
        try {
            var rand = __seededRandom(result.width * 13 + result.height * 7 + Math.floor(arguments[0]||0) + Math.floor(arguments[1]||0) + 3);
            for (var i = 0; i < result.data.length; i += 4) {
                if (rand() < 0.004) {
                    result.data[i] = Math.max(0, Math.min(255, result.data[i] + 1));
                }
            }
        } catch(e){}
    }
    return result;
};

// ===== 7. WebGL 指纹伪造（vendor/renderer 返回常见显卡，避免无 GPU 的 SwiftShader 暴露）=====
try {
    var __glGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return "__WEBGL_VENDOR__";
        if (param === 37446) return "__WEBGL_RENDERER__";
        return __glGetParam.call(this, param);
    };
} catch(e){}
try {
    var __gl2GetParam = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return "__WEBGL_VENDOR__";
        if (param === 37446) return "__WEBGL_RENDERER__";
        return __gl2GetParam.call(this, param);
    };
} catch(e){}

// ===== 8. AudioContext 指纹保护（含 getByteTimeDomainData）=====
if (window.AudioContext || window.webkitAudioContext) {
    var __AC = window.AudioContext || window.webkitAudioContext;
    var __origCreateAnalyser = __AC.prototype.createAnalyser;
    __AC.prototype.createAnalyser = function() {
        var analyser = __origCreateAnalyser.apply(this, arguments);
        var __origGetByteFreq = analyser.getByteFrequencyData;
        analyser.getByteFrequencyData = function(array) {
            __origGetByteFreq.apply(this, arguments);
            var rand = __seededRandom(array.length);
            for (var i = 0; i < array.length; i++) {
                if (rand() < 0.025) array[i] = Math.max(0, Math.min(255, array[i] + (rand()<0.5?1:-1)));
            }
        };
        if (analyser.getByteTimeDomainData) {
            var __origGetByteTime = analyser.getByteTimeDomainData;
            analyser.getByteTimeDomainData = function(array) {
                __origGetByteTime.apply(this, arguments);
                var rand = __seededRandom(array.length + 99);
                for (var i = 0; i < array.length; i++) {
                    if (rand() < 0.015) array[i] = Math.max(0, Math.min(255, array[i] + (rand()<0.5?1:-1)));
                }
            };
        }
        return analyser;
    };
}

// ===== 9. toString 伪装（含 eval/setTimeout/setInterval）=====
const __origToString = Function.prototype.toString;
Function.prototype.toString = function() {
    try {
        // 对被脚本覆盖的函数，返回 native code 伪装，防止 toString() 暴露自定义函数体
        try { if (window.__spoofedFns && window.__spoofedFns.indexOf(this) !== -1) return 'function query() { [native code] }'; } catch(e){}
        var result = __origToString.call(this);
        if (result.indexOf('[native code]') !== -1) return result;
        return result;
    } catch(e) { return 'function () { [native code] }'; }
};
try {
    eval.toString = function(){ return 'function eval() { [native code] }'; };
    setTimeout.toString = function(){ return 'function setTimeout() { [native code] }'; };
    setInterval.toString = function(){ return 'function setInterval() { [native code] }'; };
    Function.prototype.toString.toString = function(){ return 'function toString() { [native code] }'; };
} catch(e){}

// ===== 10. 错误栈伪装（清理 playwright/selenium 痕迹）=====
Object.defineProperty(Error, 'stackTraceLimit', { value: 10, writable: true });
try {
    if (Error.prepareStackTrace) {
        var __origPrepare = Error.prepareStackTrace;
        Error.prepareStackTrace = function(error, stack) {
            var result = __origPrepare(error, stack);
            if (typeof result === 'string') {
                return result.replace(/playwright|puppeteer|selenium|webdriver|cdc_/gi, '');
            }
            return result;
        };
    }
} catch(e){}

// ===== 11. 连接属性伪造 =====
Object.defineProperty(navigator, 'connection', {
    get: function(){ return {
        effectiveType:'4g', rtt:50, downlink:10, saveData:false,
        onchange:null, addEventListener:function(){}, removeEventListener:function(){}, dispatchEvent:function(){return true;}
    };}, configurable: true
});

// ===== 12. Intl 时区一致性伪造 =====
try {
    var __origResolved = Intl.DateTimeFormat.prototype.resolvedOptions;
    Intl.DateTimeFormat.prototype.resolvedOptions = function() {
        var opts = __origResolved.call(this);
        opts.timeZone = 'Asia/Shanghai';
        opts.locale = 'zh-CN';
        return opts;
    };
} catch(e){}

// ===== 13. matchMedia 伪造（prefers-color-scheme = light）=====
try {
    var __origMatchMedia = window.matchMedia;
    window.matchMedia = function(query) {
        var result = __origMatchMedia.call(this, query);
        if (query.indexOf('prefers-color-scheme') !== -1) {
            try { Object.defineProperty(result, 'matches', { get: function(){ return query.indexOf('light') !== -1; }, configurable: true }); } catch(e){}
        }
        return result;
    };
} catch(e){}

// ===== 14. 清理 window/document 上的自动化注入痕迹 =====
['__playwright_playwright','__pw_manual','__PW_SELENIUM__','_phantom','callPhantom','_selenium',
 'webdriver','__driver_evaluate','__webdriver_evaluate','__selenium_evaluate','__fxdriver_evaluate',
 'cdc_adoQpoasnfa76pfcZLmcfl_','cdc_asdjflasutopfhvcZLmcfl_','cdc_sdjflasutopfhvcZLmcfl_']
.forEach(function(p){
    try { delete window[p]; } catch(e){}
    try { delete document[p]; } catch(e){}
});

// ===== 15. document.documentElement.lang =====
try { document.documentElement.lang = 'zh-CN'; } catch(e){}

// ===== 17. iframe 防护：监听新 iframe 并注入基础伪装 =====
try {
    var __iframeObserver = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                if (node.tagName === 'IFRAME') {
                    try {
                        var idoc = node.contentDocument || (node.contentWindow && node.contentWindow.document);
                        if (idoc) idoc.documentElement.lang = 'zh-CN';
                    } catch(e){}
                }
            });
        });
    });
    __iframeObserver.observe(document.documentElement, { childList: true, subtree: true });
} catch(e){}

// ===== 18. 字体指纹伪造（document.fonts.status = loaded）=====
try {
    if (document.fonts) {
        Object.defineProperty(document.fonts, 'status', { get: function(){ return 'loaded'; }, configurable: true });
    }
} catch(e){}

// ===== 19. 电池 API 伪造（插电+满电，桌面端典型状态）=====
try {
    if ('getBattery' in navigator) {
        navigator.getBattery = function() {
            return Promise.resolve({
                charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1.0,
                onchargingchange: null, onchargingtimechange: null, ondischargingtimechange: null, onlevelchange: null,
                addEventListener: function(){}, removeEventListener: function(){}, dispatchEvent: function(){ return true; }
            });
        };
    }
} catch(e){}

// ===== 20. WebGL debug extension 伪造（与 getParameter 伪造保持一致）=====
try {
    var __glExt = WebGLRenderingContext.prototype.getExtension;
    WebGLRenderingContext.prototype.getExtension = function(name) {
        if (name === 'WEBGL_debug_renderer_info') {
            return { UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 };
        }
        return __glExt.call(this, name);
    };
} catch(e){}

"""


def build_stealth_script(real_ua, nav=None):
    """用真实 User-Agent 与真实硬件/平台值替换注入模板占位符，生成与运行环境一致的注入脚本。

    修复原硬编码 UA/硬件值与真实浏览器版本不一致、反而暴露自动化特征的问题；
    同时从 UA 解析出 Chrome 版本号，用于 userAgentData（UA Client Hints）伪造，
    保证 navigator.userAgent 与 navigator.userAgentData.brands 的版本完全一致。
    nav 为运行时读取的真实导航属性 dict，未提供时使用安全兜底值。
    """
    nav = nav or {}
    hw = int(nav.get("hw") or 8)
    mem = float(nav.get("mem") or 8)
    mtp = int(nav.get("mtp") or 0)
    platform = str(nav.get("platform") or "Win32")
    vendor = str(nav.get("vendor") or "Google Inc.")
    webgl_vendor = str(nav.get("webgl_vendor") or "Google Inc.")
    webgl_renderer = str(nav.get("webgl_renderer") or "ANGLE")
    # 运行时透传真实 plugins / mimeTypes（读取失败时回退到保守的常见值）
    plugins_json = json.dumps(nav.get("plugins") or [
        {"name": "PDF Viewer", "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai", "description": ""},
        {"name": "Chrome PDF Viewer", "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai", "description": ""},
        {"name": "Chromium PDF Viewer", "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai", "description": ""},
        {"name": "Microsoft Edge PDF Viewer", "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai", "description": ""},
        {"name": "WebKit built-in PDF", "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
    ], ensure_ascii=False)
    mimes_json = json.dumps(nav.get("mimes") or [
        {"type": "application/pdf", "suffixes": "pdf", "description": ""},
        {"type": "text/pdf", "suffixes": "pdf", "description": ""},
    ], ensure_ascii=False)
    m = re.search(r"Chrome/(\d+)(?:\.(\d+)\.(\d+)\.(\d+))?", real_ua)
    if m:
        major = m.group(1)
        full_ver = f"{m.group(1)}.{m.group(2) or '0'}.{m.group(3) or '0'}.{m.group(4) or '0'}"
    else:
        major, full_ver = "138", "138.0.7204.0"
    return (STEALTH_SCRIPT_TEMPLATE
            .replace("__UA_PLACEHOLDER__", real_ua)
            .replace("__CHROME_MAJOR_PLACEHOLDER__", major)
            .replace("__CHROME_VERSION_PLACEHOLDER__", full_ver)
            .replace("__HW_CONCURRENCY__", str(hw))
            .replace("__DEVICE_MEMORY__", str(mem))
            .replace("__MAX_TOUCH_POINTS__", str(mtp))
            .replace("__PLATFORM__", platform)
            .replace("__VENDOR__", vendor)
            .replace("__WEBGL_VENDOR__", webgl_vendor)
            .replace("__WEBGL_RENDERER__", webgl_renderer)
            .replace("__PLUGINS_JSON__", plugins_json)
            .replace("__MIMES_JSON__", mimes_json))

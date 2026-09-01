# -*- coding: utf-8 -*-
"""core/adaptive.py — 自适应元素定位（公共核心模块）

解决"网站改版导致固定 CSS 选择器失效"这一爬虫头号痛点。
思路移植自 D4Vinci/Scrapling 的 relocate()/相似度评分：
  1. 首次采到目标元素时，提取其"结构指纹"（tag + 属性 + 祖先路径 + 文本特征）保存；
  2. 后续页面若原选择器匹配不到，就用指纹在 DOM 里做相似度匹配，自动重定位；
  3. 相似度评分：同 tag + 属性值相似（忽略 href/src 等易变属性）+ 祖先路径相似。

适配 Playwright 同步架构，评分在浏览器端用 JS 执行（性能好、不依赖 lxml）。
"""
import json
import random

# 忽略的属性：URL 类属性随元素不同变化大，不可靠
_IGNORE_ATTRS = ("href", "src", "data-e2e", "data-index", "style")

# 浏览器端相似度计算脚本
_SIMILARITY_JS = r"""
(original, threshold) => {
  function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
  function attrs(el) {
    var a = {};
    for (var i = 0; i < el.attributes.length; i++) {
      var n = el.attributes[i].name;
      if (['href','src','data-e2e','data-index','style'].indexOf(n) >= 0) continue;
      if (n.indexOf('on') === 0) continue;  // 事件属性不可靠
      a[n] = norm(el.getAttribute(n));
    }
    return a;
  }
  function classMatch(a, b) {
    var ca = (a['class']||'').split(/\s+/).filter(Boolean);
    var cb = (b['class']||'').split(/\s+/).filter(Boolean);
    if (!ca.length || !cb.length) return null;  // 无 class 不参与评分
    var hit = 0;
    for (var i=0;i<ca.length;i++){ if (cb.indexOf(ca[i])>=0) hit++; }
    return hit / Math.max(ca.length, cb.length);
  }
  function pathOf(el) {
    var p = [];
    var n = el.parentElement;
    while (n && n !== document.body && p.length < 5) { p.push(n.tagName.toLowerCase()); n = n.parentElement; }
    return p.join('>');
  }
  // 候选：同 tag 的元素
  var cands = document.getElementsByTagName(original.tag);
  var best = null, bestScore = 0;
  for (var i = 0; i < cands.length; i++) {
    var c = cands[i];
    if (c === original.self) continue;
    var ca = attrs(c);
    var score = 0, checks = 0;
    // 属性值相似度
    var keys = {};
    for (var k in original.attrs) keys[k] = 1;
    for (var k in ca) keys[k] = 1;
    for (var k in keys) {
      if (k === 'class') continue;
      checks++;
      var oa = original.attrs[k] || '';
      var ca2 = ca[k] || '';
      if (k === 'id') { if (oa && oa === ca2) score++; }
      else if (oa && ca2 && oa.length && ca2.length) {
        // 子串/包含性近似
        if (oa === ca2 || oa.indexOf(ca2) >= 0 || ca2.indexOf(oa) >= 0) score++;
      }
    }
    // class 匹配（加分项）
    var cm = classMatch(original.attrs, ca);
    if (cm !== null) { checks++; score += cm; }
    // 祖先路径相似（权重高）
    checks++;
    var pp = pathOf(c);
    if (pp === original.path) score += 1;
    else if (pp.split('>')[0] === original.path.split('>')[0]) score += 0.5;
    var s = checks ? score / checks : 0;
    if (s > bestScore) { bestScore = s; best = c; }
  }
  if (bestScore >= threshold && best) {
    best.setAttribute('data-adap-marker', Date.now() + '-' + Math.random().toString(36).slice(2,8));
    return { score: bestScore, threshold: threshold, found: true };
  }
  return { score: bestScore, threshold: threshold, found: false };
}
"""


def _extract_fingerprint(el):
    """从 Playwright ElementHandle 提取结构指纹。"""
    try:
        return el.evaluate("""(node) => {
            function norm(s){ return (s||'').replace(/\s+/g,' ').trim(); }
            function attrs(n){
                var a={};
                for(var i=0;i<n.attributes.length;i++){
                    var k=n.attributes[i].name;
                    if(['href','src','data-e2e','data-index','style'].indexOf(k)>=0) continue;
                    if(k.indexOf('on')===0) continue;
                    a[k]=norm(n.getAttribute(k));
                }
                return a;
            }
            function path(n){
                var p=[]; var x=n.parentElement;
                while(x && x!==document.body && p.length<5){ p.push(x.tagName.toLowerCase()); x=x.parentElement; }
                return p.join('>');
            }
            return { tag: node.tagName.toLowerCase(), attrs: attrs(node), path: path(node), text: norm(node.textContent||'').slice(0,80) };
        }""")
    except Exception:
        return None


class AdaptiveLocator:
    """自适应元素定位器。

    用法：
      locator = AdaptiveLocator(page)
      el = locator.locate("note_link", selectors=[NOTE_LINK_SELECTOR], auto_save=True)
      # 下次页面改版，selectors 失效时自动用指纹重定位
    """

    def __init__(self, page=None, threshold=0.4):
        self.page = page
        self.threshold = threshold
        self._store = {}  # identifier -> fingerprint

    def attach(self, page):
        self.page = page
        return self

    def save(self, identifier, element):
        """保存元素指纹，返回指纹。"""
        fp = _extract_fingerprint(element)
        if fp:
            self._store[identifier] = fp
        return fp

    def retrieve(self, identifier):
        return self._store.get(identifier)

    def has(self, identifier):
        return identifier in self._store

    def locate(self, identifier, selectors=None, auto_save=False, use_fallback=True):
        """定位元素。

        :param identifier: 元素逻辑名（用于指纹存储/检索）
        :param selectors: 首选 CSS 选择器列表（按序尝试）
        :param auto_save: 命中后自动保存指纹
        :param use_fallback: 选择器全部失效时是否用指纹重定位
        :return: ElementHandle 或 None
        """
        if not self.page:
            raise RuntimeError("AdaptiveLocator 未绑定 page，请先 attach(page)")

        # 1. 首选选择器
        if selectors:
            for sel in selectors:
                try:
                    el = self.page.query_selector(sel)
                    if el:
                        if auto_save:
                            self.save(identifier, el)
                        return el
                except Exception:
                    continue

        # 2. 指纹重定位
        if use_fallback:
            fp = self._store.get(identifier)
            if fp:
                el = self.relocate(fp)
                if el is not None:
                    if auto_save:
                        self.save(identifier, el)
                    return el
        return None

    def relocate(self, fingerprint):
        """用指纹在页面 DOM 中重定位元素。

        JS 端给最优匹配元素打一个临时 marker 属性，Python 端据此定位后移除。
        """
        if not self.page:
            return None
        marker = None
        try:
            fp = dict(fingerprint)
            fp.pop("self", None)
            fp_str = json.dumps(fp, ensure_ascii=False)
            result = self.page.evaluate(
                f"({_SIMILARITY_JS})({fp_str}, {self.threshold})"
            )
            if result and result.get("found"):
                el = self.page.query_selector("[data-adap-marker]")
                if el:
                    try:
                        el.evaluate(
                            "(n)=>{ n.removeAttribute('data-adap-marker'); }"
                        )
                    except Exception:
                        pass
                    return el
        except Exception:
            return None
        return None

    def save_all(self, identifier, elements):
        """保存多个元素指纹（取第一个作为代表）。"""
        if elements:
            return self.save(identifier, elements[0])
        return None

    def clear(self):
        self._store.clear()

    def to_dict(self):
        return dict(self._store)

    def load_dict(self, data):
        if data:
            self._store.update(data)

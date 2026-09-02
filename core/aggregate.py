# -*- coding: utf-8 -*-
"""core/aggregate.py — 汇总聚合层（公共核心模块）

职责：把各平台 Worker 采集的结果做「公司维度」聚合，输出双层数据。
  1. 公司名识别：从标题/正文/作者名提取公司名（填充线索的「关联公司」字段）
  2. 跨平台去重：按 内容链接 + 作者ID 去重（同一线索多平台重复命中）
  3. 按公司聚合：以「每家公司」为聚合标准，生成联系池「公司档案」行
  4. 汇总：合并各平台 JSON 结果，统一字段

设计要点：
  - 聚合标准 = 公司名。同一公司在不同平台（小红书/企查查/知乎...）的线索归并到同一档案
  - 联系池行以公司名为主键，后续企查查 Worker 可回填工商字段（电话/邮箱/信用代码）
"""
import re
import time

# ---------- 公司名识别 ----------
# 中文公司后缀（按特异性从高到低）
_COMPANY_SUFFIX_PATTERN = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9（）()·&]{2,24}?"
    r"(?:股份有限公司|有限责任公司|有限公司|"
    r"科技集团|产业集团|控股集团|投资集团|集团|"
    r"科技有限公司|网络科技|信息技术|信息科技|数据科技|数字科技|"
    r"生物科技|生物医药|医疗科技|医疗器械|能源科技|新能源科技|"
    r"新材料|智能制造|智能科技|机器人|半导体|"
    r"资本|投资控股|基金管理|资产管理|咨询有限公司)"
)
# 宽松模式：只带「公司/集团」等，用于主模式失败后的兜底
_COMPANY_LOOSE_PATTERN = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9·]{2,16}?(?:公司|集团|工作室)"
)
# 不太可能是公司名的词头（过滤误报，如"没有公司/这家公司/我们公司"）
_NON_COMPANY_HINTS = (
    "没有", "什么", "这家", "那家", "我们", "你们", "他们",
    "一家", "两家", "大型", "小型", "上市", "非上市", "自己",
    "别的", "对方", "一个", "这个", "那个", "哪个", "随便",
    "就是", "公司名称", "公司名字", "母公司", "子公司", "集团化",
)


def _looks_like_company(name):
    """过滤明显不是公司名的候选。"""
    if len(name) < 2:
        return False
    if any(name.startswith(h) for h in _NON_COMPANY_HINTS):
        return False
    return True


def extract_company(text, max_candidates=2):
    """从文本中提取公司名，返回列表（按置信度排序，最多 max_candidates 个）。

    优先匹配完整公司后缀（XX有限公司/集团），失败再尝试宽松后缀。
    """
    if not text:
        return []
    # 优先完整模式
    found = _COMPANY_SUFFIX_PATTERN.findall(text)
    # 去重保序
    seen, ordered = set(), []
    for name in found:
        name = name.strip()
        if name and _looks_like_company(name) and name not in seen:
            seen.add(name)
            ordered.append(name)
    if ordered:
        return ordered[:max_candidates]
    # 宽松兜底
    loose = _COMPANY_LOOSE_PATTERN.findall(text)
    out = []
    for name in loose:
        name = name.strip()
        if name and _looks_like_company(name) and name not in seen:
            seen.add(name)
            out.append(name)
    return out[:max_candidates]


def fill_company(rows):
    """为每条线索填充「关联公司」字段（若原本为空）。"""
    for r in rows:
        if (r.get("关联公司") or "").strip():
            continue
        source = " ".join([
            str(r.get("内容标题") or ""),
            str(r.get("帖子正文") or ""),
            str(r.get("作者昵称") or ""),
        ])
        companies = extract_company(source)
        if companies:
            r["关联公司"] = companies[0]
    return rows


# ---------- 跨平台去重 ----------
def dedup_rows(rows):
    """按 内容链接 + 作者ID 去重（同一线索多平台命中只保留一份）。"""
    seen = set()
    out = []
    for r in rows:
        link = str(r.get("内容链接") or "").strip()
        author = str(r.get("作者ID") or "").strip()
        key = (link, author) if link else (author,)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ---------- 按公司聚合 ----------
def aggregate_by_company(clue_rows):
    """以「每家公司」为聚合标准，生成联系池「公司档案」行。

    同一公司名下的线索归并：统计来源平台、线索数、收集到的联系方式、
    代表标题（取第一条）、匹配板块（取首个非空）。
    """
    companies = {}
    for r in clue_rows:
        company = (str(r.get("关联公司") or "").strip()) or "未归类"
        norm = _normalize_company_name(company) or company
        info = companies.setdefault(norm, {
            "公司名": company,  # 用第一个遇到的原始显示名
            "来源平台": [],
            "线索数": 0,
            "联系方式": [],
            "代表标题": "",
            "匹配板块": "",
            "最新采集": "",
        })
        info["线索数"] += 1
        platform = str(r.get("来源平台") or "")
        if platform and platform not in info["来源平台"]:
            info["来源平台"].append(platform)
        contact = str(r.get("联系方式") or "").strip()
        if contact and contact not in info["联系方式"]:
            info["联系方式"].append(contact)
        if not info["代表标题"]:
            info["代表标题"] = str(r.get("内容标题") or "")
        if not info["匹配板块"]:
            info["匹配板块"] = str(r.get("匹配板块") or "")
        info["最新采集"] = str(r.get("采集时间") or info["最新采集"])

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    contact_rows = []
    for company in sorted(companies.keys()):
        info = companies[company]
        contact_rows.append({
            "公司名": info["公司名"],
            "统一社会信用代码": "",  # 待企查查 Worker 回填
            "所属板块": info["匹配板块"],
            "融资轮次": "",           # 待回填
            "法定代表人/董监高": "",  # 待回填
            "联系电话": "; ".join(info["联系方式"]),
            "公司邮箱": "",           # 待回填
            "注册地址": "",           # 待回填
            "公司官网": "",           # 待回填
            "融资新闻链接": "",       # 待回填
            "联系人角色": "",         # 待回填
            "跟进状态": "待联系",
            "采集时间": now,
            "来源平台": " / ".join(info["来源平台"]),   # 内部附加字段（落盘忽略）
            "线索数": info["线索数"],                   # 内部附加字段
            "代表标题": info["代表标题"],               # 内部附加字段
        })
    return contact_rows


# ---------- 公司名归一化 ----------
def _normalize_company_name(name):
    """归一化公司名用于匹配：去括号内容、去常见后缀、去空格特殊符、转小写。

    例："字节跳动有限公司" → "字节跳动"
        "北京字节跳动科技有限公司" → "北京字节跳动科技"
    仅用于匹配 key，显示仍用原始名。
    """
    if not name:
        return ""
    n = str(name).strip().lower()
    n = re.sub(r"[（(].*?[)）]", "", n)  # 去括号及内容
    # 去常见后缀（从长到短，避免短后缀先匹配）
    for suffix in ["股份有限公司", "有限责任公司", "集团有限公司", "有限公司",
                   "股份公司", "集团", "公司"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)]
            break
    n = re.sub(r"[\s\-_·&]", "", n)  # 去空格和特殊符
    return n


# ---------- 汇总入口 ----------
# 平台 → 输出通道：
#   线索平台（社交）→ 线索池（帖子/账号，联系方式待人工补）
#   联系平台（工商）→ 联系池（直接拿到电话/邮箱）
CLUE_PLATFORMS = ("xhs", "zhihu", "bilibili", "weibo", "douyin", "baidu", "maimai")
CONTACT_PLATFORMS = ("qcc", "tianyancha", "aiqicha", "itjuzi")


def merge_platform_results(results):
    """合并各平台 worker 返回的 JSON 结果（results: {platform: [rows]}）。

    :return: (clue_rows, contact_rows)
        clue_rows    = 线索平台：去重 + 公司识别后的线索池逐条行
        contact_rows = 联系池：工商平台行（优先）+ 线索侧按公司聚合的档案（补充）
    """
    # 1. 按平台通道分流
    clue_src, contact_src = [], []
    for platform, rows in results.items():
        if not isinstance(rows, list):
            continue
        if platform in CONTACT_PLATFORMS:
            contact_src.extend(rows)
        else:
            clue_src.extend(rows)
    if not clue_src and not contact_src:
        return [], []

    # 2. 线索平台：跨平台去重 + 公司识别
    clue_rows = dedup_rows(clue_src)
    clue_rows = fill_company(clue_rows)

    # 3. 线索侧按公司聚合 → 公司档案
    clue_contact = aggregate_by_company(clue_rows)

    # 4. 联系池合并：工商平台行优先，线索档案补充未覆盖公司（按公司名去重）
    contact_rows = _merge_contact(contact_src, clue_contact)

    return clue_rows, contact_rows


def _merge_contact(contact_src, clue_contact):
    """合并联系池：以「归一化公司名」为键，支持包含关系匹配（短名包含于长名视为同一家）。
    工商平台行优先，线索档案补充空字段。"""
    by_name = {}       # norm_key -> row
    norm_list = []     # 已有的 norm_key 列表（用于包含匹配查找）

    def _find_match(norm):
        """查找已有归一化名：精确匹配，或短名包含于长名（短名长度>=4，避免误匹配）。"""
        if norm in by_name:
            return norm
        for existing in norm_list:
            if len(norm) >= 4 and norm in existing:
                return existing
            if len(existing) >= 4 and existing in norm:
                return existing
        return None

    def _merge_fields(target, source):
        """把 source 中非空字段合并到 target（仅填充 target 的空字段）。"""
        for k, v in source.items():
            if v and not target.get(k):
                target[k] = v

    # 工商平台行优先
    for r in contact_src:
        name = str(r.get("公司名") or "").strip()
        if not name:
            continue
        norm = _normalize_company_name(name) or name
        match = _find_match(norm)
        if match:
            _merge_fields(by_name[match], r)
        else:
            by_name[norm] = dict(r)
            norm_list.append(norm)

    # 线索档案补充
    for r in clue_contact:
        name = str(r.get("公司名") or "").strip()
        if not name:
            continue
        norm = _normalize_company_name(name) or name
        match = _find_match(norm)
        if not match:
            by_name[norm] = dict(r)
            norm_list.append(norm)
        else:
            _merge_fields(by_name[match], r)

    return list(by_name.values())

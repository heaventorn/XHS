# -*- coding: utf-8 -*-
"""core/blacklist.py — 黑名单过滤（公共核心模块）
账号黑名单（昵称/ID）与内容不相关关键词过滤。配置由各采集器注入。
"""


BLACKLIST_AUTHORS = [
    # "账号昵称1",
    # "账号昵称2",
]


BLACKLIST_IDS = [
    "109181692",
    "49292951005",
]


IRRELEVANT_KEYWORDS = [
    # 养生健康类
    "养生", "保健", "中医", "中药", "艾灸", "拔罐", "刮痧", "推拿", "按摩", "针灸",
    "减肥", "瘦身", "健身", "瑜伽", "冥想",
    # 相亲情感类
    "相亲", "恋爱", "情感", "婚姻", "择偶", "脱单", "约会", "表白", "分手", "复合",
    "渣男", "渣女", "绿茶", "海王", "舔狗", "备胎", "暧昧", "暗恋", "初恋", "异地恋",
    # 美妆时尚类
    "美妆", "护肤", "化妆", "美甲", "美睫", "美容", "美发", "染发", "烫发", "穿搭",
    "时尚", "潮流", "奢侈品", "包包", "首饰",
    # 美食类
    "美食", "料理", "食谱", "烹饪", "烘焙", "甜品", "蛋糕", "火锅", "烧烤", "奶茶",
    "咖啡", "茶叶", "红酒", "白酒", "啤酒",
    # 旅游生活类
    "旅游", "旅行", "攻略", "景点", "打卡", "拍照", "摄影", "vlog", "日常", "生活",
    "好物", "推荐", "种草", "测评", "开箱",
    # 母婴教育类
    "母婴", "育儿", "亲子", "孕妇", "宝宝", "婴儿", "教育", "学习", "考试", "考研",
    "考公", "留学", "英语",
    # 职场副业类
    "招聘", "求职", "面试", "简历", "职场", "副业", "兼职", "赚钱", "打工", "辞职",
    "离职", "跳槽",
    # 房产汽车类
    "买房", "租房", "装修", "家居", "家具", "家电", "汽车", "车型", "二手车",
    # 娱乐游戏类
    "游戏", "电竞", "动漫", "漫画", "小说", "影视", "电影", "电视剧", "音乐", "歌曲",
    "明星", "八卦", "娱乐", "综艺", "直播", "带货",
    # 玄学星座类
    "星座", "塔罗", "命理", "风水", "算命", "占卜", "玄学", "灵异", "鬼故事",
    # 宠物收藏类
    "宠物", "猫狗", "花鸟", "收藏", "古董", "文玩",
]


def is_blacklisted(author_name, author_id=""):
    """检查作者是否在账号黑名单中。
    支持两种匹配：按昵称（BLACKLIST_AUTHORS）精确匹配，或按小红书号（BLACKLIST_IDS）精确匹配。
    均不区分大小写、去除首尾空格。"""
    if author_name:
        name = author_name.strip().lower()
        if any(name == b.strip().lower() for b in BLACKLIST_AUTHORS if b.strip()):
            return True
    if author_id:
        aid = author_id.strip()
        if any(aid == i.strip() for i in BLACKLIST_IDS if i.strip()):
            return True
    return False


def is_irrelevant_content(title):
    """检查帖子标题是否包含不相关关键词黑名单（不区分大小写）。
    命中则返回 True，表示该帖子应被跳过。只检查标题，避免正文误杀。"""
    if not title or not IRRELEVANT_KEYWORDS:
        return False
    title_lower = title.strip().lower()
    return any(kw.strip().lower() in title_lower for kw in IRRELEVANT_KEYWORDS if kw.strip())


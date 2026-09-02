# -*- coding: utf-8 -*-
"""config/settings.py — 大爬虫框架配置

集中管理：双密码验证参数、输出路径、启用的平台采集器。
各平台具体参数（关键词、采集上限）在各采集器内维护，此处只做开关。
"""
import os

# ==================== 双密码验证 ====================
# 手动访问密码（BAT 弹窗输入）
MASTER_PWD = "ACFUND"
# Argon2 组合哈希 = Argon2("ACFUND" + 本地 pwd.key 强密码)，程序外一次性生成（16MB 内存档）
# 与 XHS 原版一致，pwd.key 中为同一强密码，保证框架版与旧版密码体系互通
ARGON2_HASH = "$argon2id$v=19$m=16384,t=2,p=1$HCgmuwQA+BfTOr27ADdlVQ$LazRy4nOadH7YkzrWLj3gA2uOLA+CbSs6zZD+Y5sR+o"
# 本地强密码文件名（仅存本地、不上传仓库）
KEY_FILE = "pwd.key"

# ==================== 输出 ====================
# 输出目录（默认桌面）
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
# 输出文件名前缀
OUTPUT_PREFIX = "大爬虫采集结果"

# ==================== 平台开关 ====================
# 按需启用的采集器（True=启用）。每个启用平台 = 一个并行 Worker 进程。
# 新增平台：在 platforms/ 下创建 <name>.py（run() 返回行列表 + --output 支持），并在此追加。
ENABLED_PLATFORMS = {
    "xhs": True,     # 小红书（线索池：帖子/账号，联系方式留空待人工补）
    # "qcc": True,   # 企查查（联系池：工商电话/邮箱，当前为骨架，数据采集待开发）
    # "zhihu": False,
    # "bilibili": False,
}

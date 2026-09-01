# -*- coding: utf-8 -*-
"""大爬虫框架 · 主入口

流程：
  1. 双密码验证（手动访问密码 + 本地 pwd.key 强密码，Argon2 双校验）
  2. 按 config/settings.py 启用的平台依次运行采集器
  3. 汇总为双层 EXCEL：
       Sheet1 线索池（社交平台：帖子/账号，联系方式留空待人工补）
       Sheet2 联系池（工商数据：直接拿到电话/邮箱）

用法：
  直接运行 run.py（会先弹密码框）
  python run.py
"""
import os
import sys
import time

# 确保以框架根目录为基准（双击运行/从其他目录调用都正确）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import settings
from core import auth, storage


def verify_password():
    """双密码验证：手动密码 + 本地强密码。返回 True=通过。"""
    gate = auth.PasswordGate(
        master_pwd=settings.MASTER_PWD,
        hash_str=settings.ARGON2_HASH,
        key_file=settings.KEY_FILE,
        base_dir=BASE_DIR,
    )
    return gate.run(title="大爬虫框架 · 身份验证", prompt="请输入访问密码")


def load_crawlers():
    """按配置加载启用的平台采集器，返回 [(名称, 实例)]。"""
    crawlers = []
    if settings.ENABLED_PLATFORMS.get("xhs"):
        from platforms.xhs import XHSCrawler
        crawlers.append(("xhs", XHSCrawler()))
    # 未来新增平台在此追加
    # if settings.ENABLED_PLATFORMS.get("qcc"):
    #     from platforms.qcc import QCCCrawler
    #     crawlers.append(("qcc", QCCCrawler()))
    return crawlers


def main():
    print("=" * 60)
    print("  大爬虫框架 · 多渠道找 CFO/融资负责人")
    print("=" * 60)

    # ---- 1. 双密码验证 ----
    if not verify_password():
        print("\n[!] 密码验证失败或已取消，程序退出。")
        return 1
    print("[√] 双密码验证通过，开始运行...\n")

    # ---- 2. 运行各平台采集器 ----
    crawlers = load_crawlers()
    if not crawlers:
        print("错误：config/settings.py 中未启用任何平台采集器。")
        return 1

    all_clue_rows = []
    all_contact_rows = []

    for name, crawler in crawlers:
        print(f"\n{'=' * 60}\n开始采集平台：{crawler.platform}\n{'=' * 60}")
        try:
            rows = crawler.run()
            if name == "xhs":
                # 小红书 → 线索池（需要人工补联系方式）
                all_clue_rows.extend(rows)
                print(f"小红书采集完成，线索 {len(rows)} 条（去重后累计 {len(all_clue_rows)} 条）")
            # elif name == "qcc":
            #     all_contact_rows.extend(rows)
        except Exception as e:
            print(f"[!] 平台 {crawler.platform} 采集失败：{e}")
            continue

    # ---- 3. 双层 EXCEL 落盘 ----
    if not all_clue_rows and not all_contact_rows:
        print("\n本次未采集到任何数据，不生成 Excel。")
        return 0

    out = os.path.join(settings.OUTPUT_DIR,
                       f"{settings.OUTPUT_PREFIX}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
    storage.save_two_sheets(out, clue_rows=all_clue_rows, contact_rows=all_contact_rows)
    print(f"\n[√] 已保存到：{out}")
    print(f"    线索池 {len(all_clue_rows)} 条 / 联系池 {len(all_contact_rows)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""大爬虫框架 · 主入口（多进程并行版）

流程：
  1. 双密码验证（手动访问密码 + 本地 pwd.key 强密码，Argon2 双校验）
  2. 并行启动启用的平台采集器 Worker（每个平台一个独立进程，互不干扰）
  3. 等待全部完成，实时转发各平台日志
  4. 汇总聚合层：跨平台去重 + 公司名识别 + 按公司聚合
  5. 落盘双层 EXCEL：
       Sheet1 线索池（社交平台：帖子/账号，联系方式留空待人工补）
       Sheet2 联系池（按公司聚合的档案；企查查 Worker 可回填工商字段）

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
from core import auth, storage, worker, aggregate


def verify_password():
    """双密码验证：手动密码 + 本地强密码。返回 True=通过。"""
    gate = auth.PasswordGate(
        master_pwd=settings.MASTER_PWD,
        hash_str=settings.ARGON2_HASH,
        key_file=settings.KEY_FILE,
        base_dir=BASE_DIR,
    )
    return gate.run(title="大爬虫框架 · 身份验证", prompt="请输入访问密码")


def get_enabled_platforms():
    """返回配置中启用的平台名列表（保持配置顺序）。"""
    return [name for name, enabled in settings.ENABLED_PLATFORMS.items() if enabled]


def main():
    print("=" * 60)
    print("  大爬虫框架 · 多渠道找 CFO/融资负责人")
    print("  （多进程并行采集 → 按公司聚合）")
    print("=" * 60)

    # ---- 1. 双密码验证 ----
    if not verify_password():
        print("\n[!] 密码验证失败或已取消，程序退出。")
        return 1
    print("[√] 双密码验证通过，开始运行...\n")

    # ---- 2. 并行启动平台 Worker ----
    platforms = get_enabled_platforms()
    if not platforms:
        print("错误：config/settings.py 中未启用任何平台采集器。")
        return 1

    print(f"[并行] 启用的平台：{platforms}（每个平台一个独立进程）\n")

    def log(text):
        print(text, end="", flush=True)

    workers = worker.spawn_platform_workers(platforms, log_cb=log)
    if not workers:
        print("\n[!] 所有平台 Worker 启动失败，请检查 platforms/ 下采集器是否存在。")
        return 1

    # ---- 3. 等待全部完成并收集 ----
    print("\n[并行] 各平台 Worker 已启动，等待采集完成...\n")
    results = worker.wait_and_collect(workers, log_cb=log)

    total = sum(len(v) for v in results.values())
    print(f"\n[汇总] 各平台原始采集合计 {total} 条，进入聚合环节...")

    # ---- 4. 汇总聚合：去重 + 公司识别 + 按公司聚合 ----
    clue_rows, contact_rows = aggregate.merge_platform_results(results)
    if not clue_rows and not contact_rows:
        print("[汇总] 未采集到有效数据，不生成 Excel。")
        return 0
    print(f"[汇总] 跨平台去重后线索 {len(clue_rows)} 条，识别出公司 {len(contact_rows)} 家")

    # ---- 5. 双层 EXCEL 落盘 ----
    out = os.path.join(settings.OUTPUT_DIR,
                       f"{settings.OUTPUT_PREFIX}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
    storage.save_two_sheets(out, clue_rows=clue_rows, contact_rows=contact_rows)
    print(f"\n[√] 已保存到：{out}")
    print(f"    线索池 {len(clue_rows)} 条 / 联系池 {len(contact_rows)} 家")
    return 0


if __name__ == "__main__":
    sys.exit(main())

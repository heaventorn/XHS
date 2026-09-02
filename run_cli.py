# -*- coding: utf-8 -*-
"""命令行运行入口：无弹窗密码验证（沙箱环境 tkinter 不可用时使用）。
用法：python run_cli.py
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import settings
from core import auth as auth_mod


def cli_verify():
    """命令行双密码验证：ACFUND + pwd.key，无 GUI 弹窗。"""
    gate = auth_mod.PasswordGate(
        master_pwd=settings.MASTER_PWD,
        hash_str=settings.ARGON2_HASH,
        key_file=settings.KEY_FILE,
        base_dir=BASE_DIR,
    )
    key = gate._load_key()
    if not key:
        print(f"错误：找不到本地密钥文件 {settings.KEY_FILE}")
        return False
    if gate.verify_str(settings.MASTER_PWD + key):
        print("[√] 双密码验证通过（命令行模式）")
        return True
    print("[!] 密码验证失败")
    return False


if __name__ == "__main__":
    print("=" * 60)
    print("  大爬虫框架 · 命令行运行模式")
    print("=" * 60)

    if not cli_verify():
        sys.exit(1)

    # monkeypatch：替换 PasswordGate.run 为直接返回 True，
    # 这样 run.main() 里的 verify_password 不会再弹 GUI
    auth_mod.PasswordGate.run = lambda self, **kwargs: True

    import run
    sys.exit(run.main())

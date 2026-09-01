# -*- coding: utf-8 -*-
"""core/auth.py — 双密码验证（公共核心模块）
供所有平台采集器共用：手动输入访问密码 + 自动加载本地 pwd.key 强密码，
Argon2 校验两者拼接的哈希是否匹配内置值。

- 手动密码、内置哈希、密钥文件名均通过参数/配置传入（见 run.py / config）
- 密钥文件（pwd.key）仅存本地、不上传仓库
- 返回 0=通过 1=未通过（退出码，供 BAT 判断）

用法（由调用方传入配置）：
    from core.auth import PasswordGate
    gate = PasswordGate(master_pwd="ACFUND", hash_str="...", key_file="pwd.key")
    if gate.run():  # 弹窗验证通过
        ...
"""
import os
import sys

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _ARGON2_OK = True
except Exception:
    _ARGON2_OK = False


class PasswordGate:
    """双密码验证门：手动密码 + 本地密钥文件强密码，拼接后 Argon2 校验。"""

    def __init__(self, master_pwd, hash_str, key_file="pwd.key", base_dir=None):
        """
        :param master_pwd: 手动输入的访问密码（如 "ACFUND"）
        :param hash_str: 预生成的 Argon2 哈希（Argon2id，自含盐）
        :param key_file: 本地强密码文件名（默认 pwd.key，在框架根目录）
        :param base_dir: 框架根目录；默认取上层目录（core/ 的父目录）
        """
        self.master_pwd = master_pwd
        self.hash_str = hash_str
        self.key_file = key_file
        # 默认以本文件所在目录的父目录（框架根）作为基准
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.ph = PasswordHasher(time_cost=2, memory_cost=16384, parallelism=1) if _ARGON2_OK else None

    # ---- 密钥文件 ----
    def _load_key(self):
        """读取本地强密码明文（该文件不上传仓库）。"""
        try:
            with open(os.path.join(self.base_dir, self.key_file), "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    # ---- Argon2 校验 ----
    def _verify(self, pwd):
        """Argon2 校验；密码不匹配返回 False。"""
        if not _ARGON2_OK or self.ph is None:
            return False
        try:
            self.ph.verify(self.hash_str, pwd)
            return True
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    # ---- 弹窗验证（阻塞直到通过/取消）----
    def run(self, title="身份验证", prompt="请输入访问密码"):
        """弹出密码输入框，返回 True=通过，False=取消/失败。"""
        if not _ARGON2_OK:
            print("错误：缺少 argon2-cffi 库。请先执行: pip install argon2-cffi")
            return False

        key = self._load_key()
        if not key:
            print("错误：找不到本地密钥文件 %s，程序拒绝启动。" % self.key_file)
            return False

        try:
            import tkinter as tk
        except Exception:
            print("错误：无法加载 tkinter（Windows 系统自带，请检查 Python 安装）。")
            return False

        root = tk.Tk()
        root.title(title)
        root.geometry("340x160")
        root.resizable(False, False)
        root.eval("tk::PlaceWindow . center")

        tk.Label(root, text=prompt, font=("微软雅黑", 11)).pack(pady=(22, 6))
        entry = tk.Entry(root, show="*", font=("微软雅黑", 13), width=18, justify="center")
        entry.pack(pady=4)
        entry.focus_set()

        state = {"ok": False}
        err_label = None

        def on_ok():
            nonlocal err_label
            if self._verify(entry.get() + key):
                state["ok"] = True
                root.destroy()
            else:
                if err_label is None:
                    err_label = tk.Label(root, text="密码错误", fg="red", font=("微软雅黑", 9))
                    err_label.pack()

        def on_cancel():
            root.destroy()

        bf = tk.Frame(root)
        bf.pack(pady=12)
        tk.Button(bf, text="确定", width=8, command=on_ok, default="active").pack(side="left", padx=10)
        tk.Button(bf, text="取消", width=8, command=on_cancel).pack(side="left", padx=10)
        entry.bind("<Return>", lambda e: on_ok())
        entry.bind("<Escape>", lambda e: on_cancel())
        root.protocol("WM_DELETE_WINDOW", on_cancel)
        root.mainloop()
        return state["ok"]

    # ---- 无弹窗校验（供测试/命令行） ----
    def verify_str(self, pwd):
        """直接校验拼接后的密码串（pwd 应为 手动密码+强密码），返回 True/False。"""
        return self._verify(pwd)


def main():
    """命令行直跑：验证 ACFUND + pwd.key（默认，供测试）。"""
    if not _ARGON2_OK:
        print("错误：缺少 argon2-cffi 库。请先执行: pip install argon2-cffi")
        return 1
    # 默认配置（与 XHS 一致：ACFUND + pwd.key + 原哈希）
    gate = PasswordGate(
        master_pwd="ACFUND",
        hash_str="$argon2id$v=19$m=16384,t=2,p=1$HCgmuwQA+BfTOr27ADdlVQ$LazRy4nOadH7YkzrWLj3gA2uOLA+CbSs6zZD+Y5sR+o",
        key_file="pwd.key",
    )
    return 0 if gate.run() else 1


if __name__ == "__main__":
    sys.exit(main())

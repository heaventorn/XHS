# -*- coding: utf-8 -*-
"""core/worker.py — 多进程并行采集框架（公共核心模块）

架构：
  主进程（run.py）
    ├─ 双密码验证
    ├─ spawn_platform_workers()：为每个启用平台 Popen 一个独立子进程
    │    每个 worker = python platforms/<platform>.py --output data/results/<platform>.json
    │    子进程内：独立 Playwright + 独立登录态 + 独立断点，崩溃互不影响
    ├─ wait_and_collect()：等待全部完成，实时转发各平台日志
    └─ 汇总层（core.aggregate）按公司聚合 → 双层 EXCEL

结果传递：各 worker 把 run() 返回的行列表 dump 为 JSON 文件，主进程收集。
隔离性：进程级（Windows spawn 干净，无 pickle 限制），比线程可靠。
"""
import os
import sys
import json
import threading
import subprocess


# 各平台结果 JSON 输出目录（相对框架根）
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "results")


def _result_path(platform_name):
    """某平台的 JSON 结果路径。"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    return os.path.join(RESULTS_DIR, f"{platform_name}.json")


def _worker_command(platform_name, output_path, extra_args=None):
    """构造 worker 子进程命令：python platforms/<name>.py --output <path>"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(base, "platforms", f"{platform_name}.py")
    cmd = [sys.executable, script, "--output", output_path]
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def spawn_platform_workers(platform_names, extra_args=None, log_cb=None):
    """并行启动多个平台采集器子进程。

    :param platform_names: 启用的平台名列表，如 ["xhs", "qcc"]
    :param extra_args: 透传给每个 worker 的额外命令行参数
    :param log_cb: 日志回调 callable(text)，用于实时转发子进程输出
    :return: worker 描述列表 [{"platform":name, "proc":Popen, "out":path}]
    """
    procs = []
    for name in platform_names:
        out = _result_path(name)
        # 清掉上次残留结果，避免汇总读到旧数据
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass
        cmd = _worker_command(name, out, extra_args)
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            )
        except Exception as e:
            if log_cb:
                log_cb(f"[worker] 启动平台 {name} 失败：{e}\n")
            continue
        procs.append({"platform": name, "proc": p, "out": out})

        # 后台线程实时转发该 worker 日志
        def _relay(proc, label):
            try:
                for line in proc.stdout:
                    if log_cb:
                        log_cb(f"[{label}] {line}")
            except Exception:
                pass

        threading.Thread(target=_relay, args=(p, name), daemon=True).start()
        if log_cb:
            log_cb(f"[worker] 已启动平台「{name}」进程 (pid={p.pid})\n")
    return procs


def wait_and_collect(workers, log_cb=None):
    """等待所有 worker 完成并收集结果。

    :param workers: spawn_platform_workers 的返回值
    :param log_cb: 日志回调
    :return: {platform_name: [row_dict, ...]}
    """
    results = {}
    for item in workers:
        name = item["platform"]
        try:
            item["proc"].wait()
        except Exception:
            pass
        rows = _read_result(item["out"])
        results[name] = rows
        if log_cb:
            log_cb(f"[worker] 平台「{name}」完成，返回 {len(rows)} 条\n")
    return results


def _read_result(path):
    """读取平台结果 JSON；缺失/损坏返回空列表。"""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def clear_all_results(platform_names):
    """清空指定平台的结果文件（下次运行前调用）。"""
    for name in platform_names:
        try:
            p = _result_path(name)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

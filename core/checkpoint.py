# -*- coding: utf-8 -*-
"""core/checkpoint.py — 断点续爬 + 流式导出（公共核心模块）

断点续爬（思想来自 Scrapling CheckpointManager）：
  - 把"已处理 ID 集合 / 待办队列 / 进度元数据"周期性地原子写入磁盘（tmp+rename）；
  - 中断（Ctrl+C / 崩溃 / 被风控踢出）后重启，从断点恢复，跳过已完成项。

流式导出：
  - 每采到一条立即追加到 JSONL 文件（不依赖内存，中断不丢）；
  - 可定期把累积数据合并到最终 Excel（调用方触发）。

与 core/storage 配合：storage 负责双层 Excel 最终落盘，checkpoint 负责运行期进度保护。
"""
import os
import json
import time
import threading


class CheckpointStore:
    """运行期进度检查点（JSON，原子写）。"""

    def __init__(self, crawldir, name="checkpoint", interval=60.0):
        """
        :param crawldir: 检查点目录
        :param name: 检查点文件名（不含扩展名）
        :param interval: 自动保存间隔（秒）
        """
        self.crawldir = crawldir
        self._path = os.path.join(crawldir, f"{name}.json")
        self._tmp = self._path + ".tmp"
        self.interval = interval
        self._last_save = time.time()
        self._lock = threading.Lock()

        # 运行期状态
        self.seen_ids = set()          # 已处理 ID（去重 + 断点）
        self.todo_queue = []           # 待办项列表
        self.progress = {}             # 任意进度元数据 {key: value}
        self.finished = False

        self._load()

    # ---------- 状态 ----------
    def mark_done(self, item_id):
        self.seen_ids.add(str(item_id))

    def is_done(self, item_id):
        return str(item_id) in self.seen_ids

    def add_todo(self, item):
        self.todo_queue.append(item)

    def next_todo(self):
        return self.todo_queue.pop(0) if self.todo_queue else None

    # ---------- 持久化 ----------
    def save(self, force=False):
        """原子保存检查点。可设置 force=True 强制立即保存。"""
        if not force and time.time() - self._last_save < self.interval:
            return
        with self._lock:
            data = {
                "seen_ids": sorted(self.seen_ids),
                "todo_queue": self.todo_queue,
                "progress": self.progress,
                "finished": self.finished,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            try:
                os.makedirs(self.crawldir, exist_ok=True)
                with open(self._tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(self._tmp, self._path)  # 原子替换
                self._last_save = time.time()
                return True
            except Exception:
                return False

    def _load(self):
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.seen_ids = set(data.get("seen_ids", []))
                self.todo_queue = data.get("todo_queue", [])
                self.progress = data.get("progress", {})
                self.finished = data.get("finished", False)
        except Exception:
            # 损坏则从零开始
            self.seen_ids = set()
            self.todo_queue = []
            self.progress = {}
            self.finished = False

    def has_checkpoint(self):
        return bool(os.path.exists(self._path)) and bool(
            self.seen_ids or self.todo_queue or self.finished
        )

    def clear(self):
        with self._lock:
            self.seen_ids.clear()
            self.todo_queue.clear()
            self.progress.clear()
            self.finished = False
            try:
                if os.path.exists(self._path):
                    os.remove(self._path)
            except Exception:
                pass


class StreamExporter:
    """流式导出器：每条结果立即追加到 JSONL，支持实时交付。

    与 CheckpointStore 配合：结果行写入 JSONL，ID 记入检查点；
    中断后 JSONL 已保留全部已采数据，重启从检查点续爬。
    """

    def __init__(self, filepath, fields=None):
        self.filepath = filepath
        self.fields = fields
        self.count = 0
        os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None

    def append(self, row):
        """追加一条记录到 JSONL。row 为 dict。"""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                if self.fields:
                    # 只保留声明字段，保持顺序
                    filtered = {k: row.get(k, "") for k in self.fields}
                    f.write(json.dumps(filtered, ensure_ascii=False) + "\n")
                else:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.count += 1
            return True
        except Exception:
            return False

    def append_many(self, rows):
        for r in rows:
            self.append(r)

    def load_all(self):
        """读取已导出全部记录。"""
        rows = []
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                rows.append(json.loads(line))
                            except Exception:
                                continue
        except Exception:
            pass
        return rows

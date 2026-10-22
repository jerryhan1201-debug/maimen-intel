"""本地运行状态：增量识别与“新”徽标去重。

- demo / live 各自独立的状态文件（mode 隔离）。
- 状态只记录匿名化的条目 key 与首次出现日期，不保存任何账户数据。
- 状态目录应被 .gitignore 忽略。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class StateStore:
    def __init__(self, state_dir: str | Path, mode: str):
        if mode not in ("demo", "live"):
            raise ValueError(f"未知模式：{mode}")
        self.dir = Path(state_dir)
        self.mode = mode
        self.path = self.dir / f"{mode}.json"

    def load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("seen"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"seen": {}}

    def save(self, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        tmp.replace(self.path)

    def preview_new(self, keys: list[str]) -> set[str]:
        """只读预览：返回其中“首次出现”的集合，不写盘。"""
        seen = self.load()["seen"]
        return {k for k in keys if k not in seen}

    def commit(self, keys: list[str], today: date) -> None:
        """渲染全部成功后才提交状态，失败重试不会丢失“新”识别。"""
        data = self.load()
        seen: dict = data["seen"]
        stamp = today.isoformat()
        changed = False
        for k in keys:
            if k not in seen:
                seen[k] = stamp
                changed = True
        if changed:
            self.save(data)

    def mark_and_get_new(self, keys: list[str], today: date) -> set[str]:
        """等价于 preview_new + commit（保留给不需要两阶段的调用方）。"""
        new_keys = self.preview_new(keys)
        self.commit(keys, today)
        return new_keys

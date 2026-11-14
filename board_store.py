"""读写看板快照，并保留各数据源自己的更新时间。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from et_time import BJ


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    # HTTP 线程只能读到完整的旧版或新版，不能读到写了一半的 JSON。
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def update_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp.astimezone(BJ) if stamp.tzinfo else stamp.replace(tzinfo=BJ)


def merge_todos(board: dict, path: Path) -> bool:
    todos = read_json(path)
    if not isinstance(todos.get("items"), list):
        return False
    stamp = update_time(todos.get("updated"))
    if stamp is None:
        # 兼容旧版待办快照，部署时保留已经抓到的数据。
        stamp = datetime.fromtimestamp(path.stat().st_mtime, BJ)
    prev = update_time(board.get("todo_updated"))
    if prev is not None and stamp <= prev:
        return False
    board["family"] = todos["items"]
    board["todo_updated"] = stamp.isoformat()
    return True

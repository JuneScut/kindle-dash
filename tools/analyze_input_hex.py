#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析 probe-input.sh 抓到的 /dev/input/event* 十六进制转储。

    python3 tools/analyze_input_hex.py /Volumes/Kindle/kindle-todo/input-probe

Linux input_event 在 32 位 ARM 上是 16 字节：
    timeval(4+4) | type(2) | code(2) | value(4)    全部小端
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

EV = {0: "SYN", 1: "KEY", 2: "REL", 3: "ABS"}
CODES = {
    (3, 0x00): "ABS_X", (3, 0x01): "ABS_Y",
    (3, 0x35): "ABS_MT_POSITION_X", (3, 0x36): "ABS_MT_POSITION_Y",
    (3, 0x39): "ABS_MT_TRACKING_ID", (3, 0x30): "ABS_MT_TOUCH_MAJOR",
    (1, 0x14a): "BTN_TOUCH", (1, 0x110): "BTN_LEFT", (1, 0x145): "BTN_TOOL_FINGER",
    (0, 0): "SYN_REPORT",
}

SIZE = 16


def parse(path: Path) -> list[tuple[int, int, int, int]]:
    raw = path.read_text(errors="ignore").split()
    n = len(raw) // SIZE
    out = []
    for i in range(n):
        b = bytes(int(x, 16) for x in raw[i * SIZE:(i + 1) * SIZE])
        sec = int.from_bytes(b[0:4], "little", signed=True)
        usec = int.from_bytes(b[4:8], "little", signed=True)
        typ = int.from_bytes(b[8:10], "little")
        code = int.from_bytes(b[10:12], "little")
        val = int.from_bytes(b[12:16], "little", signed=True)
        out.append((sec * 1_000_000 + usec, typ, code, val))
    return out


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    devices = root / "devices.txt"
    if devices.exists():
        print("=== /proc/bus/input/devices 摘要 ===")
        name = ""
        for line in devices.read_text(errors="ignore").splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip('"')
            elif line.startswith("H: Handlers="):
                print(f"  {name:<34} {line.split('=', 1)[1].strip()}")
        print()

    for hexf in sorted(root.glob("event*.hex")):
        events = parse(hexf)
        if not events:
            print(f"=== {hexf.name}: 空 ===")
            continue

        kinds = Counter(EV.get(t, str(t)) for _, t, _, _ in events)
        axes = Counter(CODES.get((t, c), f"code{c}") for _, t, c, _ in events
                       if (t, c) in CODES)

        print(f"=== {hexf.name}: {len(events)} 条事件 ===")
        print("  类型:", dict(kinds))
        if axes:
            print("  关键码:", dict(axes))
            xs = [v for _, t, c, v in events if (t, c) in ((3, 0x35), (3, 0x00))]
            ys = [v for _, t, c, v in events if (t, c) in ((3, 0x36), (3, 0x01))]
            if xs and ys:
                print(f"  X 范围 {min(xs)}–{max(xs)}   Y 范围 {min(ys)}–{max(ys)}")
            elif xs:
                print(f"  X 范围 {min(xs)}–{max(xs)}")
            # 时间跨度
            span = (events[-1][0] - events[0][0]) / 1e6
            print(f"  时间跨度 {span:.2f}s")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

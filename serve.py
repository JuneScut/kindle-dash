#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 Kindle 看的极简服务端。

    python3 serve.py            # -> http://0.0.0.0:8000
    python3 serve.py --port 9000

路由：
    GET /screen        给 Kindle 浏览器看：整屏图 + 每 15 分钟自动刷新（越狱前的过渡）
    GET /today.png     单张整屏图，每次请求都按本地数据快照重渲染
    GET /todos.json    原始数据
    GET /draw.txt      布局指令流
    GET /              一个很土的首页，告诉你地址和二维码

注意：这条路（浏览器）只能做到"能看"，做不成"一块屏"。
真正的常亮免维护得越狱，用 fbink 直接写 framebuffer。详见 README。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import render as R
from board_store import merge_todos, read_json, update_time, write_json
from et_time import BJ

HERE = Path(__file__).resolve().parent


def current_source() -> Path:
    for c in (HERE / "data" / "board.json", HERE / "todos.md", HERE / "todos.json"):
        if c.exists():
            return c
    return HERE / "todos.md"


# 只显示哪些清单（收集箱固定包含）。改这里就换数据源
TICKTICK_PROJECTS = "收集箱,准备学习"

# 刷新间隔（秒）。设备每轮会来读 /interval.txt，所以改这里 + 重启服务即可生效
REFRESH_INTERVAL = 600

# 数据同步使用北京时间，独立于 Kindle 的刷屏间隔。
SYNC_HOUR = 8
SYNC_RETRY_SECONDS = 30 * 60

# 每页能放几条。条数超了就自动分页
MARKET_PER_PAGE = 9
TODO_PER_PAGE = 10


def page_plan() -> list[tuple[str, int, str | None]]:
    """按当前数据量算出这一轮要有几页：(页类型, 起点, 清单名)。"""
    src = current_source()
    market: list = []
    family: list = []
    if src.suffix == ".json":
        try:
            d = json.loads(src.read_text(encoding="utf-8"))
            market = d.get("market", []) or []
            family = d.get("family", []) or []
        except (OSError, json.JSONDecodeError):
            pass

    plan: list[tuple[str, int, str | None]] = []
    for off in range(0, len(market), MARKET_PER_PAGE):
        plan.append(("market", off, None))

    # 待办按清单分页：每个清单各占自己的页
    order: list[str] = []
    buckets: dict[str, list] = {}
    for it in family:
        tag = it.get("tag", "") or "待办"
        if tag not in buckets:
            buckets[tag] = []
            order.append(tag)
        buckets[tag].append(it)
    for tag in order:
        for off in range(0, len(buckets[tag]), TODO_PER_PAGE):
            plan.append(("todo", off, tag))

    return plan or [("all", 0, None)]


def build(page: str = "all", idx: int = 0, total: int = 1,
          offset: int = 0, project: str | None = None) -> tuple[bytes, int, dict]:
    per_page = MARKET_PER_PAGE if page == "market" else TODO_PER_PAGE
    ops, count, meta = R.compose_any(current_source(), page=page,
                                     page_index=idx, page_total=total,
                                     offset=offset, per_page=per_page,
                                     project=project)
    img = R.paint(ops)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), count, meta


def run_fetch(script: str, *args: str) -> bool:
    try:
        subprocess.run([sys.executable, str(HERE / script), *args],
                       cwd=HERE, timeout=300, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  {script} 同步失败: {e}", flush=True)
        return False
    return True


def sync_todos() -> dict:
    data = HERE / "data"
    board = read_json(data / "board.json")
    if merge_todos(board, data / "todos.json"):
        write_json(data / "board.json", board)
    return board


def sync_cutoffs(now: datetime) -> tuple[datetime, datetime]:
    """最近一次已到的每天、每周同步时间。"""
    now = now.astimezone(BJ)
    daily = now.replace(hour=SYNC_HOUR, minute=0, second=0, microsecond=0)
    if daily > now:
        daily -= timedelta(days=1)
    weekly = daily - timedelta(days=daily.weekday())
    return daily, weekly


def refresh_due(now: datetime, retry_after: dict[str, float]) -> None:
    daily, weekly = sync_cutoffs(now)
    board = sync_todos()
    todo_stamp = update_time(board.get("todo_updated"))
    market_stamp = update_time(board.get("market_updated") or board.get("updated"))

    if (todo_stamp is None or todo_stamp < daily) and time.monotonic() >= retry_after.get("todo", 0):
        if run_fetch("fetch_ticktick.py", "--all", "--max", "10", "--projects", TICKTICK_PROJECTS):
            sync_todos()
        else:
            retry_after["todo"] = time.monotonic() + SYNC_RETRY_SECONDS

    if (market_stamp is None or market_stamp < weekly) and time.monotonic() >= retry_after.get("market", 0):
        if not (run_fetch("fetch_macro.py", "--current-week") and run_fetch("fetch_market.py")):
            retry_after["market"] = time.monotonic() + SYNC_RETRY_SECONDS


def auto_refresh() -> None:
    retry_after: dict[str, float] = {}
    while True:
        try:
            refresh_due(datetime.now(BJ), retry_after)
        except OSError as e:
            print(f"  读写数据快照失败: {e}", flush=True)
        time.sleep(60)


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 1))          # 不会真的发包，只为拿到出口网卡地址
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]

        if path == "/interval.txt":
            self._send(str(REFRESH_INTERVAL).encode(), "text/plain; charset=utf-8")
            return

        if path == "/pages.txt":
            self._send(str(len(page_plan())).encode(), "text/plain; charset=utf-8")
            return

        if path.startswith("/page/"):
            plan = page_plan()
            try:
                idx = int(path[len("/page/"):].replace(".png", ""))
                page, offset, project = plan[idx]
            except (ValueError, IndexError):
                self.send_error(404)
                return
            png, _c, _m = build(page, idx, len(plan), offset, project)
            self._send(png, "image/png")
            return

        if path in ("/today.png", "/today"):
            png, _count, _ = build()
            # 顺手把图落盘，方便 USB 拷贝或调试
            (HERE / "out").mkdir(exist_ok=True)
            (HERE / "out" / "today.png").write_bytes(png)
            self._send(png, "image/png")
            return

        if path in ("/data.json", "/todos.json"):
            src = current_source()
            if src.suffix == ".json":
                body = src.read_bytes()
            else:
                items, meta = R.load(src)
                body = json.dumps({"meta": meta, "items": items},
                                  ensure_ascii=False, indent=2).encode()
            self._send(body, "application/json; charset=utf-8")
            return

        if path == "/draw.txt":
            ops, _, _ = R.compose_any(current_source())
            self._send(R.to_drawlist(ops).encode(), "text/plain; charset=utf-8")
            return

        if path == "/screen":
            # 越狱前的过渡方案：包一层 HTML，靠 meta refresh 自动刷新。
            # 地址栏和工具栏藏不掉，浏览器也会自己睡过去，只能算"能看"。
            html = f"""<!doctype html><meta charset=utf-8>
<meta http-equiv="refresh" content="900">
<title>-</title>
<style>
  html,body{{margin:0;padding:0;background:#fff;overflow:hidden}}
  img{{display:block;width:100%;height:auto}}
</style>
<img src="/today.png?t={int(datetime.now().timestamp())}">
"""
            self._send(html.encode(), "text/html; charset=utf-8")
            return

        if path == "/":
            ip, port = lan_ip(), self.server.server_address[1]
            url = f"http://{ip}:{port}/screen"
            # 生成一张二维码，省得在 Kindle 上敲 URL
            qr = ""
            try:
                import qrcode  # 可选依赖
                q = qrcode.QRCode(border=1, box_size=8)
                q.add_data(url)
                q.make()
                buf = io.BytesIO()
                q.make_image().save(buf, format="PNG")
                qr = f'<img src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}" width="260">'
            except ImportError:
                qr = "<p>（装了 qrcode 就有二维码：pip3 install qrcode pillow）</p>"

            html = f"""<!doctype html><meta charset=utf-8>
<title>kindle-todo</title>
<style>body{{font:16px/1.6 -apple-system,sans-serif;max-width:640px;margin:60px auto;padding:0 20px}}</style>
<h1>kindle-todo</h1>
<p>Kindle 浏览器打开（每 15 分钟自动刷新）：<br><b><a href="{url}">{url}</a></b></p>
{qr}
<p>单张图：<a href="/today.png">/today.png</a>　原始数据：<a href="/data.json">/data.json</a> ／ 布局指令：<a href="/draw.txt">/draw.txt</a></p>"""
            self._send(html.encode(), "text/html; charset=utf-8")
            return

        self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-fetch", action="store_true", help="不自动抓数据")
    args = ap.parse_args()

    if not args.no_fetch:
        threading.Thread(target=auto_refresh, daemon=True).start()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("kindle-dash 已启动")
    print(f"  看板:      http://{lan_ip()}:{args.port}/today.png")
    print(f"  原始数据:  http://{lan_ip()}:{args.port}/data.json")
    print(f"  自动抓数据: {'关' if args.no_fetch else '北京时间每天 08:00 待办，每周一 08:00 美股大事'}")
    print("  Ctrl-C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

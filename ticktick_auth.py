#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性授权：拿到滴答清单 / TickTick 的 access token。

    python3 ticktick_auth.py --region cn      # 滴答清单（国内版，默认）
    python3 ticktick_auth.py --region intl    # TickTick（国际版）

需要先在开发者后台建一个应用，回调地址填 http://127.0.0.1:8080/callback，
然后把 Client ID / Secret 写进 data/ticktick_client.json。
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

REGIONS = {
    "cn": {"web": "https://dida365.com", "api": "https://api.dida365.com"},
    "intl": {"web": "https://ticktick.com", "api": "https://api.ticktick.com"},
}
SCOPE = "tasks:read"
PORT = 8080
REDIRECT = f"http://127.0.0.1:{PORT}/callback"

HERE = Path(__file__).resolve().parent
CLIENT_FILE = HERE / "data" / "ticktick_client.json"
TOKEN_FILE = HERE / "data" / "ticktick_token.json"


def load_client() -> tuple[str, str, str]:
    if not CLIENT_FILE.exists():
        sys.exit(
            f"缺少 {CLIENT_FILE}\n"
            "先建一个应用，然后写：\n"
            '  {"client_id": "...", "client_secret": "...", "region": "cn"}'
        )
    cfg = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    return cfg["client_id"], cfg["client_secret"], cfg.get("region", "cn")


class Catcher(BaseHTTPRequestHandler):
    code: str | None = None
    state_ok = False

    def do_GET(self):  # noqa: N802
        q = parse_qs(urlparse(self.path).query)
        if "code" in q:
            Catcher.code = q["code"][0]
            body = "<h2>授权成功</h2><p>可以关掉这个页面，回终端看结果。</p>"
        else:
            body = f"<h2>没拿到 code</h2><pre>{self.path}</pre>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=["cn", "intl"], default=None)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--redirect", default=None,
                    help="回调地址，必须和开发者后台登记的一致")
    ap.add_argument("--code", default=None,
                    help="手动模式：把浏览器地址栏里的 code 粘进来，不起本地服务")
    args = ap.parse_args()

    client_id, client_secret, region = load_client()
    region = args.region or region
    web = REGIONS[region]["web"]
    redirect = args.redirect or f"http://127.0.0.1:{args.port}/callback"

    state = secrets.token_urlsafe(12)
    url = f"{web}/oauth/authorize?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": redirect,
        "state": state,
    })

    print(f"区域: {region}   授权页: {web}")
    print("在浏览器里打开下面这个地址并点『允许』：\n")
    print(url, "\n")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass

    if args.code:
        Catcher.code = args.code.strip()
        print("用手动提供的 code")
    else:
        print(f"等待回调（监听 127.0.0.1:{args.port}）…")
        print("提示：如果卡住没反应，Ctrl-C 退出，改用 --code 手动模式")
        srv = HTTPServer(("127.0.0.1", args.port), Catcher)
        srv.handle_request()          # 只处理一次
        srv.server_close()

    if not Catcher.code:
        print("没收到授权码，重试一次")
        return 1

    print("拿到 code，换 token…")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = requests.post(
        f"{web}/oauth/token",
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": Catcher.code,
              "redirect_uri": redirect},
        timeout=30,
    )
    if r.status_code != 200:
        print("换取失败:", r.status_code, r.text[:300])
        return 1

    tok = r.json()
    tok["region"] = region
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已保存到 {TOKEN_FILE}")
    print(f"   access_token 前 8 位: {tok.get('access_token','')[:8]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从滴答清单（或 TickTick）拉未完成任务，写成 data/todos.json。

前置：先跑 ticktick_auth.py 拿到 token。

    python3 fetch_ticktick.py
    python3 fetch_ticktick.py --max 6 --days 14 --project 家庭
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import requests

REGIONS = {
    "cn": {"web": "https://dida365.com", "api": "https://api.dida365.com"},
    "intl": {"web": "https://ticktick.com", "api": "https://api.ticktick.com"},
}

BJ = ZoneInfo("Asia/Shanghai")
HERE = Path(__file__).resolve().parent
CLIENT_FILE = HERE / "data" / "ticktick_client.json"
TOKEN_FILE = HERE / "data" / "ticktick_token.json"
OUT_FILE = HERE / "data" / "todos.json"


def load_token() -> dict:
    if not TOKEN_FILE.exists():
        raise SystemExit(f"没有 {TOKEN_FILE}，先跑 python3 ticktick_auth.py")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


def save_token(tok: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_if_needed(tok: dict) -> dict:
    """token 快到期就续一次，省得半年后突然拉不到。"""
    expires_at = tok.get("expires_at") or (__import__("time").time() + tok.get("expires_in", 0))
    tok["expires_at"] = expires_at
    if not expires_at:
        # 老文件没有这个字段，按 expires_in 补齐
        if tok.get("expires_in"):
            tok["expires_at"] = time.time() + tok["expires_in"]
        else:
            return tok
    if time.time() < tok["expires_at"] - 86400:
        return tok

    if not tok.get("refresh_token"):
        # 滴答的 authorization_code 有时不返回 refresh_token，
        # 那就没法自动续期，到期后重新跑一次 ticktick_auth.py 即可。
        print("  ⚠️ 没有 refresh_token，token 到期后需要重新授权一次")
        return tok

    cfg = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    web = REGIONS[tok.get("region", "cn")]["web"]
    r = requests.post(
        f"{web}/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token",
              "refresh_token": tok["refresh_token"],
              "client_id": cfg["client_id"],
              "client_secret": cfg["client_secret"]},
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"续期失败: {r.status_code} {r.text[:200]}")
    new = r.json()
    new["region"] = tok.get("region", "cn")
    new["expires_at"] = time.time() + new.get("expires_in", 0)
    if "refresh_token" not in new:
        new["refresh_token"] = tok["refresh_token"]
    save_token(new)
    print("  token 已续期")
    return new


def parse_due(raw: str | None) -> datetime | None:
    """滴答给的是 '2026-11-01T09:00:00+0800'，带偏移没冒号。"""
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=9, help="最多几条")
    ap.add_argument("--days", type=int, default=14, help="只看未来多少天内的")
    ap.add_argument("--project", default=None, help="只要某个清单（按名字）")
    ap.add_argument("--all", action="store_true", help="包括没有截止日期的")
    ap.add_argument("--no-inbox", action="store_true", help="不包含收集箱")
    ap.add_argument("--projects", default=None,
                    help='只显示这些清单，逗号分隔，可用名字的一部分，例：--projects "收集箱,学习"')
    args = ap.parse_args()

    tok = refresh_if_needed(load_token())
    api = REGIONS[tok.get("region", "cn")]["api"]
    h = {"Authorization": f"Bearer {tok['access_token']}"}

    r = requests.get(f"{api}/open/v1/project", headers=h, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"拿清单失败: {r.status_code} {r.text[:200]}")
    projects = r.json()

    def _norm(text: str) -> str:
        """去掉 emoji/空格，只留中英文数字，方便模糊匹配。"""
        return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "")

    wanted = [_norm(x) for x in args.projects.split(",")] if args.projects else []

    def _match(name: str) -> bool:
        return (not wanted) or any(w and w in _norm(name) for w in wanted)

    targets = [p for p in projects
               if (not args.project or p.get("name") == args.project) and _match(p.get("name", ""))]
    if not targets:
        print("没匹配到清单。现有清单：", [p.get("name") for p in projects])
        return 1

    # (下标, 清单, 数据地址)。收集箱有独立端点，不在 project 列表里
    sources = [(i, p, f"{api}/open/v1/project/{p['id']}/data")
               for i, p in enumerate(targets)]
    if not args.no_inbox and not args.project and _match("收集箱"):
        sources.insert(0, (-1, {"name": "收集箱"},
                           f"{api}/open/v1/project/inbox/data"))

    today = datetime.now().date()
    horizon = today + timedelta(days=args.days)
    rows: list[dict] = []

    for pidx, p, url in sources:
        pr = requests.get(url, headers=h, timeout=30)
        if pr.status_code != 200:
            print(f"  {p.get('name')}: 拉取失败 {pr.status_code}")
            continue
        for t in (pr.json().get("tasks") or []):
            if t.get("status") == 2:          # 已完成
                continue
            due = parse_due(t.get("dueDate"))
            if due and due.tzinfo:
                due = due.astimezone(BJ)      # 接口给的常是 UTC，换算后再取日期
            if due is None:
                if not args.all:
                    continue
            else:
                if not (today - timedelta(days=365) <= due.date() <= horizon):
                    continue
            rows.append({
                "title": t.get("title", "").strip(),
                "due": due.strftime("%m-%d") if due else "",
                "tag": p.get("name", ""),
                # 有日期的排前面按日期；没日期的按"清单顺序 + 你手动拖的顺序"
                "_dated": 0 if due else 1,
                "_sort": (due.date().isoformat() if due else "9999-12-31"),
                "_proj": pidx,
                "_order": t.get("sortOrder", 0),
            })

    rows.sort(key=lambda r: (r["_dated"], r["_sort"], r["_proj"], r["_order"]))

    # 先保证"有截止日期"的上屏（按日期，逾期在最前）
    picked = [r for r in rows if r["_dated"] == 0][: args.max]

    # 还有位置，再用没日期的补齐：各清单轮流取，避免一个清单把别的挤掉
    slots = args.max - len(picked)
    if slots > 0:
        pools: dict[int, list[dict]] = {}
        for r in rows:
            if r["_dated"] == 1:
                pools.setdefault(r["_proj"], []).append(r)
        order_keys = sorted(pools)
        while slots > 0 and any(pools[k] for k in order_keys):
            for k in order_keys:
                if pools[k] and slots > 0:
                    picked.append(pools[k].pop(0))
                    slots -= 1
    rows = picked
    for r in rows:
        for k in ("_dated", "_sort", "_proj", "_order"):
            r.pop(k, None)

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"共 {len(rows)} 条 → {OUT_FILE}")
    for r in rows:
        print(f"  {r['due'] or '   ':<6} {r['title'][:24]:<26} @{r['tag']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

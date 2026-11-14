#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 Nasdaq 的财报日历拉未来 N 天的大票财报，写成 data/board.json 的 market 段。

    python3 fetch_market.py               # 未来 7 天，市值 ≥ 1000 亿美元
    python3 fetch_market.py --days 10 --min-cap 50

接口无需 key。筛选逻辑：按市值排序，每天最多留 2 家，且必须在关注名单或市值达标。
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests   # 用 requests 而不是 urllib：后者在 macOS 的 Python 上常常验不过根证书

from board_store import merge_todos, read_json, write_json
import et_time

API = "https://api.nasdaq.com/api/calendar/earnings?date={}"
SCREENER = ("https://api.nasdaq.com/api/screener/stocks"
            "?tableonly=true&limit=25&offset=0&download=true")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# 无论市值多少都保留（你特别关心的票）
WATCHLIST = {"NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO"}

TIME_CN = {"time-pre-market": "盘前", "time-after-hours": "盘后", "time-not-supplied": ""}
# 财报没有精确时刻，按惯例给个大概：盘前 7:00、盘后 16:30（美东）
EARNINGS_CLOCK = {"time-pre-market": (7, 0), "time-after-hours": (16, 30)}

# 公司名里那些没用的尾巴
SUFFIX = re.compile(
    r"[,.]?\s*(Inc\.?|Incorporated|Corp\.?|Corporation|plc|Ltd\.?|Limited|"
    r"Ord|Ordinary Shares?|Class [A-Z]|Holdings?|Group|Company|Co\.?|S\.?A\.?|AG|N\.?V\.?).*$",
    re.I)


def norm_sym(sym: str) -> str:
    """BRK.A / BRK/A / brk.a 统一成 BRKA"""
    return (sym or "").upper().replace(".", "").replace("/", "").strip()


def load_us_symbols(here: Path, max_age_days: int = 7) -> set[str]:
    """从纳斯达克筛选器拉一份"美国公司"白名单，缓存一周。

    财报日历里混着 ADR 和海外上市（三菱日联、巴西石油…），
    这个名单用来把它们滤掉。拉失败就返回空集合，表示不过滤。
    """
    cache = here / "data" / "us_symbols.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_days * 86400:
        try:
            return set(json.loads(cache.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    try:
        r = requests.get(SCREENER, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        rows = ((r.json().get("data") or {}).get("rows")) or []
        us = {norm_sym(x["symbol"]) for x in rows
              if (x.get("country") or "").strip().lower() == "united states"}
        if us:
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(sorted(us)), encoding="utf-8")
            print(f"  美股白名单: {len(us)} 只（已缓存）", flush=True)
        return us
    except Exception as e:                      # noqa: BLE001
        print(f"  白名单拉取失败（本次不过滤）: {e}", flush=True)
        return set()


def load_cn_names(here: Path) -> dict[str, str]:
    f = here / "data" / "company_cn.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def short_name(name: str) -> str:
    """'Advanced Micro Devices, Inc.' -> 'Advanced Micro Devices'"""
    out = SUFFIX.sub("", name or "").strip(" ,.")
    out = out.rstrip(" &,.").strip()
    return out or (name or "")


def fetch_day(d: date) -> list[dict]:
    r = requests.get(API.format(d.isoformat()),
                     headers={"User-Agent": UA, "Accept": "application/json"},
                     timeout=30)
    r.raise_for_status()
    return ((r.json().get("data") or {}).get("rows")) or []


def cap(value) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "") or 0)
    except ValueError:
        return 0.0


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--min-cap", type=float, default=100, help="市值门槛，单位：十亿美元")
    ap.add_argument("--per-day", type=int, default=2, help="每天最多几条")
    ap.add_argument("--max-rows", type=int, default=8, help="整屏最多几条")
    ap.add_argument("-o", "--out", type=Path, default=here / "data" / "board.json")
    args = ap.parse_args()

    cn = load_cn_names(here)
    us = load_us_symbols(here)
    today = datetime.now(et_time.BJ).date()
    window = [today + timedelta(days=i) for i in range(args.days)]
    date_order = {d.strftime("%m-%d"): i for i, d in enumerate(window)}
    picked: list[dict] = []
    failed = False
    for d in window:
        if d.weekday() >= 5:            # 周末没有财报
            continue
        try:
            rows = fetch_day(d)
        except Exception as e:
            print(f"  {d} 拉取失败: {e}", flush=True)
            failed = True
            continue
        rows = [r for r in rows if (r.get("symbol") or "").strip()]
        rows.sort(key=lambda r: cap(r.get("marketCap")), reverse=True)
        chosen = [r for r in rows
                  if (not us or norm_sym(r["symbol"]) in us)      # 只要美股
                  and (r["symbol"] in WATCHLIST
                       or cap(r.get("marketCap")) >= args.min_cap * 1e9)]
        seen: set[str] = set()
        for r in chosen:
            sn = short_name(r.get("name", ""))
            if sn.lower() in seen:      # BRK.A / BRK.B 这种同一家公司只留一条
                continue
            seen.add(sn.lower())
            if len(seen) > args.per_day:
                break
            tkey = r.get("time", "")
            clock = EARNINGS_CLOCK.get(tkey)
            when = ""
            if clock:
                bj = et_time.label(et_time.at(d.year, d.month, d.day, *clock))
                when = f"{TIME_CN[tkey]}·约{bj}"

            picked.append({
                "date": d.strftime("%m-%d"),
                "symbol": r["symbol"],
                "title": cn.get(r["symbol"]) or sn,
                "name_en": sn,
                "when": when,
                "cap": round(cap(r.get("marketCap")) / 1e9),
                "hot": cap(r.get("marketCap")) >= 500e9 or r["symbol"] in WATCHLIST,
            })
        print(f"  {d}  {len(rows)} 家 → 留下 {min(len(chosen), args.per_day)}", flush=True)

    if failed:
        print("财报没有抓全，保留上一份看板")
        return 1

    # 宏观事件优先占位：手动维护在 data/macro.json
    macro: list[dict] = []
    mf = here / "data" / "macro.json"
    if mf.exists():
        try:
            for m in json.loads(mf.read_text(encoding="utf-8")).get("events", []):
                if m.get("date") in date_order:
                    macro.append({"date": m["date"], "symbol": "",
                                  "title": m.get("title", ""),
                                  "when": m.get("when", ""),
                                  "hot": bool(m.get("hot"))})
        except json.JSONDecodeError:
            pass

    room = max(2, args.max_rows - len(macro))
    if len(picked) > room:
        picked.sort(key=lambda p: p["cap"], reverse=True)
        picked = picked[:room]

    picked = sorted(macro + picked, key=lambda p: date_order[p["date"]])
    if len(picked) > args.max_rows:
        picked = picked[: args.max_rows]

    board = read_json(args.out)
    stamp = datetime.now(et_time.BJ).isoformat(timespec="seconds")
    board.update(updated=stamp, market_updated=stamp, market=picked)
    merge_todos(board, here / "data" / "todos.json")
    board.setdefault("family", [])
    write_json(args.out, board)

    print(f"\n共 {len(picked)} 条 → {args.out}")
    for p in picked:
        sym = p.get("symbol") or "—"
        capv = f"{p['cap']:>6} 十亿" if "cap" in p else "     宏观事件"
        print(f"  {p['date']}  {sym:<6} {p.get('when',''):<3} {capv}  {p['title'][:28]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

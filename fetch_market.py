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
from datetime import date, datetime, timedelta
from pathlib import Path

import requests   # 用 requests 而不是 urllib：后者在 macOS 的 Python 上常常验不过根证书

import et_time

API = "https://api.nasdaq.com/api/calendar/earnings?date={}"
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
    today = date.today()
    picked: list[dict] = []
    for i in range(args.days):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:            # 周末没有财报
            continue
        try:
            rows = fetch_day(d)
        except Exception as e:
            print(f"  {d} 拉取失败: {e}", flush=True)
            continue
        rows = [r for r in rows if (r.get("symbol") or "").strip()]
        rows.sort(key=lambda r: cap(r.get("marketCap")), reverse=True)
        chosen = [r for r in rows
                  if r["symbol"] in WATCHLIST or cap(r.get("marketCap")) >= args.min_cap * 1e9]
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

    old = {}
    if args.out.exists():
        try:
            old = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}

    # 宏观事件优先占位：手动维护在 data/macro.json
    macro: list[dict] = []
    mf = here / "data" / "macro.json"
    if mf.exists():
        try:
            for m in json.loads(mf.read_text(encoding="utf-8")).get("events", []):
                try:
                    md = datetime.strptime(m["date"], "%m-%d").replace(year=today.year).date()
                except (ValueError, KeyError):
                    continue
                if today <= md < today + timedelta(days=args.days):
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

    picked = sorted(macro + picked, key=lambda p: p["date"])
    if len(picked) > args.max_rows:
        picked = picked[: args.max_rows]

    # 家庭待办：由 fetch_ticktick.py 产出
    fam_file = here / "data" / "todos.json"
    family = []
    if fam_file.exists():
        try:
            family = json.loads(fam_file.read_text(encoding="utf-8")).get("items", [])
        except json.JSONDecodeError:
            family = []

    board = {
        "updated": datetime.now().isoformat(timespec="minutes"),
        "market": picked,
        "family": family,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n共 {len(picked)} 条 → {args.out}")
    for p in picked:
        sym = p.get("symbol") or "—"
        capv = f"{p['cap']:>6} 十亿" if "cap" in p else "     宏观事件"
        print(f"  {p['date']}  {sym:<6} {p.get('when',''):<3} {capv}  {p['title'][:28]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

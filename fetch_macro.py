#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零 API key 抓下周的宏观日历，写进 data/macro.json。

数据来自 Newsquawk 的 "Week in Focus" —— 页面里带一段 JSON-LD，正文是
「MON: ... TUE: ...」这种干净结构，比 LLM 抽取稳得多，也不用注册任何账号。

    python3 fetch_macro.py            # 抓最近一期，写 data/macro.json
    python3 fetch_macro.py --dry-run  # 只看结果不落盘
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import et_time

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
INDEX = "https://www.newsquawk.com/daily/week-in-focus"

# 只留真正会动美股的
PRIORITY = [
    (r"midterm", "美国中期选举", 100),
    (r"\bFOMC\b|Fed Policy", "FOMC 利率决议", 100),
    (r"\bNFP\b|Nonfarm|Jobs Report", "非农就业报告", 95),
    (r"\bCPI\b", "CPI 通胀", 90),
    (r"\bPCE\b", "PCE 物价", 85),
    (r"ISM Manufacturing", "ISM 制造业 PMI", 80),
    (r"ISM Services", "ISM 服务业 PMI", 80),
    (r"\bGDP\b", "GDP", 75),
    (r"Retail Sales", "零售销售", 70),
    (r"\bPPI\b", "PPI", 65),
    (r"\bADP\b", "ADP 就业", 55),
    (r"JOLTS", "JOLTS 职位空缺", 55),
    (r"Treasury Quarterly Refunding", "财政部再融资", 50),
    (r"Consumer Confidence|UoM", "消费者信心", 45),
]
DAY_CN = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}

# 官方发布时刻（美东）。没有固定时刻的（如选举）留空。
RELEASE_CLOCK = {
    "美国中期选举": None,
    "FOMC 利率决议": (14, 0),
    "非农就业报告": (8, 30),
    "CPI 通胀": (8, 30),
    "PCE 物价": (8, 30),
    "GDP": (8, 30),
    "零售销售": (8, 30),
    "PPI": (8, 30),
    "ADP 就业": (8, 15),
    "JOLTS 职位空缺": (10, 0),
    "财政部再融资": (8, 30),
    "ISM 制造业 PMI": (10, 0),
    "ISM 服务业 PMI": (10, 0),
    "消费者信心": (10, 0),
}


def latest_edition() -> str:
    html = requests.get(INDEX, headers=UA, timeout=30).text
    links = re.findall(r'href="(/daily/\d+-week-in-focus-[^"]+)"', html)
    if not links:
        raise RuntimeError("索引页里找不到 Week in Focus 链接")
    return "https://www.newsquawk.com" + links[0]


def article_body(url: str) -> tuple[str, str]:
    html = requests.get(url, headers=UA, timeout=30).text
    # 一页里有好几个 ld+json 块，正文在 type=NewsArticle 那个里
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            data = data[0]
        if data.get("articleBody"):
            return data["articleBody"], data.get("headline", "")
    raise RuntimeError("页面里没有找到含正文的 JSON-LD")


def week_start(headline: str) -> date:
    """'Week In Focus 2nd-6th November 2026' -> 2026-11-02"""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s*[-–]\s*\d{1,2}(?:st|nd|rd|th)?\s+(\w+)\s+(\d{4})",
                  headline)
    if not m:
        raise RuntimeError(f"读不出周起始日期: {headline}")
    day, month_name, year = m.groups()
    d = datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y").date()
    return d - timedelta(days=d.weekday())      # 归到那一周的周一


def parse_events(body: str) -> list[dict]:
    """从 MON/TUE/... 段落里挑出美股相关项。"""
    body = body.split("WEEK AHEAD")[0]      # 后面是正文评论，不能扫
    out: list[dict] = []
    for day, offset in DAY_CN.items():
        m = re.search(rf"\b{day}:(.*?)(?=\b(?:MON|TUE|WED|THU|FRI):|$)", body, re.S)
        if not m:
            continue
        chunk = m.group(1)
        for piece in re.split(r",", chunk):
            piece = piece.strip().strip(".")
            if not re.search(r"\bUS\b", piece):
                continue
            for pat, cn, score in PRIORITY:
                if re.search(pat, piece, re.I):
                    out.append({"offset": offset, "title": cn, "score": score,
                                "raw": piece})
                    break
    # 同一天重复的（比如 ISM 制造业 + 制造业终值）只留分高的
    best: dict[tuple[int, str], dict] = {}
    for e in out:
        key = (e["offset"], e["title"])
        if key not in best or e["score"] > best[key]["score"]:
            best[key] = e
    return sorted(best.values(), key=lambda e: (e["offset"], -e["score"]))


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--current-week", action="store_true", help="等待本周或下周的周报")
    ap.add_argument("--min-score", type=int, default=60, help="低于这个分数的事件不显示")
    ap.add_argument("-o", "--out", type=Path, default=here / "data" / "macro.json")
    args = ap.parse_args()

    url = latest_edition()
    body, headline = article_body(url)
    start = week_start(headline)
    today = datetime.now(et_time.BJ).date()
    if args.current_week and start < today - timedelta(days=today.weekday()):
        print("新一周的宏观日历还没发布，保留原文件不动")
        return 1

    if not re.search(r"\b(?:MON|TUE|WED|THU|FRI):", body.split("WEEK AHEAD")[0]):
        print("没解析出事件，保留原文件不动")
        return 1

    rows = []
    per_day: dict[int, int] = {}
    for e in parse_events(body):
        d = start + timedelta(days=e["offset"])
        if d < today:                        # 已经过去的不显示
            continue
        if e["score"] < args.min_score:
            continue
        if per_day.get(e["offset"], 0) >= 2:  # 每天最多两条
            continue
        per_day[e["offset"]] = per_day.get(e["offset"], 0) + 1
        clock = RELEASE_CLOCK.get(e["title"])
        when = et_time.label(et_time.at(d.year, d.month, d.day, *clock)) if clock else ""
        rows.append({"date": d.strftime("%m-%d"), "title": e["title"], "when": when,
                     "hot": e["score"] >= 85})

    payload = {
        "_说明": "由 fetch_macro.py 自动生成，源：Newsquawk Week in Focus。手工改也可以。",
        "_source": url,
        "events": rows,
    }
    print(f"周起始 {start}  共 {len(rows)} 条")
    for r in rows:
        print(f"  {r['date']}  {'★' if r['hot'] else ' '} {r['title']}")

    if not args.dry_run:
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

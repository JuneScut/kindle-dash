#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美东时间 → 北京时间的换算。用 zoneinfo 自动处理夏令时切换。"""

from __future__ import annotations

from datetime import date, datetime

from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BJ = ZoneInfo("Asia/Shanghai")


def to_beijing(et_dt: datetime) -> datetime:
    if et_dt.tzinfo is None:
        et_dt = et_dt.replace(tzinfo=ET)
    return et_dt.astimezone(BJ)


def label(et_dt: datetime) -> str:
    """把美东时刻转成北京时间的短标签：'21:30' / '次日05:30'。"""
    b = to_beijing(et_dt)
    days = (b.date() - et_dt.date()).days
    prefix = {0: "", 1: "次日", -1: "前日"}.get(days, f"{days:+d}日")
    return f"{prefix}{b:%H:%M}"


def at(year: int, month: int, day: int, hh: int, mm: int) -> datetime:
    return datetime(year, month, day, hh, mm, tzinfo=ET)


def offset_text(d: date) -> str:
    """给定日期返回当时的 UTC 偏移，例如 'UTC-5'。自动考虑夏令时。"""
    dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=ET)
    hours = int(dt.utcoffset().total_seconds() // 3600)
    return f"UTC{hours:+d}"

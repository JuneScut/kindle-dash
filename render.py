#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kindle Paperwhite 4 (1072x1448) 待办看板。

排版一次，两种出口：
    PNG       -> 电脑上渲染整屏图，Kindle 直接显示（先跑通）
    指令流    -> 只下发"画什么"，Kindle 自己按指令画（后续，支持局部刷新）

用法:
    python3 render.py                       # 读 todos.md -> out/today.png
    python3 render.py -s todos.json         # 读 JSON
    python3 render.py --drawlist            # 输出设备端指令流（Tab 分隔）
    python3 render.py --battery 78
    python3 render.py --stamp "10月30日 周五 22:50"   # 固定页眉，调版式用
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

import et_time

# ---------------------------------------------------------------- 设备与配色

W, H = 1072, 1448          # Paperwhite 4 = 1072x1448。换机型只改这两行。
MARGIN = 72
HEADER_H = 176
FOOTER_H = 104
ROW_H = 96          # 列表行高。两页统一，紧凑，宁可下半屏留白

INK = 0                    # 纯黑
PAPER = 255                # 纯白
# e-ink 上不要用灰阶：灰看起来脏、对比度也差。只留黑白。

FONT_CACHE: dict = {}

WEIGHT_FILES = {
    "bold": [("/System/Library/Fonts/Hiragino Sans GB.ttc", 2)],
    "medium": [("/System/Library/Fonts/STHeiti Medium.ttc", 1)],
    "body": [
        ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
    ],
}

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 字体里没有彩色 emoji，直接画会变成 □。渲染前先剔掉。
EMOJI_RE = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF" "\U00002190-\U000021FF"
    "\uFE0F\u200D\u20E3" "]")


def clean(text: str) -> str:
    return EMOJI_RE.sub("", text or "").strip()

# 一条绘制指令就是一个元组，PNG 渲染器和指令流共用同一份
#   ("rect",  x, y, w, h, color)
#   ("frame", x, y, w, h, width)
#   ("line",  x, y, x2, y2, width)
#   ("text",  x, y, size, weight, color, anchor, text)


def font(size: int, weight: str = "body") -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key in FONT_CACHE:
        return FONT_CACHE[key]
    for path, index in WEIGHT_FILES.get(weight, WEIGHT_FILES["body"]):
        try:
            f = ImageFont.truetype(path, size, index=index)
            FONT_CACHE[key] = f
            return f
        except OSError:
            continue
    raise RuntimeError("找不到可用的中文字体，请改 WEIGHT_FILES")


# ---------------------------------------------------------------- 数据源

def load_markdown(path: Path) -> list[dict]:
    """解析 `- [ ] 待办 @标签 ~时间 !`。已完成的不显示。

    @标签  右下角小字
    ~时间  当天时间，例 ~18:00
    !      逾期，显示成黑底白字
    """
    items = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*[-*]\s*\[( |x|X)\]\s*(.+?)\s*$", raw)
        if not m or m.group(1).lower() == "x":
            continue
        text = m.group(2)
        overdue, tag, due = False, "", ""

        while True:
            if text.rstrip().endswith("!"):
                overdue, text = True, text.rstrip()[:-1].rstrip()
                continue
            m_tag = re.search(r"@(\S+)\s*$", text)
            if m_tag and not tag:
                tag, text = m_tag.group(1), text[: m_tag.start()].rstrip()
                continue
            m_due = re.search(r"~(\S+)\s*$", text)
            if m_due and not due:
                due, text = m_due.group(1), text[: m_due.start()].rstrip()
                continue
            break

        if text:
            items.append({"title": text, "tag": tag, "due": due, "overdue": overdue})
    return items


def load_json(path: Path) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = {k: data[k] for k in ("battery", "updated", "source") if k in data}
    return data.get("items", []), meta


def load(src: Path) -> tuple[list[dict], dict]:
    """统一入口：换数据源只改这里。飞书 / Todoist 都从这里接。"""
    if src.suffix == ".json":
        return load_json(src)
    return load_markdown(src), {}


# ---------------------------------------------------------------- 排版工具

def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_w: int, max_lines: int = 2) -> list[str]:
    """按像素宽度逐字换行，优先在空格处断。超出 max_lines 末行加省略号。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        if fnt.getlength(trial) <= max_w:
            cur = trial
            continue
        if " " in cur:
            head, _, tail = cur.rpartition(" ")
            if head:
                lines.append(head)
                cur = tail + ch
                continue
        lines.append(cur)
        cur = ch
    if cur:
        lines.append(cur)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and fnt.getlength(last + "…") > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines or [""]


CHIP_PAD = (14, 8)


def chip_size(text: str, size: int = 26) -> tuple[int, int]:
    f = font(size, "bold")
    pad_x, pad_y = CHIP_PAD
    return int(f.getlength(text)) + pad_x * 2, size + pad_y * 2


def chip_ops(x: int, y: int, text: str, size: int = 26) -> list[tuple]:
    """反白小标签（黑底白字）。"""
    pad_x, pad_y = CHIP_PAD
    w, h = chip_size(text, size)
    return [
        ("rect", x, y, w, h, INK),
        ("text", x + pad_x, y + pad_y - 2, size, "bold", PAPER, "la", text),
    ]


# ---------------------------------------------------------------- 期限文案

TIME_RE = re.compile(r"^\d{1,2}[:：]\d{2}$")
DATE_RE = re.compile(r"^(?:(\d{4})[-/.])?(\d{1,2})[-/.](\d{1,2})$")


def humanize_due(raw: str, now: datetime) -> tuple[str, bool]:
    """把 ~18:00 / ~10-31 变成给人看的文案。返回 (文案, 是否已过期)。

    墨水屏上写绝对日期没人算，写"3 天后"才有压力感 —— 规划文档第 7 节。
    """
    raw = (raw or "").strip()
    if not raw:
        return "", False

    if TIME_RE.match(raw):
        return raw.replace("：", ":"), False

    m = DATE_RE.match(raw)
    if not m:
        return raw, False

    year, mon, day = m.groups()
    today = now.date()
    try:
        y = int(year) if year else today.year
        target = date(y, int(mon), int(day))
        # 只写了月日、又已经过去大半年，那多半指明年
        if not year and (today - target).days > 180:
            target = date(y + 1, int(mon), int(day))
    except ValueError:
        return raw, False

    delta = (target - today).days
    if delta < 0:
        return f"逾期 {abs(delta)} 天", True
    return {0: "今天", 1: "明天", 2: "后天"}.get(delta, f"{delta} 天后"), False


# ---------------------------------------------------------------- 排版：只产出指令

def compose(items: list[dict], meta: dict, stamp: str | None = None) -> list[tuple]:
    ops: list[tuple] = []
    now = datetime.now()

    # ---- 顶部黑条
    ops.append(("rect", 0, 0, W, HEADER_H, INK))
    date_txt = stamp or f"{now.month}月{now.day}日 {WEEKDAYS[now.weekday()]}"
    ops.append(("text", MARGIN, HEADER_H // 2, 60, "bold", PAPER, "lm", date_txt))
    ops.append(("text", W - MARGIN, HEADER_H // 2, 34, "medium", PAPER, "rm",
                f"{len(items)} 项待办"))

    # ---- 正文区
    top = HEADER_H + 56
    bottom = H - FOOTER_H - 24
    avail = bottom - top
    gap = 32
    right_col = 168

    # 字号随条目数自适应：条目少就放大，把整屏用满，远看也认得出
    n = len(items)
    if n <= 4:
        title_size, row_pad = 62, 46
    elif n <= 6:
        title_size, row_pad = 54, 40
    elif n <= 9:
        title_size, row_pad = 48, 34
    else:
        title_size, row_pad = 42, 28

    title_f = font(title_size, "medium")
    line_h = int(title_size * 1.32)
    cb = int(title_size * 0.82)
    text_x = MARGIN + cb + gap
    text_w = W - MARGIN - right_col - text_x

    # 先排版，算出每行自然高度；没有右侧标签的条目可以用满整行
    rows: list[tuple[dict, list[str]]] = []
    for it in items:
        has_right = it.get("overdue") or it.get("due") or it.get("tag")
        w_avail = text_w if has_right else W - MARGIN - text_x
        rows.append((it, wrap(it["title"], title_f, w_avail)))
        used = sum(max(line_h * len(l), cb) + row_pad for _, l in rows)
        if used > avail:
            rows.pop()
            break

    # 剩余空白均摊成额外行距，避免内容全挤在顶部
    used = sum(max(line_h * len(l), cb) + row_pad for _, l in rows)
    bonus = min(40, max(0, (avail - used) // max(len(rows), 1)))

    y = top
    for it, lines in rows:
        row_h = max(line_h * len(lines), cb) + row_pad + bonus

        # 复选框：手画方框比字体图标更锐利，垂直对齐首行
        box_y = y + (line_h - cb) // 2
        ops.append(("frame", MARGIN, box_y, cb, cb, 4))

        # 标题
        for i, ln in enumerate(lines):
            ops.append(("text", text_x, y + i * line_h, title_size, "medium", INK, "la", ln))

        # 右列：逾期 > 期限 > 标签
        due_txt, due_over = humanize_due(it.get("due", ""), now)
        if it.get("overdue") or due_over:
            label = due_txt if due_txt.startswith("逾期") else "逾期"
            csize = 24 if len(label) <= 5 else 22
            w_chip, h_chip = chip_size(label, csize)
            ops += chip_ops(W - MARGIN - w_chip, y + (line_h - h_chip) // 2, label, csize)
        elif due_txt:
            dsize = 32 if len(due_txt) <= 5 else 28
            ops.append(("text", W - MARGIN, y + line_h // 2, dsize, "bold", INK, "rm", due_txt))
        elif it.get("tag"):
            ops.append(("text", W - MARGIN, y + line_h // 2, 28, "body", INK, "rm", it["tag"]))

        y += row_h

    rest = n - len(rows)
    if rest > 0:
        ops.append(("text", MARGIN, min(y + 4, bottom - 20), 30, "body", INK, "la",
                    f"…还有 {rest} 项"))

    # ---- 底部信息区
    fy = H - FOOTER_H
    ops.append(("line", MARGIN, fy, W - MARGIN, fy, 2))

    updated = meta.get("updated")
    if isinstance(updated, str):
        left = f"更新于 {updated[11:16]}" if len(updated) >= 16 else f"更新于 {updated}"
    else:
        left = f"更新于 {now.strftime('%H:%M')}"
    ops.append(("text", MARGIN, fy + FOOTER_H // 2 + 4, 26, "body", INK, "lm", left))

    batt = meta.get("battery")
    right = f"电量 {batt}%" if batt is not None else meta.get("label", "")
    if right:
        ops.append(("text", W - MARGIN, fy + FOOTER_H // 2 + 4, 26, "body", INK, "rm", right))

    return ops


# ---------------------------------------------------------------- 出口一：PNG

def paint(ops: list[tuple]) -> Image.Image:
    img = Image.new("L", (W, H), PAPER)      # 先灰度画，抗锯齿更好
    d = ImageDraw.Draw(img)

    for op in ops:
        kind = op[0]
        if kind == "rect":
            _, x, y, w, h, color = op
            d.rectangle([x, y, x + w, y + h], fill=color)
        elif kind == "frame":
            _, x, y, w, h, width = op
            d.rectangle([x, y, x + w, y + h], outline=INK, width=width)
        elif kind == "line":
            _, x, y, x2, y2, width = op
            d.line([x, y, x2, y2], fill=INK, width=width)
        elif kind == "text":
            _, x, y, size, weight, color, anchor, text = op
            d.text((x, y), text, font=font(size, weight), fill=color, anchor=anchor)
        else:
            raise ValueError(f"未知指令: {kind}")

    # 二值化：阈值偏黑一点，e-ink 上笔画更实。
    # 结果仍留在 8-bit 灰度里（只有 0 和 255 两个值），**不要**转成 mode "1"——
    # 1-bit PNG 在这台机器的 eips 上会画成花屏。
    return img.point(lambda p: PAPER if p >= 160 else INK)


def render(items: list[dict], meta: dict, stamp: str | None = None) -> Image.Image:
    return paint(compose(items, meta, stamp))


# ---------------------------------------------------------------- 出口二：指令流

def to_drawlist(ops: list[tuple]) -> str:
    """Tab 分隔，每行一条。设备端 while IFS=tab read 就能执行，不用 JSON 解析器。

        canvas  1072  1448
        rect    0     0     1072  176   0
        frame   72    292   40    40    4
        line    72    1344  1000  1344  2
        text    72    88    60    bold  255   lm   10月30日 周五

    文字放在最后一列（行内剩余部分），所以不用转义引号。
    """
    out = [f"canvas\t{W}\t{H}"]
    for op in ops:
        kind = op[0]
        if kind == "rect":
            _, x, y, w, h, color = op
            out.append(f"rect\t{x}\t{y}\t{w}\t{h}\t{color}")
        elif kind == "frame":
            _, x, y, w, h, width = op
            out.append(f"frame\t{x}\t{y}\t{w}\t{h}\t{width}")
        elif kind == "line":
            _, x, y, x2, y2, width = op
            out.append(f"line\t{x}\t{y}\t{x2}\t{y2}\t{width}")
        elif kind == "text":
            _, x, y, size, weight, color, anchor, text = op
            out.append(f"text\t{x}\t{y}\t{size}\t{weight}\t{color}\t{anchor}\t{text}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 双区版式

def event_day(raw: str, now: datetime) -> tuple[str, str]:
    """'11-05' -> ('周三', '11/05')；当天 -> ('今天', '11/05')。"""
    m = DATE_RE.match((raw or "").strip())
    if not m:
        return (raw or "", "")
    year, mon, day = m.groups()
    y = int(year) if year else now.date().year
    try:
        d = date(y, int(mon), int(day))
    except ValueError:
        return (raw, "")
    if d == now.date():
        return ("今天", f"{int(mon)}/{int(day)}")
    return (WEEKDAYS[d.weekday()], f"{int(mon)}/{int(day)}")


def _footer_ops(meta: dict, now: datetime, page: int | None = None,
                total: int | None = None) -> list[tuple]:
    ops: list[tuple] = []
    fy = H - FOOTER_H
    ops.append(("line", MARGIN, fy, W - MARGIN, fy, 2))
    updated = meta.get("updated")
    if isinstance(updated, str) and len(updated) >= 16:
        left = f"更新于 {updated[11:16]}"
    else:
        left = f"更新于 {now.strftime('%H:%M')}"
    ops.append(("text", MARGIN, fy + FOOTER_H // 2 + 4, 26, "body", INK, "lm", left))

    right = ""
    if page is not None and total:
        right = f"{page + 1}/{total}"          # 轮播页码
    batt = meta.get("battery")
    if batt is not None:
        right = f"电量 {batt}%" + (f"  {right}" if right else "")
    if right:
        ops.append(("text", W - MARGIN, fy + FOOTER_H // 2 + 4, 26, "body", INK, "rm", right))
    return ops


def _market_section(ops, market, market_all, y, bottom, now):
    """画「美股大事件」。同一天的多个事件合并成一组，只标一次星期。"""
    date_w = 132
    _dates = [it.get("date", "") for it in market_all if it.get("date")]
    _range = ""
    if _dates:
        _first, _last = _dates[0], _dates[-1]
        _range = (_first.replace("-", "/") if _first == _last
                  else f"{_first.replace('-', '/')}–{_last.replace('-', '/')}")
    ops.append(("text", MARGIN, y, 34, "bold", INK, "la", "美股大事件"))
    if _range:
        ops.append(("text", W - MARGIN, y + 8, 26, "body", INK, "ra", _range))
    y += 64

    # 按日期分组，保持原有顺序
    groups: list[tuple[str, list[dict]]] = []
    for it in market:
        key = it.get("date", "")
        if groups and groups[-1][0] == key:
            groups[-1][1].append(it)
        else:
            groups.append((key, [it]))

    n_events = sum(len(items) for _, items in groups)
    gap = 16 if len(groups) > 1 else 0
    avail = bottom - y - gap * (len(groups) - 1)
    row_h = min(ROW_H, avail // max(n_events, 1))

    sym_f = font(40, "bold")
    name_f = font(26, "body")

    for dkey, items in groups:
        block_h = row_h * len(items)
        wd, dt = event_day(dkey, now)

        # 对齐组内第一行：居中会让首行看起来"没有归属"
        ly = y + 2
        ops.append(("text", MARGIN, ly, 34, "bold", INK, "la", wd))
        if dt:
            ops.append(("text", MARGIN, ly + 42, 22, "body", INK, "la", dt))

        for it in items:
            sym = (it.get("symbol") or "").strip()
            name = clean(it.get("title", ""))
            when = it.get("when", "")

            sx = MARGIN + date_w
            if sym:
                sw = int(sym_f.getlength(sym))
                if it.get("hot"):
                    ops.append(("rect", sx - 10, y - 4, sw + 20, 56, INK))
                    ops.append(("text", sx, y + 2, 40, "bold", PAPER, "la", sym))
                else:
                    ops.append(("text", sx, y + 2, 40, "bold", INK, "la", sym))
                nx = sx + max(132, sw + 26)
            else:
                if it.get("hot"):
                    w = int(font(42, "bold").getlength(name))
                    ops.append(("rect", sx - 10, y - 4, w + 20, 58, INK))
                    ops.append(("text", sx, y + 2, 42, "bold", PAPER, "la", name))
                else:
                    ops.append(("text", sx, y + 2, 42, "bold", INK, "la", name))
                nx = None

            reserve = 250 if when else 10
            if nx is not None and name:
                room = W - MARGIN - reserve - nx
                while name and name_f.getlength(name) > room:
                    name = name[:-1]
                if name:
                    ops.append(("text", nx, y + 14, 26, "body", INK, "la", name))

            if when:
                ops.append(("text", W - MARGIN, y + 16, 22, "body", INK, "rm", when))
            y += row_h

        y += gap
    return y


def _todo_section(ops, family, total, y, bottom, now, paged=False, title="待办事项"):
    """画待办这一段，返回 (新 y, 实际画了几条)。"""
    cb, gap, right_w = 38, 30, 150
    text_x = MARGIN + cb + gap
    task_f = font(42, "medium")

    # 紧凑固定行高，条目少就少，下半屏留白
    row_h = min(ROW_H, (bottom - y - 64) // max(len(family), 1))

    ops.append(("text", MARGIN, y, 34, "bold", INK, "la", clean(title)))
    ops.append(("text", W - MARGIN, y + 8, 26, "body", INK, "ra", f"{total} 项"))
    y += 64

    shown = 0

    for it in family:
        if y + row_h > bottom + 20:
            break
        label, over = humanize_due(it.get("due", ""), now)
        ops.append(("frame", MARGIN, y + 6, cb, cb, 4))
        lines = wrap(clean(it.get("title", "")), task_f, W - MARGIN - right_w - text_x)
        for i, ln in enumerate(lines[:2]):
            ops.append(("text", text_x, y + i * 50, 42, "medium", INK, "la", ln))
        if label:
            if over:
                txt = label if label.startswith("逾期") else "逾期"
                cw, ch = chip_size(txt, 22)
                ops += chip_ops(W - MARGIN - cw, y + 10, txt, 22)
            else:
                ops.append(("text", W - MARGIN, y + 24, 30, "bold", INK, "rm", label))
        elif it.get("tag"):
            ops.append(("text", W - MARGIN, y + 24, 24, "body", INK, "rm", clean(it["tag"])))
        y += row_h
        shown += 1

    if shown < total and not paged:
        ops.append(("text", MARGIN, min(y, bottom - 20), 28, "body", INK, "la",
                    f"…还有 {total - shown} 项"))
    return y, shown


def compose_board(data: dict, meta: dict, stamp: str | None = None,
                  page: str = "all", page_index: int = 0,
                  page_total: int = 1, offset: int = 0,
                  per_page: int | None = None,
                  project: str | None = None) -> tuple[list[tuple], int]:
    """page: all / market / todo —— 轮播时每页各占满整屏。"""
    ops: list[tuple] = []
    now = datetime.now()
    market_all = data.get("market", [])
    family_all = data.get("family", [])

    cap = per_page or (9 if page == "market" else 10)

    if page == "market":
        market, family = market_all[offset:offset + cap], []
    elif page == "todo":
        # 按清单分页时，只取这个清单的条目
        pool = family_all
        if project:
            pool = [x for x in family_all if x.get("tag", "") == project]
        market, family = [], pool[offset:offset + cap]
        _pool_total = len(pool)
    else:
        market = market_all[: (4 if family_all else 8)]
        family = family_all

    # ---- 页眉
    ops.append(("rect", 0, 0, W, HEADER_H, INK))
    ops.append(("text", MARGIN, HEADER_H // 2, 60, "bold", PAPER, "lm",
                stamp or f"{now.month}月{now.day}日 {WEEKDAYS[now.weekday()]}"))

    tz_txt = "美东"
    for _it in market_all:
        _m = DATE_RE.match(_it.get("date", "") or "")
        if _m:
            _y, _mo, _dd = _m.groups()
            try:
                _ref = date(int(_y) if _y else now.year, int(_mo), int(_dd))
                tz_txt = f"美东 {et_time.offset_text(_ref)}"
            except ValueError:
                pass
            break
    ops.append(("text", W - MARGIN, HEADER_H // 2, 26, "medium", PAPER, "rm", tz_txt))

    y = HEADER_H + 40
    bottom = H - FOOTER_H - 20

    if market:
        y = _market_section(ops, market, market_all, y, bottom, now)

    if market and family:
        y += 6
        ops.append(("line", MARGIN, y, W - MARGIN, y, 2))
        y += 34

    shown = 0
    if family:
        y, shown = _todo_section(ops, family,
                                 _pool_total if page == "todo" else len(family_all),
                                 y, bottom, now, paged=(page != "all"),
                                 title=project or "待办事项")

    ops.extend(_footer_ops(meta, now,
                           page_index if page_total > 1 else None,
                           page_total if page_total > 1 else None))
    return ops, len(market) + shown


def compose_any(src: Path, meta_extra: dict | None = None,
                stamp: str | None = None, page: str = "all",
                page_index: int = 0, page_total: int = 1,
                offset: int = 0, per_page: int | None = None,
                project: str | None = None) -> tuple[list[tuple], int, dict]:
    """统一入口：board.json / todos.json / todos.md 都从这里出去。"""
    board = None
    if src.exists() and src.suffix == ".json":
        raw = json.loads(src.read_text(encoding="utf-8"))
        if "market" in raw or "family" in raw:
            board = raw

    meta: dict = dict(meta_extra or {})
    if board is not None:
        for k in ("updated", "battery"):
            if k in board and k not in meta:
                meta[k] = board[k]
        ops, count = compose_board(board, meta, stamp=stamp, page=page,
                                   page_index=page_index, page_total=page_total,
                                   offset=offset, per_page=per_page,
                                   project=project)
    else:
        items, m = load(src) if src.exists() else ([], {})
        meta = {**m, **meta}
        ops = compose(items, meta, stamp=stamp)
        count = len(items)
    return ops, count, meta


def main(argv: Iterable[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="渲染 Kindle 看板")
    ap.add_argument("-s", "--source", type=Path, help="board.json / todos.md / todos.json")
    ap.add_argument("-o", "--out", type=Path, default=here / "out" / "today.png")
    ap.add_argument("--battery", type=int, default=None)
    ap.add_argument("--stamp", default=None, help="固定页眉文字，调试排版用")
    ap.add_argument("--drawlist", action="store_true", help="输出指令流而不是 PNG")
    ap.add_argument("--page", choices=["all", "market", "todo"], default="all",
                    help="all=合并在屏 / market=只显示美股 / todo=只显示待办")
    ap.add_argument("--offset", type=int, default=0, help="分页起点")
    ap.add_argument("--per-page", type=int, default=None, help="每页几条")
    args = ap.parse_args(argv)

    src = args.source
    if src is None:
        for c in (here / "data" / "board.json", here / "todos.md", here / "todos.json"):
            if c.exists():
                src = c
                break
        src = src or (here / "todos.md")

    if not src.exists() and args.stamp is None:
        print(f"找不到数据源: {src}", file=sys.stderr)
        return 1

    extra = {"battery": args.battery} if args.battery is not None else None
    ops, count, _meta = compose_any(src, extra, stamp=args.stamp, page=args.page,
                                    offset=args.offset, per_page=args.per_page)

    if args.drawlist:
        sys.stdout.write(to_drawlist(ops))
        return 0

    img = paint(ops)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, optimize=True)
    print(f"{args.out}  ({W}x{H}, {count} 项, {args.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""1080px 宽移动端分享图（仅公开内容）。

- 自动换行、动态高度；footer 是普通内容块，永远不覆盖正文。
- 不使用字体可能不支持的 emoji；“新”用红底白字中文徽标绘制。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..parse import STATUS_EMPTY, STATUS_OK
from ..report import (CALENDAR_STATUS_NOTES, CATEGORY_LABELS, CATEGORY_ORDER,
                      PublicReport)

WIDTH = 1080
PADDING = 56
CONTENT_W = WIDTH - 2 * PADDING

PAPER = (250, 245, 234)
INK = (51, 48, 43)
INK_SOFT = (107, 100, 89)
RED = (198, 47, 34)
RED_DEEP = (165, 36, 24)
YELLOW = (244, 180, 0)
RULE = (216, 207, 186)
WHITE = (255, 255, 255)

_REPO_URL = "https://github.com/jerryhan1201-debug/maimen-intel"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

# 中文字体不支持的 emoji / 符号：绘制前剔除，避免出现豆腐块
_EMOJI_RE = re.compile(
    "[\U00010000-\U0010FFFF"      # 非 BMP 字符（绝大多数 emoji）
    "☀-➿"                        # 杂项符号/装饰符号
    "⬀-⯿"                        # 补充符号与箭头
    "️‍]")                   # 变体选择符 / 零宽连接符


def _strip_emoji(text: str) -> str:
    cleaned = _EMOJI_RE.sub("", text or "")
    return re.sub(r" {2,}", " ", cleaned).strip()


def find_cjk_font() -> str:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError("找不到可用的中文字体（尝试过 PingFang / STHeiti 等）")


@dataclass
class Block:
    kind: str
    text: str = ""
    is_new: bool = False


def build_blocks(public: PublicReport) -> list[Block]:
    """把公开视图铺成绘制块。隐私测试可直接断言这些块不含个人标记。

    公开版只有公共活动与通用领券指引，不含个人可领券状态。
    """
    mode = "DEMO · 虚构演示数据" if public.mode == "demo" else "LIVE · 真实查询"
    blocks: list[Block] = [
        Block("title", "麦门情报站"),
        Block("meta", f"{public.date.strftime('%Y 年 %m 月 %d 日')} · {mode} · 公开分享版"),
        Block("meta", f"来源：{public.source} · 生成于 {public.generated_at}"),
        Block("rule"),
    ]
    failed_note = CALENDAR_STATUS_NOTES.get(public.calendar_status)
    for cat in CATEGORY_ORDER:
        views = public.sections.get(cat, [])
        blocks.append(Block("h2", f"{CATEGORY_LABELS[cat]}（{len(views)}）"))
        if failed_note:
            blocks.append(Block("note", failed_note))
        elif not views:
            blocks.append(Block("note", "暂无"))
        for v in views:
            blocks.append(Block("item_title", _strip_emoji(v.campaign.title),
                                is_new=v.is_new))
            blocks.append(Block("item_meta", v.date_text))
            if v.campaign.summary:
                blocks.append(Block("item_body", _strip_emoji(v.campaign.summary)))
            for cond in v.campaign.conditions[:3]:
                blocks.append(Block("item_cond", f"· {_strip_emoji(cond)}"))
    blocks.append(Block("rule"))
    if public.anomalies:
        blocks.append(Block("h2", "数据异常"))
        for a in public.anomalies:
            blocks.append(Block("item_cond", f"· {a}"))
        blocks.append(Block("rule"))
    blocks.append(Block("guide", "领取方式：麦当劳 App / 小程序 →「麦麦省」或「优惠券」"))
    blocks.append(Block("footer", "非麦当劳官方产品，信息以官方渠道为准"))
    blocks.append(Block("footer", _REPO_URL))
    return blocks


class _Painter:
    def __init__(self, font_path: str):
        self.fonts = {
            "title": ImageFont.truetype(font_path, 84),
            "meta": ImageFont.truetype(font_path, 26),
            "h2": ImageFont.truetype(font_path, 40),
            "item_title": ImageFont.truetype(font_path, 34),
            "item_meta": ImageFont.truetype(font_path, 26),
            "item_body": ImageFont.truetype(font_path, 28),
            "item_cond": ImageFont.truetype(font_path, 24),
            "note": ImageFont.truetype(font_path, 26),
            "guide": ImageFont.truetype(font_path, 26),
            "footer": ImageFont.truetype(font_path, 24),
            "badge": ImageFont.truetype(font_path, 24),
        }
        self.colors = {
            "title": RED, "meta": INK_SOFT, "h2": INK,
            "item_title": INK, "item_meta": RED_DEEP, "item_body": INK,
            "item_cond": INK_SOFT, "note": INK_SOFT, "guide": RED_DEEP,
            "footer": INK_SOFT,
        }
        self.leading = {
            "title": 100, "meta": 40, "h2": 58, "item_title": 48,
            "item_meta": 38, "item_body": 42, "item_cond": 36, "note": 40,
            "guide": 42, "footer": 36,
        }
        self.before = {
            "title": 8, "meta": 4, "h2": 30, "item_title": 18,
            "item_meta": 2, "item_body": 4, "item_cond": 2, "note": 6,
            "rule": 26, "guide": 8, "footer": 6,
        }
        self._probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def wrap(self, text: str, kind: str, indent: int = 0) -> list[str]:
        """按像素宽度逐字换行，长标题不会溢出。"""
        font = self.fonts[kind]
        max_w = CONTENT_W - indent
        lines: list[str] = []
        current = ""
        for ch in text:
            trial = current + ch
            if self._probe.textlength(trial, font=font) > max_w and current:
                lines.append(current)
                current = ch
            else:
                current = trial
        if current or not lines:
            lines.append(current)
        return lines

    def block_height(self, block: Block) -> int:
        if block.kind == "rule":
            return self.before["rule"] * 2 + 3
        indent = 0
        if block.kind == "item_title" and block.is_new:
            indent = 56  # 给“新”徽标留位
        lines = self.wrap(block.text, block.kind, indent)
        return self.before.get(block.kind, 6) + len(lines) * self.leading[block.kind]

    def draw_block(self, draw: ImageDraw.ImageDraw, block: Block, y: int) -> int:
        kind = block.kind
        if kind == "rule":
            y += self.before["rule"]
            draw.line([(PADDING, y), (WIDTH - PADDING, y)], fill=RULE, width=2)
            draw.line([(PADDING, y + 5), (WIDTH - PADDING, y + 5)], fill=RULE, width=1)
            return y + self.before["rule"] + 3

        font = self.fonts[kind]
        color = self.colors[kind]
        y += self.before.get(kind, 6)
        indent = 0
        if kind == "item_title" and block.is_new:
            # “新”徽标：红底圆角白字
            badge_font = self.fonts["badge"]
            bw = draw.textlength("新", font=badge_font) + 22
            bh = 36
            by = y + 6
            draw.rounded_rectangle([PADDING, by, PADDING + bw, by + bh],
                                   radius=6, fill=RED)
            draw.text((PADDING + 11, by + 3), "新", font=badge_font, fill=WHITE)
            indent = int(bw) + 14

        centered = kind in ("title", "meta", "footer")
        for line in self.wrap(block.text, kind, indent):
            if centered:
                w = draw.textlength(line, font=font)
                x = (WIDTH - w) / 2
            else:
                x = PADDING + indent
            if kind == "title":
                # 字标加一点红色下划线装饰
                draw.text((x, y), line, font=font, fill=color)
                tw = draw.textlength(line, font=font)
                uy = y + self.leading[kind] - 14
                draw.rectangle([x, uy, x + tw, uy + 6], fill=YELLOW)
            else:
                draw.text((x, y), line, font=font, fill=color)
            y += self.leading[kind]
            indent = 0 if kind != "item_title" else indent
        return y


def render_png(public: PublicReport, path: str,
               font_path: str | None = None) -> tuple[str, int]:
    """渲染分享图。返回 (路径, 高度)。"""
    painter = _Painter(font_path or find_cjk_font())
    blocks = build_blocks(public)
    height = PADDING + sum(painter.block_height(b) for b in blocks) + PADDING
    image = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(image)
    y = PADDING
    for block in blocks:
        y = painter.draw_block(draw, block, y)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    image.save(path, "PNG")
    return path, height

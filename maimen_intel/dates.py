"""日期工具：北京时间与活动日期区间提取。

规则（与需求一一对应）：
- 明确写出的年份绝不被改写：``2025年10月8日至10月21日`` 在 2026 年解析仍是 2025 年。
- 缺少年份时保守处理：以基准日所在年份为准；若结束日早于开始日，结束日顺延一年（跨年）。
- 只有开始日（"10月8日起"）时不凭空补结束日。
- 特殊数字（全角、数学字母数字符号等）先做 NFKC 规范化。
- 非法日期（如 2 月 30 日）不猜测，返回不确定结果。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def beijing_now() -> datetime:
    """当前北京时间。"""
    return datetime.now(BEIJING_TZ)


def beijing_today() -> date:
    return beijing_now().date()


def normalize_text(text: str | None) -> str:
    """NFKC 规范化：全角数字、数学数字（如 𝟏𝟎）统一为 ASCII 数字。"""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)


@dataclass
class DateRange:
    start: date | None = None
    end: date | None = None
    explicit_year: bool = False
    ambiguous: bool = False  # 缺少年份或只有单边日期时为 True

    @property
    def known(self) -> bool:
        return self.start is not None or self.end is not None

    @property
    def fully_known(self) -> bool:
        return self.start is not None and self.end is not None and not self.ambiguous


# 一段“[年]月日”的通用片段
_YMD = r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
_SEP = r"(?:\s*(?:至|到|—|–|~|～|\-|—|－)\s*)"

_RE_RANGE = re.compile(_YMD + _SEP + _YMD)
_RE_RANGE_END_NO_MONTH = re.compile(_YMD + _SEP + r"(\d{1,2})\s*日")
_RE_START_FROM = re.compile(_YMD + r"\s*(?:起|开始|起售|开售|上线|启动)")
_RE_UNTIL = re.compile(r"(?:即日起|现在起|今日起)?\s*(?:至|到|截止(?:至|到)?|有效期至)\s*" + _YMD)
# 单独日期只在“整段文本就是一个日期”或明确以“有效期/日期/时间”引导时才认作有效期，
# 普通正文提及的单日不一律当作有效期。
_RE_SINGLE_LABELED = re.compile(
    r"(?:有效期|活动时间|活动日期|日期|时间)\s*[:：]?\s*" + _YMD + r"\s*$")
_RE_SINGLE_FULL = re.compile(r"^\s*" + _YMD + r"\s*$")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def extract_date_range(text: str | None, today: date) -> DateRange:
    """从中文文案中提取活动起止日期。

    返回 DateRange；解析不出任何日期时 start/end 均为 None。
    """
    if not text:
        return DateRange(ambiguous=True)
    t = normalize_text(text)

    m = _RE_RANGE.search(t)
    if m:
        sy, sm, sd, ey, em, ed = (int(g) if g else None for g in m.groups())
        start_y = sy or ey or today.year
        start = _safe_date(start_y, sm, sd)
        if ey is not None:
            # 结束年份明确写出：绝不改写
            end = _safe_date(ey, em, ed)
            if start and end and end < start:
                # 反向区间：保持原文，标为不确定
                return DateRange(start=start, end=end, explicit_year=True,
                                 ambiguous=True)
            return DateRange(start=start, end=end,
                             explicit_year=sy is not None or ey is not None,
                             ambiguous=False)
        # 结束年份缺失：保守推断；若顺延（跨年推断）则保持不确定
        end = _safe_date(start_y, em, ed)
        rolled = False
        if start and end and end < start:
            end = _safe_date(start_y + 1, em, ed)
            rolled = True
        explicit = sy is not None
        return DateRange(start=start, end=end, explicit_year=explicit,
                         ambiguous=(not explicit) or rolled)

    m = _RE_RANGE_END_NO_MONTH.search(t)
    if m:
        sy, sm, sd, ed = (int(g) if g else None for g in m.groups())
        explicit = sy is not None
        start = _safe_date(sy or today.year, sm, sd)
        end = _safe_date(sy or today.year, sm, ed) if start else None
        if start and end and end < start:
            # 同年反向（如“10月21日至8日”）：非法，标不确定
            return DateRange(start=start, end=end, explicit_year=explicit,
                             ambiguous=True)
        return DateRange(start=start, end=end, explicit_year=explicit,
                         ambiguous=not explicit)

    m = _RE_START_FROM.search(t)
    if m:
        sy, sm, sd = (int(g) if g else None for g in m.groups())
        start = _safe_date(sy or today.year, sm, sd)
        # 只有开始日：不凭空补结束日
        return DateRange(start=start, end=None, explicit_year=sy is not None,
                         ambiguous=True)

    m = _RE_UNTIL.search(t)
    if m:
        ey, em, ed = (int(g) if g else None for g in m.groups())
        end = _safe_date(ey or today.year, em, ed)
        return DateRange(start=None, end=end, explicit_year=ey is not None,
                         ambiguous=True)

    m = _RE_SINGLE_LABELED.search(t) or _RE_SINGLE_FULL.search(t)
    if m:
        groups = m.groups()
        sy, sm, sd = (int(g) if g else None for g in groups[-3:])
        d = _safe_date(sy or today.year, sm, sd)
        return DateRange(start=d, end=d, explicit_year=sy is not None,
                         ambiguous=sy is None)

    return DateRange(ambiguous=True)


def format_range(start: date | None, end: date | None) -> str:
    """展示用日期区间。"""
    if start and end:
        if start == end:
            return start.strftime("%Y-%m-%d")
        return f"{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}"
    if start:
        return f"{start.strftime('%Y-%m-%d')} 起（结束日期待核实）"
    if end:
        return f"截至 {end.strftime('%Y-%m-%d')}（开始日期待核实）"
    return "日期待核实"

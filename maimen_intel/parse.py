"""MCP 工具结果的解包与解析。

同时支持三种返回形态：
1. ``structuredContent``（优先）
2. ``content`` 中的 JSON 文本包装
3. ``content`` 中的 Markdown 文本

失败语义：
- 传输/协议/业务失败 -> status='error'，展示“查询失败”，绝不当作 0 条数据。
- 明确的空（空数组、“暂无”文案）-> status='empty'。
- 非空但无法识别的结构 -> status='unknown'，展示“结构待核实”，不谎称已核验。
- “服务繁忙，请稍后再试”之类的提示一律视为 error，不当作 empty。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .dates import DateRange, extract_date_range, normalize_text

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"

_BUSY_HINTS = ("服务繁忙", "稍后再试", "系统繁忙", "请稍后")
_EMPTY_HINTS = ("暂无", "没有", "无可用", "空空如也", "not found", "no data")


@dataclass
class ToolResult:
    """单个工具调用后的标准化结果。"""
    name: str
    status: str  # ok / empty / error / unknown
    data: Any = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


# ---------------------------------------------------------------------------
# MCP 结果解包
# ---------------------------------------------------------------------------

def unwrap_mcp_result(name: str, raw: Any) -> tuple[Any, ToolResult | None]:
    """把 MCP tools/call 的 result 解成业务 payload。

    返回 (payload, error_result)。error_result 非 None 表示该接口失败。
    """
    if not isinstance(raw, dict):
        return None, ToolResult(name, STATUS_ERROR, message="查询失败：返回格式无法识别")

    # JSON-RPC 层错误（历史出现过 -32602）
    if "error" in raw:
        err = raw.get("error") or {}
        code = err.get("code", "?") if isinstance(err, dict) else "?"
        return None, ToolResult(name, STATUS_ERROR,
                                message=f"查询失败（协议错误 {code}）")

    if raw.get("__transport_error__"):
        return None, ToolResult(name, STATUS_ERROR,
                                message=f"查询失败（{raw['__transport_error__']}）")

    if raw.get("isError"):
        text = _first_text(raw) or "接口返回错误"
        return None, ToolResult(name, STATUS_ERROR,
                                message=f"查询失败：{_sanitize_text(text)}")

    structured = raw.get("structuredContent")
    if structured is not None:
        return structured, None

    texts = [c.get("text", "") for c in raw.get("content", [])
             if isinstance(c, dict) and c.get("type") == "text"]
    if not texts:
        # 有些实现直接返回业务体
        if "code" in raw or "data" in raw:
            return raw, None
        return None, ToolResult(name, STATUS_ERROR, message="查询失败：无返回内容")

    joined = "\n".join(t for t in texts if t).strip()
    if not joined:
        return None, ToolResult(name, STATUS_ERROR, message="查询失败：返回内容为空")

    # JSON 文本包装优先
    try:
        return json.loads(joined), None
    except (ValueError, TypeError):
        pass
    # 有的内容外面包了多余字符，尝试截取第一个 { 或 [
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = joined.find(opener), joined.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(joined[i:j + 1]), None
            except (ValueError, TypeError):
                continue
    # 兜底：按 Markdown 文本返回
    return MarkdownPayload(joined), None


def _first_text(raw: dict) -> str:
    for c in raw.get("content", []) or []:
        if isinstance(c, dict) and c.get("type") == "text":
            return c.get("text", "")
    return ""


def _sanitize_text(text: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _looks_busy(message: str) -> bool:
    return any(h in message for h in _BUSY_HINTS)


_CODE_RE = re.compile(
    r"((?:券码|券号|优惠码|兑换码|会员号|couponCode)\s*[:：]?\s*)([A-Za-z0-9_\-]{4,})",
    re.IGNORECASE)


def _redact_codes(text: str) -> str:
    """券码/券号/会员号等标识一律打码，不进入任何（尤其公开）投影。"""
    return _CODE_RE.sub(lambda m: m.group(1) + "***", text or "")


_EMPTY_STRICT = re.compile(r"(暂无|没有|无).{0,8}(活动|优惠|内容|结果|数据)")


def _strict_empty(text: str) -> bool:
    """只有“纯空响应”才算 empty：短文本且含明确空提示。"""
    return len(text.strip()) <= 60 and bool(_EMPTY_STRICT.search(text))


class MarkdownPayload(str):
    """标记：payload 是 Markdown 文本而非结构化数据。"""


def _check_envelope(name: str, payload: Any) -> tuple[Any, ToolResult | None]:
    """处理 {code, data, message} 业务信封。"""
    if isinstance(payload, dict) and "code" in payload and ("data" in payload or "message" in payload):
        code = payload.get("code")
        message = str(payload.get("message") or "")
        if code != 200:
            if _looks_busy(message):
                return None, ToolResult(name, STATUS_ERROR, message="查询失败：服务繁忙，请稍后再试")
            return None, ToolResult(name, STATUS_ERROR,
                                    message=f"查询失败（code={code}）：{_sanitize_text(message)}")
        return payload.get("data"), None
    return payload, None


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Campaign:
    title: str
    date_group: str | None  # 日历分组日期（不等于活动起止日期）
    summary: str = ""
    conditions: list[str] = field(default_factory=list)
    start: date | None = None
    end: date | None = None
    date_uncertain: bool = False
    source: str = "structured"

    @property
    def key(self) -> str:
        return f"{self.title}|{self.start}|{self.end}|{self.date_group or ''}"


@dataclass
class AvailableCoupon:
    name: str
    status: str = ""
    label: str = ""


@dataclass
class MyCoupon:
    title: str
    subtitle: str = ""
    discount_desc: str = ""
    start: date | None = None
    end: date | None = None
    datetime_text: str = ""
    tags: list[str] = field(default_factory=list)
    enable: bool = True
    # 强标识仅用于内存中的领券核验，不落盘、不进公开输出
    coupon_id: str = ""
    code: str = ""

    @property
    def key(self) -> str:
        return f"{self.title}|{self.start}|{self.end}"


@dataclass
class PointsInfo:
    """积分月度汇总。字段名与接口原名保持一致；None 表示“接口未返回”。"""
    availablePoint: int | None = None
    currentMouthExpirePoint: int | None = None
    nextMouthExpirePoint: int | None = None
    lastMouthExpirePoint: int | None = None


# ---------------------------------------------------------------------------
# campaign-calendar
# ---------------------------------------------------------------------------

_CONDITION_WORDS = ("使用条件", "限", "每单", "每客", "适用", "不与其他", "不可",
                    "仅限", "需", "仅", "规则", "须知", "有效期", "核销")
_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG.sub("", text or "")


def _shorten(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", _redact_codes(text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _extract_conditions(content: str) -> list[str]:
    conditions: list[str] = []
    for line in re.split(r"[\n。；;]", content):
        line = line.strip(" -•·\t")
        if not line:
            continue
        if any(w in line for w in _CONDITION_WORDS):
            conditions.append(_shorten(line, 80))
        if len(conditions) >= 5:
            break
    return conditions


def _parse_iso_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_campaign_calendar(raw: Any, today: date) -> ToolResult:
    """解析 campaign-calendar。绝不读取 subscribedEvents（个人订阅状态）。"""
    payload, err = unwrap_mcp_result("campaign-calendar", raw)
    if err:
        return err
    data, err = _check_envelope("campaign-calendar", payload)
    if err:
        return err

    if isinstance(data, dict):
        daily = data.get("dailyList")
        if not isinstance(daily, list):
            # {} / False / "" / 缺失 等畸形结构一律 unknown，只有空数组才算 empty
            return ToolResult("campaign-calendar", STATUS_UNKNOWN,
                              message="结构待核实：dailyList 不是数组")
        if not daily:
            return ToolResult("campaign-calendar", STATUS_EMPTY, data=[],
                              message="本月暂无活动")
        campaigns: list[Campaign] = []
        for day in daily:
            if not isinstance(day, dict):
                continue
            group = day.get("date") or None
            for ev in day.get("events") or []:
                if not isinstance(ev, dict):
                    continue
                title = _redact_codes((ev.get("activityTitle") or "").strip())
                article = ev.get("articleDto") or {}
                if not title and isinstance(article, dict):
                    title = _redact_codes((article.get("title") or "").strip())
                if not title:
                    continue
                content = ""
                if isinstance(article, dict):
                    content = _strip_html(str(article.get("content") or ""))
                subtitle = _redact_codes((ev.get("activitySubTitle") or "").strip())
                summary = _shorten(content) if content else subtitle
                conditions = _extract_conditions(content)

                # 日期：优先券核销日期，其次从文案提取；日历分组日期不是活动起止日期。
                # 仅起始日（缺结束日）保持不确定，不凭空补全。
                start = end = None
                coupon_info = ev.get("couponInfo") or {}
                if isinstance(coupon_info, dict):
                    start = _parse_iso_date(coupon_info.get("tradeStartDate"))
                    end = _parse_iso_date(coupon_info.get("tradeEndDate"))
                if start and end:
                    # 反向区间（结束早于开始）：标为不确定，归入日期待核实
                    uncertain = end < start
                else:
                    dr = extract_date_range(f"{title} {subtitle} {content}", today)
                    start = start or dr.start
                    end = end or dr.end
                    if start and end and end < start:
                        uncertain = True
                    else:
                        uncertain = not (start and end) or dr.ambiguous
                campaigns.append(Campaign(
                    title=title, date_group=group, summary=summary,
                    conditions=conditions, start=start, end=end,
                    date_uncertain=uncertain, source="structured",
                ))
        if not campaigns:
            return ToolResult("campaign-calendar", STATUS_UNKNOWN, data=[],
                              message="结构待核实：dailyList 非空但未解析出活动")
        return ToolResult("campaign-calendar", STATUS_OK, data=campaigns)

    if isinstance(data, MarkdownPayload) or isinstance(data, str):
        return _parse_calendar_markdown(str(data), today)

    return ToolResult("campaign-calendar", STATUS_UNKNOWN,
                      message="结构待核实：返回既不是结构化数据也不是文本")


_MD_HEADING = re.compile(
    r"^\s*(?:#{1,4}\s*|\*\*|【)?\s*"
    r"((?:\d{4}[-/年])?\d{1,2}[-/月]\d{1,2}\s*日?(?:\s*周[一二三四五六日天])?)"
    r"\s*(?:\*\*|】)?\s*:?\s*$")
_MD_ITEM = re.compile(r"^\s*(?:[-*•·]|\d+[.、)]|【(.+?)】|\*\*(.+?)\*\*)\s*(.*)$")


def _parse_calendar_markdown(text: str, today: date) -> ToolResult:
    text = normalize_text(text)
    if not text.strip():
        return ToolResult("campaign-calendar", STATUS_ERROR,
                          message="查询失败：返回内容为空")
    # 先判“服务繁忙”类错误，再做任何空判定
    if _looks_busy(text):
        return ToolResult("campaign-calendar", STATUS_ERROR,
                          message="查询失败：服务繁忙，请稍后再试")

    campaigns: list[Campaign] = []
    current_group: str | None = None
    current: Campaign | None = None

    def _flush():
        nonlocal current
        if current is not None:
            campaigns.append(current)
            current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        hm = _MD_HEADING.match(line)
        if hm:
            _flush()
            d = _parse_iso_date(normalize_text(hm.group(1)).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-"))
            current_group = d.isoformat() if d else hm.group(1)
            continue
        im = _MD_ITEM.match(line)
        if im:
            title = (im.group(1) or im.group(2) or "").strip()
            rest = (im.group(3) or "").strip()
            if not title and rest:
                bm = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", rest)
                if bm:
                    title, rest = bm.group(1).strip(), bm.group(2).strip()
                else:
                    title, rest = rest, ""
            if title and 2 <= len(title) <= 60:
                _flush()
                current = Campaign(title=_redact_codes(title),
                                   date_group=current_group,
                                   summary=_shorten(rest), source="markdown")
                if rest:
                    current.conditions = _extract_conditions(rest)
                continue
        if current is not None:
            extra = line.strip(" -•·")
            if any(w in extra for w in _CONDITION_WORDS):
                current.conditions.append(_shorten(extra, 80))
            elif not current.summary:
                current.summary = _shorten(extra)
            else:
                current.summary = _shorten(current.summary + " " + extra, 160)

    _flush()

    for c in campaigns:
        dr = extract_date_range(f"{c.title} {c.summary} {' '.join(c.conditions)}", today)
        c.start, c.end = dr.start, dr.end
        c.date_uncertain = not dr.fully_known

    if not campaigns:
        # 只有严格匹配的纯空响应才算 empty；其余非空内容一律“结构待核实”
        if _strict_empty(text):
            return ToolResult("campaign-calendar", STATUS_EMPTY, data=[],
                              message="本月暂无活动")
        return ToolResult("campaign-calendar", STATUS_UNKNOWN, data=[],
                          message="结构待核实：Markdown 非空但未解析出活动")
    return ToolResult("campaign-calendar", STATUS_OK, data=campaigns)


# ---------------------------------------------------------------------------
# available-coupons
# ---------------------------------------------------------------------------

def parse_available_coupons(raw: Any) -> ToolResult:
    payload, err = unwrap_mcp_result("available-coupons", raw)
    if err:
        return err
    data, err = _check_envelope("available-coupons", payload)
    if err:
        return err

    # 历史问题：data/data must be array —— 非数组一律视为查询失败，不能当 0 张
    if isinstance(data, MarkdownPayload) or isinstance(data, str):
        text = str(data)
        if _looks_busy(text):
            return ToolResult("available-coupons", STATUS_ERROR,
                              message="查询失败：服务繁忙，请稍后再试")
        # 空提示只严格匹配纯空响应；“没有使用门槛”这类合法文案不算空
        if _strict_empty(text):
            return ToolResult("available-coupons", STATUS_EMPTY, data=[],
                              message="当前暂无可领取的券")
        return ToolResult("available-coupons", STATUS_UNKNOWN,
                          message="券结构待核实：返回了非结构化文本")
    if data is None:
        return ToolResult("available-coupons", STATUS_ERROR,
                          message="查询失败：data 字段缺失（data must be array）")
    if not isinstance(data, list):
        return ToolResult("available-coupons", STATUS_ERROR,
                          message="查询失败：data 不是数组（data must be array）")
    if not data:
        return ToolResult("available-coupons", STATUS_EMPTY, data=[],
                          message="当前暂无可领取的券")

    coupons: list[AvailableCoupon] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get("couponName") or "").strip()
        if not name:
            continue  # 不把任意字段当券名
        coupons.append(AvailableCoupon(
            name=name,
            status=str(item.get("couponStatus") or ""),
            label=str(item.get("label") or ""),
        ))
    if not coupons:
        return ToolResult("available-coupons", STATUS_UNKNOWN, data=[],
                          message="券结构待核实：列表非空但未识别出券名，未核验")
    return ToolResult("available-coupons", STATUS_OK, data=coupons)


# ---------------------------------------------------------------------------
# query-my-coupons
# ---------------------------------------------------------------------------

def parse_my_coupons(raw: Any, *, page: int = 1) -> ToolResult:
    payload, err = unwrap_mcp_result("query-my-coupons", raw)
    if err:
        return err
    data, err = _check_envelope("query-my-coupons", payload)
    if err:
        return err
    if not isinstance(data, dict) or not isinstance(data.get("coupons"), list):
        return ToolResult("query-my-coupons", STATUS_UNKNOWN,
                          message="结构待核实：缺少 coupons 列表")

    coupons: list[MyCoupon] = []
    skipped = 0
    for item in data["coupons"]:
        if not isinstance(item, dict):
            skipped += 1
            continue
        title = (item.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        discount = item.get("discountInfo") or {}
        tags = [str(t.get("label")) for t in item.get("tags") or []
                if isinstance(t, dict) and t.get("label")]
        coupons.append(MyCoupon(
            title=title,
            subtitle=(item.get("subtitle") or "").strip(),
            discount_desc=str(discount.get("discountDesc") or ""),
            start=_parse_iso_date(item.get("tradeStartDate")),
            end=_parse_iso_date(item.get("tradeEndDate")),
            datetime_text=str(item.get("datetimeText") or ""),
            tags=tags,
            enable=item.get("enable", 1) == 1,
            coupon_id=str(item.get("id") or ""),
            code=str(item.get("code") or ""),
        ))
    meta = {
        "totalCount": data.get("totalCount"),
        "totalPages": data.get("totalPages"),
        "currentPage": data.get("currentPage", page),
        "pageSize": data.get("pageSize"),
    }
    if not data["coupons"]:
        return ToolResult("query-my-coupons", STATUS_EMPTY,
                          data={"coupons": [], "meta": meta}, message="卡包为空")
    if not coupons:
        # 非空卡包但一条都识别不了：不能当作已解析的零券
        return ToolResult("query-my-coupons", STATUS_UNKNOWN,
                          data={"coupons": [], "meta": meta},
                          message="结构待核实：卡包记录无法识别，未核验")
    message = ""
    if skipped:
        message = f"有 {skipped} 条记录无法识别，仅展示可识别的 {len(coupons)} 张"
    return ToolResult("query-my-coupons", STATUS_OK,
                      data={"coupons": coupons, "meta": meta}, message=message)


# ---------------------------------------------------------------------------
# query-my-account
# ---------------------------------------------------------------------------

_POINT_FIELDS = ("availablePoint", "currentMouthExpirePoint",
                 "nextMouthExpirePoint", "lastMouthExpirePoint")


_INT_RE = re.compile(r"^-?\d+$")
_THOUSANDS_RE = re.compile(r"^-?\d{1,3}(,\d{3})+$")


def parse_point(value: Any) -> int | None:
    """积分值解析：只接受整数或规范千分位字符串；
    缺失/非法/小数/科学计数/NaN/Infinity 一律为 None（未知），确实为 0 才是 0。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if not value.is_integer() or abs(value) > 1e15:
            return None
        return int(value)
    if isinstance(value, str):
        text = normalize_text(value).strip()
        if _INT_RE.match(text):
            try:
                return int(text)
            except ValueError:
                return None
        if _THOUSANDS_RE.match(text):
            try:
                return int(text.replace(",", ""))
            except ValueError:
                return None
        return None  # "1e-400"、"0,,0"、"3.5" 等一律非法
    return None


def parse_my_account(raw: Any) -> ToolResult:
    """解析积分账户。账户标识（accountId 等）不进入解析结果，不落盘。"""
    payload, err = unwrap_mcp_result("query-my-account", raw)
    if err:
        return err
    data, err = _check_envelope("query-my-account", payload)
    if err:
        return err
    if not isinstance(data, dict):
        return ToolResult("query-my-account", STATUS_UNKNOWN,
                          message="结构待核实：账户数据不是对象")
    points = PointsInfo(**{f: parse_point(data.get(f)) for f in _POINT_FIELDS})
    return ToolResult("query-my-account", STATUS_OK, data=points)

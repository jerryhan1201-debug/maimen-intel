"""报告模型：把四个工具结果组织成日报视图，并严格区分私人/公开数据。

- 单接口失败不阻断日报：失败的接口进入“数据异常”区。
- 日历查询失败/未知时保留 calendar_status，各渲染层必须显示“未能核实”，
  不得给出看似确认的“暂无活动”。
- 公开视图（to_public）在类型层面就不包含任何个人数据字段，
  也不含当前用户的可领券/领取状态——公开版只有公共活动与通用领券指引。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .dates import format_range
from .parse import (STATUS_EMPTY, STATUS_ERROR, STATUS_OK, STATUS_UNKNOWN,
                    Campaign, PointsInfo, ToolResult)

ENDING_SOON_DAYS = 3  # 结束日在未来 3 天内 -> 即将结束

CATEGORY_LABELS = {
    "ongoing": "今日进行中",
    "upcoming": "即将开始",
    "ending_soon": "即将结束",
    "unverified": "日期待核实",
}

CATEGORY_ORDER = ("ongoing", "ending_soon", "upcoming", "unverified")

# 日历失败/未知时的分区提示（不伪装成“暂无活动”）
CALENDAR_STATUS_NOTES = {
    STATUS_ERROR: "活动日历查询失败，未能核实",
    STATUS_UNKNOWN: "活动日历结构待核实，未能核实",
}


def classify_campaign(c: Campaign, today: date) -> str:
    """活动分区。日期不确定的一律进“日期待核实”，不推荐为确定进行中。"""
    if c.date_uncertain or (c.start is None and c.end is None):
        return "unverified"
    if c.end is not None and today > c.end:
        return "ended"
    if c.start is not None and today < c.start:
        return "upcoming"
    if c.end is not None and (c.end - today).days <= ENDING_SOON_DAYS:
        return "ending_soon"
    return "ongoing"


@dataclass
class CampaignView:
    campaign: Campaign
    category: str
    date_text: str
    is_new: bool = False


@dataclass
class Report:
    mode: str  # demo / live
    date: date
    generated_at: str
    source: str  # 数据来源说明
    calendar_status: str = STATUS_UNKNOWN
    sections: dict[str, list[CampaignView]] = field(default_factory=dict)
    ended: list[CampaignView] = field(default_factory=list)
    available_coupons: ToolResult | None = None
    my_coupons: ToolResult | None = None      # 私人
    points: PointsInfo | None = None          # 私人
    points_status: str = STATUS_UNKNOWN       # 私人
    pagination_note: str = ""                 # 私人：如实说明分页范围
    anomalies: list[str] = field(default_factory=list)

    def campaigns(self) -> list[CampaignView]:
        out: list[CampaignView] = []
        for cat in CATEGORY_ORDER:
            out.extend(self.sections.get(cat, []))
        return out


@dataclass
class PublicReport:
    """公开视图：只含公共活动与通用领券指引，类型上不含个人字段。

    注意：刻意没有 available_coupons / my_coupons / points 字段——
    当前用户的可领券资格与状态属于个人数据，不得进入公开输出。
    """
    mode: str
    date: date
    generated_at: str
    source: str
    calendar_status: str
    sections: dict[str, list[CampaignView]]
    anomalies: list[str]  # 仅通用化提示，不含任何接口原文


def build_report(mode: str, today: date, generated_at: str, source: str,
                 calendar: ToolResult, available: ToolResult | None,
                 my_coupons: ToolResult | None, account: ToolResult | None,
                 new_keys: set[str] | None = None) -> Report:
    new_keys = new_keys or set()
    sections: dict[str, list[CampaignView]] = {k: [] for k in CATEGORY_LABELS}
    ended: list[CampaignView] = []
    anomalies: list[str] = []

    if calendar.status == STATUS_OK and calendar.data:
        seen_in_response: set[tuple] = set()
        for c in calendar.data:
            # 同一次响应内重复返回的活动去重（含内容维度）
            sig = (c.title, c.start, c.end, c.summary, tuple(c.conditions))
            if sig in seen_in_response:
                continue
            seen_in_response.add(sig)
            cat = classify_campaign(c, today)
            view = CampaignView(
                campaign=c, category=cat,
                date_text=format_range(c.start, c.end),
                is_new=c.key in new_keys,
            )
            if cat == "ended":
                ended.append(view)
            else:
                sections[cat].append(view)
    elif calendar.status == STATUS_ERROR:
        anomalies.append(f"活动日历：{calendar.message}")
    elif calendar.status == STATUS_UNKNOWN:
        anomalies.append(f"活动日历：{calendar.message or '结构待核实'}")

    if available is not None and available.status in (STATUS_ERROR, STATUS_UNKNOWN):
        anomalies.append(f"可领券：{available.message}")

    points = None
    points_status = STATUS_UNKNOWN
    if account is not None:
        if account.status == STATUS_OK:
            points = account.data
            points_status = STATUS_OK
        elif account.status == STATUS_EMPTY:
            points_status = STATUS_EMPTY
        else:
            points_status = account.status
            anomalies.append(f"积分账户：{account.message}")

    if my_coupons is not None and my_coupons.status in (STATUS_ERROR, STATUS_UNKNOWN):
        anomalies.append(f"我的券：{my_coupons.message}")

    return Report(
        mode=mode, date=today, generated_at=generated_at, source=source,
        calendar_status=calendar.status,
        sections=sections, ended=ended,
        available_coupons=available, my_coupons=my_coupons,
        points=points, points_status=points_status,
        anomalies=anomalies,
    )


def to_public(report: Report) -> PublicReport:
    """生成公开视图：只复制公共字段，个人数据在此边界被丢弃。

    公开版的异常提示一律通用化，不带任何接口原文。
    """
    public_anomalies: list[str] = []
    if report.calendar_status in (STATUS_ERROR, STATUS_UNKNOWN):
        public_anomalies.append("活动日历未能核实，请稍后再试或查看官方渠道")
    return PublicReport(
        mode=report.mode, date=report.date, generated_at=report.generated_at,
        source=report.source, calendar_status=report.calendar_status,
        sections=report.sections,
        anomalies=public_anomalies,
    )


def points_note(points: PointsInfo | None, status: str, today: date) -> list[str]:
    """积分提醒文案（仅私人版）。月度汇总，没有日级到期日期。"""
    if status != STATUS_OK or points is None:
        return ["积分账户接口未返回可用数据，无法生成到期提醒。"]
    lines: list[str] = []

    def fmt(v: int | None) -> str:
        return "接口未返回" if v is None else f"{v} 分"

    lines.append(f"可用积分：{fmt(points.availablePoint)}")
    next_month_date = (today.replace(day=28) + timedelta(days=8)).replace(day=1)
    lines.append(
        f"本月（{today.year} 年 {today.month} 月）将过期："
        f"{fmt(points.currentMouthExpirePoint)}"
        "（接口只提供月度汇总，无日级到期日期）")
    lines.append(
        f"下月（{next_month_date.year} 年 {next_month_date.month} 月）将过期："
        f"{fmt(points.nextMouthExpirePoint)}")
    lines.append(f"上月已过期：{fmt(points.lastMouthExpirePoint)}")
    return lines

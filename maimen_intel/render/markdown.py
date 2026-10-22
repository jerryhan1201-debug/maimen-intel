"""私人 Markdown 简报。"""
from __future__ import annotations

from ..parse import STATUS_EMPTY, STATUS_OK, MyCoupon
from ..report import (CALENDAR_STATUS_NOTES, CATEGORY_LABELS, CATEGORY_ORDER,
                      Report, points_note)


def _coupon_lines(coupons: list[MyCoupon]) -> list[str]:
    lines = []
    for c in coupons:
        date_text = c.datetime_text or (
            f"{c.start} 至 {c.end}" if c.start or c.end else "有效期以券面为准")
        discount = f"（{c.discount_desc}）" if c.discount_desc else ""
        tags = f" [{' / '.join(c.tags)}]" if c.tags else ""
        lines.append(f"- **{c.title}**{discount}{tags}\n  - {date_text}")
    return lines or ["- 卡包为空"]


def render_private_markdown(report: Report) -> str:
    mode_badge = "DEMO（虚构演示数据）" if report.mode == "demo" else "LIVE（真实查询）"
    lines: list[str] = [
        f"# 麦门情报站 · {report.date.strftime('%Y 年 %m 月 %d 日')}",
        "",
        f"- 模式：**{mode_badge}**",
        f"- 数据来源：{report.source}",
        f"- 生成时间：{report.generated_at}（北京时间）",
        "",
        "> 本项目非麦当劳官方产品，信息以麦当劳官方渠道为准。",
        "",
    ]

    calendar_failed_note = CALENDAR_STATUS_NOTES.get(report.calendar_status)
    for cat in CATEGORY_ORDER:
        views = report.sections.get(cat, [])
        lines.append(f"## {CATEGORY_LABELS[cat]}（{len(views)}）")
        lines.append("")
        if calendar_failed_note:
            # 日历失败/未知：不得显示看似确认的“暂无活动”
            lines.append(f"⚠️ {calendar_failed_note}。")
        elif not views:
            lines.append("暂无。")
        for v in views:
            badge = " `新`" if v.is_new else ""
            lines.append(f"### {v.campaign.title}{badge}")
            lines.append(f"- 日期：{v.date_text}")
            if v.campaign.summary:
                lines.append(f"- 内容：{v.campaign.summary}")
            for cond in v.campaign.conditions:
                lines.append(f"- 使用条件：{cond}")
            lines.append("")

    lines.append("## 可领券")
    lines.append("")
    avail = report.available_coupons
    if avail is None:
        lines.append("未查询。")
    elif avail.status == STATUS_OK:
        for c in avail.data:
            label = f"（{c.label}）" if c.label else ""
            lines.append(f"- {c.name}{label}")
    elif avail.status == STATUS_EMPTY:
        lines.append(avail.message or "当前暂无可领取的券。")
    else:
        lines.append(avail.message or "查询失败。")
    lines.append("")

    lines.append("## 我的券（仅私人版）")
    lines.append("")
    mine = report.my_coupons
    if mine is None:
        lines.append("未查询。")
    elif mine.status == STATUS_OK and isinstance(mine.data, dict):
        lines.extend(_coupon_lines(mine.data["coupons"]))
        if mine.message:
            lines.append(f"\n> 注意：{mine.message}")
        if report.pagination_note:
            lines.append("")
            lines.append(f"分页范围：{report.pagination_note}")
    elif mine.status == STATUS_EMPTY:
        lines.append("卡包为空。")
    else:
        lines.append(mine.message or "查询失败。")
    lines.append("")

    lines.append("## 积分到期提醒（仅私人版）")
    lines.append("")
    for line in points_note(report.points, report.points_status, report.date):
        lines.append(f"- {line}")
    lines.append("")

    if report.anomalies:
        lines.append("## 数据异常")
        lines.append("")
        for a in report.anomalies:
            lines.append(f"- {a}")
        lines.append("")

    lines.append("## 领取指引")
    lines.append("")
    lines.append("- 打开麦当劳 App / 小程序，进入「麦麦省」或「优惠券」页面领取。")
    lines.append("- 本工具不会自动领券；如需一键领券，请显式执行"
                 " `python -m maimen_intel claim --confirm`。")
    lines.append("")
    return "\n".join(lines)

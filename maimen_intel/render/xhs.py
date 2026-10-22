"""小红书草稿（仅公开内容：公共活动 + 通用领券指引）。"""
from __future__ import annotations

from ..report import CALENDAR_STATUS_NOTES, CATEGORY_LABELS, CATEGORY_ORDER, PublicReport

_REPO_URL = "https://github.com/jerryhan1201-debug/maimen-intel"


def render_xhs_draft(public: PublicReport) -> str:
    mode = "演示数据（虚构）" if public.mode == "demo" else "当日真实查询"
    lines: list[str] = [
        "麦门情报站 | 今日麦当劳活动一览",
        "",
        f"{public.date.strftime('%Y年%m月%d日')} · {mode}",
        "",
    ]
    failed_note = CALENDAR_STATUS_NOTES.get(public.calendar_status)
    for cat in CATEGORY_ORDER:
        views = public.sections.get(cat, [])
        if not views:
            continue
        lines.append(f"== {CATEGORY_LABELS[cat]} ==")
        for v in views:
            badge = " [新]" if v.is_new else ""
            lines.append(f"· {v.campaign.title}{badge}")
            lines.append(f"  {v.date_text}")
            if v.campaign.summary:
                lines.append(f"  {v.campaign.summary}")
        lines.append("")

    if failed_note:
        lines.append(f"注意：{failed_note}，建议以官方渠道为准。")
        lines.append("")

    lines += [
        "领取方式：麦当劳 App / 小程序 →「麦麦省」或「优惠券」",
        "",
        "本内容由开源工具「麦门情报站」生成，非麦当劳官方产品，",
        "活动与价格以官方渠道实时结果为准。",
        f"项目源码：{_REPO_URL}",
        "",
        "#麦当劳 #麦门 #优惠券 #省钱攻略",
    ]
    return "\n".join(lines)

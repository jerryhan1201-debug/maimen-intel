"""demo 模式的虚构数据。

所有活动、券、积分均为**虚构示例**，仅用于演示排版与逻辑；
日期全部以完整 date 对象计算（相对今日），跨月/跨年自然正确。
"""
from __future__ import annotations

from datetime import date, timedelta

from .parse import (STATUS_OK, AvailableCoupon, Campaign, MyCoupon, PointsInfo,
                    ToolResult)


def demo_calendar(today: date) -> ToolResult:
    """虚构活动日历（结构化形态，等价于解析后的结果）。"""
    def d(offset: int) -> date:
        return today + timedelta(days=offset)

    campaigns = [
        Campaign(
            title="【示例】麦麦会员日：经典小食第二份半价",
            date_group=today.isoformat(),
            summary="会员日到店或麦乐送下单，指定经典小食享第二份半价。",
            conditions=["每单限享一次", "不与其他优惠同享", "部分门店不参与"],
            start=d(-6), end=d(8), source="demo",
        ),
        Campaign(
            title="【示例】早餐满减周：满 20 减 5",
            date_group=today.isoformat(),
            summary="早餐时段指定组合满 20 元立减 5 元。",
            conditions=["仅限早餐时段（10:30 前）", "每单限用一次"],
            start=d(-12), end=d(2), source="demo",
        ),
        Campaign(
            title="【示例】季节限定派买一送一",
            date_group=d(4).isoformat(),
            summary="新品季节限定派上市，活动期间买一送一。",
            conditions=["数量有限，售完即止"],
            start=d(4), end=d(18), source="demo",
        ),
        Campaign(
            title="【示例】周末亲子派对报名",
            date_group=d(10).isoformat(),
            summary="主题派对开放报名，含手工体验与套餐。",
            conditions=["需提前预约门店与场次", "名额有限"],
            start=d(30), end=d(45), source="demo",  # 跨月（12 月时跨年）
        ),
        Campaign(
            title="【示例】积分翻倍日",
            date_group=None,
            summary="官方尚未公布具体日期，上线后会第一时间更新。",
            conditions=[],
            start=None, end=None, date_uncertain=True, source="demo",
        ),
    ]
    return ToolResult("campaign-calendar", STATUS_OK, data=campaigns)


def demo_available_coupons(today: date) -> ToolResult:
    """虚构可领券列表。"""
    coupons = [
        AvailableCoupon(name="【示例】免费中薯条券", status="AVAILABLE", label="可领取"),
        AvailableCoupon(name="【示例】麦乐送满 39 减 8", status="AVAILABLE", label="可领取"),
    ]
    return ToolResult("available-coupons", STATUS_OK, data=coupons)


def demo_my_coupons(today: date) -> ToolResult:
    """虚构个人卡包。"""
    def d(offset: int) -> date:
        return today + timedelta(days=offset)

    coupons = [
        MyCoupon(
            title="【示例】板烧鸡腿堡单品 9.9 元券", subtitle="到店可用",
            discount_desc="优惠价 9.9 元", start=d(-3), end=d(5),
            datetime_text=d(5).strftime("%Y-%m-%d") + " 到期",
            tags=["会员专享"], enable=True,
        ),
        MyCoupon(
            title="【示例】咖啡买一送一券", subtitle="麦咖啡",
            discount_desc="买一送一", start=d(-1), end=d(20),
            datetime_text=d(20).strftime("%Y-%m-%d") + " 到期",
            tags=["麦咖啡"], enable=True,
        ),
    ]
    return ToolResult("query-my-coupons", STATUS_OK,
                      data={"coupons": coupons,
                            "meta": {"totalCount": 2, "totalPages": 1,
                                     "currentPage": 1, "pageSize": 200}})


def demo_account(today: date) -> ToolResult:
    """虚构积分账户（字符串数字，模拟真实接口）。"""
    points = PointsInfo(availablePoint=1280, currentMouthExpirePoint=300,
                        nextMouthExpirePoint=150, lastMouthExpirePoint=0)
    return ToolResult("query-my-account", STATUS_OK, data=points)

import unittest
from datetime import date

from maimen_intel.parse import (STATUS_ERROR, STATUS_OK, Campaign, PointsInfo,
                                ToolResult)
from maimen_intel.report import (build_report, classify_campaign,
                                 points_note, to_public)

TODAY = date(2026, 10, 22)


def _campaign(start=None, end=None, uncertain=False, title="活动"):
    return Campaign(title=title, date_group=None, start=start, end=end,
                    date_uncertain=uncertain)


class TestClassify(unittest.TestCase):
    def test_ongoing(self):
        c = _campaign(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(classify_campaign(c, TODAY), "ongoing")

    def test_ending_soon(self):
        c = _campaign(date(2026, 10, 1), date(2026, 10, 24))
        self.assertEqual(classify_campaign(c, TODAY), "ending_soon")

    def test_upcoming(self):
        c = _campaign(date(2026, 10, 30), date(2026, 11, 10))
        self.assertEqual(classify_campaign(c, TODAY), "upcoming")

    def test_ended(self):
        c = _campaign(date(2026, 10, 1), date(2026, 10, 20))
        self.assertEqual(classify_campaign(c, TODAY), "ended")

    def test_uncertain_not_recommended(self):
        """不确定日期不得推荐为确定进行中/即将结束。"""
        c = _campaign(date(2026, 10, 1), date(2026, 10, 24), uncertain=True)
        self.assertEqual(classify_campaign(c, TODAY), "unverified")
        c2 = _campaign(None, None)
        self.assertEqual(classify_campaign(c2, TODAY), "unverified")


class TestBuildReport(unittest.TestCase):
    def test_single_tool_failure_does_not_block(self):
        """单接口失败不阻断日报，其余分区正常。"""
        cal = ToolResult("campaign-calendar", STATUS_OK,
                         data=[_campaign(date(2026, 10, 1), date(2026, 10, 31))])
        avail = ToolResult("available-coupons", STATUS_ERROR,
                           message="查询失败（code=500）")
        report = build_report("live", TODAY, "2026-10-22 09:00:00", "测试",
                              cal, avail, None, None)
        self.assertEqual(len(report.sections["ongoing"]), 1)
        self.assertTrue(any("可领券" in a for a in report.anomalies))

    def test_points_monthly_only(self):
        """积分只按月度汇总展示；未知字段显示“接口未返回”，不补 0。"""
        points = PointsInfo(availablePoint=None, currentMouthExpirePoint=300,
                            nextMouthExpirePoint=None, lastMouthExpirePoint=0)
        lines = points_note(points, STATUS_OK, TODAY)
        joined = "\n".join(lines)
        self.assertIn("可用积分：接口未返回", joined)
        self.assertIn("300 分", joined)
        self.assertIn("无日级到期日期", joined)
        self.assertIn("2026 年 10 月", joined)
        self.assertIn("2026 年 11 月", joined)

    def test_points_unavailable(self):
        lines = points_note(None, STATUS_ERROR, TODAY)
        self.assertIn("接口未返回", lines[0])

    def test_public_view_has_no_personal_fields(self):
        report = build_report(
            "live", TODAY, "t", "src",
            ToolResult("campaign-calendar", STATUS_OK, data=[]),
            None, None, None)
        public = to_public(report)
        self.assertFalse(hasattr(public, "my_coupons"))
        self.assertFalse(hasattr(public, "points"))


if __name__ == "__main__":
    unittest.main()

"""私人/公开隔离：向个人数据注入唯一标记，断言所有公开格式都不含。"""
import unittest
from datetime import date

from maimen_intel.parse import (STATUS_OK, AvailableCoupon, Campaign,
                                MyCoupon, PointsInfo, ToolResult)
from maimen_intel.render import html as render_html
from maimen_intel.render import markdown as render_md
from maimen_intel.render import xhs as render_xhs
from maimen_intel.render.png import build_blocks
from maimen_intel.report import build_report, to_public

TODAY = date(2026, 10, 22)
MARKER = "PRIVXYZZY-唯一标记"


def _report_with_marker():
    cal = ToolResult("campaign-calendar", STATUS_OK, data=[
        Campaign(title="公共活动甲", date_group="2026-10-22",
                 start=TODAY, end=date(2026, 10, 30))])
    avail = ToolResult("available-coupons", STATUS_OK,
                       data=[AvailableCoupon(name="公共可领券")])
    mine = ToolResult("query-my-coupons", STATUS_OK, data={
        "coupons": [MyCoupon(title=f"我的券-{MARKER}", start=TODAY,
                             end=date(2026, 10, 30))],
        "meta": {"currentPage": 1, "totalPages": 1, "totalCount": 1,
                 "pageSize": 200},
    })
    account = ToolResult("query-my-account", STATUS_OK,
                         data=PointsInfo(availablePoint=999,
                                         currentMouthExpirePoint=123,
                                         nextMouthExpirePoint=0,
                                         lastMouthExpirePoint=0))
    return build_report("live", TODAY, "2026-10-22 09:00:00", "测试",
                        cal, avail, mine, account)


class TestPrivacyIsolation(unittest.TestCase):
    def setUp(self):
        self.report = _report_with_marker()
        self.public = to_public(self.report)

    def test_private_contains_marker(self):
        self.assertIn(MARKER, render_md.render_private_markdown(self.report))
        self.assertIn(MARKER, render_html.render_private_html(self.report))

    def test_public_html_excludes_marker(self):
        out = render_html.render_public_html(self.public)
        self.assertNotIn(MARKER, out)
        self.assertNotIn("我的券", out.split("</nav>")[-1].split("<footer")[0]
                         .replace("我的券（仅私人版）", ""))  # 私人分区不出现在正文
        self.assertIn("非麦当劳官方产品", out)

    def test_png_blocks_exclude_marker(self):
        for block in build_blocks(self.public):
            self.assertNotIn(MARKER, block.text)

    def test_xhs_excludes_marker(self):
        self.assertNotIn(MARKER, render_xhs.render_xhs_draft(self.public))

    def test_public_view_object_has_no_personal_data(self):
        self.assertNotIn(MARKER, repr(self.public))


if __name__ == "__main__":
    unittest.main()

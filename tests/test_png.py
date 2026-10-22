import os
import tempfile
import unittest
from datetime import date

from maimen_intel.parse import STATUS_OK, AvailableCoupon, Campaign, ToolResult
from maimen_intel.render.png import (CONTENT_W, _Painter, build_blocks,
                                     find_cjk_font, render_png)
from maimen_intel.report import build_report, to_public

TODAY = date(2026, 10, 22)
LONG_TITLE = ("超长活动标题" * 12) + "——含各种前缀后缀说明文字，确保必须换行且绝不溢出边界"


def _public(long=False):
    title = LONG_TITLE if long else "会员日小食半价"
    cal = ToolResult("campaign-calendar", STATUS_OK, data=[
        Campaign(title=title, date_group="2026-10-22",
                 summary="指定小食第二份半价。" * 6,
                 conditions=["每单限享一次", "不与其他优惠同享"],
                 start=TODAY, end=date(2026, 10, 30))])
    avail = ToolResult("available-coupons", STATUS_OK,
                       data=[AvailableCoupon(name="免费薯条券")])
    report = build_report("demo", TODAY, "2026-10-22 09:00:00", "测试",
                          cal, avail, None, None)
    return to_public(report)


class TestPng(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = find_cjk_font()

    def test_wrap_within_width(self):
        painter = _Painter(self.font)
        for line in painter.wrap(LONG_TITLE, "item_title"):
            self.assertLessEqual(
                painter._probe.textlength(line, font=painter.fonts["item_title"]),
                CONTENT_W)

    def test_height_grows_with_content(self):
        short_blocks = build_blocks(_public(long=False))
        long_blocks = build_blocks(_public(long=True))
        painter = _Painter(self.font)
        h_short = sum(painter.block_height(b) for b in short_blocks)
        h_long = sum(painter.block_height(b) for b in long_blocks)
        self.assertGreater(h_long, h_short)

    def test_render_and_footer_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "share.png")
            _, height = render_png(_public(long=True), path, font_path=self.font)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(height, 1000)
            from PIL import Image
            with Image.open(path) as img:
                self.assertEqual(img.width, 1080)
                self.assertEqual(img.height, height)

    def test_new_badge_is_chinese(self):
        public = _public()
        # 手工构造带 is_new 的视图
        view = public.sections["ongoing"][0]
        view.is_new = True
        blocks = build_blocks(public)
        badge_blocks = [b for b in blocks if b.is_new]
        self.assertEqual(len(badge_blocks), 1)
        # 徽标文本必须是中文“新”，不是 emoji
        self.assertNotIn("🆕", "".join(b.text for b in blocks))


if __name__ == "__main__":
    unittest.main()

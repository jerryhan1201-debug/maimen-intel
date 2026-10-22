import unittest
from datetime import date

from maimen_intel.dates import extract_date_range, normalize_text


class TestExtractDateRange(unittest.TestCase):
    def test_explicit_year_never_rewritten(self):
        """明确年份绝不改：2026 年解析 2025 年文案仍是 2025。"""
        dr = extract_date_range("2025年10月8日至10月21日", date(2026, 10, 18))
        self.assertEqual(dr.start, date(2025, 10, 8))
        self.assertEqual(dr.end, date(2025, 10, 21))
        self.assertTrue(dr.explicit_year)

    def test_same_month_abbreviation(self):
        dr = extract_date_range("10月8日至21日", date(2026, 10, 1))
        self.assertEqual(dr.start, date(2026, 10, 8))
        self.assertEqual(dr.end, date(2026, 10, 21))

    def test_cross_month(self):
        dr = extract_date_range("10月28日至11月6日", date(2026, 10, 20))
        self.assertEqual(dr.start, date(2026, 10, 28))
        self.assertEqual(dr.end, date(2026, 11, 6))

    def test_cross_year_rollover(self):
        """结束月小于开始月时，结束日保守顺延到下一年。"""
        dr = extract_date_range("12月28日至1月6日", date(2026, 12, 20))
        self.assertEqual(dr.start, date(2026, 12, 28))
        self.assertEqual(dr.end, date(2027, 1, 6))

    def test_leap_year(self):
        dr = extract_date_range("2024年2月28日至3月1日", date(2024, 2, 27))
        self.assertEqual(dr.start, date(2024, 2, 28))
        self.assertEqual(dr.end, date(2024, 3, 1))

    def test_explicit_end_year(self):
        dr = extract_date_range("2026年12月28日至2027年1月6日", date(2026, 12, 20))
        self.assertEqual(dr.end, date(2027, 1, 6))
        self.assertTrue(dr.explicit_year)

    def test_start_only_no_fabricated_end(self):
        """只有起始日不能凭空补结束日。"""
        dr = extract_date_range("10月8日起", date(2026, 10, 1))
        self.assertEqual(dr.start, date(2026, 10, 8))
        self.assertIsNone(dr.end)
        self.assertTrue(dr.ambiguous)

    def test_until_only(self):
        dr = extract_date_range("即日起至10月31日", date(2026, 10, 1))
        self.assertIsNone(dr.start)
        self.assertEqual(dr.end, date(2026, 10, 31))

    def test_fullwidth_digits(self):
        dr = extract_date_range("２０２５年１０月８日至１０月２１日", date(2026, 10, 18))
        self.assertEqual(dr.start, date(2025, 10, 8))
        self.assertEqual(dr.end, date(2025, 10, 21))

    def test_math_digits(self):
        dr = extract_date_range("𝟐𝟎𝟐𝟓年𝟏𝟎月𝟖日至𝟏𝟎月𝟐𝟏日", date(2026, 10, 18))
        self.assertEqual(dr.start, date(2025, 10, 8))
        self.assertEqual(dr.end, date(2025, 10, 21))

    def test_invalid_date_not_guessed(self):
        dr = extract_date_range("2月30日至3月1日", date(2026, 2, 20))
        self.assertIsNone(dr.start)  # 非法日期不猜测

    def test_no_date(self):
        dr = extract_date_range("近期即将上线，敬请期待", date(2026, 10, 18))
        self.assertFalse(dr.known)
        self.assertTrue(dr.ambiguous)

    def test_normalize_text(self):
        self.assertEqual(normalize_text("１２𝟑"), "123")


if __name__ == "__main__":
    unittest.main()

"""端到端：demo 两次运行去重、mode 隔离、demo 跨月/跨年日期正确。"""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from maimen_intel import demo_data
from maimen_intel.parse import STATUS_OK
from maimen_intel.report import classify_campaign
from maimen_intel.runner import run_brief

TODAY = date(2026, 10, 22)


class TestDemoRun(unittest.TestCase):
    def test_demo_twice_dedup_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "outputs")
            state = os.path.join(tmp, "state")
            first = run_brief("demo", today=TODAY, output_dir=out,
                              state_dir=state)
            for key, path in first["outputs"].items():
                self.assertTrue(os.path.exists(path), key)
            self.assertGreater(first["new_items"], 0)

            second = run_brief("demo", today=TODAY, output_dir=out,
                               state_dir=state)
            self.assertEqual(second["new_items"], 0,
                             "第二次运行不应再标“新”")

            # 状态文件按 mode 隔离存放
            self.assertTrue(os.path.exists(os.path.join(state, "demo.json")))
            self.assertFalse(os.path.exists(os.path.join(state, "live.json")))

            # 公开产物不含私人分区标题
            public_html = Path(first["outputs"]["public_html"]).read_text(
                encoding="utf-8")
            self.assertNotIn("积分到期提醒", public_html)
            self.assertIn("麦门情报站", public_html)

    def test_demo_marked_as_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = run_brief("demo", today=TODAY, output_dir=tmp + "/o",
                               state_dir=tmp + "/s")
            public_html = Path(status["outputs"]["public_html"]).read_text(
                encoding="utf-8")
            self.assertIn("DEMO", public_html)
            self.assertIn("虚构", public_html)


class TestDemoDates(unittest.TestCase):
    def test_cross_month(self):
        cal = demo_data.demo_calendar(date(2026, 10, 22))
        self.assertEqual(cal.status, STATUS_OK)
        cross = [c for c in cal.data if c.start and c.end
                 and (c.end - c.start).days >= 14]
        self.assertTrue(cross)
        for c in cross:
            self.assertLess(c.start, c.end)

    def test_cross_year(self):
        """12 月中旬运行时，远期示例自然跨年且日期正确。"""
        cal = demo_data.demo_calendar(date(2026, 12, 15))
        spans = {(c.start, c.end) for c in cal.data if c.start and c.end}
        self.assertIn((date(2027, 1, 14), date(2027, 1, 29)), spans)

    def test_uncertain_campaign_unverified(self):
        cal = demo_data.demo_calendar(TODAY)
        uncertain = [c for c in cal.data if c.date_uncertain]
        self.assertTrue(uncertain)
        for c in uncertain:
            self.assertEqual(classify_campaign(c, TODAY), "unverified")

    def test_statuses_match_dates(self):
        """每个示例的分区与其日期一致。"""
        today = TODAY
        cal = demo_data.demo_calendar(today)
        cats = {classify_campaign(c, today) for c in cal.data}
        self.assertIn("ongoing", cats)
        self.assertIn("ending_soon", cats)
        self.assertIn("upcoming", cats)
        self.assertIn("unverified", cats)


class TestRunStatusSanitized(unittest.TestCase):
    def test_no_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = run_brief("demo", today=TODAY, output_dir=tmp + "/o",
                               state_dir=tmp + "/s")
            raw = Path(tmp, "o", "demo", TODAY.isoformat(),
                       "run-status.json").read_text(encoding="utf-8")
            self.assertNotIn("Authorization", raw)
            self.assertNotIn("accountId", raw)
            data = json.loads(raw)
            self.assertEqual(data["mode"], "demo")


if __name__ == "__main__":
    unittest.main()

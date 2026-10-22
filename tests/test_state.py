import tempfile
import unittest
from datetime import date
from pathlib import Path

from maimen_intel.state import StateStore

TODAY = date(2026, 10, 22)


class TestStateStore(unittest.TestCase):
    def test_dedup_same_day_second_run(self):
        """重复生成不重复标“新”。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp, "demo")
            first = store.mark_and_get_new(["a", "b"], TODAY)
            self.assertEqual(first, {"a", "b"})
            second = store.mark_and_get_new(["a", "b"], TODAY)
            self.assertEqual(second, set())
            # 新实例（模拟另一次进程运行）依然去重
            store2 = StateStore(tmp, "demo")
            third = store2.mark_and_get_new(["a", "b", "c"], TODAY)
            self.assertEqual(third, {"c"})

    def test_mode_isolation(self):
        """demo / live 状态相互隔离。"""
        with tempfile.TemporaryDirectory() as tmp:
            demo = StateStore(tmp, "demo")
            live = StateStore(tmp, "live")
            demo.mark_and_get_new(["a"], TODAY)
            self.assertEqual(live.mark_and_get_new(["a"], TODAY), {"a"})
            self.assertTrue((Path(tmp) / "demo.json").exists())
            self.assertTrue((Path(tmp) / "live.json").exists())

    def test_corrupt_state_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.json"
            path.write_text("not json", encoding="utf-8")
            store = StateStore(tmp, "demo")
            self.assertEqual(store.mark_and_get_new(["a"], TODAY), {"a"})

    def test_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                StateStore(tmp, "publish")


if __name__ == "__main__":
    unittest.main()

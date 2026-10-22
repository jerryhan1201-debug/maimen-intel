"""第二轮审查回归测试：协议形状、全链路脱敏、反向日期、严格空判定、
状态提交时机、run-status 通用化。"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from maimen_intel import runner
from maimen_intel.mcp_client import McpClient, McpError
from maimen_intel.parse import (STATUS_EMPTY, STATUS_OK, STATUS_UNKNOWN,
                                ToolResult, parse_available_coupons,
                                parse_campaign_calendar)
from maimen_intel.render import html as render_html
from maimen_intel.render import xhs as render_xhs
from maimen_intel.render.png import build_blocks
from maimen_intel.report import build_report, to_public

TODAY = date(2026, 12, 30)


class _Resp:
    def __init__(self, body, headers=None, status=200):
        self.body = json.dumps(body).encode() if isinstance(body, dict) else body
        self.headers = headers or {"Content-Type": "application/json"}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


class _Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        r = next(self.responses)
        if isinstance(r, BaseException):
            raise r
        return r


def _init_result(**over):
    result = {"protocolVersion": "2025-03-26", "capabilities": {},
              "serverInfo": {"name": "x", "version": "1"}}
    result.update(over)
    return {"jsonrpc": "2.0", "id": 0, "result": result}


class TestInitializeShape(unittest.TestCase):
    def _attempt(self, result_payload):
        opener = _Opener([_Resp({"jsonrpc": "2.0", "id": 0,
                                 "result": result_payload})])
        client = McpClient(opener=opener)
        return client, client.call_tool("x")

    def test_version_list_rejected(self):
        client, res = self._attempt({**_init_result()["result"],
                                     "protocolVersion": []})
        self.assertIn("__transport_error__", res)
        self.assertFalse(client.initialized)

    def test_version_dict_rejected(self):
        client, res = self._attempt({**_init_result()["result"],
                                     "protocolVersion": {}})
        self.assertIn("__transport_error__", res)
        self.assertFalse(client.initialized)

    def test_missing_capabilities_rejected(self):
        client, res = self._attempt({"protocolVersion": "2025-03-26",
                                     "serverInfo": {"name": "x"}})
        self.assertIn("__transport_error__", res)
        self.assertFalse(client.initialized)

    def test_missing_server_info_rejected(self):
        client, res = self._attempt({"protocolVersion": "2025-03-26",
                                     "capabilities": {}})
        self.assertIn("__transport_error__", res)
        self.assertFalse(client.initialized)


class TestFullChainRedaction(unittest.TestCase):
    """title/subtitle/summary/conditions/异常 全链路公开产物不含哨兵。"""

    def _public(self, event):
        cal = parse_campaign_calendar({"code": 200, "data": {"dailyList": [
            {"date": "2026-12-30", "events": [event]}]}}, TODAY)
        report = build_report("demo", TODAY, "t", "offline", cal, None, None,
                              None)
        return to_public(report)

    def test_title_subtitle_redacted(self):
        public = self._public({
            "activityTitle": "券码 TITLE_SENTINEL_1234",
            "activitySubTitle": "券码 SUBTITLE_SENTINEL_1234"})
        blob = json.dumps(public.__dict__, ensure_ascii=False, default=str)
        self.assertNotIn("TITLE_SENTINEL_1234", blob)
        self.assertNotIn("SUBTITLE_SENTINEL_1234", blob)
        for out in (render_html.render_public_html(public),
                    render_xhs.render_xhs_draft(public),
                    "".join(b.text for b in build_blocks(public))):
            self.assertNotIn("TITLE_SENTINEL_1234", out)
            self.assertNotIn("SUBTITLE_SENTINEL_1234", out)

    def test_member_id_redacted(self):
        public = self._public({
            "activityTitle": "虚构活动",
            "articleDto": {"content": "凭 会员号 MEMBER_SENTINEL_1234 参与"}})
        blob = json.dumps(public.__dict__, ensure_ascii=False, default=str)
        self.assertNotIn("MEMBER_SENTINEL_1234", blob)


class TestStructuredReverseDate(unittest.TestCase):
    def test_reversed_structured_dates_unverified_not_ended(self):
        cal = parse_campaign_calendar({"code": 200, "data": {"dailyList": [{
            "date": "2026-12-30",
            "events": [{"activityTitle": "反向结构化日期",
                        "couponInfo": {"tradeStartDate": "2026-12-31",
                                       "tradeEndDate": "2026-01-02"}}],
        }]}}, TODAY)
        self.assertEqual(cal.status, STATUS_OK)
        c = cal.data[0]
        self.assertTrue(c.date_uncertain)
        report = build_report("demo", TODAY, "t", "s", cal, None, None, None)
        self.assertEqual(len(report.sections["unverified"]), 1)
        self.assertEqual(len(report.ended), 0)


class TestAvailableCouponStrictEmpty(unittest.TestCase):
    def test_legal_text_with_negation_not_empty(self):
        res = parse_available_coupons({"content": [{"type": "text",
                                       "text": "虚构饮料券，没有使用门槛"}]})
        self.assertEqual(res.status, STATUS_UNKNOWN)
        self.assertNotEqual(res.status, STATUS_EMPTY)

    def test_pure_empty_still_empty(self):
        res = parse_available_coupons({"content": [{"type": "text",
                                       "text": "暂无可领优惠券"}]})
        self.assertEqual(res.status, STATUS_EMPTY)


class TestStateCommitTiming(unittest.TestCase):
    def test_failed_render_does_not_consume_new_state(self):
        results = {
            "campaign-calendar": parse_campaign_calendar(
                {"code": 200, "data": {"dailyList": [{
                    "date": "2026-12-30",
                    "events": [{"activityTitle": "虚构新活动",
                                "activitySubTitle": "2026年12月30日至2027年1月2日"}],
                }]}}, TODAY),
            "available-coupons": ToolResult("available-coupons", "empty", data=[]),
            "query-my-coupons": ToolResult("query-my-coupons", "empty",
                                           data={"coupons": [], "meta": {}}),
            "query-my-account": ToolResult("query-my-account", "error",
                                           message="账户标识 ACCOUNT_ERROR_SENTINEL_1234"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = {"mode": "demo", "today": TODAY,
                      "output_dir": Path(tmp) / "out",
                      "state_dir": Path(tmp) / "state"}
            with patch.object(runner, "_fetch_demo",
                              return_value=(results, "mock", "none")):
                # 第一次：渲染失败 -> 状态不得提交
                with patch.object(runner.render_md, "render_private_markdown",
                                  side_effect=RuntimeError("synthetic")):
                    with self.assertRaises(RuntimeError):
                        runner.run_brief(**kwargs)
                state_file = Path(tmp) / "state" / "demo.json"
                if state_file.exists():
                    self.assertEqual(json.loads(state_file.read_text())["seen"],
                                     {})
                # 第二次：成功 -> 活动仍应被识别为“新”
                status = runner.run_brief(**kwargs)
                self.assertGreater(status["new_items"], 0)

                # run-status 只含通用原因，不含账户标识原文
                persisted = Path(status["outputs"]["private_md"]).parent \
                    / "run-status.json"
                text = persisted.read_text(encoding="utf-8")
                self.assertNotIn("ACCOUNT_ERROR_SENTINEL_1234", text)
                self.assertEqual(
                    json.loads(text)["tools"]["query-my-account"]["message"],
                    "查询失败")


if __name__ == "__main__":
    unittest.main()

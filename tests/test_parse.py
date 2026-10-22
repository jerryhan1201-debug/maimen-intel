import unittest
from datetime import date

from maimen_intel.parse import (STATUS_EMPTY, STATUS_ERROR, STATUS_OK,
                                STATUS_UNKNOWN, parse_available_coupons,
                                parse_campaign_calendar, parse_my_account,
                                parse_my_coupons, parse_point,
                                unwrap_mcp_result)

TODAY = date(2026, 10, 22)


def _text_result(text: str):
    return {"content": [{"type": "text", "text": text}]}


class TestUnwrap(unittest.TestCase):
    def test_structured_content_priority(self):
        raw = {"structuredContent": {"code": 200, "data": [1]},
               "content": [{"type": "text", "text": "not json"}]}
        payload, err = unwrap_mcp_result("t", raw)
        self.assertIsNone(err)
        self.assertEqual(payload["data"], [1])

    def test_json_text_wrapper(self):
        payload, err = unwrap_mcp_result("t", _text_result('{"code":200,"data":[]}'))
        self.assertIsNone(err)
        self.assertEqual(payload["code"], 200)

    def test_markdown_fallback(self):
        from maimen_intel.parse import MarkdownPayload
        payload, err = unwrap_mcp_result("t", _text_result("## 10月22日\n- 某活动"))
        self.assertIsNone(err)
        self.assertIsInstance(payload, MarkdownPayload)

    def test_jsonrpc_error_32602(self):
        """历史出现过的 -32602 必须是失败，不能当 0 条。"""
        payload, err = unwrap_mcp_result(
            "available-coupons",
            {"error": {"code": -32602, "message": "Invalid params"}})
        self.assertIsNone(payload)
        self.assertEqual(err.status, STATUS_ERROR)
        self.assertIn("查询失败", err.message)

    def test_is_error(self):
        payload, err = unwrap_mcp_result(
            "t", {"isError": True, "content": [{"type": "text", "text": "boom"}]})
        self.assertEqual(err.status, STATUS_ERROR)


class TestAvailableCoupons(unittest.TestCase):
    def test_data_must_be_array(self):
        """历史问题：data 不是数组 -> 查询失败。"""
        raw = {"structuredContent": {"code": 200, "message": "ok",
                                     "data": {"oops": 1}}}
        res = parse_available_coupons(raw)
        self.assertEqual(res.status, STATUS_ERROR)
        self.assertIn("data must be array", res.message)

    def test_empty_array(self):
        res = parse_available_coupons(
            {"structuredContent": {"code": 200, "message": "ok", "data": []}})
        self.assertEqual(res.status, STATUS_EMPTY)

    def test_busy_is_not_empty(self):
        """“服务繁忙”不能当空。"""
        res = parse_available_coupons(
            {"structuredContent": {"code": 500, "message": "服务繁忙，请稍后再试"}})
        self.assertEqual(res.status, STATUS_ERROR)

    def test_busy_text_is_not_empty(self):
        res = parse_available_coupons(_text_result("服务繁忙，请稍后再试"))
        self.assertEqual(res.status, STATUS_ERROR)

    def test_unknown_structure_not_verified(self):
        """非空未知券结构 -> unknown，不得谎称已核验。"""
        res = parse_available_coupons(
            {"structuredContent": {"code": 200, "message": "ok",
                                   "data": [{"foo": "bar", "baz": 1}]}})
        self.assertEqual(res.status, STATUS_UNKNOWN)
        self.assertIn("待核实", res.message)

    def test_ok(self):
        res = parse_available_coupons({"structuredContent": {
            "code": 200, "message": "ok", "data": [
                {"couponName": "免费薯条券", "couponStatus": "AVAILABLE",
                 "label": "可领取"}]}})
        self.assertEqual(res.status, STATUS_OK)
        self.assertEqual(res.data[0].name, "免费薯条券")


class TestCampaignCalendar(unittest.TestCase):
    def test_structured(self):
        raw = {"structuredContent": {"code": 200, "message": "ok", "data": {
            "currentTime": "2026-10-22 09:00:00",
            "dailyList": [{
                "date": "2026-10-22", "dateText": "今天", "today": True,
                "events": [{
                    "eventType": 0,
                    "activityTitle": "会员日小食半价",
                    "activitySubTitle": "经典小食",
                    "articleDto": {"title": "会员日",
                                   "content": "指定小食第二份半价。每单限享一次。不与其他优惠同享。"},
                    "couponInfo": {"tradeStartDate": "2026-10-20",
                                   "tradeEndDate": "2026-10-25"},
                }],
            }],
            # 个人订阅状态绝不允许进入解析结果
            "subscribedEvents": [{"activityTitle": "PRIV-MARKER-订阅活动"}],
        }}}
        res = parse_campaign_calendar(raw, TODAY)
        self.assertEqual(res.status, STATUS_OK)
        self.assertEqual(len(res.data), 1)
        c = res.data[0]
        self.assertEqual(c.title, "会员日小食半价")
        self.assertEqual(c.start, date(2026, 10, 20))
        self.assertEqual(c.end, date(2026, 10, 25))
        self.assertTrue(any("每单限" in x for x in c.conditions))
        # subscribedEvents 未被读取
        self.assertNotIn("PRIV-MARKER", repr(res.data))

    def test_structured_empty(self):
        res = parse_campaign_calendar(
            {"structuredContent": {"code": 200, "message": "ok",
                                   "data": {"dailyList": []}}}, TODAY)
        self.assertEqual(res.status, STATUS_EMPTY)

    def test_structured_unparsable_is_unknown(self):
        """非空原文解析不出活动 -> 结构待核实，不得显示“暂无活动”。"""
        res = parse_campaign_calendar(
            {"structuredContent": {"code": 200, "message": "ok",
                                   "data": {"dailyList": [{"date": "2026-10-22",
                                                           "events": [{}]}]}}},
            TODAY)
        self.assertEqual(res.status, STATUS_UNKNOWN)
        self.assertIn("待核实", res.message)

    def test_markdown_grouped(self):
        md = ("# 本月活动\n\n## 2026-10-22\n"
              "- **会员日小食半价** 指定小食第二份半价\n"
              "  每单限享一次\n\n"
              "## 2026-10-30\n"
              "- 周末亲子派对 需提前预约\n")
        res = parse_campaign_calendar(_text_result(md), TODAY)
        self.assertEqual(res.status, STATUS_OK)
        self.assertEqual(len(res.data), 2)
        self.assertEqual(res.data[0].title, "会员日小食半价")
        self.assertEqual(res.data[0].date_group, "2026-10-22")
        self.assertTrue(any("每单限" in x for x in res.data[0].conditions))

    def test_markdown_empty_hint(self):
        res = parse_campaign_calendar(_text_result("本月暂无活动"), TODAY)
        self.assertEqual(res.status, STATUS_EMPTY)

    def test_markdown_unparsable_is_unknown(self):
        res = parse_campaign_calendar(
            _text_result("！！！无法理解的返回内容，没有日期也没有条目" * 10), TODAY)
        self.assertEqual(res.status, STATUS_UNKNOWN)
        self.assertIn("待核实", res.message)

    def test_markdown_busy_is_error(self):
        res = parse_campaign_calendar(_text_result("服务繁忙，请稍后再试"), TODAY)
        self.assertEqual(res.status, STATUS_ERROR)


class TestMyCoupons(unittest.TestCase):
    def test_ok_and_meta(self):
        raw = {"structuredContent": {"code": 200, "message": "ok", "data": {
            "coupons": [{
                "title": "板烧 9.9 元券", "subtitle": "到店",
                "discountInfo": {"discountDesc": "优惠价 9.9 元"},
                "tradeStartDate": "2026-10-20", "tradeEndDate": "2026-10-25",
                "enable": 1, "tags": [{"label": "会员专享"}],
            }],
            "currentPage": 1, "pageSize": 200, "totalCount": 1, "totalPages": 1,
        }}}
        res = parse_my_coupons(raw)
        self.assertEqual(res.status, STATUS_OK)
        c = res.data["coupons"][0]
        self.assertEqual(c.end, date(2026, 10, 25))
        self.assertEqual(res.data["meta"]["totalPages"], 1)

    def test_empty_book(self):
        res = parse_my_coupons({"structuredContent": {
            "code": 200, "message": "ok", "data": {
                "coupons": [], "currentPage": 1, "pageSize": 200,
                "totalCount": 0, "totalPages": 0}}})
        self.assertEqual(res.status, STATUS_EMPTY)

    def test_failure_is_error(self):
        res = parse_my_coupons({"error": {"code": -1, "message": "x"}})
        self.assertEqual(res.status, STATUS_ERROR)


class TestMyAccount(unittest.TestCase):
    def test_string_numbers(self):
        res = parse_my_account({"structuredContent": {
            "code": 200, "data": {
                "accountId": "PRIV-ACC-ID",
                "availablePoint": "1,280",
                "currentMouthExpirePoint": "300",
                "nextMouthExpirePoint": "150",
                "lastMouthExpirePoint": "0",
            }}})
        self.assertEqual(res.status, STATUS_OK)
        p = res.data
        self.assertEqual(p.availablePoint, 1280)
        self.assertEqual(p.currentMouthExpirePoint, 300)
        # 账户标识不进入解析结果
        self.assertNotIn("PRIV-ACC-ID", repr(p))

    def test_invalid_values_are_unknown(self):
        res = parse_my_account({"structuredContent": {
            "code": 200, "data": {
                "availablePoint": "NaN",
                "currentMouthExpirePoint": "Infinity",
                "nextMouthExpirePoint": None,
                "lastMouthExpirePoint": "abc",
            }}})
        p = res.data
        self.assertIsNone(p.availablePoint)
        self.assertIsNone(p.currentMouthExpirePoint)
        self.assertIsNone(p.nextMouthExpirePoint)
        self.assertIsNone(p.lastMouthExpirePoint)

    def test_parse_point(self):
        self.assertEqual(parse_point("300"), 300)
        self.assertEqual(parse_point(300), 300)
        self.assertEqual(parse_point(3.0), 3)
        self.assertIsNone(parse_point(float("nan")))
        self.assertIsNone(parse_point(float("inf")))
        self.assertIsNone(parse_point(True))
        self.assertIsNone(parse_point(""))


if __name__ == "__main__":
    unittest.main()

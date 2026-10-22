import unittest
import urllib.request

from maimen_intel.mcp_client import (McpError, _NoCredentialRedirect,
                                     messages_from_sse, parse_sse_events,
                                     sanitize, select_response)


class TestSSE(unittest.TestCase):
    BODY = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"x":1}}\n'
        "\n"
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":7,"result":{"content":[]}}\n'
        "\n"
        "event: message\n"
        'data: {"jsonrpc":"2.0","method":"notifications/message"}\n'
        "\n"
    )

    def test_parse_events(self):
        events = parse_sse_events(self.BODY)
        self.assertEqual(len(events), 3)

    def test_match_by_id_not_last_notification(self):
        """必须按请求 id 匹配，不能盲取最后一条通知。"""
        messages = messages_from_sse(self.BODY)
        # 最后一条是通知；正确响应在中间
        resp = select_response(messages, 7)
        self.assertIsNotNone(resp)
        self.assertIn("result", resp)
        # 不存在的 id -> None（而不是错拿通知）
        self.assertIsNone(select_response(messages, 99))

    def test_notifications_skipped(self):
        messages = messages_from_sse(self.BODY)
        notifications = [m for m in messages if "method" in m]
        self.assertEqual(len(notifications), 2)
        for n in notifications:
            self.assertIsNone(select_response([n], n.get("id")))

    def test_unparseable_data_ignored(self):
        messages = messages_from_sse("data: not-json\n\n"
                                     'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n')
        self.assertEqual(len(messages), 1)
        self.assertIsNotNone(select_response(messages, 1))


class TestSanitize(unittest.TestCase):
    def test_token_removed(self):
        token = "Bearer abc123secret"
        msg = sanitize(f"请求失败：Authorization={token}", token)
        self.assertNotIn("abc123secret", msg)

    def test_raw_token_removed(self):
        msg = sanitize("token abc123secret 失效", "abc123secret")
        self.assertNotIn("abc123secret", msg)


class TestRedirectPolicy(unittest.TestCase):
    def test_cross_domain_redirect_refused(self):
        handler = _NoCredentialRedirect()
        req = urllib.request.Request("https://mcp.mcd.cn", method="POST")
        with self.assertRaises(McpError):
            handler.redirect_request(req, None, 302, "Found", {},
                                     "https://evil.example.com/x")


if __name__ == "__main__":
    unittest.main()

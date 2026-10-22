import unittest

from maimen_intel.claim import REFUSAL_MESSAGE, claim


def _wallet(items):
    return {"code": 200, "message": "ok", "data": {
        "coupons": items, "totalCount": len(items),
        "totalPages": 1, "currentPage": 1, "pageSize": 200}}


def _claim_body(entries, success=None, failed=None, failed_count=None):
    """构造 auto-bind-coupons 成功响应。

    success/failed_count 传入非 None 时用于模拟计数不一致（测试形状校验）；
    默认与列表长度一致。
    """
    fc = failed_count if failed_count is not None else len(failed or [])
    return {"code": 200, "message": "ok", "data": {
        "totalCount": len(entries) + len(failed or []),
        "successCount": len(entries) if success is None else success,
        "failedCount": fc,
        "successCoupons": entries, "failedCoupons": failed or []}}


OLD = {"id": "OLDID", "code": "OLDCODE", "title": "旧薯条券", "enable": 1}
NEW_ENTRY = {"couponId": "NEWID", "couponCode": "NEWCODE",
             "couponName": "大薯条优惠券"}
NEW_OWNED = {"id": "NEWID", "code": "NEWCODE", "title": "大薯条优惠券",
             "enable": 1}


class FakeClient:
    """记录所有调用的假客户端（不真实领券）。支持领取前后卡包。"""

    def __init__(self, auto_bind_raw, pre_wallet, post_wallet=None):
        self.auto_bind_raw = auto_bind_raw
        self.pre_wallet = pre_wallet
        self.post_wallet = post_wallet if post_wallet is not None else pre_wallet
        self.calls: list[str] = []

    def call_tool(self, name, arguments):
        self.calls.append(name)
        if name == "query-my-coupons":
            # 第一次（领取前）与第二次（领取后）返回不同快照
            return self.pre_wallet if self.calls.count(name) == 1 \
                else self.post_wallet
        if name == "auto-bind-coupons":
            return self.auto_bind_raw
        raise AssertionError(f"不允许调用其他工具：{name}")


class TestClaim(unittest.TestCase):
    def test_default_not_triggered(self):
        """claim 默认关闭：日报流程不调用 auto-bind-coupons。"""
        from maimen_intel import runner
        import inspect
        self.assertNotIn("auto-bind-coupons", inspect.getsource(runner))

    def test_unconfirmed_refused_before_network(self):
        """未确认时在任何网络调用之前拒绝。"""
        result = claim(client=None, confirm=False)
        self.assertFalse(result.attempted)
        self.assertFalse(result.ok)
        self.assertEqual(result.message, REFUSAL_MESSAGE)

    def test_unconfirmed_with_client_makes_no_calls(self):
        client = FakeClient(_claim_body([NEW_ENTRY]), _wallet([OLD]))
        result = claim(client=client, confirm=False)
        self.assertEqual(client.calls, [])
        self.assertFalse(result.attempted)

    def test_confirmed_executes_and_verifies(self):
        """确认后：领取前快照 -> 领券 -> 领取后核验（强标识一致的新增）。"""
        client = FakeClient(_claim_body([NEW_ENTRY]),
                            _wallet([OLD]), _wallet([OLD, NEW_OWNED]))
        result = claim(client=client, confirm=True)
        self.assertTrue(result.attempted)
        self.assertEqual(client.calls,
                         ["query-my-coupons", "auto-bind-coupons",
                          "query-my-coupons"])
        self.assertTrue(result.ok)
        self.assertTrue(result.verified)
        self.assertIn("已领取并核验", result.message)
        self.assertIn("大薯条优惠券", result.message)

    def test_inconsistent_counts_unknown(self):
        """successCount=1 但成功列表为空：形状不一致，不得 verified。"""
        client = FakeClient(_claim_body([], success=1), _wallet([OLD]))
        result = claim(client=client, confirm=True)
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)
        self.assertNotIn("已领取并核验", result.message)

    def test_preexisting_same_identity_not_new(self):
        """领取前已有同标识的券，不能宣称本次新增。"""
        client = FakeClient(
            _claim_body([{"couponId": "OLDID", "couponCode": "OLDCODE",
                          "couponName": "旧薯条券"}]),
            _wallet([OLD]), _wallet([OLD]))
        result = claim(client=client, confirm=True)
        self.assertFalse(result.verified)
        self.assertNotIn("已领取并核验", result.message)

    def test_conflicting_code_same_id_not_verified(self):
        """券ID相同但券码不一致：多个强标识必须一致，不得误确认。"""
        client = FakeClient(
            _claim_body([{"couponId": "OLDID", "couponCode": "NEWCODE",
                          "couponName": "同类新券"}]),
            _wallet([]),
            _wallet([{"id": "OLDID", "code": "OLDCODE", "title": "冲突券"}]))
        result = claim(client=client, confirm=True)
        self.assertFalse(result.verified)
        self.assertNotIn("已领取并核验", result.message)

    def test_no_identifier_cannot_verify(self):
        """无可靠标识：只能显示接口报告成功、尚未核实。"""
        client = FakeClient(
            _claim_body([{"couponName": "神秘券"}]),
            _wallet([OLD]), _wallet([OLD, NEW_OWNED]))
        result = claim(client=client, confirm=True)
        self.assertTrue(result.ok)
        self.assertFalse(result.verified)
        self.assertIn("尚未核实", result.message)
        self.assertNotIn("已领取并核验", result.message)

    def test_auto_bind_failure_not_shown_as_claimed(self):
        client = FakeClient({"error": {"code": 500, "message": "boom"}},
                            _wallet([OLD]))
        result = claim(client=client, confirm=True)
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)
        self.assertNotIn("已领取并核验", result.message)

    def test_verify_failure_not_shown_as_claimed(self):
        client = FakeClient(_claim_body([NEW_ENTRY]), _wallet([OLD]),
                            {"__transport_error__": "网络错误"})
        result = claim(client=client, confirm=True)
        self.assertTrue(result.ok)          # 接口自称成功
        self.assertFalse(result.verified)   # 但核验失败
        self.assertNotIn("已领取并核验", result.message)

    def test_all_failed(self):
        client = FakeClient(
            _claim_body([], failed=[{"couponId": "X", "couponName": "某券",
                                     "reason": "没有领取资格"}]),
            _wallet([OLD]))
        result = claim(client=client, confirm=True)
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)

    def test_nothing_new_to_claim(self):
        client = FakeClient(_claim_body([]), _wallet([OLD]))
        result = claim(client=client, confirm=True)
        self.assertTrue(result.verified)
        self.assertIn("没有新的券", result.message)

    def test_success_message_uses_names_not_ids(self):
        """成功信息只输出券名，绝不用券ID/券码替代。"""
        entry = {"couponId": "NEWID", "couponCode": "NEWCODE",
                 "couponName": ""}
        owned = {"id": "NEWID", "code": "NEWCODE", "title": "大薯条优惠券"}
        client = FakeClient(_claim_body([entry]), _wallet([OLD]),
                            _wallet([OLD, owned]))
        result = claim(client=client, confirm=True)
        self.assertTrue(result.verified)
        self.assertNotIn("NEWID", result.message)
        self.assertNotIn("NEWCODE", result.message)

    def test_failed_branch_unnamed_not_id(self):
        """失败条目 couponName 为空时显示「未命名券」，绝不回退 couponId/couponCode；
        失败理由里的券ID/券码一律打码，避免 CLI 泄漏私密标识。"""
        client = FakeClient(
            _claim_body([], failed=[
                {"couponId": "SECRETID1234", "couponCode": "SECRETCODE5678",
                 "couponName": "", "reason": "couponId:SECRETID1234 无资格"},
                {"couponId": "ABC123", "couponName": "已知失败的券",
                 "reason": "已达上限"},
            ]),
            _wallet([OLD]))
        result = claim(client=client, confirm=True)
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)
        joined = "".join(result.failed_names)
        # 失败名称不得含原始券ID/券码
        self.assertNotIn("SECRETID1234", joined)
        self.assertNotIn("SECRETCODE5678", joined)
        self.assertNotIn("ABC123", joined)
        # couponName 为空时回退为「未命名券」
        self.assertIn("未命名券", joined)
        # 有名字的券保留名字
        self.assertIn("已知失败的券", joined)
        # 理由里的 ID 字段被打码
        self.assertIn("couponId：***", joined)

    def test_failed_reason_id_redacted(self):
        """失败理由内嵌原始券码时被打码，不进入 failed_names。"""
        client = FakeClient(
            _claim_body([], failed=[
                {"couponId": "Z999", "couponName": "X 券",
                 "reason": "code:TOPSECRET00 couponId:Z999 已过期"},
            ]),
            _wallet([OLD]))
        result = claim(client=client, confirm=True)
        joined = "".join(result.failed_names)
        self.assertNotIn("TOPSECRET00", joined)
        self.assertNotIn("Z999", joined)
        self.assertIn("code：***", joined)
        self.assertIn("couponId：***", joined)

    def test_failed_reason_bare_value_redacted(self):
        """失败理由里裸值（无字段名前缀）出现条目自身的 couponId/couponCode 时，
        也必须被精确替换为 ***，不得泄露私密标识。"""
        client = FakeClient(
            _claim_body([], failed=[
                {"couponId": "TEST_PRIVATE_42",
                 "couponCode": "TEST_CODE_43",
                 "couponName": "",
                 "reason": "券 TEST_PRIVATE_42 / TEST_CODE_43 不可领取"},
            ]),
            _wallet([OLD]))
        result = claim(client=client, confirm=True)
        joined = "".join(result.failed_names)
        # 裸值不得出现
        self.assertNotIn("TEST_PRIVATE_42", joined)
        self.assertNotIn("TEST_CODE_43", joined)
        # 回退为「未命名券」而非 couponId
        self.assertIn("未命名券", joined)
        # 裸值被替换为 ***
        self.assertIn("***", joined)


if __name__ == "__main__":
    unittest.main()

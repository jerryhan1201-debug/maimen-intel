"""显式领券（claim）——默认关闭的独立命令。

规则：
- 只有用户明确执行 claim 命令并携带 --confirm 时才会调用 auto-bind-coupons。
- 未确认时在任何网络调用之前直接拒绝（零网络调用）。
- auto-bind-coupons 返回形状必须可识别，且 successCount/failedCount 与列表一致；
  未知或不一致一律 unknown。
- 核验流程（确认后）：先查卡包（领取前快照）-> auto-bind-coupons -> 再查卡包。
  只有“领取前不存在、领取后出现”的券才算本次新增；
  领取前已有同标识的券不能宣称本次新增。
- 强标识一致核验：券ID与券码都存在时必须指向同一张卡包券且全部一致；
  只有单一标识时可按该标识匹配；券名包含关系一律不算核验。
- 没有可靠标识只可显示“接口报告成功，尚未核实”。
- 成功信息只输出券名；券名为空时显示“未命名券”，绝不用券ID/券码替代输出。
- 强标识只在内存中处理，不写公开文件、状态或日志。
- 失败/未知一律不显示“已领取”。不提供下单、积分消费、抽奖等任何其他写操作。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .parse import (STATUS_EMPTY, STATUS_OK, MyCoupon, parse_my_coupons,
                    unwrap_mcp_result, _check_envelope)


# 失败理由里的原始券ID/券码一律打码，避免泄露到任何输出（含 CLI 与日志）。
# 1) 带字段名前缀的：couponId:XXX / coupon_code:YYY 等
_ID_TOKEN_RE = re.compile(
    r"(?i)(couponId|couponCode|coupon_id|code|id)\s*[:：]?\s*"
    r"([A-Za-z0-9_\-]{4,})")


def _redact_id_tokens(text: str, coupon_id: str = "",
                      coupon_code: str = "") -> str:
    """移除/打码失败理由中的原始券ID与券码。

    两道防线：
    1) 带英文字段名前缀的（couponId:XXX / couponCode:YYY / id:ZZZ …）→ 打码。
    2) 条目自身的 couponId / couponCode 裸值（不带字段名前缀直接出现在
       理由正文里，如「券 TEST_PRIVATE_42 不可领取」）→ 精确替换为 ***。
    """
    result = _ID_TOKEN_RE.sub(lambda m: f"{m.group(1)}：***", text or "")
    # 条目自身裸值精确替换（仅替换长度 >= 4 的，避免误伤短词）
    for value in (coupon_id, coupon_code):
        if value and len(value) >= 4:
            result = result.replace(value, "***")
    return result.strip()


@dataclass
class ClaimedCoupon:
    """领券结果条目（仅内存使用）。"""
    coupon_id: str = ""
    code: str = ""
    name: str = ""


@dataclass
class ClaimResult:
    attempted: bool = False       # 是否发起了网络调用
    confirmed: bool = False
    ok: bool = False              # auto-bind-coupons 业务成功且形状一致
    verified: bool = False        # 前后卡包对比 + 强标识核验通过
    message: str = ""
    success_names: list[str] = field(default_factory=list)
    failed_names: list[str] = field(default_factory=list)


REFUSAL_MESSAGE = ("未提供确认标志（--confirm），已拒绝执行领券；"
                   "未发起任何网络请求。")


def parse_auto_bind(raw: Any) -> tuple[str, list[ClaimedCoupon], list[str], str]:
    """解析 auto-bind-coupons 返回。

    返回 (status, success_entries, failed_names, message)。
    status: ok / failed / error / unknown。
    形状不可识别（{}、{"futureStatus": ...} 等）或计数与列表不一致一律 unknown。
    """
    payload, err = unwrap_mcp_result("auto-bind-coupons", raw)
    if err:
        return "error", [], [], err.message
    data, err = _check_envelope("auto-bind-coupons", payload)
    if err:
        return "error", [], [], err.message
    if not isinstance(data, dict):
        return "unknown", [], [], "领券结果结构待核实，不能确认已领取"
    success_raw = data.get("successCoupons")
    failed_raw = data.get("failedCoupons")
    if not isinstance(success_raw, list) or not isinstance(failed_raw, list):
        return "unknown", [], [], "领券结果结构待核实，不能确认已领取"

    # 计数一致性：successCount/failedCount 存在时必须与列表长度一致
    for count_key, items in (("successCount", success_raw),
                             ("failedCount", failed_raw)):
        count = data.get(count_key)
        if count is not None:
            try:
                if int(count) != len(items):
                    return "unknown", [], [], \
                        "领券结果计数与列表不一致，结构待核实，不能确认已领取"
            except (TypeError, ValueError):
                return "unknown", [], [], \
                    "领券结果计数无法识别，结构待核实，不能确认已领取"

    success: list[ClaimedCoupon] = []
    for c in success_raw:
        if not isinstance(c, dict):
            return "unknown", [], [], "领券结果结构待核实，不能确认已领取"
        success.append(ClaimedCoupon(
            coupon_id=str(c.get("couponId") or ""),
            code=str(c.get("couponCode") or ""),
            name=str(c.get("couponName") or ""),
        ))
    failed: list[str] = []
    for c in failed_raw:
        if isinstance(c, dict):
            cid = str(c.get("couponId") or "").strip()
            ccode = str(c.get("couponCode") or "").strip()
            # 失败条目券名为空时一律显示「未命名券」，绝不回退到 couponId/couponCode
            name = str(c.get("couponName") or "").strip() or "未命名券"
            raw_reason = str(c.get("reason") or "").strip()
            # 理由里不得残留原始券ID/券码：同时处理带字段名前缀和裸值出现
            reason = _redact_id_tokens(raw_reason, cid, ccode)
            failed.append(f"{name}（{reason}）" if reason else name)

    if failed and not success:
        return "failed", success, failed, "全部领取失败"
    message = ""
    if isinstance(payload, dict):
        message = str(payload.get("message") or "")
    return "ok", success, failed, message


def _identity(entry: ClaimedCoupon) -> frozenset:
    return frozenset(x for x in (entry.coupon_id, entry.code) if x)


def _coupon_identity(c: MyCoupon) -> frozenset:
    return frozenset(x for x in (c.coupon_id, c.code) if x)


def _matches(entry: ClaimedCoupon, coupon: MyCoupon) -> bool:
    """强标识一致：entry 提供的每个标识都必须与该券对应字段相同。"""
    if entry.coupon_id and entry.coupon_id != coupon.coupon_id:
        return False
    if entry.code and entry.code != coupon.code:
        return False
    return bool(entry.coupon_id or entry.code)


def claim(client: Any, confirm: bool = False) -> ClaimResult:
    """执行领券。client 需有 call_tool(name, arguments) 方法。"""
    if not confirm:
        # 在任何网络调用之前拒绝
        return ClaimResult(message=REFUSAL_MESSAGE)

    result = ClaimResult(attempted=True, confirmed=True)

    # 1) 领取前卡包快照（用于“本次新增”判定）
    pre_raw = client.call_tool("query-my-coupons",
                               {"page": "1", "pageSize": "200"})
    pre = parse_my_coupons(pre_raw)
    if pre.status not in (STATUS_OK, STATUS_EMPTY) \
            or not isinstance(pre.data, dict):
        result.message = ("领取前卡包查询失败/未知，无法建立基线，已中止；"
                          "未执行领券。")
        return result
    pre_coupons: list[MyCoupon] = pre.data["coupons"]

    # 2) 执行领券
    raw = client.call_tool("auto-bind-coupons", {})
    status, success, failed, message = parse_auto_bind(raw)
    result.success_names = [c.name or "未命名券" for c in success]
    result.failed_names = failed
    if status != "ok":
        result.message = message or "领券接口返回异常，不能确认已领取。"
        return result
    result.ok = True

    if not success:
        result.verified = True
        result.message = "没有新的券被领取（可能之前已领过）。"
        if failed:
            result.message += f" 另有 {len(failed)} 张领取失败。"
        return result

    # 3) 领取后卡包对比核验
    post_raw = client.call_tool("query-my-coupons",
                                {"page": "1", "pageSize": "200"})
    post = parse_my_coupons(post_raw)
    if post.status not in (STATUS_OK, STATUS_EMPTY) \
            or not isinstance(post.data, dict):
        result.message = ("领券接口报告成功，但卡包核验失败/未知，尚未核实；"
                          "请稍后自行在 App 内确认。")
        return result
    post_coupons: list[MyCoupon] = post.data["coupons"]

    # 新增判定：标识集合不在领取前快照中的才算本次新增
    pre_identities = {_coupon_identity(p) for p in pre_coupons}
    new_coupons = [c for c in post_coupons
                   if _coupon_identity(c) not in pre_identities]

    matched: list[ClaimedCoupon] = []
    unidentified = 0
    for entry in success:
        if not entry.coupon_id and not entry.code:
            unidentified += 1  # 没有可靠标识，不能凭名称模糊确认
            continue
        hit = next((c for c in new_coupons if _matches(entry, c)), None)
        if hit is not None:
            matched.append(entry)

    if len(matched) == len(success) and matched:
        result.verified = True
        names = "、".join(c.name or "未命名券" for c in matched)
        result.message = f"已领取并核验 {len(matched)} 张：{names}"
    elif matched:
        names = "、".join(c.name or "未命名券" for c in matched)
        result.message = (f"接口报告成功 {len(success)} 张，"
                          f"仅核验到 {len(matched)} 张本次新增（{names}），"
                          "其余尚未核实，不标记为已领取。")
    elif unidentified:
        result.message = ("领券接口报告成功，但返回结果缺少可靠标识（券ID/券码），"
                          "无法核验，尚未核实。")
    else:
        result.message = ("领券接口报告成功，但未能在卡包中核验到本次新增"
                          "（按券ID/券码严格比对），尚未核实，不标记为已领取。")
    return result

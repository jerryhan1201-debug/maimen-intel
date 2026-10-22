"""麦当劳 MCP（Streamable HTTP）客户端，仅使用 Python 标准库。

安全约束：
- Token 优先取环境变量 ``MCD_MCP_TOKEN``；仅当显式传入 --workbuddy-config 路径时，
  才读取该文件内 ``mcpServers.mcd-mcp.headers.Authorization``。
- Token 接受裸值或完整 ``Bearer ...``，统一只添加一次 Bearer 前缀。
- Token 不出现在日志、异常信息与任何输出中：错误先完整脱敏再截断；
  工具返回结果在交还调用方之前递归脱敏。
- 重定向仅允许同 origin 的 https；拒绝降级（https->http）与跨 origin。
- SSE / JSON 响应都按请求 id 的值与类型严格匹配，并校验响应形状；
  不匹配即协议失败，绝不盲取通知或错误 id 的消息。
- initialize 校验服务端协议版本（必须在支持集合内），保存协商版本，
  后续 initialized 通知与业务请求都使用协商版本。
"""
from __future__ import annotations

import itertools
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})
ENV_TOKEN = "MCD_MCP_TOKEN"


class McpError(Exception):
    """脱敏后的 MCP 错误。"""


def sanitize(message: str, token: str | None) -> str:
    """保证错误信息中不出现真实 Token（含 Bearer 形式）。"""
    text = str(message)
    if token:
        text = text.replace(token, "***")
        bare = token[7:].strip() if token.lower().startswith("bearer ") else token
        if bare:
            text = text.replace(bare, "***")
    return text


def normalize_token(token: str) -> str:
    """统一为恰好一个 ``Bearer `` 前缀。"""
    token = token.strip()
    if token.lower().startswith("bearer "):
        return "Bearer " + token[7:].strip()
    return "Bearer " + token


def load_token(workbuddy_config: str | None = None) -> tuple[str | None, str]:
    """解析 Token。返回 (token, 来源说明)。不打印 token 本体。"""
    env = os.environ.get(ENV_TOKEN)
    if env:
        return env.strip(), f"环境变量 {ENV_TOKEN}"
    if workbuddy_config:
        try:
            with open(workbuddy_config, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            auth = (cfg.get("mcpServers", {}).get("mcd-mcp", {})
                    .get("headers", {}).get("Authorization"))
        except (OSError, ValueError) as exc:
            raise McpError(f"无法读取指定的 WorkBuddy 配置：{exc}") from exc
        if auth:
            return str(auth).strip(), "WorkBuddy 配置 mcpServers.mcd-mcp.headers.Authorization"
        raise McpError("指定的 WorkBuddy 配置中没有 mcd-mcp 的 Authorization")
    return None, "未提供"


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    """仅允许同 origin 的 https 重定向；拒绝降级与跨 origin。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = _origin(req.get_full_url())
        new = _origin(newurl)
        if new[0] != "https":
            raise McpError(
                f"拒绝非 https 重定向：{new[0]}://{new[1]}（不允许降级）")
        if new != old:
            raise McpError(
                f"拒绝跨 origin 重定向：{old[1]}:{old[2]} -> {new[1]}:{new[2]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------------------------------------------------------------------------
# SSE 解析（纯函数，便于测试）
# ---------------------------------------------------------------------------

def parse_sse_events(body: str) -> list[str]:
    """从 SSE 报文中提取所有 data 载荷。"""
    import re
    events: list[str] = []
    for block in re.split(r"\r?\n\r?\n", body):
        data_lines = [line[5:].lstrip() for line in block.splitlines()
                      if line.startswith("data:")]
        if data_lines:
            events.append("\n".join(data_lines))
    return events


def messages_from_sse(body: str) -> list[dict]:
    """SSE 报文 -> JSON-RPC 消息列表（忽略无法解析的载荷）。"""
    messages: list[dict] = []
    for event in parse_sse_events(body):
        try:
            msg = json.loads(event)
        except (ValueError, TypeError):
            continue
        if isinstance(msg, dict):
            messages.append(msg)
    return messages


def _id_matches(msg_id: Any, request_id: Any) -> bool:
    """id 的值与类型都必须一致（True 不等于 1）。"""
    return type(msg_id) is type(request_id) and msg_id == request_id


def _valid_response_shape(msg: dict) -> bool:
    return "result" in msg or "error" in msg


def select_response(messages: list[dict], request_id: Any) -> dict | None:
    """严格按请求 id（值+类型）匹配；通知（无 id / 带 method）一律跳过；
    响应必须是合法的 result/error 形状。"""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if "id" not in msg or "method" in msg:
            continue  # 通知
        if _id_matches(msg.get("id"), request_id) and _valid_response_shape(msg):
            return msg
    return None


def _redact(obj: Any, token: str | None) -> Any:
    """递归脱敏：返回结果中的任何字符串都不得含有 token。"""
    if not token:
        return obj
    if isinstance(obj, str):
        return sanitize(obj, token)
    if isinstance(obj, dict):
        return {k: _redact(v, token) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v, token) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

@dataclass
class McpClient:
    endpoint: str = DEFAULT_ENDPOINT
    token: str | None = None
    timeout: float = 30.0
    opener: Any = None  # 可注入 urllib opener 便于测试

    def __post_init__(self):
        self._ids = itertools.count(1)
        self.session_id: str | None = None
        self.initialized = False
        self.protocol_version = PROTOCOL_VERSION  # initialize 后更新为协商版本
        if self.opener is None:
            self.opener = urllib.request.build_opener(_NoCredentialRedirect())

    # -- 内部 -------------------------------------------------------------

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "maimen-intel/1.0",
        }
        if self.token:
            headers["Authorization"] = normalize_token(self.token)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.initialized:
            headers["MCP-Protocol-Version"] = self.protocol_version
        if extra:
            headers.update(extra)
        return headers

    def _post(self, payload: dict) -> tuple[int, Any, bytes]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body,
                                     headers=self._headers(), method="POST")
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.headers, resp.read()
        except McpError:
            raise
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                # 先完整脱敏，再截断（顺序不能反）
                detail = sanitize(
                    exc.read().decode("utf-8", "replace"), self.token)[:200]
            except Exception:
                pass
            raise McpError(f"HTTP {exc.code}：{detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise McpError(sanitize(f"网络错误：{exc}", self.token)) from exc

    def _decode(self, headers: Any, body: bytes, request_id: Any) -> dict:
        """按 Content-Type 解码并严格匹配响应；不匹配即协议失败。"""
        ctype = ""
        try:
            ctype = headers.get("Content-Type", "") or ""
        except AttributeError:
            pass
        text = body.decode("utf-8", "replace")
        if "text/event-stream" in ctype:
            msg = select_response(messages_from_sse(text), request_id)
        else:
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                raise McpError("协议失败：响应既不是 JSON 也不是可解析的 SSE")
            if isinstance(parsed, dict) and "method" not in parsed \
                    and "id" in parsed and _id_matches(parsed.get("id"), request_id) \
                    and _valid_response_shape(parsed):
                msg = parsed
            else:
                msg = None
        if msg is None:
            raise McpError(f"协议失败：未收到与请求 id={request_id} 匹配的合法响应")
        return msg

    # -- 协议 -------------------------------------------------------------

    def initialize(self) -> None:
        request_id = 0
        payload = {
            "jsonrpc": "2.0", "id": request_id, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "maimen-intel", "version": "1.0.0"},
            },
        }
        _, headers, body = self._post(payload)
        msg = self._decode(headers, body, request_id)
        if "error" in msg:
            code = msg["error"].get("code", "?") \
                if isinstance(msg["error"], dict) else "?"
            raise McpError(f"initialize 被拒绝（code={code}）")
        result = msg.get("result")
        if not isinstance(result, dict) or not result:
            raise McpError("协议失败：initialize 缺少有效 result")
        version = result.get("protocolVersion")
        if not isinstance(version, str) or version not in SUPPORTED_VERSIONS:
            raise McpError(f"协议失败：不支持的协议版本 {version!r}")
        if not isinstance(result.get("capabilities"), dict) \
                or not isinstance(result.get("serverInfo"), dict):
            raise McpError("协议失败：initialize result 缺少 capabilities/serverInfo")
        self.protocol_version = version  # 保存协商版本
        try:
            sid = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        except AttributeError:
            sid = None
        if sid:
            self.session_id = sid
        self.initialized = True
        # initialized 通知（无 id，使用协商版本与会话头）
        notice = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            self._post(notice)
        except McpError:
            pass  # 通知失败不阻断

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """调用工具。失败时返回 {'__transport_error__': 脱敏信息}，不抛异常。

        返回结果已递归脱敏，任何字符串都不会含有 token。
        """
        if not self.initialized:
            try:
                self.initialize()
            except McpError as exc:
                return {"__transport_error__": sanitize(str(exc), self.token)}
        request_id = next(self._ids)
        payload = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments or {}}}
        try:
            _, headers, body = self._post(payload)
            msg = self._decode(headers, body, request_id)
        except McpError as exc:
            return {"__transport_error__": sanitize(str(exc), self.token)}
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {}
            return {"error": {"code": err.get("code", "?"),
                              "message": sanitize(err.get("message", ""), self.token)}}
        result = msg.get("result")
        if not isinstance(result, dict):
            return {"__transport_error__": "协议失败：响应缺少 result"}
        return _redact(result, self.token)

# MCP 集成说明

## 端点与协议

- 入口：`https://mcp.mcd.cn`，Streamable HTTP（单端点 POST）。
- 每次请求头：`Content-Type: application/json`，`Accept: application/json, text/event-stream`。
- `initialize` 协商：客户端提议 `2025-06-18`，支持集合
  `{2024-11-05, 2025-03-26, 2025-06-18}`；服务端版本必须在支持集合内，
  且 `result` 必须包含 `capabilities`/`serverInfo`，否则协议失败。
  协商后的版本会保存，并在后续 `notifications/initialized` 与业务请求的
  `MCP-Protocol-Version` 头中使用；`Mcp-Session-Id` 响应头会被保留并随请求回传。
- 响应解码：按 `Content-Type` 区分 JSON 与 SSE；SSE 拆 `data:` 事件后按
  **JSON-RPC 请求 id 的值与类型严格匹配**（`true` 不等于 `1`），通知一律跳过，
  不盲取最后一条消息；不匹配即协议失败。
- 健壮性：请求有超时；HTTP 错误**先完整脱敏再截断**；拒绝非 https 与跨 origin
  的重定向（不携带凭证降级/跨域）；工具返回结果在交还调用方之前递归脱敏。

## 凭证

- 优先环境变量 `MCD_MCP_TOKEN`；裸 token 与 `Bearer ...` 都接受，统一只加一次前缀。
- 仅显式 `--workbuddy-config <路径>` 时读取该文件
  `mcpServers.mcd-mcp.headers.Authorization`，不读取其他连接器凭证。
- Token 不出现在项目文件、文档、日志、命令参数、报错与 run-status.json 中。

## 使用的工具（日报只读四个 + 显式领券一个）

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `campaign-calendar` | `{}`（查当月） | 公共活动日历 |
| `available-coupons` | `{}` | 当前可领取的券 |
| `query-my-coupons` | `page`/`pageSize` 字符串，最多 5 页 × 200 | 我的券（分页范围如实标注） |
| `query-my-account` | `{}` | 积分月度汇总 |
| `auto-bind-coupons` | `{}` | **仅** claim --confirm 分支调用，领后核验 |

## 真实字段（依据 tools/list 快照，2026-10-22 live 实测一致）

- `campaign-calendar`：`data.dailyList[].date/dateText/today/events[]`，
  event 含 `activityTitle/activitySubTitle/articleDto{title,content}/couponInfo{
  tradeStartDate,tradeEndDate}`。公开版绝不读取 `subscribedEvents`（个人订阅状态）。
- `available-coupons`：`data[]` 含 `couponName/couponStatus/label`。
- `query-my-coupons`：`data.coupons[]` 含 `id/code/title/subtitle/
  discountInfo.discountDesc/tradeStartDate/tradeEndDate/datetimeText/tags/enable`，
  分页元数据 `totalCount/totalPages/currentPage/pageSize`。
- `query-my-account`：`data.availablePoint/currentMouthExpirePoint/
  nextMouthExpirePoint/lastMouthExpirePoint` 等为**字符串数字**；字段原名保留；
  只表示月度汇总，无日级到期日期。
- `auto-bind-coupons`：`data.totalCount/successCount/failedCount/
  successCoupons[]/failedCoupons[]`，条目含 `couponId/couponCode/couponName`。

## 历史问题与本次实测的区分

历史记录（来自分享记录，本次未复现、按防御处理）：

- `available-coupons` 曾返回 `-32602` 与 `data/data must be array` —— 
  代码按“查询失败”处理，绝不当 0 张；本次 live 实测该接口正常返回数组。
- “服务繁忙，请稍后再试”按 error 处理，不当 empty。

本次实测（2026-10-22，live）：

- 四个只读接口均可正常协商与调用；响应为 `structuredContent` 或 JSON 文本包装，
  两种形态均已支持。
- 真实活动中大量文案只有开售日（如“10月8日10:45开售”），按规则进入
  「日期待核实」而不是被猜测为进行中。
- 已验证 `query-my-coupons` 的空结果语义，以及 `query-my-account` 的字符串数字解析；公开记录不包含真实账户结果。

## 错误与未知语义

- `isError` / JSON-RPC error / HTTP 错误 / 业务 `code != 200` → “查询失败”。
- 非空但无法识别的结构 → “结构待核实”（unknown），不谎称已核验。
- 只有明确空（空数组 / 严格纯空响应）才显示“暂无”。

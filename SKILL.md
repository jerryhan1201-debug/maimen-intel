---
name: maimen-intel
description: 麦当劳活动本地简报（麦门情报站）。当用户想了解"今天麦当劳有什么活动/优惠"、"有什么券可以领"、"我的券和积分到期情况"，或要求生成麦当劳日报/分享图/小红书草稿时使用。默认只读查询四个接口生成简报；只有用户明确说"领券/一键领取"并确认后才进入领券分支。
---

# 麦门情报站

生成当日麦当劳情报简报的本地工具。**非麦当劳官方产品**。

## 触发范围

- 适用：今日/即将开始/即将结束的麦当劳活动、可领券、我的券、积分月度到期提醒、
  生成分享 PNG / 小红书草稿 / 私人或公开 HTML 简报。
- 不适用：下单、积分兑换/消费、抽奖、外送地址管理等任何其他写操作——一律拒绝并说明。

## 只读日报流程（默认）

依次调用四个只读工具，单接口失败不阻断，失败/未知进入「数据异常」区：

1. `campaign-calendar`（参数 `{}`）→ 公共活动，按日期分区：
   今日进行中 / 即将结束（3 天内）/ 即将开始 / 日期待核实。
   - 优先 `data.dailyList[].events`（title、articleDto）；绝不读取 `subscribedEvents`。
   - 活动日期优先券核销期；仅起始日/含糊日期一律进「日期待核实」；
     明确写出的年份绝不改写；反向/非法区间标为不确定。
2. `available-coupons`（参数 `{}`）→ 可领券列表。
   - 失败（含历史 -32602、data must be array）显示“查询失败”，不得当作 0 张；
   - 非空但无法识别的结构为 unknown（“结构待核实”）；
   - 只有空数组或严格纯空响应才算 empty；“服务繁忙”是 error 不是 empty。
3. `query-my-coupons`（page/pageSize 为字符串，最多 5 页、每页最多 200）→ 我的券，
   如实标注分页范围；后续页失败保留已查页并标注“结果不完整”。
4. `query-my-account`（参数 `{}`）→ 积分月度汇总：
   `availablePoint`/`currentMouthExpirePoint`/`nextMouthExpirePoint`/`lastMouthExpirePoint`
   保留原名；缺失/非法/NaN/Infinity 显示“接口未返回”，不补 0；无日级到期日期。

## 凭证

- 优先环境变量 `MCD_MCP_TOKEN`（裸 token 或 Bearer 均可）。
- 仅当用户显式传 `--workbuddy-config <路径>` 时读取该文件内
  `mcpServers.mcd-mcp.headers.Authorization`；绝不读取其他连接器凭证。
- Token 不写入项目/文档/日志/命令参数/报错。

## 输出

每次运行生成到 `outputs/<demo|live>/<日期>/`：

- 私人版 `report-private.md` / `report-private.html`：含个人券与积分。
- 公开版 `report-public.html`、`share-1080.png`、`xhs-draft.md`：
  **只有公共活动与通用领券指引**，不含个人积分、卡包明细、账号标识、Token。
- 券码/券号/会员号等标识在所有投影中统一打码；run-status.json 只含通用原因。
- demo / live 输出与状态完全隔离；状态仅存散列键，重复当日去重、
  重复生成不重复标“新”、内容变化可识别更新。

## 显式领券分支（默认关闭）

仅当用户明确说“领券/一键领取”并加 `--confirm`：

```bash
python -m maimen_intel claim --confirm
```

流程：领取前卡包快照 → `auto-bind-coupons` → 领取后卡包核验。
核验只按券ID/券码严格比对“本次新增”；无可靠标识或标识冲突时显示
“接口报告成功，尚未核实”；失败/未知一律不显示“已领取”。
未携带 `--confirm` 时在任何网络调用前拒绝。日报流程永不触发领券。

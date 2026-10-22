# workbuddy.md — 麦门情报站本机重建记录

## 背景

用户提供了一份历史 WorkBuddy 需求记录，要求用 Kimi 接续实现「麦门情报站」。原代码在另一台电脑、公开仓库仍为空，
用户已明确同意「按分享记录的需求，在本机重新实现」。因此这是**本机新实现**，
不声称恢复了原代码或继承了原先的测试历史。

后因 Kimi 模型频率限制，由 GLM-5.2 接续完成最后收尾。

## 分享记录需求摘要

- 工作空间：项目根目录 `maimen-intel/`
- 远程文档参考：`https://github.com/jerryhan1201-debug/maimen-intel`（经用户授权发布的目标仓库）
- 交付：可复用根目录 `SKILL.md` + 可安装、可运行的 Python 本地简报工具
- 命令：`python -m maimen_intel demo / live / claim`
- 输出：私人 Markdown/HTML、公开 HTML、1080px PNG、小红书草稿
- MCP：`https://mcp.mcd.cn`，Streamable HTTP，环境变量 `MCD_MCP_TOKEN` 或显式
  `--workbuddy-config ~/.workbuddy/mcp.json`
- 只读调用：`campaign-calendar`、`available-coupons`、`query-my-coupons`、`query-my-account`
- 不真实领券、不推送、不发布、不报名、不设定时任务

## 实际完成情况

### 源码

完整实现于 `maimen_intel/` 包：

| 模块 | 职责 |
| --- | --- |
| `dates.py` | 北京时间日期解析；NFKC 规范化；明确年份保留；跨月/跨年保守处理 |
| `parse.py` | 四种内容格式解析（content/JSON/structuredContent/Markdown）；券码/会员号打码 |
| `mcp_client.py` | Streamable HTTP 客户端；initialize 协商；SSE 按请求 ID 匹配；重定向脱敏 |
| `state.py` | 散列键状态去重；预览/提交分离；demo/live 隔离 |
| `report.py` | 报告模型；私人/公开视图隔离；活动分类与增量识别 |
| `claim.py` | 显式领券（默认关闭）；前后卡包对比 + 强标识核验；失败名/理由脱敏 |
| `render/` | Markdown / HTML / PNG / 小红书渲染 |
| `runner.py` | 编排：拉取→解析→构建报告→渲染→提交状态 |
| `__main__.py` | CLI 入口 |

### 测试

- **unittest：99 项全部通过**（`python -m unittest discover -s tests`）
- 覆盖：日期解析（跨月/跨年/闰年/明确年份/特殊数字）、内容解析（四种格式/失败/空/unknown）、
  私公隔离（唯一标记注入后断言所有公开格式不含）、单接口失败、空卡包、积分未知/月度、
  长标题、demo 跨年、两次运行去重与 mode 隔离、SSE 匹配 ID 与通知、claim 各分支
  （默认不触发/未确认拒绝/确认 mock 执行且核验/失败不显示成功/失败名不回退券ID/
  失败理由裸值脱敏）。
- **定向 mock 复测**（`work/maimen_remaining_review.py`）：11 项用例的 actual 输出
  均符合 expected 描述，无隐私泄露。

### 真实只读 live 验证

已完成 `campaign-calendar`、`available-coupons`、`query-my-coupons`、
`query-my-account` 的真实只读连接与响应解析验证。凭证仅从本机显式指定的配置读取，
未打印 Token，未保存原始账户响应。

发布内容不包含真实账户结果、私人日报、运行状态或本机凭证；
仓库中的 `examples/demo/` 仅使用内置虚构数据。

### demo 两次去重

- 第一次运行：`new_items` > 0（标“新”）
- 第二次运行：`new_items = 0`（重复生成不重复标新）
- 状态键已散列（含内容维度），demo/live 状态隔离

### 视觉验证

- PNG（1080px 宽，动态高度）：通过 `view_image` 静态查看，文字正常、长标题不溢出、
  footer 不覆盖正文、无字体不支持的 emoji，新增用中文"新"徽标。
- HTML：通过程序化正则解析检查锚点无死链、筛选按钮存在且 `data-filter`/`data-category`
  匹配、`<details>` 展开结构存在、`prefers-reduced-motion` 规则存在。
- 私人页"可领券"导航不重复（demo 与 live 均已验证）。
- 公开 HTML 领取指引仅保留官方 App/小程序路径，无本地 Python 命令。
- **未做浏览器点击验收**：上述检查均为静态解析与脚本逻辑匹配，未在浏览器内
  实际点击按钮、展开 `<details>` 或测试筛选交互。先前 IAB 已因安全策略拒绝
  本地 `file://` 浏览器导航，未改用服务器、别的浏览器或间接方式绕开。

### live HTML 静态修正

对本地真实日报的固定导航与领取指引做了静态修正，保留原数据和生成时间，
未重新查询、未用 demo 替换。静态检查确认私人页“可领券”导航仅一项、
公开页不含该导航、无本地 Python 命令与锚点死链。真实日报不随仓库发布。

## 审查反馈处理

> 以下审查由 Codex（自动化审查工具）执行，修复由 Kimi 或 GLM 完成，用户只提供任务方向。

### round1（Codex 审查，Kimi 修复）

- MCP 客户端 `initialize` 形状校验、协议版本范围、响应 ID 严格匹配
- Token 错误脱敏（不输出到日志/报错/命令参数）
- 明确年份保留（`extract_date_range('2025年10月8日至10月21日', date(2026,10,18))` 不改 2025）
- unknown 与 empty 严格区分（"服务繁忙"不当空）
- 公开输出仅公共活动 + 通用领券指引

### round2（Codex 审查，Kimi 修复）

- 状态预览/提交分离（渲染失败不消费 new-item 状态）
- 散列状态键（内容变化可识别更新）
- 分页上限如实标注（上限 5 页、每页 200 条）
- `available-coupons` 非数组结构 → 查询失败，不当 0 张
- 结构化反向日期（开始 > 结束）→ 日期待核实，不误判为已结束
- claim 前后卡包对比 + 强标识一致核验
- 公开 HTML 导航不含"可领券"死链

### round3（Codex 定向复测，GLM 修复）

- `claim.py` 失败条目 `couponName` 为空时回退"未命名券"（不回退 couponId）
- 失败理由里原始券ID/券码（带字段名前缀和裸值出现）一律打码
- 私人页"可领券"导航去重
- 公开 HTML 领取指引移除本地 Python 命令
- live HTML 静态快照修正（不重新查询、不用 demo 替换）

## 文档清单

| 文件 | 说明 |
| --- | --- |
| `README.md` | 目标用户、安装、demo/live/claim 命令、示例、限制 |
| `SKILL.md` | WorkBuddy 技能定义（name/description YAML，触发范围，四项只读流程） |
| `MCP_INTEGRATION.md` | MCP 集成细节（真实字段/价值/历史问题与实测区分） |
| `mcp-config.example.json` | 配置示例（type streamablehttp，仅环境变量占位符） |
| `CONTEST_DECLARATION.md` | 官方参赛声明（原文逐字保留，SHA256 已校验） |
| `requirements.txt` | 依赖清单（Pillow） |
| `.gitignore` | 排除 .env、缓存、outputs/、state/、临时凭证 |
| `workbuddy.md` | 本文件 |

## 隐私保障

- Token 不写入项目、文档、日志、命令参数、示例、报错
- 仅显式 `--workbuddy-config` 时读 `mcp.json` 内 `mcpServers.mcd-mcp.headers.Authorization`，
  绝不读取其他连接器凭证
- 敏感原始账户响应不保存
- 私人/公开在类型层面隔离（`Report` vs `PublicReport`）
- 券码/会员号/券ID 在所有输出（含公开）统一打码
- `run-status.json` 只存脱敏状态（tool status + 通用 message）

## 不做的事

- 不真实领券（`auto-bind-coupons` 只 mock 测试，不真实执行）
- 不下单、不积分消费、不抽奖
- 不推送 GitHub、不发布、不报名
- 不创建真实定时任务
- 不绕过浏览器限制

"""命令行入口。

  python -m maimen_intel demo                        # 无凭证演示
  python -m maimen_intel live                        # 真实只读查询（需凭证）
  python -m maimen_intel live --workbuddy-config ~/.workbuddy/mcp.json
  python -m maimen_intel claim --confirm             # 显式一键领券（默认关闭）
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .claim import claim
from .mcp_client import McpClient, McpError, load_token
from .runner import MAX_PAGES, run_brief


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"无效日期：{value}（应为 YYYY-MM-DD）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maimen_intel",
        description="麦门情报站：麦当劳活动本地简报工具（非麦当劳官方产品）")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--date", type=_parse_date, default=None,
                       help="基准日期 YYYY-MM-DD（默认：北京时间今天）")
        p.add_argument("--output-dir", default=None, help="输出目录")
        p.add_argument("--state-dir", default=None, help="状态目录（本地、勿提交）")

    p_demo = sub.add_parser("demo", help="用虚构示例数据生成完整简报（无需凭证）")
    common(p_demo)

    p_live = sub.add_parser("live", help="真实查询四项只读接口并生成简报")
    common(p_live)
    p_live.add_argument("--workbuddy-config", default=None,
                        help="显式指定 WorkBuddy mcp.json 路径以读取 mcd-mcp 凭证；"
                             "默认只读环境变量 MCD_MCP_TOKEN")
    p_live.add_argument("--max-pages", type=int, default=MAX_PAGES,
                        help="我的券最多查询页数（上限 5，默认 5）")

    p_claim = sub.add_parser("claim", help="一键领取当前可领的券（默认关闭，需 --confirm）")
    p_claim.add_argument("--confirm", action="store_true",
                         help="确认执行领券；不带此标志时在任何网络调用前拒绝")
    p_claim.add_argument("--workbuddy-config", default=None,
                         help="同 live 的凭证来源说明")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command in ("demo", "live"):
        try:
            status = run_brief(
                mode=args.command, today=args.date,
                output_dir=args.output_dir, state_dir=args.state_dir,
                workbuddy_config=getattr(args, "workbuddy_config", None),
                max_pages=getattr(args, "max_pages", MAX_PAGES))
        except McpError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        print(f"[{status['mode']}] {status['date']} 生成完毕"
              f"（凭证来源：{status['token_source']}）")
        for name, tool in status["tools"].items():
            msg = f" — {tool['message']}" if tool["message"] else ""
            print(f"  · {name}: {tool['status']}{msg}")
        if status["anomalies"]:
            print("  数据异常：")
            for a in status["anomalies"]:
                print(f"    - {a}")
        print("  产物：")
        for key, path in status["outputs"].items():
            print(f"    - {key}: {path}")
        return 0

    if args.command == "claim":
        # 未确认：在任何网络调用之前拒绝（不创建客户端）
        if not args.confirm:
            result = claim(client=None, confirm=False)
            print(result.message, file=sys.stderr)
            return 2
        try:
            token, source = load_token(args.workbuddy_config)
        except McpError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        if not token:
            print("错误：未找到凭证（需要环境变量 MCD_MCP_TOKEN 或 "
                  "--workbuddy-config）。", file=sys.stderr)
            return 2
        print(f"开始一键领券（凭证来源：{source}）…")
        client = McpClient(token=token)
        result = claim(client=client, confirm=True)
        print(result.message)
        if result.failed_names:
            print("  领取失败：")
            for name in result.failed_names:
                print(f"    - {name}")
        return 0 if result.verified else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

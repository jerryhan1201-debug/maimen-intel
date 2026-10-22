"""编排：拉取数据 -> 构建报告 -> 渲染全部产物 -> 记录脱敏状态。"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from . import demo_data
from .dates import beijing_now
from .mcp_client import McpClient, McpError, load_token, sanitize
from .parse import (STATUS_OK, ToolResult, parse_available_coupons,
                    parse_campaign_calendar, parse_my_account,
                    parse_my_coupons)
from .render import html as render_html
from .render import markdown as render_md
from .render import png as render_png
from .render import xhs as render_xhs
from .report import Report, build_report, to_public
from .state import StateStore

MAX_PAGES = 5
MIN_PAGES = 1
PAGE_SIZE = 200

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def clamp_pages(value: int) -> int:
    """--max-pages 只允许 1..5，越界截断。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return MAX_PAGES
    return max(MIN_PAGES, min(MAX_PAGES, n))


def _hash_key(*parts: Any) -> str:
    """状态键一律散列：不持久化券名/活动原文，同时包含内容维度，
    使“同条活动内容变化”能被识别为更新。"""
    import hashlib
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _fetch_live(today: date, workbuddy_config: str | None,
                max_pages: int = MAX_PAGES) -> tuple[dict[str, ToolResult], str, str]:
    """执行四项只读查询。返回 (结果字典, 来源说明, 脱敏 token 来源)。"""
    max_pages = clamp_pages(max_pages)
    token, token_source = load_token(workbuddy_config)
    if not token:
        raise McpError(
            "未找到凭证。请设置环境变量 MCD_MCP_TOKEN，"
            "或显式传 --workbuddy-config <mcp.json 路径>。")
    client = McpClient(token=token)
    results: dict[str, ToolResult] = {}

    results["campaign-calendar"] = parse_campaign_calendar(
        client.call_tool("campaign-calendar", {}), today)
    results["available-coupons"] = parse_available_coupons(
        client.call_tool("available-coupons", {}))

    # 我的券：最多 max_pages 页、每页最多 200 条，如实记录分页范围
    first = parse_my_coupons(
        client.call_tool("query-my-coupons",
                         {"page": "1", "pageSize": str(PAGE_SIZE)}), page=1)
    if first.status == STATUS_OK and isinstance(first.data, dict):
        meta = dict(first.data["meta"])
        coupons = list(first.data["coupons"])
        try:
            total_pages = int(meta.get("totalPages") or 1)
        except (TypeError, ValueError):
            total_pages = 1
        pages_fetched = 1
        incomplete = False
        for page in range(2, min(total_pages, max_pages) + 1):
            more = parse_my_coupons(
                client.call_tool("query-my-coupons",
                                 {"page": str(page), "pageSize": str(PAGE_SIZE)}),
                page=page)
            if more.status != STATUS_OK or not isinstance(more.data, dict):
                incomplete = True  # 保留已查页，但如实标记不完整
                break
            coupons.extend(more.data["coupons"])
            pages_fetched = page
        if total_pages > pages_fetched:
            incomplete = True
        meta["pagesFetched"] = pages_fetched
        meta["incomplete"] = incomplete
        note = first.message
        if incomplete:
            note = (note + "；" if note else "") + \
                f"仅查询第 1..{pages_fetched} 页 / 共 {total_pages} 页，结果不完整"
        results["query-my-coupons"] = ToolResult(
            "query-my-coupons", first.status,
            data={"coupons": coupons, "meta": meta}, message=note)
    else:
        results["query-my-coupons"] = first

    results["query-my-account"] = parse_my_account(
        client.call_tool("query-my-account", {}))
    return results, f"麦当劳 MCP（{client.endpoint}）", token_source


def _fetch_demo(today: date) -> tuple[dict[str, ToolResult], str, str]:
    return {
        "campaign-calendar": demo_data.demo_calendar(today),
        "available-coupons": demo_data.demo_available_coupons(today),
        "query-my-coupons": demo_data.demo_my_coupons(today),
        "query-my-account": demo_data.demo_account(today),
    }, "内置虚构演示数据", "无需凭证"


def run_brief(mode: str, today: date | None = None,
              output_dir: str | Path | None = None,
              state_dir: str | Path | None = None,
              workbuddy_config: str | None = None,
              max_pages: int = MAX_PAGES) -> dict[str, Any]:
    """生成一次日报。返回产物路径与脱敏状态。"""
    today = today or beijing_now().date()
    generated_at = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    output_dir = Path(output_dir or PROJECT_ROOT / "outputs")
    state_dir = Path(state_dir or PROJECT_ROOT / "state")

    if mode == "demo":
        results, source, token_source = _fetch_demo(today)
    elif mode == "live":
        results, source, token_source = _fetch_live(today, workbuddy_config,
                                                    max_pages)
    else:
        raise ValueError(f"未知模式：{mode}")

    # 增量识别：“新”徽标。状态键一律散列（含内容维度，内容变化可识别更新）。
    # 先预览（不写盘），全部产物渲染成功后才提交状态——失败重试仍保留“新”识别。
    store = StateStore(state_dir, mode)
    keys: list[str] = []
    cal = results["campaign-calendar"]
    if cal.status == STATUS_OK and cal.data:
        keys.extend(_hash_key("c", c.title, c.start, c.end, c.summary,
                              tuple(c.conditions), c.date_group)
                    for c in cal.data)
    mine = results["query-my-coupons"]
    if mine.status == STATUS_OK and isinstance(mine.data, dict):
        keys.extend(_hash_key("k", c.title, c.start, c.end, c.subtitle,
                              c.discount_desc)
                    for c in mine.data["coupons"])
    new_hashed = store.preview_new(keys)
    # 映射回业务 key 供 is_new 判断
    new_keys: set[str] = set()
    if cal.status == STATUS_OK and cal.data:
        for c in cal.data:
            if _hash_key("c", c.title, c.start, c.end, c.summary,
                         tuple(c.conditions), c.date_group) in new_hashed:
                new_keys.add(c.key)
    if mine.status == STATUS_OK and isinstance(mine.data, dict):
        for c in mine.data["coupons"]:
            if _hash_key("k", c.title, c.start, c.end, c.subtitle,
                         c.discount_desc) in new_hashed:
                new_keys.add(c.key)

    meta = (mine.data.get("meta", {}) if mine.status == STATUS_OK
            and isinstance(mine.data, dict) else {})
    pagination_note = ""
    if meta:
        fetched = meta.get("pagesFetched", meta.get("currentPage", "?"))
        pagination_note = (f"已查询第 1..{fetched} 页 / "
                           f"共 {meta.get('totalPages', '?')} 页，"
                           f"总计 {meta.get('totalCount', '?')} 张"
                           f"（最多查询 {clamp_pages(max_pages)} 页、"
                           f"每页最多 {PAGE_SIZE} 条）")
        if meta.get("incomplete"):
            pagination_note += "；后续页未查询或查询失败，结果不完整"

    report = build_report(
        mode=mode, today=today, generated_at=generated_at, source=source,
        calendar=cal, available=results["available-coupons"],
        my_coupons=mine, account=results["query-my-account"],
        new_keys=new_keys)
    report.pagination_note = pagination_note

    public = to_public(report)

    out_dir = output_dir / mode / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "private_md": out_dir / "report-private.md",
        "private_html": out_dir / "report-private.html",
        "public_html": out_dir / "report-public.html",
        "png": out_dir / "share-1080.png",
        "xhs": out_dir / "xhs-draft.md",
    }
    paths["private_md"].write_text(render_md.render_private_markdown(report),
                                   encoding="utf-8")
    paths["private_html"].write_text(render_html.render_private_html(report),
                                     encoding="utf-8")
    paths["public_html"].write_text(render_html.render_public_html(public),
                                    encoding="utf-8")
    _, png_height = render_png.render_png(public, str(paths["png"]))
    paths["xhs"].write_text(render_xhs.render_xhs_draft(public), encoding="utf-8")

    # 全部渲染成功后才提交“新”状态
    store.commit(keys, today)

    # 持久化状态只写通用原因，不保存任何接口原文（可能含账户标识）
    _GENERIC = {"ok": "成功", "empty": "空", "error": "查询失败",
                "unknown": "结构待核实"}
    _LABELS = {"campaign-calendar": "活动日历", "available-coupons": "可领券",
               "query-my-coupons": "我的券", "query-my-account": "积分账户"}
    generic_anomalies = [
        f"{_LABELS.get(name, name)}：{_GENERIC.get(r.status, r.status)}"
        for name, r in results.items()
        if r.status in ("error", "unknown")]
    status = {
        "mode": mode,
        "date": today.isoformat(),
        "generated_at": generated_at,
        "token_source": token_source,
        "tools": {name: {"status": r.status,
                         "message": _GENERIC.get(r.status, r.status)}
                  for name, r in results.items()},
        "anomalies": generic_anomalies,
        "new_items": len(new_keys),
        "png": {"width": 1080, "height": png_height},
        "outputs": {k: str(v) for k, v in paths.items()},
    }
    # 状态记录只含脱敏信息
    (out_dir / "run-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status

"""HTML 渲染：报刊式版面，奶油白纸面 + 红色主强调。

- 私人版（Report）含个人券与积分；公开版（PublicReport）类型上不含个人数据。
- 所有按钮均有实际行为：分区筛选、锚点导航、使用条件展开。
- 尊重 prefers-reduced-motion。
"""
from __future__ import annotations

import html as _html

from ..parse import STATUS_EMPTY, STATUS_OK
from ..report import (CALENDAR_STATUS_NOTES, CATEGORY_LABELS, CATEGORY_ORDER,
                      PublicReport, Report, points_note)

_REPO_URL = "https://github.com/jerryhan1201-debug/maimen-intel"

_CSS = """
:root {
  --paper: #faf5ea;
  --paper-deep: #f3ecdb;
  --ink: #33302b;
  --ink-soft: #6b6459;
  --red: #c62f22;
  --red-deep: #a52418;
  --yellow: #f4b400;
  --rule: #d8cfba;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper-deep); color: var(--ink);
  font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  line-height: 1.65;
}
.page {
  max-width: 880px; margin: 24px auto; background: var(--paper);
  border: 1px solid var(--rule); box-shadow: 0 2px 14px rgba(60, 45, 20, .08);
  padding: 40px 44px 28px;
}
.masthead { text-align: center; border-bottom: 3px double var(--ink); padding-bottom: 18px; }
.masthead .brand {
  font-size: 44px; font-weight: 800; letter-spacing: 6px; color: var(--red);
  margin: 0;
}
.masthead .brand .dot { color: var(--yellow); }
.masthead .meta { color: var(--ink-soft); font-size: 13px; margin-top: 8px; }
.badge {
  display: inline-block; padding: 1px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 700; vertical-align: middle;
}
.badge.mode-demo { background: var(--yellow); color: #4a3200; }
.badge.mode-live { background: var(--red); color: #fff; }
.badge.scope { border: 1px solid var(--ink-soft); color: var(--ink-soft); }
.disclaimer {
  margin: 14px 0 0; font-size: 12px; color: var(--ink-soft);
  background: var(--paper-deep); border-left: 3px solid var(--yellow);
  padding: 6px 10px; text-align: left;
}
nav.toc {
  display: flex; flex-wrap: wrap; gap: 8px 18px; justify-content: center;
  border-bottom: 1px solid var(--rule); padding: 12px 0; font-size: 14px;
}
nav.toc a { color: var(--red); text-decoration: none; border-bottom: 1px dotted var(--red); }
nav.toc a:hover { color: var(--red-deep); }
.filters {
  display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 4px;
}
.filters button {
  font: inherit; font-size: 13px; cursor: pointer;
  border: 1px solid var(--rule); background: #fff; color: var(--ink);
  padding: 4px 14px; border-radius: 999px;
  transition: background .15s ease, color .15s ease, border-color .15s ease;
}
.filters button:hover { border-color: var(--red); color: var(--red); }
.filters button.active {
  background: var(--red); border-color: var(--red); color: #fff;
}
section { margin-top: 26px; }
h2.section-title {
  font-size: 20px; margin: 0 0 4px; padding-bottom: 6px;
  border-bottom: 2px solid var(--ink); letter-spacing: 2px;
}
h2.section-title .count { font-size: 13px; color: var(--ink-soft); font-weight: 400; margin-left: 8px; }
.article {
  border-bottom: 1px solid var(--rule); padding: 14px 2px;
}
.article:last-child { border-bottom: none; }
.article h3 {
  margin: 0 0 4px; font-size: 17px; line-height: 1.4; word-break: break-word;
}
.new-badge {
  display: inline-block; background: var(--red); color: #fff;
  font-size: 11px; font-weight: 700; border-radius: 3px;
  padding: 0 6px; margin-left: 6px; vertical-align: 2px;
}
.date-line { font-size: 13px; color: var(--red-deep); font-weight: 600; }
.date-line.uncertain { color: #8a6d00; }
.summary { margin: 6px 0 0; font-size: 14.5px; }
details.conditions { margin-top: 6px; font-size: 13.5px; }
details.conditions summary {
  cursor: pointer; color: var(--red); list-style: none; user-select: none;
}
details.conditions summary::before { content: "▸ "; }
details.conditions[open] summary::before { content: "▾ "; }
details.conditions ul { margin: 6px 0 0; padding-left: 20px; color: var(--ink-soft); }
.empty-note, .error-note, .unknown-note {
  font-size: 14px; padding: 8px 12px; margin: 8px 0;
}
.empty-note { color: var(--ink-soft); }
.error-note { background: #fbe7e4; border-left: 3px solid var(--red); color: var(--red-deep); }
.unknown-note { background: #fdf3d7; border-left: 3px solid var(--yellow); color: #7a5c00; }
ul.simple { padding-left: 20px; margin: 8px 0; }
.personal h2.section-title { border-bottom-color: var(--red); }
footer {
  margin-top: 34px; border-top: 3px double var(--ink); padding-top: 12px;
  font-size: 12px; color: var(--ink-soft); text-align: center;
}
footer a { color: var(--red); }
@media (max-width: 640px) {
  .page { margin: 0; padding: 22px 16px; border: none; }
  .masthead .brand { font-size: 32px; letter-spacing: 3px; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""

_JS = """
(function () {
  var buttons = document.querySelectorAll('.filters button[data-filter]');
  function apply(filter) {
    document.querySelectorAll('[data-category]').forEach(function (el) {
      el.style.display = (filter === 'all' || el.getAttribute('data-category') === filter)
        ? '' : 'none';
    });
    buttons.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-filter') === filter);
    });
  }
  buttons.forEach(function (b) {
    b.addEventListener('click', function () { apply(b.getAttribute('data-filter')); });
  });
})();
"""


def _e(text: object) -> str:
    return _html.escape(str(text), quote=True)


def _mode_badge(mode: str) -> str:
    if mode == "demo":
        return '<span class="badge mode-demo">DEMO · 虚构演示数据</span>'
    return '<span class="badge mode-live">LIVE · 真实查询</span>'


def _campaign_html(view) -> str:
    c = view.campaign
    new = '<span class="new-badge">新</span>' if view.is_new else ""
    uncertain_cls = " uncertain" if view.category == "unverified" else ""
    parts = [
        f'<article class="article" data-category="{_e(view.category)}">',
        f"<h3>{_e(c.title)}{new}</h3>",
        f'<div class="date-line{uncertain_cls}">{_e(view.date_text)}</div>',
    ]
    if c.summary:
        parts.append(f'<p class="summary">{_e(c.summary)}</p>')
    if c.conditions:
        items = "".join(f"<li>{_e(x)}</li>" for x in c.conditions)
        parts.append(
            f'<details class="conditions"><summary>使用条件（{len(c.conditions)} 条）</summary>'
            f"<ul>{items}</ul></details>")
    parts.append("</article>")
    return "\n".join(parts)


def _sections_html(sections: dict, calendar_status: str = "ok") -> tuple[str, str]:
    """返回 (正文 HTML, 目录锚点 HTML)。

    日历失败/未知时显示“未能核实”，不得给出看似确认的“暂无活动”。
    """
    failed_note = CALENDAR_STATUS_NOTES.get(calendar_status)
    body: list[str] = []
    toc: list[str] = []
    for cat in CATEGORY_ORDER:
        views = sections.get(cat, [])
        label = CATEGORY_LABELS[cat]
        toc.append(f'<a href="#sec-{cat}">{_e(label)} {len(views)}</a>')
        body.append(
            f'<section id="sec-{cat}"><h2 class="section-title">{_e(label)}'
            f'<span class="count">{len(views)} 项</span></h2>')
        if failed_note:
            cls = "error-note" if calendar_status == "error" else "unknown-note"
            body.append(f'<p class="{cls}">{_e(failed_note)}。</p>')
        elif not views:
            body.append('<p class="empty-note">暂无。</p>')
        for v in views:
            body.append(_campaign_html(v))
        body.append("</section>")
    return "\n".join(body), "\n".join(toc)


def _available_html(avail) -> str:
    parts = ['<section id="sec-available"><h2 class="section-title">可领券</h2>']
    if avail is None:
        parts.append('<p class="empty-note">未查询。</p>')
    elif avail.status == STATUS_OK:
        items = "".join(
            f"<li>{_e(c.name)}" + (f"（{_e(c.label)}）" if c.label else "") + "</li>"
            for c in avail.data)
        parts.append(f'<ul class="simple">{items}</ul>')
    elif avail.status == STATUS_EMPTY:
        parts.append(f'<p class="empty-note">{_e(avail.message or "当前暂无可领取的券。")}</p>')
    elif avail.status == "unknown":
        parts.append(f'<p class="unknown-note">{_e(avail.message or "结构待核实。")}</p>')
    else:
        parts.append(f'<p class="error-note">{_e(avail.message or "查询失败。")}</p>')
    parts.append("</section>")
    return "\n".join(parts)


def _personal_html(report: Report) -> str:
    parts: list[str] = []
    toc: list[str] = []

    toc.append('<a href="#sec-my-coupons">我的券</a>')
    parts.append('<section id="sec-my-coupons" class="personal">'
                 '<h2 class="section-title">我的券（仅私人版）</h2>')
    mine = report.my_coupons
    if mine is None:
        parts.append('<p class="empty-note">未查询。</p>')
    elif mine.status == STATUS_OK and isinstance(mine.data, dict):
        coupons = mine.data["coupons"]
        if coupons:
            items = []
            for c in coupons:
                date_text = c.datetime_text or (
                    f"{c.start} 至 {c.end}" if c.start or c.end else "有效期以券面为准")
                discount = f"（{_e(c.discount_desc)}）" if c.discount_desc else ""
                items.append(f"<li><strong>{_e(c.title)}</strong>{discount}"
                             f"<br><small>{_e(date_text)}</small></li>")
            parts.append(f'<ul class="simple">{"".join(items)}</ul>')
        else:
            parts.append('<p class="empty-note">卡包为空。</p>')
        if mine.message:
            parts.append(f'<p class="unknown-note">{_e(mine.message)}</p>')
        if report.pagination_note:
            parts.append(f'<p class="empty-note">分页范围：{_e(report.pagination_note)}</p>')
    elif mine.status == STATUS_EMPTY:
        parts.append('<p class="empty-note">卡包为空。</p>')
    else:
        parts.append(f'<p class="error-note">{_e(mine.message or "查询失败。")}</p>')
    parts.append("</section>")

    toc.append('<a href="#sec-points">积分提醒</a>')
    parts.append('<section id="sec-points" class="personal">'
                 '<h2 class="section-title">积分到期提醒（仅私人版）</h2>')
    items = "".join(f"<li>{_e(line)}</li>"
                    for line in points_note(report.points, report.points_status,
                                            report.date))
    parts.append(f'<ul class="simple">{items}</ul>')
    parts.append("</section>")
    return "\n".join(parts), "\n".join(toc)


def _anomalies_html(anomalies: list[str]) -> str:
    if not anomalies:
        return ""
    items = "".join(f"<li>{_e(a)}</li>" for a in anomalies)
    return ('<section id="sec-anomalies"><h2 class="section-title">数据异常</h2>'
            f'<ul class="simple">{items}</ul></section>')


def _guide_html() -> str:
    """通用领券指引：仅保留官方 App / 小程序路径。

    本地 Python 命令属开发者操作，写在 README，避免出现在面向读者的页面里。
    """
    return (
        '<section id="sec-guide"><h2 class="section-title">领取指引</h2>'
        '<ul class="simple">'
        "<li>打开麦当劳 App / 小程序，进入「麦麦省」或「优惠券」页面领取。</li>"
        "<li>部分活动需在 App 内点击「立即参与」或到店核销，以官方页面为准。</li>"
        "</ul></section>")


def _page(title_suffix: str, scope_badge: str, head_meta: str,
          body_html: str, toc_html: str, anomalies_html: str,
          show_filters: bool, show_available_nav: bool = True) -> str:
    filters = ""
    if show_filters:
        filters = (
            '<div class="filters" role="group" aria-label="活动筛选">'
            '<button data-filter="all" class="active">全部</button>'
            '<button data-filter="ongoing">今日进行中</button>'
            '<button data-filter="ending_soon">即将结束</button>'
            '<button data-filter="upcoming">即将开始</button>'
            '<button data-filter="unverified">日期待核实</button>'
            "</div>")
    available_nav = '<a href="#sec-available">可领券</a>' if show_available_nav else ''
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦门情报站 · {title_suffix}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    <h1 class="brand">麦门情报站<span class="dot">·</span></h1>
    <div class="meta">{head_meta}</div>
    <p class="disclaimer">本页面由开源工具「麦门情报站」生成，<strong>非麦当劳官方产品</strong>；活动、价格与供应状态以麦当劳官方渠道的实时结果为准。</p>
  </header>
  <nav class="toc">{toc_html}{available_nav}{'<a href="#sec-anomalies">数据异常</a>' if anomalies_html else ''}<a href="#sec-guide">领取指引</a></nav>
  {filters}
  {body_html}
  {anomalies_html}
  {_guide_html()}
  <footer>
    <p>非麦当劳官方产品 · 仅供个人参考 · 源码：<a href="{_REPO_URL}">{_REPO_URL}</a></p>
  </footer>
</div>
<script>{_JS}</script>
</body>
</html>
"""


def render_private_html(report: Report) -> str:
    body, toc = _sections_html(report.sections, report.calendar_status)
    personal, personal_toc = _personal_html(report)
    body += "\n" + _available_html(report.available_coupons) + "\n" + personal
    # 「可领券」锚点由 _page 的 available_nav 统一注入，避免重复。
    toc += "\n" + personal_toc
    anomalies = _anomalies_html(report.anomalies)
    head_meta = (f'{_e(report.date.strftime("%Y 年 %m 月 %d 日"))} · '
                 f'{_mode_badge(report.mode)} '
                 f'<span class="badge scope">私人版</span><br>'
                 f'数据来源：{_e(report.source)} · 生成于 {_e(report.generated_at)}')
    return _page(f'{report.date} 私人简报', "私人版", head_meta,
                 body, toc, anomalies, show_filters=True)


def render_public_html(public: PublicReport) -> str:
    """公开版：只有公共活动与通用领券指引，不含任何个人数据与可领券状态。"""
    body, toc = _sections_html(public.sections, public.calendar_status)
    anomalies = _anomalies_html(public.anomalies)
    head_meta = (f'{_e(public.date.strftime("%Y 年 %m 月 %d 日"))} · '
                 f'{_mode_badge(public.mode)} '
                 f'<span class="badge scope">公开版</span><br>'
                 f'数据来源：{_e(public.source)} · 生成于 {_e(public.generated_at)}')
    return _page(f'{public.date} 公开简报', "公开版", head_meta,
                 body, toc, anomalies, show_filters=True,
                 show_available_nav=False)

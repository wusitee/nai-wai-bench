"""Token bill page: total tokens for running and building the benchmark, usage by model and reasoning
effort, and contributor credits. The overview page embeds the headline panel."""

import re
from html import escape as e
from pathlib import Path

from nwb.bill import BUCKETS
from nwb.config import ModelSpec
from nwb.contributions import UNCOMMITTED
from nwb.site import BILL_NAME, FRONTEND_NAME, SUITE_TEXT, _footer, _head, _header, _suite_href

CSS = """
.bill-chip{display:inline-flex;gap:7px;font:10.5px var(--mono);text-transform:uppercase;letter-spacing:.1em;color:var(--ink2);
border:1px solid var(--line);background:var(--card);border-radius:4px;padding:3px 9px;text-decoration:none;white-space:nowrap}
.bill-chip b{color:var(--yellow)}.bill-chip:hover{border-color:rgba(250,204,21,.3)}
.bill-big{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.bill-big strong{font:800 64px/1 var(--sans);letter-spacing:-.04em}
.bill-big span{font:12px var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.bill-split,.bill-types{display:flex;gap:2px}.bill-split{height:26px;margin:18px 0 8px}.bill-types{height:10px;margin:18px 0 10px}
.bill-split i,.bill-types i{display:block;height:100%;border-radius:3px;min-width:3px}
.bill-split-labels{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 12px;font:12px var(--mono);color:var(--muted)}
.bill-split-labels b,.bill-legend b{color:var(--fg);font-weight:600}
.bill-legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:6px 22px;font:12px var(--mono);color:var(--muted)}
.bill-legend div{display:flex;align-items:center;gap:8px;white-space:nowrap}.bill-legend b{margin-left:auto}
.sw{display:inline-block;width:9px;height:9px;border-radius:2px;flex:none}
.b-build{background:#8b8b94}.b-run{background:var(--yellow)}
.b-input{background:var(--ink2)}.b-cache_read{background:#71717a}.b-cache_write{background:var(--orange)}.b-output{background:var(--blue)}
.bill-rows td{vertical-align:middle}.bill-rows td.m{width:32%}.bill-rows .track{display:block;min-width:60px}
.bill-rows .fill{background:#8b8b94;box-shadow:none}.bill-rows.run .fill{background:var(--yellow)}
.ladders{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:14px;margin:14px 0}
.ladders .panel{padding:14px 18px}.ladders td{padding:6px 4px;vertical-align:middle;border:0}
.ladders td:first-child{width:1%;padding-left:0}.ladders .track{display:block;min-width:60px}
.ladders .fill{background:var(--blue);box-shadow:none}.ladders td.n:last-child{color:var(--muted);width:1%}
.usage td.n{white-space:nowrap}.usage td:first-child{min-width:170px}
.credits td{vertical-align:middle}.credits .names{color:var(--muted);font-size:12.5px;line-height:1.5}
"""

ROLE = {"understanding": ("回答", "answers"), "judge": ("评审", "judging"), "imagegen": ("生图", "image generation"),
        "frontend": ("页面", "pages")}
BUCKET = {"input": ("输入", "Input"), "cache_read": ("缓存读取", "Cache read"),
          "cache_write": ("缓存写入", "Cache write"), "output": ("输出", "Output")}
UNIT = {"understanding": ("回答", "answer"), "frontend": ("页面", "page")}
TITLE = f"Token {BILL_NAME[0]} <span class=en>Token bill</span>"


def tok(n: float | None) -> str:
    """Compact token count."""
    if n is None:
        return "—"
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= size:
            return f"{n / size:.{2 if size == 1e9 else 1}f}{suffix}"
    return f"{n:,.0f}"


def _usd(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _meter(value: float, top: float) -> str:
    width = 100 * value / top if top else 0
    return f"<span class=track><span class=fill style='width:{width:.1f}%'></span></span>"


def _effort(effort: str) -> str:
    return f"<span class=status>{e(effort)}</span>"


def _labels(models: dict[str, ModelSpec]):
    """Display names by registry entry and by provider model id, without a reasoning-effort suffix:
    effort has its own column here."""
    plain = lambda label: re.sub(r" \((?:none|minimal|low|medium|high|xhigh|max|ultra)\)$", "", label)
    by_id = {}
    for spec in models.values():
        by_id.setdefault(spec.model, plain(spec.label))
    return (lambda name: plain(models[name].label) if name in models else name), lambda model: by_id.get(model, model)


def chip(summary: dict, href: str) -> str:
    return (f"<a class=bill-chip href='{e(href, quote=True)}'><b>{tok(summary['total'])}</b> tokens 烧掉了 · burned</a>")


def headline(summary: dict) -> str:
    """The total with its running/building split and token-type composition."""
    agents = summary["agents"]
    run = sum(summary["tokens"].values())
    build = sum(agents["tokens"].values()) if agents else 0
    total = summary["total"]
    counts = f"{summary['calls']:,} 次模型调用 model calls"
    if agents:
        counts += f" · {agents['sessions']:,} 个 agent 会话 agent sessions"
    out = [f"<div class=panel><div class=bill-big><strong>{tok(total)}</strong><span>tokens · {counts}</span></div>"]
    if agents and total:
        share = lambda n: f"{100 * n / total:.1f}%"
        out.append(
            f"<div class=bill-split role=img aria-label='Building {share(build)}, running {share(run)}'>"
            f"<i class=b-build style='flex:{build}' title='Building it: {build:,} tokens'></i>"
            f"<i class=b-run style='flex:{run}' title='Running it: {run:,} tokens'></i></div>"
            "<div class=bill-split-labels>"
            f"<span><span class='sw b-build'></span> 造 bench Building it <b>{tok(build)}</b> · {share(build)}</span>"
            f"<span><b>{tok(run)}</b> · {share(run)} 跑 bench Running it <span class='sw b-run'></span></span></div>")
    types = {k: summary["tokens"][k] + (agents["tokens"][k] if agents else 0) for k in BUCKETS}
    if total:
        out.append("<div class=bill-types role=img aria-label='Token types'>" + "".join(
            f"<i class=b-{k} style='flex:{types[k]}' title='{BUCKET[k][1]}: {types[k]:,} tokens'></i>"
            for k in BUCKETS if types[k]) + "</div>")
    out.append("<div class=bill-legend>" + "".join(
        f"<div><span class='sw b-{k}'></span>{BUCKET[k][0]} {BUCKET[k][1]}<b>{tok(types[k])}</b></div>"
        for k in BUCKETS) + "</div></div>")
    return "".join(out)


def credit_names(board: dict) -> list[str]:
    return [row["contributor"] for row in board["contributors"] if row["contributor"] != UNCOMMITTED]


def _running(summary: dict) -> str:
    names = {**{s: text["name"] for s, text in SUITE_TEXT.items()}, "frontend": FRONTEND_NAME}
    top = max((t["tokens"] for t in summary["tracks"]), default=0)
    rows = []
    for t in summary["tracks"]:
        suite, role = names.get(t["suite"], (t["suite"], t["suite"])), ROLE.get(t["role"], (t["role"], t["role"]))
        missing = f" · {t['no_usage_calls']:,} 次无用量 without usage" if t["no_usage_calls"] else ""
        rows.append(f"<tr><td>{e(suite[0])} {e(suite[1])} · {e(role[0])} <span class=en>{e(role[1])}</span>"
                    f"<div class=row-meta>{t['calls']:,} 次调用 calls{missing}</div></td>"
                    f"<td class=m>{_meter(t['tokens'], top)}</td><td class=n>{tok(t['tokens'])}</td></tr>")
    return ("<div class=panel><h3>跑 bench <span class=en>Running it</span></h3>"
            f"<p class=muted>{tok(sum(summary['tokens'].values()))} · 所有已保存的回答、评审、生图与页面调用"
            "<span class=en> · every saved answer, judgment, image, and page call</span></p>"
            "<table class='bill-rows run'>" + "".join(rows) + "</table></div>")


def _building(agents: dict, agent_label) -> str:
    total = lambda row: sum(row["tokens"][k] for k in BUCKETS)
    top = max((total(r) for r in agents["models"]), default=0)
    rows = "".join(
        f"<tr><td>{e(agent_label(r['model']))}<div class=row-meta>{r.get('requests', 0):,} 次请求 requests</div></td>"
        f"<td class=m>{_meter(total(r), top)}</td><td class=n>{tok(total(r))}</td></tr>" for r in agents["models"])
    return ("<div class=panel><h3>造 bench <span class=en>Building it</span></h3>"
            f"<p class=muted>{tok(sum(agents['tokens'].values()))} · 写代码、审代码的 AI 编程助手，"
            f"{e(agents['first_day'])} 至 {e(agents['last_day'])}<span class=en> · coding agents that wrote and "
            f"reviewed the bench, {e(agents['first_day'])} to {e(agents['last_day'])}</span></p>"
            "<table class=bill-rows>" + rows + "</table></div>")


def _ladders(summary: dict, agent_label) -> str:
    cards = []
    for ladder in summary["ladders"]:
        base = ladder["steps"][0]["mean_output"]
        top = max(s["mean_output"] for s in ladder["steps"])
        unit = UNIT[ladder["role"]]
        rows = "".join(
            f"<tr><td>{_effort(s['effort'])}</td><td>{_meter(s['mean_output'], top)}</td>"
            f"<td class=n>{s['mean_output']:,.0f}</td>"
            f"<td class=n>{'×' + format(s['mean_output'] / base, '.1f') if base else ''}</td></tr>"
            for s in ladder["steps"])
        role = ROLE[ladder["role"]]
        cards.append(f"<div class=panel><h3>{e(agent_label(ladder['model']))} <span class=en>· {role[0]} {role[1]}"
                     f"</span></h3><p class=muted>输出 token/{unit[0]} · {ladder['tasks']} 道共同题目<span class=en> · output "
                     f"tokens per {unit[1]} · {ladder['tasks']} shared tasks</span></p><table>{rows}</table></div>")
    return "<div class=ladders>" + "".join(cards) + "</div>"


def _usage(summary: dict, entry_label) -> str:
    groups: dict[str, int] = {}
    for row in summary["entries"]:
        groups[row["model"]] = groups.get(row["model"], 0) + sum(row["tokens"].values())
    out = ["<div class='scroll card-table'><table class=usage><tr><th>模型 Model</th><th>强度<br>Effort</th>"
           "<th class=n>调用<br>Calls</th><th class=n>合计<br>Total</th>"
           + "".join(f"<th class=n>{BUCKET[k][0]}<br>{BUCKET[k][1]}</th>" for k in BUCKETS)
           + "<th class=n>输出/回答<br>Output/answer</th><th class=n>输出/页面<br>Output/page</th>"
           "<th class=n>标价估值<br>List-price value</th></tr>"]
    for row in sorted(summary["entries"], key=lambda r: -groups[r["model"]]):  # stable: efforts stay ordered
        known = row["no_usage_calls"] < row["calls"]
        per = lambda role: (f"{row['roles'][role]['output'] / row['roles'][role]['usage_calls']:,.0f}"
                            if row["roles"].get(role, {}).get("usage_calls") else "—")
        roles = " · ".join(ROLE.get(r, (r, r))[1] for r in row["roles"])
        missing = f" · {row['no_usage_calls']} without usage" if row["no_usage_calls"] and known else ""
        out.append(
            f"<tr><td><b>{e(entry_label(row['entry']))}</b><div class=row-meta><code>{e(row['entry'])}</code> · "
            f"{e(roles)}{missing}</div></td><td>{_effort(row['effort'])}</td><td class=n>{row['calls']:,}</td>"
            f"<td class=n>{tok(sum(row['tokens'].values())) if known else '—'}</td>"
            + "".join(f"<td class=n>{tok(row['tokens'][k]) if known else '—'}</td>" for k in BUCKETS)
            + f"<td class=n>{per('understanding')}</td><td class=n>{per('frontend')}</td>"
            f"<td class=n>{_usd(row['usd'])}</td></tr>")
    return "".join(out) + "</table></div>"


def _credits(board: dict, entry_label) -> str:
    top = max((row["usd"] or 0 for row in board["contributors"]), default=0)
    out = ["<div class='scroll card-table'><table class=credits><tr><th>#</th><th>贡献者 Contributor</th>"
           "<th>标价估值<br>List-price value</th><th class=n>调用<br>Calls</th><th class=n>Token</th>"
           "<th>模型 Models</th></tr>"]
    for row in board["contributors"]:
        tokens = sum(m["tokens"]["input"] + m["tokens"]["output"] for m in row["models"])
        names = " · ".join(dict.fromkeys(entry_label(m["model"]) for m in row["models"]))
        meter = (f"<div class=meter>{_meter(row['usd'], top)}<b>{_usd(row['usd'])}</b></div>"
                 if row["usd"] is not None else "—")
        out.append(f"<tr><td class=rank>{row['rank'] or '–'}</td><td><b>{e(row['contributor'])}</b></td><td>{meter}</td>"
                   f"<td class=n>{row['calls']:,}</td><td class=n>{tok(tokens)}</td>"
                   f"<td class=names>{e(names)}</td></tr>")
    return "".join(out) + "</table></div>"


def build(summary: dict, board: dict, models: dict[str, ModelSpec], out: Path, repo_url: str | None = None,
          blob: str | None = None) -> Path:
    entry_label, agent_label = _labels(models)
    agents = summary["agents"]
    links = ("<a href='#where'>去向 Breakdown</a><a href='#effort'>强度 Effort</a><a href='#models'>模型 Models</a>"
             "<a href='#credits'>贡献者 Credits</a>")
    docs = (f"<a href='{e(blob, quote=True)}/docs/contributing-results.md'>贡献结果 Contributing results</a>"
            if blob else "docs/contributing-results.md")
    page = [
        _head(f"Token {BILL_NAME[0]} · Token bill · 奶蛙bench") + f"<style>{CSS}</style>",
        _header("bill", links, True),
        f"<div class='hero solo'><div><h1>{TITLE}</h1>"
        "<p class=lede>这个 bench 一共烧掉了多少 token：跑分本身"
        + ("，加上写代码、审代码的 AI 编程助手" if agents else "") + "。<br><span class=en>Every token that went "
        "into this bench: running it" + (", plus the coding agents that built and reviewed it" if agents else "")
        + ".</span></p></div></div>",
        headline(summary),
        "<p class=muted>跑分用量来自仓库里每一次已保存调用的记录，合并运行中重复的调用只算一次；没有报告用量的客户端"
        f"（{summary['no_usage_calls']:,} 次调用）不计入。"
        + ("开发用量是维护者本机 AI 编程助手日志的快照，无法从仓库重算。" if agents else "")
        + "缓存读取是重复送入的上下文，按次计入。<span class=en> Running usage is read from every saved call in the "
        "repository, counting a call repeated across merged runs once; clients that report no usage "
        f"({summary['no_usage_calls']:,} calls) are left out. "
        + ("Building usage is a snapshot of the maintainer's local coding-agent logs and cannot be rebuilt from "
           "the repository. " if agents else "")
        + "Cache reads are context sent again and count every time.</span></p>",
        "<h2 id=where>去向 <span class=en>Where it went</span></h2><div class=panels>" + _running(summary)
        + (_building(agents, agent_label) if agents else "") + "</div>"
        "<p class=muted>条形在各栏内按最大值缩放；生图调用的 token 只是图像工具外层的对话，不是生成图像的成本。"
        "<span class=en> Bars are scaled within each panel. Image-generation tokens cover the relay around the "
        "image tool, not image generation itself.</span></p>",
    ]
    if summary["ladders"]:
        page.append(
            "<h2 id=effort>推理强度 <span class=en>Reasoning effort</span></h2>"
            "<p>同一个模型换一档推理强度，每道题多用多少输出 token？只比较各档都答过的题目，每题先对重复取平均；"
            "倍数相对最低一档。<br><span class=en>How many more output tokens does a model spend per task at a "
            "higher reasoning effort? Only tasks answered at every listed effort are compared, averaging "
            "repetitions within a task first; multipliers are relative to the lowest effort.</span></p>"
            + _ladders(summary, agent_label))
    page += [
        "<h2 id=models>各模型用量 <span class=en>Usage by model and effort</span></h2>"
        "<p class=muted>每个模型配置（模型 × 推理强度）在所有已保存调用中的合计，包括作为评审的调用。输出含推理 token；"
        "输入含各客户端自带的系统提示。每题输出是该配置全部题目的平均，题目范围不同的行不能直接比较。估值按 "
        "<code>models.toml</code> 的 API 标价计算，订阅制 CLI 并不按 token 计费。<span class=en> Totals per model "
        "configuration (model × reasoning effort) over every saved call, including calls made as a judge. Output "
        "includes reasoning tokens; input includes each client's own system prompt. Output per task averages all "
        "of a configuration's tasks, so rows covering different tasks are not directly comparable. Values use the "
        "API list prices in <code>models.toml</code>; subscription CLIs are not billed per token.</span></p>"
        + _usage(summary, entry_label),
        "<h2 id=credits>贡献者 <span class=en>Contributors</span></h2>"
        "<p>感谢每一位贡献跑分结果的人。每次已保存的调用记在首次提交该记录的 Git 作者名下，按 API 标价估值排名。"
        "<br><span class=en>Thanks to everyone who contributed results. Each saved call is credited to the Git "
        "author who first committed its record, ranked by its value at API list prices.</span></p>"
        + _credits(board, entry_label)
        + f"<p class=muted>想加入？见{docs}。<span class=en> Want to add a model? See Contributing results. "
        "The value is an estimate at pay-as-you-go prices, not what anyone paid.</span></p>",
        _footer(repo_url, blob),
    ]
    target = out / "bill"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "index.html"
    path.write_text("\n".join(page), encoding="utf-8")
    return path


def index_section(summary: dict, board: dict) -> str:
    """Summary for the overview page, linking to the full bill."""
    href = _suite_href("index", "bill")
    names = credit_names(board)
    thanks = (f"感谢贡献结果的 {' · '.join(e(n) for n in names)}。<span class=en> Thanks to "
              f"{', '.join(e(n) for n in names)} for contributing results.</span> " if names else "")
    return (f"<h2 id=bill>{TITLE}</h2>" + headline(summary)
            + f"<p class=muted>{thanks}<a href='{href}'>完整账单与贡献者 Full bill and credits →</a></p>")

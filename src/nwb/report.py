"""Self-contained HTML report for a run (images are linked relative to the run directory)."""

import math
import re
from collections import defaultdict
from html import escape

from nwb import CANARY, __version__
from nwb.config import Bench

CSS = """
body{font:14px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:1200px;padding:0 1rem;color:#1f2328;background:#fff}
h1,h2,h3{line-height:1.25}table{border-collapse:collapse;margin:.5rem 0 1.5rem}
th,td{border:1px solid #d0d7de;padding:.3rem .55rem;text-align:right;vertical-align:top}
th:first-child,td:first-child{text-align:left}th{background:#f6f8fa}
.gallery td{text-align:center;width:180px}.gallery img{width:170px;border-radius:6px;display:block;margin:auto}
.muted{color:#656d76;font-size:12px}.bad{color:#cf222e}.ans{white-space:pre-wrap;text-align:left;font-size:13px}
details{margin:.4rem 0}summary{cursor:pointer;font-weight:600}
.scroll{overflow-x:auto}
@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}th{background:#161b22}
th,td{border-color:#30363d}.muted{color:#8d96a0}}
"""


def fmt(x, digits=0) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def score_text(row: dict) -> str:
    value = fmt(row["score"], 1)
    if row.get("score_interval"):
        lo, hi = row["score_interval"]
        value += f" [{lo:.1f}–{hi:.1f}]"
    return value


def rank_range(row: dict) -> str:
    if not row.get("rank_range"):
        return "–"
    lo, hi = row["rank_range"]
    return str(lo) if lo == hi else f"{lo}–{hi}"


def row_details(row: dict) -> str:
    details = [row["status"]] if row["status"] != "complete" else []
    if row.get("settings_status") == "settings unrecorded":
        details.append("settings unrecorded")
    details += row.get("conditions", [])
    if row["status"] == "mixed conditions":
        details.append("diagnostic score " + fmt(row.get("diagnostic_score"), 1))
    return "; ".join(details)


def judge_text(row: dict, label=lambda m: m) -> str:
    return " · ".join(f"{label(j)} ×{n}" for j, n in row.get("judges", {}).items()) or "none"


def model_html(label: str) -> str:
    """Keep a recorded reasoning-effort suffix visually secondary."""
    match = re.search(r" \((?:none|minimal|low|medium|high|xhigh|max|ultra)\)$", label)
    if match:
        return escape(label[:match.start()]) + f"<span class=muted>{escape(match.group())}</span>"
    return escape(label)


def leaderboard_table(rows: list[dict], label=lambda m: m) -> str:
    out = ["<table><tr><th>Rank</th><th>Model</th><th>Score [95% interval]</th><th>Rank range</th><th>Scored cells</th>"
           "<th>Repetitions/cell</th><th>Status</th><th>Contributing judges (samples)</th></tr>"]
    for row in rows:
        rank = row["rank"] if row["rank"] is not None else "–"
        out.append(f"<tr><td>{rank}</td><td>{escape(label(row['model']))}</td>"
                   f"<td><b>{score_text(row)}</b></td><td>{rank_range(row)}</td><td>{row['completed']}/{row['required']}</td>"
                   f"<td>{row['repetitions']}</td><td>{escape(row_details(row))}</td>"
                   f"<td>{escape(judge_text(row))}</td></tr>")
    return "\n".join(out) + "</table>"


UNCERTAINTY_NOTE = ("95% percentile intervals and rank ranges use 2,000 paired cluster-bootstrap draws (seed 6643): "
                    "source images for understanding, animals with all tiers for generation. Repetitions are averaged "
                    "within each cell before resampling. They describe sensitivity to sampling these items/animals "
                    "with the observed repetitions and fixed judges, not a significance test or population claim. "
                    "Few clusters make intervals wide or unstable; they do not measure judge or label uncertainty.")


def collection_text(scores: dict) -> str:
    c = scores.get("collection", {})
    start, end = c.get("started_at"), c.get("finished_at")
    if start and end:  # e.g. "2026-10-25 00:45 – 01:17 UTC"; the end date is repeated only when it differs
        s, f = start.replace("T", " ")[:16], end.replace("T", " ")[:16]
        dates = f"{s} – {f[11:] if f[:10] == s[:10] else f} UTC"
    else:
        dates = "dates unrecorded"
    return f"nai-wai-bench {scores.get('nwb_version', __version__)} · {scores.get('suite', 'core')} · collected {dates}"


def stale_text(scores: dict) -> str:
    """'Stale judgments ignored: 9 (prompt: 8, target: 1). ' or '' when none were ignored."""
    stale = scores.get("stale_judgments", {})
    if not stale.get("total"):
        return ""
    reasons = ", ".join(f"{k}: {v}" for k, v in sorted(stale.get("reasons", {}).items()))
    return f"Stale judgments ignored: {stale['total']}{f' ({reasons})' if reasons else ''}. "


def _cost(value: float | None) -> str:
    if value is None:
        return "—"
    if 0 < value < .0001:
        return "&lt;$0.0001"
    rounded = float(f"{value:.4g}")
    decimals = max(0, 3 - math.floor(math.log10(rounded))) if rounded else 4
    text = f"${rounded:,.{decimals}f}"
    return text.rstrip("0") if decimals > 4 else text


def efficiency_section(scores: dict, label=lambda m: m) -> str:
    efficiency = scores.get("efficiency", {})
    rows = efficiency.get("visual_understanding", {})
    board = scores.get("leaderboards", {}).get("visual_understanding", [])
    out = ["<h2 id=efficiency>效率 <span class=en>Efficiency</span></h2>"
           '<p>每个模型在排名题组上平均每题用多少 token，以及按官方 API 标价估算的费用。输出 token（含推理）最适合横向比较；'
           '输入 token 包含各客户端自带的系统提示，所以输入量和费用反映的是"通过该客户端运行"的成本。'
           '订阅制 CLI 并不按 token 计费；没有报告用量的客户端显示为"—"。<br><span class=en>'
           "Average tokens per ranked task, and an estimate at each vendor's list API price. Output tokens "
           "(including reasoning) are the most comparable figure; input tokens include each client's own system "
           "prompt, so input and cost describe running the task through that client. Subscription CLIs are not "
           'billed per token; clients that do not report usage show "—".</span></p>'
           "<div class=scroll><table class=efficiency><tr><th>模型 Model</th><th class=n>得分 Score</th>"
           "<th class=n>输出 token/题<br>Output tokens/task</th><th class=n>输入 token/题<br>Input tokens/task</th>"
           "<th class=n>估算费用/题<br>Est. cost/task</th><th class=n>整组估算<br>Est. panel cost</th>"
           "<th class=n>客户端用时/题<br>Client time/task</th><th class=n>用量覆盖<br>Usage coverage</th></tr>"]
    for ranked in board:
        model = ranked["model"]
        r = rows.get(model, {})
        price = r.get("price") or {}
        price_note = f"{price.get('source', '')}; as of {price.get('as_of', 'unrecorded')}" if price else "Price unavailable"
        numbers = ["—" if r.get(k) is None else f"{r[k]:,.0f}" for k in ("mean_output_tokens", "mean_input_tokens")]
        out.append(f"<tr><td>{model_html(label(model))}</td><td class=n>{fmt(ranked['score'], 1) if ranked['score'] is not None else '—'}</td>"
                   + "".join(f"<td class=n>{n}</td>" for n in numbers)
                   + "".join(f"<td class=n title='{escape(price_note, quote=True)}'>{_cost(r.get(k))}</td>"
                             for k in ("mean_cost_usd", "estimated_cost_usd"))
                   + f"<td class=n>{format(r['median_seconds'], ',.1f') + ' s' if r.get('median_seconds') is not None else '—'}</td>"
                   f"<td class=n>{r.get('token_tasks', 0)}/{r.get('tasks', 0)}</td></tr>")
    out.append("</table></div>")
    points = [(r["model"], rows.get(r["model"], {}).get("mean_output_tokens"), r["score"]) for r in board]
    missing = [m for m, x, _ in points if x is None]
    points = [(m, x, y) for m, x, y in points if x is not None and y is not None]
    if points:
        positive = [x for _, x, _ in points if x > 0]
        logarithmic = bool(positive) and max(positive) / min(positive) >= 10
        transform = (lambda x: math.log10(x if x > 0 else min(positive) / 3)) if logarithmic else lambda x: x
        low, high = min(transform(x) for _, x, _ in points), max(transform(x) for _, x, _ in points)
        padding = (high - low) * .08 if high > low else .5
        low, high = low - padding, high + padding
        xpos = lambda x: 70 + 520 * (transform(x) - low) / (high - low)
        out.append("<svg class=efficiency-chart viewBox='0 0 640 360' style='width:100%;max-width:680px;height:auto' role=img "
                   "aria-label='得分 Score / 每题输出 token Output tokens per task'>")
        for y in (0, 25, 50, 75, 100):
            yy = 280 - 2.4*y
            out.append(f"<path d='M70 {yy}H590' stroke='var(--line,#d0d7de)'/>"
                       f"<text x=60 y='{yy + 5}' text-anchor=end fill=currentColor font-size=13>{y}</text>")
        if logarithmic:
            ticks = [v * 10**power for power in range(math.floor(low), math.ceil(high) + 1) for v in (1, 3)
                     if low <= math.log10(v * 10**power) <= high]
            if any(x == 0 for _, x, _ in points):
                ticks.insert(0, 0)
        else:
            step = 10 ** math.floor(math.log10((high - low) / 4))
            step *= next(v for v in (1, 2, 5, 10) if step * v >= (high - low) / 4)
            ticks = [i * step for i in range(max(0, math.ceil(low / step)), math.floor(high / step) + 1)]
        for x in ticks:
            xx = xpos(x)
            text = f"{x / 1000:g}k" if x >= 1000 else f"{x:g}"
            out.append(f"<path d='M{xx:.1f} 40V280' stroke='var(--line,#d0d7de)'/>"
                       f"<text x='{xx:.1f}' y=302 text-anchor=middle font-size=13 fill=currentColor>{text}</text>")
        labels = []
        for m, x, y in points:
            xx, yy = xpos(x), 280 - 2.4*y
            short = label(m).split(" (")[0]
            anchor = "end" if xx > 400 else "start"
            tx = xx - 7 if anchor == "end" else xx + 7
            left = tx - len(short) * 7 if anchor == "end" else tx
            ty = yy - 9
            for candidate in [ty] + [ty + sign * offset for offset in range(16, 260, 16) for sign in (1, -1)]:
                if 20 <= candidate <= 270 and not any(
                        abs(candidate - ly) < 16 and left < lx + lw and lx < left + len(short) * 7
                        for lx, ly, lw in labels):
                    ty = candidate
                    break
            labels.append((left, ty, len(short) * 7))
            out.append(f"<circle cx='{xx:.1f}' cy='{yy:.1f}' r=4 fill='var(--bar,#c98500)'><title>"
                       f"{escape(label(m))}: {x:,.0f} tokens, {y:.1f} score</title></circle>"
                       f"<text x='{tx:.1f}' y='{ty:.1f}' text-anchor='{anchor}' font-size=13 fill=currentColor>{escape(short)}</text>")
        out.append("<text x=330 y=330 text-anchor=middle fill=currentColor font-size=13>每题输出 token Output tokens per task</text>"
                   + ("<text x=330 y=351 text-anchor=middle fill=currentColor font-size=12>对数刻度 · log scale</text>" if logarithmic else "")
                   + "<text x=17 y=160 transform='rotate(-90 17 160)' text-anchor=middle fill=currentColor font-size=13>"
                   "得分 Score</text></svg>")
    else:
        out.append("<p class=muted>No ranked models have output-token telemetry for this panel.</p>")
    if missing:
        out.append("<p class=muted>无用量数据 No usage data: " + " · ".join(escape(label(m)) for m in missing) + "</p>")
    images = efficiency.get("imagegen", {})
    if any(r["tasks"] for r in images.values()):
        out.append("<h3>Image generation</h3><table><tr><th>Model</th><th>Images</th><th>Median client seconds/task</th></tr>")
        for m, r in images.items():
            if r["tasks"]:
                out.append(f"<tr><td>{escape(label(m))}</td><td>{r['images']}</td><td>{fmt(r['median_seconds'], 1)}</td></tr>")
        out.append("</table>")
    out.append("<p class=muted>Visual metrics cover retained tasks in the fixed visual panel, including failures with reported usage; "
               "token means use reported fields only. Panel cost requires complete repetition coverage, usage and prices for every panel task. "
               "Seconds are end-to-end client time, not model speed. Image relay tokens are not generator cost. "
               "Whole-run subject totals and separate judge totals (cost to evaluate) are in scores.json.</p>")
    return "\n".join(out)

def objective_tables(summary: dict, label=lambda m: m) -> str:
    rows = {m: s for m, s in summary.items() if s.get("fields")}
    if not any(s.get("family_classes") for s in rows.values()):
        return ""
    fields = list(dict.fromkeys(f for s in rows.values() for f in s["fields"]))
    out = ["<h3>Answer-key diagnostics</h3><div class=scroll><table><tr><th>Model</th>"
           "<th>Family macro</th><th>Family labels</th><th>Visual joint</th><th>All-field joint</th><th>Repetition consistency (images)</th>"
           + "".join(f"<th>{escape(f)} (items)</th>" for f in fields) + "</tr>"]
    for model, s in rows.items():
        out.append(f"<tr><td>{escape(label(model))}</td><td>{fmt(s['family_macro'], 1)}</td>"
                   f"<td>{len(s['family_classes'])}</td><td>{fmt(s['visual_joint'], 1)}</td>"
                   f"<td>{fmt(s['joint'], 1)}</td><td>{fmt(s.get('repetition_consistency'), 1)} ({s.get('repetition_consistency_images', 0)})</td>"
                   + "".join(f"<td>{fmt(s['fields'].get(f), 1)} ({s['field_items'].get(f, 0)})</td>"
                             for f in fields) + "</tr>")
    out.append("</table></div><p class=muted>Scores are 0–100; item means balance repetitions. "
               "Family macro gives equal weight to observed expected family labels; check label and item coverage. "
               "Visual joint requires every non-family field to be correct; all-field joint also requires family. "
               "Field means give partial credit, while joint accuracies require complete answers.</p>")
    categories = sorted({c for s in rows.values() for c in s.get("categories", {})})
    if categories:
        out.append("<div class=scroll><table><tr><th>Model</th>"
                   + "".join(f"<th>{escape(c)}</th>" for c in categories) + "</tr>")
        for model, s in rows.items():
            out.append(f"<tr><td>{escape(label(model))}</td>"
                       + "".join(f"<td>{fmt(s['categories'].get(c), 1)}</td>" for c in categories) + "</tr>")
        out.append("</table></div>")
    return "\n".join(out)


RANKING_NOTE = ("Two independent, provisional rankings; no combined score. Only complete fixed panels with the "
                "same attempted repetition ids scored in every cell receive ranks. Image generation requires verified verbatim "
                "prompts. Missing, failed, unjudged, or ineligible cells leave a model unranked. Text/language "
                "answers and no-image controls are diagnostics. Small score gaps do not establish a reliable ordering.")


def render(bench: Bench, run_name: str, scores: dict) -> str:
    label = lambda m: scores.get("labels", {}).get(m, m)
    out = [f"<!doctype html><!-- {CANARY} --><meta charset=utf-8><title>奶蛙bench · nai-wai-bench · {escape(run_name)}</title>",
           f"<style>{CSS}</style><h1>奶蛙bench · nai-wai-bench · {escape(run_name)}</h1>",
           f"<p class=muted>Suite: {escape(bench.suite)}. Judges: {escape(', '.join(scores['judges']) or 'none')}. "
           "Scores are 0–100; LLM-graded samples are averaged over judges from other vendors than the model "
           "(all judges if none are independent).</p>"]
    out.append(f"<p class=muted>{escape(collection_text(scores))}. Collection revisions: "
               f"{escape(', '.join(scores.get('collection', {}).get('revisions', [])) or 'unrecorded')}. "
               f"{escape(stale_text(scores))}</p>")
    boards = scores.get("leaderboards", {})
    if bench.suite == "naihub-v1":
        out.append("<p>naihub-v1 visual ranks use all-field joint accuracy: every keyed field must be correct "
                   "for a sample to earn 100. Family macro and partial-credit field means are separate diagnostics.</p>")
    if bench.annotator:
        out.append(f"<p>Answer keys are provisional {escape(bench.annotator)} annotations; that model's score "
                   "measures agreement with its own labels.</p>")
    out += [f"<p class=muted>{RANKING_NOTE}</p>", "<h2>Image generation ranking</h2>",
            leaderboard_table(boards.get("imagegen", []), label), "<h2>Visual understanding ranking</h2>",
            leaderboard_table(boards.get("visual_understanding", []), label)]
    out += [f"<p class=muted>{UNCERTAINTY_NOTE}</p>", efficiency_section(scores, label)]
    out += _imagegen(bench, scores)
    out += _understanding(bench, scores)
    out += _understanding(bench, scores, states=True)
    out += _judge_health(scores)
    return "\n".join(out)


LOW_SPREAD, HIGH_DEVIATION = 5, 25


def _judge_health(scores: dict) -> list[str]:
    health = scores.get("judge_health") or {}
    if not health:
        return []
    out = ["<h2>Judge health</h2><table><tr><th>Judge</th><th>Track</th><th>Samples</th>"
           "<th>Score spread (SD)</th><th>Mean distance from other judges</th></tr>"]
    for judge, tracks in health.items():
        for track, h in tracks.items():
            low = h["n"] >= 4 and h["spread"] < LOW_SPREAD
            far = h["deviation"] is not None and h["deviation"] > HIGH_DEVIATION
            out.append(f"<tr><td>{escape(judge)}</td><td>{track}</td><td>{h['n']}</td>"
                       f"<td{' class=bad' if low else ''}>{fmt(h['spread'], 1)}</td>"
                       f"<td{' class=bad' if far else ''}>{fmt(h['deviation'], 1)}</td></tr>")
    out.append(f"</table><p class=muted>Red: spread below {LOW_SPREAD} (the judge barely tells samples apart) or "
               f"distance above {HIGH_DEVIATION} points (it disagrees with the panel). To leave a judge out, "
               "list the judges to keep with <code>nwb report --judges</code>.</p>")
    return out


def _understanding(bench: Bench, scores: dict, states: bool = False) -> list[str]:
    label = lambda m: scores.get("labels", {}).get(m, m)
    summary = scores.get("state_understanding" if states else "understanding", {})
    if not summary:
        return []
    items = bench.state_items if states else bench.items
    item_ids = [i.id for i in items if any(i.id in s["items"] for s in summary.values())]
    title = "Optional state extraction · answer-keyed" if states else "Understanding diagnostics"
    out = [f"<h2>{title}</h2><div class=scroll><table><tr><th>Model</th><th>Vision</th><th>Text</th>"
           "<th>Text ZH</th><th>Text EN</th><th>Grounding</th><th>No image</th><th>Visual gain</th>"
           "<th>Halluc./answer</th><th>Used tools</th>" + "".join(f"<th>{escape(i)}</th>" for i in item_ids) + "</tr>"]
    for model, s in sorted(summary.items()):
        out.append(f"<tr><td>{escape(label(model))}</td><td>{fmt(s['vision'])}</td><td>{fmt(s['text'])}</td>"
                   f"<td>{fmt(s.get('languages', {}).get('zh'))}</td><td>{fmt(s.get('languages', {}).get('en'))}</td>"
                   f"<td>{fmt(s.get('grounding'))}</td><td>{fmt(s.get('blind'))}</td><td>{fmt(s.get('visual_gain'))}</td>"
                   f"<td>{fmt(s['hallucinations_per_answer'], 1)}</td><td>{s['contaminated']}</td>"
                   + "".join(f"<td>{fmt(s['items'].get(i))}</td>" for i in item_ids) + "</tr>")
    out.append("</table></div><p class=muted>Visual gain is the matched score difference with versus without the image, "
               "in percentage points. Grounding uses answer keys, not judges. Used tools: excluded answers where "
               "the agent called a tool despite being told not to.</p>")
    out.append(objective_tables(summary, label))
    out.append("<h3>Answers</h3>")
    by_item = defaultdict(list)
    for s in scores["samples"]["understanding"]:
        if bool(s.get("state")) == states:
            by_item[s["item"]].append(s)
    prompts = {i.id: i.prompt for i in items}
    for item in [i.id for i in items if i.id in by_item]:
        out.append(f"<details><summary>{escape(item)}</summary><p class=muted>{escape(prompts[item])}</p><table>")
        for s in sorted(by_item[item], key=lambda s: (s["model"], s["rep"])):
            halluc = "".join(f"<div class=bad>✗ {escape(h)}</div>" for h in s["hallucinations"])
            why = "".join(f"<div class=muted>{escape(j)}: {escape(r)}</div>" for j, r in s["rationales"].items())
            out.append(f"<tr><td>{escape(label(s['model']))} r{s['rep']}<br><b>{fmt(s['score'])}</b></td>"
                       f"<td class=ans>{escape(s['answer'])}{halluc}{why}</td></tr>")
        out.append("</table></details>")
    return out


def _imagegen(bench: Bench, scores: dict) -> list[str]:
    label = lambda m: scores.get("labels", {}).get(m, m)
    summary = scores["imagegen"]
    if not scores["samples"]["imagegen"]:
        return []
    tiers = [t for t in bench.all_tiers if any(t == s["tier"] for s in scores["samples"]["imagegen"])]
    out = ["<h2>Image generation diagnostics</h2><table><tr><th>Model</th><th>Available-cell mean</th>"
           + "".join(f"<th>{escape(t)}</th>" for t in tiers)
           + "<th>Knowledge ratio</th><th>Failure modes</th><th>Prompt not verbatim</th></tr>"]
    for model, s in sorted(summary.items()):
        modes = ", ".join(f"{escape(m)}×{n}" for m, n in sorted(s["failure_modes"].items(), key=lambda kv: -kv[1]))
        out.append(f"<tr><td>{escape(label(model))}</td><td><b>{fmt(s['overall'])}</b></td>"
                   + "".join(f"<td>{fmt(s['tiers'].get(t, {}).get('overall'))}</td>" for t in tiers)
                   + f"<td>{fmt(s['knowledge_ratio'], 2)}</td><td>{modes or '–'}</td>"
                   f"<td>{s['not_verbatim']} / {s['n']}</td></tr>")
    out.append("</table><p class=muted>Diagnostic means use available cells and may differ from the fixed ranking panel. "
               "Knowledge ratio = mean of both name tiers ÷ described_detailed, using only animals present in all "
               "three tiers. It measures sensitivity to prompt detail, not a calibrated probability of knowledge.</p>")
    if not summary:
        out = ["<h2>Image generation · unscored</h2>"]
    if any(s.get("state") for s in scores["samples"]["imagegen"]):
        out.append("<p>Optional state transfer: reference versus description, with animal identity and source expression "
                   "held separately for human review. State outputs are unscored; the laughing rubric is not applied.</p>")

    trait_names = list(bench.traits) + ["identity"]
    if summary:
        out.append("<h3>Trait coverage (0–2)</h3><table><tr><th>Model</th>"
                   + "".join(f"<th>{escape(t)}</th>" for t in trait_names) + "</tr>")
    by_model = defaultdict(list)
    for s in scores["samples"]["imagegen"]:
        by_model[s["model"]].append(s)
    for model, s in summary.items():
        out.append(f"<tr><td>{escape(label(model))}</td>"
                   + "".join(f"<td>{fmt(s['traits'].get(t), 1)}</td>" for t in bench.traits)
                   + f"<td>{fmt(s['identity'], 1)}</td></tr>")
    if summary:
        out.append("</table>")

    for model, samples in by_model.items():
        cells = {(s["animal"], s["tier"]): s for s in sorted(samples, key=lambda s: -s["rep"])}
        animals = [a for a in bench.animals if any(a == s["animal"] for s in samples)]
        out.append(f"<h3>Gallery · {escape(label(model))}</h3><table class=gallery><tr><th></th>"
                   + "".join(f"<th>{escape(t)}</th>" for t in tiers) + "</tr>")
        for a in animals:
            row = [f"<tr><td>{escape(bench.animals[a].zh)} {escape(a)}</td>"]
            for t in tiers:
                s = cells.get((a, t))
                if not s:
                    row.append("<td></td>")
                    continue
                if not s["images"]:
                    row.append(f"<td><span class=bad>refused by provider</span><br><b>{fmt(s['overall'])}</b></td>")
                    continue
                title = escape(" | ".join(f"{j}: {r}" for j, r in s["rationales"].items()), quote=True)
                flags = f"<div class='muted bad'>{escape(', '.join(s['failure_modes']))}</div>" if s["failure_modes"] else ""
                row.append(f"<td title=\"{title}\"><a href=\"{escape(s['images'][0])}\"><img loading=lazy "
                           f"src=\"{escape(s['images'][0])}\"></a><b>{fmt(s['overall'])}</b>"
                           f" <span class=muted>style {fmt(s['style'])}</span>{flags}</td>")
            out.append("".join(row) + "</tr>")
        out.append("</table>")
    return out

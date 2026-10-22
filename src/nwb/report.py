"""Self-contained HTML report for a run (images are linked relative to the run directory)."""

from collections import defaultdict
from html import escape

from nwb.config import Bench

CSS = """
body{font:14px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:1200px;padding:0 1rem;color:#1f2328;background:#fff}
h1,h2,h3{line-height:1.25}table{border-collapse:collapse;margin:.5rem 0 1.5rem}
th,td{border:1px solid #d0d7de;padding:.3rem .55rem;text-align:right;vertical-align:top}
th:first-child,td:first-child{text-align:left}th{background:#f6f8fa}
.gallery td{text-align:center;width:180px}.gallery img{width:170px;border-radius:6px;display:block;margin:auto}
.muted{color:#656d76;font-size:12px}.bad{color:#cf222e}.ans{white-space:pre-wrap;text-align:left;font-size:13px}
details{margin:.4rem 0}summary{cursor:pointer;font-weight:600}
@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}th{background:#161b22}
th,td{border-color:#30363d}.muted{color:#8d96a0}}
"""


def fmt(x, digits=0) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def leaderboard_table(rows: list[dict], label=lambda m: m) -> str:
    out = ["<table><tr><th>Rank</th><th>Model</th><th>Score</th><th>Scored cells</th>"
           "<th>Repetitions/cell</th><th>Status</th></tr>"]
    for row in rows:
        rank = row["rank"] if row["rank"] is not None else "–"
        out.append(f"<tr><td>{rank}</td><td>{escape(label(row['model']))}</td>"
                   f"<td><b>{fmt(row['score'], 1)}</b></td><td>{row['completed']}/{row['required']}</td>"
                   f"<td>{row['repetitions']}</td><td>{escape(row['status'])}</td></tr>")
    return "\n".join(out) + "</table>"


RANKING_NOTE = ("Two independent, provisional rankings; no combined score. Only complete fixed panels with the "
                "same attempted repetition ids scored in every cell receive ranks. Image generation requires verified verbatim "
                "prompts. Missing, failed, unjudged, or ineligible cells leave a model unranked. Text/language "
                "answers and no-image controls are diagnostics. Small score gaps do not establish a reliable ordering.")


def render(bench: Bench, run_name: str, scores: dict) -> str:
    out = [f"<!doctype html><meta charset=utf-8><title>奶蛙bench · nai-wai-bench · {escape(run_name)}</title>",
           f"<style>{CSS}</style><h1>奶蛙bench · nai-wai-bench · {escape(run_name)}</h1>",
           f"<p class=muted>Judges: {escape(', '.join(scores['judges']) or 'none')}. "
           "Scores are 0–100; each sample is averaged over judges from other vendors than the model "
           "(all judges if none are independent).</p>"]
    boards = scores.get("leaderboards", {})
    out += [f"<p class=muted>{RANKING_NOTE}</p>", "<h2>Image generation ranking</h2>",
            leaderboard_table(boards.get("imagegen", [])), "<h2>Visual understanding ranking</h2>",
            leaderboard_table(boards.get("visual_understanding", []))]
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
    summary = scores.get("state_understanding" if states else "understanding", {})
    if not summary:
        return []
    items = bench.state_items if states else bench.items
    item_ids = [i.id for i in items if any(i.id in s["items"] for s in summary.values())]
    title = "Optional state extraction · answer-keyed" if states else "Understanding diagnostics"
    out = [f"<h2>{title}</h2><table><tr><th>Model</th><th>Vision</th><th>Text</th>"
           "<th>Text ZH</th><th>Text EN</th><th>Grounding</th><th>No image</th><th>Visual gain</th>"
           "<th>Halluc./answer</th><th>Used tools</th>" + "".join(f"<th>{escape(i)}</th>" for i in item_ids) + "</tr>"]
    for model, s in sorted(summary.items()):
        out.append(f"<tr><td>{escape(model)}</td><td>{fmt(s['vision'])}</td><td>{fmt(s['text'])}</td>"
                   f"<td>{fmt(s.get('languages', {}).get('zh'))}</td><td>{fmt(s.get('languages', {}).get('en'))}</td>"
                   f"<td>{fmt(s.get('grounding'))}</td><td>{fmt(s.get('blind'))}</td><td>{fmt(s.get('visual_gain'))}</td>"
                   f"<td>{fmt(s['hallucinations_per_answer'], 1)}</td><td>{s['contaminated']}</td>"
                   + "".join(f"<td>{fmt(s['items'].get(i))}</td>" for i in item_ids) + "</tr>")
    out.append("</table><p class=muted>Visual gain is the matched score difference with versus without the image, "
               "in percentage points. Grounding uses answer keys, not judges. Used tools: excluded answers where "
               "the agent called a tool despite being told not to.</p><h3>Answers</h3>")
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
            out.append(f"<tr><td>{escape(s['model'])} r{s['rep']}<br><b>{fmt(s['score'])}</b></td>"
                       f"<td class=ans>{escape(s['answer'])}{halluc}{why}</td></tr>")
        out.append("</table></details>")
    return out


def _imagegen(bench: Bench, scores: dict) -> list[str]:
    summary = scores["imagegen"]
    if not scores["samples"]["imagegen"]:
        return []
    tiers = [t for t in bench.all_tiers if any(t == s["tier"] for s in scores["samples"]["imagegen"])]
    out = ["<h2>Image generation diagnostics</h2><table><tr><th>Model</th><th>Available-cell mean</th>"
           + "".join(f"<th>{escape(t)}</th>" for t in tiers)
           + "<th>Knowledge ratio</th><th>Failure modes</th><th>Prompt not verbatim</th></tr>"]
    for model, s in sorted(summary.items()):
        modes = ", ".join(f"{escape(m)}×{n}" for m, n in sorted(s["failure_modes"].items(), key=lambda kv: -kv[1]))
        out.append(f"<tr><td>{escape(model)}</td><td><b>{fmt(s['overall'])}</b></td>"
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
        out.append(f"<tr><td>{escape(model)}</td>"
                   + "".join(f"<td>{fmt(s['traits'].get(t), 1)}</td>" for t in bench.traits)
                   + f"<td>{fmt(s['identity'], 1)}</td></tr>")
    if summary:
        out.append("</table>")

    for model, samples in by_model.items():
        cells = {(s["animal"], s["tier"]): s for s in sorted(samples, key=lambda s: -s["rep"])}
        animals = [a for a in bench.animals if any(a == s["animal"] for s in samples)]
        out.append(f"<h3>Gallery · {escape(model)}</h3><table class=gallery><tr><th></th>"
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

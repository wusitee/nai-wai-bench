"""Local gallery and summary for the experimental frontend track (runs/<run>/frontend/gallery.html)."""

import html
import os
from pathlib import Path

from nwb.frontend import KINDS, MEMORY, Corpus, judged_images, samples, step
from nwb.frontend_render import page_document, render_current

# Live previews run model code inside an opaque-origin sandboxed iframe that may load nothing.
CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
       "style-src 'unsafe-inline'; script-src 'unsafe-inline'\">")
STYLE = """
body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#222;background:#fafafa}
h1{font-size:22px}h2{margin-top:36px;border-bottom:1px solid #ddd}h3{margin:18px 0 6px}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}
th{background:#f0f0f0}.num{text-align:right;font-variant-numeric:tabular-nums}
.strip{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}
figure{margin:0;background:#fff;border:1px solid #e3e3e3;padding:4px;max-width:260px}
figure img,figure iframe{display:block;image-rendering:auto;border:0}
figcaption{font-size:12px;color:#555}.fail{color:#b00020}.ok{color:#137333}
details{font-size:12px}.note{color:#666;max-width:900px}
"""


def _pct(value) -> str:
    return "–" if value is None else f"{value:.0%}"


def _link(path: Path, base: Path) -> str:
    return html.escape(os.path.relpath(path, base).replace(os.sep, "/"))


def _answers(questions, by_judge: dict) -> str:
    rows = "".join(f"<li>{html.escape(q)} " + " ".join(
        f"<span class={'ok' if a[i] else 'fail'}>{html.escape(j)}: {'yes' if a[i] else 'no'}</span>"
        for j, a in by_judge.items()) + "</li>" for i, q in enumerate(questions))
    return f"<details><summary>answers</summary><ol>{rows}</ol></details>"


def _live_2d(record: dict) -> str:
    """A sandboxed live preview of a 2D page, driving window.nwb.render(t) when the page uses it."""
    driver = ("<script>(function(){var D=%d;function f(ts){if(window.nwb&&typeof nwb.render==='function')"
              "nwb.render(ts%%D);requestAnimationFrame(f)}requestAnimationFrame(f)})()</script>" % record["duration_ms"])
    doc = page_document(record["html"], False, head=CSP) + driver
    return (f'<figure><iframe sandbox="allow-scripts" width="{record["width"]}" height="{record["height"]}" '
            f'srcdoc="{html.escape(doc)}"></iframe><figcaption>live (sandboxed)</figcaption></figure>')


def _sample_html(corpus: Corpus, path: Path, record: dict, scored: dict, base: Path) -> str:
    render_dir = path.with_suffix("")
    render = render_current(record, render_dir)
    gates = record["static_gates"] + (render["gates"] if render else [])
    status = (f"<span class=fail>gates failed: {html.escape('; '.join(gates))}</span>" if gates
              else f"score <b>{_pct(scored.get('score'))}</b>" if scored.get("score") is not None
              else html.escape(scored.get("status", "")))
    meta = record.get("meta", {})
    seconds = meta.get("seconds")
    tokens = (meta.get("tokens") or {}).get("output")
    detail = " · ".join(x for x in (f"{seconds:.0f}s" if seconds else "", f"{tokens} output tokens" if tokens else "",
                                    f"mode {render.get('mode')}" if render and render.get("mode") else "") if x)
    tiles = []
    if render and render.get("preview"):
        tiles.append(f'<figure><img src="{_link(render_dir / render["preview"], base)}" width="{record["width"]}">'
                     f"<figcaption>rendered loop</figcaption></figure>")
    if render and step(record["kind"]) == "s2" and record["kind"].startswith("2d") and not gates:
        tiles.append(_live_2d(record))
    images = scored.get("images", {})
    if render:
        for name, image, questions in judged_images(corpus, record, render, render_dir):
            if not image.is_file():
                continue
            judged = images.get(name)
            caption = f"{name} · {_pct(judged['score'])}" if judged else name
            answers = _answers(questions, judged["by_judge"]) if judged else ""
            tiles.append(f'<figure><img src="{_link(image, base)}" width="{min(record["width"], 240)}">'
                         f"<figcaption>{html.escape(caption)}</figcaption>{answers}</figure>")
        if render.get("failed_screenshot"):
            tiles.append(f'<figure><img src="{_link(render_dir / render["failed_screenshot"], base)}" width="240">'
                         "<figcaption>page at failure</figcaption></figure>")
    source = render_dir / "source.html.txt"
    if record.get("html") is not None:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(record["html"], encoding="utf-8")
    links = f' · <a href="{_link(source, base)}">source</a>' if source.is_file() else ""
    return (f"<h3>{html.escape(record['model'])} · {record['kind']} · r{record['rep']}</h3>"
            f"<p>{status}{' · ' + html.escape(detail) if detail else ''}{links}</p>"
            f"<div class=strip>{''.join(tiles)}</div>")


def gallery(corpus: Corpus, run_dir: Path, scores: dict) -> Path:
    base = run_dir / "frontend"
    out = base / "gallery.html"
    by_sample = {s["sample"]: s for s in scores["samples"]}
    found = samples(run_dir)
    parts = [f"<h1>Frontend reconstruction · {html.escape(run_dir.name)}</h1>",
             "<p class=note>Experimental and outside the NaiWai Index. Checklists are drafts awaiting human review; "
             "3D is unranked. Scores are the share of yes answers to each image's checklist, averaged over the "
             "images of a sample; a failed gate scores 0. Judges from the subject's own vendor are left out when "
             "another judge exists.</p>",
             "<h2>Summary</h2><table><tr><th>model</th><th>kind</th><th>score</th><th>95% CI</th>"
             "<th>keyframes</th><th>views</th><th>gates passed</th></tr>"]
    for row in scores["rows"]:
        ci = f"{row['ci95'][0]:.0%}–{row['ci95'][1]:.0%}" if row["ci95"] else "–"
        parts.append(f"<tr><td>{html.escape(row['model'])}</td><td>{row['kind']}</td>"
                     f"<td class=num>{_pct(row['score'])}</td><td class=num>{ci}</td>"
                     f"<td class=num>{_pct(row['frames_score'])}</td><td class=num>{_pct(row['views_score'])}</td>"
                     f"<td class=num>{row['gates_passed']}/{row['scored']} of {row['samples']}</td></tr>")
    parts.append("</table>")
    if scores["controls"]:
        parts.append("<h2>Judge calibration</h2><p class=note>Yes rates on control images: the reference frames "
                     "themselves should score high; a blank page and another task's frames should score low.</p>"
                     "<table><tr><th>judge</th><th>control</th><th>yes rate</th></tr>")
        for judge, groups in scores["controls"].items():
            for name, value in groups.items():
                parts.append(f"<tr><td>{html.escape(judge)}</td><td>{html.escape(name)}</td>"
                             f"<td class=num>{_pct(value)}</td></tr>")
        parts.append("</table>")
    for task_id in sorted({r["task"] for _, r in found}, key=lambda t: (t == MEMORY, t)):
        task = corpus.task(task_id)
        parts.append(f"<h2>{html.escape(task_id)} · {html.escape(task.title)}</h2>")
        if task.gif is not None:
            frames = "".join(f'<figure><img src="{_link(f.image, base)}" width="120"><figcaption>{f.timestamp_ms} ms'
                             "</figcaption></figure>" for f in task.frames)
            parts.append(f'<div class=strip><figure><img src="{_link(task.gif, base)}" width="{task.width}">'
                         f"<figcaption>reference GIF · {task.duration_ms} ms</figcaption></figure>{frames}</div>")
        for kind in KINDS:
            for path, record in found:
                if record["task"] == task_id and record["kind"] == kind:
                    parts.append(_sample_html(corpus, path, record, by_sample.get(record_sample(path, run_dir), {}), base))
    out.write_text(f"<!doctype html><meta charset=utf-8><title>Frontend gallery · {html.escape(run_dir.name)}</title>"
                   f"<style>{STYLE}</style>" + "\n".join(parts), encoding="utf-8")
    return out


def record_sample(path: Path, run_dir: Path) -> str:
    return path.relative_to(run_dir).as_posix()

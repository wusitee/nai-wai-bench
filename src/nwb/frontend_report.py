"""Local gallery for human review of the experimental frontend track (runs/<run>/frontend/gallery.html).

The gallery never runs model code: it shows the harness renders beside the reference keyframes, with the
checklist questions as review prompts, and links the page source as text."""

import html
import os
from pathlib import Path

from nwb.frontend import KINDS, MEMORY, Corpus, rendered_images, samples
from nwb.frontend_render import render_current

STYLE = """
body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#222;background:#fafafa}
h1{font-size:22px}h2{margin-top:36px;border-bottom:1px solid #ddd}h3{margin:18px 0 6px}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}
th{background:#f0f0f0}.num{text-align:right;font-variant-numeric:tabular-nums}
.strip{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}
figure{margin:0;background:#fff;border:1px solid #e3e3e3;padding:4px;max-width:260px}figure.wide{max-width:none}
figure img{display:block}.pair{display:flex;gap:2px}
figcaption{font-size:12px;color:#555}.fail{color:#b00020}.ok{color:#137333}
details{font-size:12px}details ol{padding-left:18px;margin:4px 0}.note{color:#666;max-width:900px}
"""


def _link(path: Path, base: Path) -> str:
    return html.escape(os.path.relpath(path, base).replace(os.sep, "/"))


def _questions(questions) -> str:
    items = "".join(f"<li>{html.escape(q)}</li>" for q in questions)
    return f"<details><summary>checklist</summary><ol>{items}</ol></details>"


def _sample_html(corpus: Corpus, path: Path, record: dict, base: Path) -> str:
    render_dir = path.with_suffix("")
    render = render_current(record, render_dir)
    gates = record["static_gates"] + (render["gates"] if render else [])
    status = (f"<span class=fail>gates failed: {html.escape('; '.join(gates))}</span>" if gates
              else "<span class=ok>gates passed</span>" if render else "not rendered yet")
    meta = record.get("meta", {})
    seconds = meta.get("seconds")
    tokens = (meta.get("tokens") or {}).get("output")
    detail = " · ".join(x for x in (f"{seconds:.0f}s" if seconds else "", f"{tokens} output tokens" if tokens else "",
                                    f"mode {render.get('mode')}" if render and render.get("mode") else "") if x)
    tiles = []
    task = corpus.task(record["task"])
    width = min(record["width"], 240)
    if render and render.get("preview"):
        reference = (f'<img src="{_link(task.gif, base)}" width="{width}">' if task.gif else "")
        tiles.append(f'<figure class=wide><div class=pair>{reference}<img src="{_link(render_dir / render["preview"], base)}" '
                     f'width="{width}"></div><figcaption>reference · rendered loop</figcaption></figure>')
    if render:
        for name, image, frame, questions in rendered_images(task, record, render_dir):
            if not image.is_file():
                continue
            half = width // 2 if frame and frame.image else width
            reference = f'<img src="{_link(frame.image, base)}" width="{half}">' if frame and frame.image else ""
            caption = f"{name} · {frame.timestamp_ms} ms" if frame and task.gif else name
            tiles.append(f'<figure><div class=pair>{reference}<img src="{_link(image, base)}" width="{half}"></div>'
                         f"<figcaption>{html.escape(caption)}</figcaption>{_questions(questions)}</figure>")
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


def gallery(corpus: Corpus, run_dir: Path, summary: dict) -> Path:
    base = run_dir / "frontend"
    out = base / "gallery.html"
    found = samples(run_dir)
    parts = [f"<h1>Frontend reconstruction · {html.escape(run_dir.name)}</h1>",
             "<p class=note>Experimental and outside the NaiWai Index. Samples are checked by scripted gates only; "
             "likeness is judged by people. Each tile shows the reference keyframe (left) beside the render (right); "
             "the checklist lists what to look for. 3D views have no reference image.</p>",
             "<h2>Gates</h2><table><tr><th>model</th><th>kind</th><th>passed</th><th>samples</th></tr>"]
    for row in summary["rows"]:
        parts.append(f"<tr><td>{html.escape(row['model'])}</td><td>{row['kind']}</td>"
                     f"<td class=num>{row['passed']}</td><td class=num>{row['samples']}</td></tr>")
    parts.append("</table>")
    for task_id in sorted({r["task"] for _, r in found}, key=lambda t: (t == MEMORY, t)):
        task = corpus.task(task_id)
        parts.append(f"<h2>{html.escape(task_id)} · {html.escape(task.title)}</h2>")
        if task.gif is not None:
            frames = "".join(f'<figure><img src="{_link(f.image, base)}" width="120"><figcaption>{f.timestamp_ms} ms'
                             "</figcaption></figure>" for f in task.frames)
            parts.append(f'<div class=strip><figure><img src="{_link(task.gif, base)}" width="{task.width}">'
                         f"<figcaption>reference GIF · {task.duration_ms} ms</figcaption></figure>{frames}</div>")
        else:
            parts.append(f"<div class=strip><figure><figcaption>From memory, no reference image.</figcaption>"
                         f"{_questions(task.frames[0].questions)}</figure></div>")
        for kind in KINDS:
            for path, record in found:
                if record["task"] == task_id and record["kind"] == kind:
                    parts.append(_sample_html(corpus, path, record, base))
    out.write_text(f"<!doctype html><meta charset=utf-8><title>Frontend gallery · {html.escape(run_dir.name)}</title>"
                   f"<style>{STYLE}</style>" + "\n".join(parts), encoding="utf-8")
    return out

"""Release pages of the experimental frontend track (frontend/ of the published site).

Built only from the checksum-verified files of a saved run, after `nwb.frontend_results.load` has checked
every identifier and reference in them. Like the local gallery, the pages never run model
code: they show the harness renders beside the reference GIFs and link each page's source as plain text.
Images are lazy-loaded with fixed dimensions, sample details load only when opened, and each task has its
own page, so the overview stays light."""

import json
import shutil
from html import escape as e
from pathlib import Path

from nwb.frontend import KINDS, MEMORY, VIEWS
from nwb.report import model_html
from nwb.site import FRONTEND_NAME, _footer, _head, _header

CSS = """
.fe-tasks{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,210px),1fr));gap:14px;margin-top:12px}
.fe-task{display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;
text-decoration:none;color:var(--fg);transition:border-color .15s}.fe-task:hover{border-color:rgba(250,204,21,.45)}
.fe-task img,.fe-task .fe-mem{display:block;width:100%;height:auto;aspect-ratio:1;object-fit:contain;background:var(--soft)}
.fe-mem{display:flex!important;align-items:center;justify-content:center;font-size:44px;font-weight:800;color:var(--yellow)}
.fe-task div{padding:10px 12px;font-size:13px;line-height:1.35}.fe-task b{display:block;font:700 12px var(--mono);color:var(--yellow)}
.fe-ref{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;margin-top:16px}
.fe-ref figure{margin:0}.fe-ref img{display:block;height:auto;border-radius:6px;background:var(--soft)}
.fe-ref figcaption,.fe-cell figcaption,.fe-pair figcaption{font:11px/1.4 var(--mono);color:var(--muted);margin-top:4px}
.fe-strip{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:6px;flex:1;min-width:min(100%,420px)}
.fe-strip img{width:100%}.fe-ref>figure{max-width:100%}
@media(max-width:760px){.fe-strip{grid-template-columns:repeat(4,minmax(0,1fr))}}
.fe-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,500px),1fr));gap:14px;margin-top:12px}
.fe-card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;min-width:0;
content-visibility:auto;contain-intrinsic-size:auto 340px}
.fe-card h3{margin:0 0 10px;font-size:14px;text-transform:none;letter-spacing:0}
.fe-row{display:grid;grid-template-columns:repeat(var(--cols),minmax(0,1fr));gap:8px}
.fe-cell{margin:0;min-width:0}.fe-cell img,.fe-pair img{display:block;width:100%;height:auto;border-radius:5px;background:var(--soft)}
.fe-none{display:flex;align-items:center;justify-content:center;text-align:center;padding:6px;border:1px dashed var(--line);
border-radius:5px;color:var(--muted);font-size:12px}
.fe-none.bad{color:var(--bad-ink);border-color:rgba(239,68,68,.35)}
.fe-card details{margin:10px 0 0;background:none;padding:6px 10px}
.fe-card h4{margin:12px 0 6px;font:600 11px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--ink2)}
.fe-pairs{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.fe-views{display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:8px;margin-top:8px}
.fe-pair{margin:0}.fe-pair>div{display:grid;grid-template-columns:1fr 1fr;gap:2px}
.fe-gates{color:var(--bad-ink);font-size:12px;word-break:break-word}
.fe-table td.n,.fe-table th.n{text-align:center}
"""
# Columns of a card: per dimension, the kinds from first page to revision.
STAGES = {"gif": (("s1", "静态", "Still"), ("s2", "动画", "Animated"), ("s3", "修订", "Revision")),
          "mem": (("mem", "初稿", "First page"), ("mem2", "修订", "Revision"))}
DIMENSIONS = (("2d", "svg", "2D · SVG", "手写内联 SVG", "hand-written inline SVG"),
              ("3d", "threejs", "3D · three.js", "代码生成几何体的 three.js 场景", "three.js scenes built in code"))
VIEW_TEXT = {"side": "侧面 side", "back": "背面 back", "three_quarter": "四分之三 three-quarter", "top": "顶视 top"}


def _img(src: str, width: int, height: int, alt: str, still: str | None = None) -> str:
    img = (f"<img src='{e(src, quote=True)}' width={width} height={height} alt='{e(alt, quote=True)}' "
           "loading=lazy decoding=async>")
    if still:  # animated loops fall back to their first frame for readers who prefer reduced motion
        return f"<picture><source srcset='{e(still, quote=True)}' media='(prefers-reduced-motion: reduce)'>{img}</picture>"
    return img


def _number(value, pattern: str) -> str:
    return pattern.format(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else ""


def build(files: dict[str, bytes], summary: dict, out: Path, repo_url: str | None = None,
          blob: str | None = None) -> Path:
    """Write out/frontend/: an overview with the gate table and one page per task."""
    base = out / "frontend"
    if base.exists():
        shutil.rmtree(base)
    tasks = summary["tasks"]
    labels = summary["labels"]
    status = {entry["sample"]: entry for entry in summary["samples"]}
    models = sorted(labels, key=lambda m: labels[m].lower())
    by_key = {(s["model"], s["task"], s["kind"], s["rep"]): s["sample"] for s in summary["samples"]}

    def write(stem: str, name: str, data: bytes) -> str:
        """Write a file of snapshot directory `stem` (reference/<task>/ stays, frontend/<model>/... goes under
        m/) and return its path below frontend/."""
        relative = ("m/" + stem.removeprefix("frontend/") if stem.startswith("frontend/") else stem) + "/" + name
        target = base / relative
        if not target.resolve().is_relative_to(base.resolve()):
            raise ValueError(f"frontend page file leaves the output directory: {relative!r}")
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return relative

    def media(name: str | None, stem: str, depth: str) -> str | None:
        """Publish one verified image and return its link from a page `depth` levels below frontend/."""
        return depth + write(stem, name, files[f"{stem}/{name}"]) if name else None

    docs = f"<a href='{e(blob, quote=True)}/docs/frontend.md'>方法 Method</a>" if blob else ""
    title = f"{FRONTEND_NAME[0]} · {FRONTEND_NAME[1]} · 奶蛙bench"
    head = _head(title) + f"<style>{CSS}</style>"
    intro = ("<p class=lede>模型只看 GIF 的关键帧，手写网页把奶蛙动图复刻出来：2D 用内联 SVG，3D 用 three.js 在代码里搭几何体。"
             "不能用任何图片，渲染在沙箱里离线进行。<br><span class=en>Models rebuild animated 奶蛙 GIFs as hand-written "
             "web pages from their keyframes: inline SVG in 2D, three.js geometry built in code in 3D. No raster "
             "images are allowed, and pages render offline in a sandbox.</span></p>")
    note = ("<div class=note>实验项目，不计入奶蛙指数，也没有分数或名次：脚本只检查硬性规则（离线、无图片、确定性、循环周期、3D 的立体感等），"
            "像不像由人来看。LLM 评审试过，会给布局对但画得粗糙的作品满分，所以没有采用。每个模型每题一次采样；"
            "“修订”是模型看过自己的渲染结果后的一次修改。<br><span class=en>Experimental and outside the NaiWai Index, "
            "with no score or rank. Scripted gates check only hard rules (offline, no raster images, determinism, "
            "loop period, 3D depth, ...); likeness is for people to judge. LLM checklist judging was tried and "
            "dropped because it gave rough drawings with the right layout full marks. One sample per model and task; "
            "a revision is the model's one change after seeing its own render.</span></div>")

    # --- overview ---
    rows: dict[tuple[str, str], dict] = {}
    for entry in summary["samples"]:
        row = rows.setdefault((entry["model"], entry["kind"]), {"samples": 0, "passed": 0})
        row["samples"] += 1
        row["passed"] += entry["status"] == "passed"
    kinds = [k for k in KINDS if any(kind == k for _, kind in rows)]
    table = ["<div class='scroll card-table'><table class=fe-table><tr><th>模型 Model</th>"
             + "".join(f"<th class=n>{e(k)}</th>" for k in kinds) + "</tr>"]
    for model in models:
        cells = []
        for kind in kinds:
            row = rows.get((model, kind))
            if row is None:
                cells.append("<td class=n>–</td>")
            else:
                mark = "mark-ok" if row["passed"] == row["samples"] else "mark-no"
                cells.append(f"<td class=n><span class={mark}>{row['passed']}</span>/{row['samples']}</td>")
        table.append(f"<tr><td><b>{model_html(labels[model])}</b></td>{''.join(cells)}</tr>")
    table.append("</table></div>")
    cards = []
    for task_id, task in tasks.items():
        count = sum(1 for s in summary["samples"] if s["task"] == task_id)
        if task["frames"]:
            thumb = _img(media(task["frames"][0]["file"], f"reference/{task_id}", ""), task["width"], task["height"],
                         task["title"])
            name = task_id
        else:
            thumb, name = "<span class=fe-mem>?</span>", "凭记忆 From memory"
        cards.append(f"<a class=fe-task href='{e(task_id, quote=True)}/'>{thumb}<div><b>{e(name)}</b>{e(task['title'])}"
                     f"<br><span class=muted>{count} 个样本 samples</span></div></a>")
    page = [head, _header("frontend", "<a href='#tasks'>题目 Tasks</a><a href='#gates'>检查 Gates</a>" + docs, True),
            "<div class='hero solo'><div>"
            f"<h1>前端复刻 <span class=en>Frontend rebuild</span></h1>{intro}"
            f"<span class=badge>实验 Experimental</span> <span class=stamp>run <code>{e(summary['run'])}</code> · "
            f"corpus <code>{e(summary['corpus'])}</code> · harness <code>{e(summary['harness'])}</code></span>"
            f"</div></div>{note}",
            f"<h2 id=tasks>题目 <span class=en>Tasks</span></h2><div class=fe-tasks>{''.join(cards)}</div>",
            "<h2 id=gates>脚本检查 <span class=en>Scripted gates</span></h2>"
            "<p class=muted>通过数 / 样本数；s1 静态、s2 动画、s3 与 mem2 为修订。<span class=en> Passed / samples. s1 is "
            "the still page, s2 the animation, s3 and mem2 the revisions.</span></p>" + "".join(table),
            _footer(repo_url, blob)]
    base.mkdir(parents=True, exist_ok=True)
    (base / "index.html").write_text("\n".join(page), encoding="utf-8")

    # --- one page per task ---
    for task_id, task in tasks.items():
        width, height = task["width"], task["height"]
        memory = task_id == MEMORY
        stages = STAGES["mem" if memory else "gif"]
        ref_frames = task["frames"]

        def sample_figure(model: str, kind: str, rep: int, caption: tuple[str, str]) -> tuple[str, str]:
            """A card cell and the detail section for one sample."""
            label = f"{caption[0]} <span class=en>{caption[1]}</span>"
            path = by_key.get((model, task_id, kind, rep))
            if path is None:
                return (f"<figure class=fe-cell><div class=fe-none style='aspect-ratio:{width}/{height}'>未采集<br>"
                        f"not collected</div><figcaption>{label}</figcaption></figure>"), ""
            stem = path.removesuffix(".json")
            entry = status[path]
            record = json.loads(files[path])
            render = json.loads(files[f"{stem}/render.json"]) if f"{stem}/render.json" in files else None
            meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
            tokens = meta.get("tokens") if isinstance(meta.get("tokens"), dict) else {}
            facts = [_number(meta.get("seconds"), "{:.0f} s"), _number(tokens.get("output"), "{:,} tok")]
            mark = {"passed": "<span class=mark-ok>✓</span>", "gate failed": "<span class=mark-no>✗</span>"}.get(
                entry["status"], "<span class=muted>–</span>")
            frames = (render or {}).get("frames", [])
            first = media(frames[0]["file"], stem, "../") if frames and frames[0]["file"] else None
            loop = media(render.get("preview"), stem, "../") if render else None
            if loop:
                main = _img(loop, width, height, f"{labels[model]} {kind}", still=first)
            elif first:
                main = _img(first, width, height, f"{labels[model]} {kind}")
            elif render and render.get("failed_screenshot"):
                main = _img(media(render["failed_screenshot"], stem, "../"), width, height, "page at failure")
            else:
                text = "未通过 gates failed" if entry["status"] == "gate failed" else "未渲染 not rendered"
                main = f"<div class='fe-none bad' style='aspect-ratio:{width}/{height}'>{text}</div>"
            cell = (f"<figure class=fe-cell>{main}<figcaption>{mark} {label}<br>"
                    + " · ".join(e(f) for f in facts if f) + "</figcaption></figure>")
            page_source = record.get("html") if isinstance(record.get("html"), str) else ""
            source = write(stem, "source.txt", page_source.encode())
            detail = [f"<h4>{e(kind)} · {e(caption[1])} · <a href='../{e(source, quote=True)}'>源码 source</a></h4>"]
            if entry["gates"]:
                detail.append("<p class=fe-gates>" + "<br>".join(e(g) for g in entry["gates"]) + "</p>")
            # Keyframes pair the reference (left) with the render; renders without a reference and the 3D
            # views are single tiles at the same size.
            pairs, singles = [], []
            for index, frame in enumerate(frames):
                if not frame["file"]:
                    continue
                render_img = _img(media(frame["file"], stem, "../"), width, height, "render")
                reference = ref_frames[index] if index < len(ref_frames) else None
                if reference:
                    ref = _img(media(reference["file"], f"reference/{task_id}", "../"), width, height, "reference")
                    pairs.append(f"<figure class=fe-pair><div>{ref}{render_img}</div>"
                                 f"<figcaption>{int(reference['t'])} ms</figcaption></figure>")
                else:
                    singles.append(f"<figure class=fe-pair>{render_img}<figcaption>{int(frame['t'])} ms</figcaption></figure>")
            for view in (render or {}).get("views", []):
                if view["file"] and view["view"] in VIEWS:
                    singles.append(f"<figure class=fe-pair>{_img(media(view['file'], stem, '../'), width, height, view['view'])}"
                                   f"<figcaption>{e(VIEW_TEXT[view['view']])}</figcaption></figure>")
            if pairs:
                detail.append(f"<div class=fe-pairs>{''.join(pairs)}</div>")
            if singles:
                detail.append(f"<div class=fe-views>{''.join(singles)}</div>")
            return cell, "".join(detail)

        sections = []
        for dim, anchor, heading, zh, en in DIMENSIONS:
            dim_cards = []
            for model in models:
                reps = sorted({s["rep"] for s in summary["samples"]
                               if s["model"] == model and s["task"] == task_id and s["kind"].startswith(dim)})
                for rep in reps:
                    cells, details = zip(*(sample_figure(model, f"{dim}-{stage}", rep, (czh, cen))
                                           for stage, czh, cen in stages))
                    name = model_html(labels[model]) + (f" <span class=muted>r{rep}</span>" if len(reps) > 1 else "")
                    dim_cards.append(
                        f"<div class=fe-card><h3>{name}</h3><div class=fe-row style='--cols:{len(stages)}'>{''.join(cells)}</div>"
                        + (f"<details><summary>关键帧、视角与源码 <span class=en>Keyframes, views, source</span></summary>"
                           "<p class=muted>关键帧左为参考、右为渲染。<span class=en> Keyframes: reference left, render right.</span></p>"
                           f"{''.join(details)}</details>" if any(details) else "") + "</div>")
            if dim_cards:
                sections.append(f"<h2 id={anchor}>{e(heading)}</h2><p class=muted>{e(zh)}<span class=en> · {e(en)}</span></p>"
                                f"<div class=fe-cards>{''.join(dim_cards)}</div>")
        if memory:
            reference = ("<p class=muted>没有参考图：只给一句“凭记忆画出大笑奶龙”。<span class=en> No reference image: the "
                         "prompt only asks to draw 大笑奶龙 from memory.</span></p>")
        else:
            strip = "".join(f"<figure>{_img(media(f['file'], f'reference/{task_id}', '../'), width, height, 'keyframe')}"
                            f"<figcaption>{int(f['t'])} ms</figcaption></figure>" for f in ref_frames)
            gif = media(task["gif"], f"reference/{task_id}", "../")
            reference = (f"<div class=fe-ref><figure>{_img(gif, width, height, task['title'], still=media(ref_frames[0]['file'], f'reference/{task_id}', '../'))}"
                         f"<figcaption>参考 GIF reference · {task['duration_ms']} ms · {width} × {height}</figcaption></figure>"
                         f"<div class=fe-strip>{strip}</div></div>")
        links = "".join(f"<a href='#{a}'>{e(h.split(' ')[0])}</a>" for _, a, h, _, _ in DIMENSIONS) + docs
        page = [head, _header("frontend", links, True, up="../"),
                f"<p class=muted><a href='../'>← 前端复刻 Frontend rebuild</a></p>"
                f"<h1>{e('凭记忆' if memory else task_id)} <span class=en>{e(task['title'])}</span></h1>{reference}",
                *sections, _footer(repo_url, blob)]
        write(task_id, "index.html", "\n".join(page).encode())
    return base / "index.html"

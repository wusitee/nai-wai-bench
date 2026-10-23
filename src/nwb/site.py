"""Static, bilingual (中文 / English) results site for a run: one index.html plus resized images,
ready to publish with GitHub Pages."""

import datetime
import shutil
import subprocess
from collections import defaultdict
from html import escape as e
from pathlib import Path

from nwb.config import SUITES, Bench, ModelSpec, UnderstandingItem
from nwb.report import fmt
from nwb.util import extract_json, read_json

FAILURE_ZH = {"generic_cute": "泛泛的可爱风", "realistic_animal": "写实动物", "plain_nailong": "只是奶龙本体",
              "text_or_watermark": "带文字或水印", "multiple_subjects": "多主体或场景杂乱"}
ACCESS = {"codex": "Codex CLI", "claude": "Claude Code", "acp": "ACP agent", "openai": "API"}
STATUS = {"complete": "完整 complete", "incomplete": "不完整 incomplete",
          "incomplete repetitions": "重复次数不齐 incomplete repetitions"}
CONDITION = {"described": ("文字描述", "description"), "reference": ("参考图", "reference image")}
IMAGE_WIDTH = 768

# Per suite: tab label, page title, introduction (zh, en), and whether the answer-keyed casebook
# is the page's centerpiece (shown before the generation galleries).
SUITE_TEXT = {
    "core": {
        "tab": ("主榜", "Core"), "title": ("奶蛙bench", "nai-wai-bench"), "casebook_first": False,
        "intro": ("测试 AI 模型对中文网络梗“大笑奶龙”（又称“奶蛙”）的掌握：能否从图片中认出它和它的变体，"
                  "以及能否按它的 3D 风格把它画成别的动物。",
                  "How well do AI models know the Chinese meme 大笑奶龙 (Laughing Nailong, also called 奶蛙)? "
                  "Can they recognize it and its variants in images, and draw other animals in its 3D style?"),
    },
    "naihub-v1": {
        "tab": ("奶蛙图鉴", "Nai-hub v1"), "title": ("奶蛙图鉴", "Nai-hub v1 casebook"), "casebook_first": True,
        "intro": ("24 张图，同一道看图题：这是奶蛙、官方奶龙，还是别的角色？有几只？什么姿态、眼睛、嘴巴和手势？"
                  "有没有流泪？七项全部答对才算这张图答对。其中 8 张还被拿来测试：能否把同样的姿势搬到猫和青蛙身上。",
                  "24 images, one question each: is it 奶蛙, official Nailong, or someone else? How many are there? "
                  "What posture, eyes, mouth, and gesture? Any tears? An image counts only when all seven fields "
                  "are right. Eight of them also test whether image models can move the same pose onto a cat "
                  "and a frog."),
    },
}
CATEGORY = {"anchors": ("经典锚点", "Anchors"), "pose_action": ("姿势动作", "Pose and action"),
            "appearance": ("外观造型", "Appearance"), "context": ("场景与多角色", "Context"),
            "negative_control": ("反例对照", "Negative controls")}
FIELD_ZH = {"family": "类别", "subjects": "数量", "posture": "姿态", "eyes": "眼睛", "mouth": "嘴巴",
            "gesture": "手势", "tears": "眼泪", "pose": "姿势", "state": "表情"}

CSS = """
:root{--bg:#fbf8f0;--fg:#1d1b16;--ink2:#4f4a3f;--muted:#736d60;--line:#e8e1cf;--card:#fffdf8;--soft:#f3ecda;
--yellow:#f5c518;--link:#8a5a00;--bar:#c98500;--good:#0ca30c;--bad:#d03b3b;--good-ink:#006300;--bad-ink:#b4261e;
--heat:#c2410c;--heat-ink:#fff;--shadow:0 1px 2px rgba(60,40,0,.06),0 6px 18px rgba(60,40,0,.05)}
@media (prefers-color-scheme:dark){:root{--bg:#14130f;--fg:#ece8df;--ink2:#cfc8b8;--muted:#a39d90;--line:#2e2b24;
--card:#1c1a15;--soft:#28251d;--link:#f0b429;--bar:#f0b429;--good-ink:#57c46f;--bad-ink:#f2777a;--heat:#d9592a;
--heat-ink:#ece8df;--shadow:none}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--link)}code,.mono{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 90%,transparent);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.top>div{max-width:1180px;margin:auto;padding:8px 20px;display:flex;gap:10px 18px;align-items:center;flex-wrap:wrap}
.brand{font-weight:800;color:var(--fg);text-decoration:none}
.tabs{display:flex;gap:2px;background:var(--soft);border-radius:99px;padding:3px}
.tabs a{padding:2px 12px;border-radius:99px;text-decoration:none;color:var(--ink2);font-size:13.5px;font-weight:600}
.tabs a[aria-current]{background:var(--yellow);color:#1d1b16}
.sections{display:flex;gap:14px;overflow-x:auto;font-size:13.5px;flex:1}
.sections a{color:var(--ink2);text-decoration:none;white-space:nowrap}.sections a:hover{color:var(--link)}
main{max-width:1180px;margin:auto;padding:30px 20px 64px}
h1{font-size:34px;line-height:1.2;margin:0 0 10px}h2{font-size:23px;margin:60px 0 8px}h3{font-size:17px;margin:28px 0 8px}
.en{color:var(--muted);font-weight:400}.muted{color:var(--muted);font-size:13px}.lede{font-size:16.5px;margin:0 0 12px}
.hero{display:grid;grid-template-columns:auto 1fr;gap:28px;align-items:center}
.hero.solo{grid-template-columns:1fr}.hero>img{width:170px;border-radius:22px;box-shadow:var(--shadow)}
.badge{display:inline-block;background:var(--yellow);color:#1d1b16;border-radius:99px;padding:1px 10px;font-size:12px;font-weight:700}
.mosaic{display:grid;grid-template-columns:repeat(12,1fr);gap:6px;margin:24px 0 0}
.mosaic a{display:block;aspect-ratio:1;border-radius:10px;overflow:hidden;background:var(--card);border:1px solid var(--line)}
.mosaic img{width:100%;height:100%;object-fit:cover;transition:transform .15s}.mosaic a:hover img{transform:scale(1.08)}
.note{border:1px solid var(--line);border-left:4px solid var(--yellow);background:var(--card);border-radius:12px;
padding:10px 14px;margin:22px 0}
.panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:18px;margin-top:12px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow);min-width:0}
.panel h3{margin:0 0 4px}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top;font-size:14px}
th{font-size:12px;color:var(--muted);font-weight:600;vertical-align:bottom}th.n,td.n{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child>td{border-bottom:0}.scroll{overflow-x:auto}.card-table{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:4px 8px}
.rank{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--soft);font-weight:700;font-size:12.5px}
.rank.first{background:var(--yellow);color:#1d1b16}
.meter{display:flex;align-items:center;gap:8px;min-width:140px}.meter b{min-width:36px;text-align:right;font-variant-numeric:tabular-nums}
.track{flex:1;height:10px;background:var(--soft);border-radius:0 4px 4px 0}
.fill{display:block;height:100%;background:var(--bar);border-radius:0 4px 4px 0}
.flag{display:inline-block;font-size:11px;font-weight:600;border:1px solid var(--line);border-radius:6px;padding:0 6px;color:var(--ink2);margin-left:4px}
.heat{text-align:right;font-variant-numeric:tabular-nums;box-shadow:inset 0 0 0 1px var(--card)}.heat.hi{color:var(--heat-ink)}
.group{display:flex;align-items:baseline;gap:10px;margin:30px 0 10px}.group h3{margin:0}
.cases{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
.case{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:var(--shadow);
display:flex;flex-direction:column;scroll-margin-top:70px}.case:target{outline:3px solid var(--yellow)}
.case>a img{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:var(--soft)}
.case>div{padding:12px 14px 14px;display:flex;flex-direction:column;gap:9px}
.case-title{font-weight:700;line-height:1.3}.case-title span{color:var(--muted);font-weight:400;font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.chip{display:inline-flex;flex-direction:column;background:var(--soft);border-radius:8px;padding:2px 7px;line-height:1.25;
font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.chip small{font:10.5px system-ui,sans-serif;color:var(--muted)}
.verdict{display:flex;align-items:center;gap:10px;font-size:13px}.verdict b{white-space:nowrap}
.segs{display:flex;gap:2px;flex:1}.seg{flex:1;height:10px;background:var(--bad)}.seg.ok{background:var(--good)}
.seg:first-child{border-radius:4px 0 0 4px}.seg:last-child{border-radius:0 4px 4px 0}
.case details{background:none;border:0;padding:0;margin:0;font-size:13px}.case summary{font-weight:600;font-size:13px}
.who{list-style:none;padding:0;margin:6px 0 0}.who li{padding:4px 0;border-top:1px solid var(--line)}
.mark-ok{color:var(--good-ink);font-weight:700}.mark-no{color:var(--bad-ink);font-weight:700}
.miss{display:inline-block;margin-right:8px}.miss code{background:var(--soft);border-radius:4px;padding:0 4px}
.raw{white-space:pre-wrap;word-break:break-word;font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
background:var(--soft);border-radius:8px;padding:6px 8px;margin:4px 0 8px;max-height:220px;overflow:auto}
.gallery{table-layout:fixed;min-width:760px}.gallery td,.gallery th{text-align:center}
.gallery img{width:100%;max-width:190px;aspect-ratio:1;object-fit:contain;border-radius:12px;display:block;margin:0 auto 4px;background:var(--soft)}
.gallery td:first-child,.gallery th:first-child{text-align:left}
.score{font-size:19px;font-weight:700}.tag{font-size:11.5px;color:var(--bad-ink)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 12px;margin:8px 0}
summary{cursor:pointer;font-weight:600}.ans{white-space:pre-wrap;font-size:13px}
.refused{display:flex;align-items:center;justify-content:center;aspect-ratio:1;max-width:190px;margin:0 auto 4px;
border:1px dashed var(--line);border-radius:12px;color:var(--bad-ink);font-size:13px}
.state{display:grid;grid-template-columns:190px 1fr;gap:18px;background:var(--card);border:1px solid var(--line);
border-radius:16px;padding:16px;margin:14px 0;box-shadow:var(--shadow)}
.state figure{margin:0}.state figure img{width:100%;border-radius:12px;background:var(--soft)}
.state figcaption{font-weight:700;margin-top:6px}.state .gallery{min-width:640px}
footer{margin-top:56px;color:var(--muted);font-size:13px}
@media(max-width:760px){.meter{min-width:90px}.hero{grid-template-columns:1fr}.hero>img{width:120px}.mosaic{grid-template-columns:repeat(6,1fr)}
.state{grid-template-columns:1fr}.state figure img{max-width:200px}h1{font-size:28px}}
"""


def _record(run_dir: Path, target: str) -> dict:
    return read_json(run_dir / target)


def _copy_image(src: Path, out: Path, stem: str) -> str:
    """Copy an image into the site as out/<stem>.jpg, resized with ImageMagick when it is installed
    (otherwise copied as is); returns the path relative to the site root."""
    if shutil.which("magick"):
        rel_path = f"{stem}.jpg"
        (out / rel_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["magick", str(src), "-resize", f"{IMAGE_WIDTH}x{IMAGE_WIDTH}>", "-quality", "85",
                        str(out / rel_path)], check=True)
    else:
        rel_path = f"{stem}{src.suffix}"
        (out / rel_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out / rel_path)
    return rel_path


def _access(spec: ModelSpec | None, meta: dict) -> str:
    """The client that ran the model (e.g. "codex-cli 0.163.0") and the model id it was given."""
    backend = (spec.backend if spec else meta.get("backend")) or "?"
    client = meta.get("client")
    head = f"API · {client}" if backend == "openai" and client else client or ACCESS.get(backend, backend)
    model = meta.get("model") or (spec.model if spec else "")
    return e(head) + (f" · <code>{e(model)}</code>" if model else "")


def _c2pa(meta: dict) -> str:
    c = meta.get("c2pa")
    if not c:
        return "–"
    gens = [g for g in c.get("generators", []) if "C2PA" not in g]  # skip signing-library entries
    return e("; ".join(gens + c.get("actions", [])) or "C2PA")


def _revision(root: Path) -> str | None:
    """Short commit of the benchmark definition the site was built from, marked when it has local changes."""
    try:
        rev = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                                      text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--", "bench", "src"],
                                        text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return rev + (" + local changes" if dirty else "")


def _suite_href(here: str, target: str) -> str:
    """Published layout: the core suite at the site root, every other suite in a subdirectory named after it."""
    to_root = "" if here == "core" else "../"
    return (to_root + ("" if target == "core" else f"{target}/")) or "./"


def _ranking(rows: list[dict], label, flags: dict[str, str]) -> str:
    if not rows:
        return "<p class=muted>本次运行没有这一题组的结果。<span class=en> No results for this panel in this run.</span></p>"
    out = ["<div class=scroll><table><tr><th>名次<br>Rank</th><th>模型 Model</th><th>得分 Score</th>"
           "<th class=n>已计分<br>Scored</th></tr>"]
    for row in rows:
        rank = (f"<span class='rank{' first' if row['rank'] == 1 else ''}'>{row['rank']}</span>"
                if row["rank"] is not None else "–")
        meter = (f"<div class=meter><span class=track><span class=fill style='width:{row['score']:.1f}%'></span>"
                 f"</span><b>{fmt(row['score'], 1)}</b></div>" if row["score"] is not None else "–")
        # Only unranked rows need their status spelled out.
        status = ("" if row["status"] == "complete"
                  else f"<br><span class=tag>{e(STATUS.get(row['status'], row['status']))}</span>")
        out.append(f"<tr><td>{rank}</td><td><b>{e(label(row['model']))}</b>{flags.get(row['model'], '')}{status}</td>"
                   f"<td>{meter}</td><td class=n>{row['completed']}/{row['required']} "
                   f"<span class=muted title='每格重复 repetitions per cell'>×{row['repetitions']}</span></td></tr>")
    return "\n".join(out) + "</table></div>"


def _heat(value: float | None, note: str = "") -> str:
    """A 0–100 score cell shaded by its shortfall: the surface at 100, one warm hue at full strength at 0."""
    if value is None:
        return "<td class=heat>–</td>"
    miss = max(0.0, min(100.0, 100 - value))
    style = f"background:color-mix(in oklab,var(--heat) {miss:.0f}%,var(--card))"
    return f"<td class='heat{' hi' if miss >= 75 else ''}' style='{style}'>{fmt(value)}{note}</td>"


HEAT_NOTE = "颜色越深，分数越低。<span class=en> Darker cells mark lower scores.</span>"


def _image_cell(s: dict | None, image: str | None, alt: str, scored: bool = True, meta: dict | None = None) -> str:
    """A gallery cell: the image (or the provider's refusal), its score when scored, its prompt audit, and
    a label when the record notes another route than the model's usual client (meta.fill_note)."""
    if not s:
        return "<td>–</td>"
    audit = {True: "原样传递 · Verbatim", False: "提示词有改动 · Prompt changed", None: "未核实 · Unverified"}[s["verbatim"]]
    score = f"<span class=score>{fmt(s['overall'])}</span>" if scored else ""
    if not image:
        return f"<td><div class=refused>服务商拒绝生成<br>Refused by provider</div>{score}<div class=muted>{audit}</div></td>"
    why = " | ".join(f"{j}: {r}" for j, r in s["rationales"].items())
    tags = "".join(f"<div class=tag>{e(FAILURE_ZH.get(f, f))}</div>" for f in s["failure_modes"])
    if (meta or {}).get("fill_note"):
        tags += (f"<div class=muted title='{e(meta['fill_note'], quote=True)} · {e(meta.get('model', ''), quote=True)}'>"
                 f"补图 · via {e(meta.get('client', '?'))}</div>")
    return (f"<td title='{e(why, quote=True)}'><a href='{e(image)}'><img loading=lazy src='{e(image)}' alt='{e(alt)}'></a>"
            f"{score}{tags}<div class=muted>{audit}</div></td>")


def _summary_table(usum: dict, label) -> str:
    """Understanding diagnostics per model; columns without any value in this run are left out."""
    optional = [
        ("文字 Text", lambda s: s.get("text"), 0),
        ("中文 Text ZH", lambda s: s.get("languages", {}).get("zh"), 0),
        ("英文 Text EN", lambda s: s.get("languages", {}).get("en"), 0),
        ("视觉核对 Grounding", lambda s: s.get("grounding"), 0), ("无图 No image", lambda s: s.get("blind"), 0),
        ("视觉增益 Visual gain", lambda s: s.get("visual_gain"), 0),
        ("每答幻觉 Halluc./answer", lambda s: s.get("hallucinations_per_answer"), 1),
    ]
    # Grounding repeats the vision mean when every image item is answer-keyed.
    if all(s.get("grounding") == s.get("vision") for s in usum.values()):
        optional = [c for c in optional if not c[0].startswith("视觉核对")]
    shown = ([("看图 Vision", lambda s: s.get("vision"), 0)]
             + [c for c in optional if any(c[1](s) is not None for s in usum.values())])
    out = ["<div class='scroll card-table'><table><tr><th>模型 Model</th>"
           + "".join(f"<th class=n>{h.replace(' ', '<br>', 1)}</th>" for h, _, _ in shown)
           + "<th class=n>用了工具<br>Used tools</th></tr>"]
    for m, s in sorted(usum.items(), key=lambda kv: (-(kv[1].get("vision") or 0), kv[0])):
        out.append(f"<tr><td>{e(label(m))}</td>" + "".join(f"<td class=n>{fmt(f(s), d)}</td>" for _, f, d in shown)
                   + f"<td class=n>{s['contaminated']}</td></tr>")
    out.append("</table></div><p class=muted>视觉增益 = 有图得分 − 无图得分（按题目和重复配对，单位为百分点）。"
               "用了工具：违反要求调用了工具的回答，不计分。<span class=en> Visual gain is the matched with-image minus "
               "no-image score, in percentage points. Used tools: answers that called a tool despite instructions; "
               "they are excluded.</span></p>")
    return "\n".join(out)


def _field_heatmap(usum: dict, label) -> str:
    """Answer-key diagnostics for suites with family labels: joint accuracies and per-field means."""
    rows = {m: s for m, s in usum.items() if s.get("fields")}
    if not any(s.get("family_classes") for s in rows.values()):
        return ""
    fields = list(dict.fromkeys(f for s in rows.values() for f in s["fields"]))
    full = max(n for s in rows.values() for n in s["field_items"].values())
    labels = max(len(s["family_classes"]) for s in rows.values())
    order = sorted(rows, key=lambda m: (-(rows[m]["joint"] or 0), m))
    out = ["<h3>逐项诊断 <span class=en>Answer-key diagnostics</span></h3><div class='scroll card-table'><table>"
           "<tr><th>模型 Model</th><th class=n>全对<br>Joint</th><th class=n>视觉全对<br>Visual joint</th>"
           "<th class=n>类别宏平均<br>Family macro</th>"
           + "".join(f"<th class=n>{e(FIELD_ZH.get(f, f))}<br>{e(f)}</th>" for f in fields) + "</tr>"]
    for m in order:
        s = rows[m]
        classes = f" <small>({len(s['family_classes'])})</small>" if len(s["family_classes"]) < labels else ""
        out.append(f"<tr><td>{e(label(m))}</td>{_heat(s['joint'])}{_heat(s['visual_joint'])}"
                   f"{_heat(s['family_macro'], note=classes)}"
                   + "".join(_heat(s["fields"].get(f), note=f" <small>({s['field_items'][f]})</small>"
                                   if s["field_items"].get(f, 0) < full else "") for f in fields) + "</tr>")
    out.append(f"</table></div><p class=muted>0–100，每张图权重相同。全对：七项全部正确；视觉全对：除类别外全部正确；"
               f"类别宏平均：各类别召回率的等权平均；括号内为不足 {full} 张图或 {labels} 个类别时的实际覆盖。{HEAT_NOTE}"
               "<span class=en> 0–100, equal weight per image. Joint: every field correct; visual joint: every field "
               "except family; family macro: equal-weight recall over the expected family labels. Parentheses show "
               f"item or label coverage when below {full} items or {labels} labels.</span></p>")
    categories = sorted({c for s in rows.values() for c in s.get("categories", {})}, key=_category_order)
    if categories:
        out.append("<div class='scroll card-table'><table><tr><th>模型 Model</th>"
                   + "".join(f"<th class=n>{e(CATEGORY.get(c, (c, c))[0])}<br>{e(CATEGORY.get(c, (c, c))[1])}</th>"
                             for c in categories) + "</tr>")
        for m in order:
            out.append(f"<tr><td>{e(label(m))}</td>"
                       + "".join(_heat(rows[m]["categories"].get(c)) for c in categories) + "</tr>")
        out.append("</table></div><p class=muted>按图片类别的部分得分均值（每项字段等分）。<span class=en> Partial-credit "
                   "means by slice (equal credit per field).</span></p>")
    return "\n".join(out)


def _category_order(category: str) -> tuple[int, str]:
    return (list(CATEGORY).index(category) if category in CATEGORY else len(CATEGORY), category)


def _reply(answer: str) -> dict:
    try:
        return extract_json(answer)
    except ValueError:
        return {}


def _casebook(items: list[UnderstandingItem], samples: list[dict], order: list[str], label, asset) -> str:
    """One card per answer-keyed image: the image, its key, a verdict strip, and each model's misses."""
    first = {}  # (item, model) -> the first repetition, as in the galleries
    for s in sorted(samples, key=lambda s: s["rep"]):
        first.setdefault((s["item"], s["model"]), s)
    rank = {m: i for i, m in enumerate(order)}
    groups = defaultdict(list)
    for item in items:
        groups[item.category].append(item)
    out = []
    for group in sorted(groups, key=_category_order):
        zh, en = CATEGORY.get(group, (group, group))
        out.append((f"<div class=group><h3>{e(zh)} <span class=en>{e(en)}</span></h3>"
                    f"<span class=muted>{len(groups[group])} 张 images</span></div>" if group else "")
                   + "<div class=cases>" + "".join(_case(item, first, rank, label, asset) for item in groups[group])
                   + "</div>")
    return "\n".join(out)


def _case(item: UnderstandingItem, first: dict, rank: dict, label, asset) -> str:
    """A casebook card; `first` maps (item id, model) to the sample shown for that model."""
    models = sorted({m for (i, m) in first if i == item.id}, key=lambda m: (rank.get(m, len(rank)), m))
    image = asset(item.images[0])
    case = item.id.split(".", 1)[1]
    title = item.title or case
    chips = "".join(f"<span class=chip title='{e(FIELD_ZH.get(f, f))}'><small>{e(f)}</small>{e(v)}</span>"
                    for f, v in item.answers.items())
    segs, who, raw, n_ok = [], [], [], 0
    for m in models:
        s = first[(item.id, m)]
        reply = _reply(s["answer"])
        right = sum(v == 100 for v in s["fields"].values())
        ok = right == len(s["fields"])
        n_ok += ok
        segs.append(f"<i class='seg{' ok' if ok else ''}' title='{e(label(m))}: {right}/{len(s['fields'])}'></i>")
        if ok:
            misses = ""
        elif not reply:
            misses = "<span class=miss>无法解析 unparseable</span>"
        else:
            misses = "".join(f"<span class=miss>{e(f)} <code>{e(str(reply.get(f, '–')))}</code></span>"
                             for f, v in s["fields"].items() if v != 100)
        mark = "<span class=mark-ok>✓</span>" if ok else "<span class=mark-no>✗</span>"
        who.append(f"<li>{mark} <b>{e(label(m))}</b> <span class=muted>{right}/{len(s['fields'])}</span><br>{misses}</li>")
        blind = first.get((f"{item.id}.blind", m))
        raw.append(f"<b>{e(label(m))}</b><div class=raw>{e(s['answer'])}</div>"
                   + (f"<span class=muted>无图对照 No image</span><div class=raw>{e(blind['answer'])}</div>"
                      if blind else ""))
    # Models that only answered the no-image control (text-only models, failed visual cells) get no verdict,
    # but their replies still count toward the No image score, so show them.
    for m in sorted({m for (i, m) in first if i == f"{item.id}.blind"} - set(models),
                    key=lambda m: (rank.get(m, len(rank)), m)):
        raw.append(f"<b>{e(label(m))}</b> <span class=muted>无图对照 No image</span>"
                   f"<div class=raw>{e(first[(f'{item.id}.blind', m)]['answer'])}</div>")
    note = f"<p class=muted>{e(item.image_note)}</p>" if item.image_note else ""
    return (
        f"<article class=case id='case-{e(case)}'><a href='{e(image)}'><img loading=lazy src='{e(image)}' "
        f"alt='{e(title)}'></a><div><div class=case-title>{e(title)} <span>{e(case)}</span></div>"
        f"<div class=chips>{chips}</div><div class=verdict><span class=segs>{''.join(segs)}</span>"
        f"<b>{n_ok}/{len(models)}</b><span class=muted>全对 all correct</span></div>"
        f"<details><summary>逐模型 Per model</summary>{note}<ul class=who>{''.join(who)}</ul>"
        f"<details><summary>原始回答 Raw replies</summary>{''.join(raw)}</details></details></div></article>")


def build(bench: Bench, models: dict[str, ModelSpec], run_dir: Path, scores: dict, out: Path,
          repo_url: str | None = None, suite_tabs: bool = False) -> Path:
    (out / "images").mkdir(parents=True, exist_ok=True)
    text = SUITE_TEXT[bench.suite]
    copied: dict[Path, str] = {}

    def asset(src: Path) -> str:
        """Copy a benchmark image once per build, keyed by its path below bench/ so names never collide."""
        if src not in copied:
            stem = src.relative_to(bench.root / "bench").with_suffix("").as_posix()
            copied[src] = _copy_image(src, out, f"images/bench/{stem}")
        return copied[src]

    def generated(s: dict) -> str | None:
        if not s["images"]:
            return None
        stem = "images/" + Path(s["target"]).with_suffix("").as_posix().removeprefix("imagegen/")
        return _copy_image(run_dir / s["images"][0], out, stem)

    img_samples = scores["samples"]["imagegen"]
    und_samples = scores["samples"]["understanding"]
    meta_of = {s["target"]: _record(run_dir, s["target"]).get("meta", {}) for s in img_samples + und_samples}

    def label(m: str) -> str:
        return models[m].label if m in models else m

    boards = scores.get("leaderboards", {})
    vision_order = [r["model"] for r in boards.get("visual_understanding", [])]
    # An image item is shown when it or its no-image control has a sample.
    sampled = {s.get("control_for") or s["item"] for s in und_samples}
    keyed = [i for i in bench.items if i.modality == "vision" and i.answers and i.id in sampled]
    state_keyed = [i for i in bench.state_items if i.modality == "vision" and i.id in sampled]
    core_tiers = [t for t in bench.tiers.values() if any(t.id == s["tier"] for s in img_samples)]
    state_samples = [s for s in img_samples if s["state"]]
    sections = ["rankings"] + (["casebook", "gallery"] if text["casebook_first"] else ["gallery", "casebook"])
    sections += ["states", "understanding", "models", "judges"]
    present = {"rankings": True, "casebook": bool(keyed), "gallery": bool(core_tiers), "states": bool(state_samples),
               "understanding": bool(und_samples), "models": True, "judges": bool(scores.get("judge_health"))}
    nav_text = {"rankings": "排名 Rankings", "casebook": "图鉴 Casebook", "gallery": "图像 Images",
                "states": "姿势迁移 Transfer", "understanding": "理解 Understanding", "models": "模型 Models",
                "judges": "评审 Judges"}

    revision = _revision(bench.root)
    # Link the documentation of the exact commit the results were built from.
    blob = f"{repo_url}/blob/{revision.split()[0]}" if repo_url and revision else None
    html = [f"<!doctype html><html lang=zh><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(text['title'][0])} · {e(text['title'][1])}</title><style>{CSS}</style>"]
    tabs = ("<div class=tabs>" + "".join(
        f"<a href='{_suite_href(bench.suite, s)}'{' aria-current=page' if s == bench.suite else ''}>"
        f"{e(SUITE_TEXT[s]['tab'][0])} {e(SUITE_TEXT[s]['tab'][1])}</a>" for s in SUITES) + "</div>"
            if suite_tabs else "")
    links = "".join(f"<a href='#{s}'>{nav_text[s]}</a>" for s in sections if present[s])
    links += f"<a href='{e(blob, quote=True)}/docs/methodology.md'>方法 Methodology</a>" if blob else ""
    home = _suite_href(bench.suite, "core") if suite_tabs else "#"
    html.append(f"<header class=top><div><a class=brand href='{home}'>奶蛙bench</a>{tabs}"
                f"<nav class=sections>{links}</nav></div></header><main>")

    # --- hero ---
    stamp = f"suite <code>{e(bench.suite)}</code> · run <code>{e(run_dir.name)}</code> · {datetime.date.today().isoformat()}"
    stamp += f" · revision <code>{e(revision)}</code>" if revision else ""
    mosaic = bool(keyed) and text["casebook_first"]
    portrait = "" if mosaic else f"<img src='{e(asset(bench.reference_image))}' alt='大笑奶龙'>"
    html.append(f"<div class='hero{' solo' if mosaic else ''}'>{portrait}<div>"
                f"<h1>{e(text['title'][0])} <span class=en>{e(text['title'][1])}</span></h1>"
                f"<p class=lede>{e(text['intro'][0])}<br><span class=en>{e(text['intro'][1])}</span></p>"
                f"<span class=badge>第一版 · First draft</span> <span class=muted>{stamp}</span></div></div>")
    if mosaic:
        html.append("<div class=mosaic>" + "".join(
            f"<a href='#case-{e(i.id.split('.', 1)[1])}' title='{e(i.title)}'>"
            f"<img src='{e(asset(i.images[0]))}' alt='{e(i.title)}'></a>" for i in keyed) + "</div>")
    annotated = (f"答案键由 {e(label(bench.annotator))} 标注，尚未经人工校准；它在本页的得分只反映与自身标注的一致程度。"
                 if bench.annotator else "")
    annotated_en = (f" Answer keys are provisional {e(label(bench.annotator))} annotations without human calibration; "
                    "its own score measures agreement with its labels." if bench.annotator else "")
    html.append(
        "<div class=note><b>第一版结果。</b>"
        f"共 {len(img_samples)} 个生成样本、{len(und_samples)} 条回答。自由回答与标准图像生成由 LLM 评审，结构化回答按答案键本地计分；"
        f"{annotated}几分的差距可能只是偶然，排名未做统计检验。只有完整跑完固定题组的模型才有名次。<br><span class=en>"
        f"First-draft results: {len(img_samples)} generation samples and {len(und_samples)} answers. "
        f"Free-form answers and standard generation use LLM judges; structured answers use local keys.{annotated_en} "
        "Gaps of a few points can be noise; ranks are not statistically "
        "tested. Only models that complete the fixed panel are ranked.</span></div>")

    body = {}
    # --- rankings ---
    panel_animals = bench.select_animals("default")
    vision_items = [i for i in bench.items if i.modality == "vision"]
    grounding = sum(1 for i in vision_items if i.answers)
    flags = ({bench.annotator: "<br><span class=flag>答案键标注者 Key annotator</span>"}
             if bench.annotator else {})
    joint = ("七项全部答对才得分。<span class=en> All seven fields must be correct for a sample to score.</span>"
             if bench.suite == "naihub-v1" else "")
    imagegen_rows = boards.get("imagegen", [])
    imagegen_panel = (
        "<div class=panel><h3>图像生成 <span class=en>Image generation ranking</span></h3>"
        f"<p class=muted>固定题组：{len(panel_animals)} 种动物 × {len(bench.tiers)} 档提示词；只计入核实为原样传递的提示词，"
        "服务商拒绝生成记 0 分。<br><span class=en>Fixed panel: "
        f"{len(panel_animals)} animals × {len(bench.tiers)} prompt tiers; verified verbatim prompts only. "
        "Provider refusals score 0.</span></p>" + _ranking(imagegen_rows, label, {}) + "</div>"
        if imagegen_rows else "")
    scope = ("两个排名相互独立，不合成总分。<span class=en> Two independent rankings, no combined score.</span> "
             if imagegen_rows else "本次运行没有标准图像生成题组的结果；下方的姿势迁移图不计分。"
             "<span class=en> This run has no standard image-generation panel results; transfer images below "
             "are unscored.</span> ")
    body["rankings"] = (
        "<h2 id=rankings>排名 <span class=en>Rankings</span></h2><div class=panels><div class=panel>"
        "<h3>视觉理解 <span class=en>Visual understanding ranking</span></h3>"
        f"<p class=muted>固定题组：{len(vision_items)} 道看图题（{len(vision_items) - grounding} 道自由回答识别、"
        f"{grounding} 道按答案键计分的视觉核对）。文字知识与无图对照只作诊断。{joint}<br><span class=en>Fixed panel: "
        f"{len(vision_items)} image-input tasks ({len(vision_items) - grounding} free-form recognition, {grounding} "
        "answer-keyed grounding checks). Text knowledge and no-image controls are diagnostics.</span></p>"
        + _ranking(boards.get("visual_understanding", []), label, flags) + "</div>" + imagegen_panel
        + f"</div><p class=muted>{scope}有缺失、失败、未评分或不合格格子的模型不参与排名；×N 为每格重复次数。"
        "<span class=en> Missing, failed, unjudged, or ineligible cells leave a model unranked; ×N is "
        "repetitions per cell.</span></p>")

    # --- casebook ---
    if keyed:
        body["casebook"] = (
            "<h2 id=casebook>看图图鉴 <span class=en>Casebook</span></h2>"
            "<p>每张图都问同一个问题，要求按固定标签返回 JSON，再在本地与答案键逐项比对。色条每格代表一个模型"
            "（按视觉理解排名排序）：绿色为全部答对，红色为至少错一项。展开卡片可看每个模型错在哪里，以及原始回答。"
            "<br><span class=en>Every image gets the same question, answered as JSON with fixed labels and compared "
            "field by field with a local key. Each strip segment is one model, in visual-ranking order: green means "
            "every field is right, red means at least one miss. Open a card for each model's misses and raw "
            "replies.</span></p>" + _casebook(keyed, und_samples, vision_order, label, asset))

    # --- image generation ---
    summary = scores["imagegen"]
    by_cell = {(s["model"], s["animal"], s["tier"]): s for s in sorted(img_samples, key=lambda s: -s["rep"])}
    img_models = sorted({s["model"] for s in img_samples}, key=lambda m: (-(summary.get(m, {}).get("overall") or 0), m))
    if core_tiers:
        part = ["<h2 id=gallery>图像生成 <span class=en>Image generation</span></h2>"
                "<p>让模型画“⟨动物⟩版的大笑奶龙”，提示词分五档。评审对照原图，按 9 项加权视觉特征打分，"
                "再乘以能否认出目标动物（0–100）。<br><span class=en>Models draw an animal version of the meme from five "
                "prompt tiers. Judges compare each image with the reference on nine weighted visual traits, "
                "scaled by whether the target animal is recognizable (0–100).</span></p>",
                "<details><summary>提示词 · Prompts</summary><table><tr><th>档位 Tier</th><th>提示词（以猫为例）"
                " Prompt (cat)</th></tr>"]
        cat = bench.animals.get("cat") or next(iter(bench.animals.values()))
        for t in core_tiers:
            extra = "（附原图 + reference image）" if t.reference else ""
            part.append(f"<tr><td><b>{e(t.title_zh)}</b><br><span class=muted>{e(t.title_en)} · {e(t.id)}</span></td>"
                        f"<td class=ans>{e(t.render(cat))}{extra}</td></tr>")
        part.append("</table></details>")
        for a in [a for a in bench.animals if any(s["animal"] == a and not s["state"] for s in img_samples)]:
            animal = bench.animals[a]
            part.append(f"<h3>{e(animal.zh)} <span class=en>{e(animal.en)}</span></h3><div class='scroll card-table'>"
                        "<table class=gallery><tr><th style='width:150px'></th>"
                        + "".join(f"<th>{e(t.title_zh)}<br><span class=en>{e(t.title_en)}</span></th>" for t in core_tiers)
                        + "</tr>")
            for m in img_models:
                cells = []
                for t in core_tiers:
                    s = by_cell.get((m, a, t.id))
                    cells.append(_image_cell(s, s and generated(s), f"{label(m)} {t.id} {a}",
                                             meta=s and meta_of[s["target"]]))
                part.append(f"<tr><td><b>{e(label(m))}</b></td>{''.join(cells)}</tr>")
            part.append("</table></div>")
        part.append("<h3>诊断汇总 <span class=en>Diagnostics</span></h3><div class='scroll card-table'><table><tr><th>模型 Model</th>"
                    "<th class=n>已有格子均分<br>Available-cell mean</th>"
                    + "".join(f"<th class=n>{e(t.title_zh)}</th>" for t in core_tiers)
                    + "<th class=n>知识比率<br>Knowledge ratio</th></tr>")
        for m in img_models:
            if m not in summary:
                continue
            s = summary[m]
            part.append(f"<tr><td>{e(label(m))}</td>{_heat(s['overall'])}"
                        + "".join(_heat(s["tiers"].get(t.id, {}).get("overall")) for t in core_tiers)
                        + f"<td class=n>{fmt(s['knowledge_ratio'], 2)}</td></tr>")
        part.append("</table></div><p class=muted>知识比率 = 两个“只给梗名”档的均分 ÷ “详细描述”档的均分，只比较三档都有结果的相同动物；"
                    "它反映对提示词详细程度的敏感度，不是“认识这个梗”的概率。诊断均分可能与固定排名题组不同。"
                    "<span class=en> Knowledge ratio = mean of both name tiers ÷ detailed-description tier, on "
                    "matched animals only. It is prompt sensitivity, not a calibrated probability of knowledge. "
                    "Diagnostic means may differ from the fixed ranking panel.</span> " + HEAT_NOTE + "</p>")
        body["gallery"] = "\n".join(part)

    # --- optional state transfer ---
    if state_samples:
        part = ["<h2 id=states>姿势迁移（可选，不计分）<span class=en>Optional state transfer · unscored</span></h2>"
                "<p>把奶蛙源图的可见表情、动作和姿势迁移到别的动物身上。每张源图有两种条件："
                "只给固定的文字描述，或附上源图。这部分不由 LLM 评分，也不计入排名，请对照源图分别查看表情、动作、"
                "动物辨识度和渲染风格。<br><span class=en>Visible expressions, gestures, and postures from 奶蛙 source "
                "images are transferred to other animals, either from a fixed text description or from the attached "
                "source image. These images receive no LLM grades and do not enter either ranking; compare expression, "
                "gesture, animal identity, and render style with the source by eye.</span></p>"]
        state_tiers = defaultdict(dict)
        for t in bench.state_tiers.values():
            if any(s["tier"] == t.id for s in state_samples):
                state_tiers[t.state]["reference" if t.reference else "described"] = t
        state_animals = [a for a in bench.animals if any(s["animal"] == a for s in state_samples)]
        state_models = sorted({s["model"] for s in state_samples})
        cat = bench.animals.get("cat") or next(iter(bench.animals.values()))
        for state, conditions in state_tiers.items():
            any_tier = next(iter(conditions.values()))
            source = asset(any_tier.reference_image)
            title_zh, title_en = any_tier.title_zh.split(" · ")[0], any_tier.title_en.split(" · ")[0]
            columns = [(a, c, conditions[c]) for a in state_animals for c in CONDITION if c in conditions]
            rows = []
            for m in state_models:
                cells = []
                for a, _, t in columns:
                    s = by_cell.get((m, a, t.id))
                    cells.append(_image_cell(s, s and generated(s), f"{label(m)} {t.id} {a}", scored=False,
                                             meta=s and meta_of[s["target"]]))
                rows.append(f"<tr><td><b>{e(label(m))}</b></td>{''.join(cells)}</tr>")
            prompts = "".join(f"<tr><td style='width:120px'><b>{CONDITION[c][0]}</b><br><span class=muted>"
                              f"{CONDITION[c][1]}</span></td><td class=ans>{e(t.render(cat))}</td></tr>"
                              for c, t in conditions.items())
            part.append(
                f"<div class=state id='state-{e(state)}'><figure><a href='{e(source)}'><img src='{e(source)}' "
                f"alt='Source: {e(state)}'></a><figcaption>{e(title_zh)} <span class=en>{e(title_en)}</span>"
                f"</figcaption><span class=muted>源图 Source</span></figure><div style='min-width:0'>"
                "<div class=scroll><table class=gallery><tr><th style='width:130px'></th>"
                + "".join(f"<th>{e(bench.animals[a].zh)} · {CONDITION[c][0]}<br><span class=en>"
                          f"{e(bench.animals[a].en)} · {CONDITION[c][1]}</span></th>" for a, c, _ in columns)
                + f"</tr>{''.join(rows)}</table></div><details><summary>提示词 · Prompts</summary><table>{prompts}"
                "</table></details></div></div>")
        body["states"] = "\n".join(part)

    # --- understanding ---
    if und_samples:
        part = ["<h2 id=understanding>理解诊断 <span class=en>Understanding diagnostics</span></h2>"
                "<p>不允许联网或使用工具。自由回答的识别题和文字题对照有出处的事实，由评审团打分，每条言之凿凿的幻觉扣 10 分；"
                "视觉核对题按答案键在本地计分。<br><span class=en>No web or tools. Recognition and text answers are "
                "scored by the judge panel against sourced facts, with 10 points off per confident hallucination; "
                "structured checks use local answer keys.</span></p>"]
        for states in (False, True):
            selected = [s for s in und_samples if bool(s.get("state")) == states]
            if not selected:
                continue
            usum = scores.get("state_understanding" if states else "understanding", {})
            if states:
                part.append("<h3>表情状态提取（可选，按答案键计分）<span class=en>Optional state extraction · answer-keyed"
                            "</span></h3><p class=muted>同一提问分别在有图和无图时作答，按所选题组的类别与可见特征答案键计分；"
                            "不影响任何排名。<span class=en> The same question with and without the source image, "
                            "scored against the selected suite's answer keys. Not part of either "
                            "ranking.</span></p>")
            part.append(_summary_table(usum, label))
            part.append(_field_heatmap(usum, label))
            if states:
                part.append("<div style='margin-top:14px'></div>"
                            + _casebook(state_keyed, selected, vision_order, label, asset))
                continue
            by_item = defaultdict(list)
            for s in selected:
                by_item[s["item"]].append(s)
            free = [i for i in bench.items if i.id in by_item and not i.answers]
            if free:
                part.append("<h3>自由回答 <span class=en>Free-form answers</span></h3>")
            for item in free:
                shown = "".join(f"<img src='{e(asset(p))}' style='max-width:140px;border-radius:8px' alt=''>"
                                for p in item.images)
                part.append(f"<details><summary>{e(item.id)} · {e(item.prompt[:60])}</summary>{shown}"
                            f"<p class=muted>{e(item.prompt)}</p><table>")
                for s in sorted(by_item[item.id], key=lambda s: (-(s["score"] or 0), s["model"])):
                    bad = "".join(f"<div class=tag>✗ {e(h)}</div>" for h in s["hallucinations"][:3])
                    part.append(f"<tr><td style='width:150px'><b>{e(label(s['model']))}</b><br><span class=score>"
                                f"{fmt(s['score'])}</span></td><td class=ans>{e(s['answer'])}{bad}</td></tr>")
                part.append("</table></details>")
        body["understanding"] = "\n".join(part)

    # --- models ---
    roles = defaultdict(set)
    for s in img_samples:
        roles[s["model"]].add("图像生成 Image generation")
    for s in und_samples:
        roles[s["model"]].add("理解 Understanding")
    for j in scores["judges"]:
        roles[j].add("评审 Judge")
    if bench.annotator:
        roles[bench.annotator].add("答案键标注 Key annotator")
    first_meta = {}
    for s in img_samples + und_samples:
        first_meta.setdefault(s["model"], meta_of[s["target"]])
    part = ["<h2 id=models>参测模型 <span class=en>Models</span></h2><div class='scroll card-table'><table><tr><th>模型 Model</th>"
            "<th>角色 Role</th><th>调用方式 Access</th><th>图像来源凭证 C2PA provenance</th></tr>"]
    for m in sorted(roles, key=lambda m: (min(roles[m]), m)):
        meta = first_meta.get(m, {})
        c2pa = _c2pa(meta) if any("Image" in r for r in roles[m]) else "–"
        part.append(f"<tr><td><b>{e(label(m))}</b><br><span class=muted>{e(m)}</span></td>"
                    f"<td>{'<br>'.join(sorted(roles[m]))}</td><td>{_access(models.get(m), meta)}</td><td>{c2pa}</td></tr>")
    part.append("</table></div><p class=muted>图片内嵌的 C2PA 内容凭证声明的生成器：OpenAI 标注为 "
                "<code>ChatGPT · gpt-image</code>，Google 只标注“由 Google 生成式 AI 创建”并加有 SynthID 水印，"
                "两家都未公开更细的版本号。图像生成由 Agent 中转：上表“调用方式”中的模型负责把提示词原样交给图像工具，"
                "内容凭证仅供参考，未验证签名；逐字核对的结果列于图片下方。<br><span class=en>Vendor-declared generators are read from each image's C2PA "
                "content credentials, which name only “ChatGPT · gpt-image” (OpenAI) and “Created by Google Generative AI” "
                "(Google); neither exposes a more specific image model version. Signatures are not verified. "
                "The listed relay model forwards prompts to the image tool; audit results appear under each image.</span></p>")
    body["models"] = "\n".join(part)

    # --- judges ---
    if present["judges"]:
        part = ["<h2 id=judges>评审 <span class=en>Judges</span></h2><p>每个样本由其他厂商的评审打分后取平均；没有独立评审时使用现有评审。"
                "下表是评审的健康度：分数离散度太低说明评审分不出好坏，与其他评审差距太大说明意见不一致。<br>"
                "<span class=en>Each sample is averaged over judges from other vendors, falling back to the available "
                "panel when none are independent. Spread: how much a judge's scores vary; distance: how far it sits "
                "from the other judges.</span></p><div class='scroll card-table'><table>"
                "<tr><th>评审 Judge</th><th>部分 Track</th><th class=n>样本 Samples</th><th class=n>离散度 Spread</th>"
                "<th class=n>与其他评审差距 Distance</th></tr>"]
        for j, tracks in scores["judge_health"].items():
            for track, h in tracks.items():
                part.append(f"<tr><td>{e(label(j))}</td><td>{e(track)}</td><td class=n>{h['n']}</td>"
                            f"<td class=n>{fmt(h['spread'], 1)}</td><td class=n>{fmt(h['deviation'], 1)}</td></tr>")
        part.append("</table></div>")
        body["judges"] = "\n".join(part)

    html += [body[s] for s in sections if s in body]
    repo = f" · <a href='{e(repo_url, quote=True)}'>源代码 Source</a>" if repo_url else ""
    sources = (f"<a href='{e(blob, quote=True)}/bench/reference/SOURCE.md'>SOURCE.md</a>" if blob
               else "bench/reference/SOURCE.md")
    html.append(f"<footer>奶蛙bench · nai-wai-bench{repo} · 参考图、表情包、二创与官方形象图的出处见 {sources}，"
                "仅供非商业研究使用。<span class=en> Sources of the reference image, stickers, remixes, and official "
                "artwork are listed in SOURCE.md. For non-commercial research use.</span></footer></main></html>")
    index = out / "index.html"
    index.write_text("\n".join(html), encoding="utf-8")
    return index

"""Static, bilingual (中文 / English) results site for a run: one index.html plus resized images,
ready to publish with GitHub Pages."""

import datetime
import shutil
import subprocess
from collections import defaultdict
from html import escape as e
from pathlib import Path

from nwb.config import Bench, ModelSpec
from nwb.report import fmt
from nwb.util import read_json

FAILURE_ZH = {"generic_cute": "泛泛的可爱风", "realistic_animal": "写实动物", "plain_nailong": "只是奶龙本体",
              "text_or_watermark": "带文字或水印", "multiple_subjects": "多主体或场景杂乱"}
ACCESS = {"codex": "Codex CLI", "claude": "Claude Code", "acp": "ACP agent", "openai": "API"}
STATUS = {"complete": "完整 complete", "incomplete": "不完整 incomplete",
          "incomplete repetitions": "重复次数不齐 incomplete repetitions"}
CONDITION = {"described": ("文字描述", "description"), "reference": ("参考图", "reference image")}
IMAGE_WIDTH = 768

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1b16;--muted:#6b665b;--line:#e4e0d6;--card:#fff;--accent:#c58a00;--bad:#b4261e;--good:#1a7f37}
@media (prefers-color-scheme:dark){:root{--bg:#14130f;--fg:#ece8df;--muted:#a39d90;--line:#2e2b24;--card:#1c1a15;--accent:#f0b429;--bad:#f2777a;--good:#57c46f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1120px;margin:auto;padding:32px 20px 64px}h1{font-size:30px;margin:0}h2{font-size:21px;margin:44px 0 6px}
h3{font-size:16px;margin:24px 0 8px}.en{color:var(--muted);font-weight:400}.muted{color:var(--muted);font-size:13px}
.hero{display:flex;gap:24px;align-items:center;flex-wrap:wrap}.hero img{width:150px;border-radius:14px}
.hero>div{flex:1;min-width:280px}
.badge{display:inline-block;background:var(--accent);color:#1d1b16;border-radius:99px;padding:1px 10px;font-size:12px;font-weight:600}
.note{border:1px solid var(--line);border-left:4px solid var(--accent);background:var(--card);border-radius:10px;padding:10px 14px;margin:18px 0}
table{border-collapse:collapse;width:100%;background:var(--card);border-radius:10px;overflow:hidden;margin:8px 0 14px}
th,td{border-bottom:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top;font-size:14px}
th{font-size:12.5px;color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
.gallery{table-layout:fixed;min-width:800px}.gallery td{text-align:center}.gallery img{width:100%;max-width:200px;aspect-ratio:1;object-fit:contain;border-radius:10px;display:block;margin:0 auto 4px}
.score{font-size:19px;font-weight:700}.bad{color:var(--bad)}.tag{font-size:11.5px;color:var(--bad)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0}
summary{cursor:pointer;font-weight:600}.ans{white-space:pre-wrap;font-size:13px}code{font-size:12.5px}
.scroll{overflow-x:auto}footer{margin-top:48px;color:var(--muted);font-size:13px}
nav{margin:18px 0;font-size:14px}nav a{color:inherit;margin-right:14px}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle;margin-left:8px}
.refused{display:flex;align-items:center;justify-content:center;aspect-ratio:1;max-width:200px;margin:0 auto 4px;
border:1px dashed var(--line);border-radius:10px;color:var(--bad);font-size:13px}
.source{width:120px;height:120px;object-fit:contain;border-radius:10px;vertical-align:middle;margin-right:12px}
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


def _ranking(rows: list[dict], label) -> str:
    out = ["<div class=scroll><table><tr><th>名次 Rank</th><th>模型 Model</th><th>得分 Score</th>"
           "<th>已计分 Scored cells</th><th>每格重复 Reps/cell</th><th>状态 Status</th></tr>"]
    for row in rows:
        rank = row["rank"] if row["rank"] is not None else "–"
        bar = f"<span class=bar style='width:{row['score']:.0f}px'></span>" if row["score"] is not None else ""
        out.append(f"<tr><td class=n>{rank}</td><td><b>{e(label(row['model']))}</b></td>"
                   f"<td class=n><b>{fmt(row['score'], 1)}</b>{bar}</td>"
                   f"<td class=n>{row['completed']}/{row['required']}</td><td class=n>{row['repetitions']}</td>"
                   f"<td>{e(STATUS.get(row['status'], row['status']))}</td></tr>")
    return "\n".join(out) + "</table></div>"


def _image_cell(s: dict | None, run_dir: Path, out: Path, alt: str, scored: bool = True) -> str:
    """A gallery cell: the image (or the provider's refusal), its score when scored, and its prompt audit."""
    if not s:
        return "<td>–</td>"
    audit = {True: "原样传递 · Verbatim", False: "提示词有改动 · Prompt changed", None: "未核实 · Unverified"}[s["verbatim"]]
    score = f"<span class=score>{fmt(s['overall'])}</span>" if scored else ""
    if not s["images"]:
        return f"<td><div class=refused>服务商拒绝生成<br>Refused by provider</div>{score}<div class=muted>{audit}</div></td>"
    stem = "images/" + Path(s["target"]).with_suffix("").as_posix().removeprefix("imagegen/")
    dst = _copy_image(run_dir / s["images"][0], out, stem)
    why = " | ".join(f"{j}: {r}" for j, r in s["rationales"].items())
    tags = "".join(f"<div class=tag>{e(FAILURE_ZH.get(f, f))}</div>" for f in s["failure_modes"])
    return (f"<td title='{e(why, quote=True)}'><a href='{e(dst)}'><img loading=lazy src='{e(dst)}' alt='{e(alt)}'></a>"
            f"{score}{tags}<div class=muted>{audit}</div></td>")


def build(bench: Bench, models: dict[str, ModelSpec], run_dir: Path, scores: dict, out: Path,
          repo_url: str | None = None) -> Path:
    (out / "images").mkdir(parents=True, exist_ok=True)
    shutil.copy2(bench.reference_image, out / "images" / bench.reference_image.name)

    img_samples = scores["samples"]["imagegen"]
    und_samples = scores["samples"]["understanding"]
    meta_of = {s["target"]: _record(run_dir, s["target"]).get("meta", {}) for s in img_samples + und_samples}

    def label(m: str) -> str:
        return models[m].label if m in models else m

    html = [f"<!doctype html><html lang=zh><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>奶蛙bench · nai-wai-bench</title><style>{CSS}</style><main>"]
    revision = _revision(bench.root)
    # Link the documentation of the exact commit the results were built from.
    blob = f"{repo_url}/blob/{revision.split()[0]}" if repo_url and revision else None
    stamp = f"run <code>{e(run_dir.name)}</code> · {datetime.date.today().isoformat()}"
    stamp += f" · revision <code>{e(revision)}</code>" if revision else ""
    html.append(
        f"<div class=hero><img src='images/{e(bench.reference_image.name)}' alt='大笑奶龙'><div>"
        "<h1>奶蛙bench <span class=en>nai-wai-bench</span></h1>"
        "<p>测试 AI 模型对中文网络梗“大笑奶龙”（又称“奶蛙”）的掌握：能否从图片中认出它和它的变体，"
        "以及能否按它的 3D 风格把它画成别的动物。<br><span class=en>How well do AI models know the Chinese meme "
        "大笑奶龙 (Laughing Nailong, also called 奶蛙)? Can they recognize it and its variants in images, and "
        "draw other animals in its 3D style?</span></p>"
        f"<span class=badge>第一版 · First draft</span> <span class=muted>{stamp}</span></div></div>")
    html.append(
        "<div class=note><b>第一版结果。</b>"
        f"共 {len(img_samples)} 张图片、{len(und_samples)} 条回答。每格只跑 1 次，由多家厂商的 LLM 评审打分；"
        "几分的差距可能只是偶然，排名未做统计检验。只有完整跑完固定题组的模型才有名次。<br><span class=en>"
        f"First-draft results: {len(img_samples)} images and {len(und_samples)} answers, one repetition per cell, "
        "scored by a multi-vendor LLM judge panel. Gaps of a few points can be noise; ranks are not statistically "
        "tested. Only models that complete the fixed panel are ranked.</span></div>")

    core_tiers = [t for t in bench.tiers.values() if any(t.id == s["tier"] for s in img_samples)]
    state_samples = [s for s in img_samples if s["state"]]
    state_und = any(s.get("state") for s in und_samples)
    nav = [("imagegen-ranking", "图像生成排名 Image generation"), ("vision-ranking", "视觉理解排名 Visual understanding"),
           ("models", "模型 Models")]
    nav += [("gallery", "图像 Images")] if core_tiers else []
    nav += [("states", "表情迁移 State transfer")] if state_samples else []
    nav += [("understanding", "理解 Understanding")] if und_samples else []
    nav += [("judges", "评审 Judges")]
    html.append("<nav>" + "".join(f"<a href='#{a}'>{t}</a>" for a, t in nav)
                + (f"<a href='{e(blob, quote=True)}/docs/methodology.md'>方法 Methodology</a>" if blob else "") + "</nav>")

    boards = scores.get("leaderboards", {})
    panel_animals = bench.select_animals("default")
    vision_items = [i for i in bench.items if i.modality == "vision"]
    grounding = sum(1 for i in vision_items if i.answers)
    html.append("<h2 id=imagegen-ranking>图像生成排名 <span class=en>Image generation ranking</span></h2>"
                f"<p class=muted>固定题组：{len(panel_animals)} 种动物 × {len(bench.tiers)} 档提示词；只计入核实为原样传递的提示词，"
                "服务商拒绝生成记 0 分。<br><span class=en>Fixed panel: "
                f"{len(panel_animals)} animals × {len(bench.tiers)} prompt tiers; verified verbatim prompts only. "
                "Provider refusals score 0.</span></p>" + _ranking(boards.get("imagegen", []), label))
    html.append("<h2 id=vision-ranking>视觉理解排名 <span class=en>Visual understanding ranking</span></h2>"
                f"<p class=muted>固定题组：{len(vision_items)} 道看图题（{len(vision_items) - grounding} 道识别、"
                f"{grounding} 道按答案键计分的视觉核对）。文字知识与无图对照只作诊断。<br><span class=en>Fixed panel: "
                f"{len(vision_items)} image-input tasks ({len(vision_items) - grounding} recognition, {grounding} "
                "answer-keyed grounding checks). Text knowledge and no-image controls are diagnostics.</span></p>"
                + _ranking(boards.get("visual_understanding", []), label)
                + "<p class=muted>两个排名相互独立，不合成总分。有缺失、失败、未评分或不合格格子的模型不参与排名。"
                "<span class=en> Two independent rankings, no combined score. Missing, failed, unjudged, or "
                "ineligible cells leave a model unranked.</span></p>")

    # --- models ---
    roles = defaultdict(set)
    for s in img_samples:
        roles[s["model"]].add("图像生成 Image generation")
    for s in und_samples:
        roles[s["model"]].add("理解 Understanding")
    for j in scores["judges"]:
        roles[j].add("评审 Judge")
    first_meta = {}
    for s in img_samples + und_samples:
        first_meta.setdefault(s["model"], meta_of[s["target"]])
    html.append("<h2 id=models>参测模型 <span class=en>Models</span></h2><div class=scroll><table><tr><th>模型 Model</th>"
                "<th>角色 Role</th><th>调用方式 Access</th><th>图像来源凭证 C2PA provenance</th></tr>")
    for m in sorted(roles, key=lambda m: (min(roles[m]), m)):
        meta = first_meta.get(m, {})
        c2pa = _c2pa(meta) if any("Image" in r for r in roles[m]) else "–"
        html.append(f"<tr><td><b>{e(label(m))}</b><br><span class=muted>{e(m)}</span></td>"
                    f"<td>{'<br>'.join(sorted(roles[m]))}</td><td>{_access(models.get(m), meta)}</td><td>{c2pa}</td></tr>")
    html.append("</table></div><p class=muted>图片内嵌的 C2PA 内容凭证声明的生成器：OpenAI 标注为 "
                "<code>ChatGPT · gpt-image</code>，Google 只标注“由 Google 生成式 AI 创建”并加有 SynthID 水印，"
                "两家都未公开更细的版本号。图像生成由 Agent 中转：上表“调用方式”中的模型负责把提示词原样交给图像工具，"
                "内容凭证仅供参考，未验证签名；逐字核对的结果列于下方。<br><span class=en>Vendor-declared generators are read from each image's C2PA "
                "content credentials, which name only “ChatGPT · gpt-image” (OpenAI) and “Created by Google Generative AI” "
                "(Google); neither exposes a more specific image model version. Signatures are not verified. "
                "The listed relay model forwards prompts to the image tool; audit results appear below.</span></p>")

    # --- image generation ---
    summary = scores["imagegen"]
    by_cell = {(s["model"], s["animal"], s["tier"]): s for s in sorted(img_samples, key=lambda s: -s["rep"])}
    img_models = sorted({s["model"] for s in img_samples}, key=lambda m: (-(summary.get(m, {}).get("overall") or 0), m))
    if core_tiers:
        html.append("<h2 id=gallery>图像生成 <span class=en>Image generation</span></h2>"
                    "<p>让模型画“⟨动物⟩版的大笑奶龙”，提示词分五档。评审对照原图，按 9 项加权视觉特征打分，"
                    "再乘以能否认出目标动物（0–100）。<br><span class=en>Models draw an animal version of the meme from five "
                    "prompt tiers. Judges compare each image with the reference on nine weighted visual traits, "
                    "scaled by whether the target animal is recognizable (0–100).</span></p>")
        html.append("<details><summary>提示词 · Prompts</summary><table><tr><th>档位 Tier</th><th>提示词（以猫为例）"
                    " Prompt (cat)</th></tr>")
        cat = bench.animals.get("cat") or next(iter(bench.animals.values()))
        for t in core_tiers:
            extra = "（附原图 + reference image）" if t.reference else ""
            html.append(f"<tr><td><b>{e(t.title_zh)}</b><br><span class=muted>{e(t.title_en)} · {e(t.id)}</span></td>"
                        f"<td class=ans>{e(t.render(cat))}{extra}</td></tr>")
        html.append("</table></details>")
        core_animals = [a for a in bench.animals if any(s["animal"] == a and not s["state"] for s in img_samples)]
        for a in core_animals:
            animal = bench.animals[a]
            html.append(f"<h3>{e(animal.zh)} <span class=en>{e(animal.en)}</span></h3><div class=scroll>"
                        "<table class=gallery><tr><th style='width:150px'></th>"
                        + "".join(f"<th>{e(t.title_zh)}<br><span class=en>{e(t.title_en)}</span></th>" for t in core_tiers)
                        + "</tr>")
            for m in img_models:
                html.append(f"<tr><td style='text-align:left'><b>{e(label(m))}</b></td>"
                            + "".join(_image_cell(by_cell.get((m, a, t.id)), run_dir, out, f"{label(m)} {t.id} {a}")
                                      for t in core_tiers) + "</tr>")
            html.append("</table></div>")
        html.append("<h3>诊断汇总 <span class=en>Diagnostics</span></h3><div class=scroll><table><tr><th>模型 Model</th>"
                    "<th>已有格子均分 Available-cell mean</th>" + "".join(f"<th>{e(t.title_zh)}</th>" for t in core_tiers)
                    + "<th>知识比率 Knowledge ratio</th></tr>")
        for m in img_models:
            if m not in summary:
                continue
            s = summary[m]
            html.append(f"<tr><td>{e(label(m))}</td><td class=n><b>{fmt(s['overall'])}</b></td>"
                        + "".join(f"<td class=n>{fmt(s['tiers'].get(t.id, {}).get('overall'))}</td>" for t in core_tiers)
                        + f"<td class=n>{fmt(s['knowledge_ratio'], 2)}</td></tr>")
        html.append("</table></div><p class=muted>知识比率 = 两个“只给梗名”档的均分 ÷ “详细描述”档的均分，只比较三档都有结果的相同动物；"
                    "它反映对提示词详细程度的敏感度，不是“认识这个梗”的概率。诊断均分可能与固定排名题组不同。"
                    "<span class=en> Knowledge ratio = mean of both name tiers ÷ detailed-description tier, on "
                    "matched animals only. It is prompt sensitivity, not a calibrated probability of knowledge. "
                    "Diagnostic means may differ from the fixed ranking panel.</span></p>")

    # --- optional state transfer ---
    if state_samples:
        html.append("<h2 id=states>表情迁移（可选，不计分）<span class=en>Optional state transfer · unscored</span></h2>"
                    "<p>把三张奶蛙表情包的表情和动作（愤怒、扶额、得意）迁移到别的动物身上。每种表情有两种条件："
                    "只给固定的文字描述，或附上源图。这部分不由 LLM 评分，也不计入排名，请对照源图分别查看表情、动作、"
                    "动物辨识度和渲染风格。<br><span class=en>Three 奶蛙 sticker states (angry, facepalm, smug) are "
                    "transferred to other animals, either from a fixed text description or from the attached source "
                    "image. These images receive no LLM grades and do not enter either ranking; compare expression, "
                    "gesture, animal identity, and render style with the source by eye.</span></p>")
        state_tiers = defaultdict(dict)
        for t in bench.state_tiers.values():
            if any(s["tier"] == t.id for s in state_samples):
                state_tiers[t.state]["reference" if t.reference else "described"] = t
        state_animals = [a for a in bench.animals if any(s["animal"] == a for s in state_samples)]
        state_models = sorted({s["model"] for s in state_samples})
        for state, conditions in state_tiers.items():
            any_tier = next(iter(conditions.values()))
            source = _copy_image(any_tier.reference_image, out, f"images/states/{state}")
            title_zh, title_en = any_tier.title_zh.split(" · ")[0], any_tier.title_en.split(" · ")[0]
            columns = [(a, c, conditions[c]) for a in state_animals for c in CONDITION if c in conditions]
            html.append(f"<h3><img class=source src='{e(source)}' alt='Source: {e(state)}'>{e(title_zh)} "
                        f"<span class=en>{e(title_en)}</span></h3><div class=scroll><table class=gallery>"
                        "<tr><th style='width:150px'></th>"
                        + "".join(f"<th>{e(bench.animals[a].zh)} · {CONDITION[c][0]}<br><span class=en>"
                                  f"{e(bench.animals[a].en)} · {CONDITION[c][1]}</span></th>" for a, c, _ in columns)
                        + "</tr>")
            for m in state_models:
                html.append(f"<tr><td style='text-align:left'><b>{e(label(m))}</b></td>"
                            + "".join(_image_cell(by_cell.get((m, a, t.id)), run_dir, out, f"{label(m)} {t.id} {a}",
                                                  scored=False) for a, _, t in columns) + "</tr>")
            html.append("</table></div>")
            cat = bench.animals.get("cat") or next(iter(bench.animals.values()))
            html.append("<details><summary>提示词 · Prompts</summary><table>"
                        + "".join(f"<tr><td style='width:150px'><b>{CONDITION[c][0]}</b><br><span class=muted>"
                                  f"{CONDITION[c][1]}</span></td><td class=ans>{e(t.render(cat))}</td></tr>"
                                  for c, t in conditions.items()) + "</table></details>")

    # --- understanding ---
    if und_samples:
        html.append("<h2 id=understanding>理解诊断 <span class=en>Understanding diagnostics</span></h2>"
                    "<p>不允许联网或使用工具。识别题和文字题对照有出处的事实，由评审团打分，每条言之凿凿的幻觉扣 10 分；"
                    "视觉核对题按答案键在本地计分。<br><span class=en>No web or tools. Recognition and text answers are "
                    "scored by the judge panel against sourced facts, with 10 points off per confident hallucination; "
                    "grounding checks use local answer keys.</span></p>")
    for states in (False, True):
        selected = [s for s in und_samples if bool(s.get("state")) == states]
        if not selected:
            continue
        usum = scores.get("state_understanding" if states else "understanding", {})
        if states:
            html.append("<h3>表情状态提取（可选，按答案键计分）<span class=en>Optional state extraction · answer-keyed"
                        "</span></h3><p class=muted>同一提问分别在有图和无图时作答，答案键只含可直接看到的表情、眼睛、"
                        "嘴巴和动作；不影响任何排名。<span class=en> The same question with and without the source image; "
                        "the keys contain only visible expression, eyes, mouth, and gesture. Not part of either "
                        "ranking.</span></p><div class=scroll><table><tr><th>模型 Model</th><th>有图 With image</th>"
                        "<th>无图 No image</th><th>视觉增益 Visual gain</th><th>用了工具 Used tools</th></tr>")
            for m, s in sorted(usum.items()):
                html.append(f"<tr><td>{e(label(m))}</td><td class=n>{fmt(s['vision'])}</td>"
                            f"<td class=n>{fmt(s.get('blind'))}</td><td class=n>{fmt(s.get('visual_gain'))}</td>"
                            f"<td class=n>{s['contaminated']}</td></tr>")
        else:
            html.append("<div class=scroll><table><tr><th>模型 Model</th><th>看图 Vision</th><th>文字 Text</th>"
                        "<th>中文 Text ZH</th><th>英文 Text EN</th><th>视觉核对 Grounding</th><th>无图 No image</th>"
                        "<th>视觉增益 Visual gain</th><th>每答幻觉 Halluc./answer</th><th>用了工具 Used tools</th></tr>")
            for m, s in sorted(usum.items()):
                html.append(f"<tr><td>{e(label(m))}</td><td class=n>{fmt(s['vision'])}</td>"
                            f"<td class=n>{fmt(s['text'])}</td>"
                            f"<td class=n>{fmt(s.get('languages', {}).get('zh'))}</td>"
                            f"<td class=n>{fmt(s.get('languages', {}).get('en'))}</td>"
                            f"<td class=n>{fmt(s.get('grounding'))}</td><td class=n>{fmt(s.get('blind'))}</td>"
                            f"<td class=n>{fmt(s.get('visual_gain'))}</td>"
                            f"<td class=n>{fmt(s['hallucinations_per_answer'], 1)}</td><td class=n>{s['contaminated']}</td></tr>")
        html.append("</table></div><p class=muted>视觉增益 = 有图得分 − 无图得分（按题目和重复配对，单位为百分点）。"
                    "用了工具：违反要求调用了工具的回答，不计分。<span class=en> Visual gain is the matched with-image minus "
                    "no-image score, in percentage points. Used tools: answers that called a tool despite instructions; "
                    "they are excluded.</span></p>")
        by_item = defaultdict(list)
        for s in selected:
            by_item[s["item"]].append(s)
        prompts = {i.id: i for i in bench.all_items}
        for item_id in [i.id for i in bench.all_items if i.id in by_item]:
            item = prompts[item_id]
            shown = "".join(f"<img src='{e(_copy_image(p, out, 'images/stimuli/' + p.stem))}' "
                            "style='max-width:140px;border-radius:8px' alt=''>" for p in item.images)
            html.append(f"<details><summary>{e(item_id)} · {e(item.prompt[:60])}</summary>{shown}"
                        f"<p class=muted>{e(item.prompt)}</p><table>")
            for s in sorted(by_item[item_id], key=lambda s: (-(s["score"] or 0), s["model"])):
                bad = "".join(f"<div class=bad>✗ {e(h)}</div>" for h in s["hallucinations"][:3])
                html.append(f"<tr><td style='width:150px'><b>{e(label(s['model']))}</b><br><span class=score>"
                            f"{fmt(s['score'])}</span></td><td class=ans>{e(s['answer'])}{bad}</td></tr>")
            html.append("</table></details>")

    # --- judges ---
    html.append("<h2 id=judges>评审 <span class=en>Judges</span></h2><p>每个样本由其他厂商的评审打分后取平均；没有独立评审时使用现有评审。"
                "下表是评审的健康度：分数离散度太低说明评审分不出好坏，与其他评审差距太大说明意见不一致。<br>"
                "<span class=en>Each sample is averaged over judges from other vendors, falling back to the available "
                "panel when none are independent. Spread: how much a judge's scores vary; distance: how far it sits "
                "from the other judges.</span></p><div class=scroll><table>"
                "<tr><th>评审 Judge</th><th>部分 Track</th><th>样本 Samples</th><th>离散度 Spread</th>"
                "<th>与其他评审差距 Distance</th></tr>")
    for j, tracks in scores.get("judge_health", {}).items():
        for track, h in tracks.items():
            html.append(f"<tr><td>{e(label(j))}</td><td>{e(track)}</td><td class=n>{h['n']}</td>"
                        f"<td class=n>{fmt(h['spread'], 1)}</td><td class=n>{fmt(h['deviation'], 1)}</td></tr>")
    html.append("</table></div>")
    repo = f" · <a href='{e(repo_url, quote=True)}'>源代码 Source</a>" if repo_url else ""
    sources = (f"<a href='{e(blob, quote=True)}/bench/reference/SOURCE.md'>SOURCE.md</a>" if blob
               else "bench/reference/SOURCE.md")
    html.append(f"<footer>奶蛙bench · nai-wai-bench{repo} · 参考图来自萌娘百科，表情包与官方形象图的出处见 {sources}，"
                "仅供非商业研究使用。<span class=en> Reference image from Moegirlpedia; sticker and official-art sources "
                "are listed in SOURCE.md. For non-commercial research use.</span></footer></main></html>")
    index = out / "index.html"
    index.write_text("\n".join(html), encoding="utf-8")
    return index

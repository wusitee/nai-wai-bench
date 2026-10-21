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
            f"<title>大笑奶龙理解基准 · nai-wai-bench</title><style>{CSS}</style><main>"]
    date = datetime.date.today().isoformat()
    animals = sorted({s["animal"] for s in img_samples})
    html.append(
        f"<div class=hero><img src='images/{e(bench.reference_image.name)}' alt='大笑奶龙'><div>"
        "<h1>大笑奶龙理解基准 <span class=en>nai-wai-bench</span></h1>"
        "<p>测试 AI 模型是否认识中文网络迷因“大笑奶龙 / 奶蛙”：能否讲清来龙去脉、认出图片，以及按这种 3D 风格把它画成别的动物。<br>"
        "<span class=en>How well do AI models know the Chinese meme 大笑奶龙 (Laughing Nailong / 奶蛙): its lore, "
        "recognizing it, and drawing other animals in its 3D style.</span></p>"
        f"<span class=badge>初步结果 · Preliminary</span> <span class=muted>run <code>{e(run_dir.name)}</code> · {date}</span>"
        "</div></div>")
    html.append(
        "<div class=note><b>这是一次试跑。</b>"
        f"图像部分共 {len(img_samples)} 个样本（{len(animals)} 种动物），理解部分共 {len(und_samples)} 条回答。"
        "样本很少，几分的差距可能只是偶然，请勿当作排名。<br><span class=en>A trial run with "
        f"{len(img_samples)} image samples ({len(animals)} animal(s)) and {len(und_samples)} answers. "
        "Differences of a few points can be noise; this is not a ranking.</span></div>")

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
    html.append("<h2>参测模型 <span class=en>Models</span></h2><div class=scroll><table><tr><th>模型 Model</th>"
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
    tiers = [t for t in bench.tiers.values() if any(t.id == s["tier"] for s in img_samples)]
    if img_samples:
        html.append("<h2>图像生成 <span class=en>Image generation</span></h2>"
                    "<p>让模型画“⟨动物⟩版的大笑奶龙”，提示词分五档。评审对照原图，按 9 项加权视觉特征打分，"
                    "再乘以能否认出目标动物。<br><span class=en>Models draw an animal version of the meme from five "
                    "prompt tiers. Judges compare each image with the reference on nine weighted visual traits, "
                    "scaled by whether the target animal is recognizable (0–100).</span></p>")
        html.append("<details><summary>提示词 · Prompts</summary><table><tr><th>档位 Tier</th><th>提示词（以猫为例）"
                    " Prompt (cat)</th></tr>")
        cat = bench.animals.get("cat") or next(iter(bench.animals.values()))
        for t in tiers:
            extra = "（附原图 + reference image）" if t.reference else ""
            html.append(f"<tr><td><b>{e(t.title_zh)}</b><br><span class=muted>{e(t.title_en)} · {e(t.id)}</span></td>"
                        f"<td class=ans>{e(t.render(cat))}{extra}</td></tr>")
        html.append("</table></details>")
        by_cell = {(s["model"], s["animal"], s["tier"]): s for s in sorted(img_samples, key=lambda s: -s["rep"])}
        img_models = sorted({s["model"] for s in img_samples},
                            key=lambda m: -(summary.get(m, {}).get("overall") or 0))
        for a in animals:
            animal = bench.animals[a]
            html.append(f"<h3>{e(animal.zh)} <span class=en>{e(animal.en)}</span></h3><div class=scroll>"
                        "<table class=gallery><tr><th style='width:150px'></th>"
                        + "".join(f"<th>{e(t.title_zh)}<br><span class=en>{e(t.title_en)}</span></th>" for t in tiers)
                        + "</tr>")
            for m in img_models:
                row = [f"<tr><td style='text-align:left'><b>{e(label(m))}</b></td>"]
                for t in tiers:
                    s = by_cell.get((m, a, t.id))
                    if not s:
                        row.append("<td>–</td>")
                        continue
                    dst = _copy_image(run_dir / s["images"][0], out, f"images/{m}/{t.id}/{a}__r{s['rep']}")
                    why = " | ".join(f"{j}: {r}" for j, r in s["rationales"].items())
                    tags = "".join(f"<div class=tag>{e(FAILURE_ZH.get(f, f))}</div>" for f in s["failure_modes"])
                    audit = {True: "原样传递 · Verbatim", False: "提示词有改动 · Prompt changed", None: "未核实 · Unverified"}[s["verbatim"]]
                    row.append(f"<td title='{e(why, quote=True)}'><a href='{e(dst)}'><img loading=lazy "
                               f"src='{e(dst)}' alt='{e(label(m))} {e(t.id)}'></a>"
                               f"<span class=score>{fmt(s['overall'])}</span>{tags}<div class=muted>{audit}</div></td>")
                html.append("".join(row) + "</tr>")
            html.append("</table></div>")
        html.append("<h3>汇总 <span class=en>Summary</span></h3><div class=scroll><table><tr><th>模型 Model</th>"
                    "<th>总分 Overall</th>" + "".join(f"<th>{e(t.title_zh)}</th>" for t in tiers)
                    + "<th>知识比率 Knowledge ratio</th></tr>")
        for m in img_models:
            if m not in summary:
                continue
            s = summary[m]
            html.append(f"<tr><td>{e(label(m))}</td><td class=n><b>{fmt(s['overall'])}</b></td>"
                        + "".join(f"<td class=n>{fmt(s['tiers'].get(t.id, {}).get('overall'))}</td>" for t in tiers)
                        + f"<td class=n>{fmt(s['knowledge_ratio'], 2)}</td></tr>")
        html.append("</table></div><p class=muted>知识比率 = 两个“只给梗名”档的平均分 ÷ “详细描述”档的分数：只凭梗名能发挥出"
                    "多少绘画能力。<span class=en> Knowledge ratio = mean of the name-only tiers ÷ the detailed-"
                    "description tier.</span></p>")

    # --- understanding ---
    usum = scores["understanding"]
    if und_samples:
        html.append("<h2>理解 <span class=en>Understanding</span></h2>"
                    "<p>不允许联网或使用工具，回答梗的来源、外观，并从图片认出它。对照有出处的事实打分，"
                    "每条言之凿凿的幻觉扣 10 分。<br><span class=en>No web or tools. Answers are scored against sourced "
                    "facts; each confident hallucination costs 10 points.</span></p><div class=scroll><table>"
                    "<tr><th>模型 Model</th><th>总分 Overall</th><th>文字 Text</th><th>看图 Vision</th>"
                    "<th>每答幻觉 Halluc./answer</th></tr>")
        for m, s in sorted(usum.items(), key=lambda kv: -(kv[1]["overall"] or 0)):
            html.append(f"<tr><td>{e(label(m))}</td><td class=n><b>{fmt(s['overall'])}</b></td>"
                        f"<td class=n>{fmt(s['text'])}</td><td class=n>{fmt(s['vision'])}</td>"
                        f"<td class=n>{fmt(s['hallucinations_per_answer'], 1)}</td></tr>")
        html.append("</table></div>")
        by_item = defaultdict(list)
        for s in und_samples:
            by_item[s["item"]].append(s)
        prompts = {i.id: i for i in bench.items}
        for item_id in [i.id for i in bench.items if i.id in by_item]:
            item = prompts[item_id]
            shown = "".join(f"<img src='{e(_copy_image(p, out, 'images/stimuli/' + p.stem))}' "
                            "style='max-width:140px;border-radius:8px' alt=''>" for p in item.images)
            html.append(f"<details><summary>{e(item_id)} · {e(item.prompt[:60])}</summary>{shown}<table>")
            for s in sorted(by_item[item_id], key=lambda s: -(s["score"] or 0)):
                ans = s["answer"]
                bad = "".join(f"<div class=bad>✗ {e(h)}</div>" for h in s["hallucinations"][:3])
                html.append(f"<tr><td style='width:150px'><b>{e(label(s['model']))}</b><br><span class=score>"
                            f"{fmt(s['score'])}</span></td><td class=ans>{e(ans)}{bad}</td></tr>")
            html.append("</table></details>")

    # --- judges ---
    html.append("<h2>评审 <span class=en>Judges</span></h2><p>优先使用其他厂商的评审打分后取平均；没有独立评审时使用现有评审。"
                "下表是评审的健康度：分数离散度太低说明评审分不出好坏，与其他评审差距太大说明意见不一致。<br>"
                "<span class=en>Scores prefer judges from other vendors, falling back to the available panel when none are independent. Spread: how much a judge's "
                "scores vary; distance: how far it sits from the other judges.</span></p><div class=scroll><table>"
                "<tr><th>评审 Judge</th><th>部分 Track</th><th>样本 Samples</th><th>离散度 Spread</th>"
                "<th>与其他评审差距 Distance</th></tr>")
    for j, tracks in scores.get("judge_health", {}).items():
        for track, h in tracks.items():
            html.append(f"<tr><td>{e(label(j))}</td><td>{e(track)}</td><td class=n>{h['n']}</td>"
                        f"<td class=n>{fmt(h['spread'], 1)}</td><td class=n>{fmt(h['deviation'], 1)}</td></tr>")
    html.append("</table></div>")
    repo = f" · <a href='{e(repo_url, quote=True)}'>源代码 Source</a>" if repo_url else ""
    html.append(f"<footer>由 nai-wai-bench 生成 · Generated by nai-wai-bench{repo} · 参考图来源：萌娘百科 "
                "(reference image: Moegirlpedia), for non-commercial research use.</footer></main></html>")
    index = out / "index.html"
    index.write_text("\n".join(html), encoding="utf-8")
    return index

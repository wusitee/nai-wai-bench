"""Static, bilingual (中文 / English) results site: one index.html per suite plus resized images, and for
releases a NaiWai Index overview page, ready to publish with GitHub Pages. Readers switch the language
(see `nwb.lang`)."""

import datetime
import shutil
import subprocess
from collections import defaultdict
from html import escape as e
from pathlib import Path

from nwb import CANARY, __version__
from nwb.config import SUITES, Bench, ModelSpec, UnderstandingItem
from nwb.lang import CSS as LANG_CSS, SCRIPT as LANG_SCRIPT, SWITCH as LANG_SWITCH, bi, bie
from nwb.report import (UNCERTAINTY_NOTE, collection_profiles_text, collection_text, efficiency_section, stale_text, fmt, judge_text,
                        model_html, rank_range, score_text)
from nwb.scoring import INDEX_WEIGHTS
from nwb.util import extract_json, read_json

FAILURE_ZH = {"generic_cute": "泛泛的可爱风", "realistic_animal": "写实动物", "plain_nailong": "只是奶龙本体",
              "text_or_watermark": "带文字或水印", "multiple_subjects": "多主体或场景杂乱"}
ACCESS = {"codex": "Codex CLI", "claude": "Claude Code", "acp": "ACP agent", "openai": "API"}
CONDITION = {"described": ("文字描述", "Description"), "reference": ("参考图", "Reference image")}
IMAGE_WIDTH = 768

# Per suite: public name (zh, en), introduction (zh, en), and whether the hero shows a mosaic of the
# answer-keyed images instead of the reference portrait. Suite ids stay internal; pages use the names.
SUITE_TEXT = {
    "core": {
        "name": ("识梗", "Meme ID"), "mosaic": False,
        "intro": ("AI 模型能否从图片中认出中文网络梗“大笑奶龙”（又称“奶蛙”）和它的变体，说出它属于哪个梗、"
                  "有哪些别名，并分清官方奶龙？",
                  "Can AI models recognize the Chinese meme 大笑奶龙 (Laughing Nailong, also called 奶蛙) and its "
                  "variants in images, name the meme and its aliases, and tell it apart from official Nailong?"),
    },
    "naihub-v1": {
        "name": ("看图", "Visual detail"), "mosaic": True,
        "intro": ("24 张图，同一道看图题：这是奶蛙、官方奶龙，还是别的角色？有几只？什么姿态、眼睛、嘴巴和手势？"
                  "有没有流泪？七项全部答对才算这张图答对。其中 8 张还被拿来测试：能否把同样的姿势搬到猫和青蛙身上。",
                  "24 images, one question each: is it 奶蛙, official Nailong, or someone else? How many are there? "
                  "What posture, eyes, mouth, and gesture? Any tears? An image counts only when all seven fields "
                  "are right. Eight of them also test whether image models can move the same pose onto a cat "
                  "and a frog."),
    },
}
INDEX_NAME = ("奶蛙指数", "NaiWai Index")
FRONTEND_NAME = ("复刻", "Rebuild")
BILL_NAME = ("账单", "Bill")
# Published release layout: the index at the site root; every suite, the experimental frontend track, and
# the token bill in a subdirectory named after it.
PAGES = {"index": "", "core": "meme-id", "naihub-v1": "visual-detail", "frontend": "frontend", "bill": "bill"}
# Earlier published suite paths, kept as redirects to the current pages.
REDIRECTS = {"naihub-v1": "naihub-v1"}
CATEGORY = {"anchors": ("经典锚点", "Anchors"), "pose_action": ("姿势动作", "Pose and action"),
            "appearance": ("外观造型", "Appearance"), "context": ("场景与多角色", "Context"),
            "negative_control": ("反例对照", "Negative controls")}
FIELD_ZH = {"family": "类别", "subjects": "数量", "posture": "姿态", "eyes": "眼睛", "mouth": "嘴巴",
            "gesture": "手势", "tears": "眼泪", "pose": "姿势", "state": "表情"}

CSS = """
:root{color-scheme:dark;--bg:#050505;--fg:#f5f5f5;--ink2:#d4d4d4;--muted:#8f8f8f;--dim:#808080;
--line:rgba(255,255,255,.07);--card:rgba(23,23,23,.45);--cell:#0d0d0d;--soft:rgba(255,255,255,.05);
--yellow:#facc15;--link:#facc15;--green:#22c55e;--blue:#0ea5e9;--orange:#f97316;--bar:rgba(161,161,170,.45);
--good:#22c55e;--bad:#ef4444;--good-ink:#4ade80;--bad-ink:#f87171;--heat:#c2410c;--heat-ink:#fff;
--sans:Geist,"Geist Sans",Inter,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
--mono:"Geist Mono","SF Mono","JetBrains Mono",ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px;background:var(--bg)}
body{margin:0;min-height:100vh;color:var(--fg);font:15px/1.6 var(--sans);-webkit-font-smoothing:antialiased;
background:linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 0),linear-gradient(180deg,rgba(255,255,255,.03) 1px,transparent 0);
background-size:40px 40px}
body:before{content:"";position:fixed;inset:0;z-index:50;pointer-events:none;opacity:.012;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
body:after{content:"";position:fixed;left:0;right:0;bottom:0;height:1px;pointer-events:none;
background:linear-gradient(90deg,transparent,rgba(250,204,21,.3),transparent)}
::selection{background:rgba(250,204,21,.3)}
a{color:var(--link);text-decoration-color:rgba(250,204,21,.35);text-underline-offset:3px}
code,.mono{font:12px var(--mono)}
.top{position:sticky;top:0;z-index:5;background:rgba(5,5,5,.82);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.top>div{max-width:1180px;margin:auto;padding:12px 20px;display:flex;gap:10px 24px;align-items:center;flex-wrap:wrap}
.brand{font-size:20px;font-weight:800;letter-spacing:-.02em;color:var(--fg);text-decoration:none;white-space:nowrap}
.brand span{color:var(--yellow)}
.tabs{display:flex;gap:20px;overflow-x:auto;max-width:100%}
.tabs a{padding:3px 0;border-bottom:2px solid transparent;text-decoration:none;color:var(--muted);font-size:13px;
font-weight:800;letter-spacing:-.01em;text-transform:uppercase;white-space:nowrap}
.tabs a:hover{color:var(--fg)}.tabs a[aria-current]{color:var(--yellow);border-color:var(--yellow)}
.sections{display:flex;gap:16px;overflow-x:auto;flex:1}.sections a:first-child{margin-left:auto}
.sections a{font:10.5px var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);text-decoration:none;white-space:nowrap}
.sections a:hover{color:var(--fg)}
main{max-width:1180px;margin:auto;padding:40px 20px 72px}
h1,h2,h3{font-weight:800;letter-spacing:-.02em;text-transform:uppercase}
h1{font-size:46px;line-height:1.05;margin:0 0 16px}h2{font-size:25px;line-height:1.2;margin:68px 0 10px}
h3{font-size:16px;margin:30px 0 8px}
.en{color:var(--muted);font-weight:inherit}.muted{color:var(--muted);font-size:13px}.lede{font-size:16.5px;margin:0 0 16px;color:var(--ink2)}
.hero{display:grid;grid-template-columns:auto 1fr;gap:32px;align-items:center}
.hero.solo{grid-template-columns:1fr}.hero>img{width:170px;border-radius:10px;border:1px solid var(--line);box-shadow:0 0 70px rgba(250,204,21,.14)}
.badge{display:inline-flex;align-items:center;gap:7px;font:10.5px var(--mono);text-transform:uppercase;letter-spacing:.1em;color:var(--yellow);
border:1px solid rgba(250,204,21,.3);background:rgba(250,204,21,.06);border-radius:4px;padding:3px 9px}
.badge:before{content:"";width:6px;height:6px;border-radius:50%;background:var(--yellow);animation:pulse 2s cubic-bezier(.4,0,.6,1) infinite}
.stamp{font:11px var(--mono);color:var(--dim);margin-left:6px}.stamp code{font-size:11px}
.mosaic{display:grid;grid-template-columns:repeat(12,1fr);gap:6px;margin:28px 0 0}
.mosaic a{display:block;aspect-ratio:1;border-radius:6px;overflow:hidden;background:var(--card);border:1px solid var(--line)}
.mosaic img{width:100%;height:100%;object-fit:cover;opacity:.85;transition:transform .15s,opacity .15s}
.mosaic a:hover img{transform:scale(1.08);opacity:1}
.note{border:1px solid var(--line);border-left:2px solid var(--yellow);background:var(--card);border-radius:6px;
padding:12px 16px;margin:24px 0;color:var(--ink2);font-size:14px}
.panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:18px;margin-top:12px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:18px 22px;backdrop-filter:blur(12px);min-width:0}
.panel h3{margin:0 0 4px}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top;font-size:14px}
th{font:500 10px/1.5 var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);vertical-align:bottom}
th.n,td.n{text-align:right;font-variant-numeric:tabular-nums}td.n{font-family:var(--mono);font-size:13px}
tr:last-child>td{border-bottom:0}tr:hover>td{background-color:rgba(255,255,255,.02)}.scroll{overflow-x:auto}
.card-table{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:4px 10px}
.rank{font:700 12px var(--mono);color:var(--dim);font-variant-numeric:tabular-nums}
.t1{--tier:var(--green)}.t2{--tier:var(--blue)}.t3{--tier:var(--orange)}
.t1 .rank,.t2 .rank,.t3 .rank{color:var(--tier)}
.meter{display:flex;align-items:center;gap:10px;min-width:150px}
.meter b{min-width:36px;text-align:right;font:700 13px var(--mono);font-variant-numeric:tabular-nums}
.track{position:relative;flex:1;min-width:48px;height:6px;background:rgba(255,255,255,.05);border-radius:99px}
.fill{display:block;height:100%;border-radius:99px;background:var(--tier,var(--bar));transform-origin:left;animation:grow .6s ease-out both;
box-shadow:0 0 8px color-mix(in srgb,var(--tier,transparent) 35%,transparent)}
.interval{position:absolute;top:2px;height:2px;background:rgba(255,255,255,.6)}
.interval:before,.interval:after{content:"";position:absolute;top:-3px;width:1px;height:8px;background:rgba(255,255,255,.6)}
.interval:before{left:0}.interval:after{right:0}
.ranking{min-width:520px}.ranking td{padding:9px 8px;line-height:1.3}.ranking th:nth-child(4){white-space:nowrap}
.ranking b{font:600 13px var(--mono);color:var(--ink2)}.ranking b .muted{font-size:12px;font-weight:400}
.ranking .meter{flex-wrap:wrap;gap:4px 10px}.ranking .meter b{font-size:12.5px;white-space:nowrap;color:var(--muted)}
.ranking :is(.t1,.t2,.t3) b,.ranking :is(.t1,.t2,.t3) .meter b{color:var(--fg)}
.row-meta{font:10.5px/1.4 var(--mono);margin-top:3px;color:var(--dim)}
.status{display:inline-block;white-space:nowrap;font:10px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
border:1px solid var(--line);border-radius:3px;padding:0 5px}
.status.mixed{color:var(--bad-ink);border-color:rgba(239,68,68,.35)}
.efficiency th{max-width:155px}.efficiency td.n{white-space:nowrap}.efficiency td:first-child{min-width:150px}
.efficiency-chart{display:block;width:100%;min-width:680px;height:auto;margin-top:22px;padding:14px;background:var(--card);border:1px solid var(--line);border-radius:8px}
.efficiency-chart path{stroke:var(--line)}.efficiency-chart text{fill:var(--muted);font-family:var(--mono);font-size:12px}
.efficiency-chart circle{fill:var(--yellow);stroke:var(--bg);stroke-width:2;filter:drop-shadow(0 0 4px rgba(250,204,21,.55))}
.flag{display:inline-block;font:600 10px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--yellow);
border:1px solid rgba(250,204,21,.3);border-radius:3px;padding:0 5px;margin:2px 0 0 4px}
.heat{text-align:right;font:13px var(--mono);font-variant-numeric:tabular-nums;box-shadow:inset 0 0 0 1px var(--cell)}.heat.hi{color:var(--heat-ink)}
.group{display:flex;align-items:baseline;gap:10px;margin:30px 0 10px}.group h3{margin:0}
.cases{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.case{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;transition:border-color .15s;
display:flex;flex-direction:column;scroll-margin-top:70px}.case:hover{border-color:rgba(255,255,255,.16)}
.case:target{outline:2px solid var(--yellow)}
.case>a img{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:rgba(255,255,255,.03)}
.case>div{padding:12px 14px 14px;display:flex;flex-direction:column;gap:9px}
.case-title{font-weight:700;line-height:1.3}.case-title span{color:var(--muted);font:400 11px var(--mono)}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.chip{display:inline-flex;flex-direction:column;background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:2px 7px;
line-height:1.25;font:12px var(--mono)}
.chip small{font:9.5px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.verdict{display:flex;align-items:center;gap:10px;font-size:13px}.verdict b{white-space:nowrap;font-family:var(--mono)}
.segs{display:flex;gap:2px;flex:1}.seg{flex:1;height:6px;background:var(--bad);opacity:.85}.seg.ok{background:var(--good);opacity:1}
.seg:first-child{border-radius:99px 0 0 99px}.seg:last-child{border-radius:0 99px 99px 0}
.case details{background:none;border:0;padding:0;margin:0;font-size:13px;backdrop-filter:none}
.case summary{font:600 11px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--ink2)}
.who{list-style:none;padding:0;margin:6px 0 0}.who li{padding:4px 0;border-top:1px solid var(--line)}
.mark-ok{color:var(--good-ink);font-weight:700}.mark-no{color:var(--bad-ink);font-weight:700}
.miss{display:inline-block;margin-right:8px}.miss code{background:var(--soft);border-radius:4px;padding:0 4px}
.raw{white-space:pre-wrap;word-break:break-word;font:12px var(--mono);color:var(--ink2);
background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:4px 0 8px;max-height:220px;overflow:auto}
.gallery{table-layout:fixed;min-width:760px}.gallery td,.gallery th{text-align:center}
.gallery img{width:100%;max-width:190px;aspect-ratio:1;object-fit:contain;border-radius:6px;display:block;margin:0 auto 4px;background:var(--soft)}
.gallery td:first-child,.gallery th:first-child{text-align:left}
.score{font:700 18px var(--mono)}.tag{font-size:11.5px;color:var(--bad-ink)}
details{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;margin:8px 0}
summary{cursor:pointer;font-weight:600}.ans{white-space:pre-wrap;font-size:13px}
.refused{display:flex;align-items:center;justify-content:center;aspect-ratio:1;max-width:190px;margin:0 auto 4px;
border:1px dashed var(--line);border-radius:6px;color:var(--bad-ink);font-size:13px}
.state{display:grid;grid-template-columns:190px 1fr;gap:18px;background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:16px;margin:14px 0}
.state figure{margin:0}.state figure img{width:100%;border-radius:6px;background:var(--soft)}
.state figcaption{font-weight:700;margin-top:6px}.state .gallery{min-width:640px}
footer{margin-top:64px;padding-top:18px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px}
@keyframes pulse{50%{opacity:.4}}@keyframes grow{from{transform:scaleX(0)}}
@media(prefers-reduced-motion:reduce){*,:before,:after{animation:none!important;transition:none!important}html{scroll-behavior:auto}}
@media(max-width:760px){.meter{min-width:90px}.hero{grid-template-columns:1fr}.hero>img{width:120px}.mosaic{grid-template-columns:repeat(6,1fr)}
.state{grid-template-columns:1fr}.state figure img{max-width:200px}h1{font-size:32px}.sections a:first-child{margin-left:0}}
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
    """Relative link between pages of the published layout; `index` is the overview page."""
    return (("../" if PAGES[here] else "") + (f"{PAGES[target]}/" if PAGES[target] else "")) or "./"


def _head(zh: str, en: str) -> str:
    """Document head for a page named `zh` / `en`; the title follows the chosen language."""
    titles = {lang: e(f"{name} · 奶蛙bench", quote=True) for lang, name in (("zh", zh), ("en", en))}
    return (f"<!doctype html><!-- {CANARY} --><html lang=zh-CN data-titlezh='{titles['zh']}' "
            f"data-titleen='{titles['en']}'><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>{e(zh)} · {e(en)} · 奶蛙bench</title>"
            f"<style>{CSS}{LANG_CSS}</style>{LANG_SCRIPT}")


def _header(here: str, links: str, tabs: bool, up: str = "") -> str:
    """Page header; `up` prefixes the tab links of pages below a section's directory."""
    names = {"index": INDEX_NAME, "frontend": FRONTEND_NAME, "bill": BILL_NAME,
             **{s: SUITE_TEXT[s]["name"] for s in SUITES}}
    tab_html = ("<div class=tabs>" + "".join(
        f"<a href='{up}{_suite_href(here, page)}'{' aria-current=page' if page == here else ''}>"
        f"{bie(names[page])}</a>" for page in PAGES) + "</div>" if tabs else "")
    home = up + _suite_href(here, "index") if tabs else "#"
    return (f"<header class=top><div><a class=brand href='{home}'>奶蛙<span>BENCH</span></a>{tab_html}"
            f"<nav class=sections>{links}</nav>{LANG_SWITCH}</div></header><main>")


def _footer(repo_url: str | None, blob: str | None) -> str:
    repo = f" · <a href='{e(repo_url, quote=True)}'>{bi('源代码', 'Source')}</a>" if repo_url else ""
    sources = (f"<a href='{e(blob, quote=True)}/bench/reference/SOURCE.md'>SOURCE.md</a>" if blob
               else "bench/reference/SOURCE.md")
    return (f"<footer>奶蛙bench · nai-wai-bench{repo} · <span class=zh>参考图、表情包、二创与官方形象图的出处见 "
            f"{sources}，仅供非商业研究使用。</span><span class=en> Sources of the reference image, stickers, remixes, "
            f"and official artwork are listed in {sources}. For non-commercial research use.</span></footer></main></html>")


def _rank_cells(row: dict) -> tuple[str, str]:
    """A ranking row's class (the top three ranks get their own color) and its zero-padded rank cell."""
    rank = row["rank"]
    if rank is None:
        return "", "<td>–</td>"
    tier = f" class=t{rank}" if rank <= 3 else ""
    return tier, f"<td><span class=rank>{rank:02d}</span></td>"


def _ranking(rows: list[dict], label, flags: dict[str, str], judge_label, judged: bool = True) -> str:
    if not rows:
        return f"<p class=muted>{bi('本次运行没有这一题组的结果。', 'No results for this panel in this run.')}</p>"
    out = [f"<div class=scroll><table class=ranking><tr><th>{bi('名次', 'Rank', True)}</th><th>{bi('模型', 'Model')}</th>"
           f"<th>{bi('得分', 'Score')}<br>{bi('95% 区间', '95% interval')}</th>"
           f"<th>{bi('名次范围', 'Rank range', True)}</th><th class=n>{bi('已计分', 'Scored', True)}</th></tr>"]
    for row in rows:
        tier, rank = _rank_cells(row)
        interval = ""
        if row.get("score_interval"):
            lo, hi = row["score_interval"]
            interval = f"<span class=interval style='left:{lo:.3f}%;width:{hi - lo:.3f}%'></span>"
        meter = (f"<div class=meter><span class=track><span class=fill style='width:{row['score']:.1f}%'></span>"
                 f"{interval}</span><b>{score_text(row)}</b></div>" if row["score"] is not None else "–")
        chips = []
        if row["status"] != "complete":
            title = "; ".join(row.get("conditions", []))
            if row["status"] == "mixed conditions":
                title += "; diagnostic score " + fmt(row.get("diagnostic_score"), 1)
            chips.append(f"<span class='status{' mixed' if row['status'] == 'mixed conditions' else ''}' "
                         f"title='{e(title, quote=True)}'>{e(row['status'])}</span>")
        if row.get("settings_status") == "settings unrecorded":
            chips.append("<span class=status>settings unrecorded</span>")
        chips.extend(f"<span class=status>{e(p)}</span>" for p in row.get("collection_profiles", []))
        meta = f"<div class=row-meta>{' '.join(chips)}</div>" if chips else ""
        if judged:
            meta += f"<div class=row-meta>{bi('评审', 'Judges')}: {e(judge_text(row, judge_label))}</div>"
        out.append(f"<tr{tier}>{rank}<td><b>{model_html(label(row['model']))}</b>{flags.get(row['model'], '')}{meta}</td>"
                   f"<td>{meter}</td><td>{rank_range(row)}</td><td class=n>{row['completed']}/{row['required']} "
                   f"<span class=muted title='每格重复次数 · repetitions per cell'>×{row['repetitions']}</span></td></tr>")
    return "\n".join(out) + "</table></div>"


def _heat(value: float | None, note: str = "") -> str:
    """A 0–100 score cell shaded by its shortfall: the cell surface at 100, one warm hue at full strength at 0."""
    if value is None:
        return "<td class=heat>–</td>"
    miss = max(0.0, min(100.0, 100 - value))
    style = f"background:color-mix(in oklab,var(--heat) {miss:.0f}%,var(--cell))"
    return f"<td class='heat{' hi' if miss >= 75 else ''}' style='{style}'>{fmt(value)}{note}</td>"


HEAT_NOTE = bi("颜色越浓，分数越低。", "Stronger color marks lower scores.")


def _image_cell(s: dict | None, image: str | None, alt: str, scored: bool = True, meta: dict | None = None) -> str:
    """A gallery cell: the image (or the provider's refusal), its score when scored, its prompt audit, and
    a label when the record notes another route than the model's usual client (meta.fill_note)."""
    if not s:
        return "<td>–</td>"
    audit = {True: bi("原样传递", "Verbatim"), False: bi("提示词有改动", "Prompt changed"),
             None: bi("未核实", "Unverified")}[s["verbatim"]]
    score = f"<span class=score>{fmt(s['overall'])}</span>" if scored else ""
    if not image:
        return (f"<td><div class=refused>{bi('服务商拒绝生成', 'Refused by provider', True)}</div>{score}"
                f"<div class=muted>{audit}</div></td>")
    why = " | ".join(f"{j}: {r}" for j, r in s["rationales"].items())
    tags = "".join(f"<div class=tag>{bi(e(FAILURE_ZH[f]), e(f.replace('_', ' ')))}</div>" if f in FAILURE_ZH
                   else f"<div class=tag>{e(f)}</div>" for f in s["failure_modes"])
    if (meta or {}).get("fill_note"):
        tags += (f"<div class=muted title='{e(meta['fill_note'], quote=True)} · {e(meta.get('model', ''), quote=True)}'>"
                 f"{bi('补图', 'Filled')} · via {e(meta.get('client', '?'))}</div>")
    return (f"<td title='{e(why, quote=True)}'><a href='{e(image)}'><img loading=lazy src='{e(image)}' alt='{e(alt)}'></a>"
            f"{score}{tags}<div class=muted>{audit}</div></td>")


def _summary_table(usum: dict, label) -> str:
    """Understanding diagnostics per model; columns without any value in this run are left out."""
    optional = [
        (("文字", "Text"), lambda s: s.get("text"), 0),
        (("中文", "Text ZH"), lambda s: s.get("languages", {}).get("zh"), 0),
        (("英文", "Text EN"), lambda s: s.get("languages", {}).get("en"), 0),
        (("视觉核对", "Grounding"), lambda s: s.get("grounding"), 0), (("无图", "No image"), lambda s: s.get("blind"), 0),
        (("视觉增益", "Visual gain"), lambda s: s.get("visual_gain"), 0),
        (("每答幻觉", "Halluc./answer"), lambda s: s.get("hallucinations_per_answer"), 1),
    ]
    # Grounding repeats the vision mean when every image item is answer-keyed.
    if all(s.get("grounding") == s.get("vision") for s in usum.values()):
        optional = [c for c in optional if c[0][1] != "Grounding"]
    shown = ([(("看图", "Vision"), lambda s: s.get("vision"), 0)]
             + [c for c in optional if any(c[1](s) is not None for s in usum.values())])
    out = [f"<div class='scroll card-table'><table><tr><th>{bi('模型', 'Model')}</th>"
           + "".join(f"<th class=n>{bie(h, True)}</th>" for h, _, _ in shown)
           + f"<th class=n>{bi('用了工具', 'Used tools', True)}</th></tr>"]
    for m, s in sorted(usum.items(), key=lambda kv: (-(kv[1].get("vision") or 0), kv[0])):
        out.append(f"<tr><td>{e(label(m))}</td>" + "".join(f"<td class=n>{fmt(f(s), d)}</td>" for _, f, d in shown)
                   + f"<td class=n>{s['contaminated']}</td></tr>")
    out.append("</table></div><p class=muted><span class=zh>视觉增益 = 有图得分 − 无图得分（按题目和重复配对，单位为百分点）。"
               "用了工具：违反要求调用了工具的回答，不计分。</span><span class=en> Visual gain is the matched with-image minus "
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
    out = [f"<h3>{bi('逐项诊断', 'Answer-key diagnostics')}</h3><div class='scroll card-table'><table>"
           f"<tr><th>{bi('模型', 'Model')}</th><th class=n>{bi('全对', 'Joint', True)}</th>"
           f"<th class=n>{bi('视觉全对', 'Visual joint', True)}</th><th class=n>{bi('类别宏平均', 'Family macro', True)}</th>"
           f"<th>{bi('重复一致性', 'Repetition consistency')}<br>{bi('（图片数）', '(images)')}</th>"
           + "".join(f"<th class=n>{bi(e(FIELD_ZH.get(f, f)), e(f), True)}</th>" for f in fields) + "</tr>"]
    for m in order:
        s = rows[m]
        classes = f" <small>({len(s['family_classes'])})</small>" if len(s["family_classes"]) < labels else ""
        out.append(f"<tr><td>{e(label(m))}</td>{_heat(s['joint'])}{_heat(s['visual_joint'])}"
                   f"{_heat(s['family_macro'], note=classes)}"
                   f"<td>{fmt(s.get('repetition_consistency'), 1)} ({s.get('repetition_consistency_images', 0)})</td>"
                   + "".join(_heat(s["fields"].get(f), note=f" <small>({s['field_items'][f]})</small>"
                                   if s["field_items"].get(f, 0) < full else "") for f in fields) + "</tr>")
    out.append(f"</table></div><p class=muted><span class=zh>0–100，每张图权重相同。全对：七项全部正确；视觉全对：除类别外全部正确；"
               f"类别宏平均：各类别召回率的等权平均；括号内为不足 {full} 张图或 {labels} 个类别时的实际覆盖。</span>"
               "<span class=en> 0–100, equal weight per image. Joint: every field correct; visual joint: every field "
               "except family; family macro: equal-weight recall over the expected family labels. Parentheses show "
               f"item or label coverage when below {full} items or {labels} labels.</span> {HEAT_NOTE}</p>")
    categories = sorted({c for s in rows.values() for c in s.get("categories", {})}, key=_category_order)
    if categories:
        out.append(f"<div class='scroll card-table'><table><tr><th>{bi('模型', 'Model')}</th>"
                   + "".join(f"<th class=n>{bie(CATEGORY.get(c, (c, c)), True)}</th>" for c in categories) + "</tr>")
        for m in order:
            out.append(f"<tr><td>{e(label(m))}</td>"
                       + "".join(_heat(rows[m]["categories"].get(c)) for c in categories) + "</tr>")
        out.append("</table></div><p class=muted>" + bi("按图片类别的部分得分均值（每项字段等分）。",
                                                         "Partial-credit means by slice (equal credit per field).") + "</p>")
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
        n = len(groups[group])
        out.append((f"<div class=group><h3>{bie(CATEGORY.get(group, (group, group)))}</h3>"
                    f"<span class=muted>{bi(f'{n} 张图', f'{n} images')}</span></div>" if group else "")
                   + "<div class=cases>" + "".join(_case(item, first, rank, label, asset) for item in groups[group])
                   + "</div>")
    return "\n".join(out)


def _case(item: UnderstandingItem, first: dict, rank: dict, label, asset) -> str:
    """A casebook card; `first` maps (item id, model) to the sample shown for that model."""
    models = sorted({m for (i, m) in first if i == item.id}, key=lambda m: (rank.get(m, len(rank)), m))
    image = asset(item.images[0])
    case = item.id.split(".", 1)[1]
    title = item.title or case
    chips = "".join(f"<span class=chip><small>{bi(e(FIELD_ZH.get(f, f)), e(f))}</small>{e(v)}</span>"
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
            misses = f"<span class=miss>{bi('无法解析', 'unparseable')}</span>"
        else:
            misses = "".join(f"<span class=miss>{e(f)} <code>{e(str(reply.get(f, '–')))}</code></span>"
                             for f, v in s["fields"].items() if v != 100)
        mark = "<span class=mark-ok>✓</span>" if ok else "<span class=mark-no>✗</span>"
        who.append(f"<li>{mark} <b>{e(label(m))}</b> <span class=muted>{right}/{len(s['fields'])}</span><br>{misses}</li>")
        blind = first.get((f"{item.id}.blind", m))
        raw.append(f"<b>{e(label(m))}</b><div class=raw>{e(s['answer'])}</div>"
                   + (f"<span class=muted>{bi('无图对照', 'No image')}</span><div class=raw>{e(blind['answer'])}</div>"
                      if blind else ""))
    # Models that only answered the no-image control (text-only models, failed visual cells) get no verdict,
    # but their replies still count toward the No image score, so show them.
    for m in sorted({m for (i, m) in first if i == f"{item.id}.blind"} - set(models),
                    key=lambda m: (rank.get(m, len(rank)), m)):
        raw.append(f"<b>{e(label(m))}</b> <span class=muted>{bi('无图对照', 'No image')}</span>"
                   f"<div class=raw>{e(first[(f'{item.id}.blind', m)]['answer'])}</div>")
    note = f"<p class=muted>{e(item.image_note)}</p>" if item.image_note else ""
    return (
        f"<article class=case id='case-{e(case)}'><a href='{e(image)}'><img loading=lazy src='{e(image)}' "
        f"alt='{e(title)}'></a><div><div class=case-title>{e(title)} <span>{e(case)}</span></div>"
        f"<div class=chips>{chips}</div><div class=verdict><span class=segs>{''.join(segs)}</span>"
        f"<b>{n_ok}/{len(models)}</b><span class=muted>{bi('全对', 'all correct')}</span></div>"
        f"<details><summary>{bi('逐模型', 'Per model')}</summary>{note}<ul class=who>{''.join(who)}</ul>"
        f"<details><summary>{bi('原始回答', 'Raw replies')}</summary>{''.join(raw)}</details></details></div></article>")


def build(bench: Bench, models: dict[str, ModelSpec], run_dir: Path, scores: dict, out: Path,
          repo_url: str | None = None, suite_tabs: bool = False, bundle_url: str | None = None) -> Path:
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
        return scores.get("labels", {}).get(m, models[m].label if m in models else m)

    boards = scores.get("leaderboards", {})
    vision_order = [r["model"] for r in boards.get("visual_understanding", [])]
    # An image item is shown when it or its no-image control has a sample.
    sampled = {s.get("control_for") or s["item"] for s in und_samples}
    keyed = [i for i in bench.items if i.modality == "vision" and i.answers and i.id in sampled]
    state_keyed = [i for i in bench.state_items if i.modality == "vision" and i.id in sampled]
    core_tiers = [t for t in bench.tiers.values() if any(t.id == s["tier"] for s in img_samples)]
    state_samples = [s for s in img_samples if s["state"]]
    # Image generation and state transfer are experimental side tracks, kept after the understanding results.
    sections = ["rankings", "casebook", "understanding", "efficiency", "gallery", "states", "models", "judges"]
    present = {"rankings": True, "casebook": bool(keyed), "gallery": bool(core_tiers), "states": bool(state_samples),
               "understanding": bool(und_samples), "efficiency": True, "models": True, "judges": bool(scores.get("judge_health"))}
    nav_text = {"rankings": ("排名", "Ranking"), "casebook": ("图鉴", "Casebook"), "gallery": ("图像生成", "Image gen"),
                "states": ("姿势迁移", "Transfer"), "understanding": ("理解", "Understanding"), "models": ("模型", "Models"),
                "judges": ("评审", "Judges"), "efficiency": ("效率", "Efficiency")}

    revision = _revision(bench.root)
    # Link the documentation of the exact commit the results were built from.
    blob = f"{repo_url}/blob/{revision.split()[0]}" if repo_url and revision else None
    html = [_head(*text["name"])]
    links = "".join(f"<a href='#{s}'>{bie(nav_text[s])}</a>" for s in sections if present[s])
    links += f"<a href='{e(blob, quote=True)}/docs/methodology.md'>{bi('方法', 'Methodology')}</a>" if blob else ""
    if bundle_url:
        links += f"<a href='{e(bundle_url, quote=True)}'>{bi('下载原始结果', 'Download raw results')}</a>"
    html.append(_header(bench.suite, links, suite_tabs))

    # --- hero ---
    stamp = (e(collection_text(scores)) + f" · suite <code>{e(bench.suite)}</code> · run <code>{e(run_dir.name)}</code>"
             f" · {datetime.date.today().isoformat()}")
    stamp += f" · revision <code>{e(revision)}</code>" if revision else ""
    mosaic = bool(keyed) and text["mosaic"]
    portrait = "" if mosaic else f"<img src='{e(asset(bench.reference_image))}' alt='大笑奶龙'>"
    html.append(f"<div class='hero{' solo' if mosaic else ''}'>{portrait}<div>"
                f"<h1>{bie(text['name'])}</h1><p class=lede>{bie(text['intro'], True)}</p>"
                f"<span class=badge>{e(__version__)} {bi('首个版本', 'First release')}</span> <span class=stamp>{stamp}</span></div></div>")
    if mosaic:
        html.append("<div class=mosaic>" + "".join(
            f"<a href='#case-{e(i.id.split('.', 1)[1])}' title='{e(i.title)}'>"
            f"<img src='{e(asset(i.images[0]))}' alt='{e(i.title)}'></a>" for i in keyed) + "</div>")
    annotated = ("答案键由 GPT-6-Astra 标注、尚未经人工校验，所以 Astra 的得分只反映与自己标注的一致程度。"
                 if bench.annotator else "")
    annotated_en = ("Answer keys are GPT-6-Astra annotations not yet checked by a person, so Astra's score measures "
                    "agreement with its own labels. " if bench.annotator else "")
    counts = (f"共 {len(img_samples)} 个生成样本、{len(und_samples)} 条回答。" if img_samples
              else f"共 {len(und_samples)} 条回答。")
    counts_en = (f"{len(img_samples)} generation samples and {len(und_samples)} answers. " if img_samples
                 else f"{len(und_samples)} answers. ")
    html.append(
        f"<div class=note><span class=zh>0.1.0 版结果：{counts}"
        "自由回答与标准图像生成优先采用其他厂商的 LLM 评审；没有独立评审时使用现有评审。看图核对题按答案键本地计分。"
        f"{annotated}方括号是 95% 自助法区间，名次范围表示重抽样时名次的波动；区间大幅重叠的模型不宜硬分高下。"
        "只有在同一设置下完整跑完固定题组的模型才有名次。</span><span class=en><br>"
        f"Release 0.1.0 results: {counts_en}"
        "Free-form answers and standard generation prefer LLM judges from other vendors, falling back to available judges; "
        f"answer-keyed checks are scored locally. {annotated_en}"
        "Brackets show 95% bootstrap intervals, and the rank range shows how a rank moves under resampling; "
        "models whose intervals largely overlap are not clearly ordered. "
        "Only models that complete the fixed panel under one setting are ranked.</span></div>")
    profiles = collection_profiles_text(scores)
    if profiles:
        html.append(f"<p class=note>{e(profiles)}</p>")

    body = {"efficiency": efficiency_section(scores, label)}
    # --- rankings ---
    panel_animals = bench.select_animals("default")
    vision_items = [i for i in bench.items if i.modality == "vision"]
    grounding = sum(1 for i in vision_items if i.answers)
    flags = ({bench.annotator: f"<br><span class=flag>{bi('答案键标注者', 'Key annotator')}</span>"}
             if bench.annotator else {})
    joint = (bi("七项全部答对才得分。", "All seven fields must be correct for a sample to score.")
             if bench.suite == "naihub-v1" else "")
    judge_label = lambda m: models[m].label if m in models else m
    total = sum(INDEX_WEIGHTS.values())
    weight = (f"<span class=zh>计入奶蛙指数，权重 {INDEX_WEIGHTS[bench.suite]}/{total}。</span>"
              f"<span class=en>Weight {INDEX_WEIGHTS[bench.suite]}/{total} in the "
              f"<a href='{_suite_href(bench.suite, 'index')}'>NaiWai Index</a>. </span>" if suite_tabs else "")
    body["rankings"] = (
        f"<h2 id=rankings>{bi(e(text['name'][0]) + '排名', e(text['name'][1]) + ' ranking')}</h2>"
        "<div class=panel>"
        f"<p class=muted><span class=zh>固定题组：{len(vision_items)} 道看图题（{len(vision_items) - grounding} 道自由回答识别、"
        f"{grounding} 道按答案键计分的视觉核对）。文字知识与无图对照只作诊断。</span>{joint}<span class=en><br>Fixed panel: "
        f"{len(vision_items)} image-input tasks ({len(vision_items) - grounding} free-form recognition, {grounding} "
        "answer-keyed grounding checks). Text knowledge and no-image controls are diagnostics.</span></p>"
        + _ranking(boards.get("visual_understanding", []), label, flags, judge_label, len(vision_items) > grounding)
        + f"</div><p class=muted>{weight}<span class=zh>有缺失、失败、未评分或不合格格子的模型不参与排名；×N 为每格重复次数。</span>"
        "<span class=en>Missing, failed, unjudged, or ineligible cells leave a model unranked; ×N is "
        "repetitions per cell.</span></p>"
        + f"<p class=muted>{UNCERTAINTY_NOTE}</p>"
        + f"<p class=muted>{e(stale_text(scores))}Collection revisions: "
          f"{e(', '.join(scores.get('collection', {}).get('revisions', [])) or 'unrecorded')}.</p>")

    # --- casebook ---
    if keyed:
        body["casebook"] = (
            f"<h2 id=casebook>{bi('图鉴', 'Casebook')}</h2>"
            "<p><span class=zh>每张图都问同一个问题，要求按固定标签返回 JSON，再在本地与答案键逐项比对。色条每格代表一个模型"
            "（按视觉理解排名排序）：绿色为全部答对，红色为至少错一项。展开卡片可看每个模型错在哪里，以及原始回答。</span>"
            "<span class=en><br>Every image gets the same question, answered as JSON with fixed labels and compared "
            "field by field with a local key. Each strip segment is one model, in visual-ranking order: green means "
            "every field is right, red means at least one miss. Open a card for each model's misses and raw "
            "replies.</span></p>" + _casebook(keyed, und_samples, vision_order, label, asset))

    # --- image generation ---
    summary = scores["imagegen"]
    by_cell = {(s["model"], s["animal"], s["tier"]): s for s in sorted(img_samples, key=lambda s: -s["rep"])}
    img_models = sorted({s["model"] for s in img_samples}, key=lambda m: (-(summary.get(m, {}).get("overall") or 0), m))
    if core_tiers:
        part = [f"<h2 id=gallery>{bi('图像生成（实验）', 'Experimental · image generation')}</h2>"
                "<p><span class=zh>让模型画“⟨动物⟩版的大笑奶龙”，提示词分五档。评审对照原图，按 9 项加权视觉特征打分，"
                "再乘以能否认出目标动物（0–100）。这是实验项目，不计入奶蛙指数。</span><span class=en><br>Models draw an "
                "animal version of the meme from five prompt tiers. Judges compare each image with the reference on "
                "nine weighted visual traits, scaled by whether the target animal is recognizable (0–100). This "
                "experimental track does not enter the NaiWai Index.</span></p>",
                f"<h3>{bi('图像生成排名', 'Image generation ranking')}</h3>"
                f"<p class=muted><span class=zh>固定题组：{len(panel_animals)} 种动物 × {len(bench.tiers)} 档提示词；"
                "只计入核实为原样传递的提示词，服务商拒绝生成记 0 分。</span><span class=en><br>Fixed panel: "
                f"{len(panel_animals)} animals × {len(bench.tiers)} prompt tiers; verified verbatim prompts only. "
                "Provider refusals score 0.</span></p>"
                + _ranking(boards.get("imagegen", []), label, {}, judge_label),
                f"<details><summary>{bi('提示词', 'Prompts')}</summary><table><tr><th>{bi('档位', 'Tier')}</th>"
                f"<th>{bi('提示词（以猫为例）', 'Prompt (cat)')}</th></tr>"]
        cat = bench.animals.get("cat") or next(iter(bench.animals.values()))
        for t in core_tiers:
            extra = bi("（附原图）", "(+ reference image)") if t.reference else ""
            part.append(f"<tr><td><b>{bi(e(t.title_zh), e(t.title_en))}</b><br><span class=muted>{e(t.id)}</span></td>"
                        f"<td class=ans>{e(t.render(cat))}{extra}</td></tr>")
        part.append("</table></details>")
        for a in [a for a in bench.animals if any(s["animal"] == a and not s["state"] for s in img_samples)]:
            animal = bench.animals[a]
            part.append(f"<h3>{bi(e(animal.zh), e(animal.en))}</h3><div class='scroll card-table'>"
                        "<table class=gallery><tr><th style='width:150px'></th>"
                        + "".join(f"<th>{bi(e(t.title_zh), e(t.title_en), True)}</th>" for t in core_tiers)
                        + "</tr>")
            for m in img_models:
                cells = []
                for t in core_tiers:
                    s = by_cell.get((m, a, t.id))
                    cells.append(_image_cell(s, s and generated(s), f"{label(m)} {t.id} {a}",
                                             meta=s and meta_of[s["target"]]))
                part.append(f"<tr><td><b>{e(label(m))}</b></td>{''.join(cells)}</tr>")
            part.append("</table></div>")
        part.append(f"<h3>{bi('诊断汇总', 'Diagnostics')}</h3><div class='scroll card-table'><table><tr><th>{bi('模型', 'Model')}</th>"
                    f"<th class=n>{bi('已有格子均分', 'Available-cell mean', True)}</th>"
                    + "".join(f"<th class=n>{bi(e(t.title_zh), e(t.title_en))}</th>" for t in core_tiers)
                    + f"<th class=n>{bi('知识比率', 'Knowledge ratio', True)}</th></tr>")
        for m in img_models:
            if m not in summary:
                continue
            s = summary[m]
            part.append(f"<tr><td>{e(label(m))}</td>{_heat(s['overall'])}"
                        + "".join(_heat(s["tiers"].get(t.id, {}).get("overall")) for t in core_tiers)
                        + f"<td class=n>{fmt(s['knowledge_ratio'], 2)}</td></tr>")
        part.append("</table></div><p class=muted><span class=zh>知识比率 = 两个“只给梗名”档的均分 ÷ “详细描述”档的均分，只比较三档都有结果的相同动物；"
                    "它反映对提示词详细程度的敏感度，不是“认识这个梗”的概率。诊断均分可能与固定排名题组不同。</span>"
                    "<span class=en> Knowledge ratio = mean of both name tiers ÷ detailed-description tier, on "
                    "matched animals only. It is prompt sensitivity, not a calibrated probability of knowledge. "
                    "Diagnostic means may differ from the fixed ranking panel.</span> " + HEAT_NOTE + "</p>")
        body["gallery"] = "\n".join(part)

    # --- optional state transfer ---
    if state_samples:
        part = [f"<h2 id=states>{bi('姿势迁移（可选，不计分）', 'Optional state transfer · unscored')}</h2>"
                "<p><span class=zh>把奶蛙源图的可见表情、动作和姿势迁移到别的动物身上。每张源图有两种条件："
                "只给固定的文字描述，或附上源图。这部分不由 LLM 评分，也不计入排名，请对照源图分别查看表情、动作、"
                "动物辨识度和渲染风格。</span><span class=en><br>Visible expressions, gestures, and postures from 奶蛙 source "
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
            prompts = "".join(f"<tr><td style='width:120px'><b>{bie(CONDITION[c])}</b></td>"
                              f"<td class=ans>{e(t.render(cat))}</td></tr>"
                              for c, t in conditions.items())
            part.append(
                f"<div class=state id='state-{e(state)}'><figure><a href='{e(source)}'><img src='{e(source)}' "
                f"alt='Source: {e(state)}'></a><figcaption>{bi(e(title_zh), e(title_en))}"
                f"</figcaption><span class=muted>{bi('源图', 'Source')}</span></figure><div style='min-width:0'>"
                "<div class=scroll><table class=gallery><tr><th style='width:130px'></th>"
                + "".join(f"<th>{bi(f'{e(bench.animals[a].zh)} · {CONDITION[c][0]}', f'{e(bench.animals[a].en)} · {CONDITION[c][1]}', True)}</th>"
                          for a, c, _ in columns)
                + f"</tr>{''.join(rows)}</table></div><details><summary>{bi('提示词', 'Prompts')}</summary><table>{prompts}"
                "</table></details></div></div>")
        body["states"] = "\n".join(part)

    # --- understanding ---
    if und_samples:
        part = [f"<h2 id=understanding>{bi('理解诊断', 'Understanding diagnostics')}</h2>"
                "<p><span class=zh>不允许联网或使用工具。自由回答的识别题和文字题对照有出处的事实，由评审团打分，每条言之凿凿的幻觉扣 10 分；"
                "视觉核对题按答案键在本地计分。</span><span class=en><br>No web or tools. Recognition and text answers are "
                "scored by the judge panel against sourced facts, with 10 points off per confident hallucination; "
                "structured checks use local answer keys.</span></p>"]
        for states in (False, True):
            selected = [s for s in und_samples if bool(s.get("state")) == states]
            if not selected:
                continue
            usum = scores.get("state_understanding" if states else "understanding", {})
            if states:
                part.append(f"<h3>{bi('表情状态提取（可选，按答案键计分）', 'Optional state extraction · answer-keyed')}"
                            "</h3><p class=muted><span class=zh>同一提问分别在有图和无图时作答，按所选题组的类别与可见特征答案键计分；"
                            "不影响任何排名。</span><span class=en> The same question with and without the source image, "
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
                part.append(f"<h3>{bi('自由回答', 'Free-form answers')}</h3>")
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
        roles[s["model"]].add(("图像生成", "Image generation"))
    for s in und_samples:
        roles[s["model"]].add(("理解", "Understanding"))
    for j in scores["judges"]:
        roles[j].add(("评审", "Judge"))
    if bench.annotator:
        roles[bench.annotator].add(("答案键标注", "Key annotator"))
    first_meta = {}
    for s in img_samples + und_samples:
        first_meta.setdefault(s["model"], meta_of[s["target"]])
    part = [f"<h2 id=models>{bi('参测模型', 'Models')}</h2><div class='scroll card-table'><table><tr><th>{bi('模型', 'Model')}</th>"
            f"<th>{bi('角色', 'Role')}</th><th>{bi('调用方式', 'Access')}</th><th>{bi('图像来源凭证', 'C2PA provenance')}</th></tr>"]
    for m in sorted(roles, key=lambda m: (min(roles[m]), m)):
        meta = first_meta.get(m, {})
        c2pa = _c2pa(meta) if any(r[1] == "Image generation" for r in roles[m]) else "–"
        part.append(f"<tr><td><b>{e(label(m))}</b><br><span class=muted>{e(m)}</span></td>"
                    f"<td>{'<br>'.join(bie(r) for r in sorted(roles[m]))}</td><td>{_access(models.get(m), meta)}</td><td>{c2pa}</td></tr>")
    part.append("</table></div><p class=muted><span class=zh>图片内嵌的 C2PA 内容凭证声明的生成器：OpenAI 标注为 "
                "<code>ChatGPT · gpt-image</code>，Google 只标注“由 Google 生成式 AI 创建”并加有 SynthID 水印，"
                "两家都未公开更细的版本号。图像生成由 Agent 中转：上表“调用方式”中的模型负责把提示词原样交给图像工具，"
                "内容凭证仅供参考，未验证签名；逐字核对的结果列于图片下方。</span><span class=en><br>Vendor-declared generators are read from each image's C2PA "
                "content credentials, which name only “ChatGPT · gpt-image” (OpenAI) and “Created by Google Generative AI” "
                "(Google); neither exposes a more specific image model version. Signatures are not verified. "
                "The listed relay model forwards prompts to the image tool; audit results appear under each image.</span></p>")
    body["models"] = "\n".join(part)

    # --- judges ---
    if present["judges"]:
        part = [f"<h2 id=judges>{bi('评审', 'Judges')}</h2><p><span class=zh>每个样本由其他厂商的评审打分后取平均；没有独立评审时使用现有评审。"
                "下表是评审的健康度：分数离散度太低说明评审分不出好坏，与其他评审差距太大说明意见不一致。</span>"
                "<span class=en><br>Each sample is averaged over judges from other vendors, falling back to the available "
                "panel when none are independent. Spread: how much a judge's scores vary; distance: how far it sits "
                "from the other judges.</span></p><div class='scroll card-table'><table>"
                f"<tr><th>{bi('评审', 'Judge')}</th><th>{bi('部分', 'Track')}</th><th class=n>{bi('样本', 'Samples')}</th>"
                f"<th class=n>{bi('离散度', 'Spread')}</th><th class=n>{bi('与其他评审差距', 'Distance')}</th></tr>"]
        for j, tracks in scores["judge_health"].items():
            for track, h in tracks.items():
                part.append(f"<tr><td>{e(label(j))}</td><td>{e(track)}</td><td class=n>{h['n']}</td>"
                            f"<td class=n>{fmt(h['spread'], 1)}</td><td class=n>{fmt(h['deviation'], 1)}</td></tr>")
        part.append("</table></div>")
        body["judges"] = "\n".join(part)

    html += [body[s] for s in sections if s in body]
    html.append(_footer(repo_url, blob))
    index = out / "index.html"
    index.write_text("\n".join(html), encoding="utf-8")
    return index


def build_index(suites: dict[str, tuple[Bench, dict]], index: dict, models: dict[str, ModelSpec], out: Path,
                repo_url: str | None = None, bill: tuple[dict, dict] | None = None) -> Path:
    """Release overview page: the NaiWai Index, then each component ranking linking to its suite page.

    `bill` is the token bill summary and contribution ranking; with it the page shows the total and
    links to the bill page."""
    from nwb import bill_site  # imported here: bill_site builds on this module's page chrome
    (out / "images").mkdir(parents=True, exist_ok=True)
    root = next(iter(suites.values()))[0].root
    reference = suites["core"][0].reference_image
    portrait = _copy_image(reference, out, "images/bench/" + reference.relative_to(root / "bench").with_suffix("").as_posix())
    labels = {m: label for _, scores in suites.values() for m, label in scores.get("labels", {}).items()}
    label = lambda m: labels.get(m, models[m].label if m in models else m)
    judge_label = lambda m: models[m].label if m in models else m
    revision = _revision(root)
    blob = f"{repo_url}/blob/{revision.split()[0]}" if repo_url and revision else None
    total = sum(index["weights"].values())
    annotators = {bench.annotator for bench, _ in suites.values() if bench.annotator}

    links = f"<a href='#index'>{bi('指数', 'Index')}</a><a href='#components'>{bi('组成排名', 'Components')}</a>"
    links += f"<a href='#bill'>{bie(BILL_NAME)}</a>" if bill else ""
    links += f"<a href='{e(blob, quote=True)}/docs/methodology.md#naiwai-index'>{bi('方法', 'Methodology')}</a>" if blob else ""
    html = [_head(*INDEX_NAME) + (f"<style>{bill_site.CSS}</style>" if bill else ""),
            _header("index", links, True)]
    weights_zh = "、".join(f"{SUITE_TEXT[s]['name'][0]} {w}/{total}" for s, w in index["weights"].items())
    weights_en = ", ".join(f"{SUITE_TEXT[s]['name'][1]} {w}/{total}" for s, w in index["weights"].items())
    html.append(
        f"<div class=hero><img src='{e(portrait)}' alt='大笑奶龙'><div>"
        f"<h1>{bie(INDEX_NAME)}</h1>"
        "<p class=lede><span class=zh>AI 模型对中文网络梗“大笑奶龙”（又称“奶蛙”）看得有多懂？奶蛙指数合并两个独立的看图排名："
        "识梗（认出梗和变体、说出别名、分清官方奶龙）与看图（逐项看清数量、姿态、表情、手势和眼泪）。</span>"
        "<span class=en><br>How well do AI models understand images of the Chinese meme 大笑奶龙 (Laughing Nailong, "
        "also called 奶蛙)? The NaiWai Index combines two independent visual rankings: Meme ID (recognize the meme "
        "and its variants, name its aliases, tell it from official Nailong) and Visual detail (read subject count, "
        "posture, expression, gesture, and tears field by field).</span></p>"
        f"<span class=badge>{e(__version__)} {bi('首个版本', 'First release')}</span> "
        + (bill_site.chip(bill[0], "#bill") + " " if bill else "") + f"<span class=stamp>index v{index['version']}"
        f" · {datetime.date.today().isoformat()}" + (f" · revision <code>{e(revision)}</code>" if revision else "")
        + "</span></div></div>")

    out_rows = [f"<div class=scroll><table class=ranking><tr><th>{bi('名次', 'Rank', True)}</th><th>{bi('模型', 'Model')}</th>"
                f"<th>{bi('指数', 'Index')}<br>{bi('95% 区间', '95% interval')}</th><th>{bi('名次范围', 'Rank range', True)}</th>"
                + "".join(f"<th class=n><a href='{_suite_href('index', s)}'>{bie(SUITE_TEXT[s]['name'], True)}</a>"
                          f" ×{w}</th>" for s, w in index["weights"].items())
                + "</tr>"]
    for row in index["rows"]:
        tier, rank = _rank_cells(row)
        interval = ""
        if row["score_interval"]:
            lo, hi = row["score_interval"]
            interval = f"<span class=interval style='left:{lo:.3f}%;width:{hi - lo:.3f}%'></span>"
        meter = (f"<div class=meter><span class=track><span class=fill style='width:{row['score']:.1f}%'></span>"
                 f"{interval}</span><b>{score_text(row)}</b></div>" if row["score"] is not None else "–")
        meta = ("<div class=row-meta><span class=status>partial</span></div>" if row["status"] != "complete" else "")
        flag = f"<br><span class=flag>{bi('答案键标注者', 'Key annotator')}</span>" if row["model"] in annotators else ""
        parts = "".join(f"<td class=n>{fmt(c['score'], 1)}"
                        + (f" <span class=muted>#{c['rank']}</span>" if c["rank"] is not None else "") + "</td>"
                        for c in row["components"].values())
        out_rows.append(f"<tr{tier}>{rank}<td><b>{model_html(label(row['model']))}</b>{flag}{meta}</td>"
                        f"<td>{meter}</td><td>{rank_range(row)}</td>{parts}</tr>")
    html.append(
        f"<h2 id=index>{bie(INDEX_NAME)}</h2>"
        "<div class=panel>" + "\n".join(out_rows) + "</table></div></div>"
        f"<p class=muted><span class=zh>指数 = 两个排名得分的加权平均（{weights_zh}）。看图是答案键本地计分的较大题组，权重加倍；"
        "识梗包含 LLM 评审的自由回答。两项都完整排名的模型才有指数名次。两个分数的尺度不同：识梗是逐项部分得分，"
        "看图要求七项全对，所以指数只用于排序，不是正确率。</span><span class=en> Index = weighted mean of the two ranking "
        f"scores ({weights_en}). Visual detail is the larger panel, scored locally against answer keys, and counts "
        "double; Meme ID includes LLM-judged free-form answers. Only models ranked in both components receive an "
        "index rank. The scales differ (Meme ID awards partial credit; Visual detail requires all seven fields), so "
        "the index orders models and is not an accuracy.</span></p>"
        "<p class=muted><span class=zh>区间与名次范围来自两个题组各自独立的 2,000 次聚类自助重抽样，按序号配对后加权。</span>"
        "<span class=en> Intervals and rank ranges pair each component's independent 2,000 cluster-bootstrap draws "
        "by draw number before weighting.</span> " + UNCERTAINTY_NOTE + "</p>"
        + ("<p class=muted><span class=zh>看图的答案键由 GPT-6-Astra 标注、尚未经人工校验，Astra 的看图得分只反映与自己标注的一致程度。</span>"
           "<span class=en> Visual detail answer keys are GPT-6-Astra annotations not yet checked by a person, so "
           "Astra's Visual detail score measures agreement with its own labels.</span></p>" if annotators else ""))

    panels = []
    for suite in index["weights"]:
        bench, scores = suites[suite]
        name = SUITE_TEXT[suite]["name"]
        vision_items = [i for i in bench.items if i.modality == "vision"]
        flags = ({bench.annotator: f"<br><span class=flag>{bi('答案键标注者', 'Key annotator')}</span>"} if bench.annotator else {})
        panels.append(
            f"<div class=panel><h3><a href='{_suite_href('index', suite)}'>"
            f"{bi(e(name[0]) + '排名', e(name[1]) + ' ranking')}</a></h3>"
            f"<p class=muted>{bi(f'{len(vision_items)} 道看图题', f'{len(vision_items)} image tasks')} · suite "
            f"<code>{e(suite)}</code></p>"
            + _ranking(scores["leaderboards"].get("visual_understanding", []), label, flags, judge_label,
                       any(not i.answers for i in vision_items)) + "</div>")
    imagegen = bool(suites["core"][1]["samples"]["imagegen"])
    html.append(
        f"<h2 id=components>{bi('组成排名', 'Component rankings')}</h2><div class=panels>"
        + "".join(panels) + "</div>"
        + ("<p class=muted><span class=zh>图像生成是实验项目，不计入指数，见"
           f"<a href='{_suite_href('index', 'core')}#gallery'>识梗页的图像生成部分</a>。</span><span class=en> Image "
           f"generation is an experimental track outside the index; see the <a href='{_suite_href('index', 'core')}#gallery'>"
           "Meme ID page</a>.</span></p>" if imagegen else "")
        + "<p class=muted><span class=zh>前端复刻（用 SVG 和 three.js 手写网页复刻奶蛙动图）也是实验项目，不计入指数，见"
        f"<a href='{_suite_href('index', 'frontend')}'>复刻页</a>。</span><span class=en> The "
        f"<a href='{_suite_href('index', 'frontend')}'>frontend rebuild track</a> (hand-written SVG and three.js pages "
        "that recreate 奶蛙 GIFs) is experimental and outside the index too.</span></p>")
    if bill:
        html.append(bill_site.index_section(*bill))
    html.append(_footer(repo_url, blob))
    page = out / "index.html"
    page.write_text("\n".join(html), encoding="utf-8")
    return page


def write_redirects(out: Path) -> None:
    """Small pages at earlier published suite paths that forward to the current suite pages."""
    for suite, old in REDIRECTS.items():
        target = f"../{PAGES[suite]}/"
        (out / old).mkdir(parents=True, exist_ok=True)
        (out / old / "index.html").write_text(
            f"<!doctype html><meta charset=utf-8><title>Moved</title><meta http-equiv=refresh content='0; url={target}'>"
            f"<link rel=canonical href='{target}'><p><a href='{target}'>{e(SUITE_TEXT[suite]['name'][1])}</a></p>",
            encoding="utf-8")

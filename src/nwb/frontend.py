"""Experimental frontend track: models rebuild animated GIFs as inline SVG or three.js pages.

The pipeline is collect (subject calls) -> render (sandboxed Chromium, `nwb.frontend_render`) -> report
(gate summary and a gallery for human review). Samples are stored as
runs/<run>/frontend/<model>/<task>/<kind>__r<rep>.json and renders in the directory with the same stem.
Every stage resumes like the other tracks.
"""

import hashlib
import re
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from nwb.backends import BackendError, Request, get_backend
from nwb.config import ModelSpec, model_settings
from nwb.tracks import Job, rel
from nwb.util import read_json

CORPUS = "frontend-v1"
KINDS = ("2d-s1", "2d-s2", "3d-s1", "3d-s2", "2d-mem", "3d-mem")
MEMORY = "mem"  # task id of the from-memory variants, which take no reference image
VIEWS = ("side", "back", "three_quarter", "top")
MAX_KB = 256
# Writing a full page takes far longer than the other tracks' answers; timeouts are not collection settings.
SUBJECT_TIMEOUT = 1800
ADDONS = ("controls/OrbitControls.js", "geometries/ConvexGeometry.js", "geometries/ParametricFunctions.js",
          "geometries/ParametricGeometry.js", "geometries/RoundedBoxGeometry.js", "math/ConvexHull.js",
          "utils/BufferGeometryUtils.js")


@dataclass(frozen=True)
class Frame:
    image: Path | None
    timestamp_ms: int
    questions: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    width: int
    height: int
    duration_ms: int
    eligibility: str
    frames: tuple[Frame, ...]
    views: dict[str, tuple[str, ...]]
    gif: Path | None = None


@dataclass
class Corpus:
    root: Path
    tasks: dict[str, Task]
    memory: Task
    prompts: dict

    def task(self, task_id: str) -> Task:
        return self.memory if task_id == MEMORY else self.tasks[task_id]


def load_corpus(root: Path) -> Corpus:
    directory = root / "bench" / CORPUS
    with open(directory / "tasks.toml", "rb") as f:
        data = tomllib.load(f)
    with open(directory / "prompts.toml", "rb") as f:
        prompts = tomllib.load(f)
    tasks = {}
    for t in data["tasks"]:
        frames = tuple(Frame(directory / k["file"], k["timestamp_ms"], tuple(k["questions"])) for k in t["keyframes"])
        tasks[t["id"]] = Task(t["id"], t["title"], t["width"], t["height"], t["duration_ms"], t["eligibility"],
                              frames, {v["view"]: tuple(v["questions"]) for v in t["novel_views"]},
                              directory / t["gif"])
    m = data["memory"]
    memory = Task(MEMORY, "大笑奶龙 from memory", m["width"], m["height"], 0, "memory",
                  (Frame(None, 0, tuple(m["questions"])),), {v["view"]: tuple(v["questions"]) for v in m["novel_views"]})
    return Corpus(directory, tasks, memory, prompts)


def dimension(kind: str) -> str:
    return kind.split("-")[0]


def step(kind: str) -> str:
    return kind.split("-")[1]


def fill(template: str, **values) -> str:
    """Substitute {NAME} placeholders only, so literal braces in prompts (JSON, JS) stay untouched."""
    return re.sub(r"\{([A-Z_0-9]+)\}", lambda m: str(values[m[1]]) if m[1] in values else m[0], template)


def subject_prompt(corpus: Corpus, task: Task, kind: str, step1: str | None = None) -> str:
    p = corpus.prompts
    values = dict(W=task.width, H=task.height, D=task.duration_ms, MAX_KB=MAX_KB,
                  ADDONS=", ".join(f"'three/addons/{a}'" for a in ADDONS),
                  TIMES=", ".join(f"image {i} at {f.timestamp_ms} ms" for i, f in enumerate(task.frames, 1)))
    values.update(RULES=fill(p["rules"], **values), CONTRACT_2D=fill(p["contract_2d"], **values),
                  CONTRACT_3D=fill(p["contract_3d"], **values))
    if step(kind) == "s2":
        values["STEP1"] = (f"```html\n{step1}\n```" if step1 is not None
                           else "(Your step 1 reply contained no ```html block, so build the page from scratch.)")
    return fill(p["tasks"][kind]["prompt"], **values).strip()


def subject_images(task: Task, kind: str) -> list[Path]:
    if step(kind) == "mem":
        return []
    return [task.frames[0].image] if step(kind) == "s1" else [f.image for f in task.frames]


_HTML_BLOCK = re.compile(r"```html[^\n]*\n(.*?)\n?```", re.S | re.I)


def extract_html(text: str) -> str | None:
    """The last ```html block of a reply; earlier blocks are drafts."""
    blocks = _HTML_BLOCK.findall(text or "")
    return blocks[-1] if blocks else None


# Static gates check what can be read from the source. Behaviour (network, timers, errors, determinism)
# is checked at render time, so comments that merely mention an API never fail a sample.
_COMMON = {
    "raster or embedded element": r"<\s*(img|image|picture|iframe|frame|object|embed|video|audio|source|track|link|base|portal)\b",
    "meta refresh": r"<\s*meta\b[^>]*http-equiv",
    "CSS import or web font": r"@import\b|@font-face\b",
    "url() other than a fragment reference": r"(?<![\w.$])url\(\s*(?![\"']?\s*#)",
    "data: URI": r"\bdata:[\w.+-]+/[\w.+-]+",
    "base64 decoding": r"\batob\s*\(",
    "external script": r"<\s*script\b[^>]*\bsrc\s*=",
}
_HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_STATIC_2D = {
    "SMIL animation": r"<\s*(animate|animateTransform|animateMotion|set)\b",
    "CSS animation or transition": r"@keyframes\b|\banimation(-name)?\s*:|\btransition\s*:",
    "script": r"<\s*script\b",
}


def static_gates(html: str | None, kind: str, width: int, height: int) -> list[str]:
    """Failed static rules; an empty list passes."""
    if html is None:
        return ["no ```html block"]
    failures = []
    if len(html.encode()) > MAX_KB * 1024:
        failures.append(f"larger than {MAX_KB} KB")
    for name, pattern in _COMMON.items():
        if re.search(pattern, html, re.I):
            failures.append(name)
    if any(not "".join(m.groups(default="")).strip().startswith("#") for m in _HREF.finditer(html)):
        failures.append("non-fragment href")
    if dimension(kind) == "2d":
        svgs = re.findall(r"<\s*svg\b[^>]*>", html, re.I)
        if len(svgs) != 1:
            failures.append(f"expected one inline <svg>, found {len(svgs)}")
        else:
            box = re.search(r"\bviewBox\s*=\s*[\"']([^\"']*)[\"']", svgs[0])
            try:
                numbers = [float(n) for n in re.split(r"[\s,]+", box[1].strip())] if box else []
            except ValueError:
                numbers = []
            if numbers != [0, 0, width, height]:
                failures.append(f'svg viewBox is not "0 0 {width} {height}"')
        if re.search(r"<\s*(foreignObject|canvas)\b", html, re.I):
            failures.append("<foreignObject> or <canvas> in 2D")
        if step(kind) != "s2":
            failures += [name for name, pattern in _STATIC_2D.items() if re.search(pattern, html, re.I)]
    else:
        if re.search(r"<\s*script\b[^>]*type\s*=\s*[\"']?importmap", html, re.I):
            failures.append("own import map")
        if not re.search(r"<\s*script\b[^>]*type\s*=\s*[\"']?module", html, re.I):
            failures.append("no module script")
        if re.search(r"(?<![\w.$])import\s*\(", html):
            failures.append("dynamic import")
        allowed = {"three", *(f"three/addons/{a}" for a in ADDONS)}
        specifiers = re.findall(r"""\b(?:from|import)\s*["']([^"']+)["']""", html)
        if bad := sorted(set(specifiers) - allowed):
            failures.append(f"imports outside the vendored three.js: {', '.join(bad)}")
    return failures


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sample_stem(run_dir: Path, model: str, task_id: str, kind: str, rep: int) -> Path:
    return run_dir / "frontend" / model / task_id / f"{kind}__r{rep}"


def _subject(spec: ModelSpec) -> ModelSpec:
    return replace(spec, options={**spec.options, "timeout": max(spec.options.get("timeout", 600), SUBJECT_TIMEOUT)})


def collect_jobs(corpus: Corpus, models: list[ModelSpec], task_ids: list[str], kinds: list[str], reps: int,
                 run_dir: Path, *, second_steps: bool) -> list[Job]:
    """Subject jobs. Step 2 jobs need their step 1 sample, so they are built in a second pass
    (`second_steps=True`) after step 1 has been collected."""
    jobs = []
    for model in models:
        backend = get_backend(_subject(model))
        settings, settings_id = model_settings(model, corpus.root.parents[1])
        for kind in kinds:
            if (step(kind) == "s2") != second_steps:
                continue
            for task_id in ([MEMORY] if step(kind) == "mem" else task_ids):
                task = corpus.task(task_id)
                for rep in range(1, reps + 1):
                    stem = sample_stem(run_dir, model.name, task_id, kind, rep)
                    depends = {}
                    step1 = None
                    if step(kind) == "s2":
                        source = sample_stem(run_dir, model.name, task_id, kind.replace("s2", "s1"), rep).with_suffix(".json")
                        record = read_json(source) if source.is_file() else {"error": "missing"}
                        if "error" in record:
                            print(f"{model.name} {task_id} {kind} r{rep}: waiting for its step 1 sample", file=sys.stderr)
                            continue
                        step1 = record.get("html")
                        # A step 1 page that failed its gates is still used; the dependency is recorded.
                        depends = {"depends_on": {"sample": rel(source, run_dir),
                                                  "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                                  "static_gates": record.get("static_gates", [])}}
                    prompt = subject_prompt(corpus, task, kind, step1)
                    images = subject_images(task, kind)

                    def fn(prompt=prompt, images=images, kind=kind, task=task, backend=backend):
                        resp = backend.run(Request(prompt=prompt, images=images))
                        if not resp.text.strip():
                            raise BackendError("empty answer")
                        html = extract_html(resp.text)
                        return {"prompt": prompt, "text": resp.text, "html": html,
                                "html_sha256": sha256_text(html) if html is not None else None,
                                "static_gates": static_gates(html, kind, task.width, task.height), "meta": resp.meta}
                    jobs.append(Job(
                        out=stem.with_suffix(".json"), label=f"{model.name} {task_id} {kind} r{rep}",
                        base={"settings_id": settings_id, "track": "frontend", "corpus": CORPUS, "model": model.name,
                              "vendor": model.vendor, "task": task_id, "kind": kind, "rep": rep,
                              "prompt_sha256": sha256_text(prompt), "width": task.width, "height": task.height,
                              "duration_ms": task.duration_ms,
                              **({"input_names": "neutral"} if images else {}),
                              "images": [p.relative_to(corpus.root.parents[1]).as_posix() for p in images], **depends},
                        fn=fn, settings=settings, run_dir=run_dir))
    return jobs


def samples(run_dir: Path) -> list[tuple[Path, dict]]:
    """Successful samples, excluding step 2 samples whose step 1 sample has changed since."""
    found = []
    for path in sorted((run_dir / "frontend").glob("*/*/*__r*.json")):
        record = read_json(path)
        if record.get("track") != "frontend" or "error" in record:
            continue
        # Static gates are recomputed, so gate fixes apply to samples collected earlier.
        record["static_gates"] = static_gates(record.get("html"), record["kind"], record["width"], record["height"])
        if depends := record.get("depends_on"):
            source = run_dir / depends["sample"]
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != depends["sha256"]:
                continue
        found.append((path, record))
    return found


def rendered_images(task: Task, record: dict, render_dir: Path) -> list[tuple[str, Path, Frame | None, tuple[str, ...]]]:
    """(name, rendered image, matching reference keyframe, checklist questions) for review."""
    frames = task.frames if step(record["kind"]) == "s2" else task.frames[:1]
    images = [(f"frame_{i:02d}", render_dir / f"frame_{i:02d}.png", f, f.questions) for i, f in enumerate(frames)]
    if dimension(record["kind"]) == "3d":
        images += [(f"view_{v}", render_dir / f"view_{v}.png", None, task.views[v]) for v in VIEWS if v in task.views]
    return images


def summary(corpus: Corpus, run_dir: Path) -> dict:
    """Gate results per sample and per model and kind. Quality is judged by people in the gallery."""
    from nwb.frontend_render import render_current

    rows, entries = {}, []
    for path, record in samples(run_dir):
        render = render_current(record, path.with_suffix(""))
        gates = record["static_gates"] + (render["gates"] if render else [])
        status = "unrendered" if render is None else "gate failed" if gates else "passed"
        entries.append({"sample": rel(path, run_dir), "model": record["model"], "task": record["task"],
                        "kind": record["kind"], "rep": record["rep"], "status": status, "gates": gates})
        row = rows.setdefault((record["model"], record["kind"]), {"model": record["model"], "kind": record["kind"],
                                                                   "samples": 0, "passed": 0, "unrendered": 0})
        row["samples"] += 1
        row["passed"] += status == "passed"
        row["unrendered"] += status == "unrendered"
    order = sorted(rows.values(), key=lambda r: (r["model"], KINDS.index(r["kind"])))
    return {"corpus": CORPUS, "experimental": True, "index_included": False, "review": "human",
            "rows": order, "samples": entries}

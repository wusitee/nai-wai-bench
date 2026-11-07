"""Experimental frontend track: models rebuild animated GIFs as inline SVG or three.js pages.

The pipeline is collect (subject calls) -> render (sandboxed Chromium, `nwb.frontend_render`) -> report
(gate summary and a gallery for human review). Samples are stored as
runs/<run>/frontend/<model>/<task>/<kind>__r<rep>.json and renders in the directory with the same stem.
Every stage resumes like the other tracks.
"""

import hashlib
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from nwb.backends import BackendError, Request, get_backend
from nwb.config import ModelSpec, model_settings
from nwb.tracks import Job, rel
from nwb.util import read_json

CORPUS = "frontend-v1"
KINDS = ("2d-s1", "2d-s2", "2d-s3", "3d-s1", "3d-s2", "3d-s3", "2d-mem", "2d-mem2", "3d-mem", "3d-mem2")
# Each later kind is built from the same model's sample of the earlier kind: step 2 animates step 1, and
# the revision kinds (s3, mem2) check the rendered result of their source and revise it once.
SOURCE = {"2d-s2": "2d-s1", "3d-s2": "3d-s1", "2d-s3": "2d-s2", "3d-s3": "3d-s2", "2d-mem2": "2d-mem",
          "3d-mem2": "3d-mem"}
REVISIONS = ("2d-s3", "3d-s3", "2d-mem2", "3d-mem2")
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


def is_memory(kind: str) -> bool:
    return step(kind).startswith("mem")


def is_animated(kind: str) -> bool:
    return step(kind) in ("s2", "s3")


def stage(kind: str) -> int:
    """Collection stage: 1 for pages from scratch, 2 for step 2, 3 for revisions, which also need the
    renders of the pages they revise."""
    return 3 if kind in REVISIONS else 2 if kind in SOURCE else 1


def fill(template: str, **values) -> str:
    """Substitute {NAME} placeholders only, so literal braces in prompts (JSON, JS) stay untouched."""
    return re.sub(r"\{([A-Z_0-9]+)\}", lambda m: str(values[m[1]]) if m[1] in values else m[0], template)


_OMITTED = object()


def subject_prompt(corpus: Corpus, task: Task, kind: str, step1: str | None = None,
                   revision: dict | None = None) -> str:
    """The prompt for one sample. Step 2 embeds the step 1 page (`step1`); revision kinds embed the
    source page, its gate results, and the attached image list (`revision`, see `revision_inputs`)."""
    p = corpus.prompts
    values = dict(W=task.width, H=task.height, D=task.duration_ms, MAX_KB=MAX_KB,
                  ADDONS=", ".join(f"'three/addons/{a}'" for a in ADDONS),
                  TIMES=", ".join(f"image {i} at {f.timestamp_ms} ms" for i, f in enumerate(task.frames, 1)))
    values.update(RULES=fill(p["rules"], **values), CONTRACT_2D=fill(p["contract_2d"], **values),
                  CONTRACT_3D=fill(p["contract_3d"], **values))
    if step(kind) == "s2":
        values["STEP1"] = ("(Omitted here: your step 2 page below was built from it.)" if step1 is _OMITTED
                           else f"```html\n{step1}\n```" if step1 is not None
                           else "(Your step 1 reply contained no ```html block, so build the page from scratch.)")
    if kind in REVISIONS:
        source = SOURCE[kind]
        # The source task as it was posed; a step 2 page's own step 1 input is superseded by the page itself.
        values["TASK"] = subject_prompt(corpus, task, source, _OMITTED)
        values["PAGE"] = (f"```html\n{revision['page']}\n```" if revision["page"] is not None
                          else "(Your reply contained no ```html block, so there was no page to render.)")
        gates = revision["gates"]
        values["GATES"] = ("The page passed every automated check." if not gates else
                           "The page failed these automated checks; a page that fails any check scores 0:\n"
                           + "\n".join(f"- {g}" for g in gates))
        values["IMAGES"] = revision["images"]
    return fill(p["tasks"][kind]["prompt"], **values).strip()


def subject_images(task: Task, kind: str) -> list[Path]:
    """Reference images; revision kinds add their renders (`revision_inputs`)."""
    if is_memory(kind):
        return []
    return [task.frames[0].image] if step(kind) == "s1" else [f.image for f in task.frames]


def revision_inputs(task: Task, kind: str, render_dir: Path, render: dict) -> tuple[list[Path], str]:
    """Rendered images of a revision's source sample and the prompt's description of all attachments.

    Animated sources show the reference keyframes first, then the render at the same times; 3D sources add
    the harness views; a page that failed before rendering shows the harness's screenshot of it."""
    source = SOURCE[kind]
    references = subject_images(task, kind)
    rendered = [render_dir / f["file"] for f in render.get("frames", [])]
    views = [render_dir / v["file"] for v in render.get("views", [])]
    parts, n = [], 0

    def describe(count: int, what: str) -> None:
        nonlocal n
        if count:
            parts.append(f"image{'s' if count > 1 else ''} {n + 1}{f'-{n + count}' if count > 1 else ''}: {what}")
            n += count

    times = ", ".join(f"{f.timestamp_ms} ms" for f in task.frames)
    describe(len(references), f"the GIF's keyframes at {times}")
    if is_animated(source):
        describe(len(rendered), "your page rendered by the harness at the same times")
    else:
        describe(len(rendered), "your page rendered by the harness")
    describe(len(views), "your scene at t = 0 from the harness cameras: " + ", ".join(
        v["view"].replace("_", "-") for v in render.get("views", []))
        + " (scenery that blocks the view of a character is hidden for these cameras)")
    failed = [render_dir / render["failed_screenshot"]] if render.get("failed_screenshot") else []
    describe(len(failed), "a screenshot of your page when it failed")
    images = references + rendered + views + failed
    return images, ("; ".join(parts) + ".") if parts else "none: the page could not be rendered."


_HTML_BLOCK = re.compile(r"```html[^\n]*\n(.*?)\n?```", re.S | re.I)


def extract_html(text: str) -> str | None:
    """The last ```html block of a reply; earlier blocks are drafts."""
    blocks = _HTML_BLOCK.findall(text or "")
    return blocks[-1] if blocks else None


# Static gates check what can be read from the source. Behaviour (network, timers, errors, determinism)
# is checked at render time, so comments that merely mention an API never fail a sample.
# Element tags in the markup; script bodies are skipped, so code such as `i < track.length` does not match.
# Elements a script creates are caught by the renderer's live DOM check.
_ELEMENTS = re.compile(r"<(img|image|picture|iframe|frame|object|embed|video|audio|source|track|link|base|portal)(?=[\s/>])",
                       re.I)
_SCRIPT_BODY = re.compile(r"(<script\b[^>]*>).*?(</script\s*>)", re.S | re.I)
_COMMON = {
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
    if _ELEMENTS.search(_SCRIPT_BODY.sub(r"\1\2", html)):
        failures.append("raster or embedded element")
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
        if not is_animated(kind):
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


def revision_inputs_dir(stem: Path) -> Path:
    """Copies of the rendered images a revision was shown, kept with the revision sample."""
    return stem.parent / f"{stem.name}.inputs"


def collect_jobs(corpus: Corpus, models: list[ModelSpec], task_ids: list[str], kinds: list[str], reps: int,
                 run_dir: Path, *, stage_no: int) -> tuple[list[Job], int]:
    """Subject jobs of one collection stage (see `stage`), and the number of samples blocked because the
    sample they build on, or for revisions its current render, is missing. Stages run in order, with the
    sources of stage 3 rendered first."""
    from nwb.frontend_render import render_current

    jobs, blocked = [], 0
    for model in models:
        backend = get_backend(_subject(model))
        settings, settings_id = model_settings(model, corpus.root.parents[1])
        for kind in kinds:
            if stage(kind) != stage_no:
                continue
            for task_id in ([MEMORY] if is_memory(kind) else task_ids):
                task = corpus.task(task_id)
                for rep in range(1, reps + 1):
                    stem = sample_stem(run_dir, model.name, task_id, kind, rep)
                    depends = {}
                    step1 = revision = None
                    images = subject_images(task, kind)
                    feedback: list[tuple[Path, Path]] = []  # (rendered image, copy shown to the model)
                    if kind in SOURCE:
                        source = sample_stem(run_dir, model.name, task_id, SOURCE[kind], rep).with_suffix(".json")
                        record = load_sample(run_dir, source)
                        if record is None:
                            print(f"{model.name} {task_id} {kind} r{rep}: waiting for a current {SOURCE[kind]} sample",
                                  file=sys.stderr)
                            blocked += 1
                            continue
                        # A source page that failed its gates is still used; the dependency is recorded. Step 2
                        # keeps the gates stored with its source, so a later checker change does not alter its
                        # identity; revisions record the recomputed gates they were shown.
                        depends = {"sample": rel(source, run_dir),
                                   "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                   "static_gates": (record["static_gates"] if kind in REVISIONS
                                                    else read_json(source).get("static_gates", []))}
                        if kind in REVISIONS:
                            render = render_current(record, source.with_suffix(""))
                            if render is None:
                                print(f"{model.name} {task_id} {kind} r{rep}: waiting for its {SOURCE[kind]} render",
                                      file=sys.stderr)
                                blocked += 1
                                continue
                            attached, described = revision_inputs(task, kind, source.with_suffix(""), render)
                            if missing := [p.name for p in attached if not p.is_file()]:
                                print(f"{model.name} {task_id} {kind} r{rep}: source render lacks {missing}",
                                      file=sys.stderr)
                                blocked += 1
                                continue
                            gates = record["static_gates"] + render["gates"]
                            revision = {"page": record.get("html"), "gates": gates, "images": described}
                            inputs = revision_inputs_dir(stem)
                            feedback = [(p, inputs / p.name) for p in attached[len(images):]]
                            # The model is shown copies, so later re-renders cannot change what it saw.
                            depends.update(harness=render["harness"], gates=gates, rendered=[
                                {"file": rel(copy, run_dir), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                for p, copy in feedback])
                            # A finished revision whose copies were lost or altered gets them back from the
                            # unchanged source render; if the source changed, the job base differs and it reruns.
                            if stem.with_suffix(".json").is_file():
                                for (src, copy), item in zip(feedback, depends["rendered"]):
                                    if not copy.is_file() or hashlib.sha256(copy.read_bytes()).hexdigest() != item["sha256"]:
                                        copy.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copyfile(src, copy)
                        else:
                            step1 = record.get("html")
                        depends = {"depends_on": depends}
                    prompt = subject_prompt(corpus, task, kind, step1, revision)
                    attached = images + [copy for _, copy in feedback]

                    def fn(prompt=prompt, images=attached, kind=kind, task=task, backend=backend, feedback=feedback,
                           expected=[r["sha256"] for r in depends.get("depends_on", {}).get("rendered", [])]):
                        for (src, copy), sha in zip(feedback, expected):
                            copy.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(src, copy)
                            if hashlib.sha256(copy.read_bytes()).hexdigest() != sha:
                                raise BackendError(f"feedback image {src.name} changed since the job was built")
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
                              **({"input_names": "neutral"} if attached else {}),
                              "images": [p.relative_to(corpus.root.parents[1]).as_posix() for p in images], **depends},
                        fn=fn, settings=settings, run_dir=run_dir))
    return jobs, blocked


def revision_sources(models: list[ModelSpec], task_ids: list[str], kinds: list[str], reps: int,
                     run_dir: Path) -> set[Path]:
    """Sample files whose renders the selected revisions need."""
    return {sample_stem(run_dir, model.name, MEMORY if is_memory(kind) else task_id, SOURCE[kind], rep)
            .with_suffix(".json")
            for model in models for kind in kinds if kind in REVISIONS
            for task_id in ([MEMORY] if is_memory(kind) else task_ids) for rep in range(1, reps + 1)}


TAINTED = "builds on a sample that used tools"


def tool_use(record: dict) -> list[str]:
    """Tools the subject used or asked to use; frontend answers must come from the model alone."""
    meta = record.get("meta") or {}
    return [*meta.get("tools_used", []), *(p.get("tool") or "tool" for p in meta.get("permissions", []))]


def load_sample(run_dir: Path, path: Path, _seen: dict | None = None) -> dict | None:
    """A successful sample whose whole dependency chain is current, or None.

    Static gates are recomputed, so gate fixes apply to samples collected earlier, and gain a tool-use
    gate when the sample or any sample it builds on used tools. A sample is stale when a sample it builds
    on changed, is stale itself, or (for revisions) when the copied feedback images are missing or changed."""
    seen = {} if _seen is None else _seen
    if path in seen:
        return seen[path]
    seen[path] = None
    record = read_json(path) if path.is_file() else {"error": "missing"}
    if record.get("track") != "frontend" or "error" in record:
        return None
    gates = static_gates(record.get("html"), record["kind"], record["width"], record["height"])
    if used := tool_use(record):
        gates.append(f"used tools: {', '.join(sorted(set(used)))}")
    if depends := record.get("depends_on"):
        source_path = run_dir / depends["sample"]
        if not source_path.is_file() or hashlib.sha256(source_path.read_bytes()).hexdigest() != depends["sha256"]:
            return None
        source = load_sample(run_dir, source_path, seen)
        if source is None:
            return None
        for item in depends.get("rendered", []):
            copy = run_dir / item["file"]
            if not copy.is_file() or hashlib.sha256(copy.read_bytes()).hexdigest() != item["sha256"]:
                return None
        if any(g.startswith(("used tools", TAINTED)) for g in source["static_gates"]):
            gates.append(TAINTED)
    record["static_gates"] = gates
    seen[path] = record
    return record


def samples(run_dir: Path) -> list[tuple[Path, dict]]:
    """Successful samples whose dependency chains are current (see `load_sample`)."""
    seen: dict = {}
    found = []
    for path in sorted((run_dir / "frontend").glob("*/*/*__r*.json")):
        if (record := load_sample(run_dir, path, seen)) is not None:
            found.append((path, record))
    return found


def rendered_images(task: Task, record: dict, render_dir: Path) -> list[tuple[str, Path, Frame | None, tuple[str, ...]]]:
    """(name, rendered image, matching reference keyframe, checklist questions) for review."""
    frames = task.frames if is_animated(record["kind"]) else task.frames[:1]
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

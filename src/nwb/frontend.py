"""Experimental frontend track: models rebuild animated GIFs as inline SVG or three.js pages.

The pipeline is collect (subject calls) -> render (sandboxed Chromium, `nwb.frontend_render`) -> judge
(checklist questions per rendered image) -> report. Samples are stored as
runs/<run>/frontend/<model>/<task>/<kind>__r<rep>.json, renders in the directory with the same stem, and
judgments under runs/<run>/frontend-judgments/<judge>/. Every stage resumes like the other tracks.
"""

import hashlib
import random
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from nwb.backends import BackendError, Request, get_backend
from nwb.config import ModelSpec, model_settings
from nwb.scoring import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, _percentile, mean, pick_judges
from nwb.tracks import Job, rel, run_jobs
from nwb.util import extract_json, read_json

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


# --- Checklist judging -------------------------------------------------------------------------------------

class ChecklistJudge(Protocol):
    """Answers yes/no questions about one image. LLM judging may later be replaced behind this interface."""
    name: str
    vendor: str
    settings: dict
    settings_id: str

    def answer(self, image: Path, questions: Sequence[str]) -> dict:
        """Return {"answers": [bool per question], ...evidence}."""


class ModelJudge:
    ATTEMPTS = 2

    def __init__(self, spec: ModelSpec, prompt: str):
        self.spec, self.prompt = spec, prompt
        self.name, self.vendor = spec.name, spec.vendor
        self.settings, self.settings_id = model_settings(spec)
        self.backend = get_backend(spec)

    def request_prompt(self, questions: Sequence[str]) -> str:
        return judge_prompt(self.prompt, questions)

    def answer(self, image: Path, questions: Sequence[str]) -> dict:
        last = None
        for _ in range(self.ATTEMPTS):
            resp = self.backend.run(Request(prompt=self.request_prompt(questions), images=[image]))
            try:
                return {"answers": parse_answers(resp.text, len(questions)), "raw": resp.text, "meta": resp.meta}
            except ValueError as e:
                last = e
        raise ValueError(f"no valid judgment after {self.ATTEMPTS} attempts: {last}")


def judge_prompt(template: str, questions: Sequence[str]) -> str:
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return fill(template, QUESTIONS=numbered).strip()


def parse_answers(reply: str, count: int) -> list[bool]:
    answers = extract_json(reply).get("answers")
    if isinstance(answers, list):
        answers = {str(i): a for i, a in enumerate(answers, 1)}
    if not isinstance(answers, dict):
        raise ValueError("judge reply has no answers object")
    result = []
    for i in range(1, count + 1):
        value = answers.get(str(i))
        if isinstance(value, str) and value.strip().lower() in ("yes", "no"):
            result.append(value.strip().lower() == "yes")
        elif isinstance(value, bool):
            result.append(value)
        else:
            raise ValueError(f"answer {i} must be yes or no, got {value!r}")
    return result


def judged_images(corpus: Corpus, record: dict, render: dict, render_dir: Path) -> list[tuple[str, Path, tuple[str, ...]]]:
    """(name, rendered image, questions) for a sample whose render passed every gate."""
    task = corpus.task(record["task"])
    frames = task.frames if step(record["kind"]) == "s2" else task.frames[:1]
    images = [(f"frame_{i:02d}", render_dir / f"frame_{i:02d}.png", f.questions) for i, f in enumerate(frames)]
    if dimension(record["kind"]) == "3d":
        images += [(f"view_{v}", render_dir / f"view_{v}.png", task.views[v]) for v in VIEWS if v in task.views]
    return images


def control_images(corpus: Corpus, task_ids: list[str], run_dir: Path) -> list[tuple[str, str, Path, tuple[str, ...]]]:
    """Calibration inputs, since every checklist answer is expected to be yes: the reference frames
    themselves (should pass), a blank page, and another task's frames (both should mostly fail)."""
    from nwb.frontend_render import blank_png

    controls = []
    panel = [t for t in corpus.tasks.values() if t.eligibility == "panel"]
    for task_id in task_ids:
        task = corpus.task(task_id)
        blank = blank_png(run_dir / "frontend" / "_controls" / f"blank_{task.width}x{task.height}.png", task.width, task.height)
        if task_id == MEMORY:
            reference = corpus.root.parent / "reference" / "nailong_laugh.png"
            other = corpus.tasks["003"].frames[0].image
            questions = task.frames[0].questions
            controls += [(task_id, "reference/canonical", reference, questions), (task_id, "blank/frame_00", blank, questions),
                         (task_id, "mismatch/frame_00", other, questions)]
            continue
        other = panel[(panel.index(task) + 1) % len(panel)] if task in panel else panel[0]
        for i, frame in enumerate(task.frames):
            controls.append((task_id, f"reference/frame_{i:02d}", frame.image, frame.questions))
            if i % 2 == 0:
                controls.append((task_id, f"mismatch/frame_{i:02d}", other.frames[i].image, frame.questions))
            if i in (0, 4):
                controls.append((task_id, f"blank/frame_{i:02d}", blank, frame.questions))
    return controls


def judge_jobs(corpus: Corpus, judges: list[ChecklistJudge], run_dir: Path, *, controls: bool = True) -> list[Job]:
    from nwb.frontend_render import render_current

    targets = []  # (output relative path, image, questions, base extras)
    task_ids = set()
    for path, record in samples(run_dir):
        task_ids.add(record["task"])
        render_dir = path.with_suffix("")
        render = render_current(record, render_dir)
        if render is None or render["gates"] or record["static_gates"]:
            continue  # unrendered samples wait; gate failures score 0 without judging
        for name, image, questions in judged_images(corpus, record, render, render_dir):
            targets.append((Path(rel(render_dir, run_dir)) / f"{name}.json", image, questions,
                            {"model": record["model"], "vendor": record["vendor"], "sample": rel(path, run_dir)}))
    if controls:
        for task_id, name, image, questions in control_images(corpus, sorted(task_ids), run_dir):
            targets.append((Path("_controls") / task_id / f"{name}.json", image, questions, {"control": name}))
    jobs = []
    vendors = {j.vendor for j in judges}
    for judge in judges:
        for target, image, questions, extra in targets:
            if extra.get("vendor") == judge.vendor and vendors - {judge.vendor}:
                continue  # scoring leaves out the subject's own vendor when another judge exists
            prompt_sha = sha256_text(judge.request_prompt(questions)) if hasattr(judge, "request_prompt") else None
            jobs.append(Job(
                out=run_dir / "frontend-judgments" / judge.name / target,
                label=f"judge {judge.name} <- {target.with_suffix('').as_posix()}",
                base={"track": "frontend-judgment", "judge": judge.name, "judge_vendor": judge.vendor,
                      "settings_id": judge.settings_id, "input_names": "neutral", "image": _image_ref(image, run_dir, corpus),
                      "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "questions": list(questions),
                      "judge_prompt": prompt_sha, **extra},
                fn=lambda judge=judge, image=image, questions=questions: judge.answer(image, questions),
                settings=judge.settings, run_dir=run_dir))
    return jobs


def run_judges(corpus: Corpus, judges: list[ChecklistJudge], run_dir: Path, workers: int, force: bool) -> tuple[int, int]:
    return run_jobs(judge_jobs(corpus, judges, run_dir), workers, force, run_dir=run_dir)


# --- Scoring -----------------------------------------------------------------------------------------------

def _image_ref(image: Path, run_dir: Path, corpus: Corpus) -> str:
    """Run-relative for renders, `repo:`-prefixed for reference inputs used as controls."""
    if image.resolve().is_relative_to(run_dir.resolve()):
        return image.resolve().relative_to(run_dir.resolve()).as_posix()
    return "repo:" + image.resolve().relative_to(corpus.root.parents[1].resolve()).as_posix()


def _resolve_image(ref: str, run_dir: Path, corpus: Corpus) -> Path:
    return corpus.root.parents[1] / ref.removeprefix("repo:") if ref.startswith("repo:") else run_dir / ref


def _judgments(corpus: Corpus, run_dir: Path, judges: set[str] | None) -> dict[str, list[dict]]:
    """Valid judgments by target path relative to the judge directory."""
    by_target: dict[str, list[dict]] = {}
    for path in sorted((run_dir / "frontend-judgments").glob("*/**/*.json")):
        record = read_json(path)
        if "error" in record or (judges is not None and record["judge"] not in judges):
            continue
        image = _resolve_image(record["image"], run_dir, corpus)
        if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != record["image_sha256"]:
            continue  # stale: the render changed since this judgment
        target = path.relative_to(run_dir / "frontend-judgments" / record["judge"]).as_posix()
        by_target.setdefault(target, []).append(record)
    return by_target


def _fresh(corpus: Corpus, judgments: list[dict], questions: Sequence[str]) -> list[dict]:
    """Judgments of these exact questions with the current judge prompt (None for non-prompt judges)."""
    expected = sha256_text(judge_prompt(corpus.prompts["judge"]["prompt"], questions))
    return [j for j in judgments if j.get("questions") == list(questions) and len(j["answers"]) == len(questions)
            and j.get("judge_prompt") in (None, expected)]


def yes_share(judgment: dict) -> float:
    return sum(judgment["answers"]) / len(judgment["answers"])


def score_sample(corpus: Corpus, path: Path, record: dict, run_dir: Path, by_target: dict[str, list[dict]]) -> dict:
    from nwb.frontend_render import render_current

    render_dir = path.with_suffix("")
    render = render_current(record, render_dir)
    result = {"sample": rel(path, run_dir), "model": record["model"], "task": record["task"], "kind": record["kind"],
              "rep": record["rep"], "static_gates": record["static_gates"],
              "render_gates": render["gates"] if render else None, "render": rel(render_dir, run_dir) if render else None}
    if render is None:
        return {**result, "status": "unrendered", "score": None}
    if record["static_gates"] or render["gates"]:
        return {**result, "status": "gate failed", "score": 0.0, "images": {}}
    images, judges_used = {}, set()
    for name, _, questions in judged_images(corpus, record, render, render_dir):
        target = f"{rel(render_dir, run_dir)}/{name}.json"
        counted = pick_judges(_fresh(corpus, by_target.get(target, []), questions), record["vendor"])
        if not counted:
            return {**result, "status": "unjudged", "score": None}
        judges_used.update(j["judge"] for j in counted)
        images[name] = {"score": mean([yes_share(j) for j in counted]),
                        "by_judge": {j["judge"]: j["answers"] for j in counted}}
    frames = [v["score"] for k, v in images.items() if k.startswith("frame_")]
    views = [v["score"] for k, v in images.items() if k.startswith("view_")]
    return {**result, "status": "scored", "score": mean([v["score"] for v in images.values()]),
            "frames_score": mean(frames), "views_score": mean(views), "judges": sorted(judges_used), "images": images}


def _bootstrap(scores_by_task: dict[str, list[float]], rng: random.Random) -> tuple[float, float] | None:
    tasks = sorted(scores_by_task)
    if not tasks:
        return None
    draws = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        picked = [scores_by_task[rng.choice(tasks)] for _ in tasks]
        draws.append(mean([rng.choice(reps) for reps in picked for _ in reps]))
    return _percentile(draws, 0.025), _percentile(draws, 0.975)


def aggregate(corpus: Corpus, run_dir: Path, judges: set[str] | None = None) -> dict:
    by_target = _judgments(corpus, run_dir, judges)
    found = samples(run_dir)
    scored = [score_sample(corpus, path, record, run_dir, by_target) for path, record in found]
    rows = []
    for model in sorted({s["model"] for s in scored}):
        for kind in KINDS:
            group = [s for s in scored if s["model"] == model and s["kind"] == kind]
            if not group:
                continue
            done = [s for s in group if s["score"] is not None]
            by_task: dict[str, list[float]] = {}
            for s in done:
                by_task.setdefault(s["task"], []).append(s["score"])
            ci = _bootstrap(by_task, random.Random(f"{BOOTSTRAP_SEED}:{model}:{kind}"))
            rows.append({"model": model, "kind": kind, "samples": len(group), "scored": len(done),
                         "gates_passed": sum(1 for s in done if s["status"] == "scored"),
                         "score": mean([s["score"] for s in done]),
                         "frames_score": mean([s.get("frames_score") for s in done if s["status"] == "scored"]),
                         "views_score": mean([s.get("views_score") for s in done if s["status"] == "scored"]),
                         "ci95": list(ci) if ci else None})
    controls = {}
    for task_id, name, _, questions in control_images(corpus, sorted({r["task"] for _, r in found}), run_dir):
        for j in _fresh(corpus, by_target.get(f"_controls/{task_id}/{name}.json", []), questions):
            group = f"{task_id}/{name.split('/')[0]}"
            controls.setdefault(j["judge"], {}).setdefault(group, []).append(yes_share(j))
    controls = {judge: {k: mean(v) for k, v in sorted(groups.items())} for judge, groups in sorted(controls.items())}
    return {"corpus": CORPUS, "experimental": True, "index_included": False, "three_d_ranked": False,
            "judges": sorted(judges) if judges else None, "rows": rows, "samples": scored, "controls": controls,
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED, "unit": "task"}}

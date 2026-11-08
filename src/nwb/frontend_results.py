"""Git-ready publication snapshot of a frontend run (results/frontend/<run>/), read by release builds.

A snapshot holds the sanitized sample records, the gate summary, the task metadata the site needs, and the
harness renders and reference GIFs re-encoded for the web (WebP, or the original file when it is smaller).
It is a publication record, not a working run: lossy renders and the revision input copies are not
restorable, so re-rendering or collecting more needs the working run under runs/<run>/."""

import hashlib
import io
import json
from pathlib import Path

from nwb import __version__
from nwb.bundle import _digest, _json_bytes
from nwb.config import ModelSpec
from nwb.frontend import MEMORY, Corpus, rendered_images, samples, summary
from nwb.frontend_render import harness_id, render_current
from nwb.results import METADATA, _file
from nwb.util import read_json, write_bytes, write_json

FORMAT = 1
STILL_QUALITY = 85
LOOP_QUALITY = 70


def directory(root: Path, run: str) -> Path:
    return root / "results" / "frontend" / run


def _encode(path: Path) -> tuple[str, bytes]:
    """(suffix, bytes): a WebP re-encoding of an image or animated GIF, or the original when smaller.
    Variable GIF delays are carried frame by frame."""
    from PIL import Image

    original = path.read_bytes()
    with Image.open(path) as image:
        buffer = io.BytesIO()
        if getattr(image, "n_frames", 1) > 1:
            durations = []
            for index in range(image.n_frames):
                image.seek(index)
                durations.append(image.info.get("duration", 100))
            image.seek(0)
            image.save(buffer, "WEBP", save_all=True, duration=durations, loop=0, quality=LOOP_QUALITY, method=6)
        else:
            image.save(buffer, "WEBP", quality=STILL_QUALITY, method=6)
    encoded = buffer.getvalue()
    return (".webp", encoded) if len(encoded) < len(original) else (path.suffix.lower(), original)


def _label(models: dict[str, ModelSpec], model: str, records: list[dict]) -> str:
    """Display label with the recorded reasoning effort, as the suite reports label their rows."""
    label = models[model].label if model in models else model
    efforts = {r.get("settings", {}).get("effort") for r in records if r["model"] == model} - {None}
    if len(efforts) == 1 and (effort := next(iter(efforts))) not in ("default", "unexposed"):
        if not label.endswith(f" ({effort})"):
            label += f" ({effort})"
    return label


def prepare(corpus: Corpus, run_dir: Path, models: dict[str, ModelSpec]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}

    def add(stem: str, source: Path) -> str:
        suffix, data = _encode(source)
        files[stem + suffix] = data
        return stem.rsplit("/", 1)[-1] + suffix

    found = samples(run_dir)
    gates = summary(corpus, run_dir)
    records = [record for _, record in found]
    task_ids = sorted({r["task"] for r in records}, key=lambda t: (t == MEMORY, t))
    tasks = {}
    for task_id in task_ids:
        task = corpus.task(task_id)
        tasks[task_id] = {"title": task.title, "width": task.width, "height": task.height,
                          "duration_ms": task.duration_ms, "eligibility": task.eligibility, "frames": []}
        if task.gif is not None:
            tasks[task_id]["gif"] = add(f"reference/{task_id}/reference", task.gif)
            tasks[task_id]["frames"] = [{"t": f.timestamp_ms, "file": add(f"reference/{task_id}/frame_{i:02d}", f.image)}
                                        for i, f in enumerate(task.frames)]
    for path, record in found:
        stem = path.relative_to(run_dir).with_suffix("").as_posix()
        files[f"{stem}.json"] = _json_bytes(record)
        render = render_current(record, path.with_suffix(""))
        if render is None:
            continue
        render = dict(render)
        names = {}
        for name, image, _, _ in rendered_images(corpus.task(record["task"]), record, path.with_suffix("")):
            if image.is_file():
                names[image.name] = add(f"{stem}/{name}", image)
        for key in ("preview", "failed_screenshot"):
            if render.get(key):
                render[key] = add(f"{stem}/{Path(render[key]).stem}", path.with_suffix("") / render[key])
        for entry in render.get("frames", []) + render.get("views", []):
            entry["file"] = names.get(entry["file"])
        files[f"{stem}/render.json"] = _json_bytes(render)
    labels = {m: _label(models, m, records) for m in sorted({r["model"] for r in records})}
    files["summary.json"] = _json_bytes({**gates, "run": run_dir.name, "harness": harness_id(), "labels": labels,
                                         "tasks": tasks})
    return files


def sync(root: Path, corpus: Corpus, run_dir: Path, models: dict[str, ModelSpec]) -> tuple[Path, str]:
    """Write the snapshot, touching only changed files; returns its directory and input digest."""
    snapshot = directory(root, run_dir.name)
    files = prepare(corpus, run_dir, models)
    previous = read_json(snapshot / METADATA) if (snapshot / METADATA).is_file() else {"files": {}}
    for name, data in files.items():
        path = _file(snapshot, name)
        if not path.is_file() or path.read_bytes() != data:
            write_bytes(path, data)
    for name in previous["files"].keys() - files.keys():
        _file(snapshot, name).unlink(missing_ok=True)
    digest = _digest(files)
    meta = {"format": FORMAT, "nwb_version": __version__, "track": "frontend", "run": run_dir.name,
            "input_sha256": digest,
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    if previous != meta:
        write_json(snapshot / METADATA, meta)
    return snapshot, digest


def load(root: Path, run: str, sha256: str) -> tuple[Path, dict]:
    """Verify a saved snapshot against its checksums and a release pin; returns it and its summary."""
    snapshot = directory(root, run)
    if not (snapshot / METADATA).is_file():
        raise FileNotFoundError(f"saved frontend results not found: {snapshot}; run nwb frontend sync --run {run}")
    meta = read_json(snapshot / METADATA)
    if meta.get("format") != FORMAT or meta.get("track") != "frontend" or meta.get("run") != run \
            or not isinstance(meta.get("files"), dict) or "summary.json" not in meta["files"]:
        raise ValueError(f"invalid frontend snapshot metadata: {snapshot / METADATA}")
    files = {}
    for name, digest in meta["files"].items():
        data = _file(snapshot, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"saved frontend result checksum mismatch: {snapshot / name}")
        files[name] = data
    digest = _digest(files)
    if digest != sha256:
        raise ValueError(f"release frontend: saved results changed (expected {sha256}, got {digest}); "
                         "review the changed run before updating the manifest")
    return snapshot, json.loads(files["summary.json"])

"""Job construction and execution for both benchmark tracks.

Results are one JSON file per sample under runs/<run>/, so interrupted runs resume where they
stopped; samples that errored are retried on the next invocation.
"""

import json
import shutil
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from nwb.backends import BackendError, ProviderRefusal, Request, get_backend
from nwb.config import Animal, Bench, ModelSpec, Tier, UnderstandingItem, model_settings
from nwb.provenance import c2pa_summary, collection_identity, utc_now
from nwb.util import IMAGE_SUFFIXES, read_json, write_json


# Prepended to every understanding prompt; backends also disable tools where the CLI allows it.
OWN_KNOWLEDGE = {
    "zh": "请仅凭你自己的知识回答，不要使用任何工具、网络搜索或文件。",
    "en": "Answer from your own knowledge only. Do not use any tools, web search, or files.",
}


@dataclass
class Job:
    out: Path
    label: str
    base: dict
    fn: Callable[[], dict]
    settings: dict = field(default_factory=dict)
    run_dir: Path | None = None


def is_done(job: Job) -> bool:
    """Done means a successful result produced by this exact job: same prompt, same judged sample, and
    so on. Results from an older prompt or sample version are redone."""
    if not job.out.is_file():
        return False
    try:
        record = read_json(job.out)
    except ValueError:
        return False
    return "error" not in record and all(record.get(k) == v for k, v in job.base.items())


def run_jobs(jobs: list[Job], workers: int, force: bool, *, run_dir: Path | None = None) -> tuple[int, int]:
    # Preflight the whole batch before logging or starting any paid calls.
    if not force:
        for job in jobs:
            if not job.out.is_file():
                continue
            try:
                previous = read_json(job.out)
            except ValueError:
                continue
            settings_changed = "settings_id" in job.base and previous.get("settings_id") != job.base["settings_id"]
            subject_changed = ("judge" not in job.base and job.base.get("track") in ("understanding", "imagegen")
                               and not is_done(job))
            if "error" not in previous and (settings_changed or subject_changed):
                raise ValueError(f"{job.label}: successful result has different collection inputs or settings; "
                                 "choose a new --run name, or use --force to explicitly replace it")
    todo = [j for j in jobs if force or not is_done(j)]
    skipped = len(jobs) - len(todo)
    if skipped:
        print(f"{skipped} of {len(jobs)} already done; running {len(todo)}", file=sys.stderr)
    if not todo:
        return 0, 0
    identity = collection_identity()
    run_dirs = dict.fromkeys(j.run_dir for j in todo if j.run_dir is not None)
    if run_dir is not None:
        run_dirs[run_dir] = None
    for run_dir in run_dirs:
        involved = {j.base.get("judge", j.base.get("model")): j.settings for j in todo if j.run_dir == run_dir}
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "collection.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": utc_now(), "argv": sys.argv, **identity,
                                     "settings": involved}, ensure_ascii=False) + "\n")
    failed = 0

    def execute(job: Job) -> tuple[Job, dict, float]:
        started = time.monotonic()
        started_at = utc_now()
        try:
            record = {**job.base, **job.fn()}
        except Exception as e:  # recorded per sample so one failure doesn't stop the run
            record = {**job.base, "error": f"{type(e).__name__}: {e}"}
        record.update(settings=job.settings, collected={"started_at": started_at,
                      "finished_at": utc_now(), **identity})
        write_json(job.out, record)
        return job, record, time.monotonic() - started

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(execute, j) for j in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            job, record, seconds = fut.result()
            status = "ok"
            if "error" in record:
                failed += 1
                status = "ERROR " + record["error"][:300]
            print(f"[{n}/{len(todo)}] {job.label} ({seconds:.0f}s) {status}", file=sys.stderr)
    return len(todo) - failed, failed


def rel(path: Path, run_dir: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def understanding_jobs(bench: Bench, models: list[ModelSpec], items: list[UnderstandingItem],
                       reps: int, run_dir: Path) -> list[Job]:
    jobs = []
    for model in models:
        usable = [i for i in items if i.modality in model.can]
        skipped = [i.id for i in items if i.modality not in model.can]
        if skipped:
            print(f"{model.name}: skipping {', '.join(skipped)} (needs vision)", file=sys.stderr)
        backend = get_backend(model)
        settings, settings_id = model_settings(model, bench.root)
        for item in usable:
            for rep in range(1, reps + 1):
                def fn(item=item, backend=backend):
                    prompt = f"{OWN_KNOWLEDGE[item.lang]}\n\n{item.prompt}"
                    resp = backend.run(Request(prompt=prompt, images=list(item.images)))
                    if not resp.text.strip():  # e.g. an ACP agent that ends its turn after API errors
                        raise BackendError("empty answer")
                    # Answers that looked things up measure retrieval, not knowledge; they are not scored.
                    return {"answer": resp.text, "contaminated": bool(resp.meta.get("tools_used")),
                            "meta": resp.meta}
                jobs.append(Job(
                    out=run_dir / "understanding" / model.name / f"{item.id}__r{rep}.json",
                    label=f"{model.name} {item.id} r{rep}",
                    base={"settings_id": settings_id, **({"input_names": "neutral"} if item.images else {}),
                          "track": "understanding", "model": model.name, "vendor": model.vendor,
                          **({"suite": bench.suite} if bench.suite != "core" else {}),
                          "item": item.id, "modality": item.modality, "lang": item.lang, "rep": rep,
                          "prompt": item.prompt, "images": [p.relative_to(bench.root).as_posix() for p in item.images]},
                    fn=fn, settings=settings, run_dir=run_dir,
                ))
    return jobs


def imagegen_jobs(bench: Bench, models: list[ModelSpec], tiers: list[Tier], animals: list[Animal],
                  reps: int, run_dir: Path) -> list[Job]:
    jobs = []
    for model in models:
        backend = get_backend(model)
        settings, settings_id = model_settings(model, bench.root, generate=True)
        for tier in tiers:
            for animal in animals:
                for rep in range(1, reps + 1):
                    stem = run_dir / "imagegen" / model.name / tier.id / f"{animal.id}__r{rep}"
                    prompt = tier.render(animal)

                    def fn(prompt=prompt, tier=tier, stem=stem, backend=backend):
                        images = [tier.reference_image or bench.reference_image] if tier.reference else []
                        shutil.rmtree(stem, ignore_errors=True)  # drop images from earlier attempts
                        try:
                            resp = backend.run(Request(prompt=prompt, images=images, image_out=stem))
                        except ProviderRefusal as e:  # a final, scored outcome; --force retries it
                            return {"images": [], "refused": str(e), "meta": e.meta}
                        files = sorted(p for p in resp.images if p.suffix.lower() in IMAGE_SUFFIXES)
                        c2pa = c2pa_summary(files[0]) if files else None
                        return {"images": [rel(p, run_dir) for p in files], "text": resp.text,
                                "meta": {**resp.meta, "c2pa": c2pa}}
                    jobs.append(Job(
                        out=stem.with_suffix(".json"),
                        label=f"{model.name} {tier.id} {animal.id} r{rep}",
                        base={"settings_id": settings_id, **({"input_names": "neutral"} if tier.reference else {}),
                              "track": "imagegen", "model": model.name, "vendor": model.vendor, "tier": tier.id,
                              **({"suite": bench.suite} if bench.suite != "core" else {}),
                              "animal": animal.id, "rep": rep, "prompt": prompt, "reference": tier.reference,
                              **({"reference_image": (tier.reference_image or bench.reference_image).relative_to(bench.root).as_posix()}
                                 if tier.reference else {}),
                              **({"state": tier.state, "state_source": tier.reference_image.relative_to(bench.root).as_posix()}
                                 if tier.state else {})},
                        fn=fn, settings=settings, run_dir=run_dir,
                    ))
    return jobs

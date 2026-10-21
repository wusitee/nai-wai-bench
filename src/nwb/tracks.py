"""Job construction and execution for both benchmark tracks.

Results are one JSON file per sample under runs/<run>/, so interrupted runs resume where they
stopped; samples that errored are retried on the next invocation.
"""

import shutil
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from nwb.backends import Request, get_backend
from nwb.config import Animal, Bench, ModelSpec, Tier, UnderstandingItem
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


def is_done(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return "error" not in read_json(path)
    except ValueError:
        return False


def run_jobs(jobs: list[Job], workers: int, force: bool) -> tuple[int, int]:
    todo = [j for j in jobs if force or not is_done(j.out)]
    skipped = len(jobs) - len(todo)
    if skipped:
        print(f"{skipped} of {len(jobs)} already done; running {len(todo)}", file=sys.stderr)
    failed = 0

    def execute(job: Job) -> tuple[Job, dict, float]:
        started = time.monotonic()
        try:
            record = {**job.base, **job.fn()}
        except Exception as e:  # recorded per sample so one failure doesn't stop the run
            record = {**job.base, "error": f"{type(e).__name__}: {e}"}
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
        for item in usable:
            for rep in range(1, reps + 1):
                def fn(item=item, backend=backend):
                    prompt = f"{OWN_KNOWLEDGE[item.lang]}\n\n{item.prompt}"
                    resp = backend.run(Request(prompt=prompt, images=list(item.images)))
                    # Answers that looked things up measure retrieval, not knowledge; they are not scored.
                    return {"answer": resp.text, "contaminated": bool(resp.meta.get("tools_used")),
                            "meta": resp.meta}
                jobs.append(Job(
                    out=run_dir / "understanding" / model.name / f"{item.id}__r{rep}.json",
                    label=f"{model.name} {item.id} r{rep}",
                    base={"track": "understanding", "model": model.name, "vendor": model.vendor,
                          "item": item.id, "modality": item.modality, "lang": item.lang, "rep": rep,
                          "prompt": item.prompt, "images": [p.relative_to(bench.root).as_posix() for p in item.images]},
                    fn=fn,
                ))
    return jobs


def imagegen_jobs(bench: Bench, models: list[ModelSpec], tiers: list[Tier], animals: list[Animal],
                  reps: int, run_dir: Path) -> list[Job]:
    jobs = []
    for model in models:
        backend = get_backend(model)
        for tier in tiers:
            for animal in animals:
                for rep in range(1, reps + 1):
                    stem = run_dir / "imagegen" / model.name / tier.id / f"{animal.id}__r{rep}"
                    prompt = tier.render(animal)

                    def fn(prompt=prompt, tier=tier, stem=stem, backend=backend):
                        images = [bench.reference_image] if tier.reference else []
                        shutil.rmtree(stem, ignore_errors=True)  # drop images from earlier attempts
                        resp = backend.run(Request(prompt=prompt, images=images, image_out=stem))
                        files = sorted(p for p in resp.images if p.suffix.lower() in IMAGE_SUFFIXES)
                        return {"images": [rel(p, run_dir) for p in files], "text": resp.text, "meta": resp.meta}
                    jobs.append(Job(
                        out=stem.with_suffix(".json"),
                        label=f"{model.name} {tier.id} {animal.id} r{rep}",
                        base={"track": "imagegen", "model": model.name, "vendor": model.vendor, "tier": tier.id,
                              "animal": animal.id, "rep": rep, "prompt": prompt, "reference": tier.reference},
                        fn=fn,
                    ))
    return jobs

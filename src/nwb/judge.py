"""LLM-as-judge prompts, reply validation, and judge job construction."""

import hashlib
import sys
from pathlib import Path

from nwb.backends import Request, get_backend
from nwb.config import Bench, ModelSpec, UnderstandingItem, find_root, model_settings
from nwb.scoring import is_current
from nwb.tracks import Job, rel
from nwb.util import extract_json, read_json

ATTEMPTS = 2
# Image judges answer with words: one judge model given a numeric 0|1|2 template wrote 1 for everything.
TRAIT_LABELS = {"absent": 0, "partial": 1, "match": 2}
IDENTITY_LABELS = {"no": 0, "partly": 1, "clearly": 2}


def understanding_prompt(bench: Bench, item: UnderstandingItem, answer: str) -> str:
    notes = []
    for cid in item.checklist:
        text = bench.criterion(cid)
        if cid in bench.identity and item.animal:
            text += f" (target animal: {item.animal.en})"
        notes.append(f"- [{cid}] {text}")
    has_facts = any(c in bench.facts for c in item.checklist)
    misconceptions = "".join(f"- {m}\n" for m in bench.misconceptions) if has_facts else ""
    background = "".join(f"- {b}\n" for b in bench.background) if has_facts else ""
    shown = (f"\nThe model was shown the attached image(s): {item.image_note}\n"
             "Check visual claims against those images, not just the character's typical appearance.\n"
             if item.modality == "vision" else "")
    ids = ", ".join(f'"{c}": 0|1|2' for c in item.checklist)
    return (
        "You are grading an AI model's answer about the Chinese internet meme 大笑奶龙 (奶蛙) "
        "against reference notes.\n\n"
        "Reference notes (the checklist):\n" + "\n".join(notes) + "\n\n"
        + (f"Background (verified, not scored):\n{background}\n" if background else "")
        + (f"Known misconceptions (asserting any of these confidently is a hallucination):\n{misconceptions}\n"
           if misconceptions else "")
        + f"The model was asked:\n<question>\n{item.prompt}\n</question>\n{shown}\n"
        f"The model answered:\n<answer>\n{answer}\n</answer>\n\n"
        "Score each checklist item: 2 = clearly and correctly covered, 1 = partly covered or vague, "
        "0 = missing or wrong. Give credit only for what the notes support; correct extra detail is fine "
        "but earns nothing.\n"
        "List hallucinations: confident claims that contradict the notes or background, or specific "
        "details (names, dates, events, quotes, visual features) that you are confident are false or made up. "
        "Do not list claims merely because the notes omit them, and do not list claims the model explicitly "
        "marks as uncertain.\n\n"
        f'Reply with only JSON: {{"scores": {{{ids}}}, "hallucinations": ["..."], '
        '"rationale": "<one or two sentences>"}'
    )


def imagegen_prompt(bench: Bench, prompt: str, animal_en: str) -> str:
    traits = "\n".join(f"- {k}: {v}" for k, v in bench.traits.items())
    identity = bench.identity["identity"]
    modes = "\n".join(f"- {k}: {v}" for k, v in bench.failure_modes.items())
    keys = ", ".join(f'"{k}": "absent|partial|match"' for k in bench.traits)
    return (
        "You are judging an image-generation benchmark about the Chinese meme 大笑奶龙 "
        "(Laughing Nailong, also called 奶蛙).\n"
        "The FIRST attached image is the meme's canonical reference. The SECOND attached image was "
        f"generated for this request:\n<request>\n{prompt}\n</request>\n"
        f"The goal is a {animal_en} reimagined in the exact style of the reference meme.\n\n"
        "Rate the second image on each trait as absent, partial, or match (clearly matches the reference, "
        f"adapted to a {animal_en}):\n{traits}\n\n"
        "Judge each trait independently from visible evidence, not a holistic preference. Do not infer "
        "hidden details. Adapt anatomy to the target species (for example, tentacles can clutch the belly); "
        "do not require human hands on an animal. Do not let a polished or cute render compensate for "
        "a missing pose, expression, or animal identity.\n\n"
        f"Also rate identity as no, partly, or clearly: {identity}\n\n"
        f"Flag every failure mode that applies:\n{modes}\n\n"
        "First write one short line per trait and for identity: what the second image actually shows, then "
        "the rating. Then end with the JSON on its own:\n"
        f'{{"traits": {{{keys}}}, "identity": "no|partly|clearly", "failure_modes": [...], '
        '"rationale": "<one or two sentences>"}'
    )


def _score(value, labels: dict[str, int] | None = None) -> int:
    if labels and isinstance(value, str) and value.strip().lower() in labels:
        return labels[value.strip().lower()]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0, 1, 2):
        raise ValueError(f"score must be 0, 1, or 2{' or one of ' + '/'.join(labels) if labels else ''}, got {value!r}")
    return int(value)


def parse_understanding(reply: str, checklist: tuple[str, ...]) -> dict:
    data = extract_json(reply)
    scores = data.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("judge reply has no scores object")
    missing = [c for c in checklist if c not in scores]
    if missing:
        raise ValueError(f"judge reply lacks scores for {missing}")
    halluc = data.get("hallucinations") or []
    if not isinstance(halluc, list):
        raise ValueError("hallucinations must be a list")
    return {"scores": {c: _score(scores[c]) for c in checklist},
            "hallucinations": [str(h) for h in halluc], "rationale": str(data.get("rationale", ""))}


def parse_imagegen(reply: str, bench: Bench) -> dict:
    data = extract_json(reply)
    traits = data.get("traits")
    if not isinstance(traits, dict):
        raise ValueError("judge reply has no traits object")
    missing = [t for t in bench.traits if t not in traits]
    if missing:
        raise ValueError(f"judge reply lacks traits {missing}")
    modes = data.get("failure_modes") or []
    if not isinstance(modes, list):
        raise ValueError("failure_modes must be a list")
    modes = [m for m in modes if m in bench.failure_modes]
    return {"traits": {t: _score(traits[t], TRAIT_LABELS) for t in bench.traits},
            "identity": _score(data.get("identity"), IDENTITY_LABELS),
            "failure_modes": modes, "rationale": str(data.get("rationale", ""))}


def _ask(backend, request: Request, parse) -> dict:
    last_error = None
    for _ in range(ATTEMPTS):
        resp = backend.run(request)
        try:
            return {**parse(resp.text), "raw": resp.text, "meta": resp.meta}
        except ValueError as e:
            last_error = e
    raise ValueError(f"no valid judgment after {ATTEMPTS} attempts: {last_error}")


def judge_jobs(bench: Bench, judges: list[ModelSpec], run_dir: Path, tracks: set[str]) -> list[Job]:
    items = {i.id: i for i in bench.all_items}
    expected = bench.expected_prompts()  # samples made with an outdated prompt are regenerated, not judged
    jobs = []
    for judge in judges:
        backend = get_backend(judge)
        if "understanding" in tracks and "text" in judge.can:
            for path in sorted((run_dir / "understanding").glob("*/*.json")):
                rec = read_json(path)
                item = items.get(rec.get("item"))
                if ("error" in rec or item is None or item.answers or rec.get("contaminated")
                        or rec.get("suite", "core") != bench.suite
                        or not is_current(rec, expected)):
                    continue
                if item.modality == "vision" and "vision" not in judge.can:
                    continue
                request = Request(prompt=understanding_prompt(bench, item, rec["answer"]), images=list(item.images))
                jobs.append(_job(judge, path, run_dir, rec, request,
                                 lambda r, c=item.checklist: parse_understanding(r, c), backend))
        if "imagegen" in tracks:
            if "vision" not in judge.can:
                print(f"{judge.name}: cannot see images; not judging imagegen", file=sys.stderr)
                continue
            for path in sorted((run_dir / "imagegen").glob("*/*/*.json")):
                rec = read_json(path)
                if ("error" in rec or not rec.get("images") or not is_current(rec, expected)
                        or rec.get("suite", "core") != bench.suite):
                    continue
                if bench.all_tiers[rec["tier"]].state:
                    continue  # The laughing rubric is invalid for state transfer; no LLM grading here.
                animal = bench.animals[rec["animal"]]
                request = Request(prompt=imagegen_prompt(bench, rec["prompt"], animal.en),
                                  images=[bench.reference_image, run_dir / rec["images"][0]])
                jobs.append(_job(judge, path, run_dir, rec, request,
                                 lambda r: parse_imagegen(r, bench), backend))
    return jobs


def _job(judge: ModelSpec, target: Path, run_dir: Path, rec: dict, request: Request, parse, backend) -> Job:
    target_rel = rel(target, run_dir)
    settings, settings_id = model_settings(judge)
    # target_sha256 and judge_prompt tie the judgment to this version of the sample and of the rubric, so
    # regenerating either makes nwb judge redo it and nwb report ignore the old one.
    return Job(
        out=run_dir / "judgments" / judge.name / target_rel,
        label=f"judge {judge.name} <- {target_rel}",
        base={"judge": judge.name, "judge_vendor": judge.vendor, "target": target_rel,
              "target_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "settings_id": settings_id, **({"input_names": "neutral"} if request.images else {}),
              "judge_prompt": hashlib.sha256(request.prompt.encode()).hexdigest()[:16],
              "judge_images": [p.relative_to(run_dir).as_posix() if p.is_relative_to(run_dir)
                               else p.relative_to(find_root()).as_posix() for p in request.images],
              "track": rec["track"], "model": rec["model"]},
        fn=lambda: _ask(backend, request, parse), settings=settings, run_dir=run_dir,
    )

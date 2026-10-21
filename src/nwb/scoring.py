"""Turn judgments into per-sample scores and per-model summaries (all scores are 0-100)."""

from collections import defaultdict
from pathlib import Path
from statistics import pstdev

from nwb.util import read_json

HALLUCINATION_PENALTY = 10
NAME_TIERS = ("name_zh", "name_en")


def understanding_score(judgment: dict) -> float:
    """Checklist coverage minus a fixed penalty per confident hallucination, floored at 0."""
    scores = judgment["scores"]
    base = 100 * sum(scores.values()) / (2 * len(scores))
    return max(0.0, base - HALLUCINATION_PENALTY * len(judgment["hallucinations"]))


def image_scores(judgment: dict, weights: dict[str, float]) -> tuple[float, float]:
    """(style, overall): style is weighted trait coverage; overall scales it by animal identity (0, 0.5, 1)."""
    traits = judgment["traits"]
    total = sum(weights.get(t, 1) for t in traits)
    style = 100 * sum(v * weights.get(t, 1) for t, v in traits.items()) / (2 * total)
    return style, style * judgment["identity"] / 2


def pick_judges(judgments: list[dict], subject_vendor: str) -> list[dict]:
    """Prefer judges from other vendors than the subject; fall back to all if none are independent."""
    independent = [j for j in judgments if j["judge_vendor"] != subject_vendor]
    return independent or judgments


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _load_judgments(run_dir: Path, judges: set[str] | None) -> dict[str, list[dict]]:
    """Successful judgments by target, keeping only those made for the target's current version and,
    when `judges` is given, only those judges."""
    by_target = defaultdict(list)
    for path in sorted((run_dir / "judgments").rglob("*.json")):
        j = read_json(path)
        if "error" in j or (judges and j["judge"] not in judges):
            continue
        target = run_dir / j["target"]
        if target.is_file() and j.get("target_mtime") == target.stat().st_mtime:
            by_target[j["target"]].append(j)
    return by_target


def _samples(run_dir: Path, track: str, pattern: str, by_target: dict) -> list[tuple[dict, list[dict]]]:
    out = []
    for path in sorted((run_dir / track).glob(pattern)):
        rec = read_json(path)
        if "error" in rec:
            continue
        rec["target"] = path.relative_to(run_dir).as_posix()
        out.append((rec, pick_judges(by_target.get(rec["target"], []), rec["vendor"])))
    return out


def aggregate(run_dir: Path, trait_weights: dict[str, float], judges: set[str] | None = None) -> dict:
    by_target = _load_judgments(run_dir, judges)
    judges = sorted({j["judge"] for js in by_target.values() for j in js})

    und, contaminated = [], defaultdict(int)
    for rec, js in _samples(run_dir, "understanding", "*/*.json", by_target):
        if rec.get("contaminated"):
            contaminated[rec["model"]] += 1
            continue
        per_judge = {j["judge"]: understanding_score(j) for j in js}
        und.append({
            **{k: rec[k] for k in ("model", "item", "modality", "lang", "rep", "target", "answer")},
            "score": mean(per_judge.values()), "per_judge": per_judge,
            "hallucinations": [h for j in js for h in j["hallucinations"]],
            "rationales": {j["judge"]: j["rationale"] for j in js},
        })

    img = []
    for rec, js in _samples(run_dir, "imagegen", "*/*/*.json", by_target):
        pairs = [image_scores(j, trait_weights) for j in js]
        modes = defaultdict(int)
        for j in js:
            for m in j["failure_modes"]:
                modes[m] += 1
        img.append({
            **{k: rec[k] for k in ("model", "tier", "animal", "rep", "target", "prompt", "images")},
            "verbatim": rec.get("meta", {}).get("audit", {}).get("verbatim"),
            "style": mean(p[0] for p in pairs), "overall": mean(p[1] for p in pairs),
            "per_judge": {j["judge"]: p[1] for j, p in zip(js, pairs)},
            "identity": mean(j["identity"] for j in js),
            "traits": {t: mean(j["traits"][t] for j in js) for t in (js[0]["traits"] if js else {})},
            # A failure mode counts when at least half of the judges flagged it.
            "failure_modes": sorted(m for m, n in modes.items() if js and n * 2 >= len(js)),
            "rationales": {j["judge"]: j["rationale"] for j in js},
        })

    return {"judges": judges, "judge_health": judge_health(by_target, trait_weights), "understanding": _summarize_understanding(und, contaminated),
            "imagegen": _summarize_imagegen(img), "samples": {"understanding": und, "imagegen": img}}


def judge_health(by_target: dict[str, list[dict]], trait_weights: dict[str, float]) -> dict:
    """Per judge and track: how much its scores vary across samples (a judge that gives everything the
    same score is not discriminating) and how far it sits from the other judges on the same samples."""
    stats = defaultdict(lambda: {"scores": [], "deviation": []})
    for js in by_target.values():
        scores = {j["judge"]: (image_scores(j, trait_weights)[1] if "traits" in j else understanding_score(j))
                  for j in js}
        track = "imagegen" if "traits" in js[0] else "understanding"
        for judge, score in scores.items():
            stats[(judge, track)]["scores"].append(score)
            others = [v for k, v in scores.items() if k != judge]
            if others:
                stats[(judge, track)]["deviation"].append(abs(score - mean(others)))
    health = defaultdict(dict)
    for (judge, track), s in sorted(stats.items()):
        health[judge][track] = {"n": len(s["scores"]), "spread": pstdev(s["scores"]),
                                "deviation": mean(s["deviation"])}
    return dict(health)


def _summarize_understanding(samples: list[dict], contaminated: dict[str, int]) -> dict:
    by_model = defaultdict(list)
    for s in samples:
        if s["score"] is not None:
            by_model[s["model"]].append(s)
    # Models whose answers all used tools still appear, with no scores.
    summary = {m: {"overall": None, "text": None, "vision": None, "hallucinations_per_answer": None,
                   "items": {}, "per_judge": {}, "contaminated": n} for m, n in contaminated.items()}
    for model, ss in by_model.items():
        items = defaultdict(list)
        for s in ss:
            items[(s["item"], s["modality"])].append(s["score"])
        item_means = {item: mean(v) for (item, _), v in items.items()}
        summary[model] = {
            "overall": mean(item_means.values()),
            "text": mean(mean(v) for (_, mod), v in items.items() if mod == "text"),
            "vision": mean(mean(v) for (_, mod), v in items.items() if mod == "vision"),
            "hallucinations_per_answer": mean(len(s["hallucinations"]) / max(1, len(s["per_judge"])) for s in ss),
            "items": item_means,
            "per_judge": {j: mean(s["per_judge"].get(j) for s in ss)
                          for j in sorted({j for s in ss for j in s["per_judge"]})},
            "contaminated": contaminated.get(model, 0),
        }
    return summary


def _summarize_imagegen(samples: list[dict]) -> dict:
    by_model = defaultdict(list)
    for s in samples:
        if s["overall"] is not None:
            by_model[s["model"]].append(s)
    summary = {}
    for model, ss in by_model.items():
        tiers = defaultdict(list)
        for s in ss:
            tiers[s["tier"]].append(s)
        tier_overall = {t: mean(s["overall"] for s in v) for t, v in tiers.items()}
        name_score = mean(tier_overall.get(t) for t in NAME_TIERS)
        described = tier_overall.get("described")
        modes = defaultdict(int)
        for s in ss:
            for m in s["failure_modes"]:
                modes[m] += 1
        summary[model] = {
            "overall": mean(s["overall"] for s in ss),
            "tiers": {t: {"overall": tier_overall[t], "style": mean(s["style"] for s in v), "n": len(v)}
                      for t, v in tiers.items()},
            "knowledge_ratio": name_score / described if name_score is not None and described else None,
            "identity": mean(s["identity"] for s in ss),
            "traits": {t: mean(s["traits"].get(t) for s in ss) for t in (ss[0]["traits"] if ss else {})},
            "failure_modes": dict(modes),
            "not_verbatim": sum(1 for s in ss if s["verbatim"] is False),
            "n": len(ss),
        }
    return summary

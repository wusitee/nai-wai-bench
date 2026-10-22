"""Turn judgments into per-sample scores and per-model summaries (all scores are 0-100)."""

from collections import defaultdict
from pathlib import Path
from statistics import pstdev

from nwb.config import Bench
from nwb.util import extract_json, read_json

HALLUCINATION_PENALTY = 10
NAME_TIERS = ("name_zh", "name_en")
CEILING_TIER = "described_detailed"  # the knowledge ratio's denominator: the best-specified prompt


def understanding_score(judgment: dict) -> float:
    """Checklist coverage minus a fixed penalty per confident hallucination, floored at 0."""
    scores = judgment["scores"]
    base = 100 * sum(scores.values()) / (2 * len(scores))
    return max(0.0, base - HALLUCINATION_PENALTY * len(judgment["hallucinations"]))


def grounding_score(answer: str, key: dict[str, str]) -> float:
    """Equal credit per correct visual field; malformed replies and abstentions get no credit."""
    try:
        reply = extract_json(answer)
    except ValueError:
        return 0.0
    return 100 * sum(isinstance(reply.get(k), str) and reply[k].strip().lower() == v
                     for k, v in key.items()) / len(key)


def image_scores(judgment: dict, weights: dict[str, float]) -> tuple[float, float]:
    """(style, overall): style is weighted trait coverage; overall scales it by animal identity (0, 0.5, 1)."""
    traits = judgment["traits"]
    total = sum(weights.get(t, 1) for t in traits)
    style = 100 * sum(v * weights.get(t, 1) for t, v in traits.items()) / (2 * total)
    return style, style * judgment["identity"] / 2


def sample_key(rec: dict) -> str:
    if rec["track"] == "understanding":
        return f"understanding/{rec['item']}"
    return f"imagegen/{rec['tier']}/{rec['animal']}"


def is_current(rec: dict, expected: dict[str, str] | None) -> bool:
    """Whether a sample was made with the bench's current prompt (always true when `expected` is None)."""
    if expected is None:
        return True
    key = sample_key(rec)
    return key in expected and expected[key] == rec.get("prompt")


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
        out.append((rec, by_target.get(rec["target"], [])))
    return out


def aggregate(run_dir: Path, trait_weights: dict[str, float], judges: set[str] | None = None,
              expected: dict[str, str] | None = None, bench: Bench | None = None) -> dict:
    """Score a run. `expected` (Bench.expected_prompts) restricts it to samples made with the current
    prompts, leaving out removed items and tiers and samples whose prompt has since changed."""
    if bench is not None:
        expected = bench.expected_prompts()
    by_target = _load_judgments(run_dir, judges)
    judges = sorted({j["judge"] for js in by_target.values() for j in js})
    items = {i.id: i for i in bench.all_items} if bench else {}

    und, contaminated, state_contaminated = [], defaultdict(int), defaultdict(int)
    for rec, js in _samples(run_dir, "understanding", "*/*.json", by_target):
        if not is_current(rec, expected):
            continue
        item = items.get(rec["item"])
        if rec.get("contaminated"):
            counts = state_contaminated if item and item.state else contaminated
            counts[rec["model"]] += 1
            continue
        if item and item.modality == "vision":
            # Legacy judgments made from a text description alone are not visual evidence.
            js = [j for j in js if j.get("judge_images") == [str(p) for p in item.images]]
        js = pick_judges(js, rec["vendor"])
        per_judge = {j["judge"]: understanding_score(j) for j in js}
        objective = bool(item and item.answers)
        und.append({
            **{k: rec[k] for k in ("model", "item", "modality", "lang", "rep", "target", "answer")},
            "score": grounding_score(rec["answer"], item.answers) if objective else mean(per_judge.values()),
            "per_judge": {} if objective else per_judge, "objective": objective,
            "control_for": item.control_for if item else "",
            "state": item.state if item else rec.get("state", ""),
            "hallucinations": [] if objective else [h for j in js for h in j["hallucinations"]],
            "rationales": {} if objective else {j["judge"]: j["rationale"] for j in js},
        })

    img = []
    for rec, js in _samples(run_dir, "imagegen", "*/*/*.json", by_target):
        if not is_current(rec, expected):
            continue
        tier = bench.all_tiers.get(rec["tier"]) if bench else None
        state = tier.state if tier else rec.get("state", "")
        # State outputs stay unscored: the canonical laughing rubric is not applicable.
        js = [] if state else pick_judges(js, rec["vendor"])
        pairs = [image_scores(j, trait_weights) for j in js]
        modes = defaultdict(int)
        for j in js:
            for m in j["failure_modes"]:
                modes[m] += 1
        # A provider refusal of the verbatim benchmark prompt is a failed cell, scored 0 without judges.
        refused = bool(rec.get("refused")) and not state
        img.append({
            **{k: rec[k] for k in ("model", "tier", "animal", "rep", "target", "prompt", "images")},
            "verbatim": rec.get("meta", {}).get("audit", {}).get("verbatim"),
            "state": state, "refused": refused,
            "style": 0.0 if refused else mean(p[0] for p in pairs),
            "overall": 0.0 if refused else mean(p[1] for p in pairs),
            "per_judge": {j["judge"]: p[1] for j, p in zip(js, pairs)},
            "identity": mean(j["identity"] for j in js),
            "traits": {t: mean(j["traits"][t] for j in js) for t in (js[0]["traits"] if js else {})},
            # A failure mode counts when at least half of the judges flagged it.
            "failure_modes": sorted(m for m, n in modes.items() if js and n * 2 >= len(js)),
            "rationales": {j["judge"]: j["rationale"] for j in js},
        })

    scores = {"judges": judges, "judge_health": judge_health(by_target, trait_weights),
              "understanding": _summarize_understanding([s for s in und if not s["state"]], contaminated),
              "state_understanding": _summarize_understanding([s for s in und if s["state"]], state_contaminated),
              "imagegen": _summarize_imagegen(img), "samples": {"understanding": und, "imagegen": img}}
    scores["leaderboards"] = leaderboards(bench, scores, run_dir) if bench else {}
    return scores


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
        by_model[s["model"]].append(s)
    # Models whose answers all used tools still appear, with no scores.
    summary = {m: {"overall": None, "text": None, "vision": None, "hallucinations_per_answer": None,
                   "items": {}, "per_judge": {}, "contaminated": n} for m, n in contaminated.items()}
    for model, all_samples in by_model.items():
        ss = [s for s in all_samples if s["score"] is not None and not s.get("control_for")]
        controls = {(s.get("control_for"), s["rep"]): s["score"] for s in all_samples
                    if s.get("control_for") and s["score"] is not None}
        items = defaultdict(list)
        for s in ss:
            items[(s["item"], s["modality"])].append(s["score"])
        item_means = {item: mean(v) for (item, _), v in items.items()}
        summary[model] = {
            # Text is a diagnostic and never changes the visual-understanding order.
            "overall": mean(mean(v) for (_, mod), v in items.items() if mod == "vision"),
            "text": mean(mean(v) for (_, mod), v in items.items() if mod == "text"),
            "vision": mean(mean(v) for (_, mod), v in items.items() if mod == "vision"),
            "languages": {lang: mean(mean(s["score"] for s in ss if s["item"] == item)
                                     for item in {s["item"] for s in ss if s["modality"] == "text" and s["lang"] == lang})
                          for lang in ("zh", "en")},
            "grounding": mean(v for item, v in item_means.items()
                              if any(s["item"] == item and s.get("objective") for s in ss)),
            "blind": mean(mean(s["score"] for s in all_samples if s.get("control_for") == item)
                          for item in {s["control_for"] for s in all_samples if s.get("control_for")}),
            "visual_gain": mean(mean(s["score"] - controls[(s["item"], s["rep"])] for s in ss
                                     if s["item"] == item and (item, s["rep"]) in controls)
                                for item in {s["item"] for s in ss if s.get("objective")}),
            "hallucinations_per_answer": mean(len(s["hallucinations"]) / len(s["per_judge"])
                                              for s in ss if s["per_judge"]),
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
        cells = defaultdict(list)
        for s in ss:
            cells[(s["tier"], s["animal"])].append(s)
        tiers = defaultdict(list)
        for (tier, animal), reps in cells.items():
            tiers[tier].append({"animal": animal, "overall": mean(s["overall"] for s in reps),
                                "style": mean(s["style"] for s in reps)})
        tier_overall = {t: mean(s["overall"] for s in v) for t, v in tiers.items()}
        # Compare the same animals in all three tiers; missing cells cannot inflate the ratio.
        matched = [a for a in {s["animal"] for s in ss}
                   if all((t, a) in cells for t in (*NAME_TIERS, CEILING_TIER))]
        name_score = mean(mean(mean(s["overall"] for s in cells[(t, a)]) for t in NAME_TIERS) for a in matched)
        described = mean(mean(s["overall"] for s in cells[(CEILING_TIER, a)]) for a in matched)
        modes = defaultdict(int)
        for s in ss:
            for m in s["failure_modes"]:
                modes[m] += 1
        summary[model] = {
            "overall": mean(tier_overall.values()),
            "tiers": {t: {"overall": tier_overall[t], "style": mean(s["style"] for s in v),
                          "n": sum(s["tier"] == t for s in ss)}
                      for t, v in tiers.items()},
            "animals": {a: mean(s["overall"] for v in tiers.values() for s in v if s["animal"] == a)
                        for a in sorted({s["animal"] for s in ss})},
            "knowledge_ratio": name_score / described if name_score is not None and described else None,
            "knowledge_animals": len(matched),
            "identity": mean(s["identity"] for s in ss),
            "traits": {t: mean(s["traits"].get(t) for s in ss) for t in dict.fromkeys(t for s in ss for t in s["traits"])},
            "failure_modes": dict(modes),
            "not_verbatim": sum(1 for s in ss if s["verbatim"] is False),
            "n": len(ss),
        }
    return summary


def leaderboards(bench: Bench, scores: dict, run_dir: Path) -> dict:
    """Rank only a complete, balanced fixed panel; extra tasks never change a panel's score."""
    expected = bench.expected_prompts()
    panels = {
        "visual_understanding": ("understanding", {(i.id,) for i in bench.items if i.modality == "vision"},
                                 ("item",), "score"),
        "imagegen": ("imagegen", {(t, a.id) for t in bench.tiers for a in bench.select_animals("default")},
                     ("tier", "animal"), "overall"),
    }
    boards = {}
    for name, (track, required, fields, metric) in panels.items():
        samples = scores["samples"][track]
        models = {p.name for p in (run_dir / track).iterdir() if p.is_dir()} if (run_dir / track).is_dir() else set()
        rows = []
        for model in sorted(models):
            attempted_reps = set()
            pattern = "*.json" if track == "understanding" else "*/*.json"
            for path in (run_dir / track / model).glob(pattern):
                rec = read_json(path)
                if tuple(rec[f] for f in fields) in required and is_current(rec, expected):
                    attempted_reps.add(rec["rep"])
            if not attempted_reps:
                continue  # never attempted this panel, e.g. a text-only model on the visual panel
            cells = defaultdict(list)
            for s in samples:
                key = tuple(s[f] for f in fields)
                if (s["model"] == model and key in required and s[metric] is not None
                        and (track != "imagegen" or s["verbatim"] is True)):
                    cells[key].append(s)
            rep_sets = [{s["rep"] for s in cell} for cell in cells.values()]
            complete = bool(required) and set(cells) == required
            balanced = complete and all(rs == attempted_reps for rs in rep_sets)
            rows.append({"model": model, "rank": None,
                         "score": mean(mean(s[metric] for s in v) for v in cells.values()) if balanced else None,
                         "completed": len(cells), "required": len(required),
                         "repetitions": min(map(len, rep_sets), default=0) if complete else 0,
                         "status": "complete" if balanced else "incomplete repetitions" if complete else "incomplete"})
        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["model"]))
        previous, rank = None, 0
        for index, row in enumerate(rows, 1):
            if row["score"] is not None:
                if row["score"] != previous:
                    rank = index
                row["rank"] = rank
                previous = row["score"]
        boards[name] = rows
    return boards

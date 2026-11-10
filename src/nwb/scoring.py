"""Turn judgments into per-sample scores and per-model summaries (all scores are 0-100)."""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import math
import random
from pathlib import Path
from statistics import median, pstdev

from nwb import __version__
from nwb.config import Bench, load_models
from nwb.provenance import collection_profile
from nwb.util import extract_json, read_json

HALLUCINATION_PENALTY = 10
NAME_TIERS = ("name_zh", "name_en")
CEILING_TIER = "described_detailed"  # the knowledge ratio's denominator: the best-specified prompt
# Judges counted in scores: None for every recorded judge, one set for both tracks, or a set per track.
JudgeSelection = set[str] | dict[str, set[str]] | None


def understanding_score(judgment: dict) -> float:
    """Checklist coverage minus a fixed penalty per confident hallucination, floored at 0."""
    scores = judgment["scores"]
    base = 100 * sum(scores.values()) / (2 * len(scores))
    return max(0.0, base - HALLUCINATION_PENALTY * len(judgment["hallucinations"]))


def grounding_fields(answer: str, key: dict[str, str]) -> dict[str, float]:
    """Score observable fields independently; malformed replies and abstentions get no credit."""
    try:
        reply = extract_json(answer)
    except ValueError:
        reply = {}
    return {k: 100.0 if isinstance(reply.get(k), str) and reply[k].strip().lower() == v else 0.0
            for k, v in key.items()}


def grounding_score(answer: str, key: dict[str, str]) -> float:
    """Equal credit per correct visual field."""
    return mean(grounding_fields(answer, key).values())


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


def judgment_prompt(bench: Bench, rec: dict) -> str | None:
    """The grading text constructed by nwb judge, without instantiating a backend."""
    from nwb.judge import imagegen_prompt, understanding_prompt

    if rec["track"] == "understanding":
        item = next((i for i in bench.all_items if i.id == rec.get("item")), None)
        return understanding_prompt(bench, item, rec.get("answer", "")) if item else None
    if rec.get("animal") in bench.animals:
        return imagegen_prompt(bench, rec["prompt"], bench.animals[rec["animal"]].en)
    return None


def _load_judgments(run_dir: Path, judges: JudgeSelection, bench: Bench | None = None,
                    stale: dict | None = None) -> dict[str, list[dict]]:
    """Check sample identity and the current judge request, without constructing a backend."""
    by_target = defaultdict(list)
    for path in sorted((run_dir / "judgments").rglob("*.json")):
        j = read_json(path)
        allowed = judges.get(j["target"].split("/", 1)[0], set()) if isinstance(judges, dict) else judges
        if "error" in j or (allowed is not None and j["judge"] not in allowed):
            continue
        target = run_dir / j["target"]
        reason = None
        if not target.is_file():
            reason = "target missing"
        elif (hashlib.sha256(target.read_bytes()).hexdigest() != j["target_sha256"]
              if "target_sha256" in j else j.get("target_mtime") != target.stat().st_mtime):
            reason = "target changed"
        elif bench:
            rec = read_json(target)
            if rec.get("suite", "core") != bench.suite:
                continue
            prompt = judgment_prompt(bench, rec)
            if prompt is None or j.get("judge_prompt") != hashlib.sha256(prompt.encode()).hexdigest()[:16]:
                reason = "judge prompt changed"
        if reason:
            if stale is not None:
                stale[reason] = stale.get(reason, 0) + 1
            continue
        by_target[j["target"]].append(j)
    return by_target


def _evidence_path(path: str) -> str:
    """Benchmark-relative evidence paths survive relocation and home-prefix sanitization."""
    parts = Path(path).parts
    return Path(*parts[parts.index("bench"):]).as_posix() if "bench" in parts else path


def _samples(run_dir: Path, track: str, pattern: str, by_target: dict) -> list[tuple[dict, list[dict]]]:
    out = []
    for path in sorted((run_dir / track).glob(pattern)):
        rec = read_json(path)
        if "error" in rec:
            continue
        rec["target"] = path.relative_to(run_dir).as_posix()
        out.append((rec, by_target.get(rec["target"], [])))
    return out


def _profile_groups(records, identifier: str) -> dict[str, list[str]]:
    groups = defaultdict(set)
    for record in records:
        profile = collection_profile(record)
        if "error" not in record and profile:
            groups[record[identifier]].add(profile)
    return {name: sorted(profiles) for name, profiles in sorted(groups.items())}


def aggregate(run_dir: Path, trait_weights: dict[str, float], judges: JudgeSelection = None,
              expected: dict[str, str] | None = None, bench: Bench | None = None) -> dict:
    """Score a run. `expected` (Bench.expected_prompts) restricts it to samples made with the current
    prompts, leaving out removed items and tiers and samples whose prompt has since changed."""
    if bench is not None:
        expected = bench.expected_prompts()
    stale = {}
    by_target = _load_judgments(run_dir, judges, bench, stale)
    judges = sorted({j["judge"] for js in by_target.values() for j in js})
    items = {i.id: i for i in bench.all_items} if bench else {}

    und, contaminated, state_contaminated = [], defaultdict(int), defaultdict(int)
    for rec, js in _samples(run_dir, "understanding", "*/*.json", by_target):
        if not is_current(rec, expected) or (bench and rec.get("suite", "core") != bench.suite):
            continue
        item = items.get(rec["item"])
        if rec.get("contaminated"):
            counts = state_contaminated if item and item.state else contaminated
            counts[rec["model"]] += 1
            continue
        if item and item.modality == "vision":
            # Legacy judgments made from a text description alone are not visual evidence.
            js = [j for j in js if [_evidence_path(p) for p in j.get("judge_images", [])]
                  == [_evidence_path(str(p)) for p in item.images]]
        js = pick_judges(js, rec["vendor"])
        per_judge = {j["judge"]: understanding_score(j) for j in js}
        objective = bool(item and item.answers)
        fields = grounding_fields(rec["answer"], item.answers) if objective else {}
        und.append({
            **{k: rec[k] for k in ("model", "item", "modality", "lang", "rep", "target", "answer")},
            "score": mean(fields.values()) if objective else mean(per_judge.values()),
            "joint": (100.0 if all(v == 100 for v in fields.values()) else 0.0) if objective else None,
            "per_judge": {} if objective else per_judge, "objective": objective,
            "fields": fields, "family": item.answers.get("family", "") if objective else "",
            "category": item.category if item else "",
            "control_for": item.control_for if item else "",
            "state": item.state if item else rec.get("state", ""),
            "hallucinations": [] if objective else [h for j in js for h in j["hallucinations"]],
            "rationales": {} if objective else {j["judge"]: j["rationale"] for j in js},
        })

    img = []
    for rec, js in _samples(run_dir, "imagegen", "*/*/*.json", by_target):
        if not is_current(rec, expected) or (bench and rec.get("suite", "core") != bench.suite):
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

    scores = {"nwb_version": __version__, "stale_judgments": {"total": sum(stale.values()), "reasons": stale},
              "suite": bench.suite if bench else "core", "judges": judges,
              "judge_health": judge_health(by_target, trait_weights),
              "understanding": _summarize_understanding([s for s in und if not s["state"]], contaminated),
              "state_understanding": _summarize_understanding([s for s in und if s["state"]], state_contaminated),
              "imagegen": _summarize_imagegen(img), "samples": {"understanding": und, "imagegen": img}}
    scores["leaderboards"] = leaderboards(bench, scores, run_dir) if bench else {}
    records = [read_json(p) for track, pattern in (("understanding", "*/*.json"), ("imagegen", "*/*/*.json"))
               for p in sorted((run_dir / track).glob(pattern))]
    judgments = [read_json(p) for p in sorted((run_dir / "judgments").rglob("*.json"))]
    collected = [r["collected"] for r in records + judgments if r.get("collected")]
    scores["collection"] = {
        "started_at": min((c["started_at"] for c in collected if c.get("started_at")), default=None),
        "finished_at": max((c["finished_at"] for c in collected if c.get("finished_at")), default=None),
        "revisions": sorted({c["revision"] for c in collected if c.get("revision")}),
        "dirty": any(c.get("revision", "").endswith("+dirty") for c in collected),
        "recorded": len(collected), "tasks": len(records) + len(judgments),
        "subject_profiles": _profile_groups((r for r in records if r.get("track") == "understanding"), "model"),
        "judge_profiles": _profile_groups(judgments, "judge"),
    }
    models = load_models(bench.root)[0] if bench else {}
    scores["labels"] = {}
    for model in sorted({r["model"] for r in records if "model" in r}):
        label = models[model].label if model in models else model
        efforts = {r.get("settings", {}).get("effort") for r in records
                   if r.get("model") == model and r.get("track") == "understanding"}
        efforts.discard(None)
        if len(efforts) == 1 and next(iter(efforts)) not in ("default", "unexposed"):
            suffix = f" ({next(iter(efforts))})"
            if not label.endswith(suffix):
                label += suffix
        scores["labels"][model] = label
    for rows in scores["leaderboards"].values():
        for row in rows:
            row["label"] = scores["labels"].get(row["model"], row["model"])
    scores["efficiency"] = efficiency(records, judgments, bench, models)
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
            **_objective_diagnostics(ss),
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


def _objective_diagnostics(samples: list[dict]) -> dict:
    """Balance repetitions within each item before reporting fields, categories, and family classes."""
    by_item = defaultdict(list)
    for s in samples:
        if s.get("fields"):
            by_item[s["item"]].append(s)
    cells = [{"fields": {f: mean(s["fields"][f] for s in reps) for f in reps[0]["fields"]},
              "score": mean(s["score"] for s in reps), "family": reps[0]["family"],
              "joint": mean(s["joint"] for s in reps),
              "visual_joint": mean(100.0 if all(v == 100 for f, v in s["fields"].items() if f != "family")
                                   else 0.0 for s in reps),
              "category": reps[0]["category"]} for reps in by_item.values()]
    fields = dict.fromkeys(f for cell in cells for f in cell["fields"])
    families = {label: mean(c["fields"]["family"] for c in cells if c["family"] == label)
                for label in sorted({c["family"] for c in cells if c["family"]})}
    return {
        "fields": {f: mean(c["fields"].get(f) for c in cells) for f in fields},
        "field_items": {f: sum(f in c["fields"] for c in cells) for f in fields},
        "family_classes": families, "family_macro": mean(families.values()),
        "joint": mean(c["joint"] for c in cells),
        "visual_joint": mean(c["visual_joint"] for c in cells),
        "repetition_consistency": mean(100.0 if len({s["joint"] for s in reps}) == 1 else 0.0
                                       for reps in by_item.values() if len(reps) >= 2),
        "repetition_consistency_images": sum(len(reps) >= 2 for reps in by_item.values()),
        "categories": {category: mean(c["score"] for c in cells if c["category"] == category)
                       for category in sorted({c["category"] for c in cells if c["category"]})},
    }


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


def _panels(bench: Bench) -> dict:
    """Fixed ranking panels: track, required cells, cell key fields, and the per-sample metric."""
    return {
        "visual_understanding": ("understanding", {(i.id,) for i in bench.items if i.modality == "vision"},
                                 ("item",), "joint" if bench.suite == "naihub-v1" else "score"),
        "imagegen": ("imagegen", {(t, a.id) for t in bench.tiers for a in bench.select_animals("default")},
                     ("tier", "animal"), "overall"),
    }


def leaderboards(bench: Bench, scores: dict, run_dir: Path) -> dict:
    """Rank only a complete, balanced fixed panel; extra tasks never change a panel's score."""
    expected = bench.expected_prompts()
    boards = {}
    for name, (track, required, fields, metric) in _panels(bench).items():
        samples = scores["samples"][track]
        models = {p.name for p in (run_dir / track).iterdir() if p.is_dir()} if (run_dir / track).is_dir() else set()
        rows = []
        for model in sorted(models):
            attempted_reps = set()
            records = []
            pattern = "*.json" if track == "understanding" else "*/*.json"
            for path in (run_dir / track / model).glob(pattern):
                rec = read_json(path)
                if (tuple(rec[f] for f in fields) in required and is_current(rec, expected)
                        and rec.get("suite", "core") == bench.suite):
                    attempted_reps.add(rec["rep"])
                    records.append(rec)
            if not attempted_reps:
                continue  # never attempted this panel, e.g. a text-only model on the visual panel
            cells = defaultdict(list)
            for s in samples:
                key = tuple(s[f] for f in fields)
                if (s["model"] == model and key in required and s[metric] is not None
                        and (track != "imagegen" or s["verbatim"] is True)):
                    cells[key].append(s)
            # Collected repetitions that only lack judgments, e.g. from a contributor without the judge models.
            unjudged = {(tuple(s[f] for f in fields), s["rep"]) for s in samples
                        if s["model"] == model and tuple(s[f] for f in fields) in required and s[metric] is None
                        and (track != "imagegen" or s["verbatim"] is True)}
            scored = {(key, s["rep"]) for key, cell in cells.items() for s in cell}
            awaiting = bool(unjudged) and scored | unjudged == {(c, r) for c in required for r in attempted_reps}
            rep_sets = [{s["rep"] for s in cell} for cell in cells.values()]
            complete = bool(required) and set(cells) == required
            balanced = complete and all(rs == attempted_reps for rs in rep_sets)
            settings = {r.get("settings_id") for r in records}
            efforts = {r.get("settings", {}).get("effort") for r in records}
            differences = []
            if len(settings) > 1:
                differences.append("settings_id: " + ", ".join(sorted(str(v) for v in settings)))
            if len(efforts) > 1:
                differences.append("effort: " + ", ".join(sorted(str(v) for v in efforts)))
            fills = sorted({str(r["meta"]["fill_note"]) for r in records if "fill_note" in r.get("meta", {})})
            if fills:
                differences.append("alternate route: " + "; ".join(fills))
            value = mean(mean(s[metric] for s in v) for v in cells.values())
            rows.append({"model": model, "rank": None,
                         "score": value if balanced and not differences else None,
                         "diagnostic_score": value, "conditions": differences,
                         "settings_status": "settings unrecorded" if settings == {None} else "recorded",
                         "settings_ids": sorted(v for v in settings if v is not None),
                         "collection_profiles": sorted({collection_profile(r) for r in records if collection_profile(r)}),
                         "judges": dict(sorted(Counter(j for cell in cells.values() for s in cell
                                                       for j in s["per_judge"]).items())),
                         "score_interval": None, "rank_range": None,
                         "completed": len(cells), "required": len(required),
                         "repetitions": min(map(len, rep_sets), default=0) if complete else 0,
                         "status": "mixed conditions" if differences else "complete" if balanced else
                                   "awaiting judges" if awaiting else
                                   "incomplete repetitions" if complete else "incomplete"})
        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["model"]))
        previous, rank = None, 0
        for index, row in enumerate(rows, 1):
            if row["score"] is not None:
                if row["score"] != previous:
                    rank = index
                row["rank"] = rank
                previous = row["score"]
        _bootstrap(rows, samples, required, fields, metric, bench, track)
        boards[name] = rows
    return boards


BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 6643


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    index = (len(values) - 1) * q
    low = int(index)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (index - low)


def _draws(models, samples, required, fields, metric, bench, track) -> tuple[dict[str, list[float]], int]:
    """Panel scores under paired source/animal cluster resampling; keep all cells and their repetition means."""
    items = {i.id: i for i in bench.items}
    clusters = defaultdict(list)
    for cell in sorted(required):
        cluster = cell[1] if track == "imagegen" else tuple(str(p.resolve()) for p in items[cell[0]].images)
        clusters[cluster].append(cell)
    groups = list(clusters.values())
    cell_scores = {}
    for model in models:
        cell_scores[model] = {
            cell: mean(s[metric] for s in samples if s["model"] == model
                       and tuple(s[f] for f in fields) == cell
                       and (track != "imagegen" or s["verbatim"] is True)) for cell in sorted(required)}
    draws = defaultdict(list)
    rng = random.Random(BOOTSTRAP_SEED)
    for _ in range(BOOTSTRAP_RESAMPLES):
        cells = [cell for group in rng.choices(groups, k=len(groups)) for cell in group]
        for model, cs in cell_scores.items():
            draws[model].append(mean(cs[c] for c in cells))
    return draws, len(groups)


def _intervals(rows: list[dict], draws: dict[str, list[float]]) -> None:
    """95% percentile score intervals and rank ranges over the same resamples for every ranked row."""
    ranked = [r["model"] for r in rows if r["score"] is not None]
    ranks = {m: sorted(1 + sum(draws[o][i] > draws[m][i] for o in ranked) for i in range(BOOTSTRAP_RESAMPLES))
             for m in ranked}
    for row in rows:
        if row["score"] is not None:
            row["score_interval"] = [_percentile(draws[row["model"]], q) for q in (.025, .975)]
            row["rank_range"] = [ranks[row["model"]][math.ceil(BOOTSTRAP_RESAMPLES * q) - 1] for q in (.025, .975)]


def _bootstrap(rows, samples, required, fields, metric, bench, track):
    ranked = [r["model"] for r in rows if r["score"] is not None]
    if not ranked:
        return
    draws, clusters = _draws(ranked, samples, required, fields, metric, bench, track)
    _intervals(rows, draws)
    for row in rows:
        if row["score"] is not None:
            row["bootstrap"] = {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                                "clusters": clusters, "cluster": "animal" if track == "imagegen" else "source image"}


# NaiWai Index v1: weighted mean of the two visual rankings. Nai-hub's answer-keyed panel counts double the
# smaller, partly judge-scored Meme ID panel.
INDEX_VERSION = 1
INDEX_WEIGHTS = {"core": 1, "naihub-v1": 2}


def naiwai_index(suites: dict[str, tuple[Bench, dict]]) -> dict:
    """Combine each suite's ranked visual score; models ranked in every component receive an index rank.

    Suites are resampled independently, so pairing their draws by resample number gives joint draws."""
    boards = {suite: {r["model"]: r for r in suites[suite][1]["leaderboards"]["visual_understanding"]}
              for suite in INDEX_WEIGHTS}
    total = sum(INDEX_WEIGHTS.values())
    rows = []
    for model in sorted(set().union(*boards.values())):
        parts = {suite: boards[suite].get(model, {}).get("score") for suite in INDEX_WEIGHTS}
        complete = all(v is not None for v in parts.values())
        rows.append({"model": model, "rank": None,
                     "score": sum(INDEX_WEIGHTS[s] * v for s, v in parts.items()) / total if complete else None,
                     "components": {s: {"score": v, "rank": boards[s].get(model, {}).get("rank")}
                                    for s, v in parts.items()},
                     "status": "complete" if complete else "partial",
                     "score_interval": None, "rank_range": None})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["model"]))
    previous, rank = None, 0
    for position, row in enumerate(rows, 1):
        if row["score"] is not None:
            if row["score"] != previous:
                rank = position
            row["rank"] = rank
            previous = row["score"]
    ranked = [r["model"] for r in rows if r["score"] is not None]
    if ranked:
        combined = {m: [0.0] * BOOTSTRAP_RESAMPLES for m in ranked}
        for suite, weight in INDEX_WEIGHTS.items():
            bench, scores = suites[suite]
            track, required, fields, metric = _panels(bench)["visual_understanding"]
            draws, _ = _draws(ranked, scores["samples"][track], required, fields, metric, bench, track)
            for m in ranked:
                combined[m] = [c + weight * d / total for c, d in zip(combined[m], draws[m])]
        _intervals(rows, combined)
    return {"version": INDEX_VERSION, "weights": INDEX_WEIGHTS, "rows": rows,
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED, "pairing": "independent suites"}}


def token_cost(tokens: dict, price: dict) -> float | None:
    if tokens.get("input") is None or tokens.get("output") is None or not all(k in price for k in ("input", "output")):
        return None
    cached, write = tokens.get("cached_input") or 0, tokens.get("cache_write") or 0
    return ((tokens["input"] - cached - write) * price["input"]
            + cached * price.get("cached_input", price["input"])
            + write * price.get("cache_write", price["input"])
            + tokens["output"] * price["output"]) / 1_000_000


def _timing(records: list[dict]) -> dict:
    """Summarize retained calls; a collection span includes pauses and overlapping jobs."""
    timed, intervals = [], []
    for record in records:
        seconds = record.get("meta", {}).get("seconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and seconds >= 0:
            timed.append((seconds, record))
        collected = record.get("collected", {})
        try:
            start, end = (datetime.fromisoformat(collected[k]) for k in ("started_at", "finished_at"))
        except (KeyError, TypeError, ValueError):
            continue
        if start.utcoffset() is not None and end.utcoffset() is not None and end >= start:
            intervals.append((start, end))
    seconds = [s for s, _ in timed]
    slowest = None
    if timed:
        _, record = max(timed, key=lambda pair: pair[0])
        if "judge" in record:
            slowest = f"{record['judge']}: {record.get('target', '?')}"
        else:
            task = record.get("item") if record.get("track") == "understanding" else "/".join(
                record.get(k, "?") for k in ("tier", "animal"))
            slowest = f"{record.get('model', '?')}: {record.get('track', '?')}/{task} · r{record.get('rep', 1)}"
    return {"tasks": len(records), "failures": sum("error" in r for r in records),
            "timed_tasks": len(timed), "total_seconds": sum(seconds) if seconds else None,
            "median_seconds": median(seconds) if seconds else None,
            "max_seconds": max(seconds) if seconds else None, "slowest_task": slowest,
            "timestamp_tasks": len(intervals),
            "wall_seconds": (max(end for _, end in intervals) - min(start for start, _ in intervals)).total_seconds()
                            if intervals else None}


def _resources(records: list[dict], price: dict) -> dict:
    tokens = [r.get("meta", {}).get("tokens") or {} for r in records]
    costs = [token_cost(t, price) for t in tokens]
    totals = {k: sum(t[k] for t in tokens if t.get(k) is not None)
              if any(t.get(k) is not None for t in tokens) else None
              for k in ("input", "output", "reasoning", "cached_input", "cache_write")}
    return {**_timing(records), "token_tasks": sum(any(v is not None for v in t.values()) for t in tokens),
            "token_totals": totals,
            "token_counts": {k: sum(t.get(k) is not None for t in tokens) for k in totals},
            "mean_input_tokens": mean(t.get("input") for t in tokens),
            "mean_output_tokens": mean(t.get("output") for t in tokens),
            "mean_reasoning_tokens": mean(t.get("reasoning") for t in tokens),
            "cost_tasks": sum(c is not None for c in costs), "mean_cost_usd": mean(costs),
            "estimated_cost_usd": sum(costs) if costs and all(c is not None for c in costs) else None,
            "known_cost_usd": sum(c for c in costs if c is not None) if any(c is not None for c in costs) else None,
            "reported_cost_usd": sum(r["meta"]["cost_usd_reported"] for r in records
                                     if r.get("meta", {}).get("cost_usd_reported") is not None)
                                 if any(r.get("meta", {}).get("cost_usd_reported") is not None for r in records) else None,
            "price": price or None}


def efficiency(records: list[dict], judgments: list[dict], bench, models) -> dict:
    """Retained-task telemetry, including failed tasks; missing usage is never zero."""
    panel = {i.id for i in bench.items if i.modality == "vision"} if bench else set()
    expected = bench.expected_prompts() if bench else None
    understanding, images, whole, judge_totals = {}, {}, {}, {}
    for model in sorted({r["model"] for r in records if "model" in r}):
        rr = [r for r in records if r.get("model") == model]
        price = models[model].options.get("price", {}) if model in models else {}
        text = [r for r in rr if r.get("track") == "understanding"]
        visual = [r for r in text if r.get("item") in panel and is_current(r, expected)
                  and r.get("suite", "core") == bench.suite] if bench else []
        understanding[model] = _resources(visual, price)
        reps = {r.get("rep", 1) for r in visual}
        if {r["item"] for r in visual} != panel or any(
                {r.get("rep", 1) for r in visual if r["item"] == item} != reps for item in panel):
            understanding[model]["estimated_cost_usd"] = None
        generated = [r for r in rr if r.get("track") == "imagegen"]
        images[model] = {**_timing(generated), "images": sum(len(r.get("images", [])) for r in generated)}
        whole[model] = {"total": _timing(rr), "understanding": _resources(text, price), "imagegen": images[model]}
    for model in sorted({r["judge"] for r in judgments if "judge" in r}):
        price = models[model].options.get("price", {}) if model in models else {}
        judge_totals[model] = _resources([r for r in judgments if r.get("judge") == model], price)
    timing = {"overall": _timing(records + judgments),
              "tracks": {track: _timing([r for r in records if r.get("track") == track])
                         for track in ("understanding", "imagegen")}}
    timing["tracks"]["judgments"] = _timing(judgments)
    return {"suite": bench.suite if bench else "core", "visual_understanding": understanding, "timing": timing,
            "imagegen": images, "whole_run": whole, "judges": judge_totals}

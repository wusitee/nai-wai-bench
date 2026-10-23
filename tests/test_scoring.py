import json
from dataclasses import replace

import pytest

from nwb import report
from nwb.config import find_root, load_bench
from nwb.scoring import aggregate, grounding_score, image_scores, understanding_score
from nwb.util import write_json

WEIGHTS = {"pose": 2.0, "render": 1.0}


def test_understanding_score_penalizes_hallucinations_and_floors_at_zero():
    assert understanding_score({"scores": {"a": 2, "b": 1}, "hallucinations": []}) == 75
    assert understanding_score({"scores": {"a": 2, "b": 1}, "hallucinations": ["x"]}) == 65
    assert understanding_score({"scores": {"a": 0, "b": 0}, "hallucinations": ["x"]}) == 0


def test_image_scores_weight_traits_and_scale_by_identity():
    style, overall = image_scores({"traits": {"pose": 2, "render": 0}, "identity": 1}, WEIGHTS)
    assert style == pytest.approx(100 * 4 / 6)
    assert overall == pytest.approx(style / 2)


def _judgment(run, judge, vendor, target, current=True, **fields):
    mtime = (run / target).stat().st_mtime if current else 0.0
    write_json(run / "judgments" / judge / target,
               {"judge": judge, "judge_vendor": vendor, "target": target, "target_mtime": mtime, **fields})


def test_aggregate_prefers_independent_current_judges_and_skips_contaminated(tmp_path):
    run = tmp_path
    base = {"track": "understanding", "vendor": "openai", "modality": "text", "lang": "zh", "rep": 1}
    write_json(run / "understanding/gpt/q__r1.json", {**base, "model": "gpt", "item": "q", "answer": "A"})
    write_json(run / "understanding/gpt/web__r1.json",
               {**base, "model": "gpt", "item": "web", "answer": "B", "contaminated": True})
    target = "understanding/gpt/q__r1.json"
    _judgment(run, "self", "openai", target, scores={"a": 2}, hallucinations=[], rationale="")
    _judgment(run, "other", "anthropic", target, scores={"a": 1}, hallucinations=[], rationale="")
    # Made for an older version of the sample, so it must not count.
    _judgment(run, "stale", "google", target, current=False, scores={"a": 0}, hallucinations=[], rationale="")

    write_json(run / "imagegen/img/name_zh/cat__r1.json",
               {"track": "imagegen", "model": "img", "vendor": "openai", "tier": "name_zh", "animal": "cat",
                "rep": 1, "prompt": "p", "images": ["x.png"], "meta": {"audit": {"verbatim": False}}})
    img_target = "imagegen/img/name_zh/cat__r1.json"
    for judge, vendor in (("j1", "anthropic"), ("j2", "google")):
        _judgment(run, judge, vendor, img_target, traits={"pose": 2, "render": 2}, identity=2,
                  failure_modes=["generic_cute"] if judge == "j1" else [], rationale="")

    scores = aggregate(run, WEIGHTS)
    und = scores["understanding"]["gpt"]
    assert und["text"] == 50  # only the independent judge counts
    assert und["overall"] is None  # text-only answers cannot receive a visual rank
    assert und["contaminated"] == 1 and "web" not in und["items"]
    img = scores["imagegen"]["img"]
    assert img["overall"] == 100 and img["not_verbatim"] == 1
    assert img["failure_modes"] == {"generic_cute": 1}  # flagged by half of the judges
    assert aggregate(run, WEIGHTS, judges={"self"})["understanding"]["gpt"]["text"] == 100
    # Only samples made with the bench's current prompt count: the image matches, the answers don't.
    current = aggregate(run, WEIGHTS, expected={"imagegen/name_zh/cat": "p", "understanding/q": "changed"})
    assert current["understanding"] == {} and current["imagegen"]["img"]["n"] == 1
    health = scores["judge_health"]
    assert health["self"]["understanding"]["deviation"] == 50  # self-vendor judge still evaluated
    assert health["j1"]["imagegen"] == {"n": 1, "spread": 0.0, "deviation": 0.0}


def test_grounding_is_answer_keyed_and_blind_controls_do_not_change_visual_scores(tmp_path):
    bench = load_bench(find_root())
    key = {"pose": "facepalm", "eyes": "open"}
    assert grounding_score('```json\n{"pose":"facepalm","eyes":"open"}\n```', key) == 100
    assert grounding_score('{"pose":"folded_arms","eyes":"open"}', key) == 50
    assert grounding_score('No image attached.', key) == 0
    assert grounding_score('{"pose":true,"eyes":"unknown"}', key) == 0

    for item in [i for i in bench.items if i.answers]:
        answer = '{"pose":"unknown","eyes":"unknown"}' if item.control_for else json.dumps(item.answers)
        write_json(tmp_path / "understanding/m" / f"{item.id}__r1.json", {
            "track": "understanding", "model": "m", "vendor": "v", "item": item.id,
            "modality": item.modality, "lang": item.lang, "rep": 1, "prompt": item.prompt, "answer": answer})
    scores = aggregate(tmp_path, bench.trait_weights, bench=bench)
    summary = scores["understanding"]["m"]
    assert summary["vision"] == summary["grounding"] == summary["visual_gain"] == 100
    assert summary["blind"] == 0 and summary["text"] is None
    board = scores["leaderboards"]["visual_understanding"][0]
    assert board["completed"] == 4 and board["rank"] is None  # recognition is still missing


def test_visual_ranking_ignores_text_scores_and_legacy_text_only_judgments(tmp_path):
    bench = load_bench(find_root())
    bench = replace(bench, items=[i for i in bench.items if i.id in ("recognize_zh", "knowledge_zh")])
    for model in ("visual", "verbal", "text_only"):
        for item in bench.items:
            if model == "text_only" and item.modality == "vision":
                continue
            target = f"understanding/{model}/{item.id}__r1.json"
            write_json(tmp_path / target, {
                "track": "understanding", "model": model, "vendor": "subject", "item": item.id,
                "modality": item.modality, "lang": item.lang, "rep": 1, "prompt": item.prompt, "answer": "A"})
            score = (2 if model == "visual" else 1) if item.modality == "vision" else (0 if model == "visual" else 2)
            _judgment(tmp_path, "j", "other", target, scores={c: score for c in item.checklist},
                      hallucinations=[], rationale="", judge_images=[str(p) for p in item.images])
    scores = aggregate(tmp_path, bench.trait_weights, bench=bench)
    rows = scores["leaderboards"]["visual_understanding"]
    # Text-only models never attempt the visual panel, so they are not listed as incomplete.
    assert [(r["model"], r["rank"]) for r in rows] == [("visual", 1), ("verbal", 2)]
    assert scores["understanding"]["visual"]["text"] == 0
    target = "understanding/visual/recognize_zh__r1.json"
    _judgment(tmp_path, "j", "other", target, scores={"a": 2}, hallucinations=[], rationale="")
    rows = aggregate(tmp_path, bench.trait_weights, bench=bench)["leaderboards"]["visual_understanding"]
    assert next(r for r in rows if r["model"] == "visual")["rank"] is None
    item = next(i for i in bench.items if i.modality == "vision")
    _judgment(tmp_path, "self", "subject", target, scores={c: 2 for c in item.checklist},
              hallucinations=[], rationale="", judge_images=[str(p) for p in item.images])
    rows = aggregate(tmp_path, bench.trait_weights, bench=bench)["leaderboards"]["visual_understanding"]
    assert rows[0]["model"] == "visual" and rows[0]["score"] == 100  # invalid independent judge cannot displace it


def _image_sample(run, bench, model, tier, animal, rep=1, score=2, verbatim=True):
    selected_tier = bench.all_tiers[tier]
    target = f"imagegen/{model}/{tier}/{animal}__r{rep}.json"
    write_json(run / target, {
        "track": "imagegen", "model": model, "vendor": "subject", "tier": tier, "animal": animal,
        "rep": rep, "prompt": selected_tier.render(bench.animals[animal]), "images": ["image.png"],
        "meta": {"audit": {"verbatim": verbatim}}})
    _judgment(run, "j", "independent", target, traits={t: score for t in bench.traits}, identity=2,
              failure_modes=[], rationale="")


def test_optional_states_are_scored_separately_and_never_use_the_laughing_rubric(tmp_path):
    bench = load_bench(find_root())
    for item in bench.state_items + [next(i for i in bench.items if i.id == "grounding.laugh")]:
        correct = item.state and not item.control_for
        answer = item.answers if correct else {k: "unknown" for k in item.answers}
        write_json(tmp_path / "understanding/m" / f"{item.id}__r1.json", {
            "track": "understanding", "model": "m", "vendor": "subject", "item": item.id,
            "modality": item.modality, "lang": item.lang, "rep": 1, "prompt": item.prompt,
            "answer": json.dumps(answer)})
    _image_sample(tmp_path, bench, "m", "name_zh", "cat")
    _image_sample(tmp_path, bench, "m", "state_angry_reference", "cat", score=0)
    scores = aggregate(tmp_path, bench.trait_weights, bench=bench)
    assert scores["understanding"]["m"]["vision"] == 0
    assert scores["state_understanding"]["m"]["vision"] == 100
    assert scores["state_understanding"]["m"]["blind"] == 0
    assert scores["state_understanding"]["m"]["visual_gain"] == 100
    assert scores["leaderboards"]["visual_understanding"][0]["completed"] == 1
    assert scores["leaderboards"]["visual_understanding"][0]["required"] == 13
    assert scores["imagegen"]["m"]["overall"] == 100
    assert next(s for s in scores["samples"]["imagegen"] if s["state"])["overall"] is None


def test_generation_panel_requires_coverage_balanced_repeats_and_prompt_audit(tmp_path):
    bench = load_bench(find_root())
    for model in ("full", "partial", "changed", "unverified", "refused"):
        for tier in bench.tiers:
            for animal in bench.select_animals("default"):
                if model == "partial" and animal.id != "cat":
                    continue
                if model == "refused" and (tier, animal.id) == ("name_zh", "cat"):
                    write_json(tmp_path / "imagegen/refused/name_zh/cat__r1.json", {
                        "track": "imagegen", "model": model, "vendor": "subject", "tier": tier, "animal": "cat",
                        "rep": 1, "prompt": bench.tiers[tier].render(animal), "images": [],
                        "refused": "moderation_blocked", "meta": {"audit": {"verbatim": True}}})
                    continue
                audit = {"changed": False, "unverified": None}.get(model, True)
                _image_sample(tmp_path, bench, model, tier, animal.id, verbatim=audit)
    scores = aggregate(tmp_path, bench.trait_weights, bench=bench)
    rows = {r["model"]: r for r in scores["leaderboards"]["imagegen"]}
    assert rows["full"]["rank"] == 1 and rows["full"]["score"] == 100
    assert rows["full"]["completed"] == rows["full"]["required"] == 30
    assert rows["partial"]["completed"] == 5 and rows["partial"]["rank"] is None
    assert rows["changed"]["completed"] == rows["unverified"]["completed"] == 0
    # A provider refusal of the verbatim prompt fills its cell with 0 instead of leaving the panel incomplete.
    assert rows["refused"]["rank"] == 2 and rows["refused"]["score"] == pytest.approx(100 * 29 / 30)
    assert "refused by provider" in report.render(bench, "test", scores)
    _image_sample(tmp_path, bench, "full", "name_zh", "shiba", score=0)  # outside the fixed panel
    assert aggregate(tmp_path, bench.trait_weights, bench=bench)["leaderboards"]["imagegen"][0]["score"] == 100
    _image_sample(tmp_path, bench, "full", "name_zh", "cat", rep=2, score=0)
    rows = aggregate(tmp_path, bench.trait_weights, bench=bench)["leaderboards"]["imagegen"]
    assert next(r for r in rows if r["model"] == "full")["status"] == "incomplete repetitions"
    write_json(tmp_path / "imagegen/full/name_zh/cat__r2.json", {
        "track": "imagegen", "model": "full", "tier": "name_zh", "animal": "cat", "rep": 2,
        "prompt": bench.tiers["name_zh"].render(bench.animals["cat"]), "error": "failed repeat"})
    rows = aggregate(tmp_path, bench.trait_weights, bench=bench)["leaderboards"]["imagegen"]
    assert next(r for r in rows if r["model"] == "full")["rank"] is None


def test_generation_means_balance_repeats_and_ratio_requires_matched_animals(tmp_path):
    bench = load_bench(find_root())
    for rep in (1, 2, 3):
        _image_sample(tmp_path, bench, "m", "name_zh", "cat", rep=rep)
    _image_sample(tmp_path, bench, "m", "name_zh", "giraffe", score=0)
    _image_sample(tmp_path, bench, "m", "described_detailed", "panda")
    summary = aggregate(tmp_path, bench.trait_weights, bench=bench)["imagegen"]["m"]
    assert summary["tiers"]["name_zh"]["overall"] == 50
    assert summary["overall"] == 75  # equal tiers, equal animals, then repetitions
    assert summary["knowledge_ratio"] is None
    _image_sample(tmp_path, bench, "m", "name_en", "cat", score=1)
    _image_sample(tmp_path, bench, "m", "described_detailed", "cat")
    summary = aggregate(tmp_path, bench.trait_weights, bench=bench)["imagegen"]["m"]
    assert summary["knowledge_ratio"] == .75 and summary["knowledge_animals"] == 1

import pytest

from nwb.scoring import aggregate, image_scores, understanding_score
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


def _judgment(run, judge, vendor, target, **fields):
    write_json(run / "judgments" / judge / target,
               {"judge": judge, "judge_vendor": vendor, "target": target, **fields})


def test_aggregate_prefers_independent_judges_and_skips_contaminated(tmp_path):
    run = tmp_path
    base = {"track": "understanding", "vendor": "openai", "modality": "text", "lang": "zh", "rep": 1}
    write_json(run / "understanding/gpt/q__r1.json", {**base, "model": "gpt", "item": "q", "answer": "A"})
    write_json(run / "understanding/gpt/web__r1.json",
               {**base, "model": "gpt", "item": "web", "answer": "B", "contaminated": True})
    target = "understanding/gpt/q__r1.json"
    _judgment(run, "self", "openai", target, scores={"a": 2}, hallucinations=[], rationale="")
    _judgment(run, "other", "anthropic", target, scores={"a": 1}, hallucinations=[], rationale="")

    write_json(run / "imagegen/img/name_zh/cat__r1.json",
               {"track": "imagegen", "model": "img", "vendor": "openai", "tier": "name_zh", "animal": "cat",
                "rep": 1, "prompt": "p", "images": ["x.png"], "meta": {"audit": {"verbatim": False}}})
    img_target = "imagegen/img/name_zh/cat__r1.json"
    for judge, vendor in (("j1", "anthropic"), ("j2", "google")):
        _judgment(run, judge, vendor, img_target, traits={"pose": 2, "render": 2}, identity=2,
                  failure_modes=["generic_cute"] if judge == "j1" else [], rationale="")

    scores = aggregate(run, WEIGHTS)
    und = scores["understanding"]["gpt"]
    assert und["overall"] == 50  # only the independent judge counts
    assert und["contaminated"] == 1 and "web" not in und["items"]
    img = scores["imagegen"]["img"]
    assert img["overall"] == 100 and img["not_verbatim"] == 1
    assert img["failure_modes"] == {"generic_cute": 1}  # flagged by half of the judges
    health = scores["judge_health"]
    assert health["self"]["understanding"]["deviation"] == 50  # self-vendor judge still evaluated
    assert health["j1"]["imagegen"] == {"n": 1, "spread": 0.0, "deviation": 0.0}

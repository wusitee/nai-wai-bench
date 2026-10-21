import pytest

from nwb.config import find_root, load_bench, load_models
from nwb.judge import imagegen_prompt, parse_imagegen, parse_understanding, understanding_prompt


@pytest.fixture(scope="module")
def bench():
    return load_bench(find_root())


def test_bench_data_and_models_load(bench):
    # load_bench validates checklist ids and image paths; rendering catches bad placeholders.
    assert bench.items and bench.tiers and bench.animals
    for tier in bench.tiers.values():
        for animal in bench.animals.values():
            assert animal.en in tier.render(animal) or animal.zh in tier.render(animal) or tier.reference
    assert set(bench.trait_weights) == set(bench.traits)
    models, defaults = load_models(find_root())
    assert {m.backend for m in models.values()} <= {"codex", "claude", "acp", "openai"}
    assert set(defaults["judges"]) | set(defaults["image_judges"]) <= set(models)
    assert all("vision" in models[j].can for j in defaults["image_judges"])


def test_judge_prompts_list_every_criterion(bench):
    item = next(i for i in bench.items if i.id == "write_prompt.cat")
    prompt = understanding_prompt(bench, item, "some answer")
    assert all(f"[{c}]" in prompt for c in item.checklist) and "target animal: cat" in prompt
    prompt = imagegen_prompt(bench, "画一只猫", "cat")
    assert all(f"- {t}:" in prompt for t in bench.traits)


def test_parse_understanding_accepts_fenced_json_and_validates_scores():
    reply = 'Here you go:\n```json\n{"scores": {"a": 2, "b": 0}, "hallucinations": ["x"], "rationale": "ok"}\n```'
    parsed = parse_understanding(reply, ("a", "b"))
    assert parsed["scores"] == {"a": 2, "b": 0} and parsed["hallucinations"] == ["x"]
    with pytest.raises(ValueError, match="lacks scores"):
        parse_understanding('{"scores": {"a": 2}}', ("a", "b"))
    with pytest.raises(ValueError, match="0, 1, or 2"):
        parse_understanding('{"scores": {"a": 3, "b": 1}}', ("a", "b"))
    with pytest.raises(ValueError, match="no scores"):
        parse_understanding('{"scores": null}', ("a",))
    # A fenced draft followed by the final bare verdict: the final one counts.
    reply = '```json\n{"scores": {"a": 2}}\n```\nCorrection: {"scores": {"a": 0}, "hallucinations": []}'
    assert parse_understanding(reply, ("a",))["scores"] == {"a": 0}


def test_parse_imagegen_maps_labels_and_drops_unknown_failure_modes(bench):
    traits = ", ".join(f'"{t}": "Partial"' for t in bench.traits)
    reply = ('- pose: hunched {not json}: partial\n'
             f'{{"traits": {{{traits}}}, "identity": "clearly", "failure_modes": ["generic_cute", "made_up"]}}')
    parsed = parse_imagegen(reply, bench)
    assert set(parsed["traits"].values()) == {1} and parsed["identity"] == 2
    assert parsed["failure_modes"] == ["generic_cute"]

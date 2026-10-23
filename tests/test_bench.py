import json
from types import SimpleNamespace

import pytest

from nwb.config import ModelSpec, find_root, load_bench, load_models
from nwb.judge import imagegen_prompt, judge_jobs, parse_imagegen, parse_understanding, understanding_prompt
from nwb.util import write_json


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
    assert {a.id for a in bench.select_animals("default")} == {"cat", "panda", "frog", "giraffe", "octopus", "elephant"}
    for item in [i for i in bench.items if i.control_for]:
        shown = next(i for i in bench.items if i.id == item.control_for)
        assert item.prompt == shown.prompt and item.answers == shown.answers
        assert item.modality == "text" and not item.images and shown.images


def test_judge_prompts_list_every_criterion(bench):
    item = next(i for i in bench.items if i.id == "write_prompt.cat")
    prompt = understanding_prompt(bench, item, "some answer")
    assert all(f"[{c}]" in prompt for c in item.checklist) and "target animal: cat" in prompt
    prompt = imagegen_prompt(bench, "画一只猫", "cat")
    assert all(f"- {t}:" in prompt for t in bench.traits)


def test_visual_judges_receive_stimuli_and_grounding_needs_no_judge(bench, tmp_path, monkeypatch):
    requests = []
    checklist = next(i.checklist for i in bench.items if i.id == "recognize_zh")

    def respond(request):
        requests.append(request)
        return SimpleNamespace(text=json.dumps({"scores": {c: 2 for c in checklist}}), meta={})

    backend = SimpleNamespace(run=respond)
    monkeypatch.setattr("nwb.judge.get_backend", lambda model: backend)
    for item in [i for i in bench.items if i.id in ("recognize_zh", "grounding.laugh", "grounding.laugh.blind")]:
        write_json(tmp_path / "understanding/m" / f"{item.id}__r1.json", {
            "track": "understanding", "model": "m", "item": item.id, "prompt": item.prompt, "answer": "A"})
    judges = [ModelSpec("text", "stub", "v", "", frozenset({"text"})),
              ModelSpec("vision", "stub", "v", "", frozenset({"text", "vision"}))]
    jobs = judge_jobs(bench, judges, tmp_path, {"understanding"})
    assert len(jobs) == 1 and jobs[0].base["judge"] == "vision"
    assert jobs[0].base["judge_images"] == [str(bench.reference_image)]
    # Inspect the request without making a model call.
    jobs[0].fn()
    assert requests[0].images == [bench.reference_image]


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

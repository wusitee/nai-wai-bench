from types import SimpleNamespace

import pytest

from nwb import cli, judge, report, scoring, tracks
from nwb.backends import Response
from nwb.config import ModelSpec, find_root, load_bench
from nwb.tracks import Job, is_done
from nwb.util import write_json


def test_is_done_only_for_successful_results_of_the_same_job(tmp_path):
    out = tmp_path / "r.json"
    job = Job(out=out, label="x", base={"prompt": "new"}, fn=lambda: {})
    assert not is_done(job)
    write_json(out, {"prompt": "new", "error": "boom"})
    assert not is_done(job)
    write_json(out, {"prompt": "old", "answer": "a"})  # the prompt changed since this result was made
    assert not is_done(job)
    write_json(out, {"prompt": "new", "answer": "a"})
    assert is_done(job)


@pytest.mark.parametrize("suite, item_count, state_count, image_count", [
    ("core", 25, 6, 12), ("naihub-v1", 48, 16, 32)])
def test_optional_states_forward_the_correct_reference_without_core_cost_or_llm_grading(
        tmp_path, monkeypatch, suite, item_count, state_count, image_count):
    bench = load_bench(find_root(), suite)
    assert cli._items(bench, None) == bench.items and len(bench.items) == item_count
    assert cli._tiers(bench, None) == list(bench.tiers.values()) and len(bench.tiers) == 5
    assert len(cli._items(bench, "states")) == state_count
    requests, jobs = [], []

    def generate(request):
        requests.append(request)
        request.image_out.mkdir(parents=True, exist_ok=True)
        path = request.image_out / "test.png"
        path.write_bytes(bench.reference_image.read_bytes())
        return Response(images=[path], meta={"audit": {"verbatim": True}})

    backend = SimpleNamespace(run=generate)
    monkeypatch.setattr(tracks, "get_backend", lambda _: backend)
    monkeypatch.setattr(tracks, "run_jobs", lambda selected, *args, **kwargs: (jobs.extend(selected) or len(selected), 0))
    model = ModelSpec("image", "stub", "subject", "", frozenset({"image"}))
    args = SimpleNamespace(models="image", tiers="states", animals="default", reps=1,
                           run_dir=tmp_path, jobs=1, force=False)
    assert cli.cmd_imagegen(args, bench.root, bench, {"image": model}, {}) == 0
    assert len(jobs) == image_count and {j.base["animal"] for j in jobs} == {"cat", "frog"}
    for job in jobs:
        tier = bench.state_tiers[job.base["tier"]]
        result = job.fn()
        assert requests[-1].images == ([tier.reference_image] if tier.reference else [])
        assert requests[-1].prompt == tier.render(bench.animals[job.base["animal"]])
        assert job.base["state"] == tier.state
        write_json(job.out, {**job.base, **result})
    # The reference prompt does not leak which state should be extracted from the image.
    assert len({t.render(bench.animals["cat"]) for t in bench.state_tiers.values() if t.reference}) == 1
    monkeypatch.setattr(judge, "get_backend", lambda _: backend)
    grader = ModelSpec("grader", "stub", "other", "", frozenset({"text", "vision"}))
    assert judge.judge_jobs(bench, [grader], tmp_path, {"imagegen"}) == []
    assert len(requests) == image_count
    scores = scoring.aggregate(tmp_path, bench.trait_weights, bench=bench)
    assert scores["imagegen"] == {} and scores["leaderboards"]["imagegen"] == []
    assert all(s["overall"] is None for s in scores["samples"]["imagegen"])
    html = report.render(bench, "states", scores)
    reference = next(t.id for t in bench.state_tiers.values() if t.reference)
    assert "State outputs are unscored" in html and reference in html and "test.png" in html


def test_settings_identity_tracks_collection_changes_not_display_or_credentials(tmp_path):
    from dataclasses import replace
    from nwb.config import model_settings
    patch = tmp_path / "config/agent.yml"
    patch.parent.mkdir()
    patch.write_text("tools: false")
    spec = ModelSpec("a", "acp", "v", "m", frozenset({"text"}), {
        "command": ["agent", "--patch", "${NWB_ROOT}/config/agent.yml"],
        "effort": "high", "effort_option": "reasoning_effort", "env": {"TOKEN": "secret"}})
    settings, original = model_settings(spec, tmp_path)
    assert settings["config"] == {"reasoning_effort": "high"}
    assert settings["env_keys"] == ["NWB_ROOT", "TOKEN"] and "secret" not in str(settings)
    assert settings["command"][-1] == "${NWB_ROOT}/config/agent.yml"
    assert "config/agent.yml" in settings["files"]
    cosmetic = replace(spec, options={**spec.options, "price": {"input": 12}, "label": "A", "timeout": 1,
                                     "env": {"TOKEN": "new-secret"}})
    assert model_settings(cosmetic, tmp_path)[1] == original
    for changes in ({"effort": "low"}, {"config": {"mode": "default"}}, {"command": ["other"]}):
        assert model_settings(replace(spec, options={**spec.options, **changes}), tmp_path)[1] != original
    absolute = replace(spec, options={**spec.options, "command": ["agent", "--patch", str(patch)]})
    assert model_settings(absolute, tmp_path)[1] == original
    relocated = tmp_path / "another-machine"
    (relocated / "config").mkdir(parents=True)
    (relocated / "config/agent.yml").write_bytes(patch.read_bytes())
    assert model_settings(spec, relocated)[1] == original
    assert model_settings(replace(spec, options={**spec.options, "usage_command": "/usage"}), tmp_path)[1] != original
    patch.write_text("tools: true")
    assert model_settings(spec, tmp_path)[1] != original
    api = replace(spec, backend="openai", options={"base_url": "https://user:secret@api.example/v1"})
    assert model_settings(api, tmp_path)[0]["endpoint"] == "api.example"


@pytest.mark.parametrize("change", [{"model": "another-model"}, {"options": {"effort": "low"}}])
def test_resume_rejects_changed_model_or_effort(tmp_path, change):
    from dataclasses import replace

    bench = load_bench(find_root())
    spec = ModelSpec("m", "codex", "v", "original-model", frozenset({"text"}), {"effort": "high"})
    item = next(i for i in bench.items if i.modality == "text")
    job = tracks.understanding_jobs(bench, [spec], [item], 1, tmp_path)[0]
    write_json(job.out, {**job.base, "answer": "saved answer"})
    assert is_done(job)
    changed = tracks.understanding_jobs(bench, [replace(spec, **change)], [item], 1, tmp_path)[0]
    assert not is_done(changed)


def test_collection_records_success_errors_settings_and_each_invocation(tmp_path):
    import json
    from datetime import datetime
    from nwb.util import read_json

    def fail():
        raise RuntimeError("failure")

    jobs = [Job(tmp_path / f"{name}.json", name, {"model": "m", "settings_id": "0123456789abcdef"}, fn,
                settings={"backend": "test", "effort": "high"}, run_dir=tmp_path)
            for name, fn in [("ok", lambda: {"answer": "OK"}), ("error", fail)]]
    assert tracks.run_jobs(jobs, 2, False) == (1, 1)
    for job in jobs:
        rec = read_json(job.out)
        assert rec["settings"] == job.settings
        collected = rec["collected"]
        assert collected["nwb_version"] == "0.1.0" and collected["revision"]
        assert datetime.fromisoformat(collected["finished_at"]) >= datetime.fromisoformat(collected["started_at"])
    assert tracks.run_jobs(jobs[:1], 1, False) == (0, 0)
    assert tracks.run_jobs([], 1, False, run_dir=tmp_path) == (0, 0)
    log = [json.loads(line) for line in (tmp_path / "collection.jsonl").read_text().splitlines()]
    assert len(log) == 3 and log[0]["argv"] and log[0]["settings"]["m"]["effort"] == "high"
    assert is_done(jobs[0])
    jobs[0].base["settings_id"] = "changed"
    assert not is_done(jobs[0])


@pytest.mark.parametrize("command", [cli.cmd_understand, cli.cmd_imagegen, cli.cmd_judge])
def test_cli_logs_empty_collection_invocations(tmp_path, command):
    bench = load_bench(find_root())
    model = ModelSpec("m", "acp", "v", "m", frozenset({"text", "vision", "image"}), {"command": ["unused"]})
    args = SimpleNamespace(models="m", items=None, tiers=None, animals="default", reps=0,
                           run_dir=tmp_path, jobs=1, force=False, track="all", judges="m")
    assert command(args, bench.root, bench, {"m": model}, {}) == 0
    assert len((tmp_path / "collection.jsonl").read_text().splitlines()) == 1

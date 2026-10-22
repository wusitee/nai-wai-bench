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
    monkeypatch.setattr(tracks, "run_jobs", lambda selected, *args: (jobs.extend(selected) or len(selected), 0))
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

from collections import Counter
import json
from types import SimpleNamespace
import tomllib

import pytest

from nwb import cli, config, judge, report, scoring, tracks
from nwb.config import ModelSpec, find_root, load_bench
from nwb.util import write_json


def test_naihub_panel_has_paired_controls_distinct_assets_and_provenance():
    bench = load_bench(find_root(), "naihub-v1")
    shown = cli._items(bench, "vision")
    assert len(shown) == 24 and len(bench.items) == 48
    assert Counter(i.answers["family"] for i in shown) == {
        "mutated_nailong": 20, "official_nailong": 1, "other": 3}
    assert {i.answers["subjects"] for i in shown} == {"one", "two", "four", "five"}
    assert {i.answers["mouth"] for i in shown} == {"open", "closed", "covered"}
    assert {i.answers["tears"] for i in shown} == {"present", "absent"}
    assert len({i.prompt for i in bench.items}) == 1
    assert all(i.prompt == shown[0].prompt for i in bench.state_items)
    for control in cli._items(bench, "text"):
        image_item = next(i for i in shown if i.id == control.control_for)
        assert not control.images and control.answers == image_item.answers
        assert image_item.images[0].stem.isdigit()
    data = tomllib.loads((bench.root / "bench/naihub-v1/tasks.toml").read_text())
    cases = list(data["grounding"]["cases"].values())
    annotation = json.loads((bench.root / "bench" / data["dataset"]["annotation_record"]).read_text())
    assert annotation["annotator"] == {"model": "gpt-6-astra", "reasoning_effort": "xhigh"}
    assert annotation["protocol"] == {"prompt": data["grounding"]["prompt"], "labels": data["grounding"]["labels"]}
    assert len(annotation["annotations"]) == len(cases)
    assert {a["id"]: (a["image"], a["sha256"], a["answers"]) for a in annotation["annotations"]} == {
        name: (c["image"], c["sha256"], c["answers"]) for name, c in data["grounding"]["cases"].items()}
    assert len({c["sha256"] for c in cases}) == 24
    assert all(c.get("source_url") or c.get("source_document") for c in cases)
    answers_by_image = {c["image"]: c["answers"] for c in cases}
    assert all(c["answers"] == answers_by_image[c["image"]]
               for c in data["state_transfer"]["cases"].values())
    assert {p for p in (bench.root / "bench/naihub-v1/images").iterdir()} == {i.images[0] for i in shown}
    assert len(load_bench(bench.root).items) == 25  # the default panel is unchanged


@pytest.mark.parametrize("change, message", [("hash", "checksum mismatch"), ("label", "declared labels")])
def test_naihub_rejects_changed_assets_or_invalid_answer_labels(monkeypatch, change, message):
    load = config._load

    def altered(path):
        data = load(path)
        if path.parent.name == "naihub-v1":
            case = next(iter(data["grounding"]["cases"].values()))
            if change == "hash":
                case["sha256"] = "0" * 64
            else:
                case["answers"]["family"] = "undeclared_label"
        return data

    monkeypatch.setattr(config, "_load", altered)
    with pytest.raises(ValueError, match=message):
        load_bench(find_root(), "naihub-v1")


def test_naihub_joint_and_macro_scores_expose_constant_label_baseline(tmp_path, monkeypatch):
    bench = load_bench(find_root(), "naihub-v1")
    shown = cli._items(bench, "vision")
    modal = {f: Counter(i.answers[f] for i in shown).most_common(1)[0][0] for f in shown[0].answers}
    items = {i.id: i for i in bench.items}
    monkeypatch.setattr(tracks, "get_backend", lambda _: SimpleNamespace())
    models = [ModelSpec(name, "codex", "test", "test", frozenset({"text", "vision"}))
              for name in ("oracle", "constant")]
    jobs = tracks.understanding_jobs(bench, models, bench.items, 1, tmp_path)
    for job in jobs:
        item = items[job.base["item"]]
        answer = ({k: "unknown" for k in item.answers} if item.control_for
                  else item.answers if job.base["model"] == "oracle" else modal)
        write_json(job.out, {**job.base, "answer": json.dumps(answer)})
    # An otherwise prompt-matching record from another suite must not fill this panel.
    write_json(tmp_path / "understanding/wrong_suite/answer.json",
               {**jobs[0].base, "model": "wrong_suite", "suite": "core", "answer": json.dumps(shown[0].answers)})
    scores = scoring.aggregate(tmp_path, bench.trait_weights, bench=bench)
    rows = {r["model"]: r for r in scores["leaderboards"]["visual_understanding"]}
    assert rows["oracle"]["score"] == 100
    assert rows["constant"]["score"] == 0
    assert "wrong_suite" not in rows and "wrong_suite" not in scores["understanding"]
    constant = scores["understanding"]["constant"]
    assert constant["vision"] == pytest.approx(100 * 108 / 168)
    assert constant["fields"]["family"] == pytest.approx(100 * 20 / 24)
    assert constant["family_macro"] == pytest.approx(100 / 3)
    assert constant["field_items"] == {f: 24 for f in modal}
    assert constant["blind"] == 0 and constant["visual_gain"] == constant["vision"]
    assert judge.judge_jobs(bench, [models[0]], tmp_path, {"understanding"}) == []
    html = report.render(bench, "fixture", scores)
    assert "Suite: naihub-v1" in html and "all-field joint accuracy" in html
    assert "Family macro" in html and "tears (items)" in html and "negative_control" in html
    core = scoring.aggregate(tmp_path, bench.trait_weights, bench=load_bench(bench.root))
    assert core["samples"]["understanding"] == []
    # Joint diagnostics average complete per-repetition answers, not thresholded mean fields.
    write_json(tmp_path / "understanding/oracle/extra__r2.json", {
        **jobs[0].base, "model": "oracle", "rep": 2,
        "answer": json.dumps({f: "unknown" for f in modal})})
    repeated = scoring.aggregate(tmp_path, bench.trait_weights, bench=bench)
    assert repeated["understanding"]["oracle"]["joint"] == pytest.approx(100 * 23.5 / 24)
    assert repeated["understanding"]["oracle"]["visual_joint"] == pytest.approx(100 * 23.5 / 24)
    rows = repeated["leaderboards"]["visual_understanding"]
    assert next(r for r in rows if r["model"] == "oracle")["status"] == "incomplete repetitions"


def test_cli_rejects_cross_suite_run_before_model_requests(tmp_path, capsys, monkeypatch):
    def no_backend(_):
        pytest.fail("cross-suite runs must be rejected before constructing model jobs")

    monkeypatch.setattr(tracks, "get_backend", no_backend)
    write_json(tmp_path / "understanding/legacy/answer.json", {"suite": "core"})
    assert cli.main(["understand", "--suite", "naihub-v1", "--run", str(tmp_path),
                     "--models", "gpt-6.1-sol"]) == 2
    assert "contains another suite" in capsys.readouterr().err

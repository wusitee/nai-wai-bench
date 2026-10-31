import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from nwb import __version__, bundle, cli, release, results, scoring
from nwb.backends import BackendError, Response
from nwb.config import find_root, load_bench
from nwb.judge import understanding_prompt
from nwb.util import read_json, write_json


@pytest.fixture
def inputs(tmp_path):
    source = find_root()
    (tmp_path / "bench").symlink_to(source / "bench", target_is_directory=True)
    shutil.copyfile(source / "models.toml", tmp_path / "models.toml")
    suites = {}
    for suite in ("core", "naihub-v1"):
        bench = load_bench(tmp_path, suite)
        item = next(i for i in bench.items if i.modality == "vision")
        run = tmp_path / "runs" / suite
        target = f"understanding/gpt-6.1-sol/{item.id}__r1.json"
        answer = json.dumps(item.answers) if item.answers else str(Path.home() / "answer")
        rec = {"track": "understanding", "suite": suite, "model": "gpt-6.1-sol", "vendor": "test",
               "item": item.id, "modality": "vision", "lang": item.lang, "rep": 1,
               "prompt": item.prompt, "answer": answer}
        write_json(run / target, rec)
        if suite == "core":
            for judge, score in [("opus-5.5", 2), ("gpt-6.1-sol", 0)]:
                write_json(run / "judgments" / judge / target, {
                    "judge": judge, "judge_vendor": "other", "target": target,
                    "target_mtime": (run / target).stat().st_mtime,
                    "judge_prompt": hashlib.sha256(understanding_prompt(bench, item, answer).encode()).hexdigest()[:16],
                    "judge_images": [str(p) for p in item.images], "scores": {c: score for c in item.checklist},
                    "hallucinations": [], "rationale": ""})
        suites[suite] = {"run": suite, "sha256": bundle.input_digest(run, bench),
                         "judges": ["opus-5.5"] if suite == "core" else []}
    manifest = tmp_path / "release.toml"

    def save():
        lines = [f'nwb_version = "{__version__}"']
        for suite, spec in suites.items():
            lines += [f"[suites.{suite}]", *(f"{k} = {json.dumps(v)}" for k, v in spec.items())]
        manifest.write_text("\n".join(lines))

    save()
    return tmp_path, manifest, suites, save


def test_release_builds_both_suites_offline_and_bundles_keep_their_pinned_identity(inputs, monkeypatch):
    root, manifest, suites, _ = inputs
    out = root / "site"
    monkeypatch.setattr(cli, "find_root", lambda: root)
    monkeypatch.setattr("nwb.site.shutil.which", lambda _: None)

    def no_backend(*args, **kwargs):
        pytest.fail("release building must not construct a model backend")

    monkeypatch.setattr("nwb.backends.get_backend", no_backend)
    assert cli.main(["release", "--manifest", str(manifest), "--out", str(out)]) == 0
    assert read_json(out / "scores.json")["understanding"]["gpt-6.1-sol"]["vision"] == 100
    assert read_json(out / "release.json")["manifest"]["suites"] == suites
    assert (out / ".nojekyll").exists()
    for suite, spec in suites.items():
        page = out / ("" if suite == "core" else suite)
        assert (page / "index.html").exists()
        scores = read_json(page / "scores.json")
        assert scores["judges"] == spec["judges"]
        assert bundle.input_digest(root / "runs" / suite, load_bench(root, suite)) == spec["sha256"]
        assert not (root / "runs" / suite / "scores.json").exists()
        archive = next((out / "bundles").glob(f"*-{suite}-{suite}.zip"))
        download = ("" if suite == "core" else "../") + f"bundles/{archive.name}"
        assert download in (page / "index.html").read_text()
        restored = root / "restored" / suite
        with zipfile.ZipFile(archive) as saved:
            saved.extractall(restored)
            if suite == "core":
                assert "--judges opus-5.5" in saved.read("BUNDLE-README.md").decode()
        bench = load_bench(root, suite)
        assert bundle.input_digest(restored, bench) == spec["sha256"]
        rescored = scoring.aggregate(restored, bench.trait_weights, set(spec["judges"]), bench=bench)
        assert rescored["understanding"] == scores["understanding"]
        assert rescored["stale_judgments"]["total"] == 0


@pytest.mark.parametrize("problem, message", [
    ("changed", "raw inputs changed"), ("missing", "restore its raw results bundle"),
    ("mixed", "contains another suite"), ("stale", "stale judgments"),
])
def test_release_rejects_inconsistent_inputs_before_writing_output(inputs, problem, message):
    root, manifest, suites, save = inputs
    run = root / "runs/core"
    path = next((run / "understanding").rglob("*.json"))
    if problem == "missing":
        shutil.rmtree(run)
    elif problem == "stale":
        judgment = next((run / "judgments/opus-5.5").rglob("*.json"))
        write_json(judgment, {**read_json(judgment), "judge_prompt": "outdated rubric"})
        suites["core"]["sha256"] = bundle.input_digest(run, load_bench(root))
        save()
    else:
        rec = read_json(path)
        rec["answer" if problem == "changed" else "suite"] = "changed"
        write_json(path, rec)
    out = root / "site"
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        release.build(root, manifest, out)
    assert not out.exists()


def test_saved_results_survive_git_checkout_and_refresh_only_managed_files(inputs, tmp_path):
    root, _, _, _ = inputs
    bench = load_bench(root)
    run = root / "runs/core"
    image = run / "imagegen/chatgpt-image/name_zh/cat__r1/image.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(bench.reference_image.read_bytes())
    target = image.parent.with_suffix(".json")
    write_json(target, {"track": "imagegen", "model": "chatgpt-image", "vendor": "openai", "rep": 1,
                        "tier": "name_zh", "animal": "cat", "prompt": bench.tiers["name_zh"].render(bench.animals["cat"]),
                        "images": [image.relative_to(run).as_posix()], "meta": {"audit": {"verbatim": True}}})
    (run / "private.log").write_text("excluded")
    snapshot = results.sync(root, bench, run, judges={"opus-5.5"})
    meta = read_json(snapshot / results.METADATA)
    assert meta["input_sha256"] == bundle.input_digest(run, bench)
    assert not (snapshot / "private.log").exists()
    answer = next((snapshot / "understanding").rglob("*.json")).read_text()
    assert str(Path.home()) not in answer
    mtimes = {p: p.stat().st_mtime_ns for p in snapshot.rglob("*") if p.is_file()}
    results.sync(root, bench, run, judges={"opus-5.5"})
    assert all(p.stat().st_mtime_ns == mtime for p, mtime in mtimes.items())

    shutil.copyfile(find_root() / ".gitattributes", root / ".gitattributes")

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init", "-q")
    git("-c", "core.autocrlf=true", "add", ".gitattributes", "results")
    git("-c", "user.name=Benchmark Tests", "-c", "user.email=tests@example.test", "-c", "commit.gpgsign=false",
        "commit", "-qm", "Save benchmark results")
    clone = tmp_path / "checkout"
    git("clone", "-q", "-c", "core.autocrlf=true", str(root), str(clone))
    restored = results.restore(clone, "core", clone / "runs/core")
    assert bundle.input_digest(restored, bench) == meta["input_sha256"]
    assert (restored / image.relative_to(run)).read_bytes() == image.read_bytes()
    fresh = scoring.aggregate(restored, bench.trait_weights, {"opus-5.5"}, bench=bench)
    assert fresh["understanding"] == read_json(snapshot / "scores.json")["understanding"]
    with pytest.raises(ValueError, match="working run already exists"):
        results.restore(clone, "core", restored)

    (snapshot / "notes.txt").write_text("keep")
    image.unlink()
    write_json(target, {**read_json(target), "images": []})
    results.sync(root, bench, run)
    assert not (snapshot / image.relative_to(run)).exists()
    assert (snapshot / "notes.txt").read_text() == "keep"


@pytest.mark.parametrize("command", ["understand", "imagegen", "judge", "report", "failed", "no-sync"])
def test_cli_automatically_saves_benchmark_results(inputs, monkeypatch, command):
    root, _, _, _ = inputs
    bench = load_bench(root)
    monkeypatch.chdir(root)
    monkeypatch.setattr(cli, "find_root", lambda: root)
    recognize = next(i for i in bench.items if i.id == "recognize_zh")
    grounding = next(i for i in bench.items if i.id == "grounding.laugh")

    def respond(request):
        if command == "failed":
            raise BackendError("test provider failure")
        if request.image_out:
            image = request.image_out / "image.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(bench.reference_image.read_bytes())
            return Response(images=[image], meta={"audit": {"verbatim": True}})
        answer = ({"scores": {c: 2 for c in recognize.checklist}} if command == "judge" else grounding.answers)
        return Response(text=json.dumps(answer))

    from types import SimpleNamespace
    backend = SimpleNamespace(run=respond)
    monkeypatch.setattr("nwb.tracks.get_backend", lambda _: backend)
    monkeypatch.setattr("nwb.judge.get_backend", lambda _: backend)
    if command == "imagegen":
        args = ["imagegen", "--models", "chatgpt-image", "--tiers", "name_zh", "--animals", "cat"]
    elif command == "judge":
        args = ["judge", "--judges", "opus-5.5", "--track", "understanding", "--force"]
    elif command == "report":
        args = ["report", "--judges", "opus-5.5"]
    else:
        args = ["understand", "--models", "gpt-6.1-sol", "--items", "grounding.laugh"]
        if command == "no-sync":
            args.append("--no-sync")
    assert cli.main([*args, "--run", "core"]) == (1 if command == "failed" else 0)
    snapshot = root / "results/core/core"
    if command == "no-sync":
        assert not snapshot.exists()
    else:
        meta = read_json(snapshot / results.METADATA)
        assert meta["input_sha256"] == bundle.input_digest(root / "runs/core", bench)
        if command == "failed":
            failures = [read_json(p) for p in (snapshot / "understanding").rglob("*.json")]
            assert sum("error" in r for r in failures) == 2


@pytest.mark.parametrize("damage", ["content", "path"])
def test_restore_validates_saved_results_before_creating_working_files(inputs, damage):
    root, _, _, _ = inputs
    run = root / "runs/core"
    snapshot = results.sync(root, load_bench(root), run)
    if damage == "content":
        next((snapshot / "understanding").rglob("*.json")).write_text("changed")
    else:
        meta = read_json(snapshot / results.METADATA)
        meta["files"]["../outside"] = "a" * 64
        write_json(snapshot / results.METADATA, meta)
    shutil.rmtree(root / "runs")
    with pytest.raises(ValueError, match="checksum mismatch|invalid result snapshot path"):
        results.restore(root, "core", run)
    assert not run.exists()


def test_merge_combines_runs_keeping_judgments_current_and_refuses_disagreement(inputs, monkeypatch):
    root, _, _, _ = inputs
    monkeypatch.setattr(cli, "find_root", lambda: root)
    bench = load_bench(root, "core")
    base = root / "runs" / "core"
    (base / "collection.jsonl").write_text('{"argv": ["base"]}\n')
    added = root / "runs" / "added"
    record = read_json(next((base / "understanding" / "gpt-6.1-sol").glob("*.json")))
    write_json(added / "understanding" / "opus-5.5" / f"{record['item']}__r1.json", {**record, "model": "opus-5.5"})
    (added / "collection.jsonl").write_text('{"argv": ["added"]}\n')

    assert cli.main(["merge", "--run", "merged", "--from", "core,added", "--no-sync"]) == 0
    merged = root / "runs" / "merged"
    scores = scoring.aggregate(merged, bench.trait_weights, bench=bench)
    assert set(scores["understanding"]) == {"gpt-6.1-sol", "opus-5.5"}
    assert scores["understanding"]["gpt-6.1-sol"]["vision"] == 50
    assert scores["stale_judgments"]["total"] == 0
    assert (merged / "collection.jsonl").read_text() == '{"argv": ["base"]}\n{"argv": ["added"]}\n'

    write_json(added / "understanding" / "gpt-6.1-sol" / f"{record['item']}__r1.json", {**record, "answer": "changed"})
    assert cli.main(["merge", "--run", "conflict", "--from", "core,added", "--no-sync"]) == 2
    assert not (root / "runs" / "conflict").exists()


def test_release_restores_selected_runs_from_repository_results(inputs, monkeypatch):
    root, manifest, suites, _ = inputs
    for suite, spec in suites.items():
        results.sync(root, load_bench(root, suite), root / "runs" / spec["run"], judges=set(spec["judges"]))
    shutil.rmtree(root / "runs")
    monkeypatch.chdir(root)
    assert cli.main(["report", "--run", "core", "--judges", "opus-5.5", "--no-sync"]) == 0
    monkeypatch.setattr("nwb.site.shutil.which", lambda _: None)
    release.build(root, manifest, root / "site")
    for suite, spec in suites.items():
        assert bundle.input_digest(root / "runs" / spec["run"], load_bench(root, suite)) == spec["sha256"]


def test_no_op_judging_keeps_pinned_results_unchanged(inputs, monkeypatch):
    root, _, suites, _ = inputs
    bench = load_bench(root, "naihub-v1")
    run = root / "runs/naihub-v1"
    snapshot = results.sync(root, bench, run, judges=set())
    before = {p: p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    monkeypatch.chdir(root)
    assert cli.main(["judge", "--suite", "naihub-v1", "--run", "naihub-v1"]) == 0
    assert not (run / "collection.jsonl").exists()
    assert bundle.input_digest(run, bench) == suites["naihub-v1"]["sha256"]
    assert all(p.read_bytes() == data for p, data in before.items())


def test_resume_settings_conflict_preserves_cache_and_snapshot_before_requests(inputs, monkeypatch):
    root, _, _, _ = inputs
    run = root / "runs/core"
    path = next((run / "understanding").rglob("*.json"))
    write_json(path, {**read_json(path), "settings_id": "historical-settings"})
    snapshot = results.sync(root, load_bench(root), run)
    before = path.read_bytes()
    saved = {p: p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    monkeypatch.chdir(root)

    def no_request(*args):
        pytest.fail("settings conflicts must stop the whole batch before model requests")

    from types import SimpleNamespace
    monkeypatch.setattr("nwb.tracks.get_backend", lambda _: SimpleNamespace(run=no_request))
    assert cli.main(["understand", "--run", "core", "--models", "gpt-6.1-sol",
                     "--items", "recognize_zh,grounding.laugh"]) == 2
    assert path.read_bytes() == before and not (run / "collection.jsonl").exists()
    assert all(p.read_bytes() == data for p, data in saved.items())

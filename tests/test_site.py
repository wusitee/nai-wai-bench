from html.parser import HTMLParser
import json
from pathlib import Path

import pytest

from nwb import CANARY, cli, report, scoring, site
from nwb.config import find_root, load_bench, load_models
from nwb.provenance import c2pa_summary
from nwb.util import write_json


def test_c2pa_summary_reads_declarations_and_ignores_missing_or_truncated_text(tmp_path):
    image = tmp_path / "image.png"
    generator = b'\x64name\x67ChatGPT\x67version\x69gpt-image'
    action = b'\x6bdescription\x78\x20Created by Google Generative AI.'
    image.write_bytes(b'PNG c2pa' + generator * 2 + action * 2)
    assert c2pa_summary(image) == {
        "generators": ["ChatGPT gpt-image"], "actions": ["Created by Google Generative AI."]}
    image.write_bytes(b'PNG c2pa\x64name\x67ChatGPT\x67version\x69short')
    assert c2pa_summary(image) == {"generators": ["ChatGPT"], "actions": []}
    image.write_bytes(b'PNG no credentials')
    assert c2pa_summary(image) is None


@pytest.mark.parametrize("resize, suite", [(False, "core"), (True, "core"), (False, "naihub-v1")])
def test_site_builds_portable_assets_and_shows_recorded_provenance(tmp_path, monkeypatch, resize, suite):
    bench = load_bench(find_root(), suite)
    models, _ = load_models(bench.root)
    model = models["chatgpt-image"]
    run = tmp_path / "run"
    image = run / "imagegen" / model.name / "name_zh" / "cat__r1.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(bench.reference_image.read_bytes())
    relative = image.relative_to(run).as_posix()
    record = {
        "track": "imagegen", "model": model.name, "vendor": model.vendor,
        "suite": suite,
        "tier": "name_zh", "animal": "cat", "rep": 1, "prompt": bench.tiers["name_zh"].render(bench.animals["cat"]),
        "images": [relative], "meta": {"client": "codex-cli test", "model": "recorded-model",
        "c2pa": {"generators": ["ChatGPT gpt-image"], "actions": []}, "audit": {"verbatim": False}},
    }
    write_json(image.with_suffix(".json"), record)
    item = bench.items[0]
    answer = '<unsafe> & ' + 'Full answer. ' * 40
    write_json(run / "understanding" / model.name / "answer__r1.json", {
        "track": "understanding", "model": model.name, "vendor": model.vendor, "item": item.id,
        "suite": suite,
        "modality": item.modality, "lang": item.lang, "rep": 1, "prompt": item.prompt,
        "answer": answer,
    })
    if suite == "naihub-v1":
        # A text-only model answers only the no-image control of an image nobody saw; its card and reply
        # must still be shown.
        text_model, unseen = models["deepseek-v4-pro"], bench.items[2]
        write_json(run / "understanding" / text_model.name / "blind__r1.json", {
            "track": "understanding", "model": text_model.name, "vendor": text_model.vendor,
            "item": f"{unseen.id}.blind", "suite": suite, "modality": "text", "lang": unseen.lang, "rep": 1,
            "prompt": unseen.prompt, "answer": json.dumps({**unseen.answers, "note": "blind-only reply"})})
    state_item = bench.state_items[0]
    write_json(run / "understanding" / model.name / "states.angry__r1.json", {
        "track": "understanding", "model": model.name, "vendor": model.vendor, "item": state_item.id,
        "suite": suite,
        "modality": "vision", "lang": "en", "rep": 1, "prompt": state_item.prompt,
        "answer": json.dumps(state_item.answers)})
    state_tier = next(t for t in bench.state_tiers.values() if t.reference)
    write_json(run / "imagegen" / model.name / state_tier.id / "cat__r1.json", {
        **record, "tier": state_tier.id, "prompt": state_tier.render(bench.animals["cat"])})
    scores = scoring.aggregate(run, bench.trait_weights, bench=bench)
    out = tmp_path / "site"
    out.mkdir()
    unrelated = out / "keep.txt"
    unrelated.write_text("keep")
    monkeypatch.setattr(site.shutil, "which", lambda _: "magick" if resize else None)
    if resize:
        run_command = site.subprocess.run

        def convert(command, **kwargs):
            if command[0] != "magick":
                return run_command(command, **kwargs)
            assert kwargs == {"check": True}
            Path(command[-1]).write_bytes(Path(command[1]).read_bytes())
        monkeypatch.setattr(site.subprocess, "run", convert)
    index = site.build(bench, models, run, scores, out, repo_url="https://example.com/repo", suite_tabs=True, bundle_url="https://example.com/results.zip")
    html = index.read_text()
    assert CANARY in html and "nai-wai-bench 0.1.0" in html
    assert "https://example.com/results.zip" in html and "Download raw results" in html
    assert "Efficiency" in html and "Stale judgments ignored" not in html  # shown only when some were ignored
    assert "0.1.0 首个版本 · First release" in html and "Release 0.1.0 results:" in html
    assert "models whose intervals largely overlap are not clearly ordered" in html
    assert model.label in html and "codex-cli test" in html and "recorded-model" in html
    assert "ChatGPT gpt-image" in html and "Prompt changed" in html
    assert answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') in html
    assert unrelated.read_text() == "keep"
    assert "Image generation ranking" in html and "Visual understanding ranking" in html
    assert "incomplete" in html and "0/30" in html
    assert "Optional state transfer · unscored" in html and f"Source: {state_item.state}" in html
    assert "Optional state extraction · answer-keyed" in html
    if suite == "naihub-v1":
        # Answer-keyed images appear as casebook cards; the annotator is flagged; tabs follow the published layout.
        assert "all seven fields" in html and "Family macro" in html and f"id='case-{item.id.split('.')[1]}'" in html
        ranking = html.split("<table class=ranking>", 1)[1].split("</table>", 1)[0]
        assert "评审 Judges:" not in ranking
        assert "Answer keys are GPT-6-Astra annotations not yet checked by a person" in html
        assert "Key annotator" in html and "href='../'" in html and "blind-only reply" in html
        assert f"id='case-{unseen.id.split('.')[1]}'" in html
    else:
        assert "Answer-key diagnostics" not in html and "href='naihub-v1/'" in html
    local_report = report.render(bench, "test", scores)
    assert "Image generation ranking" in local_report and "Visual understanding ranking" in local_report
    assert "incomplete" in local_report and "&lt;unsafe&gt;" in local_report
    assert "Optional state extraction · answer-keyed" in local_report and "State outputs are unscored" in local_report
    if suite == "core":
        assert "Answer-key diagnostics" not in local_report

    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "img":
                assert (out / attrs["src"]).is_file()
    Assets().feed(html)
    suffix = ".jpg" if resize else ".png"
    assert (out / f"images/{model.name}/name_zh/cat__r1{suffix}").is_file()


def test_export_is_deterministic_sanitized_and_rescorable(tmp_path, capsys):
    import hashlib
    import zipfile
    from types import SimpleNamespace
    from nwb.judge import understanding_prompt

    bench = load_bench(find_root())
    models, _ = load_models(bench.root)
    run = tmp_path / "release-run"
    item = next(i for i in bench.items if i.id == "recognize_zh")
    target = "understanding/m/answer.json"
    answer = "A " + str(Path.home() / "private")
    write_json(run / target, {"track": "understanding", "model": "m", "vendor": "v", "item": item.id,
                            "modality": "vision", "lang": "zh", "rep": 1, "prompt": item.prompt,
                            "answer": answer, "meta": {"path": str(Path.home() / "private")}})
    write_json(run / "judgments/j/answer.json", {
        "judge": "j", "judge_vendor": "other", "target": target,
        "target_mtime": (run / target).stat().st_mtime,
        "judge_prompt": hashlib.sha256(understanding_prompt(bench, item, answer).encode()).hexdigest()[:16],
        "judge_images": [str(p) for p in item.images], "scores": {c: 2 for c in item.checklist},
        "hallucinations": [], "rationale": ""})
    stale = json.loads((run / "judgments/j/answer.json").read_text())
    write_json(run / "judgments/stale/answer.json", {**stale, "judge": "stale", "target_sha256": "old-content"})
    write_json(run / "judgments/old_prompt/answer.json", {**stale, "judge": "old_prompt", "judge_prompt": "old-rubric"})
    image = run / "imagegen/m/reference/image.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image bytes")
    (run / "report.html").write_text("excluded")
    (run / "secrets.log").write_text("excluded")
    (run / "collection.jsonl").write_text(json.dumps({"path": str(Path.home() / "private")}) + "\n")
    args = SimpleNamespace(run_dir=run, out=str(tmp_path / "bundles"))
    assert cli.cmd_export(args, bench.root, bench, models, {}) == 0
    archive = next((tmp_path / "bundles").glob("*.zip"))
    original = archive.read_bytes()
    assert cli.cmd_export(args, bench.root, bench, models, {}) == 0
    assert archive.read_bytes() == original
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == sorted(bundle.namelist())
        assert set(bundle.namelist()) == {target, "judgments/j/answer.json", "judgments/stale/answer.json",
                                         "judgments/old_prompt/answer.json", "imagegen/m/reference/image.png",
                                         "scores.json", "collection.jsonl", "BUNDLE-README.md"}
        assert CANARY in bundle.read("BUNDLE-README.md").decode()
        assert str(Path.home()) not in bundle.read(target).decode()
        assert json.loads(bundle.read(target))["meta"]["path"] == "~/private"
        assert json.loads(bundle.read("collection.jsonl"))["path"] == "~/private"
        restored = tmp_path / "restored"
        bundle.extractall(restored)
    rescored = scoring.aggregate(restored, bench.trait_weights, bench=bench)
    assert rescored["stale_judgments"] == {"total": 2, "reasons": {"target changed": 1, "judge prompt changed": 1}}
    assert rescored["understanding"]["m"]["vision"] == 100
    assert cli.build_parser().parse_args(["site", "--bundle-url", "https://example.com/b.zip"]).bundle_url
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--version"])
    assert stopped.value.code == 0 and "nwb 0.1.0" in capsys.readouterr().out


def test_ranking_discloses_intervals_conditions_and_display_judges():
    row = {"model": "m", "rank": 1, "score": 87.5, "score_interval": [70.8, 100], "rank_range": [1, 5],
           "status": "complete", "settings_status": "settings unrecorded", "completed": 24, "required": 24,
           "repetitions": 1, "judges": {"judge-id": 17}}
    html = site._ranking([row], lambda m: "Model (high)", {}, lambda j: "Judge Label")
    assert "87.5 [70.8–100.0]" in html and ">1–5</td>" in html
    assert "class=interval style='left:70.800%;width:29.200%'" in html
    assert "Model<span class=muted> (high)</span>" in html
    assert "评审 Judges: Judge Label ×17" in html and "judge-id" not in html
    assert "<span class=status>settings unrecorded</span>" in html
    mixed = {**row, "rank": None, "score": None, "status": "mixed conditions", "diagnostic_score": 87.5,
             "conditions": ["effort: high, low", "alternate route: <API>"]}
    html = site._ranking([mixed], lambda m: m, {}, lambda j: j)
    assert "class='status mixed'" in html and "title='effort: high, low; alternate route: &lt;API&gt;" in html

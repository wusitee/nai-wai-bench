from html.parser import HTMLParser
import json
from pathlib import Path

import pytest

from nwb import report, scoring, site
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
    index = site.build(bench, models, run, scores, out, repo_url="https://example.com/repo", suite_tabs=True)
    html = index.read_text()
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

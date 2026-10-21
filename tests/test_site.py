from html.parser import HTMLParser
from pathlib import Path

import pytest

from nwb import scoring, site
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


@pytest.mark.parametrize("resize", [False, True])
def test_site_builds_portable_assets_and_shows_recorded_provenance(tmp_path, monkeypatch, resize):
    bench = load_bench(find_root())
    models, _ = load_models(bench.root)
    model = models["chatgpt-image"]
    run = tmp_path / "run"
    image = run / "imagegen" / model.name / "name_zh" / "cat__r1.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(bench.reference_image.read_bytes())
    relative = image.relative_to(run).as_posix()
    record = {
        "track": "imagegen", "model": model.name, "vendor": model.vendor,
        "tier": "name_zh", "animal": "cat", "rep": 1, "prompt": bench.tiers["name_zh"].render(bench.animals["cat"]),
        "images": [relative], "meta": {"client": "codex-cli test", "model": "recorded-model",
        "c2pa": {"generators": ["ChatGPT gpt-image"], "actions": []}, "audit": {"verbatim": False}},
    }
    write_json(image.with_suffix(".json"), record)
    item = bench.items[0]
    answer = '<unsafe> & ' + 'Full answer. ' * 40
    write_json(run / "understanding" / model.name / "answer__r1.json", {
        "track": "understanding", "model": model.name, "vendor": model.vendor, "item": item.id,
        "modality": item.modality, "lang": item.lang, "rep": 1, "prompt": item.prompt,
        "answer": answer,
    })
    scores = scoring.aggregate(run, bench.trait_weights, expected=bench.expected_prompts())
    out = tmp_path / "site"
    out.mkdir()
    unrelated = out / "keep.txt"
    unrelated.write_text("keep")
    monkeypatch.setattr(site.shutil, "which", lambda _: "magick" if resize else None)
    if resize:
        def convert(command, check):
            assert command[:2] == ["magick", str(image)] and check
            Path(command[-1]).write_bytes(image.read_bytes())
        monkeypatch.setattr(site.subprocess, "run", convert)
    index = site.build(bench, models, run, scores, out, repo_url="https://example.com/repo")
    html = index.read_text()
    assert model.label in html and "codex-cli test" in html and "recorded-model" in html
    assert "ChatGPT gpt-image" in html and "Prompt changed" in html
    assert answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') in html
    assert unrelated.read_text() == "keep"

    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "img":
                assert (out / attrs["src"]).is_file()
    Assets().feed(html)
    suffix = ".jpg" if resize else ".png"
    assert (out / f"images/{model.name}/name_zh/cat__r1{suffix}").is_file()

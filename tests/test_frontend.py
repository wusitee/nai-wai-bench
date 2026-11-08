import json
import re
from pathlib import Path

import pytest

from nwb import frontend
from nwb.backends import Response
from nwb.config import find_root
from nwb.util import write_json

ROOT = find_root()
TIMES = [0, 200, 400, 600, 800, 1000, 1200, 1400]

SVG_STATIC = """<!doctype html><html><head></head><body>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 242" width="240" height="242">
<defs><linearGradient id="g"><stop offset="0" stop-color="gold"/><stop offset="1" stop-color="orange"/></linearGradient></defs>
<g id="character"><circle cx="120" cy="120" r="60" fill="url(#g)"/></g></svg></body></html>"""

SVG_CSS_LOOP = """<!doctype html><html><head><style>
@keyframes sway { 0%, 100% { transform: translateX(0) } 50% { transform: translateX(60px) } }
#character { animation: sway 1500ms linear infinite }</style></head><body>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 242" width="240" height="242">
<g id="character"><circle cx="60" cy="120" r="40" fill="gold"/></g></svg></body></html>"""


def svg_scripted(render_body: str, setup: str = "") -> str:
    return f"""<!doctype html><html><body>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 242" width="240" height="242">
<g id="character"><circle id="c" cx="60" cy="120" r="40" fill="gold"/></g></svg>
<script>{setup}
const c = document.getElementById('c');
window.nwb = {{ render(t) {{ {render_body} }} }};</script></body></html>"""


def three_page(character: str, render_body: str = "renderer.render(scene, cam);") -> str:
    return f"""<!doctype html><html><head></head><body><script type="module">
import * as THREE from 'three';
const renderer = new THREE.WebGLRenderer({{ preserveDrawingBuffer: true }});
renderer.setPixelRatio(1); renderer.setSize(240, 242); document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color('#eeeeee');
const cam = new THREE.PerspectiveCamera(40, 240 / 242, 0.1, 100); cam.position.set(0, 1, 5); cam.lookAt(0, 1, 0);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2));
const ch = new THREE.Group(); ch.name = 'character'; scene.add(ch);
{character}
window.nwb = {{ scene, renderer, cameras: {{ ref: cam }}, characters: [ch], render(t) {{ {render_body} }}, ready: true }};
</script></body></html>"""


ROUND_CHARACTER = """
const body = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 16), new THREE.MeshStandardMaterial({ color: 'gold' }));
body.position.y = 1; ch.add(body);
const belly = new THREE.Mesh(new THREE.SphereGeometry(0.6, 32, 16), new THREE.MeshStandardMaterial({ color: '#fff3c0' }));
belly.position.set(0, 0.8, 0.5); ch.add(belly);"""

# A textured cutout: two planes facing the camera, the brief's "flat textured plane" failure.
FLAT_CHARACTER = """
const canvas = document.createElement('canvas'); canvas.width = canvas.height = 32;
const g = canvas.getContext('2d'); g.fillStyle = 'gold'; g.fillRect(0, 0, 32, 32);
const material = new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(canvas) });
for (const x of [-0.5, 0.5]) { const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 2), material); m.position.set(x, 1, 0); ch.add(m); }"""


def test_prompts_fill_every_placeholder():
    corpus = frontend.load_corpus(ROOT)
    revision = {"page": "<html></html>", "gates": ["page errors: x"], "images": "image 1: a render."}
    for kind in frontend.KINDS:
        task = corpus.memory if frontend.is_memory(kind) else corpus.task("001")
        prompt = frontend.subject_prompt(corpus, task, kind, step1="<html></html>", revision=revision)
        assert not re.findall(r"\{[A-Z_0-9]+\}", prompt), kind
        assert f"{task.width}x{task.height}" in prompt
        if kind in frontend.REVISIONS:
            assert "- page errors: x" in prompt and "image 1: a render." in prompt
    assert len(frontend.subject_images(corpus.task("001"), "2d-s2")) == 8
    assert frontend.subject_images(corpus.memory, "3d-mem") == []


def test_revision_jobs_show_reference_render_and_views(tmp_path, monkeypatch):
    from nwb import frontend_render
    from nwb.config import ModelSpec

    corpus = frontend.load_corpus(ROOT)
    task = corpus.task("001")
    run = tmp_path / "run"
    spec = ModelSpec("subject", "claude", "anthropic", "claude-x", frozenset({"vision"}))
    monkeypatch.setattr(frontend_render, "harness_id", lambda: "h")
    stem = frontend.sample_stem(run, "subject", "001", "3d-s2", 1)
    write_json(stem.with_suffix(".json"), {"track": "frontend", "model": "subject", "task": "001", "kind": "3d-s2",
                                           "rep": 1, "html": three_page(ROUND_CHARACTER), "html_sha256": "x", "width": 240,
                                           "height": 242})
    # Without a current render of the source page, the revision waits and counts as blocked.
    assert frontend.collect_jobs(corpus, [spec], ["001"], ["3d-s3"], 1, run, stage_no=3) == ([], 1)
    frames = [{"file": f"frame_{i:02d}.png", "t": f.timestamp_ms} for i, f in enumerate(task.frames)]
    views = [{"file": f"view_{v}.png", "view": v} for v in frontend.VIEWS]
    for item in frames + views:
        (stem / item["file"]).parent.mkdir(parents=True, exist_ok=True)
        (stem / item["file"]).write_bytes(item["file"].encode())
    write_json(stem / "render.json", {"html_sha256": "x", "harness": "h", "gates": ["does not loop"],
                                      "frames": frames, "views": views})
    [job], blocked = frontend.collect_jobs(corpus, [spec], ["001"], ["3d-s3"], 1, run, stage_no=3)
    assert blocked == 0 and frontend.stage("3d-mem2") == 3
    assert [Path(p).name for p in job.base["images"]] == [Path(f.image).name for f in task.frames]
    rendered = job.base["depends_on"]["rendered"]
    assert [Path(r["file"]).name for r in rendered] == [f["file"] for f in frames] + [v["file"] for v in views]
    assert job.base["depends_on"]["gates"] == ["does not loop"]

    # The model is shown copies kept with the revision, in reference-then-render order.
    class Backend:
        def run(self, req):
            self.images = req.images
            return Response(text="```html\n<p>x</p>\n```", meta={})
    backend = Backend()
    job.fn(backend=backend)
    copies = [run / r["file"] for r in rendered]
    assert backend.images == [f.image for f in task.frames] + copies and all(p.is_file() for p in copies)

    # On resume, lost copies come back from the unchanged source render; a lost source image is a re-render.
    write_json(job.out, {**job.base, "html": "<p>x</p>"})
    copies[0].unlink()
    frontend.collect_jobs(corpus, [spec], ["001"], ["3d-s3"], 1, run, stage_no=3)
    assert copies[0].read_bytes() == b"frame_00.png"
    (stem / "view_top.png").unlink()
    assert frontend_render.render_current(json.loads(stem.with_suffix(".json").read_text()), stem) is None


def test_extract_html_uses_last_block():
    reply = "draft:\n```html\n<p>old</p>\n```\nfinal:\n```HTML\n<p>new</p>\n```\n"
    assert frontend.extract_html(reply) == "<p>new</p>"
    assert frontend.extract_html("no code here") is None


@pytest.mark.parametrize("html, kind, expected", [
    (SVG_STATIC, "2d-s1", None),
    (SVG_STATIC.replace('<circle', '<image href="data:image/png;base64,iVBORw0KGgo="/><circle'), "2d-s1",
     "raster or embedded element"),
    (SVG_STATIC.replace("</defs>", '<linearGradient id="g2" href="#g"/></defs>'), "2d-s1", None),
    # Comparisons in code are not element tags.
    (three_page(ROUND_CHARACTER, "for (let i = 0; i < track.length && i <base.length; i++) {} renderer.render(scene, cam);"),
     "3d-s1", None),
    (three_page(ROUND_CHARACTER).replace("<head>", "<head><link rel=stylesheet href=#x>"), "3d-s1",
     "raster or embedded element"),
    (SVG_STATIC.replace("<circle", '<a href="https://example.com"></a><circle'), "2d-s1", "non-fragment href"),
    (SVG_STATIC.replace('viewBox="0 0 240 242"', 'viewBox="nonsense"'), "2d-s1", "viewBox"),
    (SVG_CSS_LOOP, "2d-s1", "CSS animation or transition"),
    (SVG_STATIC.replace('viewBox="0 0 240 242"', 'viewBox="0 0 100 100"'), "2d-s1", "viewBox"),
    (three_page(ROUND_CHARACTER).replace("from 'three'", "from 'https://unpkg.com/three'"), "3d-s1",
     "imports outside the vendored three.js"),
    (three_page(ROUND_CHARACTER).replace("<head>", '<head><script type="importmap">{}</script>'), "3d-s1",
     "own import map"),
])
def test_static_gates(html, kind, expected):
    failures = frontend.static_gates(html, kind, 240, 242)
    if expected is None:
        assert failures == []
    else:
        assert any(expected in f for f in failures), failures


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return __import__("os").path.exists(p.chromium.executable_path)
    except Exception:
        return False


browser = pytest.mark.skipif(not _browser_available(), reason="needs the frontend extra and Playwright Chromium")


@browser
@pytest.mark.parametrize("html, kind, expected", [
    (SVG_CSS_LOOP, "2d-s2", None),
    (three_page(ROUND_CHARACTER, "ch.rotation.y = Math.sin(2 * Math.PI * t / 1500); renderer.render(scene, cam);"),
     "3d-s2", None),
    # Raster and network access hidden from the static gates: a script-built data: image, and fetch whose
    # evidence the page tries to erase.
    (svg_scripted("c.setAttribute('cx', 60 + t / 25);",
                  "const i = document.createElementNS('http://www.w3.org/2000/svg', 'image');"
                  "i.setAttribute('href', 'da' + 'ta:image/png;base64,iVBORw0KGgo=');"
                  "document.querySelector('svg').append(i);"),
     "2d-s2", "forbidden elements: image"),
    (svg_scripted("c.setAttribute('cx', 60 + t / 25);",
                  "window['fe' + 'tch']('https://example.com/x'); console.debug = () => {};"),
     "2d-s2", "forbidden API calls: fetch"),
    (svg_scripted("c.setAttribute('cx', 60 + t / 25);",
                  "const host = document.createElement('div'); document.body.append(host);"
                  "host.attachShadow({ mode: 'closed' }).append(document.createElement('canvas'));"
                  "document.querySelectorAll = () => [];"),
     "2d-s2", "shadow root"),
    (svg_scripted("c.setAttribute('cx', 60 + t / 25 + (t === 200 ? Math.random() * 50 : 0));"), "2d-s2",
     "non-deterministic"),
    (svg_scripted("c.setAttribute('cx', 60 + 100 * Math.sin(Math.PI * t / 1500));"), "2d-s2", "does not loop"),
    (svg_scripted(""), "2d-s2", "static animation"),
    # Invisible depth does not rescue a flat cutout.
    (three_page(FLAT_CHARACTER + """
const ghost = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 3), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0 }));
ghost.position.set(0, 1, -1.5); ch.add(ghost);
const empty = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 3), new THREE.MeshBasicMaterial());
empty.geometry.setDrawRange(0, 0); ch.add(empty);
const none = new THREE.InstancedBufferGeometry().copy(new THREE.BoxGeometry(2, 2, 3)); none.instanceCount = 0;
ch.add(new THREE.Mesh(none, new THREE.MeshBasicMaterial()));"""), "3d-s1", "is flat"),
    # 64x64 tiles uploaded into a larger texture.
    (three_page(ROUND_CHARACTER + """
const gl = renderer.getContext(), raw = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, raw);
gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA8, 128, 128);
gl.texSubImage2D(gl.TEXTURE_2D, 0, 64, 64, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(64 * 64 * 4));
renderer.resetState();"""), "3d-s1", "texture upload 128x128"),
    (three_page(ROUND_CHARACTER + """
const big = new THREE.DataTexture(new Uint8Array(128 * 128 * 4).fill(200), 128, 128); big.needsUpdate = true;
body.material = new THREE.ShaderMaterial({ uniforms: { big: { value: big } },
  vertexShader: 'varying vec2 v; void main() { v = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: 'uniform sampler2D big; varying vec2 v; void main() { gl_FragColor = texture2D(big, v); }' });"""),
     "3d-s1", "texture larger than 64x64"),
])
def test_runtime_gates(tmp_path, html, kind, expected):
    from nwb.frontend_render import render_page

    result = render_page(html, kind, 240, 242, 1500, TIMES, tmp_path)
    if expected is None:
        assert result["gates"] == []
        assert len(result["frames"]) == 8 and (tmp_path / "preview.gif").is_file()
        if kind.startswith("3d"):
            assert [v["view"] for v in result["views"]] == list(frontend.VIEWS)
    else:
        assert any(expected in g for g in result["gates"]), result["gates"]


@browser
def test_harness_views_keep_characters_inside_an_occluder(tmp_path):
    from PIL import Image
    from nwb.frontend_render import render_page

    # The characters are parented to a room box that encloses every harness camera.
    html = three_page(ROUND_CHARACTER).replace("scene.add(ch);", """
const room = new THREE.Mesh(new THREE.BoxGeometry(40, 40, 40), new THREE.MeshBasicMaterial({ color: '#553311', side: THREE.BackSide }));
scene.add(room); room.add(ch);""")
    result = render_page(html, "3d-s1", 240, 242, 1500, [0], tmp_path)
    assert result["gates"] == []
    for view in frontend.VIEWS:
        assert len(Image.open(tmp_path / f"view_{view}.png").getcolors(240 * 242)) > 50, view


def test_summary_recomputes_gates_and_drops_stale_chains(tmp_path, monkeypatch):
    from nwb import frontend_render

    corpus = frontend.load_corpus(ROOT)
    run = tmp_path / "run"
    monkeypatch.setattr(frontend_render, "harness_id", lambda: "h")

    def sample(kind, html, source=None, **extra):
        stem = frontend.sample_stem(run, "subject", "001", kind, 1)
        record = {"track": "frontend", "model": "subject", "task": "001", "kind": kind, "rep": 1, "html": html,
                  "html_sha256": kind, "width": 240, "height": 242, "static_gates": ["non-fragment href"], **extra}
        if source:
            path = frontend.sample_stem(run, "subject", "001", source, 1).with_suffix(".json")
            record["depends_on"] = {"sample": path.relative_to(run).as_posix(),
                                    "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}
        write_json(stem.with_suffix(".json"), record)
        write_json(stem / "render.json", {"html_sha256": kind, "harness": "h", "gates": []})

    # A stored gate failure from an older checker no longer counts; a runtime gate failure does.
    sample("3d-s1", SVG_STATIC)
    write_json(frontend.sample_stem(run, "subject", "001", "3d-s1", 1) / "render.json",
               {"html_sha256": "3d-s1", "harness": "h", "gates": ["window.nwb.ready never became true"]})
    # Tool use fails a sample and every sample built on it.
    sample("2d-s1", SVG_STATIC, meta={"tools_used": ["command_execution"]})
    sample("2d-s2", SVG_CSS_LOOP, "2d-s1")
    sample("2d-s3", SVG_CSS_LOOP, "2d-s2")
    gates = {s["kind"]: s["gates"] for s in frontend.summary(corpus, run)["samples"]}
    assert gates["2d-s1"] == ["used tools: command_execution"] and gates["2d-s3"] == [frontend.TAINTED]
    assert any("ready" in g for g in gates["3d-s1"])
    # Recollecting step 1 makes step 2 and its revision stale.
    sample("2d-s1", SVG_STATIC)
    assert {s["kind"] for s in frontend.summary(corpus, run)["samples"]} == {"2d-s1", "3d-s1"}


def test_published_snapshot_is_pinned_web_media_and_pages_never_embed_model_code(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image", reason="frontend sync requires the optional frontend extra")
    from nwb import frontend_render, frontend_results, frontend_site
    from nwb.config import ModelSpec

    corpus = frontend.load_corpus(ROOT)
    monkeypatch.setattr(frontend_render, "harness_id", lambda: "h")
    monkeypatch.setattr(frontend_results, "harness_id", lambda: "h")
    run = tmp_path / "runs" / "pub"
    stem = frontend.sample_stem(run, "subject", "001", "2d-s2", 1)
    write_json(stem.with_suffix(".json"), {"track": "frontend", "model": "subject", "task": "001", "kind": "2d-s2",
                                           "rep": 1, "html": SVG_CSS_LOOP, "html_sha256": "x", "width": 240,
                                           "height": 242, "settings": {"effort": "xhigh"},
                                           "meta": {"seconds": 12.0, "tokens": {"output": 345}}})
    stem.mkdir(parents=True)
    frames = []
    for i, t in enumerate(TIMES):
        Image.new("RGB", (240, 242), (40 * i % 255, 200, 90)).save(stem / f"frame_{i:02d}.png")
        frames.append({"file": f"frame_{i:02d}.png", "t": t})
    loop = [Image.new("RGB", (240, 242), color) for color in ("gold", "orange")]
    loop[0].save(stem / "preview.gif", save_all=True, append_images=loop[1:], duration=[100, 300], loop=0)
    write_json(stem / "render.json", {"html_sha256": "x", "harness": "h", "gates": [], "frames": frames,
                                      "preview": "preview.gif"})
    spec = ModelSpec("subject", "claude", "anthropic", "m", frozenset({"vision"}), {"label": "Subject"})

    snapshot, digest = frontend_results.sync(tmp_path, corpus, run, {"subject": spec})
    saved = snapshot / "frontend/subject/001/2d-s2__r1"
    render = json.loads((saved / "render.json").read_text())
    assert render["preview"] == "preview.webp" and render["frames"][0]["file"] == "frame_00.webp"
    with Image.open(saved / "preview.webp") as preview:  # per-frame GIF delays survive re-encoding
        durations = []
        for index in range(preview.n_frames):
            preview.seek(index)
            preview.load()
            durations.append(preview.info["duration"])
    assert durations == [100, 300]
    summary = json.loads((snapshot / "summary.json").read_text())
    assert summary["labels"] == {"subject": "Subject (xhigh)"} and len(summary["tasks"]["001"]["frames"]) == 8
    # A re-sync of unchanged inputs keeps the pin; a changed file breaks it.
    assert frontend_results.sync(tmp_path, corpus, run, {"subject": spec})[1] == digest
    files, loaded = frontend_results.load(tmp_path, "pub", digest)
    with pytest.raises(ValueError, match="saved results changed"):
        frontend_results.load(tmp_path, "pub", "0" * 64)

    out = tmp_path / "site"
    frontend_site.build(files, loaded, out)
    page = (out / "frontend/001/index.html").read_text()
    assert "@keyframes sway" not in page and "<iframe" not in page
    assert (out / "frontend/m/subject/001/2d-s2__r1/source.txt").read_text() == SVG_CSS_LOOP
    assert "Subject" in page and "loading=lazy" in page and "prefers-reduced-motion" in page
    assert (out / "frontend/m/subject/001/2d-s2__r1/preview.webp").is_file()


def _repin(snapshot: Path, changes: dict[str, bytes]) -> str:
    """Rewrite snapshot files with consistent checksums, as a hostile or broken sync could, and return the pin."""
    import hashlib
    from nwb import frontend_results

    meta = json.loads((snapshot / "snapshot.json").read_text())
    for name, data in changes.items():
        (snapshot / name).parent.mkdir(parents=True, exist_ok=True)
        (snapshot / name).write_bytes(data)
        meta["files"][name] = hashlib.sha256(data).hexdigest()
    (snapshot / "snapshot.json").write_text(json.dumps(meta))
    return frontend_results._digest({name: (snapshot / name).read_bytes() for name in meta["files"]})


@pytest.mark.parametrize("change, message", [
    ("task", "task '../meme-id'"),
    ("model", "labels"),
    ("image", "is not a saved image"),
])
def test_published_snapshot_rejects_unsafe_identifiers_and_unverified_files(tmp_path, change, message):
    from nwb import frontend_results

    snapshot = tmp_path / "results/frontend/pub"
    sample = "frontend/subject/001/2d-s2__r1"
    files = {"summary.json": {"run": "pub", "corpus": "frontend-v1", "harness": "h", "labels": {"subject": "S"},
                              "tasks": {"001": {"title": "t", "width": 240, "height": 242, "duration_ms": 1500,
                                                "frames": []}},
                              "samples": [{"sample": f"{sample}.json", "model": "subject", "task": "001",
                                           "kind": "2d-s2", "rep": 1, "status": "passed", "gates": []}]},
             f"{sample}.json": {"html": SVG_CSS_LOOP},
             f"{sample}/render.json": {"frames": [{"file": "frame_00.webp", "t": 0}]}}
    data = {name: json.dumps(value).encode() for name, value in files.items()}
    data[f"{sample}/frame_00.webp"] = b"webp"
    (snapshot).mkdir(parents=True)
    (snapshot / "snapshot.json").write_text(json.dumps({"format": 1, "track": "frontend", "run": "pub", "files": {}}))
    assert frontend_results.load(tmp_path, "pub", _repin(snapshot, data))[1]["labels"] == {"subject": "S"}

    summary = files["summary.json"]
    if change == "task":
        summary["tasks"]["../meme-id"] = summary["tasks"]["001"]
    elif change == "model":
        summary["labels"]["m'><svg onload=alert(1)>"] = "x"
    else:  # a reference to an image outside the checksummed files
        (snapshot / sample / "extra.webp").write_bytes(b"unlisted")
        data[f"{sample}/render.json"] = json.dumps({"frames": [{"file": "extra.webp", "t": 0}]}).encode()
    data["summary.json"] = json.dumps(summary).encode()
    with pytest.raises(ValueError, match=re.escape(message)):
        frontend_results.load(tmp_path, "pub", _repin(snapshot, data))

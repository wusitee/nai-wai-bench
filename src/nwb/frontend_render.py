"""Sandboxed rendering and runtime gates for frontend samples.

Model-generated HTML is untrusted. Each sample renders in its own subprocess running headless Chromium
(Playwright) with its OS sandbox, software WebGL (SwiftShader), and a dead proxy. The page is served from
memory at a reserved origin; every request except the page itself and, for 3D, the vendored three.js
files is aborted and fails the sample. Pages never see file:// URLs. The parent kills the subprocess
when it exceeds its time budget, which also fails the sample.
"""

import argparse
import errno
import hashlib
import io
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from nwb.util import read_json, write_json

ORIGIN = "http://nwb.invalid"
RENDER_TIMEOUT = 180  # seconds for one sample, including browser start
STEP_TIMEOUT_MS = 20_000
PREVIEW_FPS = 12
DIFF_LEVEL = 8  # a pixel differs when any channel differs by more than this
DETERMINISM_LIMIT = 0.001  # share of differing pixels allowed when the same time is rendered again
LOOP_LIMIT = 0.01  # between t = 0 and t = D
MOTION_MIN = 0.005  # some keyframe must differ from t = 0 by more than this
MIN_DEPTH_RATIO = 0.3  # character depth / width along the reference camera, to catch flat cutouts
MAX_TEXTURE = 64
VIEW_FOV = 35
VENDOR = Path(__file__).resolve().parents[2] / "bench" / "frontend-v1" / "vendor" / "three"

if os.name == "nt":
    import msvcrt

    # The renderer runs in its own process group so a console Ctrl+C does not reach it directly.
    _SUBPROCESS_OPTIONS = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

    def _lock(file) -> None:
        """Block until this process holds the lock file's first byte."""
        file.seek(0)
        while True:
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
                time.sleep(0.5)

    def _unlock(file) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

    def _kill_tree(proc: subprocess.Popen) -> None:
        """Kill the renderer and its browser processes."""
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.kill()  # in case taskkill is unavailable or failed
else:
    import fcntl

    _SUBPROCESS_OPTIONS = {"start_new_session": True}

    def _lock(file) -> None:
        fcntl.flock(file, fcntl.LOCK_EX)

    def _unlock(file) -> None:
        fcntl.flock(file, fcntl.LOCK_UN)

    def _kill_tree(proc: subprocess.Popen) -> None:
        """Kill the renderer's session, which includes its browser processes."""
        os.killpg(proc.pid, signal.SIGKILL)

# Runs before any page script, in every frame. Calls to forbidden APIs and texture uploads larger than
# the limit are reported through a console.debug captured here, so a page cannot erase the evidence.
FORBIDDEN_TAG = "__nwb_forbidden__ "
INIT_SCRIPT = """
(() => {
  const debug = console.debug.bind(console), report = name => debug('%(tag)s' + name);
  const record = (name, result) => function () { report(name); return result; };
  for (const name of ['setTimeout', 'setInterval', 'requestAnimationFrame', 'requestIdleCallback'])
    window[name] = record(name, 0);
  window.fetch = function () { report('fetch'); return new Promise(() => {}); };
  for (const name of ['XMLHttpRequest', 'WebSocket', 'EventSource', 'Worker', 'SharedWorker', 'RTCPeerConnection',
                      'Image', 'createImageBitmap'])
    window[name] = function () { report(name); throw new TypeError(name + ' is not available'); };
  if (navigator.sendBeacon) navigator.sendBeacon = record('sendBeacon', false);
  URL.createObjectURL = record('URL.createObjectURL', '');
  // Data uploads are checked against both their own size and the largest allocation the destination
  // texture ever had (any face, even a failed call), so tiling, reallocation, and pixel-unpack-buffer
  // offsets cannot build a larger image. Render targets upload no data.
  const allocated = new WeakMap(), limit = %(max)d;
  for (const proto of [window.WebGLRenderingContext?.prototype, window.WebGL2RenderingContext?.prototype]) {
    if (!proto) continue;
    const { getParameter, texImage2D, texSubImage2D, texStorage2D } = proto;
    const bound = (gl, target) => getParameter.call(gl, target === 0x0DE1 ? 0x8069 : 0x8514);
    const sized = source => [source?.width ?? source?.videoWidth, source?.height ?? source?.videoHeight];
    const allocate = (texture, w, h) => {
      if (!texture) return;
      const [aw, ah] = allocated.get(texture) || [0, 0];
      allocated.set(texture, [Math.max(aw, w || 0), Math.max(ah, h || 0)]);
    };
    const check = (gl, target, w, h, data) => {
      if (data == null) return;
      const [aw, ah] = allocated.get(bound(gl, target)) || [0, 0];
      if (Math.max(w, aw) > limit || Math.max(h, ah) > limit) report(`texture upload ${Math.max(w, aw)}x${Math.max(h, ah)}`);
    };
    proto.texImage2D = function (...a) {
      const [w, h] = a.length <= 6 ? sized(a[5]) : [a[3], a[4]], data = a.length <= 6 ? a[5] : a[8];
      if (a[1] === 0) allocate(bound(this, a[0]), w, h);
      check(this, a[0], w, h, data);
      return texImage2D.apply(this, a);
    };
    proto.texSubImage2D = function (...a) {
      const [w, h] = a.length <= 7 ? sized(a[6]) : [a[4], a[5]];
      check(this, a[0], w, h, a.length <= 7 ? a[6] : a[8]);
      return texSubImage2D.apply(this, a);
    };
    if (texStorage2D) proto.texStorage2D = function (...a) {
      allocate(bound(this, a[0]), a[3], a[4]);
      return texStorage2D.apply(this, a);
    };
  }
})();
""" % {"tag": FORBIDDEN_TAG, "max": MAX_TEXTURE}

# Elements that could show raster or external content. The live DOM is read through the DevTools protocol,
# which page scripts cannot intercept and which includes closed shadow roots; author shadow roots fail too.
FORBIDDEN_ELEMENTS = {"img", "image", "picture", "iframe", "frame", "object", "embed", "video", "audio", "source",
                      "track", "foreignobject", "link", "base", "portal"}


def dom_problems(cdp, two_d: bool) -> set[str]:
    found, stack = set(), [cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]]
    while stack:
        node = stack.pop()
        name = (node.get("localName") or "").lower()
        if node.get("nodeType") == 1 and (name in FORBIDDEN_ELEMENTS or (two_d and name == "canvas")
                                          or (name == "meta" and "http-equiv" in node.get("attributes", [])[::2])):
            found.add(name)
        shadows = node.get("shadowRoots", [])
        if any(r.get("shadowRootType") != "user-agent" for r in shadows):
            found.add("shadow root")
        stack += node.get("children", []) + shadows + ([node["contentDocument"]] if "contentDocument" in node else [])
    return found


SEEK_2D = """t => {
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = t; }
  for (const s of document.querySelectorAll('svg')) { s.pauseAnimations(); s.setCurrentTime(t / 1000); }
}"""

INSPECT_2D = """() => ({
  animations: document.getAnimations().length,
  smil: document.querySelectorAll('animate, animateTransform, animateMotion, set').length,
  scripted: typeof window.nwb?.render === 'function',
})"""

INSPECT_3D = """async ({ W, H, minRatio, maxTexture }) => {
  const THREE = await import('three');
  const n = window.nwb, problems = [];
  if (!n || typeof n !== 'object') return { problems: ['window.nwb is missing'] };
  if (!n.scene?.isScene) problems.push('nwb.scene is not a THREE.Scene');
  if (!n.renderer?.isWebGLRenderer) problems.push('nwb.renderer is not a THREE.WebGLRenderer');
  if (!n.cameras?.ref?.isCamera) problems.push('nwb.cameras.ref is not a camera');
  if (typeof n.render !== 'function') problems.push('nwb.render is not a function');
  if (!Array.isArray(n.characters) || !n.characters.length) problems.push('nwb.characters is not a non-empty array');
  if (problems.length) return { problems };
  if (!n.renderer.getContext().getContextAttributes()?.preserveDrawingBuffer)
    problems.push('renderer was created without preserveDrawingBuffer');
  const canvas = n.renderer.domElement;
  if (canvas.width !== W || canvas.height !== H) problems.push(`canvas is ${canvas.width}x${canvas.height}, not ${W}x${H}`);
  n.render(0);
  const textures = new Set(), add = v => { if (v?.isTexture) textures.add(v); };
  n.scene.traverse(o => {
    for (const m of [].concat(o.material || [])) {
      for (const k in m) add(m[k]);
      for (const u of Object.values(m.uniforms || {})) for (const v of [].concat(u?.value ?? [])) add(v);
    }
  });
  add(n.scene.background); add(n.scene.environment);
  for (const t of textures)
    for (const img of [].concat(t.image ?? [])) {
      if (!img) continue;
      if (img instanceof HTMLImageElement || img instanceof ImageBitmap || img instanceof HTMLVideoElement)
        problems.push('image texture');
      else if ((img.width || 0) > maxTexture || (img.height || 0) > maxTexture)
        problems.push(`texture larger than ${maxTexture}x${maxTexture} (${img.width}x${img.height})`);
    }
  n.scene.updateMatrixWorld(true);
  const cam = n.cameras.ref; cam.updateMatrixWorld();
  // Only geometry that can draw pixels counts: hidden, layer-excluded, or fully transparent meshes do not.
  const paints = m => m && m.visible !== false && m.colorWrite !== false && !(m.transparent && m.opacity <= 0.02);
  // Index ranges three.js draws for a mesh: material groups with a painting material (or the whole
  // geometry for a single material), clipped to the draw range. Empty when nothing is drawn.
  const drawnRanges = o => {
    const g = o.geometry;
    if (!o.isMesh || !g?.attributes?.position || !o.layers.test(cam.layers)) return [];
    if ((o.isInstancedMesh && o.count === 0) || (g.isInstancedBufferGeometry && g.instanceCount === 0)) return [];
    for (let a = o; a; a = a.parent) if (!a.visible) return [];
    const total = g.index ? g.index.count : g.attributes.position.count;
    const start = g.drawRange.start, end = Math.min(total, start + g.drawRange.count);
    const groups = Array.isArray(o.material)
      ? g.groups.filter(r => paints(o.material[r.materialIndex])).map(r => [r.start, r.start + r.count])
      : paints(o.material) ? [[0, total]] : [];
    return groups.map(([a, b]) => [Math.max(a, start), Math.min(b, end)]).filter(([a, b]) => b > a);
  };
  const characters = [], p = new THREE.Vector3();
  n.characters.forEach((c, i) => {
    if (!c?.isObject3D) { problems.push(`characters[${i}] is not an Object3D`); return; }
    const label = c.name || `characters[${i}]`, box = new THREE.Box3();
    let meshes = 0;
    c.traverse(o => {
      const ranges = drawnRanges(o);
      if (!ranges.length) return;
      meshes++;
      // Bounds of the vertices actually drawn, for every instance.
      const pos = o.geometry.attributes.position, index = o.geometry.index;
      const instances = o.isInstancedMesh ? o.count : 1, local = new THREE.Matrix4(), world = new THREE.Matrix4();
      for (let i = 0; i < instances; i++) {
        if (o.isInstancedMesh) o.getMatrixAt(i, local);
        world.multiplyMatrices(cam.matrixWorldInverse, o.matrixWorld).multiply(local);
        for (const [a, b] of ranges)
          for (let k = a; k < b; k++)
            box.expandByPoint(p.fromBufferAttribute(pos, index ? index.getX(k) : k).applyMatrix4(world));
      }
    });
    const size = box.isEmpty() ? new THREE.Vector3() : box.getSize(new THREE.Vector3());
    const ratio = size.z / Math.max(size.x, 1e-9);
    characters.push({ name: c.name, meshes, width: size.x, height: size.y, depth: size.z, ratio });
    if (!c.name) problems.push(`${label} has no name`);
    if (meshes < 2) problems.push(`${label} has fewer than two visible meshes`);
    else if (!(ratio >= minRatio)) problems.push(`${label} is flat: depth/width ${ratio.toFixed(2)} < ${minRatio}`);
  });
  return { problems, characters, textures: textures.size };
}"""

# Harness cameras orbit the characters' bounding sphere. "Front" is the reference camera's horizontal
# direction from the characters. Non-character meshes whose bounds block the line of sight to a
# character's center (walls, a room box around the camera) are hidden for that view, and the near plane
# sits just in front of the sphere.
VIEW_3D = """async ({ view, W, H, fov }) => {
  const THREE = await import('three');
  const n = window.nwb, rad = THREE.MathUtils.degToRad;
  n.render(0);
  const box = new THREE.Box3();
  for (const c of n.characters) box.expandByObject(c, true);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const ref = n.cameras.ref; ref.updateMatrixWorld();
  const up = new THREE.Vector3(0, 1, 0);
  const front = ref.getWorldPosition(new THREE.Vector3()).sub(sphere.center).setY(0);
  if (front.lengthSq() < 1e-12) front.set(0, 0, 1);
  front.normalize();
  const [yaw, elevation] = { side: [90, 10], back: [180, 10], three_quarter: [45, 20], top: [0, 80] }[view];
  const dir = front.applyAxisAngle(up, rad(yaw)).multiplyScalar(Math.cos(rad(elevation)))
    .addScaledVector(up, Math.sin(rad(elevation)));
  const half = Math.min(rad(fov) / 2, Math.atan(Math.tan(rad(fov) / 2) * W / H));
  const r = Math.max(sphere.radius, 1e-6), dist = r / Math.sin(half) * 1.05;
  const cam = new THREE.PerspectiveCamera(fov, W / H, Math.max(dist - r * 1.02, dist * 1e-3), dist + r * 100);
  cam.position.copy(sphere.center).addScaledVector(dir, dist);
  cam.lookAt(sphere.center);
  cam.updateMatrixWorld();
  const own = new Set();
  for (const c of n.characters) c.traverse(o => own.add(o));
  const targets = n.characters.map(c => new THREE.Box3().setFromObject(c, true).getCenter(new THREE.Vector3()));
  cam.layers.mask = ref.layers.mask;
  // Layers are per object, so emptying an occluder's mask hides only its own drawing, never characters
  // parented to it.
  const hidden = [], hit = new THREE.Vector3();
  n.scene.traverse(o => {
    if (!o.isMesh || !o.visible || own.has(o)) return;
    const bounds = new THREE.Box3().setFromObject(o, true);
    for (const target of targets) {
      const ray = new THREE.Ray(cam.position.clone(), target.clone().sub(cam.position).normalize());
      if (ray.intersectBox(bounds, hit) && hit.distanceTo(cam.position) < target.distanceTo(cam.position)) {
        hidden.push([o, o.layers.mask]); o.layers.mask = 0; break;
      }
    }
  });
  try {
    n.renderer.render(n.scene, cam);
  } finally {
    for (const [o, mask] of hidden) o.layers.mask = mask;
  }
  return hidden.map(([o]) => o.name || o.type);
}"""


def _image_modules():
    try:
        from PIL import Image, ImageChops
    except ImportError as exc:
        raise ValueError("frontend rendering requires the 'frontend' extra: uv sync --extra frontend") from exc
    return Image, ImageChops


def harness_id() -> str:
    """Identifies the harness code and vendored three.js; changing either re-renders every sample."""
    # Hash LF line endings so a CRLF checkout (Git's autocrlf on Windows) gets the same ID.
    digest = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))
    digest.update((VENDOR / "manifest.json").read_bytes())
    return digest.hexdigest()[:16]


def vendored_files() -> dict[str, bytes]:
    manifest = read_json(VENDOR / "manifest.json")
    files = {}
    for name, expected in manifest["files"].items():
        content = (VENDOR / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"vendored three.js file {name} does not match its manifest hash")
        files[name] = content
    return files


def diff_fraction(a: bytes, b: bytes) -> float:
    Image, ImageChops = _image_modules()
    x, y = Image.open(io.BytesIO(a)).convert("RGB"), Image.open(io.BytesIO(b)).convert("RGB")
    if x.size != y.size:
        return 1.0
    r, g, bl = ImageChops.difference(x, y).split()
    histogram = ImageChops.lighter(ImageChops.lighter(r, g), bl).histogram()
    return sum(histogram[DIFF_LEVEL + 1:]) / (x.width * x.height)


def page_document(html: str, three_d: bool, head: str = "") -> str:
    """The served page: the model's document with a margin reset and, for 3D, the import map first."""
    inject = head + "<style>html,body{margin:0;padding:0;overflow:hidden;background:#fff}</style>"
    if three_d:
        imports = {"three": "/vendor/three/build/three.module.js", "three/addons/": "/vendor/three/examples/jsm/"}
        inject = f'<script type="importmap">{json.dumps({"imports": imports})}</script>' + inject
    for tag in (r"<head\b[^>]*>", r"<html\b[^>]*>"):
        if m := re.search(tag, html, re.I):
            return html[:m.end()] + inject + html[m.end():]
    return inject + html


def render_page(html: str, kind: str, width: int, height: int, duration_ms: int, timestamps: list[int],
                out_dir: Path) -> dict:
    """Render one sample in this process and return its runtime gates and evidence."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    three_d = kind.startswith("3d")
    animated = kind.split("-")[1] in ("s2", "s3")
    times = timestamps if animated else [0]
    vendor = vendored_files() if three_d else {}
    document = page_document(html, three_d).encode()
    # The CSP blocks every image, font, frame, and connection; scripts may only be inline or vendored.
    csp = ("default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
           "script-src 'unsafe-inline' 'unsafe-eval'" + (f" {ORIGIN}/vendor/three/" if three_d else ""))
    gates, errors, blocked, forbidden, elements = [], [], [], [], set()
    timing = {"declarative": False, "scripted": False}
    evidence: dict = {"frames": [], "views": []}
    out_dir.mkdir(parents=True, exist_ok=True)

    def route(r):
        url = r.request.url
        if url == f"{ORIGIN}/index.html":
            return r.fulfill(status=200, body=document, headers={"Content-Type": "text/html; charset=utf-8",
                                                                  "Content-Security-Policy": csp})
        name = url.removeprefix(f"{ORIGIN}/vendor/three/")
        if three_d and url.startswith(f"{ORIGIN}/vendor/three/") and name in vendor and name.endswith(".js"):
            return r.fulfill(status=200, body=vendor[name], content_type="text/javascript")
        blocked.append(url[:200])
        return r.abort()

    def console(m):
        if m.text.startswith(FORBIDDEN_TAG):
            forbidden.append(m.text.removeprefix(FORBIDDEN_TAG)[:100])
        elif m.type == "error":
            errors.append(f"console.error: {m.text}"[:500])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, chromium_sandbox=True, proxy={"server": "http://127.0.0.1:9"},
                                    # Main-thread animation keeps paused, seeked frames exact.
                                    args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-threaded-animation",
                                          "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
        context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                      service_workers="block", accept_downloads=False)
        context.route("**/*", route)
        context.route_web_socket("**/*", lambda ws: (blocked.append(ws.url[:200]), ws.close()))
        context.add_init_script(INIT_SCRIPT)
        page = context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)
        page.on("pageerror", lambda e: errors.append(f"uncaught: {e}"[:500]))
        page.on("console", console)
        cdp = context.new_cdp_session(page)

        def inspect() -> None:
            """Checks repeated after every render, since a page can change itself while rendering."""
            elements.update(dom_problems(cdp, not three_d))
            if not three_d:
                info = page.evaluate(INSPECT_2D)
                timing["declarative"] |= bool(info["animations"] or info["smil"])
                timing["scripted"] |= info["scripted"]

        def shot() -> bytes:
            try:
                return page.screenshot(type="png", animations="allow", caret="initial")
            except PlaywrightError as e:
                # Chromium on Windows occasionally fails the first capture after load; capturing has no
                # side effects on the paused page, so one retry cannot change the result.
                if "Unable to capture screenshot" not in str(e):
                    raise
                return page.screenshot(type="png", animations="allow", caret="initial")

        def render_at(t: int) -> bytes:
            draw(t)
            inspect()
            return shot()

        try:
            page.goto(f"{ORIGIN}/index.html", wait_until="load")
            inspect()
            if three_d:
                # Poll from Python: Playwright's own page-side polling would use the disabled timers.
                deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000
                while not page.evaluate("() => window.nwb?.ready === true"):
                    if time.monotonic() > deadline:
                        gates.append("window.nwb.ready never became true")
                        break
                    time.sleep(0.05)
                if not gates:
                    info = page.evaluate(INSPECT_3D, {"W": width, "H": height, "minRatio": MIN_DEPTH_RATIO,
                                                      "maxTexture": MAX_TEXTURE})
                    gates += info.pop("problems")
                    evidence["scene"] = info
                draw = (lambda t: page.evaluate("t => window.nwb.render(t)", t)) if not gates else None
                evidence["mode"] = "render(t)"
            elif not animated:
                draw = lambda t: None  # noqa: E731
                evidence["mode"] = "static"
            elif timing["declarative"] == timing["scripted"]:
                draw = None  # both or neither; reported below
            elif timing["declarative"]:
                draw = lambda t: page.evaluate(SEEK_2D, t)  # noqa: E731
                evidence["mode"] = "declarative"
            else:
                draw = lambda t: page.evaluate("t => window.nwb.render(t)", t)  # noqa: E731
                evidence["mode"] = "render(t)"
            if draw is not None:
                render_at(times[0])  # warm-up: the first seek after load can reach the compositor one frame late
                shots = []
                for i, t in enumerate(times):
                    shots.append(render_at(t))
                    (out_dir / f"frame_{i:02d}.png").write_bytes(shots[-1])
                    evidence["frames"].append({"file": f"frame_{i:02d}.png", "t": t})
                if three_d:
                    for view in ("side", "back", "three_quarter", "top"):
                        hidden = page.evaluate(VIEW_3D, {"view": view, "W": width, "H": height, "fov": VIEW_FOV})
                        inspect()
                        (out_dir / f"view_{view}.png").write_bytes(shot())
                        evidence["views"].append({"file": f"view_{view}.png", "view": view, "t": 0,
                                                  "hidden": hidden[:50]})
                # Every time again, in a fixed shuffled order, so state carried between calls shows up.
                order = list(range(len(times)))
                random.Random(len(times)).shuffle(order)
                repeat = {times[i]: diff_fraction(shots[i], render_at(times[i])) for i in order}
                checks = {"determinism_diff": max(repeat.values())}
                if animated:
                    loop = {t: diff_fraction(shots[i], render_at(t + duration_ms)) for i, t in enumerate(times)}
                    checks["loop_diff"] = max(loop.values())
                    checks["motion_diff"] = max(diff_fraction(shots[0], s) for s in shots[1:])
                    step = 1000 / PREVIEW_FPS
                    previews = [render_at(round(k * step)) for k in range(int(duration_ms // step) or 1)]
                    _save_gif(previews, out_dir / "preview.gif", round(step))
                    evidence["preview"] = "preview.gif"
                evidence["checks"] = checks
                if checks["determinism_diff"] > DETERMINISM_LIMIT:
                    t = max(repeat, key=repeat.get)
                    gates.append(f"non-deterministic: rendering t={t} again changed {repeat[t]:.1%} of pixels")
                if animated and checks["loop_diff"] > LOOP_LIMIT:
                    t = max(loop, key=loop.get)
                    gates.append(f"does not loop: t={t} and t={t + duration_ms} differ in {loop[t]:.1%} of pixels")
                if animated and checks["motion_diff"] <= MOTION_MIN:
                    gates.append("static animation: no keyframe differs from t=0")
            else:
                (out_dir / "failed.png").write_bytes(shot())
                evidence["failed_screenshot"] = "failed.png"
        except PlaywrightError as e:
            gates.append(f"render failed: {str(e).splitlines()[0][:300]}")
        finally:
            context.close()
            browser.close()
    if not three_d:
        if not animated and (timing["declarative"] or timing["scripted"]):
            gates.append("animation in a static task")
        elif animated and timing["declarative"] and timing["scripted"]:
            gates.append("uses both declarative animation and window.nwb.render")
        elif animated and not timing["declarative"] and not timing["scripted"]:
            gates.append("no animation: neither declarative animation nor window.nwb.render")
    if elements:
        gates.append(f"forbidden elements: {', '.join(sorted(elements))}")
    if forbidden:
        gates.append(f"forbidden API calls: {', '.join(sorted(set(forbidden)))}")
    if blocked:
        gates.append(f"network requests: {', '.join(blocked[:5])}")
    if errors:
        gates.append(f"page errors: {errors[0]}")
    return {"gates": gates, "errors": errors[:20], "blocked": blocked[:20], "forbidden": sorted(set(forbidden)),
            "elements": sorted(elements), "timing": timing, **evidence}


def _save_gif(frames: list[bytes], path: Path, duration: int) -> None:
    Image, _ = _image_modules()
    images = [Image.open(io.BytesIO(f)).convert("RGB") for f in frames]
    images[0].save(path, save_all=True, append_images=images[1:], duration=duration, loop=0)


def render_current(record: dict, render_dir: Path) -> dict | None:
    """The render of exactly this sample with the current harness, or None."""
    path = render_dir / "render.json"
    if not path.is_file():
        return None
    render = read_json(path)
    if render.get("html_sha256") != record.get("html_sha256") or render.get("harness") != harness_id():
        return None
    # An interrupted re-render can leave render.json behind without the images it lists.
    files = [e["file"] for e in render.get("frames", []) + render.get("views", [])]
    files += [render[k] for k in ("preview", "failed_screenshot") if render.get(k)]
    if not all((render_dir / f).is_file() for f in files):
        return None
    return render


def render_sample(record: dict, timestamps: list[int], render_dir: Path) -> dict:
    """Render in a killable subprocess and write render.json."""
    started = time.monotonic()
    base = {"html_sha256": record.get("html_sha256"), "harness": harness_id(), "kind": record["kind"]}
    if record.get("html") is None:
        result = {"gates": ["no html to render"]}
    else:
        render_dir.mkdir(parents=True, exist_ok=True)
        for old in [*render_dir.glob("*.png"), *render_dir.glob("*.gif")]:
            old.unlink()
        job = render_dir / "job.json"
        write_json(job, {"html": record["html"], "kind": record["kind"], "width": record["width"],
                         "height": record["height"], "duration_ms": record["duration_ms"], "timestamps": timestamps})
        # UTF-8 both ways, so gates quoting page content survive non-UTF-8 locale code pages.
        proc = subprocess.Popen([sys.executable, "-m", "nwb.frontend_render", str(job)],
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", errors="replace", **_SUBPROCESS_OPTIONS)
        try:
            stdout, stderr = proc.communicate(timeout=RENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            result = {"gates": [f"render timed out after {RENDER_TIMEOUT}s"]}
        else:
            if proc.returncode == 0:
                result = json.loads(stdout.strip().splitlines()[-1])
            else:
                raise RuntimeError(f"renderer exited {proc.returncode}: {stderr.strip()[-800:]}")
        job.unlink(missing_ok=True)
    (render_dir / "page.html").parent.mkdir(parents=True, exist_ok=True)
    if record.get("html") is not None:
        (render_dir / "page.html").write_text(record["html"], encoding="utf-8")
    render = {**base, **result, "seconds": round(time.monotonic() - started, 1)}
    write_json(render_dir / "render.json", render)
    return render


def render_all(corpus, run_dir: Path, force: bool = False, only: set[Path] | None = None) -> tuple[int, int]:
    """Render samples without a current render (all, or those in `only`). Renders are serialized across
    processes by a lock in the run directory, and each sample is checked again under the lock."""
    from nwb.frontend import is_animated, samples

    todo = [(p, r) for p, r in samples(run_dir) if (only is None or p in only)
            and (force or render_current(r, p.with_suffix("")) is None)]
    print(f"rendering {len(todo)} samples", file=sys.stderr)
    failed = 0
    lock_path = run_dir / "frontend" / ".render.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        for n, (path, record) in enumerate(todo, 1):
            _lock(lock)
            try:
                if not force and render_current(record, path.with_suffix("")) is not None:
                    status = "rendered by another process"
                else:
                    task = corpus.task(record["task"])
                    timestamps = [f.timestamp_ms for f in task.frames] if is_animated(record["kind"]) else [0]
                    try:
                        render = render_sample(record, timestamps, path.with_suffix(""))
                        status = "ok" if not render["gates"] else "GATES " + "; ".join(render["gates"])[:300]
                    except (RuntimeError, ValueError, OSError) as e:
                        failed += 1
                        status = f"ERROR {e}"[:300]
            finally:
                _unlock(lock)
            print(f"[{n}/{len(todo)}] render {path.relative_to(run_dir).with_suffix('')} {status}", file=sys.stderr)
    return len(todo) - failed, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render one frontend sample job (internal).")
    parser.add_argument("job", type=Path)
    args = parser.parse_args(argv)
    job = read_json(args.job)
    result = render_page(job["html"], job["kind"], job["width"], job["height"], job["duration_ms"],
                         job["timestamps"], args.job.parent)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

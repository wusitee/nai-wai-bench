# Experimental frontend track

Models rebuild animated 奶蛙 GIFs as hand-written web pages: inline SVG (2D) or three.js scenes (3D).
`bench/frontend-v1/` holds the reference corpus, checklists, prompts, and a vendored three.js. The track
is outside the NaiWai Index, and the corpus and its checklists await human review. Samples are checked
by scripted gates; likeness is reviewed by people in a local gallery (`nwb frontend report`), and there
is no automatic quality score or ranking. Site integration is not implemented.

## Corpus

The [task manifest](../bench/frontend-v1/tasks.toml) contains nine panel GIFs and one unranked showcase.
Task `001` is the first 2D and 3D pilot. Each GIF has eight timestamped keyframes with neutral filenames,
six yes/no questions per frame, and separate side, back, three-quarter, and top checklists.

| Task | Upstream asset | Viewport | Duration (s) | Eligibility / difficulty | Reference GIF |
|---|---|---|---:|---|---|
| 001 | naiwa_0001 | 240 × 242 | 1.5 | panel / easy | [Two characters at a school desk, one rubbing the other's belly](../bench/frontend-v1/assets/001/reference.gif) |
| 002 | naiwa_0002 | 240 × 240 | 5.99 | panel / medium | [Character crossing a sunlit living room in a thinking pose, then saluting](../bench/frontend-v1/assets/002/reference.gif) |
| 003 | naiwa_0019 | 304 × 300 | 0.74 | panel / easy | [Front-facing character standing still and jiggling](../bench/frontend-v1/assets/003/reference.gif) |
| 004 | naiwa_0045 | 244 × 240 | 1.2 | panel / easy | [Front-facing character pumping both fists](../bench/frontend-v1/assets/004/reference.gif) |
| 005 | naiwa_0012 | 240 × 240 | 3.67 | panel / easy | [Close-up character swaying with shy smiles](../bench/frontend-v1/assets/005/reference.gif) |
| 006 | naiwa_0034 | 240 × 246 | 3.2 | panel / medium | [Green character rubbing the belly of a pink character lying on a bed](../bench/frontend-v1/assets/006/reference.gif) |
| 007 | naiwa_0026 | 240 × 294 | 5.54 | panel / medium | [Full-body character dancing and turning sideways](../bench/frontend-v1/assets/007/reference.gif) |
| 008 | naiwa_0048 | 216 × 216 | 1.22 | panel / medium | [Full-body character laughing and bouncing between a crouch and standing](../bench/frontend-v1/assets/008/reference.gif) |
| 009 | naiwa_0096 | 240 × 240 | 4.39 | panel / medium | [Character in a tank top holding in laughter, then laughing](../bench/frontend-v1/assets/009/reference.gif) |
| 010 | naiwa_0017 | 300 × 300 | 5 | showcase / showcase | [Laughing characters falling through the sky over mountains](../bench/frontend-v1/assets/010/reference.gif) |

The panel has one or two main characters per GIF, fixed or simple camera motion, and durations at most
six seconds. Task `002` has a drifting camera and an exit/re-entry; its nearly empty frames assess the
room rather than an occluded pose. Task `003` deliberately has subtle motion. The crowd and moving
camera in task `010` are exceptions reserved for showcase use.

## Provenance and timing

The captured [source index](../bench/frontend-v1/source-index.json) comes from
[Nai-hub's animated collection](https://nai-hub.com/data/naiwa/animated.json). Each task records its
upstream title, immutable 40-character Git revision, jsDelivr URL, byte SHA-256, dimensions, GIF frame
count, total duration, and camera/selection notes. The original GIF bytes are unchanged. Neutral asset
paths are `assets/<task>/reference.gif` and `assets/<task>/frame_00.png` through `frame_07.png`.
The benchmark canary GUID is retained in the manifest.

GIF delays are preserved, including variable delays. Eight targets span the first through final
source frame starts. Each target selects the nearest distinct source frame while reserving enough
frames for later samples; ties prefer the earlier frame. Keyframe records contain the selected source
index, its actual cumulative start time in integer milliseconds, and the PNG hash. The last keyframe
occurs before the loop duration; it is not an extra copy at the loop boundary.

Pillow 13.0.0 decodes the GIF's composited full-resolution RGBA frames, respecting disposal, and writes
PNG files with compression level 9 and optimization disabled. No crop, resize, synthesis, or retiming
is applied. Metadata and filenames are provenance, not extra model input.

## Checklist interpretation

Checklists were drafted by Claude Opus 5.5 from timestamped contact sheets and have **not** been
human-validated. GPT-6.1-Sol performed visual spot checks and tooling QA. Every question describes an observable property expected to receive **yes** for a
faithful reconstruction. The questions are review prompts shown in the gallery, not subject
prompts.

Novel-view questions are structural priors: bodies should have volume, facial features belong on the
front, and visible pale belly patches belong on the front. A single source view does not establish
hidden geometry. These questions do not claim reference-truth side/back images or require invented
hidden markings. Novel views apply to the static scene or animation at t=0, so their questions avoid later motion states.
The view names denote the harness cameras described under [Rendering and gates](#rendering-and-gates).

Review points include task `005`'s partially closed eyes, task `007`'s initial eye state, and task
`009`'s small eye/brow details. Task `006` intentionally avoids the hidden pink character's face and
an unreadable hand. Some showcase questions describe absence while still expecting yes.

## Local preparation and validation

Install the optional data dependency and validate the committed corpus without model calls:

```sh
uv sync --extra data
uv run --extra data python scripts/prepare_frontend.py --check bench/frontend-v1/tasks.toml
uv run --extra data pytest tests/test_frontend_data.py
```

Validation checks the captured index hash and pinned URL membership, GIF hashes and decoded metadata,
canonical sample selection, neutral PNG paths, PNG hashes and composited pixels, and checklist structure.
It uses only local files. It does not certify the visual truth of checklist wording.

Restore keyframe PNGs from the vendored GIFs:

```sh
uv run --extra data python scripts/prepare_frontend.py --prepare bench/frontend-v1/tasks.toml
```

All generated PNG hashes must match the frozen manifest before any file is written. A different
encoder or dependency version cannot silently replace the corpus. To draft metadata for another
local GIF, direct scratch output to the ignored working directory:

```sh
uv run --extra data python scripts/prepare_frontend.py --sample /path/to/reference.gif \
  --output-dir .scratch/frontend-candidate
```

Changing reference bytes, sampling, or checklist meanings changes the experimental evaluation inputs;
freeze reviewed inputs before collecting comparisons. The core and Nai-hub suite commands do not load
this corpus; it has its own `nwb frontend` command.

## Task kinds

| Kind | Input | Output |
|---|---|---|
| `2d-s1` | `frame_00` | Static inline SVG |
| `2d-s2` | The same model's `2d-s1` page and all eight keyframes with timestamps | Animated SVG |
| `3d-s1` | `frame_00` | Static three.js scene |
| `3d-s2` | The same model's `3d-s1` page and all eight keyframes with timestamps | Animated three.js scene |
| `2d-mem`, `3d-mem` | No image: "draw 大笑奶龙 from memory" | Static SVG or three.js scene |
| `2d-s3`, `3d-s3` | Revision of the same model's step 2 page: the page, its gate results, the eight keyframes, its render at the same times, and for 3D the four harness views | Revised animated page |
| `2d-mem2`, `3d-mem2` | Revision of the same model's memory page: the page, its gate results, its render, and for 3D the four harness views | Revised static page |

Each later kind builds on the sample of the same model and rep, even when that sample failed its gates:
step 2 on step 1, and each revision kind on the page it revises. The record stores the source sample
path, hash, and static gate result under `depends_on`. Recollecting a sample makes every sample built on
it, directly or through another sample, stale: they are ignored by rendering, reports, and later
collection stages until collected again.

The revision kinds give a model one check-and-revise round. The prompt embeds the source task's prompt,
the page, and its static and runtime gate results; the attachments are the reference keyframes (GIF tasks
only), the harness's rendered frames, and for 3D the harness views. A page that failed before rendering
contributes the harness's failure screenshot, if any. The model is shown copies of the rendered images,
kept in `<kind>__r<rep>.inputs/` beside the revision sample, so later re-renders of the source cannot change
the record of what it saw; `depends_on` also records the render's harness ID, gate results, and the copies'
paths and hashes, and a revision whose copies are missing or changed is stale. The model replies with a
complete page, which is gated like its source kind.
Memory kinds are independent of the GIF tasks (task id `mem`, 240 × 240); their review checklist is
`[memory]` in the task manifest, which follows the image-generation traits in `bench/rubric.toml`.

[Prompts](../bench/frontend-v1/prompts.toml) state every contract. A reply must contain an
` ```html ` block; the last one counts. Shared rules: offline, a W × H viewport at device pixel ratio 1,
no raster images (`<img>`, `<image>`, `url()` other than `url(#id)`, `data:` URIs, base64), no external
resources or network APIs, no timers or animation frames, at most 256 KB, and no uncaught exceptions or
console errors. Breaking any rule fails the sample's gates.

- **2D:** one inline `<svg viewBox="0 0 W H">`, one named `<g>` per character with nested named
  parts; no `<foreignObject>`, `<canvas>`, or nested `<svg>`. Step 1 and memory pages, including their
  revisions, are static (no script, SMIL, CSS animations, or transitions). Step 2 and its revision use
  exactly one timing method: declarative
  animation (CSS, SMIL, or Web Animations), which the harness pauses and seeks, or
  `window.nwb = { render(t) }`. The loop period is the GIF duration D, and t = 0 is `frame_00`.
- **3D:** a module script importing only `three` and the vendored addons through the harness import
  map; geometry built in code; procedural `CanvasTexture`/`DataTexture` up to 64 × 64; a renderer with
  `preserveDrawingBuffer`. The page sets
  `window.nwb = { scene, renderer, cameras: { ref }, characters, render(t), ready: true }`.
  `characters` lists the named character groups the harness cameras are fitted to (an addition to the
  original contract, so that walls and floors do not dominate the fit). `render(t)` renders
  synchronously with `cameras.ref` and must be deterministic.

The vendored [three.js r187](../bench/frontend-v1/vendor/three/manifest.json) contains unmodified files
from the npm tarball; the manifest records the tarball integrity and per-file hashes, which the
renderer verifies.

## Rendering and gates

Model HTML is untrusted. `nwb.frontend_render` renders each sample in its own subprocess with
Playwright's headless Chromium, using its OS sandbox, SwiftShader WebGL, main-thread animation (so
seeking is exact), and a dead proxy. The page is served from memory at `http://nwb.invalid/` with a
Content Security Policy that allows only inline scripts and styles (and, for 3D, the vendored three.js
files), so images, fonts, frames, and connections are refused; every request other than the
page and the vendored files is also aborted. Pages never see `file://` URLs. A sample that exceeds 180
seconds is killed.

Static gates read the source and are recomputed whenever samples are loaded, so gate fixes apply to
earlier samples. A sample whose subject used or requested a tool (`tools_used` or tool permission requests
in its metadata) fails, as does every sample built on it. Static gates check the HTML block, size,
forbidden elements and URLs, the 2D `<svg>` and `viewBox`, static-only rules for step 1 and memory pages
and their revisions, and 3D import specifiers. APIs that comments
may mention (`fetch`, timers) are checked at runtime instead. Runtime gates fail a sample on:

- requests or WebSockets, CSP violations, page errors, and `console.error`;
- calls to timers, `fetch`, `XMLHttpRequest`, workers, `Image`, and similar APIs, and WebGL texture
  data uploads into a texture that was ever allocated larger than 64 × 64 (including tiled and
  pixel-unpack-buffer uploads);
  these are replaced or wrapped before page scripts run and report through a console channel the page
  cannot clear;
- forbidden elements in the live DOM after any render (`img`, `image`, `iframe`, `object`, `video`,
  `foreignObject`, `link`, ..., and `canvas` in 2D), including elements created by script, and any
  author shadow root. The DOM is read through the DevTools protocol, which page scripts cannot
  intercept;
- 2D: animation in a static page, both or neither timing method in an animated page, rechecked after every
  render;
- 3D: `nwb.ready` not true within 20 seconds, a malformed `window.nwb`, a canvas that is not W × H,
  image textures or textures larger than 64 × 64 (material properties and shader uniforms), and
  characters that are unnamed, have fewer than two drawn meshes, or are flat (depth/width below 0.3
  along the reference camera). Hidden, layer-excluded, fully transparent, and empty-draw-range meshes,
  meshes with no instances, and material groups that paint nothing do not count, and bounds use the
  drawn vertices of every instance. Vertex-shader displacement is
  not modeled; the novel-view checklists also ask about visible depth;
- determinism: rendering every keyframe time again, in a shuffled order after other renders, changes
  more than 0.1% of pixels;
- animated kinds (step 2 and its revision): no keyframe differs from t = 0 by more than 0.5% of pixels, or any keyframe time t and
  t + D differ by more than 1%. A motion whose period divides D also passes; reviewers compare
  keyframes.

The renderer writes `frame_NN.png` at each keyframe time (only `frame_00` for static kinds), a 12 fps
`preview.gif` for the animated kinds, and, for 3D, `view_side`, `view_back`, `view_three_quarter`, and `view_top`
at t = 0. Harness cameras orbit the characters' bounding sphere; "front" is the reference camera's
horizontal direction. For each view, non-character meshes whose bounds block the line of sight to a
character's center (walls, a room box) stop drawing for that view (characters parented to them still
draw), and the near plane sits just in front of the sphere; `render.json` lists the hidden meshes. `render.json` records gates and evidence, and a render whose listed images are missing counts as not rendered; changing the
renderer or vendored files re-renders every sample.

## Review

Quality is judged by people. Automatic LLM checklist judging was tried in the pilot and removed: with or
without a stronger judge, rough drawings that had the right scene layout received full marks, because
the questions test the presence of parts rather than likeness.

`nwb frontend report` writes `summary.json` with each sample's gate status and a `gallery.html` for
review. The gallery shows the reference GIF and keyframes, and for each sample the rendered loop beside
the reference GIF, every rendered keyframe beside its reference keyframe with that frame's checklist,
the 3D harness views, generation time and output tokens, and the page source as text. It never runs
model code.

## Running the track

```sh
uv sync --extra frontend
uv run --extra frontend playwright install chromium
uv run --extra frontend nwb frontend collect --run pilot --models gpt-6.1-sol --tasks 001
uv run --extra frontend nwb frontend render --run pilot
uv run --extra frontend nwb frontend report --run pilot
```

`collect` defaults to all tasks and all kinds with one rep. It runs in three stages: step 1 and memory
samples, then step 2, then the revision kinds, after rendering the selected revisions' source samples.
Renders are serialized across processes by a lock in the run directory. A sample that cannot be collected
because its source sample or source render is missing counts as a failure.
Subject calls may take up to 30 minutes. Samples are `runs/<run>/frontend/<model>/<task>/<kind>__r<rep>.json`,
and renders are in the directory with the same stem. `report` writes `runs/<run>/frontend/summary.json`
and `gallery.html`. Every stage resumes and skips finished work; `--force` redoes it.

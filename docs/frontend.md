# Experimental frontend track

Models rebuild animated 奶蛙 GIFs as hand-written web pages: inline SVG (2D) or three.js scenes (3D).
`bench/frontend-v1/` holds the reference corpus, checklists, prompts, and a vendored three.js. The track
is outside the NaiWai Index, and the corpus and its checklists await human review. The 3D component is
unranked until calibrated. Results are local (`nwb frontend report` writes a gallery); site
integration is not implemented.

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
faithful reconstruction. A judge should eventually see only the rendered frame and its questions;
the reference image must be withheld. The manifest's questions are evaluator metadata, not subject
prompts.

Novel-view questions are structural priors: bodies should have volume, facial features belong on the
front, and visible pale belly patches belong on the front. A single source view does not establish
hidden geometry. These questions do not claim reference-truth side/back images or require invented
hidden markings. Novel views apply to the static scene or animation at t=0, so their questions avoid later motion states.
The view names denote the harness cameras described under [Rendering and gates](#rendering-and-gates).

Review points include task `005`'s partially closed eyes, task `007`'s initial eye state, and task
`009`'s small eye/brow details. Task `006` intentionally avoids the hidden pink character's face and
an unreadable hand. Some showcase questions describe absence while still expecting yes. All-yes
questions require judge calibration against wrong and blank renders before scores are interpreted.

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

A step 2 sample uses the step 1 sample of the same model and rep, even when step 1 failed its gates;
its record stores the step 1 sample path, hash, and static gate result under `depends_on`. Recollecting
step 1 makes its step 2 sample stale. Memory kinds are independent of the GIF tasks (task id `mem`,
240 × 240) and are judged with the `[memory]` checklist in the task manifest, which follows the
image-generation traits in `bench/rubric.toml`.

[Prompts](../bench/frontend-v1/prompts.toml) state every contract. A reply must contain an
` ```html ` block; the last one counts. Shared rules: offline, a W × H viewport at device pixel ratio 1,
no raster images (`<img>`, `<image>`, `url()` other than `url(#id)`, `data:` URIs, base64), no external
resources or network APIs, no timers or animation frames, at most 256 KB, and no uncaught exceptions or
console errors. Breaking any rule scores 0.

- **2D:** one inline `<svg viewBox="0 0 W H">`, one named `<g>` per character with nested named
  parts; no `<foreignObject>`, `<canvas>`, or nested `<svg>`. Step 1 and memory pages are static (no
  script, SMIL, CSS animations, or transitions). Step 2 uses exactly one timing method: declarative
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
seeking is exact), and a dead proxy. The page is served from memory at `http://nwb.invalid/`; every
request other than the page and, for 3D, the vendored three.js files is aborted. Pages never see
`file://` URLs. A sample that exceeds 180 seconds is killed.

Static gates read the source: the HTML block, size, forbidden elements and URLs, the 2D `<svg>` and
`viewBox`, static-only rules for step 1 and memory pages, and 3D import specifiers. APIs that comments
may mention (`fetch`, timers) are checked at runtime instead. Runtime gates fail a sample on:

- requests or WebSockets, calls to timers, `fetch`, `XMLHttpRequest`, workers, `Image`, and similar
  APIs (replaced before page scripts run), page errors, and `console.error`;
- 2D: animation in a static page, both or neither timing method in step 2;
- 3D: `nwb.ready` not true within 20 seconds, a malformed `window.nwb`, a canvas that is not W × H,
  image textures or textures larger than 64 × 64, and characters that are unnamed, have fewer than two
  visible meshes, or are flat (depth/width below 0.3 along the reference camera);
- determinism: rendering a time again after other times changes more than 0.1% of pixels;
- step 2: no keyframe differs from t = 0 by more than 0.5% of pixels, or t = 0 and t = D differ by
  more than 1%.

The renderer writes `frame_NN.png` at each keyframe time (only `frame_00` for static kinds), a 12 fps
`preview.gif` for step 2, and, for 3D, `view_side`, `view_back`, `view_three_quarter`, and `view_top`
at t = 0. Harness cameras orbit the characters' bounding sphere; "front" is the reference camera's
horizontal direction, and the near plane sits just in front of the sphere so that walls between a
harness camera and the characters are clipped. `render.json` records gates and evidence; changing the
renderer or vendored files re-renders every sample.

## Judging and scoring

A checklist judge sees one rendered image and its questions, never the reference, and answers yes or
no for each question. Judges sit behind a small `ChecklistJudge` interface; the default
`ModelJudge` asks an LLM through the normal backends. The default pool is
`[defaults].frontend_judges` in `models.toml` (Claude Opus 5.5 and GPT-6.1-Sol). As in the other
tracks, judges from the subject's own vendor are left out when another judge exists; those judge calls
are skipped.

An image's score is the share of yes answers, averaged over the counted judges. A sample's score is
the mean over its judged images: one frame for static kinds, eight for step 2, plus the four views for
3D. Samples that fail a gate score 0 without judging. Scores are reported per model and kind, with 3D
keyframe and view sub-scores, and 95% bootstrap intervals that resample tasks and reps.

Because every expected answer is yes, `nwb frontend judge` also judges calibration controls for each
task in the run: the reference keyframes (should score high), a blank page and another panel task's
keyframes (should score low), and, for memory, the canonical meme image, a blank page, and task
`003`'s first frame.

## Running the track

```sh
uv sync --extra frontend
uv run --extra frontend playwright install chromium
uv run --extra frontend nwb frontend collect --run pilot --models gpt-6.1-sol --tasks 001
uv run --extra frontend nwb frontend render --run pilot
uv run --extra frontend nwb frontend judge --run pilot
uv run --extra frontend nwb frontend report --run pilot
```

`collect` defaults to all tasks and all kinds with one rep; step 1 samples are collected before step 2.
Subject calls may take up to 30 minutes. Samples are `runs/<run>/frontend/<model>/<task>/<kind>__r<rep>.json`,
renders are in the directory with the same stem, and judgments are under `runs/<run>/frontend-judgments/`.
`report` writes `runs/<run>/frontend/scores.json` and `gallery.html`, which shows the reference GIF and
keyframes beside each sample's renders, judge answers, a sandboxed live preview of 2D animations, and the
page source as text. Every stage resumes and skips finished work; `--force` redoes it.

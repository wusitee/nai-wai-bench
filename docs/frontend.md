# Experimental frontend corpus

`bench/frontend-v1/` contains draft reference data for inline-SVG and three.js reconstruction.
It is outside the NaiWai Index. The corpus and its checklists await human review; no frontend model
results, judging, scoring, browser renderer, or site integration are implemented yet. The 3D component
is unranked until calibrated.

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
The view names denote harness cameras; camera placement is not implemented yet.

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
freeze reviewed inputs before collecting comparisons. Existing benchmark commands do not load this
corpus as a suite.

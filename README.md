<img src="assets/icon.svg" width="64" height="64" alt="">

# nai-wai-bench · 奶蛙bench

English | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-Hant.md)

A benchmark of how well AI models know the Chinese internet meme **大笑奶龙** (Laughing Nailong, also
called **奶蛙**): an AI-generated, "mutated" 奶龙 doubled over with laughter, clutching its belly.

<img src="bench/reference/nailong_laugh.png" width="200" alt="The canonical 大笑奶龙 image">

**Results:** [wusitee.github.io/nai-wai-bench](https://wusitee.github.io/nai-wai-bench/) (0.1.0 release:
95% bootstrap intervals and rank ranges).

It publishes two visual-understanding rankings and combines them into the **奶蛙指数 · NaiWai Index**:

1. **识梗 Meme ID** (`--suite core`, 13 image tasks): recognize the meme and its variants, name it and its
   aliases, and distinguish official artwork. Nine free-form answers are LLM-judged; four pose and eye
   checks use fixed answer keys.
2. **看图 Visual detail** (`--suite naihub-v1`, 24 images): report family, subject count, posture, eyes,
   mouth, gesture, and tears, scored locally against answer keys. An image counts only when all seven
   fields are correct.

The index is the weighted mean of both scores (Meme ID 1/3, Visual detail 2/3) for models ranked in both.
Text-only lore, visual memory, and prompt writing in Chinese and English are diagnostics outside every
ranking. Only complete fixed panels receive provisional ranks. Partial runs remain visible with coverage
counts. Small score differences are not evidence of a reliable ordering.

**Image generation** is an experimental track outside the index: image models draw the meme as other
animals from five prompt tiers (its Chinese name, its English name, a brief description, a detailed
description of its 3D look, and the reference image). An optional, unscored set also tests transferring
other 奶蛙 expressions (angry, facepalm, smug) to other animals.

Claude Opus 5.5 judges free-form answers and generated images by default; answer-keyed tasks are scored
locally. Reports use the configured judge pool unless `--judges` selects another. Collecting results needs
no judge access: [contributors](docs/contributing-results.md) can share results for judging elsewhere.

## Getting started

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and at least one logged-in agent CLI or API key:
[Codex](https://github.com/openai/codex) (OpenAI models and image generation),
[Claude Code](https://claude.com/claude-code) (Anthropic models, or other providers' Anthropic-compatible
endpoints), [pi](https://github.com/earendil-works/pi) (any provider pi supports), an ACP agent such as
DeepSeek Harness (DeepSeek and GLM models), Kimi Code, or Antigravity, or an OpenAI-compatible API such as
Xiaomi MiMo (key from an environment variable or [CC Switch](https://github.com/farion1231/cc-switch)).

```sh
uv sync
uv run nwb list                                   # models, items, tiers, animals

# Understanding: visual tasks plus text diagnostics and no-image controls
uv run nwb understand --models opus-5.5,gpt-6.1-sol,deepseek-v4-pro,mimo-v2.6-pro
# Image generation: six animals × five tiers = 30 images per model
uv run nwb imagegen --models chatgpt-image --animals default

uv run nwb judge                                  # default judges from models.toml (needs Claude Code)
uv run nwb report                                 # writes runs/main/report.html
uv run nwb site                                   # writes site/index.html
```

Working results go to `runs/<run>/` (`--run NAME`, default `main`). Collection, judging, and reporting
also save portable copies under `results/<suite>/<run>/` for normal Git commits and pushes. Commands
resume interrupted runs and retry failed samples; a fresh checkout restores missing working runs
from the saved results automatically. Use `--no-sync` for local experiments.

## Releases

See the [changelog](CHANGELOG.md) and [benchmark card](docs/benchmark-card.md) for versioned releases,
validation status, and corrections. `uv run nwb --version` prints the installed version;
`uv run nwb export --run RUN --suite SUITE` exports raw results for offline re-scoring.

To rebuild the selected comparison from retained raw results, run
`uv run nwb release --manifest releases/0.1.0.toml`. It builds both suites and downloadable bundles
without model calls. See the [release workflow](docs/releases.md) for restoring inputs and publishing.

Ranked rows require homogeneous conditions; legacy settings are flagged. Effective effort is high where
exposed, otherwise default, with labels showing the recorded setting. Reports include paired cluster
intervals and token efficiency; these are small-panel sensitivity estimates and list API cost estimates,
not significance claims or subscription bills. See the [methodology](docs/methodology.md).

## Documentation

- [Architecture](docs/architecture.md): execution flow, scoring paths, result storage, and interactive board
- [Release workflow](docs/releases.md): pinned comparison inputs, offline builds, raw bundles, and publishing
- [Visual detail set (Nai-hub v1)](docs/naihub-eval-set.md): the 24-image answer-keyed panel with
  no-image controls and eight transfer references (`--suite naihub-v1`)
- [Experimental frontend track](docs/frontend.md): models rebuild GIFs as SVG or three.js pages,
  rendered in a sandboxed browser, gate-checked, and reviewed by people in a gallery (`nwb frontend`)
- [Benchmark design](docs/design.md): items, tiers, rubrics, scoring, results site, and run layout
- [Evaluation methodology](docs/methodology.md): research basis, budget, controls, and limitations
- [Optional state transfer](docs/design.md#optional-state-transfer): transfer angry, facepalm, and smug
  expressions to cat/frog in 12 images per generator; separate state-extraction checks, without LLM grading
- [Backends and models](docs/backends.md): how each agent CLI is driven and isolated, and how to add models,
  including pi and other providers through Claude Code
- [Contributing results](docs/contributing-results.md): collecting and sharing results without judge access,
  and judging shared results
- [Episode videos](docs/video.md): format, data rules, build pipeline, and publishing for the Bilibili
  result videos
- [Sources](bench/reference/SOURCE.md): where the reference image, stickers, and facts come from

The reference image and stickers are included for non-commercial research use only.

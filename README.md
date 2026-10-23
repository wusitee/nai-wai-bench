<img src="assets/icon.svg" width="64" height="64" alt="">

# nai-wai-bench · 奶蛙bench

English | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-Hant.md)

A benchmark of how well AI models know the Chinese internet meme **大笑奶龙** (Laughing Nailong, also
called **奶蛙**): an AI-generated, "mutated" 奶龙 doubled over with laughter, clutching its belly.

<img src="bench/reference/nailong_laugh.png" width="200" alt="The canonical 大笑奶龙 image">

**Results:** [wusitee.github.io/nai-wai-bench](https://wusitee.github.io/nai-wai-bench/) (first draft:
one repetition per cell, LLM judges); [Nai-hub v1 casebook](https://wusitee.github.io/nai-wai-bench/naihub-v1/).

It publishes two independent rankings:

1. **Visual understanding**: recognize the meme and its variants, distinguish official artwork, and answer
   image-grounded questions with fixed answer keys. Text-only lore, visual memory, and prompt writing in
   Chinese and English are separate diagnostics; they do not affect visual rank.
2. **Image generation**: image models draw the meme as other animals (cat, panda, frog, giraffe, octopus,
   and elephant in the default panel)
   from five prompt tiers: the meme's name in Chinese, its name in English, a brief description, a detailed
   description of its 3D look, and the reference image. Matched name-only and described results measure
   sensitivity to prompt detail.

Only complete fixed panels receive provisional ranks. Partial runs remain visible with coverage counts.
Small score differences are not evidence of a reliable ordering. An optional, unscored suite also tests
whether generators can transfer other 奶蛙 expressions (angry, facepalm, smug) to other animals.

Judges from several vendors score every sample; a model is never scored by its own vendor's judges when
an independent judge is available.

## Getting started

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and at least one logged-in agent CLI or API key:
[Codex](https://github.com/openai/codex) (OpenAI models and image generation),
[Claude Code](https://claude.com/claude-code), an ACP agent such as DeepSeek Harness, Kimi Code, or
Antigravity, or an OpenAI-compatible API such as Xiaomi MiMo (key from an environment variable or
[CC Switch](https://github.com/farion1231/cc-switch)).

```sh
uv sync
uv run nwb list                                   # models, items, tiers, animals

# Understanding: visual tasks plus text diagnostics and no-image controls
uv run nwb understand --models opus-5.5,gpt-6.1-sol,deepseek-v4-pro,mimo-v2.6-pro
# Image generation: six animals × five tiers = 30 images per model
uv run nwb imagegen --models chatgpt-image --animals default

uv run nwb judge                                  # default judges from models.toml
uv run nwb report                                 # writes runs/main/report.html
uv run nwb site                                   # writes site/index.html
```

Results go to `runs/<run>/` (`--run NAME`, default `main`). Commands resume interrupted runs and retry
failed samples.

## Documentation

- [Nai-hub v1 evaluation set](docs/naihub-eval-set.md): optional 24-image expansion with local answer
  keys, no-image controls, and eight transfer references (`--suite naihub-v1`)
- [Benchmark design](docs/design.md): items, tiers, rubrics, scoring, results site, and run layout
- [Evaluation methodology](docs/methodology.md): research basis, budget, controls, and limitations
- [Optional state transfer](docs/design.md#optional-state-transfer): transfer angry, facepalm, and smug
  expressions to cat/frog in 12 images per generator; separate state-extraction checks, without LLM grading
- [Backends and models](docs/backends.md): how each agent CLI is driven and isolated, and how to add models
- [Sources](bench/reference/SOURCE.md): where the reference image, stickers, and facts come from

The reference image and stickers are included for non-commercial research use only.

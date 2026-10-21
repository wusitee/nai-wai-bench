<img src="assets/icon.svg" width="64" height="64" alt="">

# nai-wai-bench

English | [简体中文](README.zh-CN.md)

A benchmark of how well AI models know the Chinese internet meme **大笑奶龙** (Laughing Nailong, also
called **奶蛙**): an AI-generated, "mutated" 奶龙 doubled over with laughter, clutching its belly.

<img src="bench/reference/nailong_laugh.png" width="200" alt="The canonical 大笑奶龙 image">

It has two parts:

1. **Understanding**: text and vision LLMs explain the meme's origin and lore, describe its look from memory,
   write image prompts for it, and recognize it from images. Answers are checked against sourced facts, and
   confident hallucinations are penalized.
2. **Image generation**: image models draw the meme as other animals (cat, giraffe, octopus, and more)
   from four prompt tiers: the meme's name in Chinese, its name in English, a full visual description, and
   the reference image. Comparing name-only results with described results shows whether a model actually
   knows the meme or can only draw it when told what it looks like.

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

# Part 1: ask models about the meme, then judge the answers
uv run nwb understand --models opus-5.5,gpt-6.1-sol,deepseek-v4-pro,mimo-v2.6-pro
# Part 2: draw the default animal subset with every tier
uv run nwb imagegen --models chatgpt-image --animals default

uv run nwb judge                                  # default judges from models.toml
uv run nwb report                                 # writes runs/main/report.html
```

Results go to `runs/<run>/` (`--run NAME`, default `main`). Commands resume interrupted runs and retry
failed samples.

## Documentation

- [Benchmark design](docs/design.md): items, tiers, rubrics, scoring, and run layout
- [Backends and models](docs/backends.md): how each agent CLI is driven and isolated, and how to add models

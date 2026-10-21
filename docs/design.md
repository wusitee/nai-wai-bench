# Benchmark design

English | [简体中文](design.zh-CN.md) | [繁體中文](design.zh-Hant.md)

nai-wai-bench measures how well AI models know the Chinese internet meme 大笑奶龙 (Laughing Nailong, also
called 奶蛙): an AI-generated, "mutated" 奶龙 hunched over, clutching its belly, laughing with its eyes
squeezed shut and its mouth agape. The canonical image is `bench/reference/nailong_laugh.png`; sources are
listed in `bench/reference/SOURCE.md`.

There are two parts.

## Part 1: understanding (`nwb understand`)

Text and vision LLMs answer questions about the meme. Items are defined in `[understanding.*]` in
`bench/tasks.toml`:

| Item | Modality | What it tests |
|---|---|---|
| `knowledge_zh`, `knowledge_en` | text | Origin, aliases, remixes, and lore, asked in Chinese and in English |
| `describe` | text | Recalling the canonical image's visual traits without seeing it |
| `write_prompt.<animal>` | text | Writing a text-to-image prompt for an animal version (tests applying the knowledge) |
| `recognize_zh`, `recognize_en` | vision | Identifying the meme from the reference image |
| `recognize_variant` | vision | Identifying the meme from a panda drawn in its style |

Every prompt is prefixed with an instruction to answer from the model's own knowledge, and the backends
disable web search and other tools (see [backends.md](backends.md)). If an agent still calls a tool, the
answer is marked `contaminated` and excluded from judging and scoring; the report shows the count.

**Scoring.** Each item has a checklist of ids from `bench/rubric.toml`: facts (`[facts.*]`) for knowledge
and recognition items, visual traits (`[traits.*]`) and `identity` for the describe and prompt items. A judge
scores each id 0 (missing or wrong), 1 (partial or vague), or 2 (clearly correct), and lists hallucinations:
confident claims that contradict the notes, `[background]`, or `[misconceptions]`, or details the judge is
confident are invented. Hedged guesses are not hallucinations.

```
item score = 100 × Σ checklist scores / (2 × checklist size) − 10 × hallucinations   (floored at 0)
```

## Part 2: image generation (`nwb imagegen`)

Image models draw the meme as other animals (`[animals.*]` in `bench/tasks.toml`). Each animal is rendered
with four prompt tiers (`[imagegen.tiers.*]`):

| Tier | Prompt gives | What it isolates |
|---|---|---|
| `name_zh` | Only the meme's name, in Chinese | Knowledge of the meme |
| `name_en` | Only the meme's name, in English | Cross-lingual knowledge |
| `described` | A full visual description, without the name | Rendering ability (upper bound) |
| `reference` | The reference image plus "draw a ⟨animal⟩ version" | Style transfer from an example |

Animals tagged `anatomy_conflict` (giraffe, octopus, shark, penguin) stress the pose and body traits;
`frog` plays on the 奶蛙 name. `--animals default` runs the subset marked `default = true`.

**Scoring.** A vision judge sees the reference image and the generated image. It scores each visual trait
0–2, scores `identity` (is it recognizably the target animal) 0–2, and flags failure modes
(`[failure_modes]`: `generic_cute`, `realistic_animal`, `plain_nailong`, and others).

```
style   = 100 × Σ (trait score × weight) / (2 × Σ weights)
overall = style × identity / 2
```

Trait weights favor what distinguishes the meme from any cute laughing animal: pose and belly clutch (2),
mouth and vibe (1.5), then eyes, body, and render (1), and belly patch and background (0.5).

**Knowledge ratio** = mean overall score of the two name tiers ÷ the `described` tier. A ratio near 1 means
the model draws the meme from its name as well as from a description; a low ratio means it can draw the
style but does not know the meme.

Image generators are agents (Codex, Antigravity) that receive the benchmark prompt and forward it to their
image tool. The harness reads the prompt argument of each recorded image-tool call and checks that it equals
the benchmark prompt exactly; the report counts samples where it did not.

## Judges and aggregation (`nwb judge`, `nwb report`)

Any configured model with `text` can judge part 1; judging part 2 needs `vision`. Default judges are listed
under `[defaults].judges` (part 1) and `[defaults].image_judges` (part 2) in `models.toml`. Judges answer in
JSON; replies that fail validation are retried once and then recorded as errors.

Image judges describe what they see for each trait, then rate it with a word (`absent`, `partial`,
`match`; identity `no`, `partly`, `clearly`) that maps to 0–2.

Each sample's score is the mean over judges, excluding judges from the subject's own vendor when at least one
independent judge exists (self-judging was visibly lenient in testing). A failure mode counts when at least
half of the judges flag it. Each judgment is tied to the version of the sample it scored and to the exact
judge prompt: when a sample is regenerated or the rubric changes, `nwb judge` redoes the judgment and
`nwb report` ignores the old one.

The report's **judge health** table shows, per judge and track, the spread of its scores across samples and
its mean distance from the other judges on the same samples. A near-zero spread means the judge is not
discriminating; a large distance means it disagrees with the panel. Either is a reason to leave the judge
out: `nwb report --judges` counts only the listed judges. Gemini 3.8 Flash (via Antigravity) is excluded from the default image judges for
this reason: it rated every trait of every image `partial`, even when its own notes described a match.

## Run layout

Each run lives in `runs/<run>/` (git-ignored), with one JSON file per sample:

```
runs/<run>/understanding/<model>/<item>__r<rep>.json
runs/<run>/imagegen/<model>/<tier>/<animal>__r<rep>.json      (+ <animal>__r<rep>/ with the image files)
runs/<run>/judgments/<judge>/<same path as the judged sample>
runs/<run>/scores.json, runs/<run>/report.html
```

Commands skip samples that already succeeded with the current prompt and redo ones that recorded an
`error` or were made with a different prompt, so an interrupted run resumes where it stopped; `--force`
regenerates everything selected.

## Extending

- **Facts or traits:** add entries to `bench/rubric.toml` and reference their ids from item checklists.
  Ids must be unique across facts, traits, and identity; `nwb` validates this at startup.
- **Items, tiers, animals:** edit `bench/tasks.toml`. Use `{zh}` and `{en}` in prompts for animal names.
- **Models:** see [backends.md](backends.md).

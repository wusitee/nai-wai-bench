# Benchmark design

English | [简体中文](design.zh-CN.md) | [繁體中文](design.zh-Hant.md)

nai-wai-bench (Chinese name: 奶蛙bench) measures how well AI models know the Chinese internet meme
大笑奶龙 (Laughing Nailong, also called 奶蛙): an AI-generated, "mutated" 奶龙 hunched over, clutching its
belly, laughing with its eyes squeezed shut and its mouth agape. The canonical image is
`bench/reference/nailong_laugh.png`; sources are listed in `bench/reference/SOURCE.md`.

There are two independent, provisional rankings: **image generation** and **visual understanding**.
There is no combined score across them. Text/language performance is diagnostic only. See
[evaluation methodology](methodology.md) for the research basis, budget, and limits of the protocol.

Unless stated otherwise, this document describes the default `core` suite. The optional
[naihub-v1 evaluation set](naihub-eval-set.md) provides a separate 24-image, answer-keyed visual
panel with broader pose/style coverage and eight transfer references. Select it with `--suite naihub-v1`
and use a separate run; its joint-accuracy scores are not comparable with the core panel's scores.

## Ranking panels

- **Image generation:** six default animals (cat, panda, frog, giraffe, octopus, elephant) × all five tiers,
  or 30 cells. Each cell needs a current judgment and a verified verbatim prompt audit (`true`). Changed
  and unverified prompts are visible in diagnostics but ineligible for ranking.
- **Visual understanding:** all 13 image-input items: nine recognition tasks and four answer-keyed
  grounding checks. Text-only models are not listed in this ranking.

Each panel score is the arithmetic mean of its cell means; repetitions are averaged within each cell
first. Every required cell must be scored, with every attempted repetition id scored in every cell.
An attempted failed repetition cannot silently disappear from eligibility. A generation cell that the
image provider's safety system refused for the verified verbatim prompt scores 0 without judges (see
[backends.md](backends.md#codex-backend--codex)); refusals are outcomes, so they are not retried
automatically. Incomplete or uneven panels have coverage and status but no rank or ranking score. Failed, contaminated, stale, and
unjudged samples cannot fill a cell. Additional animals and text tasks cannot change the fixed-panel score.
Models can use different repetition counts, shown beside their scores; compare the same count when
possible. Exact scores share ranks when equal. These ranks describe the observed panel, not statistical
significance or general multimodal ability.

`scores.json` stores these tables under `leaderboards.imagegen` and `leaderboards.visual_understanding`.
The older `understanding.overall` field now aliases the available-item vision mean; it is not a mixed
text/vision score. Diagnostic means use available items and may differ from the qualified ranking score.

## Part 1: understanding (`nwb understand`)

Text and vision LLMs answer questions about the meme. Items are defined in `[understanding.*]` in
`bench/tasks.toml`:

| Item | Modality | What it tests |
|---|---|---|
| `knowledge_zh`, `knowledge_en` | text | Origin, aliases, remixes, and lore, asked in Chinese and in English |
| `describe`, `describe_en` | text | Recalling visual traits without seeing the image, in Chinese and English |
| `write_prompt.<animal>`, `write_prompt_zh.<animal>` | text | Writing animal-version prompts in English and Chinese, for cat and giraffe |
| `recognize_zh`, `recognize_en` | vision | Identifying the meme from the reference image |
| `recognize_variant` | vision | Identifying the meme from a panda drawn in its style |
| `recognize_naiwa`, `recognize_angry` | vision | Identifying the meme family from real stickers: the frog-like 奶蛙 (「惊鸿一瞥」) and a red angry variant (「切换愤怒模式」) |
| `recognize_facepalm`, `recognize_smug`, `recognize_folded_arms` | vision | Recognizing three visually distinct circulating mutated-Nailong stickers |
| `recognize_official` | vision | Distinguishing official Nailong artwork from the unofficial meme (negative control) |
| `grounding.<case>` | vision | Reporting pose and eye state from four existing stimuli using fixed JSON labels |
| `grounding.<case>.blind` | text | The identical question with the image withheld; a diagnostic control |

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

The four grounding cases are defined under `[grounding]` in `bench/tasks.toml`. Their answer keys are
scored locally: 50 points for the correct pose and 50 for the correct eye state, without LLM judgments.
Wrong, missing, or `unknown` fields earn zero; a reply without a JSON object earns zero. JSON fences
are accepted, labels ignore case and surrounding whitespace. No-image controls are excluded from the
text and vision means. **Visual gain** is the mean matched with-image minus no-image score, in percentage
points, pairing each case and repetition. Missing controls yield no paired difference, not a zero score.
This is a diagnostic of image dependence, not MMStar's full leakage analysis.

`--items vision` selects only image-input tasks, `--items text` selects text-input tasks (including blind
controls), and `--items grounding` selects the four grounding cases and their four controls.
These selectors and the default command select the core suite; `--items states` opts into the separate
state-extraction suite described below.

## Part 2: image generation (`nwb imagegen`)

Image models draw the meme as other animals (`[animals.*]` in `bench/tasks.toml`). Each animal is rendered
with five prompt tiers (`[imagegen.tiers.*]`):

| Tier | Prompt gives | What it isolates |
|---|---|---|
| `name_zh` | Only the meme's name, in Chinese | Knowledge of the meme |
| `name_en` | Only the meme's name, in English | Cross-lingual knowledge |
| `described_brief` | A one-line description of the look, without the name | Drawing it from a rough idea |
| `described_detailed` | A detailed description of the pose, body, and smooth 3D render style, without the name | Rendering ability (upper bound) |
| `reference` | The reference image plus "draw a ⟨animal⟩ version" | Style transfer from an example |

Animals tagged `anatomy_conflict` (giraffe, octopus, shark, penguin) stress the pose and body traits;
`frog` plays on the 奶蛙 name. `--animals default` runs the fixed six-animal panel marked `default = true`.
`--animals all` includes all 12 species; the extra species appear in diagnostics and galleries.

**Scoring.** A vision judge sees the reference image and the generated image. It scores each visual trait
0–2, scores `identity` (is it recognizably the target animal) 0–2, and flags failure modes
(`[failure_modes]`: `generic_cute`, `realistic_animal`, `plain_nailong`, and others).

```
style   = 100 × Σ (trait score × weight) / (2 × Σ weights)
overall = style × identity / 2
```

Trait weights favor what distinguishes the meme from any cute laughing animal: pose and belly clutch (2),
mouth and vibe (1.5), then eyes, body, and render (1), and belly patch and background (0.5).

**Knowledge ratio** = mean overall score of both name tiers ÷ the `described_detailed` tier, restricted
to animals scored in all three tiers. Repetitions are averaged within each animal/tier cell first.
It is unavailable without matched animals or when the mean denominator is zero. A ratio near 1 indicates
similar performance under the two prompt conditions; a low ratio indicates a benefit from the detailed
prompt. It is not a calibrated probability that the model knows the meme, and may exceed 1. Comparing
`described_brief` with `described_detailed` shows how much spelling out the render style helps. Diagnostics
also provide per-animal means; adding repetitions of one animal cannot increase its aggregate weight.

Image generators are agents (Codex, Antigravity) that receive the benchmark prompt and forward it to their
image tool. The harness reads the prompt argument of each recorded image-tool call and checks that it equals
the benchmark prompt exactly; the report counts samples where it did not.

## Optional state transfer

`[state_transfer]` in `bench/tasks.toml` defines three source states: angry, facepalm, and smug. The goal is
to transfer the source's visible expression and body language onto another species, beyond the canonical
laughing pose. The default targets are cat and frog. Each state has two generation conditions:

- `state_<state>_reference`: the appropriate source image is attached, with the same neutral transfer
  instruction for every state. The source state is not named in that prompt.
- `state_<state>_described`: no image is attached; a fixed description supplies its expression and gesture.

The suite costs 3 states × 2 animals × 2 conditions = **12 images per generator per repetition**. Use
`--animals` to select other species explicitly. `--tiers states` selects these six optional tiers; the
default generation command still selects only the five core tiers and 30 core cells. Tier ids and output
paths are distinct, so prior core samples remain reusable.

`--items states` selects `states.<state>` and `states.<state>.blind`: three image-input questions and three
matched no-image controls. The same extraction prompt asks for `state`, `eyes`, `mouth`, and `gesture`.
Each correct field earns 25 points locally; wrong, missing, or `unknown` fields earn zero. These diagnostics
appear under `state_understanding` in `scores.json`, with matched visual gain, and never enter either
core ranking. Default understanding runs and `--items vision` do not add these optional calls.

State-generation outputs remain **unscored** in reports and the site. `nwb judge` skips them, and aggregation
ignores any existing canonical-trait judgments attached to them: a rubric rewarding belly-clutching
laughter is invalid for an angry or facepalm target. The site shows state source images with generated
outputs for human review. See [methodology.md](methodology.md#cross-animal-state-transfer) for the review
criteria and limits. Reference preparation and provenance are in [SOURCE.md](../bench/reference/SOURCE.md).

```sh
# Optional suite only; these commands generate answers/images, not LLM grades.
uv run nwb understand --run states --models VISION_MODEL --items states
uv run nwb imagegen --run states --models IMAGE_MODEL --tiers states
uv run nwb report --run states
uv run nwb site --run states
```

## Judges and aggregation (`nwb judge`, `nwb report`)

Any configured model with `text` can judge text answers; judging recognition answers and generated images
needs `vision`. Recognition judges receive the actual stimulus as well as the reference notes. Legacy
recognition judgments made without the image do not count and must be regenerated. Grounding checks and
their blind controls need no judge calls. Default judges are listed
under `[defaults].judges` (part 1) and `[defaults].image_judges` (part 2) in `models.toml`. Judges answer in
JSON; replies that fail validation are retried once and then recorded as errors.

Image judges describe what they see for each trait, then rate it with a word (`absent`, `partial`,
`match`; identity `no`, `partly`, `clearly`) that maps to 0–2.

Each sample's score is the mean over judges, excluding judges from the subject's own vendor when at least one
independent judge exists (self-judging was visibly lenient in testing). A failure mode counts when at least
half of the judges flag it. Each judgment is tied to the version of the sample it scored and to the exact
judge prompt: `nwb judge` redoes it when either changes, and `nwb report` ignores judgments of a sample that
has since been regenerated. The report also counts only samples made with the current prompts, so samples of
removed or reworded items and tiers drop out until they are regenerated.

The report's **judge health** table shows, per judge and track, the spread of its scores across samples and
its mean distance from the other judges on the same samples. A near-zero spread means the judge is not
discriminating; a large distance means it disagrees with the panel. Either is a reason to leave the judge
out: `nwb report --judges` counts only the listed judges. Gemini 3.8 Flash (via Antigravity) is excluded from the default image judges for
this reason: it rated every trait of every image `partial`, even when its own notes described a match.

## Results site (`nwb site`)

`uv run nwb site --run v1` builds a bilingual Chinese/English site in `site/`, separate from the local
report. Each page covers one suite and run. It opens with the visual-understanding and image-generation
rankings, with coverage and repetitions per cell; an image-generation panel without results is left out. The
remaining sections appear when the run has data for them:

- **Casebook:** one card per answer-keyed image item, grouped by the task file's `category`. Each card shows
  the image, its answer key, a verdict strip (one segment per model, in visual-ranking order; green when
  every field is correct), each model's wrong fields with the label it gave, and raw replies including
  the no-image control. Models that answered only the no-image control get no verdict, but their replies
  are listed. The naihub-v1 page leads with the casebook and a mosaic of its images.
- **Image generation:** one gallery per animal with every core tier, score, failure modes, and prompt
  audit (provider refusals appear as refused cells; a record's `meta.fill_note` labels images made through
  another route, with the hover text naming it); diagnostic tier means and matched knowledge ratios.
- **State transfer:** each source image beside its generated outputs, unscored.
- **Understanding diagnostics:** summary columns that have values in the run; for suites with family
  labels, joint, visual-joint, family-macro, per-field, and per-category heatmaps; free-form answers;
  optional state extraction as its own casebook.
- **Models** (access metadata, C2PA provenance, and the answer-key annotator when the suite names one)
  and **judge health** when the run has judgments.

Missing judgments appear as dashes. With repetitions, galleries and casebook cards show the first
repetition while summaries include every sample. Heatmap cells darken as scores fall below 100. When a
suite's `[dataset].annotation_record` names an annotator model, that model is flagged in the ranking: its
score measures agreement with its own labels.

The header records the suite, run name, build date, and the repository commit (`git rev-parse --short HEAD`,
marked when `bench/` or `src/` have uncommitted changes). With `--repo-url`, the methodology and
source links point to that commit.

`--out DIR` selects the output directory; `--judges NAME,...` restricts scoring to those judges; `--repo-url URL` adds a source link; `--suite-tabs` adds tabs linking every suite's page, assuming the published layout below. The builder writes `index.html` and relative image assets without deleting existing output files. Images are resized to fit within 768 × 768 pixels using ImageMagick (`magick`) when available, and copied unchanged otherwise. Gallery thumbnails preserve the full image.

C2PA names only `ChatGPT · gpt-image` for OpenAI and “Created by Google Generative AI” for Google; neither exposes a more specific image model version. These are vendor declarations, not verified signatures. `meta.client` identifies the relay client, not the underlying image generator.

### Publishing

`scripts/publish_site.sh [CORE_RUN [NAIHUB_RUN]]` (defaults `v1` and `naihub-v1`) builds the core suite into the root of a fresh temporary directory and naihub-v1 into `naihub-v1/`, both with suite tabs, adds `.nojekyll`, and replaces the `gh-pages` branch on `origin` with only the generated site. Both runs must exist. It requires `uv`, Git, configured Git author identity, and push access, and leaves the checked-out branch unchanged. Generated runs and site files stay git-ignored on the source branch.

Enable GitHub Pages once with `gh api -X POST repos/OWNER/REPO/pages -f 'source[branch]=gh-pages' -f 'source[path]=/'`; if Pages is already enabled, use `-X PUT` instead. Inspect `gh api repos/OWNER/REPO/pages/builds/latest` for build status and `gh api repos/OWNER/REPO/pages --jq .html_url` for the URL. **The Pages site is public even when the source repository is private.** Publish only results intended for public access.

## Run layout

Each run lives in `runs/<run>/` (git-ignored), with one JSON file per sample:

```
runs/<run>/understanding/<model>/<item>__r<rep>.json
runs/<run>/imagegen/<model>/<tier>/<animal>__r<rep>.json      (+ <animal>__r<rep>/ with the image files)
runs/<run>/judgments/<judge>/<same path as the judged sample>
runs/<run>/scores.json, runs/<run>/report.html
```

Commands skip samples that already succeeded with the current prompt and redo ones that recorded an
`error` or were made with a different prompt, so an interrupted run resumes where it stopped. Provider
refusals are kept as results; `--force` regenerates everything selected.

## Extending

- **Facts or traits:** add entries to `bench/rubric.toml` and reference their ids from item checklists.
  Ids must be unique across facts, traits, and identity; `nwb` validates this at startup.
- **Items, tiers, animals:** edit `bench/tasks.toml`. Use `{zh}` and `{en}` in prompts for animal names.
- **Models:** see [backends.md](backends.md).

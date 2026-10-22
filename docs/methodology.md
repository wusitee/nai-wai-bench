# Evaluation methodology

English | [简体中文](methodology.zh-CN.md) | [繁體中文](methodology.zh-Hant.md)

This is a small, domain-specific benchmark of 大笑奶龙 / 奶蛙 knowledge, recognition, and animal-style
transfer. It is not a general intelligence or general image-quality benchmark. Its two provisional
rankings measure image generation and visual understanding independently. The implemented scoring and
coverage rules are described in [design.md](design.md).

The panels and budgets below describe the default `core` suite. The optional
[naihub-v1 set](naihub-eval-set.md) uses 24 structured image questions and paired no-image controls,
with local answer keys, all-field joint accuracy, per-field diagnostics, and separate family macro
accuracy. Its labels remain provisional; it does not reproduce the core ranking protocol.

## Research basis

These are adaptations of established evaluation principles, not reproductions of the cited benchmarks
or claims of equivalent validation.

| Primary source | Useful principle | Application here |
|---|---|---|
| [GenEval (2023)](https://arxiv.org/abs/2310.11513) | Evaluate distinct visual properties rather than one global similarity score | Score pose, expression, rendering, and animal identity separately; publish trait and animal diagnostics |
| [TIFA (2023)](https://arxiv.org/abs/2303.11897) | Decompose faithfulness into answerable visual questions | Grounding probes have explicit pose/eye answer keys; generation judges assess individual traits with visible evidence |
| [GenEval 2 (2025)](https://github.com/facebookresearch/GenEval2) | Broaden concept coverage and audit whether evaluator scores remain aligned with people | Use six anatomically varied animals and retain inspectable images and rationales; the protocol below calls for a small human audit |
| [MMStar (2024)](https://arxiv.org/abs/2403.20330) | Check whether questions need the image and separate visual benefit from language priors | Ask identical grounding questions on different stimuli and withhold each image in a paired control |
| [MMBench (2024 revision)](https://arxiv.org/abs/2307.06281) | Match Chinese/English questions and check sensitivity to answer choices | Match knowledge, visual-memory, and prompt-writing tasks across languages; use semantic JSON labels instead of letter-choice positions |

This harness does not implement GenEval's detectors, TIFA's question-generation pipeline, GenEval 2's
Soft-TIFA probabilities, MMStar's training-leakage measurement, or MMBench's CircularEval. Their full
pipelines are unnecessary for this small corpus and can require substantially more inference or local
models. Fixed answer keys need no evaluator model, and existing reference-grounded trait judgments
remain inspectable without introducing a large evaluation stack.

## What the two rankings measure

**Image generation** uses six animals across five prompt tiers: 30 cells per model. Cat and panda test
familiar mammal identities; frog checks the meme's amphibian association; giraffe and octopus stress
transferring the pose onto different anatomy; elephant tests distinctive ears and trunk. This is a
purposeful small panel, not a representative sample of animals. Five tiers distinguish performance
with names, descriptions, and a reference. Their mean measures performance on this meme task across
prompt conditions, so inspect tier scores when comparing name recall with reference-based transfer.

**Visual understanding** uses nine recognition questions and four grounding questions. Recognition
includes the canonical image in two languages, an animal remix, circulating variants, and official art
as a negative control. These tasks combine visual evidence with cultural knowledge. The four grounding
items ask the same pose and eye-state question about four different images; their answer keys contain
only directly observable properties. They test basic perception, not difficult visual reasoning.
Each of the 13 items has equal weight; the canonical image is intentionally tested twice for the
bilingual recognition check. The public images are reused across tasks, so 13 questions are not 13
independent visual examples.

**Text/language diagnostics** use four matched tasks per language: knowledge, visual description from
memory, and prompt writing for cat and giraffe. They use the same checklists across translations.
Language means exclude blind controls and must be compared on matching item coverage and judge panels.
An English prompt-writing answer can itself use another language: these tasks measure understanding of
the input language, not strict output-language compliance. The generation tiers are not translations
of a fully matched experiment, so their differences cannot isolate language alone.

**No-image controls** repeat the four grounding prompts without their images. Scores are matched by
case and repetition before computing visual gain. Refusals and `unknown` receive no correctness credit
in either condition. Therefore gain also depends on willingness to guess and instruction following;
it is evidence about this task's image dependence, not a pure measure of visual ability. A model that
always predicts open eyes already gets 75% on that field; report pose and eye answers when auditing,
and do not assume a 50% chance baseline for the overall score.

## A constrained evaluation budget

Start with one repetition on the entire panel for every model. Broad, matched coverage is more useful
than many cat repetitions. Run counts below exclude failures and the judge's single allowed retry.

| Work per subject model | Calls at one repetition |
|---|---:|
| Generation panel | 30 image-generation requests |
| Generation judging with two configured judges | 60 vision-judge requests |
| Visual understanding | 13 answer requests |
| Text/language diagnostics | 8 answer requests |
| No-image controls | 4 answer requests |
| Judging all free-form understanding answers with two vision-capable judges | 34 judge requests |
| Judging grounding answers and controls | 0 |

Two configured judges do not guarantee two independent judgments: when the subject shares a vendor
with one, only the other contributes. Use the same configured pool across subjects and record it.
To get two independent vendors for every subject may require three judge vendors. Judge health is a
disagreement diagnostic, not proof of evaluator correctness or a reason to remove a judge merely
because it changes the ordering. Choose judge exclusions using fixed calibration cases before comparing
subject scores.

```sh
# Cheap visual-dependence diagnostic: four image inputs + four blind controls, no judge calls.
uv run nwb understand --run pilot --models MODEL --items grounding
uv run nwb report --run pilot

# Full comparable panels; understand also collects text diagnostics and blind controls.
uv run nwb understand --run comparison --models VISION_MODEL
uv run nwb imagegen --run comparison --models IMAGE_MODEL --animals default
uv run nwb judge --run comparison --judges VISION_JUDGE_A,VISION_JUDGE_B
uv run nwb report --run comparison
uv run nwb site --run comparison
```

Substitute configured model names from `nwb list`. Models without vision can run text diagnostics and
blind controls but cannot fill the visual ranking panel. `--items vision` omits text diagnostics and
controls if only the visual panel is needed. `--judges` on report/site changes which recorded judges
count; it does not launch model requests.

## Publication protocol and limitations

1. Freeze the task file, rubric, reference assets, model versions, access settings, repetition count,
   and judge pool before collecting comparison data. Retain the repository revision with exported results.
   Changing the default animal set or required vision items changes the panel and requires a new comparison.
2. Run every required cell. Retry infrastructure errors without selecting among successful outputs.
   A provider's safety refusal of the verbatim prompt is an outcome, scored 0 and not retried.
   Tool-contaminated answers and unverified/changed generation prompts remain ineligible. The harness
   checks prompt identity and sample freshness; it cannot guarantee identical hidden vendor settings.
3. Inspect a small fixed audit set before publication: the four grounding source images, the official-art
   negative control, and the same six generated cells per image model (one per default animal, tier chosen
   in advance). Hide model/vendor labels during the human audit. Include deliberately wrong pose/identity
   examples when calibrating judges. Record disagreements; do not silently edit scores after seeing ranks.
   The harness exposes outputs for this review but does not automate or certify human calibration.
4. Publish panel coverage, repetition counts, tier scores, prompt audits, judge selection, and text/no-image
   diagnostics with ranks. The harness shows provisional observed ranks and does not calculate confidence
   intervals or significance tests. If a consequential ordering needs support, spend remaining budget on
   the same second repetition for all competing models across the complete panel, rather than cherry-picking
   weak cells. For a subsequent statistical analysis, compare paired model differences and resample by
   source image or animal, keeping translations, tiers, and repetitions within each cluster. Four or six
   clusters still give weak uncertainty estimates; avoid strong population-level claims.

Sources are public, the corpus is tiny, some recognition stimuli are synthetic, and source filenames may
be exposed by agent clients. No contamination-free holdout or blinded-input guarantee is claimed. Correct
basic grounding does not establish knowledge of a meme's history; convincing lore does not establish that
a model used its image input. A weighted trait score also retains subjective choices, especially the
`vibe` trait. The knowledge ratio is a matched prompt-sensitivity diagnostic and may exceed one; it does
not identify training exposure. Costs in tokens, images, and latency depend on the configured providers;
the call counts above are a planning budget, not measured billing or new benchmark results.

## Cross-animal state transfer

The optional suite tests whether a source state transfers to another animal, rather than testing only
whether a generator can repeat the canonical laugh. The three source states are angry, facepalm, and
smug-looking, with cat and frog as the small default target panel. These are visible-expression/action
bins for the selected fixtures, not a universal or psychological emotion taxonomy.

For each state/animal pair, compare **reference-image transfer** with **fixed-description generation**.
The reference condition provides the source image and an identical state-neutral instruction; the
description condition gives explicit visible cues without an image. Source body color is not a success
criterion: the animal keeps its own colors and markings, so a red animal alone cannot count as an angry
transfer. For cropped portraits, preserve the framing and do not invent a gesture outside it.

The angry reference has its caption and emoji removed, and all three attachments have neutral filenames.
Otherwise a state-extraction model could answer from 「切换愤怒模式」 or a filename instead of the character.
Sources and the deterministic crop are documented in [SOURCE.md](../bench/reference/SOURCE.md).

The visual-understanding tasks separately extract state, eyes, mouth, and gesture, using the same prompt
on each source plus a no-image control. Local key matching costs **six subject calls and zero judge calls**
per model at one repetition. Those answers are diagnostic: generation uses fixed descriptions, so an
upstream extraction error does not silently change the task given to different image generators.
The fields are not balanced (all three mouths are closed), so do not assume a generic chance score;
inspect individual fields and the matched no-image controls.
Both conditions together cost **12 image requests per generator**, without expanding the default panel.

Generated outputs need human inspection; no LLM judge or canonical laughing score is applied. Review
the same state/animal pair across both conditions with model/vendor labels hidden. Record these criteria
separately before considering a transfer successful:

1. **Animal identity:** the target species is recognizable from meaningful features, not token ears on a
   red or yellow Nailong body.
2. **Expression:** visible eyes, brows, and mouth convey the source state. Generic happiness or a return
   to the canonical gaping laugh is a failure for these three states.
3. **Gesture/posture:** preserve the facepalm or behind-the-back posture when visible. For the smug
   close-up, check its half-lidded eyes and raised chin; do not require imaginary hands.
4. **Style:** keep the smooth, bulky 3D meme rendering. Report this separately from expression correctness.

A joint transfer success requires recognizable animal identity, the source expression, and any visible
gesture/posture. Inspect style independently so polish cannot compensate for an incorrect state. Publish
per-state, per-animal, and per-condition observations; do not merge this tiny optional suite into the two
core rankings. A reference advantage suggests useful visual conditioning on these examples, not proof of
general emotion understanding. With only one source per state, state, source artwork, and viewpoint are
confounded. Add a second independently sourced example per state before making broad transfer claims.

No human ratings are synthesized by the harness. Until a human review is collected, the generation
gallery has no transfer-accuracy score, and the predefined extraction labels remain provisional.

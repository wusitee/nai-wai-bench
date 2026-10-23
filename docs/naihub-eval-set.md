# Nai-hub v1 evaluation set

`--suite naihub-v1` selects a versioned expansion of the default `core` benchmark: 24 static
images, one shared structured question per image, and 24 matched no-image controls. All
understanding answers are scored locally, without LLM judges. This tests family recognition
and visible features; the core suite retains free-form lore, language, and prompt-writing tasks.

Images, keys, source links, upstream revisions where available, and SHA-256 hashes are in
[bench/naihub-v1/tasks.toml](../bench/naihub-v1/tasks.toml). Vendored images have neutral numeric
filenames. The loader verifies their hashes and answer labels; running requires no downloads
or image-processing tools.

## Coverage and sources

| Slice | Images | Cases |
|---|---:|---|
| Anchors | 4 | Canonical laugh, red behind-back pose, forehead touch, narrowed-eye portrait |
| Pose/action | 7 | Squatting chin rest, prone, hands at head, tears, thumb up, pointing, wide stance |
| Appearance | 4 | Hood/mask, outdoor full figure, belly touch without laughter, winged costume remix |
| Context | 5 | Phone under covers, painted ring of five, two at desks, four chin-rest portraits, mirror phone portrait |
| Negative controls | 4 | Official Nailong, Psyduck, Pikachu, Bulbasaur |

Ten images come from [nai-hub](https://nai-hub.com/index.html#/naiwa), six from the
[湖南奶蛙大学 collection](https://xn--6kr28k0gz4eq33b1t7a.com/stickers/), five reuse existing
fixtures, and three are official Pokémon Pokédex artwork. See the
[source notes](../bench/reference/SOURCE.md#nai-hub-v1-evaluation-set) and per-case provenance.
Collection membership records the selection provenance, not ground-truth family labels,
original authorship, or independent origins. The two collections may share upstream sources.

Selected files preserve their source bytes. The red anchor reuses the existing caption-free
crop documented in SOURCE.md. Mode-switch pictures whose captions name a state are excluded.
Some context/style images retain signatures, branding, camera UI, or an AI-generation watermark;
these are not answer keys. Public assets and agent clients do not provide a blinded or
contamination-free holdout, even with neutral filenames.

## Questions and metrics

Every image receives the same English prompt and allowed-label dictionary, without its title,
slice, notes, or answers. The JSON fields are:

- `family`: `mutated_nailong`, `official_nailong`, or `other`.
- `subjects`: `one`, `two`, `four`, or `five` main characters.
- `posture`: upright, crouched, prone, seated, quadruped, or outside the frame.
- `eyes`: open, closed, narrowed, covered, or mixed across characters.
- `mouth`: open, closed, covered, or mixed across characters.
- `gesture`: a fixed visible-gesture label from the task file.
- `tears`: present or absent, based on visible drops or streams.

The prompt defines cropped bodies, mixed subjects, phone holding, and narrowed versus closed
eyes. Upright requires visible hips above downward-extending thighs; hunching alone does not
make a crouch, and knees or feet may be cropped. Torso-only crops use `out_of_frame` for posture.
`raised_arms` includes one or both arms when no more specific gesture applies.
`unknown` is an abstention and earns zero. Wrong, missing, or malformed fields also earn
zero; fences, label case, and surrounding whitespace use the existing JSON scoring rules.
These are visible-state bins, not psychological emotions or inferred motion sequences.

The visual ranking uses **all-field joint accuracy**: a sample earns 100 only when all seven
fields are correct, otherwise 0. Images have equal weight; repetitions are averaged within
each image first. Ranking requires all 24 images with the same attempted repetition ids scored
throughout. At one repetition, one extra perfect image changes the score by about 4.17 points;
small differences do not establish a reliable ordering.

Report/site diagnostics also show per-field means with item coverage, slice means,
**visual joint accuracy** (all six non-family fields correct), and **family macro accuracy**
(equal recall weight per observed expected family label). A complete panel has three family
labels; partial runs can have fewer, explicitly counted. Matched with-image minus no-image
gain uses the partial-credit score. `understanding.vision` and `understanding.overall` remain
available-item partial-credit means, distinct from the qualified joint-accuracy ranking.

The panel has 20 mutated-family images, one official Nailong, and three unrelated characters.
Always predicting the mutated family earns 83.33% raw family accuracy but 33.33% family macro
accuracy. Predicting each field's most common label everywhere earns about 64.29% partial
credit but 0% all-field joint accuracy. These are deterministic constant-label
baselines, not random chance estimates. Compare diagnostics on matching item/label coverage;
related portraits, anchors, and gestures are not independent observations.

This is a small closed-label diagnostic panel with a vocabulary tailored to its examples.
Seventeen gesture labels cover 24 images. Official Nailong and each multi-subject count have
only one example; tears-present has two, including an ambiguous case. Correcting the official
image alone moves family macro accuracy by about 33.33 points. These slices cannot establish
general performance on their classes.

## Running

Use a fresh run and the same suite on every command. The CLI rejects samples from another
suite in that run; legacy samples without a suite field belong to `core`.

```sh
uv run nwb list --suite naihub-v1
# 24 image answers + 24 no-image controls per repetition; no judge requests.
uv run nwb understand --suite naihub-v1 --run naihub-v1 --models VISION_MODEL
uv run nwb report --suite naihub-v1 --run naihub-v1
uv run nwb site --suite naihub-v1 --run naihub-v1 --out site/naihub-v1
```

The site page leads with a casebook of all 24 images, showing each model's wrong fields, and flags
the answer-key annotator in the ranking. `scripts/publish_site.sh` publishes it under `naihub-v1/`
beside the core results; see [Results site](design.md#results-site-nwb-site).

Replace `VISION_MODEL` with a configured name. `--items vision` selects just the 24 image-input
items; `--items grounding.naihub_v1_017` selects the tear case and its blind control. Text-only
models can run controls but cannot fill the visual panel. The default `core` suite retains its
13-image visual panel and existing prompts and scoring rules.

## Optional generation transfer

Eight references select forehead touch, squatting, prone, hands at head, tears, thumb up,
pointing, and the wide stance. Each has fixed-description and reference-image conditions,
with cat/frog as default targets:

```sh
# 8 references × 2 conditions × 2 animals = 32 generation requests per repetition.
uv run nwb imagegen --suite naihub-v1 --run naihub-v1 --models IMAGE_MODEL --tiers states
uv run nwb report --suite naihub-v1 --run naihub-v1
```

The reference prompt is identical across sources and preserves framing. Descriptions specify
visible cues rather than using source color as an emotion proxy. Outputs remain unscored;
review animal identity, expression, gesture, and style separately. The laughing rubric is not
applied. `--items states` optionally extracts the same seven fields on these eight sources
and blind controls; these reused images are not additional independent evidence. The standard
six-animal, five-tier generation panel remains available separately from these transfer tiers.

## Annotation status

The answer keys use GPT-6-Astra with `xhigh` reasoning. The
[annotation record](../bench/naihub-v1/annotations/astra-xhigh.json) preserves the shared protocol,
image hashes, per-field visual evidence, qualitative confidence, and ambiguous alternatives.
The annotator received neutral image IDs and the protocol without previous answer keys, titles,
or collection metadata. This was a procedural separation within a shared workspace, not an
access-isolated or contamination-free blind experiment. Confidence is not a calibrated probability.

The record flags nine field ambiguities across eight images, including possible tears in 007
and differing eye openings in 010. The active keys adopt Astra's best labels even where flagged;
alternatives remain review notes and do not receive credit under exact-match scoring.

These are provisional model annotations, without independent human calibration. Review uncertain
fields before publishing a calibrated comparison. Evaluating Astra against its own labels
measures agreement with those annotations, not independent ground truth. No benchmark evaluation
is claimed by the annotation pass. Changes to the frozen panel or keys require a new suite
version and run. Source links do not establish reuse permission; original authorship remains
unknown for many remixes.

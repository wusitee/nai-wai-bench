# Changelog

All notable changes are documented here in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style.
Software releases use semantic versions; suite ids version the evaluation panels and keys independently.

## Unreleased

- Add run-time summaries to reports and suite pages: retained-call totals and per-track, per-model,
  and judge breakdowns, timing coverage, median/slowest tasks, and collection spans that distinguish
  resumed-session gaps and parallel calls from cumulative client time.
- Add Chinese/English origin-evidence text diagnostics and a sourced Naiwa origin guide, reviewed on
  2026-11-05 against the initial Bilibili investigation, its pinned screenshots, and the creator's
  origin-confirmation follow-up. Distinguish the early Xingye avatar from the later laughing variant,
  and historical prompt speculation from newly written reconstruction guidance. Existing ranked panels,
  generation prompts, retained judgments, and release inputs remain unchanged.
- Add the experimental frontend track (`nwb frontend collect|render|report|sync`, `bench/frontend-v1/`):
  models rebuild animated 奶蛙 GIFs as hand-written inline SVG or three.js pages, with a step-2 animation
  and one check-and-revise round, rendered in a sandboxed browser and checked by scripted gates; likeness
  is reviewed by people. Release manifests select a saved frontend run under `[frontend]`, and release
  sites add the 复刻 Rebuild pages (`frontend/`) with lazy-loaded WebP renders. The 0.1.0 comparison
  selects `frontend-pilot`; the track is outside the NaiWai Index.
- Present the `core` and `naihub-v1` visual rankings as 识梗 Meme ID and 看图 Visual detail, and combine them
  in the versioned 奶蛙指数 · NaiWai Index (Meme ID 1/3, Visual detail 2/3, with paired bootstrap intervals).
  Release sites open with the index and write `index.json`; suite pages move to `meme-id/` and
  `visual-detail/`, and `naihub-v1/` redirects. Image generation moves to an experimental section outside
  the index.
- Add GLM-5.3-Flash, the GLM Coding Plan's GLM-5.3 model with image input, run through pi's built-in
  `zai-coding-cn` provider at high effort (`glm-5.3-flash-pi`), and select it in the 0.1.0 comparison through
  `rel-0.1-with-glm-5.3-flash-and-images-2.6` and `rel-0.1-naihub-with-glm-5.3-flash`, retaining the
  Images 2.6 additions; earlier observations and verdicts are unchanged.
- Add ChatGPT Images 2.6 (`chatgpt-images-2.6`, Codex built-in image generation) to the experimental image
  track and select it in the 0.1.0 comparison through `rel-0.1-with-images-2.6`. That run also adds Opus 5.5
  verdicts for the October `chatgpt-image` row, which had none under the Opus-only judge policy; no existing
  verdicts change.
- Add egg-alpha, an undisclosed preview model on the TokenRhythm router, run through pi at high effort, and
  select it in the 0.1.0 comparison through `rel-0.1-with-egg-alpha` and `rel-0.1-naihub-with-egg-alpha`;
  earlier rows are unchanged. The pi backend now resends provider-rate-limited (HTTP 429) prompts after the
  provider's retry hint.
- Select Claude Fable 5.1 (high) in the 0.1.0 comparison through the merged runs `rel-0.1-with-fable-5.1`
  and `rel-0.1-naihub-with-fable-5.1`, matching the published site; earlier rows are unchanged.
- Use Opus 5.5 as the sole default judge and for the selected 0.1.0 core comparison, including
  self-judgments; retain other judges' raw verdicts and score reports, sites, snapshots, exports, and merges
  with each track's configured judge pool unless `--judges` selects another recorded pool. `nwb judge --judges`
  only chooses which judges to call.
- Add Gemini 4 Argon and max-effort configurations of GPT-6.1-Sol, GPT-6-Astra, GPT-6.1 Terra,
  GPT-6-Luna, and Claude Opus/Sonnet/Haiku 5.5, with saved core understanding runs judged by reduced
  judge sets; the 0.1.0 release selection is unchanged.
- Record the costliest `modelUsage` entry as a Claude result's `resolved_model`. Claude Code also lists
  auxiliary models there, so earlier Claude records can name `claude-haiku-5-5` for answers and
  judgments the requested model produced, as their reported costs show.
- Add the Claude Fable 5.1 configuration to the maintained model registry, with a saved Nai-hub v1 run.
- Start the Claude and Codex CLIs through their resolved executables and read their output as UTF-8,
  so npm `.cmd` shims and non-UTF-8 console code pages on Windows work; recorded command templates
  keep the bare command name, and arguments that `cmd.exe` would reinterpret are refused.
- Add `nwb merge` to combine separately collected runs into a fresh run for a release manifest.
- Refuse settings-mismatched successful results before any request unless `--force` is explicit;
  leave collection logs and snapshots unchanged on no-op collection commands.
- Support the recorded `legacy-v1` and `isolated-v1` Codex tool profiles and disclose the retained
  comparison's mixed subject/judge profiles in scores, row labels, and release documentation.
- Save portable JSON/image snapshots to `results/` after collection, judging, and reporting; restore
  missing working runs from these checked-in results, with per-file checksum validation.
- Reconcile the maintained collector, scorer, reports, and raw bundle exporter with the 0.1.0 results
  format, retaining support for legacy timestamp-based judgments.
- Add an offline release build driven by a manifest of suite runs, normalized input hashes, and judge
  selections. Publishing uses the same build and requires an explicit manifest.
- Include the GPT-6.1 Terra and GPT-5.6-Sol comparison configurations in the maintained model registry.
- Add the `pi` backend (pi coding agent in RPC mode), which confirms the selected model, thinking level, and
  image input before prompting.
- Run other providers' models through Claude Code from an entry's `env` or a CC Switch provider; such entries
  must supply their own key, inherited Anthropic credentials are withheld from these endpoints, and Claude
  Code's cost estimate is not retained.
- Add GLM-5.3 and GLM-5.3-Flash through dsh's pi-ai routes for Zhipu's GLM providers.
- Show `awaiting judges` for panels whose missing cells and repetitions are collected but unjudged, and
  document collecting and sharing results without judge access.
- Add the Claude Fable 5.1 max-effort configuration with saved core and Nai-hub v1 runs, and save Opus 5.5
  and GPT-6.1-Sol judgments for both Fable core runs, scored with the Opus-only default.

## [0.1.0] - 2026-10-25

### Added

- First versioned release: `core` and `naihub-v1` suites, separate visual-understanding and image-generation
  rankings, fixed-panel coverage, answer keys, text diagnostics, and matched no-image controls.
- Vendor-aware LLM judges (three vendors for image generation), contributing-judge counts, content and
  judge-prompt freshness checks.
- Recorded effective settings, effort labels, neutral staged image names, UTC collection dates and revisions;
  mixed settings or alternate routes cannot receive a rank. Legacy settings remain explicitly unrecorded.
- Paired cluster-bootstrap score intervals and rank ranges; repeated-answer consistency for naihub-v1.
- Token coverage, client time, list API price estimates, and separate subject/judge resource accounting.
- `nwb --version`, deterministic sanitized results bundles (`nwb export`), and site download links.
- Benchmark card and a canary marker in benchmark data, bundles, and generated pages.

### Known limitations / planned for 1.0

- Naihub-v1 keys are GPT-6-Astra annotations pending human validation.
- LLM judges have not yet been human-audited.
- Current image-generation results use one repetition per cell.
- Small, deliberately selected panels yield fragile orderings; intervals do not support population claims.
- Human-validated keys and a human judge audit are prerequisites for 1.0, not claims of this release.

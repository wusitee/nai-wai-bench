# Changelog

All notable changes are documented here in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style.
Software releases use semantic versions; suite ids version the evaluation panels and keys independently.

## Unreleased

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
- Add the Claude Fable 5.1 configuration to the maintained model registry.
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

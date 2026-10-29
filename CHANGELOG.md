# Changelog

All notable changes are documented here in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style.
Software releases use semantic versions; suite ids version the evaluation panels and keys independently.

## Unreleased

- Save portable JSON/image snapshots to `results/` after collection, judging, and reporting; restore
  missing working runs from these checked-in results, with per-file checksum validation.
- Reconcile the maintained collector, scorer, reports, and raw bundle exporter with the 0.1.0 results
  format, retaining support for legacy timestamp-based judgments.
- Add an offline release build driven by a manifest of suite runs, normalized input hashes, and judge
  selections. Publishing uses the same build and requires an explicit manifest.
- Include the GPT-6.1 Terra and GPT-5.6-Sol comparison configurations in the maintained model registry.

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

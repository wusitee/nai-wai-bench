# Release workflow

The maintained `nwb` package collects, scores, exports, and builds results. A release manifest in
`releases/` selects one comparison across both suites. Media projects and intermediate renders are
independent of this workflow.

## Selected comparison

[`releases/0.1.0.toml`](../releases/0.1.0.toml) selects the expanded comparison including GPT-6.1 Terra
and the high/xhigh GPT-5.6-Sol configurations:

| Suite | Raw run | Judge policy |
|---|---|---|
| `core` | `rel-0.1-with-gpt-5.6-sol` | Only the recorded judge names listed in the manifest; vendor exclusion still applies per sample |
| `naihub-v1` | `rel-0.1-naihub-with-gpt-5.6-sol` | Local answer-key scoring, without judges |

This historical comparison mixes two recorded Codex collection profiles:

| Subject rows | Profile |
|---|---|
| `gpt-6.1-sol`, `gpt-6-astra` | `legacy-v1` |
| `gpt-6.1-terra-xhigh`, `gpt-5.6-sol`, `gpt-5.6-sol-xhigh` | `isolated-v1` |

Both disable web/browser access. The isolated profile additionally disables shell execution, agents,
plugins, skill search, goals, sleeping, image-viewing tools, and interactive mode features. The complete
feature list and versioned `tool_profile` option are in [backend documentation](backends.md#codex-tool-profiles).
The maintained backend recreates both recorded command configurations. Historical `gpt-6.1-sol`
judgments also include both profiles; reports expose recorded subject and judge profiles and label
each ranked row. These remain provisional observed rankings across different model and collector
configurations. The collection-profile effect is confounded with the model: use matching profiles
and judge conditions for controlled comparisons. The original observations and numeric scores are retained.

The manifest records the software version, collection-source artifact identity, run names, normalized
SHA-256 input digests, and explicit judge selections. Collection source identity describes the retained
observations; it is separate from the revision building the current site. Models, efforts, and historical
price metadata live in `models.toml`. Machine paths and credentials belong in ignored local configuration.

Portable raw results are kept on the source branch under `results/<suite>/<run>/`. Each snapshot
contains sanitized answers, judgments, generated images, scores, a re-scoring README, and
`snapshot.json` with per-file checksums, the normalized input digest, and judge selection. JSON stays
readable in Git diffs, and unchanged images reuse the same Git blobs. `.gitattributes` preserves the
exported bytes across checkouts so line-ending conversion cannot invalidate judgment hashes.

The resumable working copy remains in ignored `runs/<run>/`. Collection, judging, reporting, and site
or bundle commands restore a missing working copy from its saved snapshot; `nwb release` does the same
for selected runs. Restoration verifies checksums and suite membership before writing. An existing
working run takes precedence. Explicit restoration requires a fresh working directory:

```sh
uv run nwb restore --suite core --run rel-0.1-with-gpt-5.6-sol
```

Raw ZIP bundles are still available for separate downloads. Extract them into fresh run directories;
their README gives the suite and re-scoring command.

## Saving results to Git

`nwb understand`, `imagegen`, and `judge` refresh the saved snapshot after invocations that execute
jobs, including partial runs and recorded failures. `report` and explicit `sync` refresh derived
results without model calls. No-op collection commands leave logs and snapshots unchanged. Each snapshot contains the retained run,
not just its most recent model. An unchanged file is left untouched; obsolete generated files are
removed only when they were listed in the previous snapshot. Generated HTML, unrelated logs, local
configuration, and temporary files are excluded.

Use `--no-sync` on collection or reporting commands for local experiments. To save an existing run
explicitly, with an optional recorded judge selection:

```sh
uv run nwb sync --suite core --run RUN --judges opus-5.5,gpt-6.1-sol
```

Saving writes files under `results/`; include them with the corresponding source/configuration
changes in normal Git commits and pushes. The benchmark commands do not stage, commit, or push Git
changes. Release manifests remain explicit: collecting new observations does not silently update a
frozen comparison's input pins.

## Build and review offline

```sh
uv sync
uv run nwb release --manifest releases/0.1.0.toml --out site
```

This command makes no model requests and restores missing working runs from repository snapshots.
Before writing release output, it checks
the software version, suite membership, input digests, configured judge names, and judgment freshness
for every selected suite. Missing inputs, changed inputs, and stale judgments are errors. Failed raw
requests remain in the bundles; incomplete model panels remain visible without a rank.

Input digests cover normalized sample JSON, image outputs, judgments, and `collection.jsonl` when
present. They exclude generated reports, scores, and existing ZIP exports. Normalization uses the
exporter's home-path sanitization and content-based judgment identity, so extracting a bundle preserves
its release digest despite different file timestamps. A mismatch reports the expected and observed digest.
Review the underlying records before changing a manifest's pin.

The output contains:

| Path | Contents |
|---|---|
| `index.html`, `images/`, `scores.json` | Core results and assets |
| `naihub-v1/` | Nai-hub results, assets, and scores |
| `bundles/` | Portable raw bundles linked from each suite's page |
| `release.json` | Selected manifest, its hash, and build revision |
| `.nojekyll` | GitHub Pages marker |

Review the pages, contributing judges, coverage, settings, and raw bundle contents locally. The builder
updates these generated outputs without removing unrelated files from an existing output directory.
The publisher always builds into a fresh temporary directory.

## Collecting and extending a comparison

Choose a new run name for new collection conditions. Subject and judge records carry their settings
fingerprints, model/effort metadata, and collection revision. Resume reuses a successful sample only
when its recorded job identity still matches. A successful subject result with changed prompts, inputs,
or settings, or a successful judgment with a different settings identity, stops the entire requested
batch before logging or model requests. Choose a new run for changed model
IDs, effort, tool profiles, or command/configuration files. `--force` explicitly authorizes replacement
of existing results. Legacy literal executable paths and current environment-variable templates can
also produce different fingerprints; restoration and re-scoring are available without replaying calls.
Panels mixing recorded settings within a model retain diagnostic scores but cannot receive a rank.

A release selects one run per suite, so rows collected in separate runs must be combined first. Judge
new rows in their own runs, because resuming a retained run stops on a judgment recorded under different
settings. Then merge without model calls:

```sh
uv run nwb merge --suite core --run NEW_RUN --from RETAINED_RUN,ADDED_RUN
```

The target must be a fresh run. Sources stay unchanged, missing ones are restored from their saved
results, collection logs are concatenated in source order, and a file that differs between sources
stops the merge without creating the target. Legacy judgments that identify their sample by
modification time are converted to content hashes checked against their own source, so stale
judgments stay stale. Pin the merged run in a new manifest after reviewing it.

Use the ordinary `nwb understand`, `imagegen`, `judge`, `report`, and `export` commands for individual
runs. `report`, `site`, and `export` require an existing run. An archived comparison is not selected by
searching for the newest directory: update or add an explicit manifest after reviewing its input runs.
Retain original snapshots or bundles as evidence; additional comparison directories do not need to
be deleted to build the selected release.

## Publish

After reviewing and authorizing the generated release:

```sh
scripts/publish_site.sh releases/0.1.0.toml
```

The script rebuilds the same manifest and force-updates only `gh-pages` on `origin`, without switching
the source checkout. It publishes the pages and sanitized raw bundles. Git author identity and push
access must be configured. See [results-site hosting](design.md#publishing) for GitHub Pages setup.

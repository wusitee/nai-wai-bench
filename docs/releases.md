# Release workflow

The maintained `nwb` package collects, scores, exports, and builds results. A release manifest in
`releases/` selects one comparison across both suites. Media projects and intermediate renders are
independent of this workflow.

## Selected comparison

[`releases/0.1.0.toml`](../releases/0.1.0.toml) selects the expanded comparison including GPT-6.1 Terra,
the high/xhigh GPT-5.6-Sol configurations, Claude Fable 5.1 (high), egg-alpha (high, pi through the TokenRhythm
router), GLM-5.3-Flash (high, pi through Zhipu's GLM Coding Plan endpoint), and ChatGPT Images 2.6
(Codex built-in image generation):

| Suite | Raw run | Judge policy |
|---|---|---|
| `core` | `rel-0.1-with-glm-5.3-flash-and-images-2.6` | Opus 5.5 only, including its judgments of Opus and other Anthropic subjects |
| `naihub-v1` | `rel-0.1-naihub-with-glm-5.3-flash` | Local answer-key scoring, without judges |

Each selected run is a chain of `nwb merge`s; every source remains saved. The earlier comparison runs
(`rel-0.1-with-gpt-5.6-sol`, `rel-0.1-naihub-with-gpt-5.6-sol`) were merged with the Fable runs
(`fable-5.1-core`, `fable-5.1-naihub`) into `rel-0.1-with-fable-5.1` and `rel-0.1-naihub-with-fable-5.1`,
those with the egg-alpha runs (`egg-alpha-core`, `egg-alpha-naihub`) into `rel-0.1-with-egg-alpha` and
`rel-0.1-naihub-with-egg-alpha`. The core result was merged with `images-2.6-core` into
`rel-0.1-with-images-2.6`, then with `glm-5.3-flash-pi-core` into
`rel-0.1-with-glm-5.3-flash-and-images-2.6`. The Nai-hub result was merged with
`glm-5.3-flash-pi-naihub` into `rel-0.1-naihub-with-glm-5.3-flash`. The earlier
`rel-0.1-with-glm-5.3-flash` core comparison remains archived without the Images 2.6 additions.
The Fable, egg-alpha, and GLM-5.3-Flash Nai-hub rows have three repetitions per image, averaged within
each image. egg-alpha's vendor is undisclosed, so judge independence from Opus 5.5 cannot be confirmed.

`chatgpt-images-2.6` repeats the `chatgpt-image` configuration after OpenAI's Images 2.6 launch on
2026-11-04. Codex names no image model in its output or C2PA credentials, so the row relies on OpenAI's
statement that Images 2.6 serves Codex on all plans ([announcement](https://openai.com/index/introducing-images-2-6/),
[availability post](https://x.com/OpenAI/status/2118124966055223755)); the `chatgpt-image` row is the same
relay collected in October.
Opus 5.5 verdicts for the October `chatgpt-image` images were added in `rel-0.1-with-images-2.6`, so both
rows are scored by the same judge.

This historical comparison mixes two recorded Codex collection profiles:

| Subject rows | Profile |
|---|---|
| `gpt-6.1-sol`, `gpt-6-astra` | `legacy-v1` |
| `gpt-6.1-terra-xhigh`, `gpt-5.6-sol`, `gpt-5.6-sol-xhigh` | `isolated-v1` |

Both disable web/browser access. The isolated profile additionally disables shell execution, agents,
plugins, skill search, goals, sleeping, image-viewing tools, and interactive mode features. The complete
feature list and versioned `tool_profile` option are in [backend documentation](backends.md#codex-tool-profiles).
The maintained backend recreates both recorded command configurations. Historical `gpt-6.1-sol`
judgments, retained for alternative re-scoring, also include both profiles; reports expose recorded subject and judge profiles and label
each ranked row. These remain provisional observed rankings across different model and collector
configurations. The collection-profile effect is confounded with the model: use matching profiles
and judge conditions for controlled comparisons. All original observations and judges' raw verdicts are
retained. Derived scores use only Opus 5.5; Naihub-v1 continues to use its local answer keys.

The manifest's `[frontend]` table selects the experimental [frontend track](frontend.md) run, saved under
`results/frontend/<run>/` by `nwb frontend sync`, and pins its digest. The 0.1.0 manifest selects
`frontend-pilot`: tasks 001, 004, 007, 008, and the memory task, one sample each, from Claude Opus 5.5,
GPT-6.1-Sol, and Kimi K3.1 Pro at high effort (without revisions) and from GPT-6-Astra, GPT-6.1-Sol, and
Claude Opus 5.5 at xhigh and Kimi K3.1 Pro at max (with revisions). The track is outside the index.

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
uv run nwb restore --suite core --run rel-0.1-with-glm-5.3-flash-and-images-2.6
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

Scoring for reports, sites, exports, snapshots, and merges uses the configured judge pools (Opus 5.5 only
by default), each for its own track. `--judges` selects a different recorded pool for both tracks without
requesting new judgments; on `nwb judge` it only chooses which judges to call. Raw verdicts
from other judges remain in snapshots and bundles. Release builds use the explicit judge selection in
their manifest, independently of these defaults.

Use `--no-sync` on collection or reporting commands for local experiments. To save an existing run
explicitly, with an optional recorded judge selection:

```sh
uv run nwb sync --suite core --run RUN --judges opus-5.5
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
| `index.html`, `images/`, `index.json` | NaiWai Index overview and its versioned rows |
| `meme-id/` | Meme ID (`core`) page, assets, and scores |
| `visual-detail/` | Visual detail (`naihub-v1`) page, assets, and scores |
| `frontend/` | Experimental frontend track (复刻 Rebuild): gate table and one page per task, with WebP renders |
| `bill/` | Token bill: total tokens, usage by model and reasoning effort, contributor credits, and `bill.json` |
| `naihub-v1/` | Redirect to `visual-detail/` for earlier links |
| `bundles/` | Portable raw bundles linked from each suite's page |
| `release.json` | Selected manifest, its hash, and build revision |
| `.nojekyll` | GitHub Pages marker |

Review the pages, contributing judges, coverage, settings, and raw bundle contents locally. The builder
updates these generated outputs without removing unrelated files from an existing output directory.
CI builds into a fresh directory on every run.

### Token bill

The bill page and the overview's summary are not limited to the manifest's runs. Running usage counts
every unique saved call under `results/`, the same calls and credit rules as
[`nwb contributions`](contributing-results.md#contribution-credit); calls whose client reported no usage
are listed without tokens. Usage rows are per registry entry and recorded model and effort, so an entry
whose settings changed between runs gets one row per configuration.

The reasoning-effort comparison takes each provider model that one backend ran at more than one effort and
averages output tokens per task over the tasks every one of those efforts answered. Calls are pooled by
recorded effort, whichever registry entry made them; efforts outside the known scale, such as an unset
default, are left out. When the compared efforts were collected under different
[Codex tool profiles](backends.md), the card names each profile and says that its gap mixes effort with
the collector.

Building usage, the coding-agent tokens spent writing and reviewing the benchmark, comes from
`results/agent-usage.json`. It is a self-reported snapshot that cannot be rebuilt from the repository;
without the file the bill shows running usage only. Refresh and commit it before publishing:

```sh
scripts/agent_usage.py
```

The script reads [`toktop-collector --snapshot`](https://github.com/wusitee/toktop) and writes per-model
totals and the covered dates only, with no session titles or paths. A response that appears in several log
files, as after a resumed or forked session, is counted once. Logs the machine no longer has are missing
from the snapshot.

A session counts when its project directory is at or below this checkout or one of its current Git
worktrees, or below any directory named like the main checkout. The name rule catches worktrees that have
since been removed, and would also catch an unrelated directory of the same name. Pass `--include DIR`
for a separate clone elsewhere. Benchmark calls run in temporary `nwb-*` directories; sessions with such a
path component are always left out, so the two figures do not overlap.

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

## Saved runs outside the release

`results/core/` also keeps single-model understanding runs that no manifest selects directly. Apart from
`fable-5.1-core`, a source of the selected merged run, they are archived observations, not rows of the
0.1.0 comparison:

| Runs | Subject settings | Recorded judges |
|---|---|---|
| `gemini-4-argon` | `gemini-4-argon-high` (high through the model id) | `opus-5.5`, `gpt-6.1-sol` |
| `gpt-6.1-sol-max`, `gpt-6-astra-max`, `gpt-6.1-terra-max`, `gpt-6-luna-max` | `max`, `isolated-v1` | `opus-5.5` |
| `opus-5.5-max`, `sonnet-5.5-max`, `haiku-5.5-max` | `max` | `gpt-6.1-sol` |
| `fable-5.1-core` | `high` | `opus-5.5`, `gpt-6.1-sol` |
| `fable-5.1-max` | `max` | `opus-5.5`, `gpt-6.1-sol` |

The two Fable runs are saved with the default Opus-only pool, like the published site; their
GPT-6.1-Sol verdicts stay in the snapshot as raw judgments, and
`uv run nwb report --run fable-5.1-core --judges gpt-6.1-sol --no-sync` shows those scores (use
`--run fable-5.1-max` for the `max` run). The other runs' saved scores count every recorded judge.
Re-scoring them with the default pool leaves the Claude `max` runs at `awaiting judges` until Opus judges
them; pass their recorded judges with `--judges` to reproduce the saved scores. The retained high-effort
`gpt-6.1-sol` and `gpt-6-astra` rows
use `legacy-v1`. Score differences from the release rows therefore mix effort with judge and
collection-profile changes; a controlled effort comparison needs matching profiles and judges.

`results/naihub-v1/` keeps the matching Nai-hub runs `fable-5.1-naihub` (`high`, merged into the selected
run) and `fable-5.1-max-naihub` (`max`, archived): three repetitions of the fixed panel, scored locally from the answer
keys, so they need no judges. A subscription limit interrupted the `max` run; 17 samples used the
Claude Code login and 127 an API key, with the same recorded settings.

## Publish

CI (`.github/workflows/ci.yml`) runs the tests and builds the manifest named by the workflow's
`RELEASE_MANIFEST` on every pull request and every push to `main`. On `main`, it then deploys that build,
pages and sanitized raw bundles, to GitHub Pages, so merging to `main` updates the site. Change the
variable when a new manifest becomes the published release.

To republish without a new commit, for example after a failed deployment:

```sh
gh workflow run CI --ref main
```

Deployments run one at a time, and a run whose commit is no longer the head of `main` skips
deployment, so an older commit never replaces a newer site. See [results-site hosting](design.md#publishing) for GitHub Pages setup.

# Contributing results

Collecting answers and images needs only the models under test. LLM judges score free-form answers and
generated images; answer-keyed tasks are scored locally. Contributors without access to the configured
judges (by default Claude Opus 5.5 through Claude Code, `[defaults]` in `models.toml`) can collect and
share results, and someone with the judges scores them later from the shared files.

## What needs a judge

| Result | Scoring | Judge calls |
|---|---|---|
| Visual detail ranking (`--suite naihub-v1`) | Local answer keys | None |
| Meme ID grounding probes, no-image controls, state extraction | Local answer keys | None |
| Meme ID ranking (`--suite core`: recognition items and grounding probes) | Vision judge for recognition, keys for grounding | Recognition items |
| Text diagnostics (lore, description, prompt writing) | Text judge with reference notes | Every item |
| Experimental image-generation ranking | Vision judge | Every image |
| Optional state-transfer images | Unscored | None |

Without judgments, `nwb report` shows the locally scored results. A row whose remaining panel cells and
repetitions are collected but not yet judged has the status `awaiting judges`.

## Collecting without judges

Add the models to test to `models.local.toml` (git-ignored), or to `models.toml` when they should appear
with a label and price in shared reports. Any backend works: an agent CLI, [pi](backends.md#pi-backend--pi)
with any provider it supports, [Claude Code with another provider's endpoint](backends.md#other-providers-through-claude-code),
or an [OpenAI-compatible API](backends.md#openai-compatible-apis-backend--openai).

Use a run name unique to you, with one run per suite. A working run cannot mix suites.

```sh
uv run nwb understand --models my-model --run alice-core
uv run nwb imagegen --models my-image-model --run alice-core
uv run nwb report --run alice-core                     # local scores; judged cells await judges

uv run nwb understand --suite naihub-v1 --models my-model --run alice-naihub
uv run nwb report --suite naihub-v1 --run alice-naihub # complete visual ranking, no judges needed
```

Do not run `nwb judge`; it calls the configured judges. Each command saves a portable copy under
`results/<suite>/<run>/`. Commit that directory and open a pull request, or send the archive written by
`uv run nwb export --suite <suite> --run <run>`.

You can judge with models you do have (`nwb judge --judges NAME`). The saved snapshot and later reports
and exports still count only the configured judge pool, so these judgments do not change shared scores;
view them with `nwb report --judges NAME --no-sync`, which leaves the snapshot unchanged. They are retained in the shared results.

## Judging shared results

With shared results in `results/<suite>/<run>/`, the judge command restores the working run when
`runs/<run>/` is missing, judges every current sample, and saves the judgments back into the results:

```sh
uv run nwb judge --run alice-core
uv run nwb report --run alice-core
```

Commit the updated results directory. Restoring never overwrites a working run: after a contributor
updates shared results, remove the old `runs/<run>/` before judging again.

To compare a contributed model with other runs, judge it in its own run first, then combine the runs
without model calls and report the merged run. Judging after merging can fail when retained judgments
have different settings identities; the [release workflow](releases.md) describes the merge rules.

```sh
uv run nwb merge --suite core --run comparison --from main,alice-core
uv run nwb report --suite core --run comparison
```

Rows still need matching collection conditions to be compared; see the [methodology](methodology.md).

## Contribution credit

`uv run nwb contributions` ranks contributors by what their saved calls would cost at the pay-as-you-go
API list prices in `models.toml`. It reads every call record under `results/` (answers, generated images,
judgments, and frontend pages) without model calls and prices each one from its model entry's `price` in
`models.toml` (plus `models.local.toml`); each `price` names its source, and some are catalog estimates
rather than verified vendor rates. Plain input, cache reads (`cached_input`), cache writes
(`cache_write`), and output are billed at their own rates. Subscription CLIs are not billed per token,
so the total is a value estimate, not a bill. `--brief` omits the per-model breakdown; `--json` prints the
full ranking.

- A call is counted once, even when merged runs repeat it.
- A call is credited to the Git author of the commit that first added its record content under
  `results/`; author names follow `.mailmap`. Calls not yet committed appear as `(uncommitted)`.
- Calls whose entry has no `price` show "no list price", and calls without reported usage show
  "no usage". Neither counts as zero, and a contributor with no priced call is unranked.
- An entry missing from the registry uses the price of configured entries with the same resolved model id
  when their billing rates agree. Generated-image calls never use this fallback, because their tokens
  describe only the relay around the image tool.
- Prices are the current `price` tables, not the price on the collection date.

Optional `results/contributors.toml` corrects credit when Git authorship is wrong, for example when a
maintainer commits results someone else collected:

```toml
[runs]     # "<suite>/<run>" = contributor; applies to collected calls in that run, not to judgments
"core/alice-core" = "Alice"

[aliases]  # Git author name = displayed name, to merge identities
"alice-laptop" = "Alice"
```

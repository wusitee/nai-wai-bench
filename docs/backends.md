# Backends and models

English | [简体中文](backends.zh-CN.md) | [繁體中文](backends.zh-Hant.md)

Most models run through agent CLIs that are already installed and logged in on your machine, so the
benchmark uses existing subscriptions; the `openai` backend calls an OpenAI-compatible API with a key.
Models are configured in `models.toml`; put machine-specific paths or extra models in `models.local.toml`
(git-ignored), which is merged per model.

Every agent call starts in a fresh, empty temporary directory so agents never load this repository's
`AGENTS.md`/`CLAUDE.md` or other project context. The Claude and Codex CLIs are started through the
executable found on `PATH` at call time (on Windows, the npm `.cmd` shim) and their output is read as
UTF-8; the recorded command template keeps the bare command name.

Every attachment is copied at call time into a separate fresh temporary directory as `image-1.<ext>`,
`image-2.<ext>`, and so on, preserving order. This covers subject stimuli, generation references, and
judges' reference and generated images. Codex receives only these neutral paths through `--image`;
ACP image blocks contain base64 data and MIME type, with no URI or name; Claude uses base64 sources;
the OpenAI backend uses data URLs. Logical repository/run-relative paths remain in records only.
Generated-image collection excludes input copies by content hash. The API backend starts no agent process
and sends no working directory; all CLI/ACP processes use fresh temporary working directories.

Every sample records `meta.client`: the CLI name and version, ACP `agentInfo` name and version, or API host. Image samples also record `meta.c2pa`, the vendor-declared generators and action descriptions read from C2PA content credentials without verifying signatures. Missing credentials are recorded as `null`.

An empty understanding answer is recorded as an error and retried on the next run. Some ACP agents end
their turn without text when their API cannot be reached.

## Collection settings and metadata

`effort` is shared across backends: Codex sets `model_reasoning_effort` (the legacy `reasoning` key is
still accepted), Claude passes `--effort`, and ACP sets its advertised session option. The configured
ACP `effort_option` selects that option explicitly; otherwise the `thought_level` category is used.
DeepSeek uses `reasoning_effort=high`; Kimi uses `thinking=high`, below its `max` setting. Gemini's `high`
is encoded in its model id and recorded with `effort_source="model-id"`. The image relay stays `low`.
An unavailable or unconfirmed ACP setting fails with `BackendError`; unsupported API effort also fails.
`default` leaves the client's effort control unset.

Each subject/judge record stores sanitized `settings` and a 16-hex `settings_id`. Settings include the
backend, configured model, effort/source, requested ACP config, command template, hashes of referenced
repository files, and API hostname. Environment names may be recorded; their values and API keys are
excluded. Labels, prices, and timeouts do not change identity. Changed settings or referenced patches
prevent reuse of cached samples; successful records require a new run or explicit `--force` before
replacement. Image jobs additionally require `input_names="neutral"`. ACP also records
all reported current session values as `meta.session_config`. `meta.resolved_model` holds the model the
client reports, or `null` when unavailable. Judge freshness uses the target JSON's SHA-256, so replacing
its bytes invalidates a judgment even when its modification time is preserved.

Every written result, including errors, has `collected.started_at`, `finished_at` (UTC), `revision`, and
`nwb_version`. Revision is captured once per process and gains `+dirty` when `bench/`, `src/`, `config/`,
or `models.toml` differ from HEAD. A collection invocation that executes jobs appends its UTC time, argv,
revision, version, and involved models' settings to `runs/<run>/collection.jsonl`.

Raw `meta.usage` is retained. `meta.tokens` normalizes these counters:

| Counter | Meaning |
|---|---|
| `input` | All input, including cache reads and writes |
| `cached_input` | Input served from cache |
| `cache_write` | Input written to cache, when reported |
| `output` | All output, including reasoning/thinking |
| `reasoning` | The reasoning subset of output, when reported |

Missing counters are `null`, never inferred as zero. Codex output already includes reasoning. Claude
input sums `input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens`; its reported
dollar estimate is retained as both `cost_usd` and `cost_usd_reported`. OpenAI-compatible usage maps
prompt/completion counters and their cache/reasoning details. ACP accepts per-call `inputTokens`,
`outputTokens`, `thoughtTokens`, `cachedReadTokens`, and `cachedWriteTokens` from prompt results,
usage notifications, or `_meta`. When a native ACP `totalTokens` proves that cache counters are
additional to `inputTokens`, normalization adds them to input; otherwise input is treated as inclusive.
The checked dsh and Kimi clients' automatic notifications report only context occupancy (`usage_update.used/size`), retained as `meta.usage_updates`; that is not billable usage.
Kimi Code CLI 2.3.1 also exposes `/usage`, a local command returning session input/output totals without
another model call. Kimi entries opt in with `usage_command="/usage"`; each sample uses a fresh session,
so those totals cover its one subject or judge prompt. Output includes thinking; cache/reasoning subsets
remain unknown. The command must be advertised before it is sent. Its text and any parse/request error
are stored in `meta.usage_command`, separate from the answer; parsed counters set
`meta.tokens_source="usage-command"` without changing raw `meta.usage`. Unrecognized totals stay unknown.
The checked dsh client advertises no comparable command, so its normalized tokens remain unavailable.
Antigravity's usage availability has not been verified. Legacy records without these fields remain
readable; their missing telemetry stays unknown.

## Model fields

| Field | Meaning |
|---|---|
| `backend` | `codex`, `claude`, `acp`, or `openai` |
| `vendor` | Used to keep judges from scoring their own vendor's models |
| `model` | Model id passed to the backend |
| `label` | Display name in the results site (defaults to the model entry name) |
| `can` | Any of `text`, `vision` (accepts images), `image` (generates images) |
| `effort` | Reasoning level, or `default` when no graded control is exposed |
| `reasoning` | Legacy Codex alias for `effort` |
| `effort_option` | ACP option id for effort (e.g. `reasoning_effort` or `thinking`) |
| `effort_source` | `model-id` when effort is encoded in the model id |
| `tool_profile` | Codex only: versioned `legacy-v1` or `isolated-v1` text/vision command configuration |
| `command`, `env` | ACP only: agent command and extra environment; `~`, `${VAR}`, and `${NWB_ROOT}` (repository root) are expanded |
| `config` | ACP only: session config options to set, as `{ id = "value" }` |
| `usage_command` | ACP only: opt-in advertised local command for session token totals (currently Kimi `/usage`) |
| `auth` | ACP only: an auth method id to call `authenticate` with before each session |
| `base_url`, `api_key_env` | OpenAI only: API base URL (ending in `/v1`) and the environment variable holding the key |
| `cc_switch` | OpenAI only: name of a [CC Switch](https://github.com/farion1231/cc-switch) provider to take the base URL and key from |
| `timeout` | Seconds per call (default 600) |

## Codex (`backend = "codex"`)

Runs `codex exec --json` with the ChatGPT login from `codex login` (respects `CODEX_HOME`). The harness
passes `--ignore-user-config`, `--sandbox read-only`, and `web_search="disabled"`, and turns off the `apps`
feature (whose connector has its own web search), browser use, and computer use. Image generation is
disabled for text calls.

**Isolation limitation.** `--ignore-user-config` does not prevent Codex from loading global instructions (`$CODEX_HOME/AGENTS.md`) and installed skills. A fresh working directory excludes repository context, but does not make Codex calls context-free. Use a dedicated, logged-in `CODEX_HOME` without personal instructions or skills for a clean benchmark. Earlier smoke samples used the normal user home.

**Image generation** (`can = ["image"]`) uses Codex's built-in `image_gen` tool. The chat model is told to
pass the benchmark prompt to the tool verbatim; images are copied from
`$CODEX_HOME/generated_images/<thread>/`. The harness then reads the session rollout
(`$CODEX_HOME/sessions/**/rollout-*-<thread>.jsonl`) and records in `meta.audit` how many `image_gen` calls
were made and whether each received the prompt unchanged. Reference-tier prompts attach the reference image
with `--image`.

When the image tool's result reports `moderation_blocked`, the provider's safety system rejected the
request or its output. The sample is then recorded with `refused` and no images instead of an error.
A refusal is a model outcome: it is not retried automatically (`--force` regenerates it), and when its
prompt audit is verbatim it scores 0 in the ranking panel.

### Codex tool profiles

`tool_profile="legacy-v1"` preserves the original text/vision command: web search plus the `apps`,
`browser_use`, `browser_use_external`, and `computer_use` features are disabled, along with image
generation for understanding/judge calls. Shell, image-viewing, and agent features remain available;
attempted tool use still contaminates an understanding answer.

`tool_profile="isolated-v1"` adds these eleven disabled features for text/vision calls:
`shell_tool`, `unified_exec`, `multi_agent`, `multi_agent_v2`, `plugins`, `skill_search`, `goals`,
`sleep_tool`, `view_image`, `collaboration_modes`, and `default_mode_request_user_input`.
The flags follow the effort argument and precede neutral image attachments, matching the retained
isolated collection commands. Generation relays retain their image-tool configuration in either profile.

The profile is reflected in the command fingerprint. The retained Sol/Astra baseline uses `legacy-v1`;
Terra and GPT-5.6-Sol rows use `isolated-v1`. Reports identify these conditions per row and in collection
metadata. These historical rows do not constitute a uniform collection protocol; see
[the selected comparison](releases.md#selected-comparison). To collect a controlled comparison, select
the same profile for its subject configurations and use a new run name. Individual legacy executable
paths and current environment-variable command templates can also produce different settings IDs.

## Claude (`backend = "claude"`)

Runs `claude -p` with the Claude Code login. Tools, MCP servers, and settings sources are disabled, and the
coding-agent system prompt is replaced with a neutral one. Images are sent as content blocks via
`--input-format stream-json`. Text and vision only.

## ACP agents (`backend = "acp"`)

Any agent that speaks the [Agent Client Protocol](https://agentclientprotocol.com) over stdio. The client
sends `initialize`, optional `authenticate`, `session/new`, sets `model` and `config` options through
`session/set_config_option` (or `session/set_model` for agents that only offer that), then
`session/prompt`. It offers no file system or terminal capabilities. Permission requests are rejected for
text and vision prompts and approved for image generation.

For image generation the client collects images returned inline in tool results, files written to the
session directory, and image paths mentioned in tool calls, dropping duplicates and copies of the input
images. Tool calls whose title or kind mentions "image" are audited for the verbatim prompt, as with Codex.

Some agents run tools without asking permission, so every tool call is recorded in `meta.tools_used`;
understanding answers with any tool call are marked `contaminated` and not scored. Disable tools in the
agent itself where possible:

- **DeepSeek Harness** (`dsh`): `config/dsh-no-tools.patch.yml` is applied with `--patch` and disables the
  web, shell, file, working-directory, skill, subagent, todo, goal, and plan-mode plugins. New dsh releases
  can add tool plugins; after upgrading, check the composed tree with `--dump-config` and extend the patch.
  The ACP agent accepts images only when its default model takes image input, whatever model the session
  selects, so `deepseek-v4.1-flash` also applies `config/dsh-flash-default.patch.yml`. DeepSeek-V4-Pro is
  text-only.
- **Kimi Code** (`kimi acp`): `config = { mode = "default" }` makes every tool call ask for approval, which
  the harness rejects for understanding prompts. Plan mode is unsuitable: K3 drafts a plan and repeatedly
  tries to leave plan mode or ask the user a question, until the call times out.
  Vision calls can be slow and occasionally hang until the timeout; rerun to retry. The agent needs access
  to `api.kimi.com`; where that host is blocked it ends every turn without text.

The initialized agent name and version are saved in `meta.client`; generated images are inspected for vendor-declared `meta.c2pa` provenance without signature verification.

### Antigravity (Gemini)

Antigravity's ACP server is not on `PATH`. Point the Gemini entries at it with two environment variables
(or override `command`/`env` in `models.local.toml`):

- `NWB_AGY_ACP`: the `agy_acp_server` executable. T3 Code installs one under
  `~/.t3/tools/antigravity-acp/<platform>/versions/<release>/agy_acp_server.par`.
- `NWB_AGY_HOME`: a Gemini home directory (`GEMINI_HOME`) holding `antigravity-acp/settings.json` with
  `{"auth": {"type": "oauth-personal"}}` and a saved login. The directory T3 Code's Antigravity provider
  has already logged in, `~/.t3/userdata/providers/antigravity/<id>/`, works.

The server needs access to `cloudcode-pa.googleapis.com`. Where that host is blocked, sessions fail with
`EOF occurred in violation of protocol`; route it through a working proxy first.

`gemini-image` uses Antigravity's built-in `generate_image` tool; reference-tier calls pass the attached
reference image to it as an input path.

## OpenAI-compatible APIs (`backend = "openai"`)

Sends one Chat Completions request (`POST {base_url}/chat/completions`) with a neutral system prompt, the
prompt, and images as base64 data URLs. No tools are offered, so this is a plain model call. Rate limits and
server errors are retried with backoff. Text and vision only.

Credentials come from `base_url` plus the `api_key_env` environment variable, or from `cc_switch`: the
named provider's pi or codex configuration in CC Switch's database (`~/.cc-switch/cc-switch.db`, or
`CC_SWITCH_DB`), read at run time so the key is never copied into this repository. Explicit `base_url` and
`api_key_env` override the CC Switch values.

The Xiaomi MiMo entries use the CC Switch provider `Xiaomi MiMo Token Plan`. The Token Plan endpoint serves
`mimo-v2.6-pro` and `mimo-v2.6-flash`, both of which accept images.

[MiMo's API reference](https://mimo.mi.com/docs/en-US/api/chat/openai-api) documents
`thinking.type=enabled|disabled`, enabled by default, with no graded reasoning-effort parameter.
MiMo entries therefore use `effort="default"`; the harness sends no speculative effort parameter.

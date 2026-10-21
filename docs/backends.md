# Backends and models

English | [简体中文](backends.zh-CN.md) | [繁體中文](backends.zh-Hant.md)

Most models run through agent CLIs that are already installed and logged in on your machine, so the
benchmark uses existing subscriptions; the `openai` backend calls an OpenAI-compatible API with a key.
Models are configured in `models.toml`; put machine-specific paths or extra models in `models.local.toml`
(git-ignored), which is merged per model.

Every agent call starts in a fresh, empty temporary directory so agents never load this repository's
`AGENTS.md`/`CLAUDE.md` or other project context.

Every sample records `meta.client`: the CLI name and version, ACP `agentInfo` name and version, or API host. Image samples also record `meta.c2pa`, the vendor-declared generators and action descriptions read from C2PA content credentials without verifying signatures. Missing credentials are recorded as `null`.

## Model fields

| Field | Meaning |
|---|---|
| `backend` | `codex`, `claude`, `acp`, or `openai` |
| `vendor` | Used to keep judges from scoring their own vendor's models |
| `model` | Model id passed to the backend |
| `label` | Display name in the results site (defaults to the model entry name) |
| `can` | Any of `text`, `vision` (accepts images), `image` (generates images) |
| `reasoning` | Codex only: `model_reasoning_effort` |
| `effort` | Claude only: `--effort` level |
| `command`, `env` | ACP only: agent command and extra environment; `~`, `${VAR}`, and `${NWB_ROOT}` (repository root) are expanded |
| `config` | ACP only: session config options to set, as `{ id = "value" }` |
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
  web, shell, file, skill, and subagent plugins. The ACP agent does not accept images.
- **Kimi Code** (`kimi acp`): `config = { mode = "plan" }` starts sessions in plan mode, which runs no tools.
  Vision calls can be slow and occasionally hang until the timeout; rerun to retry.

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

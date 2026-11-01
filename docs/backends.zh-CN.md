# 后端与模型

[English](backends.md) | 简体中文 | [繁體中文](backends.zh-Hant.md)

大多数模型通过本机已安装并已登录的 Agent CLI 运行，因此基准使用的是现有订阅；`openai` 后端则用 API 密钥
调用 OpenAI 兼容接口。模型在 `models.toml` 中配置；本机特有的路径或额外的模型请写在 `models.local.toml`
（已被 git 忽略）中，它会按模型逐项合并。

每次 Agent 调用都在一个全新的空临时目录中进行，因此 Agent 不会读取本仓库的 `AGENTS.md`/`CLAUDE.md`
或其他项目上下文。

每个样本都会记录 `meta.client`：CLI 名称和版本、ACP `agentInfo` 中的名称和版本，或 API 主机名。图像样本还会记录 `meta.c2pa`，从 C2PA 内容凭证中读取厂商声明的生成器和操作描述，不验证签名。没有凭证时记录为 `null`。

理解题的回答为空时会记录为错误，并在下次运行时重试。部分 ACP Agent 在无法连上自己的 API 时，会不输出任何文字就结束回合。

## 模型字段

| 字段 | 含义 |
|---|---|
| `backend` | `codex`、`claude`、`acp` 或 `openai` |
| `vendor` | 用于避免评审给自家厂商的模型打分 |
| `model` | 传给后端的模型 id |
| `label` | 结果网站中的显示名称（默认使用模型条目名） |
| `can` | 可包含 `text`、`vision`（接受图片输入）、`image`（生成图片） |
| `reasoning` | 仅 Codex：`model_reasoning_effort` |
| `effort` | 仅 Claude：`--effort` 等级 |
| `command`、`env` | 仅 ACP：Agent 命令和额外的环境变量；会展开 `~`、`${VAR}` 和 `${NWB_ROOT}`（仓库根目录） |
| `config` | 仅 ACP：要设置的会话配置项，格式为 `{ id = "value" }` |
| `auth` | 仅 ACP：每次会话前调用 `authenticate` 所用的认证方式 id |
| `base_url`、`api_key_env` | 仅 OpenAI：API 基础地址（以 `/v1` 结尾）和存放密钥的环境变量名 |
| `cc_switch` | 仅 OpenAI：从哪个 [CC Switch](https://github.com/farion1231/cc-switch) 供应商读取基础地址和密钥 |
| `timeout` | 每次调用的超时秒数（默认 600） |

## Codex（`backend = "codex"`）

使用 `codex login` 的 ChatGPT 登录运行 `codex exec --json`（遵循 `CODEX_HOME`）。评测程序会传入
`--ignore-user-config`、`--sandbox read-only` 和 `web_search="disabled"`，并关闭 `apps` 功能（其连接器
自带网络搜索）、浏览器操作和电脑操作。文本调用时还会关闭图像生成。

**隔离限制。** `--ignore-user-config` 无法阻止 Codex 加载全局指令（`$CODEX_HOME/AGENTS.md`）和已安装的技能。全新的工作目录能排除仓库上下文，但不能完全清除 Codex 的上下文。需要干净的评测环境时，请使用专用、已登录且不含个人指令和技能的 `CODEX_HOME`。早期试跑样本使用了普通用户目录。

**图像生成**（`can = ["image"]`）使用 Codex 内置的 `image_gen` 工具。对话模型会被要求把基准提示词原样
交给该工具；图片从 `$CODEX_HOME/generated_images/<thread>/` 复制出来。之后评测程序读取会话记录
（`$CODEX_HOME/sessions/**/rollout-*-<thread>.jsonl`），在 `meta.audit` 中记录 `image_gen` 的调用次数，
以及每次调用收到的提示词是否未被改动。`reference` 档位的提示词会用 `--image` 附上原图。

如果图像工具的结果报告 `moderation_blocked`，说明服务商的安全系统拒绝了请求或生成结果。此时样本记录为 `refused`，不含图片，而不是记录为错误。拒绝生成属于模型的结果：不会自动重试（`--force` 会重新生成），且只要提示词核对为原样传递，它在排名题组中记 0 分。

## Claude（`backend = "claude"`）

使用 Claude Code 登录运行 `claude -p`。工具、MCP 服务器和设置来源都会被禁用，编程 Agent 的系统提示词
也会被替换为中性的提示词。图片通过 `--input-format stream-json` 以内容块形式发送。仅支持文本和视觉。

## ACP Agent（`backend = "acp"`）

任何通过 stdio 使用 [Agent Client Protocol](https://agentclientprotocol.com) 的 Agent。客户端依次发送
`initialize`、可选的 `authenticate`、`session/new`，通过 `session/set_config_option`（对只支持旧接口的
Agent 则用 `session/set_model`）设置 `model` 和 `config` 选项，然后发送 `session/prompt`。客户端不提供
文件系统或终端能力。文本和视觉提示词的权限请求一律拒绝，图像生成的权限请求则予以批准。

图像生成时，客户端会收集工具结果中内联返回的图片、写入会话目录的文件，以及工具调用中提到的图片路径，
并去掉重复图片和输入图片的副本。标题或类型中含 “image” 的工具调用会像 Codex 一样检查提示词是否被原样
传递。

有些 Agent 不经请求就会运行工具，所以每次工具调用都会记录在 `meta.tools_used` 中；任何调用了工具的
理解类回答都会被标记为 `contaminated`，不参与计分。尽量在 Agent 内部直接禁用工具：

- **DeepSeek Harness**（`dsh`）：通过 `--patch` 应用 `config/dsh-no-tools.patch.yml`，禁用网络、shell、
  文件、工作目录、技能、子 Agent、待办、目标和计划模式插件。dsh 新版本可能新增工具插件；升级后用
  `--dump-config` 检查合成后的配置树并补充该 patch。无论会话选择哪个模型，该 ACP Agent 只在默认模型支持
  图片输入时才接受图片，因此
  `deepseek-v4.1-flash` 还会应用 `config/dsh-flash-default.patch.yml`。DeepSeek-V4-Pro 仅支持文本。
- **Kimi Code**（`kimi acp`）：`config = { mode = "default" }` 让每次工具调用都需要批准，而评测程序在理解题中
  会拒绝批准。计划模式不适用：K3 会先起草计划，再反复尝试退出计划模式或向用户提问，直到调用超时。
  视觉调用可能较慢，偶尔会卡住直到超时；重新运行即可重试。Agent 需要访问 `api.kimi.com`；该主机被屏蔽时，
  它每个回合都不输出任何文字。

初始化得到的 Agent 名称和版本保存在 `meta.client` 中；生成的图片会被检查，以记录厂商声明的 `meta.c2pa` 来源信息，不验证签名。

### Antigravity（Gemini）

Antigravity 的 ACP 服务器不在 `PATH` 中。请用两个环境变量让 Gemini 相关条目指向它（或在
`models.local.toml` 中覆盖 `command`/`env`）：

- `NWB_AGY_ACP`：`agy_acp_server` 可执行文件。T3 Code 会把它安装在
  `~/.t3/tools/antigravity-acp/<platform>/versions/<release>/agy_acp_server.par`。
- `NWB_AGY_HOME`：一个 Gemini 主目录（`GEMINI_HOME`），其中包含内容为 `{"auth": {"type": "oauth-personal"}}`
  的 `antigravity-acp/settings.json` 和已保存的登录信息。T3 Code 的 Antigravity 供应商已登录的目录
  `~/.t3/userdata/providers/antigravity/<id>/` 可以直接使用。

服务器需要能访问 `cloudcode-pa.googleapis.com`。如果该域名被屏蔽，会话会报错
`EOF occurred in violation of protocol`；请先让它走可用的代理。

`gemini-image` 使用 Antigravity 内置的 `generate_image` 工具；`reference` 档位的调用会把附带的原图作为
输入路径传给它。

## OpenAI 兼容 API（`backend = "openai"`）

发送一次 Chat Completions 请求（`POST {base_url}/chat/completions`），内容包括中性的系统提示词、提示词，
以及以 base64 data URL 形式附带的图片。不提供任何工具，所以这是一次单纯的模型调用。遇到限流和服务器
错误时会退避重试。仅支持文本和视觉。

凭据来自 `base_url` 加上 `api_key_env` 指定的环境变量，或来自 `cc_switch`：运行时从 CC Switch 数据库
（`~/.cc-switch/cc-switch.db`，或 `CC_SWITCH_DB`）读取指定供应商的 pi 或 codex 配置，因此密钥永远不会被
复制进本仓库。显式设置的 `base_url` 和 `api_key_env` 会覆盖 CC Switch 中的值。

小米 MiMo 条目使用 CC Switch 供应商 `Xiaomi MiMo Token Plan`。Token Plan 接口提供 `mimo-v2.6-pro` 和
`mimo-v2.6-flash`，两者都接受图片输入。

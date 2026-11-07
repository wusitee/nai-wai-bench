# 後端與模型

[English](backends.md) | [简体中文](backends.zh-CN.md) | 繁體中文

大多數模型透過本機已安裝並已登入的 Agent CLI 執行，因此基準使用的是現有訂閱或 CLI 自己的供應商設定：
Codex、Claude Code（也可接入其他供應商的 Anthropic 相容介面）、pi 和 ACP Agent。`openai` 後端則以 API 密鑰
呼叫 OpenAI 相容介面。模型在 `models.toml` 中設定；本機特有的路徑或額外的模型請寫在 `models.local.toml`
（已被 git 忽略）中，它會按模型逐項合併。

每次 Agent 呼叫都在一個全新的空白暫存目錄中進行，因此 Agent 不會讀取本儲存庫的 `AGENTS.md`/`CLAUDE.md`
或其他專案脈絡。

每個樣本都會記錄 `meta.client`：CLI 名稱和版本、ACP `agentInfo` 中的名稱和版本，或 API 主機名稱。圖像樣本另會記錄 `meta.c2pa`，從 C2PA 內容憑證讀取廠商聲明的生成器和操作描述，不驗證簽章。沒有憑證時記錄為 `null`。

理解題的回答為空時會記錄為錯誤，並在下次執行時重試。部分 ACP Agent 在無法連上自己的 API 時，會不輸出任何文字就結束回合。

## 收集設定與中繼資料

`effort` 是各後端共用的設定：Codex 設定 `model_reasoning_effort`，Claude 傳入 `--effort`，pi 傳入
`--thinking`，ACP 設定其公布的工作階段選項（由 `effort_option` 指定，否則使用 `thought_level` 類別）。
`default` 不設定用戶端的 effort 控制；`effort_source = "model-id"` 表示等級包含在模型 id 中。
ACP 或 pi 無法設定或確認請求的等級時呼叫失敗；API 不支援 effort 控制時也會失敗。

樣本和評審記錄儲存 `settings`、`settings_id`、UTC 收集時間、原始碼修訂和版本。指令或設定改變後，
已成功的記錄不能自動覆寫，必須選擇新的執行或明確使用 `--force`。token、快取、用戶端耗時和費用的
記錄規則，以及 Kimi 的可選 `/usage` 指令，見[英文中繼資料說明](backends.md#collection-settings-and-metadata)。

## 模型欄位

| 欄位 | 含義 |
|---|---|
| `backend` | `codex`、`claude`、`pi`、`acp` 或 `openai` |
| `vendor` | 用於避免評審為自家廠商的模型評分 |
| `model` | 傳給後端的模型 id（pi：`provider/id`） |
| `label` | 結果網站中的顯示名稱（預設使用模型條目名稱） |
| `can` | 可包含 `text`、`vision`（接受圖片輸入）、`image`（生成圖片） |
| `effort` | 推理等級；未提供控制時使用 `default` |
| `reasoning` | Codex 的舊版 `effort` 別名 |
| `effort_option` | ACP 的 effort 選項 id，如 `reasoning_effort` 或 `thinking` |
| `effort_source` | 等級包含在模型 id 中時為 `model-id` |
| `tool_profile` | 僅限 Codex：`legacy-v1` 或 `isolated-v1` 文字／視覺指令設定 |
| `command` | 僅限 ACP：Agent 指令；會展開 `~`、`${VAR}` 和 `${NWB_ROOT}`（儲存庫根目錄） |
| `env` | ACP、Claude 和 pi：額外的環境變數，展開方式同 `command`；只記錄變數名稱 |
| `config` | 僅限 ACP：要設定的工作階段選項，格式為 `{ id = "value" }` |
| `usage_command` | 僅限 ACP：明確啟用用戶端公布的本機 token 用量指令，目前為 Kimi `/usage` |
| `auth` | 僅限 ACP：每次工作階段前呼叫 `authenticate` 所用的驗證方式 id |
| `base_url`、`api_key_env` | 僅限 OpenAI：API 基礎網址（以 `/v1` 結尾）和存放密鑰的環境變數名稱 |
| `cc_switch` | OpenAI 和 Claude：從哪個 [CC Switch](https://github.com/farion1231/cc-switch) 供應商讀取介面網址和密鑰 |
| `timeout` | 每次呼叫的逾時秒數（預設 600） |

## Codex（`backend = "codex"`）

使用 `codex login` 的 ChatGPT 登入執行 `codex exec --json`（遵循 `CODEX_HOME`）。評測程式會傳入
`--ignore-user-config`、`--sandbox read-only` 和 `web_search="disabled"`，並關閉 `apps` 功能（其連接器
自帶網絡搜尋）、瀏覽器操作和電腦操作。文字呼叫時還會關閉圖像生成。

**隔離限制。** `--ignore-user-config` 無法阻止 Codex 載入全域指令（`$CODEX_HOME/AGENTS.md`）及已安裝的技能。全新的工作目錄能排除儲存庫脈絡，但無法完全清除 Codex 的脈絡。需要乾淨的評測環境時，請使用專用、已登入且不含個人指令和技能的 `CODEX_HOME`。早期試跑樣本使用了普通使用者目錄。

`tool_profile = "legacy-v1"` 保留原始文字／視覺指令，shell、圖片檢視和 Agent 功能仍可用；
理解回答中的工具呼叫仍會使樣本失去計分資格。`isolated-v1` 另外關閉這些功能以及外掛、技能搜尋、
目標、等待和互動模式功能。圖像生成中轉不受該區別影響。完整開關列表見
[英文工具設定說明](backends.md#codex-tool-profiles)。
目前發佈的比較混用了兩種設定，模型與收集器的影響無法分離；逐列標籤會顯示設定。
受控比較應使用相同設定和新的執行名稱，見[發佈條件](releases.md#selected-comparison)。

**圖像生成**（`can = ["image"]`）使用 Codex 內建的 `image_gen` 工具。對話模型會被要求把基準提示詞原樣
交給該工具；圖片從 `$CODEX_HOME/generated_images/<thread>/` 複製出來。之後評測程式讀取工作階段記錄
（`$CODEX_HOME/sessions/**/rollout-*-<thread>.jsonl`），在 `meta.audit` 中記錄 `image_gen` 的呼叫次數，
以及每次呼叫收到的提示詞是否未被改動。`reference` 檔位的提示詞會用 `--image` 附上原圖。

該工具沒有模型參數：Codex（至少到 0.168 預發佈版）請求的都是 `gpt-image-2`，背後實際用哪個圖像模型由 OpenAI 服務決定。
工具結果和圖片的 C2PA 憑證（`ChatGPT` / `gpt-image`）都不寫實際模型或變體，因此圖像模型的版本只能按採集日期和
Codex 版本（`meta.client`）區分。

如果圖像工具的結果回報 `moderation_blocked`，表示服務商的安全系統拒絕了請求或生成結果。此時樣本記錄為 `refused`，不含圖片，而不是記錄為錯誤。拒絕生成屬於模型的結果：不會自動重試（`--force` 會重新生成），且只要提示詞核對為原樣傳遞，它在排名題組中記 0 分。

## Claude（`backend = "claude"`）

使用 Claude Code 登入執行 `claude -p`。工具、MCP 伺服器和設定來源都會被停用，程式設計 Agent 的系統提示詞
也會被替換為中性的提示詞。圖片透過 `--input-format stream-json` 以內容區塊形式傳送。僅支援文字和視覺。

### 透過 Claude Code 執行其他供應商的模型

Claude Code 可以透過 Anthropic 相容介面執行其他供應商的模型。由於設定來源已被停用，介面必須寫在模型條目中：
以 `env` 設定 `ANTHROPIC_BASE_URL` 和密鑰變數，或以 `cc_switch` 讀取 CC Switch 中 Claude Code 供應商的環境
變數。明確的 `env` 會覆寫 CC Switch 中的值。`model` 傳給 `--model`，必須是該供應商的模型 id。範例見
[英文文件](backends.md#other-providers-through-claude-code)。

條目設定了 `ANTHROPIC_BASE_URL` 時，必須同時提供 `ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_API_KEY`，否則呼叫失敗，
因為 Claude Code 會退回使用自己的登入。繼承來的 `ANTHROPIC_*` 環境變數和 `CLAUDE_CODE_OAUTH_TOKEN` 會被移除，
Anthropic 憑證不會傳給其他供應商。設定中只記錄介面主機名稱、CC Switch 供應商名稱和環境變數名稱，不記錄變數值；也不保留 Claude Code
依 Anthropic 價格估算的費用。除非供應商說明支援 Claude Code 的 effort 控制，否則請使用 `effort = "default"`。
請把 `vendor` 設為模型的實際廠商。

## pi（`backend = "pi"`）

以 RPC 模式（`pi --mode rpc`）執行 [pi 程式設計 Agent](https://github.com/earendil-works/pi)（`@earendil-works/pi-coding-agent`），
使用 pi 的訂閱登入、API 密鑰環境變數，以及 `~/.pi/agent/models.json`（或 `PI_CODING_AGENT_DIR`）中的自訂
供應商，因此可以接入 pi 支援的任何供應商，包括本機的 OpenAI 相容服務。工作階段不會儲存；工具、擴充功能（包括
pi 內建的 MCP 支援）、技能、提示詞範本、佈景主題、上下文檔案和自動連網（如模型目錄更新）都會被停用；系統提示詞
替換為中性的提示詞，不載入全域 `SYSTEM.md` 和 `APPEND_SYSTEM.md`，pi 仍會在其中附上暫存工作目錄。pi 的自動重試會關閉，因為 pi 在重試前就結束了本輪。服務商的限流錯誤（HTTP 429）改為依服務商給出的重試等待時間（最長不超過該呼叫的 `timeout`；沒有提示時依序等 5、10、20… 秒，最多 120 秒）在新工作階段中重送，最多六次；以其他 HTTP 狀態碼開頭的錯誤不重試；`meta.rate_limit_retries` 記錄重送次數，`meta.seconds` 只計最後一次。其他失敗的樣本在下次執行時重試。僅支援
文字和視覺。

`model` 必須精確寫成 `provider/id` 或 `id`。pi 找不到模型時會改用其他模型，遇到不支援的思考等級會自動降級，
且都不報錯，所以評測程式在傳送提示詞前會讀取工作階段狀態；所選模型、思考等級或圖片輸入能力與請求不符時呼叫失敗。
pi 模型目錄中沒有的 id 會沿用該供應商預設模型的能力，請在 pi 的 `models.json` 中宣告它，使圖片輸入和推理
能力準確。`effort` 可取 `off`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`，或以 `default` 保留
pi 設定的等級；實際等級記錄在 `meta.session_config`。如需乾淨、可重現的設定，可用
`env = { PI_CODING_AGENT_DIR = "~/.pi-nwb" }` 指向專用且已登入的 pi 目錄。

### TokenRhythm（`egg-alpha`）

`egg-alpha` 是 TokenRhythm 路由上一個未公開來源的預覽模型。它的 Chat Completions 介面接受圖片和
`reasoning_effort`，Anthropic 介面則不提供該模型。該條目使用 `PI_CODING_AGENT_DIR=~/.pi-nwb`，在其中的
`models.json` 宣告供應商；`apiKey` 可以是明文、`$NAME` 或 `!command`：

```json
{
  "providers": {
    "tokenrhythm": {
      "baseUrl": "https://tokenrhythm.studio/v1",
      "api": "openai-completions",
      "apiKey": "$TOKENRHYTHM_API_KEY",
      "compat": { "thinkingFormat": "openai", "supportsReasoningEffort": true,
                  "supportsDeveloperRole": false, "supportsStore": false },
      "models": [{ "id": "egg-alpha", "reasoning": true, "input": ["text", "image"],
                   "contextWindow": 1000000, "maxTokens": 128000,
                   "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 } }]
    }
  }
}
```

設定 `thinkingFormat = "openai"` 後，pi 會把思考等級作為 `reasoning_effort` 傳送，因此 `effort = "high"`
生效。該路由對突發請求限流，回傳 HTTP 429（`MODEL_CALL_FAILED`，附 `retryAfterSeconds`），所以請用
`--jobs 1` 採集。

### 智譜 GLM（`glm-5.3-flash-pi`）

`glm-5.3-flash-pi` 透過 pi 內建的 `zai-coding-cn` 供應商（open.bigmodel.cn 的 GLM Coding Plan 介面，金鑰
讀取 `ZAI_CODING_CN_API_KEY`）執行 GLM-5.3-Flash，無須在 `models.json` 中宣告。在該供應商的模型目錄
中，GLM-5.3 系列只有 GLM-5.3-Flash 支援圖片輸入；`effort = "high"` 會作為 `reasoning_effort: "high"` 傳送。部分視覺
提示詞會讓模型陷入很長且不收斂的推理；該條目每次呼叫最多等待 900 秒，逾時的樣本會在下次執行時重試。

## ACP Agent（`backend = "acp"`）

任何透過 stdio 使用 [Agent Client Protocol](https://agentclientprotocol.com) 的 Agent。用戶端依序傳送
`initialize`、可選的 `authenticate`、`session/new`，透過 `session/set_config_option`（對只支援舊介面的
Agent 則用 `session/set_model`）設定 `model` 和 `config` 選項，然後傳送 `session/prompt`。用戶端不提供
檔案系統或終端機能力。文字和視覺提示詞的權限請求一律拒絕，圖像生成的權限請求則予以批准。

圖像生成時，用戶端會收集工具結果中內嵌回傳的圖片、寫入工作階段目錄的檔案，以及工具呼叫中提到的圖片路徑，
並去除重複圖片和輸入圖片的副本。標題或類型中含「image」的工具呼叫會像 Codex 一樣檢查提示詞是否被原樣
傳遞。

有些 Agent 不經請求就會執行工具，所以每次工具呼叫都會記錄在 `meta.tools_used` 中；任何呼叫了工具的
理解類回答都會被標記為 `contaminated`，不參與計分。盡量在 Agent 內部直接停用工具：

- **DeepSeek Harness**（`dsh`）：透過 `--patch` 套用 `config/dsh-no-tools.patch.yml`，停用網絡、shell、
  檔案、工作目錄、技能、子 Agent、待辦、目標和計畫模式外掛。dsh 新版本可能新增工具外掛；升級後用
  `--dump-config` 檢查合成後的設定樹並補充該 patch。無論工作階段選擇哪個模型，該 ACP Agent 只在預設模型支援
  圖片輸入時才接受圖片，因此
  `deepseek-v4.1-flash` 還會套用 `config/dsh-flash-default.patch.yml`。DeepSeek-V4-Pro 僅支援文字。
  dsh 會為每張圖片附上 SHA-256 和 dsh 主目錄下依內容定址的副本路徑，並追加一則說明暫存工作目錄和檔案策略的
  執行階段上下文訊息。

  智譜 GLM 模型透過 `config/dsh-glm.patch.yml` 中 dsh 的 pi-ai 路由執行：`zai-coding-cn`（open.bigmodel.cn，
  密鑰放在 `ZAI_CODING_CN_API_KEY`）和 `zai`（api.z.ai，密鑰放在 `ZAI_API_KEY`），兩者的模型目錄都指向
  GLM Coding Plan 介面。`glm-5.3`（僅文字）和 `glm-5.3-flash`（接受圖片，另套用
  `config/dsh-glm-flash-default.patch.yml`）條目使用 `zai-coding-cn`。
- **Kimi Code**（`kimi acp`）：`config = { mode = "default" }` 讓每次工具呼叫都需要批准，而評測程式在理解題中
  會拒絕批准。規劃模式不適用：K3 會先草擬計劃，再反覆嘗試退出規劃模式或向使用者提問，直到呼叫逾時。
  視覺呼叫可能較慢，偶爾會卡住直到逾時；重新執行即可重試。Agent 需要存取 `api.kimi.com`；該主機被封鎖時，
  它每個回合都不輸出任何文字。

初始化取得的 Agent 名稱和版本儲存在 `meta.client` 中；生成的圖片會被檢查，以記錄廠商聲明的 `meta.c2pa` 來源資訊，不驗證簽章。

### Antigravity（Gemini）

Antigravity 的 ACP 伺服器不在 `PATH` 中。請用兩個環境變數讓 Gemini 相關項目指向它（或在
`models.local.toml` 中覆寫 `command`/`env`）：

- `NWB_AGY_ACP`：`agy_acp_server` 執行檔。T3 Code 會把它安裝在
  `~/.t3/tools/antigravity-acp/<platform>/versions/<release>/agy_acp_server.par`。
- `NWB_AGY_HOME`：一個 Gemini 主目錄（`GEMINI_HOME`），其中包含內容為 `{"auth": {"type": "oauth-personal"}}`
  的 `antigravity-acp/settings.json` 和已儲存的登入資料。T3 Code 的 Antigravity 供應商已登入的目錄
  `~/.t3/userdata/providers/antigravity/<id>/` 可以直接使用。

伺服器需要能存取 `cloudcode-pa.googleapis.com`。如果該網域被封鎖，工作階段會報錯
`EOF occurred in violation of protocol`；請先讓它經過可用的代理。

`gemini-image` 使用 Antigravity 內建的 `generate_image` 工具；`reference` 檔位的呼叫會把附帶的原圖作為
輸入路徑傳給它。

## OpenAI 相容 API（`backend = "openai"`）

傳送一次 Chat Completions 請求（`POST {base_url}/chat/completions`），內容包括中性的系統提示詞、提示詞，
以及以 base64 data URL 形式附帶的圖片。不提供任何工具，所以這是一次單純的模型呼叫。遇到流量限制和伺服器
錯誤時會退避重試。僅支援文字和視覺。

憑證來自 `base_url` 加上 `api_key_env` 指定的環境變數，或來自 `cc_switch`：執行時從 CC Switch 資料庫
（`~/.cc-switch/cc-switch.db`，或 `CC_SWITCH_DB`）讀取指定供應商的 pi 或 codex 設定，因此密鑰永遠不會被
複製進本儲存庫。明確設定的 `base_url` 和 `api_key_env` 會覆寫 CC Switch 中的值。

小米 MiMo 項目使用 CC Switch 供應商 `Xiaomi MiMo Token Plan`。Token Plan 介面提供 `mimo-v2.6-pro` 和
`mimo-v2.6-flash`，兩者都接受圖片輸入。

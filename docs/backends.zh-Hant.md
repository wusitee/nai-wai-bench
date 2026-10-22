# 後端與模型

[English](backends.md) | [简体中文](backends.zh-CN.md) | 繁體中文

大多數模型透過本機已安裝並已登入的 Agent CLI 執行，因此基準使用的是現有訂閱；`openai` 後端則以 API 密鑰
呼叫 OpenAI 相容介面。模型在 `models.toml` 中設定；本機特有的路徑或額外的模型請寫在 `models.local.toml`
（已被 git 忽略）中，它會按模型逐項合併。

每次 Agent 呼叫都在一個全新的空白暫存目錄中進行，因此 Agent 不會讀取本儲存庫的 `AGENTS.md`/`CLAUDE.md`
或其他專案脈絡。

每個樣本都會記錄 `meta.client`：CLI 名稱和版本、ACP `agentInfo` 中的名稱和版本，或 API 主機名稱。圖像樣本另會記錄 `meta.c2pa`，從 C2PA 內容憑證讀取廠商聲明的生成器和操作描述，不驗證簽章。沒有憑證時記錄為 `null`。

理解題的回答為空時會記錄為錯誤，並在下次執行時重試。部分 ACP Agent 在無法連上自己的 API 時，會不輸出任何文字就結束回合。

## 模型欄位

| 欄位 | 含義 |
|---|---|
| `backend` | `codex`、`claude`、`acp` 或 `openai` |
| `vendor` | 用於避免評審為自家廠商的模型評分 |
| `model` | 傳給後端的模型 id |
| `label` | 結果網站中的顯示名稱（預設使用模型條目名稱） |
| `can` | 可包含 `text`、`vision`（接受圖片輸入）、`image`（生成圖片） |
| `reasoning` | 僅限 Codex：`model_reasoning_effort` |
| `effort` | 僅限 Claude：`--effort` 等級 |
| `command`、`env` | 僅限 ACP：Agent 指令和額外的環境變數；會展開 `~`、`${VAR}` 和 `${NWB_ROOT}`（儲存庫根目錄） |
| `config` | 僅限 ACP：要設定的工作階段選項，格式為 `{ id = "value" }` |
| `auth` | 僅限 ACP：每次工作階段前呼叫 `authenticate` 所用的驗證方式 id |
| `base_url`、`api_key_env` | 僅限 OpenAI：API 基礎網址（以 `/v1` 結尾）和存放密鑰的環境變數名稱 |
| `cc_switch` | 僅限 OpenAI：從哪個 [CC Switch](https://github.com/farion1231/cc-switch) 供應商讀取基礎網址和密鑰 |
| `timeout` | 每次呼叫的逾時秒數（預設 600） |

## Codex（`backend = "codex"`）

使用 `codex login` 的 ChatGPT 登入執行 `codex exec --json`（遵循 `CODEX_HOME`）。評測程式會傳入
`--ignore-user-config`、`--sandbox read-only` 和 `web_search="disabled"`，並關閉 `apps` 功能（其連接器
自帶網絡搜尋）、瀏覽器操作和電腦操作。文字呼叫時還會關閉圖像生成。

**隔離限制。** `--ignore-user-config` 無法阻止 Codex 載入全域指令（`$CODEX_HOME/AGENTS.md`）及已安裝的技能。全新的工作目錄能排除儲存庫脈絡，但無法完全清除 Codex 的脈絡。需要乾淨的評測環境時，請使用專用、已登入且不含個人指令和技能的 `CODEX_HOME`。早期試跑樣本使用了普通使用者目錄。

**圖像生成**（`can = ["image"]`）使用 Codex 內建的 `image_gen` 工具。對話模型會被要求把基準提示詞原樣
交給該工具；圖片從 `$CODEX_HOME/generated_images/<thread>/` 複製出來。之後評測程式讀取工作階段記錄
（`$CODEX_HOME/sessions/**/rollout-*-<thread>.jsonl`），在 `meta.audit` 中記錄 `image_gen` 的呼叫次數，
以及每次呼叫收到的提示詞是否未被改動。`reference` 檔位的提示詞會用 `--image` 附上原圖。

如果圖像工具的結果回報 `moderation_blocked`，表示服務商的安全系統拒絕了請求或生成結果。此時樣本記錄為 `refused`，不含圖片，而不是記錄為錯誤。拒絕生成屬於模型的結果：不會自動重試（`--force` 會重新生成），且只要提示詞核對為原樣傳遞，它在排名題組中記 0 分。

## Claude（`backend = "claude"`）

使用 Claude Code 登入執行 `claude -p`。工具、MCP 伺服器和設定來源都會被停用，程式設計 Agent 的系統提示詞
也會被替換為中性的提示詞。圖片透過 `--input-format stream-json` 以內容區塊形式傳送。僅支援文字和視覺。

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
  檔案、技能和子 Agent 外掛。該 ACP Agent 不接受圖片輸入。
- **Kimi Code**（`kimi acp`）：`config = { mode = "plan" }` 讓工作階段以規劃模式啟動，不執行任何工具。
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

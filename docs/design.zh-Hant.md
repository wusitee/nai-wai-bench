# 基準設計

[English](design.md) | [简体中文](design.zh-CN.md) | 繁體中文

奶蛙bench（nai-wai-bench）衡量 AI 模型對中文網絡迷因 大笑奶龍（Laughing Nailong，又稱 奶蛙）的了解程度：
一隻 AI 生成的「變異」奶龍，彎著腰捂著肚子，瞇著眼、張大嘴狂笑。原圖為
`bench/reference/nailong_laugh.png`，出處見 `bench/reference/SOURCE.md`。

基準有兩個互相獨立的暫定排名：**圖像生成**和**視覺理解**，兩者不合成總分。文字／語言表現只作診斷。
研究依據、呼叫預算和此評測方案的局限見 [評測方法](methodology.zh-Hant.md)。

## 排名題組

- **圖像生成：** 6 種預設動物（貓、熊貓、青蛙、長頸鹿、章魚、大象）× 全部 5 個檔位，共 30 格。每格都需要
  目前有效的評審結果，以及核實為原樣傳遞的提示詞（`true`）。提示詞有改動或未核實的樣本會顯示在診斷中，
  但不能參與排名。
- **視覺理解：** 全部 13 道看圖題：9 道識別題和 4 道按答案鍵計分的視覺核對題。純文字模型不列入該排名。

每個題組的得分是各格平均分的算術平均；同一格的多次重複先在格內取平均。每個必需的格子都必須有分數，
且每個嘗試過的重複編號在每一格中都要有分數。嘗試過但失敗的重複不會悄悄地從資格判斷中消失。如果圖像
服務商的安全系統拒絕了一個已核實為原樣傳遞的提示詞，該格不經評審直接記 0 分（見
[backends.zh-Hant.md](backends.zh-Hant.md) 的 Codex 一節）；拒絕生成屬於結果，不會自動重試。不完整或重複
次數不齊的題組會顯示完成格數和狀態，但沒有名次和排名分數。失敗、呼叫了工具、過期和未評審的樣本都不能
填補格子。額外的動物和文字題不會改變固定題組的分數。各模型的重複次數可以不同，會顯示在分數旁邊；盡量
比較重複次數相同的結果。分數完全相同時名次並列。這些名次只描述本次觀察到的題組，不代表統計顯著性，
也不代表通用的多模態能力。

`scores.json` 將這些表存放在 `leaderboards.imagegen` 和 `leaderboards.visual_understanding` 中。舊的
`understanding.overall` 欄位現在等同於已有題目的看圖平均分，不再是文字與視覺的混合分。診斷平均分使用
已有的題目，可能與合格的排名分數不同。

## 第一部分：理解（`nwb understand`）

文字模型和視覺模型回答關於這個迷因的問題。題目定義在 `bench/tasks.toml` 的 `[understanding.*]` 中：

| 題目 | 模態 | 考察內容 |
|---|---|---|
| `knowledge_zh`、`knowledge_en` | text | 來源、別名、二創和相關的梗，分別用中文和英文提問 |
| `describe`、`describe_en` | text | 不看圖片，分別用中文和英文回憶原圖的視覺特徵 |
| `write_prompt.<animal>`、`write_prompt_zh.<animal>` | text | 分別用英文和中文為貓和長頸鹿版本撰寫文生圖提示詞 |
| `recognize_zh`、`recognize_en` | vision | 從原圖認出這個迷因 |
| `recognize_variant` | vision | 從一張按此風格畫的熊貓圖認出這個迷因 |
| `recognize_naiwa`、`recognize_angry` | vision | 從真實表情包認出這個迷因的家族：蛙狀的奶蛙（「驚鴻一瞥」）和紅色憤怒版（「切換憤怒模式」） |
| `recognize_facepalm`、`recognize_smug`、`recognize_folded_arms` | vision | 認出三張外觀不同、廣為流傳的變異奶龍表情包 |
| `recognize_official` | vision | 區分官方奶龍形象圖與非官方迷因圖（陰性對照） |
| `grounding.<case>` | vision | 用固定的 JSON 標籤回報四張現有圖片中角色的姿勢和眼睛狀態 |
| `grounding.<case>.blind` | text | 同一問題但不提供圖片，作為診斷用的對照 |

每個提示詞前都會加上「僅憑自身知識回答」的指示，各後端也會關閉網絡搜尋和其他工具（見
[backends.zh-Hant.md](backends.zh-Hant.md)）。如果 Agent 仍然呼叫了工具，該回答會被標記為 `contaminated`，
不參與評審和計分；報告中會顯示這類回答的數量。

**計分。** 每道題都有一份檢查項清單，條目 id 來自 `bench/rubric.toml`：知識類和識別類題目使用事實
（`[facts.*]`），描述類和提示詞類題目使用視覺特徵（`[traits.*]`）和 `identity`。評審模型為每個 id 給
0 分（缺失或錯誤）、1 分（部分正確或含糊）或 2 分（明確正確），並列出幻覺：與參考資料、`[background]`
或 `[misconceptions]` 相矛盾的肯定說法，或評審確信是捏造的細節。帶有不確定語氣的猜測不算幻覺。

```
題目得分 = 100 × Σ 檢查項得分 / (2 × 檢查項數量) − 10 × 幻覺數量   （最低為 0）
```

四道視覺核對題定義在 `bench/tasks.toml` 的 `[grounding]` 下。它們按答案鍵在本地計分，不需要 LLM 評審：
姿勢正確得 50 分，眼睛狀態正確得 50 分。錯誤、缺失或為 `unknown` 的欄位得 0 分；回覆中沒有 JSON 物件則
得 0 分。接受帶程式碼區塊標記的 JSON，標籤不區分大小寫並忽略首尾空白。無圖對照不計入文字和看圖平均分。
**視覺增益** 是按題目和重複編號配對後「有圖得分 − 無圖得分」的平均值，單位為百分點。缺少對照時不產生
配對差值，而不是記為 0 分。這是對圖片依賴程度的診斷，並非 MMStar 完整的洩漏分析。

`--items vision` 只選看圖題，`--items text` 只選文字輸入題（包括無圖對照），`--items grounding` 選四道
視覺核對題及其四個對照。這些選擇器和預設命令都只選核心題組；`--items states` 會加入下文所述的獨立
表情提取題組。

## 第二部分：圖像生成（`nwb imagegen`）

圖像模型把這個迷因畫成其他動物（`bench/tasks.toml` 中的 `[animals.*]`）。每種動物使用五個提示詞檔位生成
（`[imagegen.tiers.*]`）：

| 檔位 | 提示詞提供的資訊 | 考察內容 |
|---|---|---|
| `name_zh` | 只有中文名稱 | 對這個迷因的了解 |
| `name_en` | 只有英文名稱 | 跨語言的了解 |
| `described_brief` | 一句話的大致描述，不提名稱 | 憑粗略印象作畫的能力 |
| `described_detailed` | 詳細描述姿勢、體型和光滑的 3D 渲染風格，不提名稱 | 繪製能力（上限） |
| `reference` | 原圖加上「畫一個⟨動物⟩版本」 | 根據範例遷移風格的能力 |

帶 `anatomy_conflict` 標籤的動物（長頸鹿、章魚、鯊魚、企鵝）對姿勢和體型特徵是更大的考驗；`frog`（青蛙）
則呼應「奶蛙」這個名字。`--animals default` 執行標記了 `default = true` 的固定六種動物題組。
`--animals all` 包含全部 12 種動物；額外的動物會出現在診斷和圖庫中。

**計分。** 視覺評審同時看到原圖和生成圖，為每項視覺特徵給 0–2 分，為 `identity`（能否認出是目標動物）
給 0–2 分，並標記失敗模式（`[failure_modes]`：`generic_cute`、`realistic_animal`、`plain_nailong` 等）。

```
style   = 100 × Σ (特徵得分 × 權重) / (2 × Σ 權重)
overall = style × identity / 2
```

特徵權重偏向能把這個迷因和一般「可愛大笑動物」區分開的特徵：姿勢和捂肚子（2），嘴巴和整體氣質（1.5），
其次是眼睛、體型和渲染（1），最後是肚皮色塊和背景（0.5）。

**知識比率** = 兩個名稱檔位的平均總分 ÷ `described_detailed` 檔位的平均總分，只統計三個檔位都有分數的
動物。同一動物／檔位格內的多次重複先取平均。沒有可配對的動物或分母平均值為 0 時不計算。比率接近 1，
表示兩種提示條件下的表現相近；比率低，表示詳細提示詞帶來了提升。它不是「模型認識這個迷因」的校準機率，
也可能大於 1。比較 `described_brief` 和 `described_detailed`，可以看出細緻說明渲染風格能帶來多大提升。
診斷中也提供每種動物的平均分；為某一種動物增加重複次數不會提高它在彙總中的權重。

圖像生成器都是 Agent（Codex、Antigravity）：它們收到基準提示詞後，轉交給自己的圖像工具。評測程式會讀取
每次圖像工具呼叫記錄中的提示詞參數，檢查它是否與基準提示詞完全一致；報告會統計不一致的樣本數。

## 可選的表情遷移

`bench/tasks.toml` 中的 `[state_transfer]` 定義了三種來源表情：憤怒、扶額和得意。目標是在經典的大笑姿勢
之外，把來源圖中可見的表情和肢體語言遷移到另一種動物身上。預設目標動物是貓和青蛙。每種表情有兩種生成
條件：

- `state_<state>_reference`：附上對應的來源圖，所有表情都使用同一條中性的遷移指示，提示詞中不提表情名稱。
- `state_<state>_described`：不附圖片，由一段固定描述給出表情和動作。

此題組的開銷是 3 種表情 × 2 種動物 × 2 種條件 = **每個圖像模型每次重複 12 張圖**。可用 `--animals`
明確選擇其他動物。`--tiers states` 選擇這六個可選檔位；預設的生成命令仍只選五個核心檔位和 30 個
核心格。檔位 id 和輸出路徑互不相同，因此已有的核心樣本仍可重用。

`--items states` 選擇 `states.<state>` 和 `states.<state>.blind`：三道看圖題和三個配對的無圖對照。
它們使用同一條提取提示詞，詢問 `state`、`eyes`、`mouth` 和 `gesture`。每個正確欄位在本地得 25 分；
錯誤、缺失或為 `unknown` 的欄位得 0 分。這些診斷結果和配對的視覺增益存放在 `scores.json` 的
`state_understanding` 下，不進入任何核心排名。預設的理解執行和 `--items vision` 不會加入這些可選呼叫。

表情遷移的生成結果在報告和網站中都**不計分**。`nwb judge` 會跳過它們，彙總時也會忽略附在它們上面的
任何經典特徵評審：獎勵「捂肚大笑」的評分標準不適用於憤怒或扶額的目標。網站把來源圖和生成結果放在一起，
供人工檢視。檢視標準和局限見 [methodology.zh-Hant.md](methodology.zh-Hant.md#跨動物的表情遷移)。參考圖的
製作方式和出處見 [SOURCE.md](../bench/reference/SOURCE.md)。

```sh
# 僅執行可選題組；這些命令只產生回答和圖片，不做 LLM 評分。
uv run nwb understand --run states --models VISION_MODEL --items states
uv run nwb imagegen --run states --models IMAGE_MODEL --tiers states
uv run nwb report --run states
uv run nwb site --run states
```

## 評審與彙總（`nwb judge`、`nwb report`）

任何具備 `text` 能力的已設定模型都可以評審文字回答；評審識別題回答和生成圖片需要 `vision` 能力。識別題
的評審除了參考資料，還會收到原始的題目圖片。舊的、沒有附圖的識別題評審結果不再計入，需要重新評審。視覺
核對題及其無圖對照不需要評審呼叫。預設評審列在 `models.toml` 的 `[defaults].judges`（第一部分）和
`[defaults].image_judges`（第二部分）中。評審以 JSON 作答；未通過驗證的回覆會重試一次，仍失敗則記為
錯誤。

圖像評審需先逐項描述看到的內容，再用一個詞給出評級（`absent`、`partial`、`match`；identity 用 `no`、
`partly`、`clearly`），這些詞對應 0–2 分。

每個樣本的得分是各評審的平均分；只要至少有一個獨立評審，就排除與受測模型同廠商的評審（測試中自評明顯
偏寬鬆）。至少一半評審標記的失敗模式才會計入。每條評審結果都對應它所評審的樣本版本和確切的評審
提示詞：兩者任一改變，`nwb judge` 都會重新評審；樣本重新生成後，`nwb report` 會忽略它的舊評審結果。報告
也只統計用目前提示詞生成的樣本，所以已刪除或改過措辭的題目和檔位，在重新生成之前不會計入。

報告中的 **評審健康度** 表列出每個評審在每部分的得分離散度，以及它與其他評審在相同樣本上的平均差距。
離散度接近 0 表示該評審沒有區分能力；差距過大表示它與其他評審意見不一致。兩者都說明應排除該評審：
`nwb report --judges` 只統計列出的評審。Gemini 3.8 Flash（透過 Antigravity）因此被排除在預設圖像評審
之外：它給每張圖的每項特徵都打了 `partial`，即使它自己的說明寫的是完全符合。

## 結果網站（`nwb site`）

`uv run nwb site --run v1` 在 `site/` 中產生中英雙語網站，與本地報告分開。兩者開頭都是互相獨立的圖像生成
和視覺理解排名，以及完成格數和重複次數。網站接著展示：模型的呼叫方式和 C2PA 來源資訊；每種動物一個
圖庫，包含全部核心檔位的圖片、分數、失敗模式和提示詞核對狀態（服務商拒絕生成的格子會單獨標出）；各檔位
的診斷平均分和配對的知識比率；不計分的可選表情遷移圖庫，與各自的來源圖並排；文字／語言、視覺核對和
表情提取的診斷結果及全部回答；以及評審健康度。沒有評審得分的地方顯示短橫線。有重複採樣時，圖庫展示
第一次採樣，彙總包含所有樣本。

頁首記錄執行名稱、建置日期和儲存庫提交（`git rev-parse --short HEAD`；`bench/` 或 `src/` 有未提交的
改動時會另行標註）。指定 `--repo-url` 時，方法說明和素材來源的連結指向該提交。

`--out DIR` 指定輸出目錄；`--judges NAME,...` 僅使用列出的評審計分；`--repo-url URL` 加入原始碼連結。
建置器寫入 `index.html` 和使用相對路徑的圖片資源，不刪除已有的輸出檔案。若安裝了 ImageMagick
（`magick`），圖片會等比例縮小至不超過 768 × 768 像素；否則原樣複製。圖庫縮圖保留完整畫面。

C2PA 對 OpenAI 僅標註 `ChatGPT · gpt-image`，對 Google 僅標註「Created by Google Generative AI」；兩者都
沒有公開更具體的圖像模型版本。這些是廠商聲明，不代表簽章已經驗證。`meta.client` 標識中轉用戶端，而非
底層圖像生成器。

### 發佈

`scripts/publish_site.sh [RUN]`（預設 `v1`）在新的暫存目錄中建置，加入 `.nojekyll`，並僅用產生的網站
取代 `origin` 上的 `gh-pages` 分支。需要 `uv`、Git、已設定的 Git 作者身分和推送權限，不會改變目前簽出的
分支。產生的執行資料和網站檔案在原始碼分支上仍被 git 忽略。

首次啟用 GitHub Pages：`gh api -X POST repos/OWNER/REPO/pages -f 'source[branch]=gh-pages' -f 'source[path]=/'`；
若已啟用則改用 `-X PUT`。用 `gh api repos/OWNER/REPO/pages/builds/latest` 檢查建置狀態，用
`gh api repos/OWNER/REPO/pages --jq .html_url` 取得網址。**即使原始碼儲存庫是私有的，Pages 網站仍然公開。**
只發佈打算公開的結果。

## 結果目錄結構

每次執行儲存在 `runs/<run>/`（已被 git 忽略），每個樣本一個 JSON 檔案：

```
runs/<run>/understanding/<model>/<item>__r<rep>.json
runs/<run>/imagegen/<model>/<tier>/<animal>__r<rep>.json      （另有 <animal>__r<rep>/ 存放圖片）
runs/<run>/judgments/<judge>/<與被評審樣本相同的路徑>
runs/<run>/scores.json, runs/<run>/report.html
```

命令會跳過用目前提示詞已成功生成的樣本，並重做記錄了 `error` 或用其他提示詞生成的樣本，所以中斷的
執行可以從中斷處繼續。服務商拒絕生成的樣本會作為結果保留；`--force` 會重新生成所選的全部樣本。

## 擴充

- **事實或特徵：** 在 `bench/rubric.toml` 中加入條目，並在題目的檢查項清單中引用其 id。事實、特徵和
  identity 的 id 不能重複；`nwb` 啟動時會驗證。
- **題目、檔位、動物：** 編輯 `bench/tasks.toml`。在提示詞中用 `{zh}` 和 `{en}` 表示動物名稱。
- **模型：** 見 [backends.zh-Hant.md](backends.zh-Hant.md)。

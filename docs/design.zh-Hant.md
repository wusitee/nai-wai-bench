# 基準設計

[English](design.md) | [简体中文](design.zh-CN.md) | 繁體中文

nai-wai-bench 衡量 AI 模型對中文網絡迷因 大笑奶龍（Laughing Nailong，又稱 奶蛙）的了解程度：一隻 AI 生成的
「變異」奶龍，彎著腰捂著肚子，瞇著眼、張大嘴狂笑。原圖為 `bench/reference/nailong_laugh.png`，出處見
`bench/reference/SOURCE.md`。

基準分為兩部分。

## 第一部分：理解（`nwb understand`）

文字模型和視覺模型回答關於這個迷因的問題。題目定義在 `bench/tasks.toml` 的 `[understanding.*]` 中：

| 題目 | 模態 | 考察內容 |
|---|---|---|
| `knowledge_zh`、`knowledge_en` | 文字 | 來源、別名、二次創作和相關梗，分別以中文和英文提問 |
| `describe` | 文字 | 不看圖片，回憶原圖的視覺特徵 |
| `write_prompt.<animal>` | 文字 | 為某種動物版本撰寫文字生成圖像的提示詞（考察知識的運用） |
| `recognize_zh`、`recognize_en` | 視覺 | 從原圖認出這個迷因 |
| `recognize_variant` | 視覺 | 從一張按此風格繪畫的熊貓圖認出這個迷因 |
| `recognize_naiwa`、`recognize_angry` | 視覺 | 從真實表情包認出這個迷因的家族：蛙狀的奶蛙（「惊鸿一瞥」）和紅色憤怒版（「切换愤怒模式」） |
| `recognize_facepalm`、`recognize_smug`、`recognize_folded_arms` | vision | 從三張外觀不同的流傳表情包認出變異奶龍 |
| `recognize_official` | vision | 區分官方奶龍形象與非官方梗圖（陰性對照） |

每個提示詞前都會加上「僅憑自身知識回答」的指示，各後端也會關閉網絡搜尋和其他工具（見
[backends.zh-Hant.md](backends.zh-Hant.md)）。如果 Agent 仍然呼叫了工具，該回答會被標記為 `contaminated`，
不參與評審和計分；報告中會顯示這類回答的數量。

**計分。** 每道題目都有一份檢查項目清單，項目 id 來自 `bench/rubric.toml`：知識類和識別類題目使用事實
（`[facts.*]`），描述類和提示詞類題目使用視覺特徵（`[traits.*]`）和 `identity`。評審模型為每個 id 給
0 分（缺失或錯誤）、1 分（部分正確或含糊）或 2 分（明確正確），並列出幻覺：與參考資料、`[background]`
或 `[misconceptions]` 相矛盾的肯定說法，或評審確信是捏造的細節。帶有不確定語氣的猜測不算幻覺。

```
題目得分 = 100 × Σ 檢查項目得分 / (2 × 檢查項目數量) − 10 × 幻覺數量   （最低為 0）
```

## 第二部分：圖像生成（`nwb imagegen`）

圖像模型把這個迷因畫成其他動物（`bench/tasks.toml` 中的 `[animals.*]`）。每種動物使用五個提示詞檔位生成
（`[imagegen.tiers.*]`）：

| 檔位 | 提示詞提供的資訊 | 考察內容 |
|---|---|---|
| `name_zh` | 只有中文名稱 | 對這個迷因的了解 |
| `name_en` | 只有英文名稱 | 跨語言的了解 |
| `described_brief` | 一句話的大致描述，不提名稱 | 憑粗略印象作畫的能力 |
| `described_detailed` | 詳細描述姿勢、體型和光滑的 3D 渲染風格，不提名稱 | 繪畫能力（上限） |
| `reference` | 原圖加上「畫一個⟨動物⟩版本」 | 根據範例轉移風格的能力 |

帶 `anatomy_conflict` 標籤的動物（長頸鹿、章魚、鯊魚、企鵝）對姿勢和體型特徵是更大的考驗；`frog`（青蛙）
則呼應「奶蛙」這個名字。`--animals default` 只執行標記了 `default = true` 的子集。

**計分。** 視覺評審同時看到原圖和生成圖，為每項視覺特徵給 0–2 分，為 `identity`（能否認出是目標動物）
給 0–2 分，並標記失敗模式（`[failure_modes]`：`generic_cute`、`realistic_animal`、`plain_nailong` 等）。

```
style   = 100 × Σ (特徵得分 × 權重) / (2 × Σ 權重)
overall = style × identity / 2
```

特徵權重偏重能把這個迷因和一般「可愛大笑動物」區分開的特徵：姿勢和捂肚子（2），嘴巴和整體氣質（1.5），
其次是眼睛、體型和渲染（1），最後是肚皮色塊和背景（0.5）。

**知識比率** = 兩個名稱檔位的平均總分 ÷ `described_detailed` 檔位的總分。比率接近 1，表示模型只憑名稱就能
畫得和給出詳細描述時一樣好；比率低，表示模型畫得出這種風格，但並不認識這個迷因。比較 `described_brief` 和
`described_detailed`，可以看出細緻說明 3D 渲染風格能帶來多大提升。

圖像生成器都是 Agent（Codex、Antigravity）：它們收到基準提示詞後，轉交給自己的圖像工具。評測程式會讀取
每次圖像工具呼叫記錄中的提示詞參數，檢查它是否與基準提示詞完全一致；報告會統計不一致的樣本數。

## 評審與彙總（`nwb judge`、`nwb report`）

任何具備 `text` 能力的已設定模型都可以評審第一部分；評審第二部分需要 `vision` 能力。預設評審列在
`models.toml` 的 `[defaults].judges`（第一部分）和 `[defaults].image_judges`（第二部分）中。評審以 JSON
作答；未通過驗證的回覆會重試一次，仍失敗則記為錯誤。

圖像評審須先逐項描述看到的內容，再用一個詞給出評級（`absent`、`partial`、`match`；identity 用 `no`、
`partly`、`clearly`），這些詞對應 0–2 分。

每個樣本的得分是各評審的平均分；只要至少有一個獨立評審，就排除與受測模型同廠商的評審（測試中自評明顯
偏寬鬆）。至少一半評審標記的失敗模式才會計入。每項評審結果都對應它所評審的樣本版本和確切的評審
提示詞：兩者任一改變，`nwb judge` 都會重新評審；樣本重新生成後，`nwb report` 會忽略它的舊評審結果。報告也只
統計以目前提示詞生成的樣本，所以已刪除或改過措辭的題目和檔位，在重新生成之前不會計入。

報告中的 **評審健康度** 表列出每個評審在每部分的得分離散度，以及它與其他評審在相同樣本上的平均差距。
離散度接近 0 表示該評審沒有鑑別能力；差距過大表示它與其他評審意見不一致。兩者都表示應排除該評審：
`nwb report --judges` 只統計列出的評審。Gemini 3.8 Flash（透過 Antigravity）因此被排除在預設圖像評審
之外：它給每張圖的每項特徵都評為 `partial`，即使它自己的說明寫的是完全符合。

## 結果網站（`nwb site`）

`uv run nwb site --run smoke` 在 `site/` 中產生中英雙語網站，與本機報告分開。網站展示模型名稱、記錄的呼叫用戶端和模型 id、C2PA 來源資訊、按動物及檔位排列的圖片與提示詞核對狀態、分數彙總和知識比率、理解得分與完整回答，以及評審健康度。結果為初步結果；沒有評審得分的地方顯示短橫線。有重複取樣時，圖庫展示第一次取樣，彙總包含所有樣本。

`--out DIR` 指定輸出目錄；`--judges NAME,...` 僅使用列出的評審計分；`--repo-url URL` 加上原始碼連結。建置器寫入 `index.html` 和使用相對路徑的圖片資源，不刪除已有輸出檔案。若安裝了 ImageMagick（`magick`），圖片會等比例縮小至不超過 768 × 768 像素；否則原樣複製。圖庫縮圖保留完整畫面。

C2PA 對 OpenAI 僅標註 `ChatGPT · gpt-image`，對 Google 僅標註「Created by Google Generative AI」；兩者均未公開更具體的圖像模型版本。這些是廠商聲明，不代表簽章已經驗證。`meta.client` 識別中轉用戶端，而非底層圖像生成器。

### 發佈

`scripts/publish_site.sh [RUN]`（預設 `smoke`）在新的暫存目錄中建置，加入 `.nojekyll`，並僅以產生的網站取代 `origin` 上的 `gh-pages` 分支。需要 `uv`、Git、已設定的 Git 作者身分和推送權限，不會改變目前簽出的分支。產生的執行資料和網站檔案在原始碼分支上仍被 git 忽略。

首次啟用 GitHub Pages：`gh api -X POST repos/OWNER/REPO/pages -f 'source[branch]=gh-pages' -f 'source[path]=/'`；若已啟用則改用 `-X PUT`。用 `gh api repos/OWNER/REPO/pages/builds/latest` 檢查建置狀態，用 `gh api repos/OWNER/REPO/pages --jq .html_url` 取得網址。**即使原始碼儲存庫是私有的，Pages 網站仍然公開。** 只發佈打算公開的結果。

## 結果目錄結構

每次執行儲存在 `runs/<run>/`（已被 git 忽略），每個樣本一個 JSON 檔案：

```
runs/<run>/understanding/<model>/<item>__r<rep>.json
runs/<run>/imagegen/<model>/<tier>/<animal>__r<rep>.json      （另有 <animal>__r<rep>/ 存放圖片）
runs/<run>/judgments/<judge>/<與被評審樣本相同的路徑>
runs/<run>/scores.json, runs/<run>/report.html
```

指令會略過以目前提示詞已成功生成的樣本，並重做記錄了 `error` 或以其他提示詞生成的樣本，所以中斷的
執行可以從中斷處繼續；`--force` 會重新生成所選的全部樣本。

## 擴充

- **事實或特徵：** 在 `bench/rubric.toml` 中新增項目，並在題目的檢查項目清單中引用其 id。事實、特徵和
  identity 的 id 不能重複；`nwb` 啟動時會驗證。
- **題目、檔位、動物：** 編輯 `bench/tasks.toml`。在提示詞中用 `{zh}` 和 `{en}` 代表動物名稱。
- **模型：** 見 [backends.zh-Hant.md](backends.zh-Hant.md)。

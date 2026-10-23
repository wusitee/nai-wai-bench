# 基准设计

[English](design.md) | 简体中文 | [繁體中文](design.zh-Hant.md)

奶蛙bench（nai-wai-bench）衡量 AI 模型对中文网络梗 大笑奶龙（Laughing Nailong，又称 奶蛙）的了解程度：
一只 AI 生成的“变异”奶龙，弯着腰捂着肚子，眯着眼、张大嘴狂笑。原图为
`bench/reference/nailong_laugh.png`，出处见 `bench/reference/SOURCE.md`。

基准有两个相互独立的暂定排名：**图像生成**和**视觉理解**，两者不合成总分。文字/语言表现只作诊断。
研究依据、调用预算和该评测方案的局限见 [评测方法](methodology.zh-CN.md)。

## 排名题组

- **图像生成：** 6 种默认动物（猫、熊猫、青蛙、长颈鹿、章鱼、大象）× 全部 5 个档位，共 30 格。每格都需要
  当前有效的评审结果，以及核实为原样传递的提示词（`true`）。提示词有改动或未核实的样本会显示在诊断中，
  但不能参与排名。
- **视觉理解：** 全部 13 道看图题：9 道识别题和 4 道按答案键计分的视觉核对题。纯文本模型不列入该排名。

每个题组的得分是各格均分的算术平均；同一格的多次重复先在格内取平均。每个必需的格子都必须有分数，
且每个尝试过的重复编号在每一格中都要有分数。尝试过但失败的重复不会悄悄地从资格判断中消失。如果图像
服务商的安全系统拒绝了一个已核实为原样传递的提示词，该格不经评审直接记 0 分（见
[backends.zh-CN.md](backends.zh-CN.md) 的 Codex 一节）；拒绝生成属于结果，不会自动重试。不完整或重复次数
不齐的题组会显示完成格数和状态，但没有名次和排名分数。失败、调用了工具、过期和未评审的样本都不能填补
格子。额外的动物和文字题不会改变固定题组的分数。各模型的重复次数可以不同，会显示在分数旁边；尽量比较
重复次数相同的结果。分数完全相同时名次并列。这些名次只描述本次观察到的题组，不代表统计显著性，也不代表
通用的多模态能力。

`scores.json` 将这些表存放在 `leaderboards.imagegen` 和 `leaderboards.visual_understanding` 中。旧的
`understanding.overall` 字段现在等同于已有题目的看图均分，不再是文字与视觉的混合分。诊断均分使用已有的
题目，可能与合格的排名分数不同。

## 第一部分：理解（`nwb understand`）

文本模型和视觉模型回答关于这个梗的问题。题目定义在 `bench/tasks.toml` 的 `[understanding.*]` 中：

| 题目 | 模态 | 考察内容 |
|---|---|---|
| `knowledge_zh`、`knowledge_en` | text | 来源、别名、二创和相关梗，分别用中文和英文提问 |
| `describe`、`describe_en` | text | 不看图片，分别用中文和英文回忆原图的视觉特征 |
| `write_prompt.<animal>`、`write_prompt_zh.<animal>` | text | 分别用英文和中文为猫和长颈鹿版本撰写文生图提示词 |
| `recognize_zh`、`recognize_en` | vision | 从原图认出这个梗 |
| `recognize_variant` | vision | 从一张按此风格画的熊猫图认出这个梗 |
| `recognize_naiwa`、`recognize_angry` | vision | 从真实表情包认出这个梗的家族：蛙状的奶蛙（「惊鸿一瞥」）和红色愤怒版（「切换愤怒模式」） |
| `recognize_facepalm`、`recognize_smug`、`recognize_folded_arms` | vision | 认出三张外观不同、广为流传的变异奶龙表情包 |
| `recognize_official` | vision | 区分官方奶龙形象图与非官方梗图（阴性对照） |
| `grounding.<case>` | vision | 用固定的 JSON 标签报告四张现有图片中角色的姿势和眼睛状态 |
| `grounding.<case>.blind` | text | 同一问题但不提供图片，作为诊断用的对照 |

每个提示词前都会加上“仅凭自身知识回答”的指令，各后端也会关闭网络搜索和其他工具（见
[backends.zh-CN.md](backends.zh-CN.md)）。如果 Agent 仍然调用了工具，该回答会被标记为 `contaminated`，
不参与评审和计分；报告中会显示这类回答的数量。

**计分。** 每道题都有一份检查项清单，条目 id 来自 `bench/rubric.toml`：知识类和识别类题目使用事实
（`[facts.*]`），描述类和提示词类题目使用视觉特征（`[traits.*]`）和 `identity`。评审模型为每个 id 打
0 分（缺失或错误）、1 分（部分正确或含糊）或 2 分（明确正确），并列出幻觉：与参考资料、`[background]`
或 `[misconceptions]` 相矛盾的肯定说法，或评审确信是编造的细节。带有不确定语气的猜测不算幻觉。

```
题目得分 = 100 × Σ 检查项得分 / (2 × 检查项数量) − 10 × 幻觉数量   （最低为 0）
```

四道视觉核对题定义在 `bench/tasks.toml` 的 `[grounding]` 下。它们按答案键在本地计分，不需要 LLM 评审：
姿势正确得 50 分，眼睛状态正确得 50 分。错误、缺失或为 `unknown` 的字段得 0 分；回复中没有 JSON 对象则
得 0 分。接受带代码块标记的 JSON，标签不区分大小写并忽略首尾空白。无图对照不计入文字和看图均分。
**视觉增益** 是按题目和重复编号配对后“有图得分 − 无图得分”的平均值，单位为百分点。缺少对照时不产生
配对差值，而不是记为 0 分。这是对图片依赖程度的诊断，并非 MMStar 完整的泄漏分析。

`--items vision` 只选看图题，`--items text` 只选文字输入题（包括无图对照），`--items grounding` 选四道
视觉核对题及其四个对照。这些选择器和默认命令都只选核心题组；`--items states` 会加入下文所述的独立
表情提取题组。

## 第二部分：图像生成（`nwb imagegen`）

图像模型把这个梗画成其他动物（`bench/tasks.toml` 中的 `[animals.*]`）。每种动物使用五个提示词档位生成
（`[imagegen.tiers.*]`）：

| 档位 | 提示词提供的信息 | 考察内容 |
|---|---|---|
| `name_zh` | 只有中文梗名 | 对这个梗的了解 |
| `name_en` | 只有英文梗名 | 跨语言的了解 |
| `described_brief` | 一句话的大致描述，不提梗名 | 凭粗略印象作画的能力 |
| `described_detailed` | 详细描述姿势、体型和光滑的 3D 渲染风格，不提梗名 | 绘制能力（上限） |
| `reference` | 原图加上“画一个⟨动物⟩版本” | 根据示例迁移风格的能力 |

带 `anatomy_conflict` 标签的动物（长颈鹿、章鱼、鲨鱼、企鹅）对姿势和体型特征是更大的考验；`frog`（青蛙）
则呼应“奶蛙”这个名字。`--animals default` 运行标记了 `default = true` 的固定六种动物题组。
`--animals all` 包含全部 12 种动物；额外的动物会出现在诊断和图库中。

**计分。** 视觉评审同时看到原图和生成图，为每项视觉特征打 0–2 分，为 `identity`（能否认出是目标动物）
打 0–2 分，并标记失败模式（`[failure_modes]`：`generic_cute`、`realistic_animal`、`plain_nailong` 等）。

```
style   = 100 × Σ (特征得分 × 权重) / (2 × Σ 权重)
overall = style × identity / 2
```

特征权重偏向能把这个梗和普通“可爱大笑动物”区分开的特征：姿势和捂肚子（2），嘴巴和整体气质（1.5），
其次是眼睛、体型和渲染（1），最后是肚皮色块和背景（0.5）。

**知识比率** = 两个梗名档位的平均总分 ÷ `described_detailed` 档位的平均总分，只统计三个档位都有分数的
动物。同一动物/档位格内的多次重复先取平均。没有可配对的动物或分母均值为 0 时不计算。比率接近 1，说明
两种提示条件下的表现相近；比率低，说明详细提示词带来了提升。它不是“模型认识这个梗”的校准概率，也可能
大于 1。对比 `described_brief` 和 `described_detailed`，可以看出细致说明渲染风格能带来多大提升。诊断中
也提供每种动物的均分；给某一种动物增加重复次数不会提高它在汇总中的权重。

图像生成器都是 Agent（Codex、Antigravity）：它们收到基准提示词后，转交给自己的图像工具。评测程序会读取
每次图像工具调用记录中的提示词参数，检查它是否与基准提示词完全一致；报告会统计不一致的样本数。

## 可选的表情迁移

`bench/tasks.toml` 中的 `[state_transfer]` 定义了三种源表情：愤怒、扶额和得意。目标是在经典的大笑姿势
之外，把源图中可见的表情和肢体语言迁移到另一种动物身上。默认目标动物是猫和青蛙。每种表情有两种生成
条件：

- `state_<state>_reference`：附上对应的源图，所有表情都使用同一条中性的迁移指令，提示词中不提表情名称。
- `state_<state>_described`：不附图片，由一段固定描述给出表情和动作。

该题组的开销是 3 种表情 × 2 种动物 × 2 种条件 = **每个图像模型每次重复 12 张图**。可用 `--animals`
明确选择其他动物。`--tiers states` 选择这六个可选档位；默认的生成命令仍只选五个核心档位和 30 个
核心格。档位 id 和输出路径互不相同，因此已有的核心样本仍可复用。

`--items states` 选择 `states.<state>` 和 `states.<state>.blind`：三道看图题和三个配对的无图对照。
它们使用同一条提取提示词，询问 `state`、`eyes`、`mouth` 和 `gesture`。每个正确字段在本地得 25 分；
错误、缺失或为 `unknown` 的字段得 0 分。这些诊断结果和配对的视觉增益存放在 `scores.json` 的
`state_understanding` 下，不进入任何核心排名。默认的理解运行和 `--items vision` 不会加入这些可选调用。

表情迁移的生成结果在报告和网站中都**不计分**。`nwb judge` 会跳过它们，汇总时也会忽略附在它们上面的
任何经典特征评审：奖励“捂肚大笑”的评分标准不适用于愤怒或扶额的目标。网站把源图和生成结果放在一起，
供人工查看。查看标准和局限见 [methodology.zh-CN.md](methodology.zh-CN.md#跨动物的表情迁移)。参考图的
制作方式和出处见 [SOURCE.md](../bench/reference/SOURCE.md)。

```sh
# 仅运行可选题组；这些命令只生成回答和图片，不做 LLM 评分。
uv run nwb understand --run states --models VISION_MODEL --items states
uv run nwb imagegen --run states --models IMAGE_MODEL --tiers states
uv run nwb report --run states
uv run nwb site --run states
```

## 评审与汇总（`nwb judge`、`nwb report`）

任何具备 `text` 能力的已配置模型都可以评审文字回答；评审识别题回答和生成图片需要 `vision` 能力。识别题
的评审除了参考资料，还会收到原始的题目图片。旧的、没有附图的识别题评审结果不再计入，需要重新评审。视觉
核对题及其无图对照不需要评审调用。默认评审列在 `models.toml` 的 `[defaults].judges`（第一部分）和
`[defaults].image_judges`（第二部分）中。评审以 JSON 作答；未通过校验的回复会重试一次，仍失败则记为
错误。

图像评审需先逐项描述看到的内容，再用一个词给出评级（`absent`、`partial`、`match`；identity 用 `no`、
`partly`、`clearly`），这些词对应 0–2 分。

每个样本的得分是各评审的平均分；只要至少有一个独立评审，就排除与被测模型同厂商的评审（测试中自评明显
偏宽松）。至少一半评审标记的失败模式才会计入。每条评审结果都对应它所评审的样本版本和确切的评审
提示词：两者任一改变，`nwb judge` 都会重新评审；样本重新生成后，`nwb report` 会忽略它的旧评审结果。报告
也只统计用当前提示词生成的样本，所以已删除或改过措辞的题目和档位，在重新生成之前不会计入。

报告中的 **评审健康度** 表列出每个评审在每部分的得分离散度，以及它与其他评审在相同样本上的平均差距。
离散度接近 0 说明该评审没有区分能力；差距过大说明它与其他评审意见不一致。两者都说明应排除该评审：
`nwb report --judges` 只统计列出的评审。Gemini 3.8 Flash（通过 Antigravity）因此被排除在默认图像评审
之外：它给每张图的每项特征都打了 `partial`，即使它自己的说明写的是完全符合。

## 结果网站（`nwb site`）

`uv run nwb site --run v1` 在 `site/` 中生成中英双语网站，与本地报告分开。两者开头都是相互独立的图像生成
和视觉理解排名，以及完成格数和重复次数。网站随后展示：模型的调用方式和 C2PA 来源信息；每种动物一个
图库，包含全部核心档位的图片、分数、失败模式和提示词核对状态（服务商拒绝生成的格子会单独标出）；各档位
的诊断均分和配对的知识比率；不计分的可选表情迁移图库，与各自的源图并排；文字/语言、视觉核对和表情
提取的诊断结果及全部回答；以及评审健康度。没有评审得分的地方显示短横线。有重复采样时，图库展示第一次
采样，汇总包含所有样本。

页头记录运行名称、构建日期和仓库提交（`git rev-parse --short HEAD`；`bench/` 或 `src/` 有未提交的
改动时会另行标注）。指定 `--repo-url` 时，方法说明和素材来源的链接指向该提交。

`--out DIR` 指定输出目录；`--judges NAME,...` 仅使用列出的评审计分；`--repo-url URL` 添加源码链接。
构建器写入 `index.html` 和使用相对路径的图片资源，不删除已有输出文件。若安装了 ImageMagick
（`magick`），图片会等比例缩小至不超过 768 × 768 像素；否则原样复制。图库缩略图保留完整画面。

C2PA 对 OpenAI 仅标注 `ChatGPT · gpt-image`，对 Google 仅标注“Created by Google Generative AI”；两者都
没有公开更具体的图像模型版本。这些是厂商声明，不代表签名已经验证。`meta.client` 标识中转客户端，而非
底层图像生成器。

### 发布

`scripts/publish_site.sh [RUN]`（默认 `v1`）在新的临时目录中构建，添加 `.nojekyll`，并仅用生成的网站
替换 `origin` 上的 `gh-pages` 分支。需要 `uv`、Git、已配置的 Git 作者身份和推送权限，不会改变当前检出的
分支。生成的运行数据和网站文件在源码分支上仍被 git 忽略。

首次启用 GitHub Pages：`gh api -X POST repos/OWNER/REPO/pages -f 'source[branch]=gh-pages' -f 'source[path]=/'`；
若已启用则改用 `-X PUT`。用 `gh api repos/OWNER/REPO/pages/builds/latest` 检查构建状态，用
`gh api repos/OWNER/REPO/pages --jq .html_url` 获取网址。**即使源码仓库是私有的，Pages 网站仍然公开。**
只发布打算公开的结果。

## 结果目录结构

每次运行保存在 `runs/<run>/`（已被 git 忽略），每个样本一个 JSON 文件：

```
runs/<run>/understanding/<model>/<item>__r<rep>.json
runs/<run>/imagegen/<model>/<tier>/<animal>__r<rep>.json      （另有 <animal>__r<rep>/ 存放图片）
runs/<run>/judgments/<judge>/<与被评审样本相同的路径>
runs/<run>/scores.json, runs/<run>/report.html
```

命令会跳过用当前提示词已成功生成的样本，并重做记录了 `error` 或用其他提示词生成的样本，所以中断的
运行可以从断点继续。服务商拒绝生成的样本会作为结果保留；`--force` 会重新生成所选的全部样本。

## 扩展

- **事实或特征：** 在 `bench/rubric.toml` 中添加条目，并在题目的检查项清单中引用其 id。事实、特征和
  identity 的 id 不能重复；`nwb` 启动时会校验。
- **题目、档位、动物：** 编辑 `bench/tasks.toml`。在提示词中用 `{zh}` 和 `{en}` 表示动物名称。
- **模型：** 见 [backends.zh-CN.md](backends.zh-CN.md)。

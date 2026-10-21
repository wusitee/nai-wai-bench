# 基准设计

[English](design.md) | 简体中文 | [繁體中文](design.zh-Hant.md)

nai-wai-bench 衡量 AI 模型对中文网络梗 大笑奶龙（Laughing Nailong，又称 奶蛙）的了解程度：一只 AI 生成的
“变异”奶龙，弯着腰捂着肚子，眯着眼、张大嘴狂笑。原图为 `bench/reference/nailong_laugh.png`，出处见
`bench/reference/SOURCE.md`。

基准分为两部分。

## 第一部分：理解（`nwb understand`）

文本模型和视觉模型回答关于这个梗的问题。题目定义在 `bench/tasks.toml` 的 `[understanding.*]` 中：

| 题目 | 模态 | 考察内容 |
|---|---|---|
| `knowledge_zh`、`knowledge_en` | 文本 | 来源、别名、二创和相关梗，分别用中文和英文提问 |
| `describe` | 文本 | 不看图片，回忆原图的视觉特征 |
| `write_prompt.<animal>` | 文本 | 为某种动物版本撰写文生图提示词（考察知识的运用） |
| `recognize_zh`、`recognize_en` | 视觉 | 从原图认出这个梗 |
| `recognize_variant` | 视觉 | 从一张按此风格画的熊猫图认出这个梗 |

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

## 第二部分：图像生成（`nwb imagegen`）

图像模型把这个梗画成其他动物（`bench/tasks.toml` 中的 `[animals.*]`）。每种动物使用四个提示词档位生成
（`[imagegen.tiers.*]`）：

| 档位 | 提示词提供的信息 | 考察内容 |
|---|---|---|
| `name_zh` | 只有中文梗名 | 对这个梗的了解 |
| `name_en` | 只有英文梗名 | 跨语言的了解 |
| `described` | 完整的外观描述，不提梗名 | 绘制能力（上限） |
| `reference` | 原图加上“画一个⟨动物⟩版本” | 根据示例迁移风格的能力 |

带 `anatomy_conflict` 标签的动物（长颈鹿、章鱼、鲨鱼、企鹅）对姿势和体型特征是更大的考验；`frog`（青蛙）
则呼应“奶蛙”这个名字。`--animals default` 只运行标记了 `default = true` 的子集。

**计分。** 视觉评审同时看到原图和生成图，为每项视觉特征打 0–2 分，为 `identity`（能否认出是目标动物）
打 0–2 分，并标记失败模式（`[failure_modes]`：`generic_cute`、`realistic_animal`、`plain_nailong` 等）。

```
style   = 100 × Σ (特征得分 × 权重) / (2 × Σ 权重)
overall = style × identity / 2
```

特征权重偏向能把这个梗和普通“可爱大笑动物”区分开的特征：姿势和捂肚子（2），嘴巴和整体气质（1.5），
其次是眼睛、体型和渲染（1），最后是肚皮色块和背景（0.5）。

**知识比率** = 两个梗名档位的平均总分 ÷ `described` 档位的总分。比率接近 1，说明模型只凭梗名就能画得和
给出描述时一样好；比率低，说明模型画得出这种风格，但并不认识这个梗。

图像生成器都是 Agent（Codex、Antigravity）：它们收到基准提示词后，转交给自己的图像工具。评测程序会读取
每次图像工具调用记录中的提示词参数，检查它是否与基准提示词完全一致；报告会统计不一致的样本数。

## 评审与汇总（`nwb judge`、`nwb report`）

任何具备 `text` 能力的已配置模型都可以评审第一部分；评审第二部分需要 `vision` 能力。默认评审列在
`models.toml` 的 `[defaults].judges`（第一部分）和 `[defaults].image_judges`（第二部分）中。评审以 JSON
作答；未通过校验的回复会重试一次，仍失败则记为错误。

图像评审需先逐项描述看到的内容，再用一个词给出评级（`absent`、`partial`、`match`；identity 用 `no`、
`partly`、`clearly`），这些词对应 0–2 分。

每个样本的得分是各评审的平均分；只要至少有一个独立评审，就排除与被测模型同厂商的评审（测试中自评明显
偏宽松）。至少一半评审标记的失败模式才会计入。每条评审结果都对应它所评审的样本版本和确切的评审
提示词：样本重新生成或评分标准改动后，`nwb judge` 会重新评审，`nwb report` 也会忽略旧结果。

报告中的 **评审健康度** 表列出每个评审在每部分的得分离散度，以及它与其他评审在相同样本上的平均差距。
离散度接近 0 说明该评审没有区分能力；差距过大说明它与其他评审意见不一致。两者都说明应排除该评审：
`nwb report --judges` 只统计列出的评审。Gemini 3.8 Flash（通过 Antigravity）因此被排除在默认图像评审
之外：它给每张图的每项特征都打了 `partial`，即使它自己的说明写的是完全符合。

## 结果目录结构

每次运行保存在 `runs/<run>/`（已被 git 忽略），每个样本一个 JSON 文件：

```
runs/<run>/understanding/<model>/<item>__r<rep>.json
runs/<run>/imagegen/<model>/<tier>/<animal>__r<rep>.json      （另有 <animal>__r<rep>/ 存放图片）
runs/<run>/judgments/<judge>/<与被评审样本相同的路径>
runs/<run>/scores.json, runs/<run>/report.html
```

命令会跳过用当前提示词已成功生成的样本，并重做记录了 `error` 或用其他提示词生成的样本，所以中断的
运行可以从断点继续；`--force` 会重新生成所选的全部样本。

## 扩展

- **事实或特征：** 在 `bench/rubric.toml` 中添加条目，并在题目的检查项清单中引用其 id。事实、特征和
  identity 的 id 不能重复；`nwb` 启动时会校验。
- **题目、档位、动物：** 编辑 `bench/tasks.toml`。在提示词中用 `{zh}` 和 `{en}` 表示动物名称。
- **模型：** 见 [backends.zh-CN.md](backends.zh-CN.md)。

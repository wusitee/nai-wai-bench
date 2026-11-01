<img src="assets/icon.svg" width="64" height="64" alt="">

# 奶蛙bench · nai-wai-bench

[English](README.md) | 简体中文 | [繁體中文](README.zh-Hant.md)

一个测试 AI 模型对中文网络梗 **大笑奶龙**（又称 **奶蛙**）了解程度的基准：AI 生成的“变异”奶龙，弯腰捧腹、狂笑不止。

<img src="bench/reference/nailong_laugh.png" width="200" alt="大笑奶龙原图">

**结果：**[wusitee.github.io/nai-wai-bench](https://wusitee.github.io/nai-wai-bench/)（第一版：每格只跑一次，
由 LLM 评审打分）；[奶蛙图鉴 Nai-hub v1](https://wusitee.github.io/nai-wai-bench/naihub-v1/)。

基准发布两个相互独立的排名：

1. **视觉理解**：认出这个梗及其变体，区分官方形象图，并回答有固定答案键的看图问题。纯文字的来龙去脉、
   凭记忆描述画面以及中英文提示词写作单独作为诊断项，不影响视觉排名。
2. **图像生成**：图像模型把这个梗画成其他动物（默认题组为猫、熊猫、青蛙、长颈鹿、章鱼和大象），
   提示词分五档：中文梗名、英文梗名、简略描述、详细描述（细致说明其 3D 外观）和参考原图。
   对比相同动物在“只给梗名”和“给出描述”时的结果，可以衡量模型对提示词详细程度的敏感度。

只有完整跑完固定题组的模型才会获得暂定名次。不完整的结果仍会显示，并标明完成的格数。
几分的差距不足以证明排序可靠。另有一个不计分的可选题组，测试图像模型能否把奶蛙的其他表情
（愤怒、扶额、得意）迁移到别的动物身上。

默认由 Claude Opus 5.5 评审自由作答和生成图片；按答案键计分的题目在本地计分。报告只统计已配置的评审，
除非用 `--judges` 另行指定。

## 快速开始

环境要求：Python 3.12+、[uv](https://docs.astral.sh/uv/)，以及至少一个已登录的 Agent CLI 或 API 密钥：
[Codex](https://github.com/openai/codex)（OpenAI 模型与图像生成）、
[Claude Code](https://claude.com/claude-code)（Anthropic 模型，或其他供应商的 Anthropic 兼容接口）、
[pi](https://github.com/earendil-works/pi)（pi 支持的任何供应商）、
ACP Agent（如 DeepSeek Harness、Kimi Code、Antigravity），
或 OpenAI 兼容 API（如小米 MiMo，密钥来自环境变量或 [CC Switch](https://github.com/farion1231/cc-switch)）。
收集结果不需要评审模型；没有评审权限的协作者可以分享结果，交由他人评审（见
[Contributing results](docs/contributing-results.md)）。

```sh
uv sync
uv run nwb list                                   # 查看模型、题目、提示词档位和动物

# 理解：看图题，以及文字诊断题和无图对照
uv run nwb understand --models opus-5.5,gpt-6.1-sol,deepseek-v4-pro,mimo-v2.6-pro
# 图像生成：6 种动物 × 5 档 = 每个模型 30 张图
uv run nwb imagegen --models chatgpt-image --animals default

uv run nwb judge                                  # 使用 models.toml 中的默认评审（需要 Claude Code）
uv run nwb report                                 # 生成 runs/main/report.html
uv run nwb site                                   # 写入 site/index.html
```

结果保存在 `runs/<run>/`（`--run NAME`，默认 `main`）。中断的运行会接着跑，失败的样本会自动重试。

## 文档

- [基准设计](docs/design.zh-CN.md)：题目、档位、评分标准、计分方式、结果网站和结果目录结构
- [评测方法](docs/methodology.zh-CN.md)：研究依据、调用预算、对照设计和局限
- [可选的表情迁移](docs/design.zh-CN.md#可选的表情迁移)：把愤怒、扶额、得意三种表情迁移到猫和青蛙身上，
  每个图像模型 12 张图；另有表情提取题，均不使用 LLM 评分
- [后端与模型](docs/backends.zh-CN.md)：各 Agent CLI 的调用与隔离方式，以及如何添加模型（包括 pi 和通过
  Claude Code 接入的其他供应商）
- [Contributing results](docs/contributing-results.md)（英文）：没有评审权限时如何收集、分享结果，以及如何评审分享来的结果
- [素材来源](bench/reference/SOURCE.md)：参考图、表情包和事实的出处

参考图和表情包仅供非商业研究使用。

<img src="assets/icon.svg" width="64" height="64" alt="">

# nai-wai-bench

[English](README.md) | 简体中文 | [繁體中文](README.zh-Hant.md)

一个测试 AI 模型对中文网络梗 **大笑奶龙**（又称 **奶蛙**）理解程度的基准：AI 生成的“变异”奶龙，弯腰捧腹、狂笑不止。

<img src="bench/reference/nailong_laugh.png" width="200" alt="大笑奶龙原图">

基准分为两部分：

1. **理解**：文本模型和视觉模型讲解这个梗的来源和相关梗、凭记忆描述它的样子、为它写图像生成提示词，
   并从图片中认出它。回答会对照有出处的事实打分，言之凿凿的幻觉会被扣分。
2. **图像生成**：图像模型把这个梗画成其他动物（猫、长颈鹿、章鱼等），提示词分四档：中文梗名、英文梗名、
   完整的外观描述、参考原图。对比“只给梗名”和“给出描述”的结果，就能看出模型是真的认识这个梗，
   还是只有被告知长相时才画得出来。

每个样本都由多家厂商的评审模型打分；只要有其他厂商的评审可用，模型就不会由同厂商的评审来评分。

## 快速开始

环境要求：Python 3.12+、[uv](https://docs.astral.sh/uv/)，以及至少一个已登录的 Agent CLI 或 API 密钥：
[Codex](https://github.com/openai/codex)（OpenAI 模型与图像生成）、
[Claude Code](https://claude.com/claude-code)、ACP Agent（如 DeepSeek Harness、Kimi Code、Antigravity），
或 OpenAI 兼容 API（如小米 MiMo，密钥来自环境变量或 [CC Switch](https://github.com/farion1231/cc-switch)）。

```sh
uv sync
uv run nwb list                                   # 查看模型、题目、提示词档位和动物

# 第一部分：向模型提问，再评审回答
uv run nwb understand --models opus-5.5,gpt-6.1-sol,deepseek-v4-pro,mimo-v2.6-pro
# 第二部分：用全部档位画默认的动物子集
uv run nwb imagegen --models chatgpt-image --animals default

uv run nwb judge                                  # 使用 models.toml 中的默认评审
uv run nwb report                                 # 生成 runs/main/report.html
```

结果保存在 `runs/<run>/`（`--run NAME`，默认 `main`）。中断的运行会接着跑，失败的样本会自动重试。

## 文档

- [基准设计](docs/design.zh-CN.md)：题目、档位、评分标准、计分方式和结果目录结构
- [后端与模型](docs/backends.zh-CN.md)：各 Agent CLI 的调用与隔离方式，以及如何添加模型

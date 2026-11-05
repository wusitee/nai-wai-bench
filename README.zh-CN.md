<img src="assets/icon.svg" width="64" height="64" alt="">

# 奶蛙bench · nai-wai-bench

[English](README.md) | 简体中文 | [繁體中文](README.zh-Hant.md)

一个测试 AI 模型对中文网络梗 **大笑奶龙**（又称 **奶蛙**）了解程度的基准：AI 生成的“变异”奶龙，弯腰捧腹、狂笑不止。

<img src="bench/reference/nailong_laugh.png" width="200" alt="大笑奶龙原图">

**结果：**[wusitee.github.io/nai-wai-bench](https://wusitee.github.io/nai-wai-bench/)（0.1.0 版：
附 95% 自助法区间与名次范围）。

基准发布两个看图理解排名，并合成为**奶蛙指数 · NaiWai Index**：

1. **识梗 Meme ID**（`--suite core`，13 道看图题）：认出这个梗及其变体，说出梗名和别名，区分官方形象图。
   9 道自由回答由 LLM 评审打分，4 道姿势与眼睛核对题按固定答案键计分。
2. **看图 Visual detail**（`--suite naihub-v1`，24 张图）：回答类别、数量、姿态、眼睛、嘴巴、手势和眼泪，
   在本地与答案键比对。七项全部答对，这张图才算答对。

指数是两项得分的加权平均（识梗 1/3、看图 2/3），只有两项都有名次的模型才进入指数。
纯文字的来龙去脉、凭记忆描述画面以及中英文提示词写作只作诊断，不进入任何排名。
只有完整跑完固定题组的模型才会获得暂定名次。不完整的结果仍会显示，并标明完成的格数。
几分的差距不足以证明排序可靠。

**图像生成**是不计入指数的实验项目：图像模型按五档提示词（中文梗名、英文梗名、简略描述、
详细描述其 3D 外观、参考原图）把这个梗画成其他动物。另有一个不计分的可选题组，测试能否把奶蛙的
其他表情（愤怒、扶额、得意）迁移到别的动物身上。

默认由 Claude Opus 5.5 评审自由作答和生成图片；按答案键计分的题目在本地计分。报告只统计已配置的评审，
除非用 `--judges` 另行指定。收集结果不需要评审模型：[协作者](docs/contributing-results.md)可以分享结果，交由他人评审。

## 快速开始

环境要求：Python 3.12+、[uv](https://docs.astral.sh/uv/)，以及至少一个已登录的 Agent CLI 或 API 密钥：
[Codex](https://github.com/openai/codex)（OpenAI 模型与图像生成）、
[Claude Code](https://claude.com/claude-code)（Anthropic 模型，或其他供应商的 Anthropic 兼容接口）、
[pi](https://github.com/earendil-works/pi)（pi 支持的任何供应商）、
ACP Agent（如 DeepSeek Harness（DeepSeek 和 GLM 模型）、Kimi Code、Antigravity），
或 OpenAI 兼容 API（如小米 MiMo，密钥来自环境变量或 [CC Switch](https://github.com/farion1231/cc-switch)）。

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

工作结果保存在 `runs/<run>/`（`--run NAME`，默认 `main`）。收集、评审和生成报告时，还会把可移植的副本保存到
`results/<suite>/<run>/`，可以正常用 Git 提交和推送。中断的运行会接着跑，失败的样本会自动重试；
全新检出的仓库会根据保存的结果自动恢复缺失的工作目录。本地实验可以加 `--no-sync`。

## 版本发布

版本发布、验证状态和勘误见[更新日志](CHANGELOG.md)（英文）和 [Benchmark card](docs/benchmark-card.md)（英文）。
`uv run nwb --version` 显示已安装的版本；`uv run nwb export --run RUN --suite SUITE` 导出原始结果，用于离线重新计分。

要用保留的原始结果重建选定的对比，运行 `uv run nwb release --manifest releases/0.1.0.toml`。
它会构建两个题组和可下载的数据包，不调用任何模型。恢复输入和发布的方法见[发布流程](docs/releases.md)（英文）。

只有条件一致的模型才能排名，旧版设置会被标出。暴露 effort 控制时使用 high，否则使用默认值，标签显示实际记录的设置。
报告包含配对聚类区间和 token 效率；这些只是小题组的敏感度估计和 API 标价成本估计，
不代表显著性结论，也不是订阅账单。详见[评测方法](docs/methodology.zh-CN.md)。

## 文档

- [架构](docs/architecture.md)（英文）：执行流程、计分路径、结果存储和交互式架构图
- [发布流程](docs/releases.md)（英文）：固定对比的输入、离线构建、原始数据包和发布
- [看图题组（Nai-hub v1）](docs/naihub-eval-set.md)（英文）：24 张按答案键计分的图，带无图对照和
  8 张迁移参考图（`--suite naihub-v1`）
- [基准设计](docs/design.zh-CN.md)：题目、档位、评分标准、计分方式、结果网站和结果目录结构
- [评测方法](docs/methodology.zh-CN.md)：研究依据、调用预算、对照设计和局限
- [可选的表情迁移](docs/design.zh-CN.md#可选的表情迁移)：把愤怒、扶额、得意三种表情迁移到猫和青蛙身上，
  每个图像模型 12 张图；另有表情提取题，均不使用 LLM 评分
- [后端与模型](docs/backends.zh-CN.md)：各 Agent CLI 的调用与隔离方式，以及如何添加模型（包括 pi 和通过
  Claude Code 接入的其他供应商）
- [贡献结果](docs/contributing-results.md)（英文）：没有评审权限时如何收集、分享结果，以及如何评审分享来的结果
- [节目视频](docs/video.md)（英文）：B 站结果视频的格式、数据规则、制作流程和发布
- [素材来源](bench/reference/SOURCE.md)：参考图、表情包和事实的出处

参考图和表情包仅供非商业研究使用。

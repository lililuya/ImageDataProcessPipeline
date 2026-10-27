# Proposal

## Why

通用 LoRA 数据对照需要可复现的模型评测。当前 DataPipeline 只有人工分层审计实现及 M4 模型评测规划；LyCORIS 的作者评测脚本已独立公开，但目录约定、依赖和实验配置需要整理为独立产品。

## What Changes

- 按用户指定将独立模型评测实现放入 `lililuya/AllBench`，本仓库保留数据发布、审计与接口边界。
- 建立固定协议、生成任务清单、图像及特征摘要、按概念和提示类型分组的指标报告。
- 实现图像相似度/SCD、CLIP 文图对齐、逐提示 Vendi、同提示同种子 VGG19 Gram 风格差异；明确工程扩展与论文复现的区别。
- 使用合成图片验证契约、恢复及 node94 流程；真实概念样本、目标底模/LoRA 与人工金标就绪后再做模型效果验收。
- 2026-10-27 用户追加指定 FLUX.2-klein-9B 作为真实生成器；接入本地权重真实出图、逐项回执与恢复。LoRA 尚未提供时采用显式 base_only 模式，允许无参考图，缺失指标保持未测。
- 用户进一步要求打通全部链路：真实匹配底模与 LoRA 开关对照、DINO/CLIP/VGG19 实测、逐图编码恢复、JSON/CSV/HTML 报告及统一运行入口；正式样本替换配置即可运行，流程验收与概念效果验收分别记录。

## Capabilities

### New Capabilities

- `lora-benchmark`: 独立 LoRA 评测协议、特征计算、指标分层报告与恢复。

### Modified Capabilities

无。原 `evaluation-feedback` change 的广义归因、补数与接口任务继续待实施，不把本次独立骨架计为完成。

## Impact

运行时代码位于用户明确指定的 `E:/Codex_Project/AllBench` 与对应 GitHub 仓库；此跨仓库目标来自用户直接指令。本仓库只更新规划、研究证据和入口文档。node94 使用独立代码/输出目录和空闲单卡，不修改既有业务环境。真实数据、模型和临时依赖不入 Git；不新增训练器，不预设模型收益或生产吞吐。

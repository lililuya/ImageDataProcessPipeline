# Design

## Context

见 proposal。LyCORIS 作者独立仓库 `cyber-meow/LyCORIS-evaluation` 修订 `7c5758c8338aa59c4601bb68db8d5112b15748c4` 已有指标、编码和生成脚本；其 setup.py 未声明运行依赖，脚本依赖目录命名及旧 WebUI 接口。AllBench 于核查时为空。DataPipeline 的 `evaluation/audit.py` 是已实现分层审计，留在本仓库。

## Goals / Non-Goals

**Goals:** 独立 Python CLI，JSON 协议输入，生成任务清单，支持外部生成结果和带版本的特征导入，CPU 指标、可选 GPU 编码、可恢复原子结果与可核验测试。

**Non-Goals:** 不新增训练器。用户已指定 FLUX.2-klein-9B；真实概念样本和 LoRA 就绪后再做完整对照。不以 FID、小样本美学分或单一总分作为主要概念验收依据。

## Decisions

1. 用户指定跨仓库实现：代码在 AllBench；规划、数据流程边界和来源证据在 DataPipeline。通过冻结数据发布 ID 交换，先不联动业务数据库。
2. 独立 manifest 显式记录概念、提示类型、实际生成提示及供 CLIP 使用的语义替换文本。base/adapted 在同一配置、提示、种子清单上配对。参考图标明 train/holdout 和亲缘组；已知跨划分精确重复/组重复拒绝，近重复筛查仍需外部候选/人工证据。
3. 数值核心采用 NumPy。余弦和 SCD 对各自 L2 归一化特征计算；Vendi 是线性核谱熵指数，逐提示计算再平均，附样本数。VGG19 在 conv1_1/2_1/3_1/4_1/5_1 取归一化 Gram，层间距离求和；保留指标方向，不跨指标求总分。
4. 特征包以图片 ID 对齐并绑定 manifest 和图片摘要、编码器身份/预处理。DINOv2、CLIP、VGG19 是可选且独立的编码路径；未配置返回未测。合成固定向量只用于数值及恢复测试，不冒充模型特征。
5. 原子写入 JSON 结果；相同输入重放返回已有报告，变化拒绝；并发写通过独占锁拒绝。错误不写为成功，已有完成产物经摘要验证。
6. node94 在独立目录用空闲单卡、小批合成图片测试，不停止现有任务。优先读取既有 DINOv2 权重和环境，缺失编码器不隐式下载。
7. 真实生成采用官方 FLUX.2-klein-9B 蒸馏版，本地单文件 transformer、Qwen3-8B、VAE/tokenizer 和显式 scheduler 配置组装 Diffusers pipeline。4步/guidance=1.0 为该版本官方示例；不与50步的 klein-base-9B 混淆。使用既有支持 Klein 的独立运行时且不升级共享环境。
8. 新增显式 `evaluation_mode=base_only`：仅生成/要求 base 输出，无 LoRA 时不创建 adapted 副本；参考可为空，保真/风格对照返回未测。旧协议缺省继续采用 paired。逐图回执绑定输入、模型组件摘要、采样配置、软件与图片摘要；相同输入恢复只补未提交项，损坏产物拒绝复用。
9. 完整链路支持同底模的 paired LoRA 推理：使用 Diffusers 官方转换器解析 Kohya/Musubi 或 Diffusers 格式，拒绝不支持的权重与未消费层；检查实际挂载张量，逐任务关闭/启用 LoRA。技术试点使用现有 klein-base-9B LoRA 与匹配非蒸馏底模，生成参考夹具只证明计算可达，不推断触发词语义或训练效果。
10. 统一入口依次冻结输入与组件、调用独立生成/编码 Python 环境、评测并导出报告。特征逐图片/文本原子提交，恢复校验摘要和身份，只补缺项。风格概念另报告参考 Gram 距离。JSON 是权威结果，CSV/HTML 附同源摘要及覆盖缺口；无人工标签时不产生自动成功结论。

## Risks / Trade-offs

- [CLIP 高分不等于身份或复杂关系正确] → 人工金标和局部属性/关系用例，报告代理指标局限。
- [单一参考池导致记忆被奖励] → train 与 holdout 独立，加入无触发词、组合及属性反事实。
- [小样本 Vendi 随数量变化] → 固定每提示种子集合并报告 n，不将 n=1 当多样性证据。
- [目标权重尚未提供] → 生成任务与离线导入接口先完成，真实生成验收保留待办。

## Migration Plan

独立初始化 AllBench，运行本地契约、数值、集成和中断恢复验证，再部署 node94 执行合成及可用编码器检查。只提交代码、中文说明及脱敏汇总；真实文件、依赖、权重、特征、输出留在仓库外。回滚仅切回独立代码目录，不改变原有 DataPipeline/ImageCaption 服务。

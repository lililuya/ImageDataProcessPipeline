# 研究依据与工程映射

核查日期：2026-10-15。本文是选定公开资料的工程分析，不宣称覆盖所有最新版本。论文按完整技术报告阅读，重点评估数据流程可复现性；不做投稿接收判断。公开方法、工程推断和未公开信息分别标记。

| 资料 | 公开依据 | 本项目工程推断 | 边界 |
|---|---|---|---|
| [LLaDA-Image §3–4、附录D](https://arxiv.org/html/2609.03796) | 纯图像阶段先于图文SFT；条件来自实际图像；分字段caption审核，编辑指令核对方向 | 素材与标注分离，视图绑定监督，字段重做，image-only兼容检查 | 模型结构须支持相应条件机制；论文阈值需校准 |
| [LLaDA 官方仓库](https://github.com/inclusionAI/LLaDA-Image) | 训练代码仍标 coming soon | 按行为契约重新实现可恢复流水线 | 推理代码不等于完整数据流水线 |
| [Qwen-Image-2.0 §2](https://arxiv.org/html/2605.10730) | 通用/文字/知识/结构化描述，分阶段处理及错误驱动数据反馈 | 任务化标注与审核、错误taxonomy、补数版本对照 | 不能把前代报告直接写成2.1配方 |
| [Qwen-Image-2.1 官方说明](https://qwen.ai/blog?id=qwen-image-2.1) | 统一生成编辑、原生透明图、最多十张参考图 | alpha、图像角色和输入顺序成为契约字段 | 能力说明不是完整数据集或训练混合比例 |
| [Krea 2 技术报告 Data / Data infrastructure](https://www.krea.ai/blog/krea-2-technical-report) | 强调多样性；OCR辅助caption；分阶段去重与筛选；元数据和对象引用分离、持久状态驱动处理 | 保留独立分数、覆盖审计、算子成本分层、持久任务 | 不照搬其规模，也不把美学分作为所有领域统一门槛 |
| [Krea 模型卡](https://huggingface.co/krea/Krea-2-Raw) | 整体训练数据包含合成数据 | 真实/合成/未知及阶段分别追踪 | 报告中的无合成图限定预训练，不能扩大到全部后训练 |
| [FLUX klein 官方风格指南](https://docs.bfl.ai/flux_2/flux2_klein_training_example) | 特定风格LoRA示例采用内容caption、触发词和省略风格描述 | 基础标注保留完整，导出时按目标投影 | 教程示例不能替代通用预训练配方 |
| [BFL Base 微调说明](https://help.bfl.ai/articles/7108141705-can-i-run-or-fine-tune-flux-2-klein-locally) | 推荐未蒸馏Base作为微调起点 | target checkpoint是配方兼容条件 | 不能推断完整基础模型数据来源与规模 |

## 参考阈值如何处理

LLaDA 报告的像素数大于1024²、文件大小/像素至少0.15 byte/pixel、ArtiMuse≥60、DeQA≥4.0，仅作为待验证参考。[依据](https://arxiv.org/html/2609.03796)

实施时先保留连续分数与来源分布，在人工审计集测量误删，再按领域和阶段选择阈值。文件字节/像素受编码格式影响；截图、设计图、透明素材与摄影图应分别检查。未加载对应模型且未复核分数量纲时，不启用数值阈值。

## 初始校准实验

1. 同预算比较全局美学门槛与分领域门槛，检查风格与长尾覆盖。
2. 比较全图caption直接复用与视图级重标，检查裁切错误和文字错误。
3. 比较单长caption与短中长混合，固定token预算并检查真实短提示表现。
4. 比较感知去重与加入语义候选复审，检查有效变体损失。
5. 比较全量大VLM处理与廉价路由后专项处理，报告人工一致性和每万张成本。
6. 编辑数据检查方向和非目标区域保持；生成质量好不代表编辑监督正确。

以上都是拟议实验，目前无本项目实测收益。数据量、模型效果或成本结论必须引用实际版本与报告。

## OpenSpec 使用依据

采用[官方 OpenSpec](https://github.com/Fission-AI/OpenSpec)的 proposal → specs → design → tasks → apply → archive 流程。本仓库固定CLI版本1.14.2。当前处于规划完成、实施未开始状态；语法校验成功不等同于系统功能测试成功。

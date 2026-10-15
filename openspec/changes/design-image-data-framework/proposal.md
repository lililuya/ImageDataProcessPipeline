# Proposal

## Why

图像训练数据需要从分散文件转为可追溯、可恢复、可按训练目标重组的数据产品。当前仓库为空，需要先建立全流程行为契约，避免清洗、标注、裁剪和训练导出之间发生信息丢失与不可复现。

## What Changes

- 建立共享资产、独立来源、派生视图、版本化观测与任务样本的数据体系。
- 支持纯图像、文生图、文字渲染、单图/多图编辑、透明图像、风格微调与偏好数据。
- 建立分层去重、字段审核、按任务与阶段选样、不可变发布及评测反馈闭环。
- 采用持久任务、幂等提交、租约与重试，分别调度 CPU、GPU 与外部推理服务。
- 将 LLaDA、Qwen、Krea、FLUX 经验转为可校准策略；不将论文阈值或特定 LoRA 示例设为全局规则。
- 本次交付设计与实施清单；运行时在后续 apply 中实现，不将规划或示例冒充可运行功能。

## Capabilities

### New Capabilities

- `asset-ingestion`: 来源登记、内容寻址、增量接入与访问治理。
- `image-validation`: 解码、方向、通道、尺寸及基础特征检查。
- `duplicate-management`: 精确/感知/语义重复候选、重复簇和泄漏防护。
- `durable-execution`: 依赖调度、租约、幂等、重试、资源与成本控制。
- `annotation-quality`: 多类型标注、字段审核、模型版本与人工复审。
- `training-views`: 裁剪、bucket、透明通道与监督一致性。
- `task-datasets`: 多种训练任务、图像角色与关联组管理。
- `curation-recipes`: 版本化筛选、覆盖率、长尾、配比与阶段课程。
- `dataset-releases`: 不可变发布、划分、打包、加载验证与撤回。
- `evaluation-feedback`: 数据审计、模型评测、错误归因与补数。

### Modified Capabilities

无；初始仓库没有现有实现或主规格。

## Impact

涉及未来 Python 数据处理包、PostgreSQL 元数据与队列、文件/对象存储、CPU/GPU 推理适配器、训练格式适配器和审核接口。Git 仅同步规格、配置、代码与合成测试夹具，不存储真实图片、凭据或大规模标注。当前引入项目级固定版本 OpenSpec 工具链；不部署服务、不下载模型、不执行付费标注。

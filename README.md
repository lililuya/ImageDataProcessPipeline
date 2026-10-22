# ImageDataProcessPipeline

面向图像生成模型训练的数据处理框架设计：共享原始资产，按任务、领域与训练阶段生成可追溯的数据版本。

**最新工作：ImageCaption v0.4模块审核、性能验证与质量模型开关。** 在v0.3的17阶段CLI/看板、联合水印裁剪、整图文字、质量分池、短中长描述及版本交付上，补充恢复核验、精确像素去重、元数据分盘和可复现性能工具。ArtiMuse与DeQA现可独立关闭，CLI和看板明确显示关闭状态。真实样本由程序处理，只查看数字与形式结果，四卡容量与实测严格区分。范围见[v0.4记录](docs/imagecaption-v0.4-status.md)，任务见[当前change](openspec/changes/build-imagecaption-data-workbench/tasks.md)。定制旧direct进度和真实质量校准仍待验收；[v0.3记录](docs/imagecaption-v0.3-status.md)与[v0.2记录](docs/imagecaption-v0.2-status.md)保留为历史。

**当前状态：框架规格已建立，按OpenSpec持续实施，已完成21/70项。** 本地有完整项目源码、规格与测试，整个系统尚未全部实现。已有接入、持久CPU处理、视图、数值质量观测、精确重复来源簇、版本化选择配方与评分导入，以及最小T2I manifest/sidecar发布和实际读取；评分/标注模型、预算、GC、完整课程与多任务发布仍待实施。

ImageCaption现已加入原始文件密度门控：参考值0.15 byte/pixel，可通过配方或CLI调整/关闭；裁后重编码不替代原始证据。已有prompt的[语义标签模型选型](docs/research-evidence.md#prompt语义标签化模型选型2026-10-22)已完成调研，标签器尚未部署或验收。

当前优先使用[Windows本地操作手册](docs/local-runbook.md)，运行`idp demo`可用合成素材完成接入→处理→发布→实际读取。其他说明见[M0指南](docs/m0-guide.md)、[node95操作手册](docs/node95-runbook.md)、[持久处理与恢复](docs/durable-processing.md)及[实施状态](docs/implementation-status.md)。`idp --help`列出的命令可运行；设计文档中的其他命令与配方不代表已实现。

2026-10-18新增最小发布与本地合成闭环，验证记录见实施状态。node95此前离线，2026-10-22已恢复只读连接；本仓库第三轮起的新代码及迁移仍未完成远端部署验收，最后确认的DataPipeline部署为第二轮。真实图片与95业务数据库未复制到本机。

同日追加选择配方与v6迁移：固定模型/配置/输入版本，区分宽保留与评分门槛，将决策绑定发布；美学和画质模型的真实推理仍待接入，本轮未在95部署。

2026-10-22完成[水印监督与完整条件链路复核](docs/research-evidence.md#watermark-conditioning-audit)：MOSS宽保留同时使用属性监督和推理负向条件。原通用底座的评分引用不自动进入训练文本；随后ImageCaption v0.3已实现视图属性、完整条件和参考加载器消费，外部训练器与实际控制收益仍待验收。

## 阅读入口

- [ImageCaption最新产品提案](openspec/changes/build-imagecaption-data-workbench/proposal.md)
- [CLI与看板、处理流程及版本设计](openspec/changes/build-imagecaption-data-workbench/design.md)
- [看板行为与进度口径规格](openspec/changes/build-imagecaption-data-workbench/specs/imagecaption-cli-progress/spec.md)
- [ImageCaption分阶段实施任务](openspec/changes/build-imagecaption-data-workbench/tasks.md)
- [提案与能力范围](openspec/changes/design-image-data-framework/proposal.md)
- [技术设计与架构图](openspec/changes/design-image-data-framework/design.md)
- [十项能力规格](openspec/changes/design-image-data-framework/specs/)
- [分阶段实施与验收任务](openspec/changes/design-image-data-framework/tasks.md)
- [论文、模型资料与工程映射（含MOSS-Image分析）](docs/research-evidence.md)
- [数据契约与配方示例](docs/contracts.md)
- [版本化选择配方与评分接入](docs/recipes.md)

## 目标全流程

下图是原通用框架的目标流程，包含待实施环节；各能力现状以实施状态和CLI帮助为准。最新ImageCaption流程及水印裁剪策略见[新设计](openspec/changes/build-imagecaption-data-workbench/design.md)。

```mermaid
flowchart TD
  A[来源与原始资产] --> B[解码与基础观测]
  B --> C[重复候选与关联组]
  C --> D[OCR / 特征 / 多类型标注]
  C --> W[水印 / 模糊等属性与证据：待实现]
  C --> Q[美学 / 画质评价：模型推理待接入]
  Q --> F
  D --> E[字段审核与人工复审]
  W --> E
  E --> F[任务与阶段配方：独立评分或显式门槛]
  F --> G[训练视图与监督匹配]
  G --> P[最终条件组装 / 完整token审计：待实现]
  P --> H[组级划分与不可变发布]
  H --> I[真实训练加载器]
  I --> J[评测归因与定向补数]
  J --> F
```

支持范围设计包含纯图像、T2I、文字排版、单图/多图编辑、透明图像、风格LoRA和偏好数据。核心原则是观测与筛选分离、原图与训练视图分离、执行失败与质量结论分离。

水印等属性有独立的观测、监督和选样用途。配方决定保留并标注、精选或复审；不预设全局删除/擦除。用于控制生成的属性还必须进入训练器实际消费的条件，仅保存分数或数据库元数据不足以实现控制。

## OpenSpec工作流

使用[OpenSpec](https://github.com/Fission-AI/OpenSpec)，固定版本1.14.2。需要Node.js≥20.19和npm：

```powershell
npm ci
npm run spec:validate
npm run spec:status
```

也可直接调用：

```powershell
node node_modules/@fission-ai/openspec/bin/openspec.js status --change design-image-data-framework
node node_modules/@fission-ai/openspec/bin/openspec.js status --change build-imagecaption-data-workbench
node node_modules/@fission-ai/openspec/bin/openspec.js validate --all --strict
```

`design-image-data-framework`记录原底座的21/70项实施进度，`npm run spec:status`仍指向该change。`build-imagecaption-data-workbench`是当前产品方向，v0.3为38/40项，模块审核与容量验收为43/45项，质量模型独立开关完成后为45/47项，文件密度门控与prompt标签选型完成后为48/50项；通过上面的显式命令及tasks查看最新验收状态。已验收任务逐项勾选，其余保持未完成，全部验收后再archive。`openspec/specs/`在归档前为空，当前规格位于change内部，避免把未实现行为当成现状。

`.agents/skills/`为CLI生成的Codex工作流。Git仅同步代码、规格与小型合成测试数据，真实图像、产物、模型和凭据保存在仓库外。远程仓库：[lililuya/ImageDataProcessPipeline](https://github.com/lililuya/ImageDataProcessPipeline)。

## 实施顺序

| 阶段 | 交付目标 |
|---|---|
| M0 | 契约、合成夹具、抽样审计与容量基准 |
| M1 | 接入、存储、持久任务、基础处理与最小发布闭环 |
| M2 | 分层去重、标注审核、训练视图、配方与覆盖审计 |
| M3 | 多任务、训练适配、完整发布与读取性能 |
| M4 | 模型对照、补数反馈、接口、故障恢复与规模验收 |

具体数据量、资源、推理模型、预算和训练器在试点部署时绑定；设计不预设未经验证的吞吐、筛选阈值或训练配比。

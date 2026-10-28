# ImageCaption流程审计与跨会话交接（2026-10-28）

当前运行时基线为`275e4e4809789c99c07d730ae7684419920a1372`，node94 v0.15。用户要求核对流程、排除JoyCaption的前置耗时，并提供其他会话可以直接使用的处理文档。

主交接文档保存在运行时仓库的[数据处理交接手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/data-processing-handoff.md)，包含机器/目录、原控制服务恢复、认证和反向隧道、GPU与本地SQLite磁盘检查、新版本与断点恢复、单long构建、数值核验、独立负面候选与待审交付。审计明细见[流程核查报告](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workflow-audit-20261028.md)。这两个文档是当前操作入口，旧部署记录保留历史意义。

## Findings

- 当前单long、实际视图绑定、低尺寸/低密度负面保留、默认裁剪和关闭双评分符合已确认目标。合成回归没有发现新增阻断性回归。
- 水印/文字校准仍pending，不能自动将候选确认为水印；开启crop不能证明实际裁剪。此前16张实际裁剪0，真实裁剪质量仍未验收。
- 当前来源授权unknown，目标训练tokenizer为空；仅能按现配方产出待审草稿，不能直接发布训练数据。待审与负面候选不自动进入训练主集。
- node94系统盘剩约3.4GB，原配方缓存落在系统盘。本轮另存`v0.15/20261027-joycaption-official/private/processing-policy-20261028.json`，缓存迁到node94本地ext4的独立工程子目录，原配方/历史state未修改。活跃SQLite WAL不放NFS。
- node94四卡当时均有其他任务，本轮没有启动真实模型或Gradio，没有中止其他GPU任务。
- 原性能文档“确定性生成”改为固定seed采样长描述、中短贪心，不承诺跨环境逐字一致。

## Timing evidence

从2026-10-26的原始数值报告重新聚合，16张的JoyCaption前11阶段共**101.290秒**，即6.33秒/输入图。其中水印41.605秒、文字33.717秒，合计74.36%。非caption模型身份校验另为1.258秒；JoyCaption身份校验187.398秒排除。原有输入快照/API登记等约4.88秒没有进一步拆分，不能全部硬计为前置阶段。

这是历史`e7d5a9b`、单5090、网络盘、新结果缓存、未清页缓存、实际裁剪0的计量。不是当前v0.15重测，也不覆盖实际裁剪编码和新增残余检测的生产成本，不能推算为四卡实测。安全数值JSON及源报告SHA保存在运行时`docs/evidence/pre-caption-timing-20261028.json`，真实图片/描述/原日志不入Git。

## Verification

- Workbench226项回归，296.203秒，连接专用本地开发PostgreSQL，各测试隔离schema，全部通过、无跳过。
- 官方JoyCaption配置5项通过，无模型加载。
- 文档两个Python片段通过语法与合成执行，错误view绑定被拒绝，输出不含夹具私有文本；7组命令与当前CLI parser一致。
- node94另存配方的离线model-plan通过；仅watermark、text、caption_long启用，每阶段1 worker。路径/磁盘为只读现场检查，新配方只改变结果缓存位置。
- 本轮修改文档及私有部署配置，不修改后端算法或UI，不重计网页、真实质量或GPU吞吐验收。OpenSpec严格校验及同步随本轮交付完成。

原任务2.5（定制旧direct集成）和6.4（真实质量）保持未完成，不archive。新增交接任务不替代它们。

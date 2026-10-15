# Spec Delta

## Purpose

本能力负责数据版本与训练交付，为图像训练数据全流程提供独立、可追溯且可验证的行为契约，明确输入处理、失败结果和下游使用边界，支持后续分阶段实现与验收。

## ADDED Requirements

### Requirement: 固定发布与校验

系统 SHALL 固定成员、视图、标注、配方、划分、分片和校验摘要；仅在全部校验通过后发布。

#### Scenario: 某分片缺少图片或 caption
- **WHEN** 某分片缺少图片或 caption
- **THEN** 发布失败且无可见 ready 版本，已上传分片保留待恢复。

### Requirement: 导出格式与实际读取

系统 SHALL 支持标准 manifest 及按适配器声明的训练格式，使用真实加载路径检查字段、解码、尺寸和样本数。

#### Scenario: 目录 sidecar 或 WebDataset 分片导出成功
- **WHEN** 目录 sidecar 或 WebDataset 分片导出成功
- **THEN** 相应加载器读取验证通过后才允许发布；未实现格式返回明确不支持。

### Requirement: 可恢复与增量发布

系统 SHALL 复用不变产物，支持中断恢复，成员变化产生新版本。

#### Scenario: 构建中断后恢复且输入未变
- **WHEN** 构建中断后恢复且输入未变
- **THEN** 复用已验证分片，最终清单无重复或缺失。

### Requirement: 撤回与可追溯历史

系统 SHALL 标记撤回发布并阻止新消费，保留审计事件及历史摘要；按删除策略处理实际文件。

#### Scenario: 来源撤回影响已发布版本
- **WHEN** 来源撤回影响已发布版本
- **THEN** 列出影响范围，撤回状态可查；删除事件与剩余审计信息明确可见。

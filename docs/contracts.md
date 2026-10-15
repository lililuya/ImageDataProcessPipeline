# 数据与配置契约草案

状态：设计示例，尚无运行时校验器。正式 schema 与迁移由 tasks.md 第1–2组实现。以下省略示例中的摘要长度，不是可直接发布的生产数据。

## 1. 发布成员

```json
{
  "schema_version": "1.0",
  "sample_id": "sample:example",
  "task_type": "edit",
  "images": [
    {"role": "source", "ordinal": 0, "asset_id": "sha256:source", "view_id": "view:source", "uri": "objects/source.png", "checksum": "sha256:source-view"},
    {"role": "target", "ordinal": 0, "asset_id": "sha256:target", "view_id": "view:target", "uri": "objects/target.png", "checksum": "sha256:target-view"}
  ],
  "instruction": "将杯子从红色改成蓝色，保持背景和形状不变。",
  "caption_ref": null,
  "annotation_refs": ["annotation:instruction-v1"],
  "review_refs": ["review:edit-direction", "review:preserve"],
  "group_id": "group:example",
  "split": "train",
  "recipe_digest": "sha256:recipe",
  "sampling": {"weight": 1.0, "policy_version": "sample-v1"}
}
```

image role与ordinal联合唯一；target数量按任务约束。edit需要source、target、instruction；多参考输入为有序reference；preference需要相同condition_digest和chosen/rejected；image-only需要condition_strategy及兼容能力声明。T2I需要有效caption_ref，不能依靠空字符串模拟其他任务。

## 2. 标注结果

```json
{
  "schema_version": "1.0",
  "annotation_id": "annotation:example",
  "subject_ref": "view:example",
  "producer": {"provider": "configured-provider", "model_digest": "sha256:model", "prompt_digest": "sha256:template", "config_digest": "sha256:config"},
  "caption_short": {"text": "蓝色杯子放在木桌上。", "language": "zh"},
  "caption_long": {"text": "木桌中央放着一个蓝色杯子。", "language": "zh"},
  "render_text": [],
  "knowledge": [],
  "reviews": {"caption_fidelity": "pending", "ocr_usability": "na"}
}
```

正式实现中每个字段可独立版本化；此示例只展示聚合输出。render_text元素需要原文、语言、polygon、坐标系、阅读顺序与置信信息。知识元素需要evidence_ref与verified状态。不支持语言和任务超时使用独立状态，不等价于空数组。

## 3. 配方示意

```yaml
schema_version: '1.0'
name: t2i-general-pilot
status: uncalibrated
task: t2i
target:
  model_adapter: to-be-selected
  checkpoint_digest: null
inputs:
  snapshot: to-be-frozen
eligibility:
  source_policy: approved-for-purpose
  required_observations: [decode]
annotation:
  variants: [short, medium, long]
  review_policy: to-be-calibrated
views:
  target_area: 1048576
  bucket_policy: adapter-defined
  allow_upscale: false
sampling:
  seed: 42
  domain_weights: null
  provenance_weights: null
split:
  strategy: connected-groups
  seed: 42
export:
  adapter: manifest
```

null与to-be-*表示设计待填参数，生产构建校验应拒绝未绑定checkpoint、未冻结快照、未校准必需审核等状态。配比不填写默认“行业最佳值”。所有默认值在生成摘要前展开，改动产生新配方。

## 4. 统一原因码与状态

| 范围 | 示例 | 处理 |
|---|---|---|
| 输入 | DECODE_CORRUPT / PIXEL_LIMIT / FORMAT_UNSUPPORTED | 隔离或明确不支持 |
| 执行 | PROVIDER_TIMEOUT / RATE_LIMIT / WORKER_OOM | 按错误类型有限重试 |
| 标注 | SCHEMA_INVALID / CAPTION_HALLUCINATION / OCR_UNCERTAIN | 字段重做或复审 |
| 视图 | SUBJECT_CROPPED / TEXT_UNREADABLE / ALPHA_EDGE | 换视图、重标或配方拒收 |
| 任务 | EDIT_REVERSED / CONDITION_MISMATCH / ADAPTER_UNSUPPORTED | 拒绝任务样本或适配器 |
| 发布 | SPLIT_LEAKAGE / MISSING_ARTIFACT / CHECKSUM_MISMATCH / SOURCE_WITHDRAWN | 阻止ready或撤回 |

所有错误包含安全subject/job标识、producer版本、是否可重试、发生时间和结构化详情。质量决策引用原因码与对应观测，不向资产写入不可解释的全局bad=true。

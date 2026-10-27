# ImageCaption v0.13：单长描述与可选VLM

2026-10-27。实现位于ImageCaption运行时仓库 `codex/imagecaption-workbench-v0.2`，提交 [970c97d](https://github.com/lililuya/ImageCaption/commit/970c97d9586ce5ee431ae0c428dce49984487db1)；本仓库维护OpenSpec和交付记录。

当前新工作流采用JoyCaption只生成一条详细长描述；关闭中短阶段及对应调用，完整性、条件和发布按选中类型核验。旧配方省略类型字段时保持三档。版本、标注、审阅包及训练索引记录模型名称、修订、后端、权重和provider摘要，不污染纯文本prompt；网页配置及结果显示生成来源。

新增Huihui Qwen3-VL本机后端，通过model_profiles和 `--caption-profile` 选择；已有OpenAI兼容API继续支持其他VLM。`--caption-variants long`明确当前类型。更换模型使用新state，不修改历史冻结身份。保留双评分关闭、短边512、0.15 byte/pixel及默认裁剪。

验证：219项后端及隔离数据库回归通过；单长测速统计追加后4项专项通过；结果页103项与配置页66项合成浏览器检查通过，覆盖1440/1024/760/390和200%缩放；前端构建通过。node94 GPU2真实JoyCaption和Huihui Qwen3-VL BF16各处理2张合成图，全部只生成long，中短零调用。两个版本的配置已同步，合成审阅包已接入本地网页。小样本冷启动和缓存不同，不据此给出生产吞吐排名；新量化路径与真实质量未验收。

本地网页/API及node94独立v0.13部署目录已更新，原Demo及其他GPU任务保持运行。初次配置摘要字段上限问题已修正；从冻结计划补同步保持原版本身份，不重复生成。测试详情、启动命令及配置示例见运行时仓库：

- [模型选择与单长启动](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-caption-models.md)
- [v0.13验证与部署范围](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.13-validation.md)

本轮不查看真实图片、描述或OCR，不进行真实质量、实际裁图或四卡吞吐验收；两个合成版本仍为待审草稿。既有未完成任务保持未勾选，不archive。

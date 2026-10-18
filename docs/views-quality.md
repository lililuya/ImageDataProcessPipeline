# 训练视图与独立质量观测

本阶段实现对应任务4.2、4.3与7.1：程序化方向/色彩/透明通道处理、可复现分桶裁剪，以及独立数值观测。标注匹配、人工图像审核、训练端增强和数据发布尚未因此完成。

## 变换协议

输入必须是本地内容寻址存储中的已登记资产，执行前验证SHA-256。显示方向先按EXIF处理，后续裁剪框统一使用`exif-transposed-pixels`坐标；原始字节不覆盖。

带ICC的受支持图像通过LittleCMS转换到sRGB；无ICC的RGB/灰度明确记录假定sRGB。无ICC的CMYK/LAB、无法解析的ICC、高位深输入、多帧输入等返回独立受控原因码，不能静默量化或当成普通RGB。LAB的A/B通道是色彩通道，不按透明通道处理；本次同时修正基础probe判定，并将probe版本从2升级到3，旧观测保留。

输出为RGB或RGBA PNG，清除EXIF和其他源元数据，仅写固定sRGB标记。没有嵌入运行时生成、可能包含时间戳的ICC字节。环境摘要包含Pillow、LittleCMS、zlib、JPEG库和Python版本；配置默认值展开后纳入摘要。

alpha默认保留，`reject`拒绝带alpha输入，`composite`必须提供显式背景RGB。RGBA缩放采用预乘alpha处理，避免透明区域隐藏RGB污染边缘。没有给真实数据生成或展示预览。

## bucket与裁剪

`configs/view-512.json`是工程试点配置，不是某个模型的已验证训练配方。选择最接近源长宽比的候选bucket，尺寸对齐patch；候选面积与目标偏差限定在25%以内，无法表示时拒绝配置，而非隐藏改变预算。

裁剪宽高保持与目标bucket完全相同的整数比例，再统一缩放。默认禁止放大；允许放大时单独记录upscale_factor、有效输入像素、裁剪框与尺寸。center居中，random由输入摘要、seed与bucket确定；同一环境下重复构建得到相同视图ID和输出校验值。

视图记录包含输入/输出摘要、方向、配置/环境版本、裁剪框、目标尺寸、插值、alpha策略和seed；details包含裁剪坐标语义、颜色假设、源ICC摘要、放大倍数和有效分辨率。所有视图初始标记为`requires-view-specific-annotation-or-audit`，不会自动继承原图caption。

## 独立质量观测

每项观测保留输入摘要、producer和配置版本。使用sRGB显示图像缩略到最大边256，仅在内存中计算，不保存该分析缩略图。

| 指标 | 定义/边界 |
|---|---|
| width / height | EXIF纠正后的输入尺寸 |
| bytes_per_pixel | 原文件字节数除以输入像素数；受格式、压缩和元数据影响，不等于压缩质量模型 |
| entropy_luma | 8位亮度直方图Shannon熵 |
| laplacian_variance | 有符号四邻域拉普拉斯方差；受分析尺度影响，不是通用清晰度评分 |
| opaque_fraction | 分析图像中完全不透明像素比例 |
| near_black/white_fraction | 完全不透明像素中亮度≤4或≥251的比例 |

alpha图仅用完全不透明像素统计，不将透明像素的隐藏RGB当作内容。无可用像素时返回null；没有可用拉普拉斯邻域也返回null。真实0值与缺失值不同。

## 数值配方

`quality-check`按给定领域配方独立决定accept/reject/needs_observation，保留配方摘要、完整观测摘要、缺失字段及失败字段，不向原始资产写全局好坏状态。同一观测可以被两个领域配方作不同决定。

`configs/quality-unverified-example.json`未校准。accept只说明满足本次数值规则，`passes_calibrated_rules=false`时不能视作通过校准；即使数值规则通过，来源授权、监督质量、任务兼容和发布检查仍需单独完成。后续7.4新增[版本化选择配方](recipes.md)，可固定观测与决策并绑定最小发布；领域路由、采样与完整多阶段引擎仍未完成。

## 命令与数据库

代码更新后先执行数据库v4追加迁移，新增transform_configs与views表。视图、质量观测、产物引用和任务成功状态一起提交，注册失败回滚；仅上传未提交的对象不会解锁下游。

```bash
idp db migrate
idp jobs enqueue-quality --batch-id private-pilot-v1 --limit 64
idp jobs enqueue-views --config configs/view-512.json --batch-id private-pilot-v1 --limit 64
idp worker --max-jobs 128
idp jobs metrics
idp quality /path/to/synthetic-image.png
idp quality-check --recipe configs/quality-unverified-example.json --observation observation.json
```

以上是本轮代码接口，node95部署是否完成以[实施状态](implementation-status.md)为准。不要在只有旧版本代码的机器上假定这些命令已存在。私有数据只输出任务数量与匿名ID，像素文件与单样本标注不提交Git。

测试使用代码生成的方向、ICC/LAB、透明边缘、高位深、多帧、清晰/模糊夹具，以及真实隔离PostgreSQL数据库。包含视图注册失败注入、回滚后恢复、配置变化版本隔离和CLI集成验证。

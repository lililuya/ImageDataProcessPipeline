# ImageCaption v0.7：裁剪开关、元信息与可选标签

2026-10-23，运行时代码已同步至`codex/imagecaption-workbench-v0.2`分支提交[`8d1718f`](https://github.com/lililuya/ImageCaption/commit/8d1718f38f67f635c201ce890f9c39af1612ce95)。本轮只核对代码与合成夹具，没有打开真实图片、caption、OCR或v0.6审阅页，也未重新部署node95模型。完整运行方式见远端[README](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/README.md)和[启动及核验手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-startup-verification.md)。

## 已实现

- `crop.enabled`默认true，严格布尔；CLI支持`--crop/--no-crop`。关闭裁剪不关闭水印检测，不使水印自动消失或绕过分流。
- 有效非重复视图记录独立`crop_metadata`：开关、实际裁剪、EXIF转正坐标空间、前后尺寸、方向、计划及实际框、保留面积比例、原因和策略摘要。仅整图重编码不标为cropped。
- 按用户确认，只对实际裁后视图生成long，中短引用该long，不额外推理原图三档。来源资产保留，不将删水印句视为新视图审核。
- 此前独立关键词脚本未集成。此次增加可选`semantic_tags`阶段，`tags.enabled`缺省false，CLI支持`--tags/--no-tags`，需开启captions并配置`providers.tags`。支持JoyCaption纯文本复用及本地兼容接口，词表仅非露骨姿态、构图、视角、可见度和内容安全大类；不生成具体性行为细节。
- 标签绑定当前view与long，保留模型、模板、词表和来源ID，未知/不支持/缺配置/依赖失败/失败各有状态。标签始终待审，不拼入训练条件、不改变准入；原文证据不进入持久结果，现有本地临时文件IPC可能短暂含源文本和证据。
- 新版本18个阶段；禁用标签不校验/加载模型，界面正确展示阶段、原因和关闭状态。审阅包保存裁剪元信息、标签和每样本`tags.json`；计划/实际框和标签来源篡改会阻断导出。版本diff能显示裁剪决策或标签变化，即使图片和描述没变。

## 核验

| 核验 | 结果 |
|---|---|
| Workbench契约、API、集成及恢复 | 172项全通过，230.376秒，无skip；使用隔离PostgreSQL schema |
| 最终版本差异补充及相关定向回归 | 32项通过，23.424秒；其中新增差异测试1项，当前清单173项，不与前一行重复累加 |
| 合成浏览器 | 引导61项、关闭166项、新标签193项，共420项；无浏览器错误、写请求、媒体或外部请求 |
| 前端 | TypeScript检查和生产构建通过 |
| README | 本地链接、代码块、CLI参数解析、PowerShell语法和两种标签配置生成检查通过 |
| OpenSpec | `validate --all --strict`两项change通过；npm未在PATH，使用同一OpenSpec Node入口执行等价校验 |

完整审核见运行时[流程与验证记录](https://github.com/lililuya/ImageCaption/blob/8d1718f38f67f635c201ce890f9c39af1612ce95/docs/workbench-v0.7-validation.md)。本轮修复的边界包括裁剪计划框绑定、标签缺父描述时误入图像读取、标签到export恢复依赖及旧17阶段测试口径。

## 交付边界

这是本地实现和Git同步，当前远程服务不会自动升级。v0.6原始审阅包不回写；使用新代码、开关或标签配置时创建新state/版本。新标签的真实准确率、输出长度预算和速度尚未验证；不把v0.6单卡测量当成本版或四卡吞吐。真实水印/文字/质量与描述人工校准、旧direct全阶段进度钩子以及四卡调度仍待后续。任务12的实现与验证不扩大旧任务2.5、6.4的完成范围，不archive此change。

# ImageCaption v0.4模块审核与容量验证

本轮在v0.3上补充逐模块形式审核、真实处理计时和四卡容量建模，继续使用[原产品change](../openspec/changes/build-imagecaption-data-workbench/proposal.md)。当前实现与建议、单模块实测与全流程估算分开记录；生产目录和历史批次未替换，真实图片、标注、模型与逐图记录不进入仓库。

## 审核修复

- 恢复时重新校验原始输入和已提交产物，旧checkpoint不能替代当前字节核验；重新启动模型worker时重新检查冻结文件身份。
- 按冻结输入总字节量建立预算，移除继承解压器默认200GB导致的大批次失败，允许显式设置预算。
- 可选精确像素去重保留EXIF方向、透明度、ICC和高位深，不将它称为近重复检测。
- 检查评分尺度、异常坐标和文字框数量；校准报告额外绑定provider预处理参数，改变检测分辨率不能继续沿用旧校准。
- 增加登记前本地输入/模型校验进度；新运行在冻结身份后登记，未把登记前状态冒充远端运行。
- 结果缓存可与图像对象分盘；构建期保留空闲SQLite连接减少WAL收尾开销，仍逐项FULL持久提交，进程中断恢复有测试证据。
- 增加数值性能工具、GPU文本环境和JoyCaption依赖清单；中短摘要可显式复用JoyCaption语言模型，保持语义审核未通过状态。

## 证据位置与边界

ImageCaption中的`docs/workbench-module-audit.md`覆盖扫描、存储、像素、去重、检测、裁剪、评分、分流、三档描述、最终条件、导出、恢复及控制面。`scripts/workbench_*profile.py`记录确定性抽样、首次与稳定调用、CPU并行、实际读写、数值状态及资源采样；`workbench_capacity.py`只计算显式假设下的容量，不启动多卡调度。

真实输入只由本地程序处理，未查看像素或显示OCR/caption。GPU共享测试不终止他人任务，不清除系统页缓存；四卡没有独占实测，不能把单卡结果乘四后称为验收。CPU文字检测、模型加载和共享机械盘的持久化开销均纳入报告。人工作业等待、真实误检、审美门槛、描述事实质量和训练效果仍未验收。

追加7.1–7.5完成时为43/45项，质量模型独立开关8.1–8.2完成后为45/47项；随后文件密度门控及prompt标签选型9.1–9.3已验收，当前累计**48/50项**。原任务2.5定制旧direct全阶段钩子和6.4人工校准保持未完成，不archive。

## 本轮验收结果

- 确定性真实样本64张：水印YOLO、CPU及GPU整图文字、ArtiMuse、DeQA均完成64/64请求；格式与实际加载器、CPU解码、O_DIRECT文件核验均通过。裁剪计时另取8张固定几何探针，不是主体保留验收。
- GPU 2上的三档描述各16/16成功，稳定平均长7.01秒、中3.77秒、短2.22秒，合计13.01秒/保留图片；平均生成151/115/69 token。输入SHA复核一致，测试后显存释放到15MiB。未查看生成文本或图片，没有质量审核通过记录。
- 测得GPU文字约1.269张/秒、ArtiMuse约0.695、DeQA约0.626；DeQA局部batch=4相对同轮batch=1约1.59倍，尚未自动接入版本构建。
- 本机机械盘共享负载下O_DIRECT读取加哈希约14.58MiB/秒；FULL持久状态在HDD与NVMe上的差异显著。四卡情景同时约束计算与IO，不直接乘四。
- 假设25%裁剪、全部输入生成三档：元数据放NVMe时，当前单实例约142–154输入/小时，四独立副本服务上界约446–632输入/小时；该估算不包含人工作业、全量控制面、启动与重试，不是四卡实跑或交付承诺。共享HDD同时承担元数据时，估算显著更低。
- 专项58项全部通过；全量244项中232通过、2跳过、10项失败/错误与v0.3基线集合相同。严格OpenSpec验证2项通过。代码修复不宣称已消除旧系统的所有失败。

详细方法、全部模块速度、冷启动、三档长度、失败重测记录、容量公式和优先优化项见ImageCaption的[模块审核](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-module-audit.md)及[性能报告](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.4-performance.md)。实际数据批次的完成时间情景和数字记录只保存在仓库外，不发布真实目录、逐图信息或语义输出。

本地证据根为`E:/Codex_Data/ImageCaptionWorkbench/v0.4`；node95证据根为`/mnt/hd4/ImageCaptionWorkbench/v0.4`。源代码测试快照与最终Git代码分别留证，没有覆盖原生产项目。用户授权的GPU 2测试已经结束，其他三卡训练未中断。

模块审核与性能验证对应ImageCaption提交[`bce7ae7`](https://github.com/lililuya/ImageCaption/commit/bce7ae7a4d2578ec3afccf27c6f4386e707688a4)，保留在[草稿PR #1](https://github.com/lililuya/ImageCaption/pull/1)，未合并主分支。

## 追加：ArtiMuse与DeQA独立执行开关

两项评分默认开启，分别通过`quality.aesthetic.enabled`、`quality.technical.enabled`或CLI的`--no-aesthetic`、`--no-technical`关闭；显式`--aesthetic`、`--technical`可覆盖配方。`build`和`dry-run`使用同一套配置解析，`required:false`仍表示执行评分但不按分数筛选。

关闭后跳过该模型的文件校验、加载、推理及校准报告依赖；观察为`disabled/null`，不生成评分缓存或虚假通过结果。已有无开关配置的版本身份、登记重放和校准摘要保持兼容。开关写入冻结版本，在原state中改变开关会被拒绝，重新启用须创建新版本并补算缺失评分。

终端、本地/API快照和网页明确显示“已关闭”，评分工作量为零且不计入验收分母；保留原`stage_count`字段口径，追加关闭数及开启阶段数。其他像素、水印、文字、描述审核与发布检查继续生效。dry-run将关闭与未知分开统计，不将历史分数当作关闭版本的新观测。

关闭评分后新进入主集的样本，dry-run同时列出缺失描述/完整条件涉及的阶段与候选数；已有绑定当前视图的描述保留复用资格，不把所有阶段范围都当作必须执行的GPU任务。

验证仅使用本地合成夹具，未访问真实图片、语义结果或GPU，也未改动现有8841服务：

- Workbench专项**69项全部通过**，覆盖四种开关组合、模型路径不可访问时关闭可运行、校准绑定、分流、实际导出读取、版本冻结、恢复及服务端重放/事务回滚。
- 全量**255项：243通过、2跳过、10项失败/错误**；失败集合与244项旧基线相同，涉及旧CPU任务领取、Windows `fcntl`和日志上传夹具，未因本改动新增失败。
- 前端TypeScript/Vite构建成功；独立临时端口、合成API和无头Edge完成四种组合、四次刷新及1440/760/480px检查，共166项断言，无溢出、浏览器错误、写请求或媒体请求。
- OpenSpec严格校验2项通过。仓库外证据为本地v0.4根中的`tests-quality-switches.log`、`full-tests-quality-switches.log`及`browser-quality-switches.log`；dry-run最终复核扩展既有测试并再次通过，记录于`quality-switch-dry-run-test.log`。运行时使用说明见`docs/workbench-v0.3.md`。

本次开关在本地完成实施和验证，未部署到node95，不将此前实测速度视为关闭后的新吞吐结果。

质量模型开关对应运行时提交[`ced37b6`](https://github.com/lililuya/ImageCaption/commit/ced37b60ad192d1f31c2b71189dba6f0439cd28a)，已同步至原草稿PR #1分支。

## 追加：原始文件密度门控与prompt标签模型选型

按用户要求增加`pixels.min_bytes_per_pixel`，示例配方为0.15 byte/pixel；CLI通过`--min-bytes-per-pixel`调整或`--no-byte-pixel-gate`关闭。旧配方省略/null保持关闭，显式数值必须有限且非负。门槛随版本冻结，原state不能变更策略；新版本可复用既有图像评分，仅对新准入且缺少描述的成员补生成。

密度观测使用原始文件实际字节与解码尺寸，绑定source SHA并记录原始格式；裁后PNG或其他重编码体积不能替代原始观测。门控在既有selection阶段执行，阶段数保持17。低于门槛或原始证据缺失阻止主集及辅助训练准入，原图、观测和原因保留；CLI及网页显示中文原因。此启发式门槛不构成真实画质或误删率验收，不声称已在评分之前提前省去GPU工作。

首次Workbench回归**77项全部通过**，含新增8项契约与集成；验证0.15含边界、非法参数、未知原始证据、低密度JPEG裁成较大PNG仍不放行、评分复用、同版本冻结、实际导出读取和恢复。前端TypeScript/Vite构建通过。证据保存在仓库外v0.4根的`byte-pixel-tests.log`及`byte-pixel-workbench-tests.log`。本轮未再次运行旧系统全量套件，不将前轮255项结果当作本轮新实测。

最终复核将有效辅助审核与准入结果分开保存，补上门槛放宽后辅助样本的描述补算提示；旧清单缺审核仍为待审核。显式整数/浮点门槛归一，避免0与0.0导致策略摘要漂移。修正后的8项定向回归全部通过，日志为`byte-pixel-admission-tests.log`。OpenSpec严格校验2项通过。

重新核对LLaDA-Image §3.2，并完成[已有prompt语义标签化模型选型](research-evidence.md#prompt语义标签化模型选型2026-10-22)：优先对比Qwen3.8-27B与Hermes-4.3-36B，Gemma 4与GLiNER2.5可作结构化/吞吐对照。记录官方许可证、任务证据边界与单卡量化部署建议，区分NSFW粗分类与多维语义标签。尚未部署标签模型或验证本项目标签质量与速度。

本轮仅使用本地合成图像、模型响应与隔离数据库；没有查看真实图片/语义内容、操作node95或占用GPU。原始资料、模型权重和测试产物不入Git。

本轮运行时提交为[`d42e84e`](https://github.com/lililuya/ImageCaption/commit/d42e84e4abfe7a980b4aaf719f42e9cc8783603a)，已同步至原草稿PR #1分支，未合并或部署node95。

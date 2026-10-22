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

本轮追加7.1–7.5均有相应证据，累计**43/45项**；原任务2.5定制旧direct全阶段钩子和6.4人工校准保持未完成，不archive。

## 本轮验收结果

- 确定性真实样本64张：水印YOLO、CPU及GPU整图文字、ArtiMuse、DeQA均完成64/64请求；格式与实际加载器、CPU解码、O_DIRECT文件核验均通过。裁剪计时另取8张固定几何探针，不是主体保留验收。
- GPU 2上的三档描述各16/16成功，稳定平均长7.01秒、中3.77秒、短2.22秒，合计13.01秒/保留图片；平均生成151/115/69 token。输入SHA复核一致，测试后显存释放到15MiB。未查看生成文本或图片，没有质量审核通过记录。
- 测得GPU文字约1.269张/秒、ArtiMuse约0.695、DeQA约0.626；DeQA局部batch=4相对同轮batch=1约1.59倍，尚未自动接入版本构建。
- 本机机械盘共享负载下O_DIRECT读取加哈希约14.58MiB/秒；FULL持久状态在HDD与NVMe上的差异显著。四卡情景同时约束计算与IO，不直接乘四。
- 假设25%裁剪、全部输入生成三档：元数据放NVMe时，当前单实例约142–154输入/小时，四独立副本服务上界约446–632输入/小时；该估算不包含人工作业、全量控制面、启动与重试，不是四卡实跑或交付承诺。共享HDD同时承担元数据时，估算显著更低。
- 专项58项全部通过；全量244项中232通过、2跳过、10项失败/错误与v0.3基线集合相同。严格OpenSpec验证2项通过。代码修复不宣称已消除旧系统的所有失败。

详细方法、全部模块速度、冷启动、三档长度、失败重测记录、容量公式和优先优化项见ImageCaption的[模块审核](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-module-audit.md)及[性能报告](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.4-performance.md)。实际数据批次的完成时间情景和数字记录只保存在仓库外，不发布真实目录、逐图信息或语义输出。

本地证据根为`E:/Codex_Data/ImageCaptionWorkbench/v0.4`；node95证据根为`/mnt/hd4/ImageCaptionWorkbench/v0.4`。源代码测试快照与最终Git代码分别留证，没有覆盖原生产项目。用户授权的GPU 2测试已经结束，其他三卡训练未中断。

运行时代码已同步至ImageCaption提交[`bce7ae7`](https://github.com/lililuya/ImageCaption/commit/bce7ae7a4d2578ec3afccf27c6f4386e707688a4)，保留在[草稿PR #1](https://github.com/lililuya/ImageCaption/pull/1)，未合并主分支。

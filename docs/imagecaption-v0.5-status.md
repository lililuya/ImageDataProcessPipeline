# ImageCaption v0.5：描述研究、看板使用与恢复

验收日期：2026-10-23。沿用[当前OpenSpec change](../openspec/changes/build-imagecaption-data-workbench/proposal.md)，重点解决看板难以理解和排错、描述worker无效重载、发布异常状态失真的问题。本轮只使用合成图像、合成模型响应和隔离数据库，没有读取真实图片、真实caption/OCR，没有操作node95或运行GPU模型。

## 本轮交付

- 看板增加首次使用说明、版本选择、当前动作、问题定位、流程分组和阶段筛选；明确构建、图像准备与训练发布的区别。刷新不会自动切走用户选定的运行，链接可固定运行UUID。
- 加载、空列表、服务连接失败分别显示；过期、无进展、历史运行和离线时不展示可信速率或ETA。图片计数、阶段状态、心跳和服务端收到时间分别解释，分流与复核不冒充执行错误。
- 提供按症状组织的CLI排错指引和白名单诊断下载/复制；诊断不含数据集名、路径、图片、prompt、OCR、自由文本异常或令牌。当前API仍只提供聚合原因，根因须在执行机器检查，不能仅凭看板判定OOM。
- 小屏下导航可折叠，保留键盘操作和清楚的页面标题。关闭ArtiMuse/DeQA时继续显示“已关闭”，不制造分数或工作量。
- 内置JoyCaption worker确认支持逐请求选项协议后，长中短切换生成上限、seed、语言和超时可复用进程；固定模型、代码、设备、精度或启动配置变化仍重载。旧worker继续保守隔离，完整变体配置仍进入缓存身份。
- 发布增加心跳及导出、登记、回执写入异常的失败事件。失败后直接重跑原`publish`，重新核验字节并幂等恢复登记；另一配置的重新打包失败保留此前有效发布。服务端已登记而本地回执失败的情况有独立测试。

实际操作见运行时仓库的[看板使用与排错手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-dashboard-guide.md)。看板为只读监控，复制命令不执行操作：普通构建失败修复环境后执行`retry`，再重跑原`build`；打包发布失败直接重跑原`publish`；事件积压用`sync`。三者不能互相替代。

## 研究结论与实现边界

新[描述、标签与吞吐研究](caption-tagging-and-throughput-review.md)核对MOSS、LLaDA-Image、RECAP、SD3、FaithScore及JoyCaption、Florence-2、WD Tagger、vLLM等一手资料，保留版本、来源和适用范围。MOSS多粒度监督与后训练JSON指南分别引用，不混淆原始/重标注配比和长中短采样配比。

建议保留自然语言描述，另外生成带文本证据、实体关系、否定/不确定性和词表版本的语义标签。中、短分别引用同一长描述，避免逐级压缩放大遗漏；文本蕴含不能证明父描述与图像一致。当前一致性检查偏向英文数字/方向集合，中文实体关系与语义判断仍不完整；新标签模型尚未接入，不能称为已验收标签系统。

性能路线按已有瓶颈排序为状态/缓存放SSD、减少模型重载、有界解码预取、阶段内批请求，再比较四卡分片与模型并行。本次只完成worker复用的代码与合成契约验证，没有新增真实GPU吞吐。2026-10-22的单卡历史数字继续见[v0.4记录](imagecaption-v0.4-status.md)，不得将本次修复与旧数字拼成加速倍数；自动批调度和四卡协调仍未实现。

另有明确待办：多阶段`retry`中断后的整体恢复计划、结构化provider错误到看板的白名单传递、在途工作遥测和更细粒度缓存依赖。记录于运行时[模块审核](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-module-audit.md)，没有把发现问题当成已修复。

## 验证证据

- Workbench相关回归**96项全部通过，202.361秒**，包含原有契约、真实隔离PostgreSQL事务、CLI集成、恢复及实际导出读取，以及新增8项worker复用和11项发布故障测试。
- 前端TypeScript/Vite构建通过。新看板浏览器测试**10个场景、61项检查**通过，覆盖加载、空列表、运行、失败、复核、过期、离线、历史、图像准备完成和已发布等状态，以及运行选择、深链接、诊断白名单、响应式和键盘导航。全部API响应为测试夹具，不读取真实运行内容。
- 独立评分开关浏览器回归**166项检查**通过，覆盖四种组合、四次刷新及1440/760/480px。两组浏览器测试均无浏览器错误、写请求、媒体请求、外网请求或横向溢出。
- `npm run spec:validate`严格验证2项通过。OpenSpec任务累计**52/54项**；本轮10.1–10.4有研究、契约、集成、恢复及交互证据后勾选。
- 本轮不重复执行旧系统全量套件；此前255项中的10项旧失败/错误仍为历史未解决基线，96项通过不能解释为整个旧系统无失败。
- 证据根为仓库外`E:/Codex_Data/ImageCaptionWorkbench/v0.5`；数值日志和合成截图不进入Git。真实素材、模型权重与凭据未入库。

对应日志为`workbench-regression.log`、`browser-guidance.log`和`browser-quality-switches.log`。发布故障分支使用合成API，现有正常发布集成使用真实隔离PostgreSQL；没有将这些测试表述为所有远端网络故障或模型真实质量已验证。

本轮未部署node95、未替换生产CLI、未合并草稿PR。原任务2.5的定制旧direct全阶段钩子、6.4的真实人工质量校准仍未完成，change不得archive。

运行时对应提交[`56df761`](https://github.com/lililuya/ImageCaption/commit/56df76198574518c912d225fcc4161c3559bf8df)，已同步至原[草稿PR #1](https://github.com/lililuya/ImageCaption/pull/1)分支。本地前端已构建，可在现有8841服务刷新查看；这不表示服务端进程已重启载入本轮Python修改，执行新CLI会读取当前源码。

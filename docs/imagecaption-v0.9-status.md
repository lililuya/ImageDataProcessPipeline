# ImageCaption v0.9：模块化推理与吞吐

2026-10-24，用户明确暂不实施GBC，优先吞吐，并要求模型选择与部署后端对上层透明。

## 已实现与验证

模型配置注册`model_profiles`、阶段绑定、离线`workbench model-plan`；保留command常驻模型，新增OpenAI兼容图文后端及同模型多端点容量池。本机vLLM和多机服务使用同一接口，vision/text能力显式声明，远端修订记录为部署声明，不冒充权重字节校验。

新增可选`execution.stage_workers`，默认1，首版支持pixels与fixture/API阶段的有界并行。相同在途身份合并、乱序结果单一提交、返回顺序稳定；保留阶段屏障、裁剪视图、父描述、缓存重验和审核要求。command并发大于1登记前拒绝，避免共享子进程和显存争抢。本地CLI提供执行统计，网页仍使用既有进度，新模型编辑/集群面板未实施。

验证分两部分完成：154项非数据库Workbench回归通过，其中新增12项后端/调度测试；31项隔离PostgreSQL集成测试通过，覆盖版本、发布、开关与恢复。最初数据库连接的用户/库名颠倒导致初始化失败，按既有runbook修正后独立重跑31项全部通过。模型与图像内容均为合成夹具。

最终合成延迟基准为24项工作、每请求100ms注入延迟、3轮交替顺序、显式HTTP预热、各轮独立缓存。串行墙钟中位数2.7216秒，四并发0.7625秒，比值3.57；每轮24成功、0失败，峰值在途1/4。仅验证等待重叠，不能当作真实GPU吞吐、四卡容量或质量收益。汇总在仓库外`E:/Codex_Data/ImageCaptionWorkbench/v0.9/synthetic-throughput.json`。

## 代码及操作入口

- ImageCaption分支：`codex/imagecaption-workbench-v0.2`。
- GitHub提交：`1e714a77f7ee4417072cb520646b19630dd473d0`；树摘要：`25e8b0ccda2545c2cfdfef824d7a5c1ce097af51`。
- 本地最初提交`b1cdaf0`；SSH密钥认证失败后，使用已连接GitHub接口创建同树提交并校验每个blob/最终tree。本地已导入验证通过的远端commit并对齐分支，无文件差异。
- [模型与后端配置](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-model-backends.md)、[验证记录](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.9-validation.md)、[启动核验手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-startup-verification.md)。

两仓库同步状态以本条记录所在提交和最终任务勾选为准。本轮未在node95部署，未启动实际GPU作业，没有更新现有服务的运行身份。代码/配方改变须创建新state/version；旧运行用冻结代码恢复。

## 保留边界

没有GBC、LangGraph、原生gbc host、自动GPU/服务部署、健康摘除、自动故障切换或本机通用张量batch。模型服务需独立部署；服务端负责实际合批。接口细分错误码尚未全部投影到caption持久清单和网页，限制已写入操作说明。

真实模型兼容性、单卡/四卡吞吐、真实标注/裁剪/质量阈值仍需单独验收。旧direct完整进度与真实质量校准仍为未完成任务，不因本轮合成测试而勾选或archive。

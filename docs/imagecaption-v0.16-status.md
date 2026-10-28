# v0.16：三模型驻留与热全流程验收

2026-10-28，落实用户要求：在node94预加载YOLO水印、Paddle文字检测及JoyCaption，模型初始化一次，连续接收任务，单独测量排除初始化的完整流程。

运行时新增`ResidentProviders`及`workbench serve/submit`本地私有队列。三个模型分别持有独立worker，跨阶段和跨批次复用；单批仍调用原版本化build，独立state和审核/负面候选边界保持。原普通build兼容。驻留worker退出或冻结身份变化时明确失败，不静默重载。使用者操作入口见运行时仓库[驻留手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-resident.md)。

## Measured result

node94 GPU2 RTX5090 32GB，同一组16张高分辨率输入连续两批，各用独立state和新结果缓存；这是16张不同输入的32次处理，不是32张不同图片。源对象和操作系统页缓存不清空。

| 指标 | 第一批16张 | 第二批16张 |
|---|---:|---:|
| 热build | 150.030秒 | 150.740秒 |
| 审阅导出 | 6.091秒 | 6.153秒 |
| job总时长 | 156.664秒 | 157.423秒 |
| scan开始到JoyCaption开始 | 66.447秒 | 62.237秒 |
| 成功long | 16 | 16 |
| 正式模型请求 | 48 | 48 |
| 模型重载计时 | 0 | 0 |
| 实际裁剪 | 0 | 0 |

一次性模型身份核验181.012秒，启动/加载/合成预热126.028秒，均从热任务排除。合并build为383.02张/小时，含审阅交付/额外核验为366.78张/小时。三个worker在两批中PID保持，96次请求全部成功。预热后YOLO适配器平均0.089秒/张、Paddle0.164秒/张，含预后处理；读取/解码分别还需0.508/0.541秒。JoyCaption完整请求4.059秒/张，合计4295 tokens。

采样显存峰值19232MiB（采样从ready后开始），测试会话按`--max-jobs 2`结束，确认自有worker及控制进程退出、GPU2恢复18MiB。node95 GPU1现场设备报错，其他三卡可识别；本轮未重置设备。

报告、分阶段明细及安全JSON见运行时[实测记录](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.16-resident-throughput.md)。64个已部署后端源文件SHA256与本地逐项相符。

## Verification and limits

233项Workbench完整回归通过、无跳过，303.888秒；另新增1项跨会话中断恢复定向测试通过，恢复沿用原版本、零正式模型重算；官方配置5项通过。OpenSpec严格校验通过。两批输入字节未变，真实图像/caption/OCR未查看。

校准仍pending，两批均16张review、裁剪0，未将开关开启当实际裁剪成功；本批没有质量负面候选。当前仍为待审交付，不是训练ready。普通build、四卡调度、解码共享、批量推理和前端控制驻留服务没有在本轮默认改造或验收；旧三档计量不能与本轮单long直接计算同配置加速倍数。原2.5/6.4保持未完成，不archive。

# node94 Huihui Caption 试验状态

2026-10-26，按用户指定在 node94 部署独立 Gradio，模型和工作目录使用已授权 `/net/node95/hd4/ImageCaptionExperiments/huihui-qwen3vl8b-node94-20261026`。不修改 Workbench 执行流程或已有数据版本。

固定源模型 `huihui-ai/Huihui-Qwen3-VL-8B-Instruct-abliterated` 修订 `b47a0690b22eaf1d9a63874d967a03781c90f9cf`，同一 RTX 5090 32GB 比较 BF16、bitsandbytes INT8、NF4。视觉塔和输出头保持 BF16；INT8/NF4 实际检查到 252 个语言层 Linear 量化。公开来源与候选量化边界见[研究依据](research-evidence.md#huihui-qwen3-vl-8b-独立-caption-试验2026-10-26)。

固定合成图、英文指令、贪心、128 输出 token、batch=1，每组合预热一次、测量三次。六组合共 18 个正式样本均成功。1024² 下中位数：

| 精度 | generate 时间 | generate token/s | 首 token 延迟 | PyTorch 分配峰值 |
|---|---:|---:|---:|---:|
| BF16 | 3.525s | 36.31 | 0.173s | 16.67GiB |
| INT8 | 15.694s | 8.16 | 0.237s | 10.34GiB |
| NF4 | 5.116s | 25.02 | 0.181s | 7.15GiB |

当前实现中 BF16 最快，NF4 节省显存但更慢，INT8 不适合作为这套单图执行器的加速选项。结论限 Transformers 5.17.0、Torch 2.11.0+cu128、bitsandbytes 0.50.2 的本次单卡环境。没有测试 AWQ/vLLM、四卡吞吐或真实语义质量，未查看真实图像和标注。

源代码、完整数值口径、两档尺寸、载入耗时及复现实验命令位于运行时仓库的 `tools/caption_demo/` 与 `docs/huihui-caption-demo-node94.md`。最终原始报告在本机 `E:/Codex_Data/ImageCaptionWorkbench/huihui-demo-node94/benchmark-final.json`，已验证输出 token、重复次数、状态及源码 SHA256。早期诊断报告不纳入结论。

网页与隧道验收通过：1440/390px 布局、空输入后恢复、合成上传与生成、释放模型，以及 Gradio API 的 NF4→BF16 串行切换均成功。前端采用必要依赖链接，已排除整套旧环境引入的不兼容音频/量化库。共享盘上传可能超过客户端默认等待时间，核验脚本使用 180 秒超时，上传不计入模型基准。截图和 `browser-check.json` 在本机同一证据目录，远端 `reports/demo-api-check.json` 仅保存字符数和数值指标。六项无 GPU 契约检查及 OpenSpec 严格校验已通过。

访问本机 `http://127.0.0.1:17864`，服务依赖 SSH 隧道；默认 BF16。操作说明见[运行时 README](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/tools/caption_demo/README.md)。本次独立试验未完成原工作流的真实质量校准或四卡验收。

同日追加JSON标签与临时公网测试：三种输出模式，固定标签结构、失败清空结构化结果并保留原文，格式通过不代表语义正确；不增加约束解码或隐式重试。公网为带认证的Gradio HTTPS分享，地址与口令仅在仓库外保存，本机入口也须登录。10项契约检查通过；公网未认证配置/上传/队列为401，已认证访问凭据文件为403；合成自由JSON与标签JSON均有效（52/89输出token），报告`public-json-check.json`只记录指标和键名。未改变生产版本或原单卡速度结论。

公网浏览器的登录、格式切换、1440/390px布局、空输入恢复、合成上传生成和卸载均通过；本机`public-ui/`保留截图和`browser-check.json`。未查看用户真实图片或标注。

随后按用户要求移除后台OUTPUT CONTRACT拼接，全部system/user/附加规则在页面可见可编辑，模板仅按钮显式载入。消息预览与推理共用构造函数，返回固定请求快照，展示模型原生聊天模板；无默认system/历史消息/tools。原速度报告保持历史证据，不将自定义提示词纳入原基准结论。

提示词透明化验证：11项契约、两种JSON真实模型合成调用及快照比对、公网浏览器的显式模板/清空/角色/不可变快照、默认展开消息和1440/390px检查均通过。证据在同一仓库外目录的`prompt-public-json-check.json`及`prompt-ui/`。

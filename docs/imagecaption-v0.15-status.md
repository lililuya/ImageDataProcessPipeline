# ImageCaption v0.15 官方JoyCaption默认预设

本轮按用户要求把未来工作流配方切到[官方Space默认配置](https://huggingface.co/spaces/fancyfeast/joy-caption-beta-one/blob/d0a1b8c39494884aa6ad4ff768189076ad054794/app.py)，并在node94提供独立、认证的Gradio Demo。长描述模型及提示、采样、BF16、Transformers 4.51.0、Liger 0.5.9共用实现；seed不固定。旧批次不改写，裁剪开启、低质量候选保留及双评分关闭继续保留。

官方权重及处理配置13项字节核验全部匹配。226项Workbench回归（含数据库/恢复/同步）和新增5项官方预设契约通过；前端构建、68项合成配置浏览器检查、本地与公网各10项Demo浏览器检查通过，规格严格校验通过。所有图片验证仅用合成几何图，无真实内容查看。

node94单5090 GPU3首次合成生成115 tokens/35.796秒，身份校验及模型加载191.048秒；共享模型的实际工作流provider热请求113 tokens/3.818秒。首次包含内核初始化，单个热请求不能代表稳定吞吐。公网与本地匿名配置访问401、登录后200、私有文件下载403；修复旧Gradio分享CDN样式入口。截图、模型、凭据和运行报告均在仓库外。

部署代码/新配方位于node94的 `/net/node95/hd4/ImageCaptionWorkbench/v0.15/20261027-joycaption-official`，Demo位于 `/net/node95/hd4/ImageCaptionExperiments/joycaption-official-node94-20261027`。运行时操作手册：[v0.15](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.15-joycaption.md)、[Demo README](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/tools/joycaption_demo/README.md)。公网链接/PID为临时状态，不写成固定配置。

本轮不重新处理生产批次，不验收真实语义质量或完整流水线吞吐。OpenSpec原未完成的2.5与6.4保持未完成，不archive。

运行时代码已同步至 `275e4e4809789c99c07d730ae7684419920a1372`（`codex/imagecaption-workbench-v0.2`）；Demo与工作流部署的65个后端源码文件和本地逐项SHA256一致。本规划记录随本提交同步。

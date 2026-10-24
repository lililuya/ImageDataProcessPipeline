# ImageCaption v0.8：网页流程隔离与状态修正

2026-10-24，运行时代码已同步到 `codex/imagecaption-workbench-v0.2` 分支提交 [1000d8f](https://github.com/lililuya/ImageCaption/commit/1000d8fe686b4b6bcd40d6400527ea08c0b7c2da)。本地 8841 服务已更新，首页构建字节、受保护接口认证与未知运行 404 已核验。node95 未部署本轮；真实图片、描述、OCR 与原审阅包均未读取或修改。

## 实现与验证

- Workbench 与旧批次导航分组，分别用 `wb_run` 与 `run` / `batch`；旧链接迁移，深链接、刷新与前进后退恢复。
- 受保护接口验证登录，防止重复提交；旧运行先核对服务端归属；图片读取限制在对应工具。
- GET 12 秒超时；目录与详情独立失败/恢复，拒绝错误运行与迟到响应。已发布、撤回、必需阶段完成及可选标签待审分开提示。
- 旧中间结果按有效审核输出 SHA 预览，说明模型实际输入；空状态区分未安排、无结果、筛选与读取错误。
- 旧导出列表按批次筛选、分页和中文状态；明确不包含 Workbench 本地产物。Target 修改回调迟到不会覆盖另一个批次。

后端 40 项测试通过（隔离 PostgreSQL、30.617 秒），前端 TypeScript 与生产构建通过。浏览器共 590 项合成检查：导航 56、连接/状态 72、中间结果 22、迟到修改回调 20、原有引导/开关/标签 420。仅中间结果夹具有 5 次合成 SVG 预览，迟到回调夹具有 6 次合成写请求；没有真实内容、业务写入、外部请求或浏览器错误。最初发现的旧 CPU worker 测试夹具与既有 profile 约束不一致已修正，未放宽生产约束。

具体脚本和行为见 [v0.8 验证记录](https://github.com/lililuya/ImageCaption/blob/1000d8fe686b4b6bcd40d6400527ea08c0b7c2da/docs/workbench-v0.8-ui-validation.md)，使用方法见 [看板指南](https://github.com/lililuya/ImageCaption/blob/1000d8fe686b4b6bcd40d6400527ea08c0b7c2da/docs/workbench-dashboard-guide.md)。

本轮不等于完整网页配置/运行/标注系统完成；Workbench 仍由 CLI 执行和交付。真实质量校准、direct 全阶段进度、四卡自动调度仍待实施，任务 2.5、6.4 不改变，不 archive。

## Togeari 只读评估

已对照官方 `c03eb960` 代码与文档完成 [Togeari 执行层评估](togeari-execution-assessment.md)。建议先试有界并行、分桶合批、常驻 worker 和分段计时，再比较轻量执行器与框架适配。当前没有安装 Togeari、实现 executor 开关或新增 GPU 测速；其调度器微基准不能替代本系统吞吐结论。

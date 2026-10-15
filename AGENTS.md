# Repository guidance

本仓库采用OpenSpec。先阅读README和相关change的proposal、specs、design、tasks，区分规划状态与实际实现。用户直接指令优先。

- 文档正文使用中文；OpenSpec结构标题、SHALL/MUST、WHEN/THEN保留规范格式。
- 当前只有设计，没有数据处理运行时。不要把CLI示意或未校准配方描述为已实现功能。
- 代码实现按依赖推进；任务只有在对应验证证据存在时才勾选。未完成实施不得archive。
- 模型事实引用docs/research-evidence.md，工程建议明确为建议，不凭空补齐闭源配方。
- 原图、真实标注、模型、凭据、临时依赖不入Git。真实试点数据使用仓库外路径。
- 修改规划后执行`npm run spec:validate`。运行时代码新增后执行与改动相符的契约、集成及恢复验证。
- 不因语法校验通过而宣称数据质量、吞吐或模型收益已验证。

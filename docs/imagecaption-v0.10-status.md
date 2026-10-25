# ImageCaption v0.10：网页整理与只读配置

日期：2026-10-25。依据已批准的网页整理与配置展示方案继续实施 `build-imagecaption-data-workbench`，不改变 CLI 处理职责。

## 已实现

主导航收敛为运行看板、运行配置、系统诊断、使用帮助，旧批次工具折叠并保留原链接。阶段列表与单项详情分离，默认优先失败阶段，手动选择不受轮询影响；仅版本上下文栏吸顶。教程、完整身份和候选池按需展开，错误常驻并提供排查入口，悬浮帮助支持键盘及边缘避让，隐藏页面停止轮询。

五组只读配置覆盖质量、水印裁剪、描述标签、模型后端、并发交付。独立摘要绑定 run/policy/plan，不修改原冻结版本；认证 API、字段白名单、CLI 构建记录和独立同步已经接入。模型参数跟随实际适配器和阶段覆盖；质量门槛跟随默认领域规则，明确逐图覆盖及历史缺失。未配置、已关闭、待校准和未验证独立表示。

配置同步失败和元数据读写失败不会撤销原事件同步；自动重试有冷却，手动 sync 立即重试并返回独立状态。网页不保存配方、不启动模型、不增加新版任务控制。

## 本轮证据

- Workbench 全回归 202 项通过，312.791 秒，无跳过；数据库使用随机隔离 schema。
- 交叉审查后的配置专项 19 项通过，含 3 项 PostgreSQL 集成，13.024 秒。与全回归存在重叠，不相加。
- 685 项合成浏览器检查通过，覆盖配置、状态、关闭模块、连接、导航、旧链接、迟到响应和隐藏页轮询。
- TypeScript 与 Vite 构建通过。1440、1024、760、390px 和 200% CSS 缩放完成几何与键盘检查，并目检合成截图；不等同于所有浏览器原生缩放实现的验收。
- 实际修复了领域质量门槛投影、异常文字面积解释、刷新失败残留提示和放大后详情列过窄等问题。

并行运行多个浏览器曾使两个下载检查超时，分别重跑通过，未删除断言或放宽超时。截图、日志与控制表逻辑快照保存在仓库外 `E:/Codex_Data/ImageCaptionWorkbench/v0.10/`，不入 Git。

## 操作与交付

运行时分支为 `codex/imagecaption-workbench-v0.2`，网页入口为 `http://127.0.0.1:8841/#workbench`。本轮本地服务保留原数据库、端口、运行身份及令牌；node95 未更新。配置摘要需要新版 API 和新版 CLI 同步，旧运行不会自动套用新默认值。

运行时代码已同步 GitHub 提交 `d58be31902f47e843233b1cd12261dc6589dfb54`，代码树 `55c6a4e1202cdd5dec7b275bfc486ccb28b680d1` 与本地逐文件核验一致。本地初始提交 `0eb729b` 经同树验证后对齐远端提交；使用已连接 GitHub 接口同步，没有更改 Git 凭据或强制覆盖远端。

本地升级前后6个既有版本冻结摘要及revision指纹一致；新版实际API完成12张合成图形build/publish，`demo-quality-v03 / v0001` 为ready，五组配置已同步且重放幂等。首次CLI受系统代理影响返回502，只为本次命令设置NO_PROXY后通过，未更改全局代理。原始控制表逻辑快照与本地验证JSON均保留在上述仓库外目录。

- [README](https://github.com/lililuya/ImageCaption/tree/codex/imagecaption-workbench-v0.2)
- [启动与升级核验](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-startup-verification.md)
- [看板手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-dashboard-guide.md)
- [运行时验收记录](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.10-ui-validation.md)

本轮仅合成素材与工程元数据，不查看真实图片、caption 或 OCR，不执行实际 GPU 推理；质量校准、模型收益和单卡／四卡吞吐不因 UI 验证提升验收状态。原 2.5 和 6.4 保持未完成，变更不归档。

规格、手册与验收记录首次同步提交为 `d09b596dc0fda6095f88cff6b800319db04b82e0`；本条后续提交记录交付任务完成。产品change累计73/75项，保留上述两项待验收任务。

## 后续：主导航移除旧工具

用户希望清除与当前CLI无关的入口。旧控制面仍承担历史先验编辑、任务与导出维护，且新版复用基础数据表，因此只移除主导航、登录、页脚与帮助中的旧工具引导，保留已有旧链接、API和数据兼容。

TypeScript、Vite及128项现有合成浏览器回归通过（51/57/20），四种宽度检查无溢出。已核对本地8841静态文件与新构建一致，未重启API、未改后端；该轮未重新执行模型或后台数据库测试。合成日志与截图保存在v0.10/nav-cleanup。

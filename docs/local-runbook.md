# Windows本地开发与最小发布

2026-10-18起，node95离线期间在`E:\Codex_Project\DataPipeline`继续实施。代码、OpenSpec和测试在本地；95的业务数据库、真实图片和私有标注没有复制到本机。整个框架尚未全部实现。

## 本机环境

| 内容 | 当前路径 |
|---|---|
| 源码和规格 | `E:\Codex_Project\DataPipeline` |
| Python环境 | 仓库内`.venv`，Python3.12 |
| 合成开发数据库 | `E:\Codex_Data\ImageDataPipeline\postgres-local` |
| 本次合成演练与汇总 | `E:\Codex_Data\ImageDataPipeline\demo-20261018` |
| 开发数据库连接 | `127.0.0.1:55497`，`idp_local`，数据库`postgres` |

本机已准备PostgreSQL17.9开发运行时，位于Git忽略的`.tools/postgres17/package/native/bin`，不属于项目发布依赖。换机需准备PostgreSQL17的bin目录，用脚本的`--postgres-bin`指定；脚本不下载安装软件。Python安装见[M0指南](m0-guide.md)。

开发库仅监听回环地址，使用trust认证，只供本机合成开发。真实私有数据另建受控数据库；不要将这个开发库改为公网监听。脚本校验项目marker，不接管无marker的既有cluster，不删除cluster。

## 启动与演练

在仓库根PowerShell执行：

```powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe scripts/local_postgres.py init --data-root E:/Codex_Data/ImageDataPipeline/postgres-local
.venv/Scripts/python.exe scripts/local_postgres.py start --data-root E:/Codex_Data/ImageDataPipeline/postgres-local
$env:IDP_DATABASE_DSN = 'postgresql://idp_local@127.0.0.1:55497/postgres'
$demoTag = Get-Date -Format 'yyyyMMdd_HHmmss'
$env:IDP_CATALOG_SCHEMA = "idp_demo_$demoTag"
$demoPath = "E:/Codex_Data/ImageDataPipeline/demo-$demoTag"
.venv/Scripts/python.exe -m idp.cli demo $demoPath
```

`demo`要求新目录、空的独立`idp_demo_` schema，测试可用`idp_test_`。素材由代码生成，不接受外部图片。它登记3条来源、合并为2个资产，运行解码、数值质量、全画面视图共6项任务；使用夹具生成定义中的描述，冻结输入，导出sidecar，实际读取通过后置ready，再重放。没有GPU/API调用，不检查真实图片，不自动批准真实来源。

输出仅有汇总计数、状态、摘要和耗时。演练目录包含`fixtures/`、`objects/`、`release-plan.json`、`releases/`、`demo-report.json`，均不进入Git。

```powershell
$env:IDP_OBJECT_ROOT = "$demoPath/objects"
$env:IDP_RELEASE_ROOT = "$demoPath/releases"
$report = Get-Content "$demoPath/demo-report.json" -Encoding UTF8 | ConvertFrom-Json
$releaseId = $report.release.release_id
.venv/Scripts/python.exe -m idp.cli release inspect $releaseId
.venv/Scripts/python.exe -m idp.cli release verify $releaseId
.venv/Scripts/python.exe -m idp.cli release read $releaseId
.venv/Scripts/python.exe -m idp.cli duplicates exact
```

对已保存的演练，设置相应schema和`$demoPath`后可重复验证，不用重新运行`demo`。

```powershell
.venv/Scripts/python.exe scripts/local_postgres.py status --data-root E:/Codex_Data/ImageDataPipeline/postgres-local
.venv/Scripts/python.exe scripts/local_postgres.py stop --data-root E:/Codex_Data/ImageDataPipeline/postgres-local
```

`init/start/stop`可重复执行；更换端口用独立数据根。控制日志在数据根的`control.log`与`server.log`。本次开发数据库与演练保留供复查；临时测试cluster另用55496端口，测试后停止。

## 最小T2I计划与发布

入口为`idp release freeze plan.json`，随后`build/verify/inspect/read RELEASE_ID`。对象与发布目录通过`IDP_OBJECT_ROOT`、`IDP_RELEASE_ROOT`显式配置。JSON Schema由`idp.releases.models.ReleasePlan.model_json_schema()`获取；合成演练的`release-plan.json`可参考结构，但不能把夹具caption、来源证据、审核声明复制到真实数据。

计划固定以下内容：

- `access_domain`与有名称、版本、说明、seed的选择配置。默认保留手工选择快照，也可通过[版本化选择配方](recipes.md)绑定固定决策；完整领域课程与采样引擎尚未实现。
- `TaskSample`：当前只支持T2I、单个target、已事务提交的RGB/L PNG视图。
- `Caption`：文本、语言、producer、来源引用、具体view_id/checksum、reviewer、review_version、review_method、review_reason。`sample.caption_ref`等于其`annotation_id`。
- `source_ids`、train/validation/test划分和采样权重；每个固定来源须保持approved并有证据，资产访问域须匹配。

Caption以内容摘要确定版本，文本或审核信息变化产生新版本；当前保存显式视图人工审核或合成ground truth声明，不自动证明语义正确。完整字段审核、推理模型和审核权限尚待实施。禁止直接复用未验证的原图caption到裁剪视图。遵守用户“不查看图片具体内容”的要求，本机不进行真实素材标注或人工图像检查。

`freeze`登记draft，`build`按`draft → building → validating → ready`推进，失败记录failed。同一命令可恢复failed或中断遗留的building/validating。构建使用数据库锁和递增token，只创建或验证文件，不覆盖已有内容。

每个发布使用release_id命名，包含固定`manifest.jsonl`与`files/<样本摘要>.png/.txt`，路径不用sample_id拼接。manifest保存图像角色、checksum、view、caption版本、来源、审核引用、配方摘要、划分和权重。图片为独立副本，防止导出被修改时损坏内容寻址对象。

ready前实际读取所有UTF-8 caption和PNG像素，检查通道、尺寸、样本数、文件集合及图片/文本/manifest摘要。重复成员、同资产/视图/输出/显式组跨划分、来源未批准或撤回、缺图和缺caption均阻断ready。成员和配置冻结后不原位修改；输入变化产生新release_id，重排成员或来源列表不改变摘要。

失败重放复用校验相同的文件；已有文件内容不符时拒绝覆盖。需操作者先在发布目录外保存损坏文件，再按原因恢复。ready产物后来丢失、被修改或来源撤回时，内置消费者拒绝新读取。自动撤回影响清单与物理删除审计仍属9.6任务；绕过内置消费者直接读取旧副本无法获得动态许可检查。

当前适配器为`t2i-sidecar-v1`，增强仅`identity-v1`。编辑、多参考、RGBA、image-only、WebDataset均不支持，不丢字段或以空caption模拟。内置加载器返回PIL图像与文本；真实目标训练器、tokenizer、采样和首epoch验收仍在8.7/9.x。完整关联图泄漏检查仍在5.4，当前只保护上述已知键。

## 验证记录

Windows/Python3.12/真实隔离PostgreSQL17.9：测试证据见[实施状态](implementation-status.md)，覆盖v4→v5保留视图、来源簇、并发冻结、字段与划分拒绝、实际读取、文件和事务失败、进程终止恢复、来源阻断及CLI。源码包与wheel构建成功；严格OpenSpec校验通过。

2026-10-18仓库外实跑：3条来源、2个资产、1个精确重复组，6项任务成功，2个sidecar样本ready且实际读取，作业重放处理0项；单次演练约5.45秒，不外推真实数据吞吐。汇总保存在`demo-report.json`。真实数据闭环4.6仍未完成。

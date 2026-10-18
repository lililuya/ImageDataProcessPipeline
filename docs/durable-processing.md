# 持久解码处理与故障恢复

本轮只实现本地CPU解码观测。输入为目录中已登记的原始对象摘要，结果为尺寸、格式、通道等元数据，不含图片预览、OCR或caption。原始来源不因处理成功而获得训练许可。

本页记录第二轮已部署流程。2026-10-17本地代码增加质量与训练视图算子，见[新增指南](views-quality.md)；95尚未部署该轮更新，具体状态见[实施记录](implementation-status.md)。

## 数据库v3

v3以追加迁移增加重试字段、资源池、事件、观测与产物引用表，不修改v1/v2迁移摘要。升级前已在node95数据盘生成私有pg_dump备份。旧应用不理解新观测提交边界，不应与新worker混跑；停旧worker、迁移、启新worker。回退使用新隔离数据库验证备份，禁止原地降级schema。

## 处理命令

```bash
cd /mnt/hd2/ImageCaptionSystem
set -a
. ./.env
set +a
.venv/bin/idp db migrate
.venv/bin/idp jobs pool cpu --concurrency 2
.venv/bin/idp jobs enqueue-probes --batch-id private-pilot-v1 --limit 64
.venv/bin/idp worker --max-jobs 64 --lease-seconds 60
.venv/bin/idp jobs metrics
```

enqueue返回匿名任务键，重复执行不会重复入队。`--batch-id`只选指定接入批次的资产；省略时按资产摘要选择。该命令不扫描或重新拷贝源图片。它只绑定已经存在的本地对象。

worker是有界前台进程：完成指定任务数或当前无可领取任务后退出；遇到尚未到重试时间的任务也可能退出，需再次启动。没有注册无人值守服务。每个worker当前串行执行一项，多个进程共享数据库资源池；`claim_batch`接口可供其他算子批量领取。

## 暂停、定位与恢复

```bash
.venv/bin/idp jobs pool cpu --concurrency 2 --paused
.venv/bin/idp jobs inspect sha256:REPLACE_WITH_TASK_KEY
.venv/bin/idp jobs retry sha256:REPLACE_WITH_TASK_KEY --actor OPERATOR --reason FIXED_CAUSE
.venv/bin/idp jobs pool cpu --concurrency 2
.venv/bin/idp worker --max-jobs 64
```

示例任务键需替换成实际64位摘要。暂停阻止新领取，在途工作继续提交并释放槽位。缩小并发不会中止在途任务。人工retry只允许隔离任务，重置本次尝试计数，不回退token；必须填写操作者与原因，事件追加保存。

`metrics`输出资源/状态数量、按创建时间计算的最老任务年龄、领取/隔离/重放/成功事件总数及观测数量；`inspect`输出任务键、状态、次数、时间与受控错误码，不输出输入URI、模型提示或原始结果。测试可用`IDP_CATALOG_SCHEMA`指定隔离schema，默认使用idp；不要将测试命令指向生产schema。

## 执行保证与边界

- 资源池行锁保护槽位计算；活跃租约总数不能超过该资源池并发上限。数据库事务外执行解码。
- 临时错误采用指数退避，上限300秒，默认最多尝试3次；永久坏输入立即隔离。失联租约也消耗尝试次数，耗尽后由下一次领取扫描转入隔离。
- token在每次领取递增；心跳和完成必须匹配有效token与未过期租约。慢任务由独立心跳线程续租，续租失败则停止提交结果。
- 每项成功任务生成内容寻址JSON观测产物；摘要校验后，观测、产物引用、成功状态与事件在同一数据库事务提交。
- 上传后崩溃可能留下没有数据库引用的对象；这些对象不解锁下游。恢复时可复用同字节对象，旧worker迟到提交会被拒绝。
- GC、API计费账本、预算限额、取消、来源访问角色及发布模块仍待实现。当前不能据此宣称分布式exactly-once或完整生产调度能力。

## 验证证据

`tests/test_postgres.py`覆盖并发批量领取、池暂停/恢复、退避窗口、尝试耗尽、永久错误、人工重放、CLI管理、长任务心跳、实际子进程强制终止、上传后故障和事务失败注入。node95上使用真实PostgreSQL执行，不使用模拟数据库代替集成验证。

真实试点只对上一轮接入的64项私有资产执行解码。报告限于工程汇总，完整画面内容不进入工具输出或Git仓库。解码成功不等于美学、标注或训练可用性通过。

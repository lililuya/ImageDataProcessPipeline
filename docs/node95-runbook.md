# node95 部署与操作

## 路径与状态

- 代码：`/mnt/hd2/ImageCaptionSystem`。
- 本地数据根：`/mnt/hd4/ImageCaptionSystem`，检查时为`/dev/sdd1`，剩余约9.4TB。
- objects：内容寻址原始字节；postgres：独立数据库数据；artifacts：测试/处理报告。
- `/mnt/hd2`实际位于已用98%的系统分区，因此不向该位置导入训练图片。
- 独立容器`idp-postgres`，仅绑定`127.0.0.1:55495`；项目没有开放外网API。

凭据由`bootstrap_node.py`随机生成到代码目录`.env`及`.tools/postgres.env`，权限0600。不要提交、打印或复制到聊天。数据库数据不进入Git。数据库镜像按本次拉取的digest固定。

## 命令

```bash
cd /mnt/hd2/ImageCaptionSystem
set -a
. ./.env
set +a
.venv/bin/idp --help
.venv/bin/idp db migrate
.venv/bin/idp probe /path/to/image.png
.venv/bin/idp ingest /path/to/image.png --source-config configs/source.synthetic.json --original-id sample-1
IDP_TEST_DSN="$IDP_DATABASE_DSN" .venv/bin/python -m pytest -q
docker inspect --format '{{.State.Health.Status}}' idp-postgres
```

只读试点使用`idp pilot INPUT_DIR --source-config PRIVATE_CONFIG --limit 64`。该命令要求来源unknown，仅输出工程统计，不生成预览或caption。图片由程序解码但不人工查看，结果不包含具体文件名；私有完整来源引用仅保留在数据库。试点有1GiB原始字节上限，达到上限跳过后续超额文件，不能将该上限理解为总IO字节数。

合成来源配置只供代码生成夹具使用，不能用来给实际图片宣称授权。真实来源应创建独立配置，批准状态需有真实证据引用；默认未知来源可接入但不能用于未来发布。

ingest执行流式SHA-256、本地staging、文件同步、无覆盖原子链接和数据库事务登记。同一字节重复接入只有一个资产；来源按批次/名称/原始标识/资产独立。上传成功、登记失败可能留下孤儿对象；目前保留、不自动回收。不要人工删除不明对象，GC仍待实现。

## 数据库迁移与备份

迁移在事务和advisory lock内执行，校验历史版本/内容摘要；禁止旧代码向较新schema降级。v1包含资产、来源与基础任务表，v2追加来源撤回事件和索引，旧资产记录保持可读。测试用随机`idp_test_*` schema，结束仅删除其测试schema。

升级前可备份：

```bash
docker exec idp-postgres pg_dump -U idp -d idp -Fc > /mnt/hd4/ImageCaptionSystem/artifacts/catalog-backup.dump
```

备份文件包含来源元数据，按敏感数据管理。以上是操作说明，尚未执行完整灾难恢复演练。当前无主数据库自动降级命令；回滚应用前先确认schema兼容，必要时在独立新数据库验证备份恢复，禁止直接覆盖生产目录。

## 持久任务边界

已实现任务键、依赖、资源类别、SKIP LOCKED领取、心跳、租约token与条件完成；当前还没有常驻worker、有限重试、限额、预算、GC和发布模块。不要据此启动无人值守全量处理。断开SSH后PostgreSQL容器继续运行；没有图片处理后台作业。

真实小批数据与模型服务尚未绑定。本轮只使用合成测试素材验证工程行为，未验证标注精度、GPU吞吐或模型训练收益。

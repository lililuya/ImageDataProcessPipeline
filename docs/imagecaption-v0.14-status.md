# ImageCaption v0.14：质量负面保留与全流程复核

运行时提交：[14150b6](https://github.com/lililuya/ImageCaption/commit/14150b67470fdfb11faa5ebfa49815fc59e2e97a)，分支 `codex/imagecaption-workbench-v0.2`。

2026-10-27。新配方保留低于短长边、可选总像素数、原始文件字节数或byte/pixel门槛的有效独立图片，继续生成所选描述并记录客观证据。当前仍为JoyCaption单长、短边512、长边1920、0.15 byte/pixel、裁剪开启、双评分关闭；不擅自设置额外总像素数和文件字节下限。

quality_negatives开关与新增阈值随版本冻结，兼容旧配方；低门槛图片即使同时有水印或文字也会生成描述。保留原review/auxiliary路由，增加negative_candidates成员清单、审阅包negative-candidates.jsonl和网页筛选；原因记录实际视图尺寸/像素与原始编码字节，不自动推断模糊或美学。描述和候选仍待审，主集发布不接纳，训练器须另行显式消费负面角色/属性，尚不声称训练收益。

226项Workbench后端/隔离数据库回归通过；结果页109项、配置页66项合成浏览器检查通过，覆盖四种宽度与200%缩放。前端构建通过。2张合成图及固定合成provider的本地版本中，1张负面候选已生成long、配置同步并接入结果页，没有GPU推理。

本地8841已更新，node94独立v0.14代码及当前配方部署完成，离线model-plan核对通过。历史版本和其他任务未修改，本轮未查看真实图片、caption或OCR，未做新真实数据吞吐试验。最后真实完整测速仍为v0.12三档16张约113张/小时；单长和扩大保留范围后应重新测量，不能外推四卡容量。

复核发现的重要未验收项仍是：真实水印误检与裁剪主体保留、文字/质量门槛及caption事实质量。上一轮16张真实试点实际裁剪0，不能将默认开关开启表述为真实裁剪质量已通过。原任务2.5、6.4保持未完成。

完整流程表、启动方式、字段说明和输出位置见[运行时v0.14手册](https://github.com/lililuya/ImageCaption/blob/codex/imagecaption-workbench-v0.2/docs/workbench-v0.14-workflow.md)。

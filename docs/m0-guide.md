# M0 使用与验收

本阶段已实现契约、合成夹具、分层审核抽样和算子身份协议；另已接入PostgreSQL目录和基础租约队列，见node95操作手册。常驻worker、标注模型及发布仍待实现。生成夹具不代表已实现自动编辑方向审核，fixture-manifest中的结论是测试预期。

## 安装

Python 3.10以上，建议独立虚拟环境。运行依赖和开发依赖在`requirements-dev.lock`固定；`pyproject.toml`定义包入口。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install -e . --no-build-isolation --no-deps
.venv/bin/idp --help
.venv/bin/python -m pytest -q
```

Windows命令把`.venv/bin/python`替换为`.venv\Scripts\python.exe`。若系统临时目录无权限，使用仓库`.tools/`下一个尚不存在的`--basetemp`目录运行pytest；不要指定有业务数据的目录。

## 合成夹具

```bash
.venv/bin/idp fixtures /tmp/idp-fixtures-new
```

目标必须不存在，避免覆盖已有文件。输出包括RGB红蓝图、字节重复图、半透明RGBA、EXIF6旋转、多帧GIF、小字图、损坏文件，以及正确/反向编辑样本声明。全部通过代码生成，无真实用户素材。夹具字节与渲染依赖绑定Pillow版本。

## 契约验证

```bash
.venv/bin/idp validate asset asset.json
.venv/bin/idp validate sample sample.json
```

可使用Python模型导出正式JSON Schema；不要使用`docs/contracts.md`中的简写摘要作为有效样本。Digest必须为`sha256:`加64位小写十六进制。时间需带时区，公共时间归一为UTC；未声明字段被拒绝。

来源身份按批次、来源名、原始标识与资产确定；相同资产多个来源不会共享来源ID。真正数据库入库去重在M1实现，本阶段仅建立可供唯一约束使用的契约与身份。

任务校验覆盖八类任务的必需字段、有序角色、连续ordinal、逐字原文/坐标、编辑保留要求、RGBA语义、风格策略及偏好条件。结构校验不等于视觉事实审核。`AdapterCapabilities.check()`必须在未来导出入口调用；仅定义能力声明不会自动使加载器支持该任务。

## 分层审计

frame.json是`[{"sample_id":"...","stratum":"..."}]`，allocation.json为各层样本数映射：

```bash
.venv/bin/idp audit sample frame.json allocation.json --seed 42 > review-plan.json
.venv/bin/idp audit estimate review-plan.json
```

Windows PowerShell 5重定向默认可能产生UTF-16，请用`Set-Content -Encoding UTF8`或Python写UTF-8文件；读取器兼容UTF-8 BOM。审核人在selected条目填写整数label（0/1）和reviewer，其余抽样字段保持不变。缺失任何选中审核或抽样概率不符均拒绝估计。

同层采用不放回简单随机抽样，各层至少取1个；记录frame_digest、seed、总体层大小与入样概率。总体比例按总体层权重汇总。区间使用保守分层Hoeffding界，全查层贡献零抽样误差；区间不是标注正确性的保证，也不覆盖人工偏差。当前不支持随意替换抽中样本或不等概率层内抽样。

## 当前证据

- 契约和任务：`tests/test_contracts.py`。
- 过采样纠偏、全查区间及缺失/篡改审核拒绝：`tests/test_audit.py`。
- 夹具像素、方向、帧数、摘要及真实CLI入口：`tests/test_fixtures_cli.py`。
- Windows开发环境与node95独立安装/执行结果记录于`docs/implementation-status.md`。

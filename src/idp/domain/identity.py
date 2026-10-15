"""确定性标识；不接受隐式类型转换或非 JSON 数据。"""

import hashlib
import json
import math
from typing import Any


def _check(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("NON_FINITE_JSON_NUMBER")
        return
    if type(value) is list:
        for item in value:
            _check(item)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for item in value.values():
            _check(item)
        return
    raise ValueError("NON_JSON_VALUE_OR_KEY")


def canonical_bytes(value: Any) -> bytes:
    """本项目 canonical-json-v1；列表顺序有意义，不作 Unicode 归一化。"""
    _check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()

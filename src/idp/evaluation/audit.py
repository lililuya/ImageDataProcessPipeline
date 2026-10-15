"""分层不放回简单随机抽样；不把定向过采样均值当总体均值。"""

import math
import random
from collections import defaultdict

from idp.domain.identity import digest


def sample_frame(rows: list[dict], allocations: dict[str, int], seed: int) -> dict:
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        if set(row) != {"sample_id", "stratum"}:
            raise ValueError("FRAME_REQUIRES_SAMPLE_ID_AND_STRATUM_ONLY")
        sid, stratum = row["sample_id"], row["stratum"]
        if not isinstance(sid, str) or not sid.strip() or sid in seen:
            raise ValueError("INVALID_OR_DUPLICATE_SAMPLE_ID")
        if not isinstance(stratum, str) or not stratum.strip():
            raise ValueError("INVALID_STRATUM")
        seen.add(sid)
        groups[stratum].append(sid)
    if not groups or set(groups) != set(allocations):
        raise ValueError("EVERY_STRATUM_REQUIRES_ALLOCATION")
    selected, sizes = [], {}
    for stratum in sorted(groups):
        population = sorted(groups[stratum])
        n = allocations[stratum]
        if type(n) is not int or not 1 <= n <= len(population):
            raise ValueError("INVALID_ALLOCATION")
        rng = random.Random(digest({"seed": seed, "stratum": stratum}))
        sizes[stratum] = len(population)
        for sid in sorted(rng.sample(population, n)):
            selected.append({"sample_id": sid, "stratum": stratum,
                             "inclusion_probability": n / len(population),
                             "label": None, "reviewer": None})
    frame = sorted(rows, key=lambda r: r["sample_id"])
    return {"schema_version": "1.0", "method": "stratified-srswor-v1",
            "frame_digest": digest(frame), "seed": seed, "population": sizes,
            "allocations": dict(allocations), "selected": selected}


def estimate(plan: dict, alpha: float = 0.05) -> dict:
    """分层加权比例及保守 Hoeffding 区间；有限总体全查层无抽样误差。"""
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("INVALID_ALPHA")
    if plan.get("method") != "stratified-srswor-v1":
        raise ValueError("UNSUPPORTED_SAMPLING_METHOD")
    sizes, allocations = plan["population"], plan["allocations"]
    if not sizes or set(sizes) != set(allocations):
        raise ValueError("INVALID_STRATA")
    groups, seen = defaultdict(list), set()
    for row in plan["selected"]:
        sid, stratum = row["sample_id"], row["stratum"]
        if sid in seen or stratum not in sizes:
            raise ValueError("DUPLICATE_OR_UNKNOWN_REVIEW")
        seen.add(sid)
        if type(row["label"]) is not int or row["label"] not in (0, 1):
            raise ValueError("ALL_SELECTED_LABELS_REQUIRED_AS_BINARY_INTS")
        if not isinstance(row["reviewer"], str) or not row["reviewer"].strip():
            raise ValueError("REVIEWER_REQUIRED")
        groups[stratum].append(row)
    total = sum(sizes.values())
    weighted, bound_term, strata = 0.0, 0.0, {}
    for name, size in sizes.items():
        n = allocations[name]
        if type(size) is not int or type(n) is not int or not 1 <= n <= size:
            raise ValueError("INVALID_STRATUM_SIZE")
        if len(groups[name]) != n:
            raise ValueError("INCOMPLETE_STRATUM")
        if any(not math.isclose(r["inclusion_probability"], n / size,
                                rel_tol=1e-12) for r in groups[name]):
            raise ValueError("INCLUSION_PROBABILITY_MISMATCH")
        rate = sum(r["label"] for r in groups[name]) / n
        weight = size / total
        weighted += weight * rate
        if n != size:
            bound_term += weight ** 2 / n
        strata[name] = {"population": size, "reviewed": n, "rate": rate,
                        "population_weight": weight}
    radius = math.sqrt(math.log(2 / alpha) * bound_term / 2)
    return {"estimate": weighted, "confidence_level": 1 - alpha,
            "interval": [max(0, weighted - radius), min(1, weighted + radius)],
            "interval_method": "conservative-stratified-hoeffding",
            "strata": strata, "population": total, "reviewed": len(seen),
            "frame_digest": plan["frame_digest"]}

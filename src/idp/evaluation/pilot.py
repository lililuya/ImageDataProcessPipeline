"""只读输入的小批工程试点，输出不含文件名、路径或语义描述。"""

import os
import time
from collections import Counter
from pathlib import Path

from idp.catalog.ingest import SourceConfig, ingest
from idp.catalog.postgres import Catalog
from idp.domain.identity import digest
from idp.operators.probe import probe
from idp.storage.local import LocalStore

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


def run_pilot(root: Path, config: SourceConfig, store: LocalStore, catalog: Catalog,
              limit: int = 64, max_bytes: int = 1024 ** 3) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir() or not 1 <= limit <= 10000 or max_bytes <= 0:
        raise ValueError("INVALID_PILOT_LIMIT_OR_ROOT")
    if config.license_status != "unknown":
        raise ValueError("PILOT_REQUIRES_UNKNOWN_SOURCE_UNTIL_AUTHORIZATION_REVIEW")
    candidates = []
    scan_errors = 0

    def scan_error(_):
        nonlocal scan_errors
        scan_errors += 1

    for base, _, names in os.walk(root, followlinks=False, onerror=scan_error):
        for name in names:
            path = Path(base) / name
            if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                continue
            if not path.resolve().is_relative_to(root):
                continue
            rank = digest(path.relative_to(root).as_posix())
            candidates.append((rank, path))
    chosen = sorted(candidates, key=lambda p: p[0])[:limit]
    statuses, modes, formats, asset_ids = Counter(), Counter(), Counter(), []
    widths, heights, durations = [], [], []
    consumed = 0
    started = time.perf_counter()
    for rank, path in chosen:
        before = time.perf_counter()
        try:
            size = path.stat().st_size
            if consumed + size > max_bytes:
                statuses["BYTE_BUDGET_SKIPPED"] += 1
                continue
            consumed += size
            result = probe(path)
            statuses[result["code"] or "DECODED"] += 1
            if result["status"] != "decoded":
                continue
            metadata = result["metadata"]
            modes[metadata["mode"]] += 1
            formats[metadata["format"]] += 1
            widths.append(metadata["width"])
            heights.append(metadata["height"])
            first = ingest(path, rank, config, store, catalog)
            if ingest(path, rank, config, store, catalog) != first:
                raise RuntimeError("IDEMPOTENCY_FAILURE")
            asset_ids.append(first)
        except OSError:
            statuses["IO_FAILURE"] += 1
        finally:
            durations.append(time.perf_counter() - before)
    elapsed = time.perf_counter() - started
    durations.sort()
    return {"schema_version": "1.0", "input_frame_digest": digest([r for r, _ in sorted(candidates)]),
            "privacy_mode": "metadata-only-no-visual-or-semantic-inspection",
            "source_license_status": "unknown", "source_modified": False,
            "candidate_images": len(candidates), "selected": len(chosen),
            "scan_errors": scan_errors, "selected_input_bytes": consumed,
            "status_counts": dict(statuses), "mode_counts": dict(modes),
            "format_counts": dict(formats), "registered_samples": len(asset_ids),
            "unique_asset_count": len(set(asset_ids)),
            "exact_duplicate_count": len(asset_ids) - len(set(asset_ids)),
            "idempotent_replays": len(asset_ids),
            "width_range": [min(widths), max(widths)] if widths else None,
            "height_range": [min(heights), max(heights)] if heights else None,
            "elapsed_seconds": elapsed,
            "sample_p50_seconds": durations[len(durations)//2] if durations else None,
            "sample_p95_seconds": durations[min(len(durations)-1, int(len(durations)*.95))] if durations else None,
            "gpu_inference": "not-run", "captioning": "not-run", "release": "not-implemented"}

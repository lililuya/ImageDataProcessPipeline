"""仅执行已登记原始对象的解码观测；不生成图像预览或语义描述。"""

import os
from pathlib import Path
import tempfile
import threading
import time

from idp.domain.identity import canonical_bytes, digest
from idp.execution.operators import OperatorSpec
from idp.execution.queue import Queue
from idp.operators.probe import probe
from idp.storage.local import LocalStore

PROBE_SPEC = OperatorSpec(operator_id="image-probe", operator_version="2",
                          input_schema="asset-checksum-v1", output_schema="image-probe-v1",
                          model_digest=None, config_digest=digest({"max_pixels": 100_000_000, "max_frames": 64}),
                          resource="cpu", max_batch_size=1)


def enqueue_probes(queue: Queue, limit: int = 64, batch_id: str | None = None) -> dict:
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("INVALID_ENQUEUE_LIMIT")
    with queue.catalog.connect() as conn:
        if batch_id is None:
            assets = conn.execute("SELECT asset_id FROM assets ORDER BY asset_id LIMIT %s", (limit,)).fetchall()
        else:
            assets = conn.execute("SELECT DISTINCT asset_id FROM source_records WHERE batch_id=%s ORDER BY asset_id LIMIT %s",
                                  (batch_id, limit)).fetchall()
    keys = [queue.enqueue(PROBE_SPEC, [row["asset_id"]]) for row in assets]
    return {"selected_assets": len(keys), "task_keys": keys}


def process_job(queue: Queue, store: LocalStore, job: dict, ttl: float) -> str:
    key, owner, token = job["task_key"], job["owner"], job["attempt_token"]
    stopped, lost = threading.Event(), threading.Event()

    def renew():
        while not stopped.wait(ttl / 3):
            try:
                queue.heartbeat(key, owner, token, ttl)
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        spec = job["record"]["spec"]
        inputs = job["record"]["inputs"]
        if spec != PROBE_SPEC.model_dump(mode="json") or len(inputs) != 1:
            return queue.fail(key, owner, token, "ADAPTER_UNSUPPORTED")
        checksum = inputs[0]
        path = store.path(checksum)
        if store.hash_file(path) != checksum:
            return queue.fail(key, owner, token, "INPUT_CHECKSUM_MISMATCH")
        start = time.perf_counter()
        result = probe(path)
        if result["status"] != "decoded":
            return queue.fail(key, owner, token, result["code"])
        result["usage"] = {"wall_seconds": time.perf_counter() - start, "resource": "cpu"}
        with tempfile.TemporaryDirectory(prefix=".worker-", dir=store.root) as temporary:
            output = Path(temporary) / "observation.json"
            output.write_bytes(canonical_bytes(result))
            artifact, _, _ = store.put(output)
        if lost.is_set():
            return "lease_lost"
        queue.complete(key, owner, token, result, (artifact,), store)
        return "succeeded"
    except MemoryError:
        return queue.fail(key, owner, token, "WORKER_OOM")
    except OSError:
        return queue.fail(key, owner, token, "IO_FAILURE")
    except ValueError as exc:
        if str(exc) == "LEASE_LOST":
            return "lease_lost"
        return queue.fail(key, owner, token, "SCHEMA_INVALID")
    finally:
        stopped.set()
        thread.join(timeout=min(ttl, 12))


def run_worker(queue: Queue, store: LocalStore, max_jobs: int = 64, ttl: float = 60,
               owner: str | None = None) -> dict:
    if type(max_jobs) is not int or not 1 <= max_jobs <= 10000 or not 0 < ttl <= 86400:
        raise ValueError("INVALID_WORKER_LIMIT")
    counts = {}
    owner = owner or f"cpu-worker-{os.getpid()}"
    for _ in range(max_jobs):
        job = queue.claim(owner, "cpu", ttl)
        if job is None:
            break
        outcome = process_job(queue, store, job, ttl)
        counts[outcome] = counts.get(outcome, 0) + 1
    return {"processed": sum(counts.values()), "outcomes": counts}

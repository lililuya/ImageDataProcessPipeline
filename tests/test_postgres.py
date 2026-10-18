"""需要显式 IDP_TEST_DSN；所有操作限定随机测试schema，结束仅删除该schema。"""

import os
import time
import subprocess
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psycopg
import pytest

from idp.catalog.ingest import SourceConfig, ingest
from idp.catalog.postgres import Catalog
from idp.domain.identity import digest
from idp.execution.operators import OperatorSpec
from idp.execution.queue import Queue
from idp.storage.local import LocalStore
from idp.evaluation.pilot import run_pilot
from idp.testing.fixtures import generate
from idp.execution.worker import PROBE_SPEC, QUALITY_SPEC, enqueue_quality, enqueue_views, run_worker, view_spec
from idp.operators.views import ViewConfig


def test_migration_and_idempotent_ingestion_sources(catalog, tmp_path):
    catalog.migrate(target=1)
    source = tmp_path / "image.png"
    source.write_bytes(b"synthetic-source-raw-bytes")
    store = LocalStore(tmp_path / "objects")
    cfg = SourceConfig(batch_id="batch", source_name="one", access_domain="test",
                       license_status="approved", evidence_ref="synthetic-license")
    asset = ingest(source, "original", cfg, store, catalog)
    catalog.migrate()
    catalog.migrate()
    for _ in range(2):
        assert ingest(source, "original", cfg, store, catalog) == asset
    cfg2 = SourceConfig(**{**cfg.model_dump(), "source_name": "two"})
    ingest(source, "original", cfg2, store, catalog)
    with catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM assets").fetchone()["n"] == 1
        rows = conn.execute("SELECT source_id FROM source_records ORDER BY source_name").fetchall()
        assert len(rows) == 2
    assert catalog.source_available(asset)
    catalog.withdraw(rows[0]["source_id"], "test", "source withdrew")
    assert catalog.source_available(asset)
    catalog.withdraw(rows[1]["source_id"], "test", "source withdrew")
    assert not catalog.source_available(asset)
    ingest(source, "original", cfg, store, catalog)
    assert not catalog.source_available(asset)
    with catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_events").fetchone()["n"] == 2
    with pytest.raises(ValueError, match="NEWER_THAN_TARGET"):
        catalog.migrate(target=1)


def test_database_constraints(catalog):
    catalog.migrate()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with catalog.connect() as conn:
            conn.execute("INSERT INTO source_records VALUES('s',%s,'name','batch','original','unknown','{}')",
                         (digest("missing"),))
    with pytest.raises(psycopg.errors.CheckViolation):
        with catalog.connect() as conn:
            conn.execute("INSERT INTO assets(asset_id,record) VALUES('bad','{}')")


def spec(version="1"):
    return OperatorSpec(operator_id="probe", operator_version=version,
                        input_schema="asset-v1", output_schema="probe-v1",
                        model_digest=None, config_digest=digest({}),
                        resource="cpu", max_batch_size=1)


def test_exclusive_claim_dependencies_and_recovery(catalog):
    catalog.migrate()
    queue = Queue(catalog)
    first = queue.enqueue(spec(), [digest("input")])
    assert queue.enqueue(spec(), [digest("input")]) == first
    second = queue.enqueue(spec("2"), [digest("input")], (first,))
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda i: queue.claim(f"worker-{i}", "cpu"), range(4)))
    claims = [c for c in claims if c]
    assert len(claims) == 1 and claims[0]["task_key"] == first
    old = claims[0]
    queue.heartbeat(first, old["owner"], old["attempt_token"], ttl=.01)
    time.sleep(.03)
    new = queue.claim("replacement", "cpu")
    assert new["attempt_token"] > old["attempt_token"]
    with pytest.raises(ValueError, match="LEASE_LOST"):
        queue.complete(first, old["owner"], old["attempt_token"], {"bad": "stale"})
    with pytest.raises(ValueError, match="LEASE_LOST"):
        queue.heartbeat(first, old["owner"], old["attempt_token"])
    queue.complete(first, "replacement", new["attempt_token"], {"ok": True})
    next_job = queue.claim("next", "cpu")
    assert next_job["task_key"] == second
    assert queue.claim("gpu-worker", "gpu") is None


def test_metadata_only_pilot_is_readonly_and_anonymous(catalog, tmp_path):
    catalog.migrate()
    root = tmp_path / "private-content"
    generate(root)
    original = {p.name: p.read_bytes() for p in root.iterdir()}
    config = SourceConfig(batch_id="pilot", source_name="private", access_domain="private")
    report = run_pilot(root, config, LocalStore(tmp_path / "objects"), catalog, limit=8)
    assert report["candidate_images"] == 8
    assert report["registered_samples"] == 7
    assert report["exact_duplicate_count"] == 1
    assert report["status_counts"]["DECODE_CORRUPT_OR_UNSUPPORTED"] == 1
    assert report["source_license_status"] == "unknown"
    assert {p.name: p.read_bytes() for p in root.iterdir()} == original
    import json
    text = json.dumps(report)
    assert "red.png" not in text and str(root) not in text
    with catalog.connect() as conn:
        rows = conn.execute("SELECT asset_id FROM assets").fetchall()
    assert all(not catalog.source_available(r["asset_id"]) for r in rows)


def test_batch_claims_respect_global_pool_and_pause(catalog):
    catalog.migrate()
    queue = Queue(catalog)
    queue.configure_pool("cpu", 3)
    for i in range(10):
        queue.enqueue(spec(), [digest(i)])
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda i: queue.claim_batch(f"worker-{i}", "cpu", 4), range(4)))
    claimed = [j for batch in batches for j in batch]
    assert len(claimed) == 3
    assert len({j["task_key"] for j in claimed}) == 3
    assert queue.claim("another", "cpu") is None
    queue.configure_pool("cpu", 3, paused=True)
    for job in claimed:
        queue.complete(job["task_key"], job["owner"], job["attempt_token"], {"ok": True})
    assert queue.claim("paused", "cpu") is None
    queue.configure_pool("cpu", 3)
    assert len(queue.claim_batch("resumed", "cpu", 10)) == 3


def test_backoff_quarantine_and_manual_replay(catalog):
    catalog.migrate()
    queue = Queue(catalog)
    key = queue.enqueue(spec(), [digest("retry")], max_attempts=2, retry_base=60)
    first = queue.claim("one", "cpu")
    assert queue.fail(key, "one", first["attempt_token"], "PROVIDER_TIMEOUT") == "retry_wait"
    with catalog.connect() as conn:
        delay = conn.execute("SELECT extract(epoch FROM available_at-clock_timestamp()) AS delay FROM jobs WHERE task_key=%s",
                             (key,)).fetchone()["delay"]
        assert 55 < delay <= 60
    assert queue.claim("too-early", "cpu") is None
    # 用数据库时间推进可领取边界，不依赖连接能在100ms内完成。
    with catalog.connect() as conn:
        conn.execute("UPDATE jobs SET available_at=clock_timestamp()-interval '1 second' WHERE task_key=%s", (key,))
    second = queue.claim("two", "cpu")
    assert queue.fail(key, "two", second["attempt_token"], "RATE_LIMIT") == "quarantined"
    assert queue.claim("no-infinite-retry", "cpu") is None
    queue.replay(key, "tester", "provider recovered")
    third = queue.claim("three", "cpu")
    assert third["attempt_token"] > second["attempt_token"]
    assert third["attempts"] == 1
    assert queue.fail(key, "three", third["attempt_token"], "DECODE_CORRUPT_OR_UNSUPPORTED") == "quarantined"
    assert queue.inspect(key)["last_error"] == "DECODE_CORRUPT_OR_UNSUPPORTED"


def test_artifact_commit_rolls_back_on_observation_failure(catalog, tmp_path):
    catalog.migrate()
    queue = Queue(catalog)
    parent = queue.enqueue(spec(), [digest("parent")])
    child = queue.enqueue(spec("2"), [digest("parent")], (parent,))
    job = queue.claim("owner", "cpu")
    store = LocalStore(tmp_path / "objects")
    output = tmp_path / "result.json"
    output.write_text('{"safe":true}', encoding="utf-8")
    checksum, _, _ = store.put(output)
    with catalog.connect() as conn:
        conn.execute("""CREATE FUNCTION reject_observation() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'injected commit failure'; END $$""")
        conn.execute("CREATE TRIGGER fail_observation BEFORE INSERT ON observations FOR EACH ROW EXECUTE FUNCTION reject_observation()")
    with pytest.raises(psycopg.Error):
        queue.complete(parent, "owner", job["attempt_token"], {"safe": True}, (checksum,), store)
    with catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM job_artifacts").fetchone()["n"] == 0
        conn.execute("DROP TRIGGER fail_observation ON observations")
    assert queue.inspect(parent)["state"] == "leased"
    assert queue.claim("child-before-commit", "cpu") is None
    queue.complete(parent, "owner", job["attempt_token"], {"safe": True}, (checksum,), store)
    assert queue.claim("child-after-commit", "cpu")["task_key"] == child
    with catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM job_artifacts").fetchone()["n"] == 1


def test_killed_worker_after_upload_recovers_without_stale_submit(catalog, tmp_path):
    catalog.migrate()
    queue = Queue(catalog)
    key = queue.enqueue(spec(), [digest("crash-test")])
    child_key = queue.enqueue(spec("2"), [digest("crash-test")], (key,))
    store = LocalStore(tmp_path / "objects")
    ready = tmp_path / "ready.json"
    output = tmp_path / "result.json"
    output.write_text('{"safe":true}', encoding="utf-8")
    env = {**os.environ, "IDP_CRASH_DSN": catalog.dsn, "IDP_CRASH_SCHEMA": catalog.schema,
           "IDP_CRASH_ROOT": str(store.root), "IDP_CRASH_OUTPUT": str(output), "IDP_CRASH_READY": str(ready)}
    script = """
import json,os,time
from pathlib import Path
from idp.catalog.postgres import Catalog
from idp.execution.queue import Queue
from idp.storage.local import LocalStore
q=Queue(Catalog(os.environ['IDP_CRASH_DSN'],os.environ['IDP_CRASH_SCHEMA']))
j=q.claim('crash-worker','cpu',ttl=1)
s=LocalStore(Path(os.environ['IDP_CRASH_ROOT']))
c,_,_=s.put(Path(os.environ['IDP_CRASH_OUTPUT']))
Path(os.environ['IDP_CRASH_READY']).write_text(json.dumps(dict(token=j['attempt_token'],checksum=c)))
time.sleep(30)
"""
    child = subprocess.Popen([sys.executable, "-c", script], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                pytest.fail("crash worker exited before upload")
            time.sleep(.02)
        assert ready.exists()
        uploaded = json.loads(ready.read_text())
        child.terminate()
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    with catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM job_artifacts").fetchone()["n"] == 0
    time.sleep(1.05)
    new = queue.claim("replacement", "cpu")
    assert new["task_key"] == key
    with pytest.raises(ValueError, match="LEASE_LOST"):
        queue.complete(key, "crash-worker", uploaded["token"], {"safe": True})
    queue.complete(key, "replacement", new["attempt_token"], {"safe": True}, (uploaded["checksum"],), store)
    assert queue.claim("downstream", "cpu")["task_key"] == child_key


def test_probe_worker_persists_observation_and_artifact(catalog, tmp_path):
    catalog.migrate()
    source = tmp_path / "fixtures"
    generate(source)
    store = LocalStore(tmp_path / "objects")
    good, _, _ = store.put(source / "alpha.png")
    bad, _, _ = store.put(source / "broken.png")
    queue = Queue(catalog)
    queue.enqueue(PROBE_SPEC, [good])
    bad_key = queue.enqueue(PROBE_SPEC, [bad])
    result = run_worker(queue, store)
    assert result["outcomes"] == {"succeeded": 1, "quarantined": 1}
    assert queue.inspect(bad_key)["attempts"] == 1
    assert queue.metrics()["observations"] == 1
    with catalog.connect() as conn:
        row = conn.execute("SELECT payload FROM observations").fetchone()
        assert row["payload"]["metadata"]["has_alpha"] is True
        assert conn.execute("SELECT count(*) AS n FROM job_artifacts").fetchone()["n"] == 1


def test_long_probe_renews_lease(catalog, tmp_path, monkeypatch):
    import idp.execution.worker as worker
    catalog.migrate()
    root = tmp_path / "fixture"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    checksum, _, _ = store.put(root / "red.png")
    queue = Queue(catalog)
    key = queue.enqueue(PROBE_SPEC, [checksum])
    original = worker.probe

    def slow_probe(path):
        time.sleep(.6)
        return original(path)

    monkeypatch.setattr(worker, "probe", slow_probe)
    assert run_worker(queue, store, ttl=.3)["outcomes"] == {"succeeded": 1}
    assert queue.inspect(key)["attempts"] == 1


def test_expired_last_attempt_is_quarantined(catalog):
    catalog.migrate()
    queue = Queue(catalog)
    key = queue.enqueue(spec(), [digest("last-attempt")], max_attempts=1)
    queue.claim("crashed", "cpu", ttl=.01)
    time.sleep(.03)
    assert queue.claim("next", "cpu") is None
    assert queue.inspect(key)["state"] == "quarantined"
    assert queue.inspect(key)["last_error"] == "LEASE_EXPIRED"


def test_jobs_cli_inspection_replay_and_metrics(catalog):
    catalog.migrate()
    queue = Queue(catalog)
    key = queue.enqueue(spec(), [digest("cli")])
    job = queue.claim("cli-worker", "cpu")
    queue.fail(key, "cli-worker", job["attempt_token"], "SCHEMA_INVALID")
    env = {**os.environ, "IDP_DATABASE_DSN": catalog.dsn, "IDP_CATALOG_SCHEMA": catalog.schema}

    def cli(*args):
        proc = subprocess.run([sys.executable, "-m", "idp.cli", "jobs", *args],
                              env=env, capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, "CLI failed (sensitive output intentionally omitted)"
        return json.loads(proc.stdout)

    assert cli("inspect", key)["state"] == "quarantined"
    assert cli("retry", key, "--actor", "tester", "--reason", "configuration fixed")["replayed"]
    assert cli("inspect", key)["state"] == "pending"
    assert cli("metrics")["jobs"]["cpu:pending"] == 1
    cli("pool", "cpu", "--concurrency", "1", "--paused")
    assert queue.claim("paused", "cpu") is None
    cli("pool", "cpu", "--concurrency", "1")
    assert queue.claim("resumed", "cpu")["task_key"] == key


def test_view_and_quality_jobs_atomic_registry_and_replay(catalog, tmp_path):
    catalog.migrate()
    root = tmp_path / "fixtures"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    cfg = SourceConfig(batch_id="views-pilot", source_name="synthetic", access_domain="private")
    asset = ingest(root / "rotated.jpg", "rotated", cfg, store, catalog)
    queue = Queue(catalog)
    config = ViewConfig(target_area=32 ** 2)
    first = enqueue_views(queue, config, batch_id="views-pilot")
    assert enqueue_views(queue, config, batch_id="views-pilot") == first
    enqueue_quality(queue, batch_id="views-pilot")
    assert run_worker(queue, store)["outcomes"] == {"succeeded": 2}
    assert run_worker(queue, store)["processed"] == 0
    with catalog.connect() as conn:
        view = conn.execute("SELECT record,details,output_checksum FROM views").fetchone()
        assert view["record"]["asset_id"] == asset
        assert view["record"]["orientation"] == 6
        assert view["record"]["input_width"] == 64
        assert view["record"]["input_height"] == 96
        assert view["details"]["supervision_status"].startswith("requires-")
        assert conn.execute("SELECT count(*) AS n FROM artifacts").fetchone()["n"] == 3
        assert conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"] == 2
    assert store.hash_file(store.path(view["output_checksum"])) == view["output_checksum"]
    assert queue.metrics()["views"] == 1


def test_new_view_config_and_input_failure_are_isolated(catalog, tmp_path):
    catalog.migrate()
    root = tmp_path / "fixtures"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    cfg = SourceConfig(batch_id="a", source_name="synthetic", access_domain="private")
    good = ingest(root / "red.png", "good", cfg, store, catalog)
    bad = ingest(root / "broken.png", "bad", cfg, store, catalog)
    queue = Queue(catalog)
    queue.enqueue(QUALITY_SPEC, [bad])
    enqueue_views(queue, ViewConfig(target_area=32 ** 2), batch_id="a")
    enqueue_views(queue, ViewConfig(target_area=16 ** 2), batch_id="a")
    outcomes = run_worker(queue, store)["outcomes"]
    assert outcomes["succeeded"] == 2 and outcomes["quarantined"] == 3
    with catalog.connect() as conn:
        records = conn.execute("SELECT record FROM views").fetchall()
        assert len(records) == 2
        assert len({r["record"]["config_digest"] for r in records}) == 2
        assert all(r["record"]["asset_id"] == good for r in records)
        assert conn.execute("SELECT max(attempts) AS n FROM jobs WHERE state='quarantined'").fetchone()["n"] == 1


def test_view_registry_failure_does_not_publish_partial_success(catalog, tmp_path):
    catalog.migrate()
    root = tmp_path / "fixtures"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    cfg = SourceConfig(batch_id="a", source_name="synthetic", access_domain="private")
    ingest(root / "red.png", "good", cfg, store, catalog)
    queue = Queue(catalog)
    config = ViewConfig(target_area=32 ** 2)
    key = enqueue_views(queue, config, batch_id="a")["task_keys"][0]
    with catalog.connect() as conn:
        conn.execute("""CREATE FUNCTION reject_view() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'injected view commit failure'; END $$""")
        conn.execute("CREATE TRIGGER fail_view BEFORE INSERT ON views FOR EACH ROW EXECUTE FUNCTION reject_view()")
    with pytest.raises(psycopg.Error):
        run_worker(queue, store, ttl=5)
    with catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM job_artifacts").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM views").fetchone()["n"] == 0
        conn.execute("DROP TRIGGER fail_view ON views")
        conn.execute("UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_key=%s", (key,))
    assert run_worker(queue, store)["outcomes"] == {"succeeded": 1}


def test_view_quality_cli_and_config_dispatch(catalog, tmp_path):
    catalog.migrate()
    root = tmp_path / "fixtures"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    cfg = SourceConfig(batch_id="cli-a", source_name="synthetic", access_domain="private")
    ingest(root / "red.png", "good", cfg, store, catalog)
    config_file = tmp_path / "view.json"
    config_file.write_text(ViewConfig(target_area=32 ** 2).model_dump_json(), encoding="utf-8")
    env = {**os.environ, "IDP_DATABASE_DSN": catalog.dsn, "IDP_CATALOG_SCHEMA": catalog.schema,
           "IDP_OBJECT_ROOT": str(store.root)}
    for command in (
        ["jobs", "enqueue-views", "--config", str(config_file), "--batch-id", "cli-a"],
        ["jobs", "enqueue-quality", "--batch-id", "cli-a"],
        ["worker", "--max-jobs", "4"],
    ):
        proc = subprocess.run([sys.executable, "-m", "idp.cli", *command], env=env,
                              capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, "CLI failed; sensitive output omitted"
    assert Queue(catalog).metrics()["views"] == 1

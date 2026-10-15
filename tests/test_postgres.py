"""需要显式 IDP_TEST_DSN；所有操作限定随机测试schema，结束仅删除该schema。"""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg import sql

from idp.catalog.ingest import SourceConfig, ingest
from idp.catalog.postgres import Catalog
from idp.domain.identity import digest
from idp.execution.operators import OperatorSpec
from idp.execution.queue import Queue
from idp.storage.local import LocalStore
from idp.evaluation.pilot import run_pilot
from idp.testing.fixtures import generate


@pytest.fixture
def catalog():
    dsn = os.environ.get("IDP_TEST_DSN")
    if not dsn:
        pytest.skip("IDP_TEST_DSN not configured; PostgreSQL integration not measured")
    schema = "idp_test_" + uuid.uuid4().hex
    cat = Catalog(dsn, schema)
    try:
        yield cat
    finally:
        assert schema.startswith("idp_test_") and len(schema) == 41
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


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

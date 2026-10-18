import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psycopg
import pytest

from idp.catalog.ingest import SourceConfig, ingest
from idp.curation.exact import snapshot_exact
from idp.domain.identity import digest
from idp.domain.models import ImageRef, TaskSample
from idp.execution.queue import Queue
from idp.execution.worker import enqueue_views, run_worker
from idp.operators.views import ViewConfig
from idp.releases.models import Caption, Member, ReleasePlan, Selection
from idp.releases.service import Releases
from idp.storage.local import LocalStore
from idp.testing.demo import run_demo, synthetic_plan
from idp.testing.fixtures import generate


def example():
    ref = digest("example")
    caption = Caption(view_id=ref, checksum=ref, text="Synthetic test caption.\n", language="en",
                      producer_version="fixture-v1", provenance_ref="code-generated", reviewer="test",
                      review_version="1", review_method="synthetic-ground-truth", review_reason="Fixture ground truth.")
    sample = TaskSample(created_at=datetime(2026, 10, 18, tzinfo=timezone.utc), producer_version="test-v1",
                        subject_ref=ref, config_digest=ref, sample_id="safe/../../name", task_type="t2i",
                        images=(ImageRef(role="target", asset_id=ref, view_id=ref, checksum=ref, uri="ignored", mode="RGB"),),
                        group_id=ref, caption_ref=caption.annotation_id)
    member = Member(sample=sample, caption=caption, source_ids=(ref,), split="train")
    return ReleasePlan(access_domain="test", selection=Selection(name="test", version="1", description="Synthetic test"),
                       members=(member,)).model_dump(mode="json")


def test_release_contracts_prevent_missing_caption_task_loss_and_leakage():
    plan = example()
    ReleasePlan.model_validate(plan)
    for field, value in (("text", " \n"), ("view_id", digest("other")), ("checksum", digest("other"))):
        bad = example()
        bad["members"][0]["caption"][field] = value
        with pytest.raises(ValueError):
            ReleasePlan.model_validate(bad)
    for field, value in (("caption_ref", None), ("task_type", "image-only")):
        bad = example()
        bad["members"][0]["sample"][field] = value
        with pytest.raises(ValueError):
            ReleasePlan.model_validate(bad)
    bad = example()
    bad["members"][0]["sample"]["images"][0]["mode"] = "RGBA"
    with pytest.raises(ValueError, match="UNSUPPORTED_MODE"):
        ReleasePlan.model_validate(bad)
    plan["members"].append(plan["members"][0])
    with pytest.raises(ValueError, match="DUPLICATE_MEMBER"):
        ReleasePlan.model_validate(plan)
    second = json.loads(json.dumps(plan["members"][0]))
    second["sample"]["sample_id"] = "second"
    second["split"] = "validation"
    plan["members"][1] = second
    with pytest.raises(ValueError, match="CROSS_SPLIT_LEAKAGE"):
        ReleasePlan.model_validate(plan)
    bad = example()
    bad["adapter"] = "webdataset"
    with pytest.raises(ValueError):
        ReleasePlan.model_validate(bad)


@pytest.fixture
def prepared(catalog, tmp_path):
    catalog.migrate(target=4)
    root = tmp_path / "fixtures"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    config = SourceConfig(batch_id="releases", source_name="synthetic", access_domain="synthetic-demo",
                          license_status="approved", evidence_ref="fixture-code-v1")
    assets = {name: ingest(root / f"{name}.png", name, config, store, catalog) for name in ("red", "blue")}
    ingest(root / "red-copy.png", "red-copy", config, store, catalog)
    queue = Queue(catalog)
    enqueue_views(queue, ViewConfig(target_area=48 * 32, aspect_ratios=((3, 2),)), batch_id="releases")
    assert run_worker(queue, store)["outcomes"] == {"succeeded": 2}
    # v4 -> v5保留已有视图及旧迁移摘要。
    catalog.migrate()
    plan = synthetic_plan(catalog, store, assets, "releases")
    return Releases(catalog, store, tmp_path / "releases"), plan


def test_exact_snapshot_idempotence_preserves_all_sources(prepared):
    service, plan = prepared
    first = snapshot_exact(service.catalog, "releases")
    assert first["unique_assets"] == 2 and first["source_records"] == 3
    assert first["duplicate_groups"] == 1 and first["duplicate_sources"] == 1
    assert snapshot_exact(service.catalog, "releases") == first
    assert snapshot_exact(service.catalog, "absent")["source_records"] == 0
    with service.catalog.connect() as conn:
        rows = conn.execute("SELECT payload FROM exact_duplicate_snapshots WHERE snapshot_id=%s", (first["snapshot_id"],)).fetchone()
    assert sorted(len(g["source_ids"]) for g in rows["payload"]["groups"]) == [1, 2]


def test_frozen_release_actual_loader_and_replay_are_deterministic(prepared):
    service, plan = prepared
    with ThreadPoolExecutor(max_workers=2) as pool:
        frozen = list(pool.map(lambda _: service.freeze(plan), range(2)))
    assert frozen[0] == frozen[1]
    release_id = frozen[0]["release_id"]
    assert service.inspect(release_id)["state"] == "draft"
    with pytest.raises(ValueError, match="NOT_READY"):
        list(service.iter_samples(release_id))
    result = service.build(release_id)
    assert result["loaded"] == 2 and result["state"] == "ready"
    assert service.build(release_id) == result
    reversed_plan = ReleasePlan.model_validate({**plan.model_dump(mode="json"), "members": list(reversed(plan.model_dump(mode="json")["members"]))})
    assert service.freeze(reversed_plan) == frozen[0]
    loaded = list(service.iter_samples(release_id, "train"))
    assert len(loaded) == 2 and not list(service.iter_samples(release_id, "test"))
    for item, member in zip(loaded, plan.members):
        assert item["caption"] == member.caption.text
        assert item["image"].size == (48, 32) and item["image"].mode == "RGB"
        item["image"].close()
    with service.catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM release_members").fetchone()["n"] == 2
        assert [r["state"] for r in conn.execute("SELECT state FROM release_events ORDER BY event_id")] == ["draft", "building", "validating", "ready"]
    for path in service.directory(release_id).rglob("*.png"):
        assert len(path.stem) == 64
        # 副本独立于内容寻址存储；训练端改写不得损坏原始视图。
        assert all(not os.path.samefile(path, service.store.path(m.sample.images[0].checksum)) for m in plan.members)


@pytest.mark.parametrize("missing", ["image", "caption"])
def test_missing_export_file_cannot_become_ready_and_can_resume(prepared, monkeypatch, missing):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    original = service._verify_files
    removed = []

    def remove_before_validation(row):
        record = row["manifest"][0]
        relative = record["images"][0]["uri"] if missing == "image" else record["caption_uri"]
        path = service.directory(release_id) / relative
        removed.append((path, path.read_bytes()))
        path.unlink()
        return original(row)

    monkeypatch.setattr(service, "_verify_files", remove_before_validation)
    with pytest.raises(OSError):
        service.build(release_id)
    assert service.inspect(release_id)["state"] == "failed"
    with pytest.raises(ValueError, match="NOT_READY"):
        list(service.iter_samples(release_id))
    monkeypatch.setattr(service, "_verify_files", original)
    assert service.build(release_id)["loaded"] == 2
    assert removed[0][0].read_bytes() == removed[0][1]
    assert service.inspect(release_id)["build_token"] == 2


def test_upload_interruption_retains_verified_files_but_no_ready(prepared, monkeypatch):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    original = service._write
    calls = []

    def interrupt(directory, relative, source, checksum):
        if calls:
            raise OSError("injected interruption")
        original(directory, relative, source, checksum)
        calls.append((directory / relative, (directory / relative).stat().st_mtime_ns))

    monkeypatch.setattr(service, "_write", interrupt)
    with pytest.raises(OSError):
        service.build(release_id)
    assert service.inspect(release_id)["state"] == "failed"
    monkeypatch.setattr(service, "_write", original)
    assert service.build(release_id)["loaded"] == 2
    assert calls[0][0].stat().st_mtime_ns == calls[0][1]


def test_source_withdrawal_and_access_mismatch_block_release(prepared):
    service, plan = prepared
    bad = ReleasePlan.model_validate({**plan.model_dump(mode="json"), "access_domain": "other"})
    with pytest.raises(ValueError, match="ACCESS_DOMAIN"):
        service.freeze(bad)
    release_id = service.freeze(plan)["release_id"]
    service.build(release_id)
    service.catalog.withdraw(plan.members[0].source_ids[0], "test", "fixture withdrawal")
    with pytest.raises(ValueError, match="SOURCE_NOT_APPROVED"):
        service.verify(release_id)
    with pytest.raises(ValueError, match="SOURCE_NOT_APPROVED"):
        list(service.iter_samples(release_id))
    with pytest.raises(ValueError, match="SOURCE_NOT_APPROVED"):
        service.freeze(plan)
    with service.catalog.connect() as conn:
        conn.execute("UPDATE source_records SET license_status='unknown'")
    with pytest.raises(ValueError, match="SOURCE_NOT_APPROVED"):
        service.freeze(plan)


def test_bad_export_or_extra_file_rejected_without_overwriting(prepared):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    directory = service.directory(release_id)
    service.build(release_id)
    extra = directory / "files" / "unexpected.txt"
    extra.write_bytes(b"not a member")
    with pytest.raises(ValueError, match="UNEXPECTED"):
        service.verify(release_id)
    extra.unlink()
    caption = next(directory.rglob("*.txt"))
    caption.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="CAPTION_CHECKSUM"):
        service.build(release_id)
    assert caption.read_bytes() == b"corrupt"


def test_ready_transaction_failure_is_recoverable(prepared):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    with service.catalog.connect() as conn:
        conn.execute("""CREATE FUNCTION reject_ready() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.state='ready' THEN RAISE EXCEPTION 'injected failure'; END IF; RETURN NEW; END $$""")
        conn.execute("CREATE TRIGGER fail_ready BEFORE UPDATE ON releases FOR EACH ROW EXECUTE FUNCTION reject_ready()")
    with pytest.raises(psycopg.Error):
        service.build(release_id)
    assert service.inspect(release_id)["state"] == "failed"
    with service.catalog.connect() as conn:
        assert not conn.execute("SELECT 1 FROM release_events WHERE state='ready'").fetchone()
        conn.execute("DROP TRIGGER fail_ready ON releases")
    assert service.build(release_id)["loaded"] == 2


def test_source_withdrawal_during_validation_blocks_ready(prepared, monkeypatch):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    original = service._verify_files

    def revoke_after_loading(row):
        result = original(row)
        service.catalog.withdraw(plan.members[0].source_ids[0], "test", "withdraw during validation")
        return result

    monkeypatch.setattr(service, "_verify_files", revoke_after_loading)
    with pytest.raises(ValueError, match="SOURCE_NOT_APPROVED"):
        service.build(release_id)
    assert service.inspect(release_id)["state"] == "failed"


def test_parallel_builder_rejected(prepared):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    with service.catalog.connect() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))",
                     (service.catalog.schema + ":build:" + release_id,))
        conn.commit()
        with pytest.raises(ValueError, match="BUILD_BUSY"):
            service.build(release_id)
    assert service.inspect(release_id)["state"] == "draft"


def test_process_kill_during_export_releases_lock_and_resumes(prepared, tmp_path):
    service, plan = prepared
    release_id = service.freeze(plan)["release_id"]
    signal = tmp_path / "uploaded.json"
    env = {**os.environ, "CRASH_DSN": service.catalog.dsn, "CRASH_SCHEMA": service.catalog.schema,
           "CRASH_STORE": str(service.store.root), "CRASH_EXPORT": str(service.root),
           "CRASH_RELEASE": release_id, "CRASH_SIGNAL": str(signal)}
    script = '''
import json, os, time
from pathlib import Path
from idp.catalog.postgres import Catalog
from idp.storage.local import LocalStore
from idp.releases.service import Releases
service = Releases(Catalog(os.environ['CRASH_DSN'],os.environ['CRASH_SCHEMA']),
                   LocalStore(Path(os.environ['CRASH_STORE'])),Path(os.environ['CRASH_EXPORT']))
original = service._write
def interrupted(directory, relative, source, checksum):
    original(directory, relative, source, checksum)
    Path(os.environ['CRASH_SIGNAL']).write_text(json.dumps({'file':relative}),encoding='utf-8')
    time.sleep(60)
service._write = interrupted
service.build(os.environ['CRASH_RELEASE'])
'''
    proc = subprocess.Popen([sys.executable, "-c", script], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not signal.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert signal.exists(), "Builder did not reach injected crash point"
        exported = service.directory(release_id) / json.loads(signal.read_text(encoding="utf-8"))["file"]
        modified = exported.stat().st_mtime_ns
        assert service.inspect(release_id)["state"] == "building"
        with pytest.raises(ValueError, match="NOT_READY"):
            service.verify(release_id)
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert service.build(release_id)["loaded"] == 2
    assert exported.stat().st_mtime_ns == modified


def test_release_cli_and_synthetic_demo(catalog, tmp_path):
    directory = tmp_path / "new-demo"
    env = {**os.environ, "IDP_DATABASE_DSN": catalog.dsn, "IDP_CATALOG_SCHEMA": catalog.schema}
    proc = subprocess.run([sys.executable, "-m", "idp.cli", "demo", str(directory)], env=env,
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, "Demo failed; sensitive output omitted"
    report = json.loads(proc.stdout)
    assert report["synthetic_only"] and report["loaded"] == 2 and report["replay_processed"] == 0
    assert report["jobs"]["outcomes"] == {"succeeded": 6}
    release_id = report["release"]["release_id"]
    env.update(IDP_OBJECT_ROOT=str(directory / "objects"), IDP_RELEASE_ROOT=str(directory / "releases"))
    for command in (("release", "freeze", str(directory / "release-plan.json")),
                    ("release", "build", release_id), ("release", "verify", release_id),
                    ("release", "read", release_id), ("release", "inspect", release_id),
                    ("duplicates", "exact")):
        proc = subprocess.run([sys.executable, "-m", "idp.cli", *command], env=env,
                              capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, "CLI failed; sensitive output omitted"
        result = json.loads(proc.stdout)
        assert "caption" not in result and "images" not in result
    with pytest.raises(FileExistsError):
        run_demo(catalog, directory)

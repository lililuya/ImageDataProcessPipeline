"""只使用代码生成的合成图像；不会接收外部图片或标注。"""

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from idp.catalog.ingest import SourceConfig, ingest
from idp.catalog.postgres import Catalog
from idp.curation.exact import snapshot_exact
from idp.domain.identity import canonical_bytes, digest
from idp.domain.models import ImageRef, TaskSample, View
from idp.execution.queue import Queue
from idp.execution.worker import enqueue_probes, enqueue_quality, enqueue_views, run_worker
from idp.operators.views import ViewConfig
from idp.releases.models import Caption, Member, ReleasePlan, Selection
from idp.releases.service import Releases
from idp.storage.local import LocalStore
from idp.testing.fixtures import generate


def synthetic_plan(catalog: Catalog, store: LocalStore, assets: dict[str, str], batch_id: str) -> ReleasePlan:
    """仅供合成夹具演练使用；标注来自生成定义，禁止用于真实输入。"""
    members = []
    config_digest = digest({"generator": "synthetic-demo-v1"})
    with catalog.connect() as conn:
        for name, asset in sorted(assets.items()):
            registered = conn.execute("SELECT record,details FROM views WHERE asset_id=%s ORDER BY view_id", (asset,)).fetchall()
            if len(registered) != 1:
                raise ValueError("DEMO_REQUIRES_ONE_VIEW_PER_ASSET")
            view = View.model_validate(registered[0]["record"])
            if (view.input_width, view.input_height, view.crop_box) != (96, 64, (0, 0, 96, 64)):
                raise ValueError("SYNTHETIC_GROUND_TRUTH_REQUIRES_FULL_FRAME")
            caption = Caption(view_id=view.view_id, checksum=view.output_checksum,
                              text=f"A {name} rectangle on a white background.", language="en",
                              producer_version="idp-fixtures-v1", provenance_ref="idp.testing.fixtures.generate",
                              reviewer="synthetic-fixture-generator", review_version="fixture-ground-truth-v1",
                              review_method="synthetic-ground-truth", review_reason="Full frame of a code-generated fixture.")
            image = ImageRef(role="target", asset_id=asset, view_id=view.view_id, checksum=view.output_checksum,
                             uri=str(store.path(view.output_checksum)), mode="RGB")
            sample = TaskSample(created_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
                                producer_version="synthetic-demo-v1", subject_ref=view.view_id,
                                config_digest=config_digest, sample_id=f"{batch_id}-{name}",
                                task_type="t2i", images=(image,), group_id=asset, caption_ref=caption.annotation_id)
            sources = conn.execute("SELECT source_id FROM source_records WHERE asset_id=%s AND batch_id=%s ORDER BY source_id",
                                   (asset, batch_id)).fetchall()
            members.append(Member(sample=sample, caption=caption, source_ids=tuple(s["source_id"] for s in sources), split="train"))
    return ReleasePlan(access_domain="synthetic-demo", selection=Selection(name="synthetic-demo", version="1",
                       description="Generated RGB fixtures with full-frame views; no real training claims."), members=tuple(members))


def run_demo(catalog: Catalog, directory: Path) -> dict:
    started = perf_counter()
    directory = directory.resolve()
    if not catalog.schema.startswith(("idp_demo_", "idp_test_")):
        raise ValueError("DEMO_REQUIRES_DEDICATED_SCHEMA")
    # 新目录约束在迁移和任何接入之前检查；不把用户目录当作demo输入。
    directory.mkdir(parents=True, exist_ok=False)
    generate(directory / "fixtures")
    catalog.migrate()
    with catalog.connect() as conn:
        if conn.execute("SELECT (SELECT count(*) FROM assets)+(SELECT count(*) FROM jobs) AS n").fetchone()["n"]:
            raise ValueError("DEMO_REQUIRES_EMPTY_CATALOG")
    batch_id = "synthetic-demo-" + digest(str(directory))[7:23]
    config = SourceConfig(batch_id=batch_id, source_name="idp-fixtures-v1", access_domain="synthetic-demo",
                          license_status="approved", evidence_ref="code-generated-test-fixtures-only")
    store = LocalStore(directory / "objects")
    assets = {}
    for filename in ("red.png", "red-copy.png", "blue.png"):
        asset = ingest(directory / "fixtures" / filename, filename, config, store, catalog)
        if filename != "red-copy.png":
            assets[filename.removesuffix(".png")] = asset
    duplicates = snapshot_exact(catalog, batch_id)
    queue = Queue(catalog)
    enqueue_probes(queue, batch_id=batch_id)
    enqueue_quality(queue, batch_id=batch_id)
    # 96x64 -> 48x32，全画面、无裁剪，合成标注可由生成规则证明。
    view_config = ViewConfig(target_area=48 * 32, aspect_ratios=((3, 2),))
    enqueue_views(queue, view_config, batch_id=batch_id)
    jobs = run_worker(queue, store, max_jobs=6)
    plan = synthetic_plan(catalog, store, assets, batch_id)
    (directory / "release-plan.json").write_bytes(canonical_bytes(plan.model_dump(mode="json")))
    releases = Releases(catalog, store, directory / "releases")
    frozen = releases.freeze(plan)
    built = releases.build(frozen["release_id"])
    count = 0
    for loaded in releases.iter_samples(frozen["release_id"]):
        loaded["image"].close()
        count += 1
    # 冻结/构建与作业重放不改变成员和摘要。
    assert releases.freeze(plan) == frozen
    assert releases.build(frozen["release_id"])["manifest_checksum"] == frozen["manifest_checksum"]
    replay = run_worker(queue, store, max_jobs=6)
    report = {"synthetic_only": True, "duplicates": duplicates, "jobs": jobs, "release": built,
              "loaded": count, "replay_processed": replay["processed"], "elapsed_seconds": perf_counter() - started}
    (directory / "demo-report.json").write_bytes(canonical_bytes(report))
    return report

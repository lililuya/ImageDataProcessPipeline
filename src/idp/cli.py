import argparse
import json
import os
from pathlib import Path

from idp.domain.models import Asset, SourceRecord, TaskSample, View
from idp.evaluation.audit import estimate, sample_frame
from idp.testing.fixtures import generate
from idp.catalog.postgres import Catalog
from idp.catalog.ingest import SourceConfig, ingest
from idp.storage.local import LocalStore
from idp.operators.probe import probe
from idp.evaluation.pilot import run_pilot
from idp.execution.queue import Queue
from idp.execution.worker import enqueue_probes, enqueue_quality, enqueue_views, run_worker
from idp.operators.views import ViewConfig
from idp.operators.quality import quality_features
from idp.curation.numeric import NumericRecipe, evaluate_numeric
from idp.curation.exact import snapshot_exact
from idp.curation.recipes import FeatureObservation, Recipe, SelectionInput
from idp.curation.service import Recipes
from idp.releases.models import ReleasePlan
from idp.releases.service import Releases
import psycopg


def _read(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _catalog() -> Catalog:
    return Catalog(os.environ["IDP_DATABASE_DSN"], os.environ.get("IDP_CATALOG_SCHEMA", "idp"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="idp", description="图像数据框架：契约、夹具与分层审计")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="校验数据契约 JSON")
    validate.add_argument("kind", choices=["asset", "source", "view", "sample"])
    validate.add_argument("path")
    fixtures = commands.add_parser("fixtures", help="在新目录生成合成测试素材")
    fixtures.add_argument("directory")
    audit = commands.add_parser("audit", help="分层审核抽样与加权估计")
    audits = audit.add_subparsers(dest="audit_command", required=True)
    sample = audits.add_parser("sample")
    sample.add_argument("frame")
    sample.add_argument("allocation")
    sample.add_argument("--seed", type=int, default=42)
    report = audits.add_parser("estimate")
    report.add_argument("plan")
    db = commands.add_parser("db", help="迁移独立项目元数据库")
    db.add_argument("action", choices=["migrate"])
    ingestion = commands.add_parser("ingest", help="本地单文件内容寻址接入")
    ingestion.add_argument("path")
    ingestion.add_argument("--source-config", required=True)
    ingestion.add_argument("--original-id", required=True)
    decoding = commands.add_parser("probe", help="实际解码并输出基础观测，不自动筛图")
    decoding.add_argument("path")
    decoding.add_argument("--max-pixels", type=int, default=100_000_000)
    decoding.add_argument("--max-frames", type=int, default=64)
    pilot = commands.add_parser("pilot", help="只读输入的小批接入/解码/重放演练，仅输出汇总")
    pilot.add_argument("directory")
    pilot.add_argument("--source-config", required=True)
    pilot.add_argument("--limit", type=int, default=64)
    jobs = commands.add_parser("jobs", help="持久任务管理，输出不含原始路径与图像内容")
    job_commands = jobs.add_subparsers(dest="jobs_command", required=True)
    job_commands.add_parser("metrics")
    inspect = job_commands.add_parser("inspect")
    inspect.add_argument("task_key")
    retry = job_commands.add_parser("retry")
    retry.add_argument("task_key")
    retry.add_argument("--actor", required=True)
    retry.add_argument("--reason", required=True)
    pool = job_commands.add_parser("pool")
    pool.add_argument("resource", choices=["cpu", "gpu", "api"])
    pool.add_argument("--concurrency", type=int, required=True)
    pool.add_argument("--paused", action="store_true")
    enqueue = job_commands.add_parser("enqueue-probes")
    enqueue.add_argument("--limit", type=int, default=64)
    enqueue.add_argument("--batch-id")
    quality_jobs = job_commands.add_parser("enqueue-quality")
    quality_jobs.add_argument("--limit", type=int, default=64)
    quality_jobs.add_argument("--batch-id")
    view_jobs = job_commands.add_parser("enqueue-views")
    view_jobs.add_argument("--config", required=True)
    view_jobs.add_argument("--limit", type=int, default=64)
    view_jobs.add_argument("--batch-id")
    quality = commands.add_parser("quality", help="独立质量数值观测，不作语义审核")
    quality.add_argument("path")
    check = commands.add_parser("quality-check", help="按指定数值配方评估观测，不改原始资产")
    check.add_argument("--recipe", required=True)
    check.add_argument("--observation", required=True)
    recipe = commands.add_parser("recipe", help="冻结配方、固定观测与可追溯选择；不执行评分模型")
    recipes = recipe.add_subparsers(dest="recipe_command", required=True)
    recipes.add_parser("freeze").add_argument("path")
    recipes.add_parser("import-observation").add_argument("path")
    recipes.add_parser("capture-quality").add_argument("task_key")
    recipes.add_parser("observation").add_argument("observation_id")
    recipes.add_parser("inspect").add_argument("recipe_digest")
    recipes.add_parser("decision").add_argument("decision_id")
    decide = recipes.add_parser("decide")
    decide.add_argument("recipe_digest")
    decide.add_argument("--input", required=True)
    worker = commands.add_parser("worker", help="有界CPU解码、质量与视图worker，不执行语义模型")
    worker.add_argument("--max-jobs", type=int, default=64)
    worker.add_argument("--lease-seconds", type=float, default=60)
    duplicates = commands.add_parser("duplicates", help="字节重复来源簇的不可变快照")
    duplicates.add_argument("action", choices=["exact"])
    duplicates.add_argument("--batch-id")
    release = commands.add_parser("release", help="最小T2I目录sidecar发布与实际读取")
    releases = release.add_subparsers(dest="release_command", required=True)
    freeze = releases.add_parser("freeze")
    freeze.add_argument("plan")
    for name in ("build", "verify", "inspect", "read"):
        action = releases.add_parser(name)
        action.add_argument("release_id")
    demo = commands.add_parser("demo", help="仅用新生成的合成素材跑通本地闭环")
    demo.add_argument("directory", help="新的、仓库外的合成演练目录")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            model = {"asset": Asset, "source": SourceRecord, "view": View, "sample": TaskSample}[args.kind]
            model.model_validate(_read(args.path))
            result = {"valid": True, "kind": args.kind}
        elif args.command == "fixtures":
            result = generate(Path(args.directory))
        elif args.command == "demo":
            from idp.testing.demo import run_demo
            result = run_demo(_catalog(), Path(args.directory))
        elif args.command == "duplicates":
            result = snapshot_exact(_catalog(), args.batch_id)
        elif args.command == "release":
            service = Releases(_catalog(), LocalStore(Path(os.environ["IDP_OBJECT_ROOT"])),
                               Path(os.environ["IDP_RELEASE_ROOT"]))
            if args.release_command == "freeze":
                result = service.freeze(ReleasePlan.model_validate(_read(args.plan)))
            elif args.release_command == "read":
                count = 0
                for loaded in service.iter_samples(args.release_id):
                    count += 1
                    loaded["image"].close()
                result = {"release_id": args.release_id, "loaded": count}
            else:
                result = getattr(service, args.release_command)(args.release_id)
        elif args.command in {"jobs", "worker"}:
            queue = Queue(_catalog())
            if args.command == "worker":
                result = run_worker(queue, LocalStore(Path(os.environ["IDP_OBJECT_ROOT"])),
                                    args.max_jobs, args.lease_seconds)
            elif args.jobs_command == "metrics":
                result = queue.metrics()
            elif args.jobs_command == "inspect":
                result = queue.inspect(args.task_key)
                result = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in result.items()}
            elif args.jobs_command == "retry":
                queue.replay(args.task_key, args.actor, args.reason)
                result = {"replayed": True}
            elif args.jobs_command == "pool":
                queue.configure_pool(args.resource, args.concurrency, args.paused)
                result = {"resource": args.resource, "concurrency": args.concurrency, "paused": args.paused}
            elif args.jobs_command == "enqueue-views":
                result = enqueue_views(queue, ViewConfig.model_validate(_read(args.config)), args.limit, args.batch_id)
            elif args.jobs_command == "enqueue-quality":
                result = enqueue_quality(queue, args.limit, args.batch_id)
            else:
                result = enqueue_probes(queue, args.limit, args.batch_id)
        elif args.command == "quality":
            result = quality_features(Path(args.path))
        elif args.command == "recipe":
            service = Recipes(_catalog())
            if args.recipe_command == "freeze":
                result = service.freeze(Recipe.model_validate(_read(args.path)))
            elif args.recipe_command == "import-observation":
                result = service.import_observation(FeatureObservation.model_validate(_read(args.path)))
            elif args.recipe_command == "capture-quality":
                result = service.capture_quality(args.task_key)
            elif args.recipe_command == "observation":
                result = service.get_observation(args.observation_id)
            elif args.recipe_command == "inspect":
                result = service.get_recipe(args.recipe_digest)
            elif args.recipe_command == "decision":
                result = service.get_decision(args.decision_id)
            else:
                result = service.decide(args.recipe_digest, SelectionInput.model_validate(_read(args.input)))
        elif args.command == "quality-check":
            result = evaluate_numeric(NumericRecipe.model_validate(_read(args.recipe)), _read(args.observation))
        elif args.command == "pilot":
            result = run_pilot(Path(args.directory), SourceConfig.model_validate(_read(args.source_config)),
                               LocalStore(Path(os.environ["IDP_OBJECT_ROOT"])),
                               _catalog(), args.limit)
        elif args.command == "probe":
            result = probe(Path(args.path), args.max_pixels, args.max_frames)
        elif args.command == "db":
            _catalog().migrate()
            result = {"migrated": True}
        elif args.command == "ingest":
            checksum = ingest(Path(args.path), args.original_id,
                              SourceConfig.model_validate(_read(args.source_config)),
                              LocalStore(Path(os.environ["IDP_OBJECT_ROOT"])),
                              _catalog())
            result = {"asset_id": checksum}
        elif args.audit_command == "sample":
            result = sample_frame(_read(args.frame), _read(args.allocation), args.seed)
        else:
            result = estimate(_read(args.plan))
    except (ValueError, OSError, KeyError, psycopg.Error) as exc:
        # 不打印 ValidationError 的输入值，避免完整文字与来源信息进入日志。
        parser.exit(2, f"idp: {type(exc).__name__}; input rejected\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

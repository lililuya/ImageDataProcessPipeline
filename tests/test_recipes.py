import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.types.json import Jsonb

from idp.catalog.ingest import SourceConfig, ingest
from idp.curation.recipes import (Binding, FeatureObservation, Recipe, Rule,
                                  SelectionInput, Subject, evaluate)
from idp.curation.service import Recipes
from idp.domain.identity import digest
from idp.execution.operators import OperatorSpec
from idp.execution.queue import Queue
from idp.execution.worker import QUALITY_SPEC, enqueue_quality, enqueue_views, run_worker
from idp.operators.views import ViewConfig
from idp.releases.models import ReleasePlan
from idp.releases.service import Releases
from idp.storage.local import LocalStore
from idp.testing.demo import synthetic_plan
from idp.testing.fixtures import generate


def score_spec(version="1"):
    return OperatorSpec(operator_id="synthetic-score-fixture", operator_version="1",
                        input_schema="image-checksum-v1", output_schema="fixture-score-v1",
                        model_digest=digest({"fixture-model": version}), config_digest=digest({"scale": "fixture-only"}),
                        resource="cpu", max_batch_size=1)


def base_recipe(**updates):
    return Recipe.model_validate({"name": "test", "version": "1", "domain": "fixture", "stage": "broad",
                                  "task_type": "t2i", **updates})


def score(subject=None, **updates):
    return FeatureObservation.model_validate({"subject": subject or Subject(asset_id=digest("asset"), checksum=digest("asset")),
               "producer": score_spec(), "provenance_ref": "synthetic-test-only", "status": "ok",
               "metrics": {"aesthetic": 0.0}, **updates})


def test_defaults_frozen_and_old_model_remains_auditable():
    sparse = {"name": "test", "version": "1", "domain": "fixture", "stage": "broad", "task_type": "t2i"}
    first = Recipe.model_validate(sparse)
    assert first.recipe_digest == Recipe.model_validate(first.model_dump(mode="json")).recipe_digest
    assert first.model_dump()["seed"] == 42 and not first.calibrated
    binding = Binding(name="aesthetic", producer=score_spec(), scope="asset", required=True)
    old = base_recipe(observations=[binding.model_dump(mode="json")])
    item = score()
    candidate = SelectionInput(subject=item.subject, observation_refs={"aesthetic": item.observation_id})
    before = evaluate(old, candidate, {item.observation_id: item})
    upgraded = base_recipe(observations=[{**binding.model_dump(mode="json"), "producer": score_spec("2")}])
    assert upgraded.recipe_digest != old.recipe_digest
    new = evaluate(upgraded, candidate, {item.observation_id: item})
    assert new["decision"] == "needs_observation" and new["evidence"][0]["code"] == "PRODUCER_MISMATCH"
    assert evaluate(old, candidate, {item.observation_id: item}) == before


def test_broad_optional_score_and_selected_threshold_are_independent():
    item = score()
    binding = Binding(name="aesthetic", producer=item.producer, scope="asset")
    broad = base_recipe(observations=[binding])
    candidate = SelectionInput(subject=item.subject, observation_refs={"aesthetic": item.observation_id})
    selected = base_recipe(observations=[binding], rules=[Rule(rule_id="minimum", observation="aesthetic",
                                                            metric="aesthetic", operator="ge", value=1.0)])
    assert evaluate(broad, candidate, {item.observation_id: item})["decision"] == "accept"
    rejected = evaluate(selected, candidate, {item.observation_id: item})
    assert rejected["decision"] == "reject" and rejected["checks"][0]["value"] == 0
    assert not rejected["passes_calibrated_rules"]
    missing = SelectionInput(subject=item.subject)
    assert evaluate(broad, missing, {})["decision"] == "accept"
    assert evaluate(selected, missing, {})["decision"] == "needs_observation"
    unknown = base_recipe(observations=[binding], rules=[Rule(rule_id="pending", observation="aesthetic",
                                                           metric="aesthetic", operator="ge")])
    assert evaluate(unknown, candidate, {item.observation_id: item})["decision"] == "needs_calibration"


@pytest.mark.parametrize("value", [True, "3.2", float("nan"), float("inf")])
def test_invalid_score_never_becomes_zero(value):
    with pytest.raises(ValueError):
        score(metrics={"aesthetic": value})


def test_failed_unsupported_missing_metric_and_wrong_view_are_not_quality_rejects():
    subject = Subject(asset_id=digest("asset"), view_id=digest("view"), checksum=digest("output"))
    binding = Binding(name="q", producer=score_spec(), scope="view", required=True)
    recipe = base_recipe(observations=[binding], rules=[Rule(rule_id="q", observation="q", metric="aesthetic", operator="ge", value=0)])
    for item in (score(), score(subject, metrics={"aesthetic": None}),
                 score(subject, status="failed", metrics={}, error_code="PROVIDER_OOM"),
                 score(subject, status="unsupported", metrics={}, error_code="INPUT_MODE")):
        candidate = SelectionInput(subject=subject, observation_refs={"q": item.observation_id})
        assert evaluate(recipe, candidate, {item.observation_id: item})["decision"] == "needs_observation"
    with pytest.raises(ValueError, match="NO_METRICS"):
        score(status="failed", error_code="FAILURE")
    ref = digest("annotation")
    recipe = base_recipe(required_annotation_refs=[ref], required_review_refs=[ref])
    assert evaluate(recipe, SelectionInput(subject=subject), {})["decision"] == "needs_review"


@pytest.fixture
def prepared(catalog, tmp_path):
    catalog.migrate(target=5)
    root = tmp_path / "fixtures"
    generate(root)
    store = LocalStore(tmp_path / "objects")
    config = SourceConfig(batch_id="recipe", source_name="synthetic", access_domain="synthetic-demo",
                          license_status="approved", evidence_ref="fixture-code-v1")
    assets = {name: ingest(root / f"{name}.png", name, config, store, catalog) for name in ("red", "blue")}
    queue = Queue(catalog)
    enqueue_views(queue, ViewConfig(target_area=48 * 32, aspect_ratios=((3, 2),)))
    quality_keys = enqueue_quality(queue)["task_keys"]
    assert run_worker(queue, store)["outcomes"] == {"succeeded": 4}
    plan = synthetic_plan(catalog, store, assets, "recipe")
    # 先建立v5发布，再升级到v6，旧发布仍可消费。
    releases = Releases(catalog, store, tmp_path / "releases")
    old = releases.freeze(plan)
    releases.build(old["release_id"])
    catalog.migrate()
    assert releases.verify(old["release_id"])["loaded"] == 2
    assert releases.freeze(plan) == old
    return Recipes(catalog), releases, plan, quality_keys


def test_persistent_capture_replay_concurrency_and_upgrade(prepared):
    service, _, plan, keys = prepared
    with ThreadPoolExecutor(max_workers=2) as pool:
        captured = list(pool.map(lambda _: service.capture_quality(keys[0]), range(2)))
    assert captured[0] == captured[1]
    with service.catalog.connect() as conn:
        item = FeatureObservation.model_validate(conn.execute("SELECT payload FROM feature_observations").fetchone()["payload"])
    recipe = base_recipe(observations=[Binding(name="numeric", producer=QUALITY_SPEC, scope="asset", required=True)])
    frozen = service.freeze(recipe)
    assert service.freeze(Recipe.model_validate(service.get_recipe(recipe.recipe_digest))) == frozen
    candidate = SelectionInput(subject=item.subject, observation_refs={"numeric": item.observation_id})
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(lambda _: service.decide(recipe.recipe_digest, candidate), range(2)))
    assert decisions[0] == decisions[1] == service.get_decision(decisions[0]["decision_id"])
    assert decisions[0]["decision"] == "accept"
    changed = base_recipe(observations=[Binding(name="numeric", producer=score_spec("upgrade"), scope="asset", required=True)])
    service.freeze(changed)
    assert service.decide(changed.recipe_digest, candidate)["decision"] == "needs_observation"
    assert service.decide(recipe.recipe_digest, candidate) == decisions[0]
    with service.catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM feature_observations").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM recipes").fetchone()["n"] == 2
    with pytest.raises(ValueError, match="COMMITTED_QUALITY"):
        service.capture_quality(digest("missing-job"))


def bind_plan(service, plan, recipe):
    service.freeze(recipe)
    payload = plan.model_dump(mode="json")
    payload["selection"]["recipe_digest"] = recipe.recipe_digest
    for member in payload["members"]:
        image = member["sample"]["images"][0]
        subject = Subject(asset_id=image["asset_id"], view_id=image["view_id"], checksum=image["checksum"])
        decision = service.decide(recipe.recipe_digest, SelectionInput(subject=subject))
        member["decision_id"] = decision["decision_id"]
    return payload


def test_release_pins_decisions_and_keeps_source_checks(prepared):
    service, releases, plan, _ = prepared
    recipe = base_recipe()
    payload = bind_plan(service, plan, recipe)
    bound = ReleasePlan.model_validate(payload)
    frozen = releases.freeze(bound)
    assert releases.build(frozen["release_id"])["loaded"] == 2
    with service.catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM release_decisions").fetchone()["n"] == 2
        rows = conn.execute("SELECT manifest FROM releases WHERE release_id=%s", (frozen["release_id"],)).fetchone()["manifest"]
    assert all(row["recipe_digest"] == recipe.recipe_digest and row["decision_ref"] for row in rows)
    payload["members"][0]["decision_id"] = payload["members"][1]["decision_id"]
    with pytest.raises(ValueError, match="DECISION_MISMATCH"):
        releases.freeze(ReleasePlan.model_validate(payload))
    service.catalog.withdraw(plan.members[0].source_ids[0], "test", "synthetic source withdrawn")
    with pytest.raises(ValueError, match="SOURCE_NOT_APPROVED"):
        list(releases.iter_samples(frozen["release_id"]))


def test_calibrated_fixture_score_can_bind_release(prepared):
    service, releases, plan, _ = prepared
    recipe = base_recipe(calibrated=True, calibration_ref="synthetic-fixture-test-only",
                         observations=[Binding(name="score", producer=score_spec(), scope="view", required=True)],
                         rules=[Rule(rule_id="score", observation="score", metric="aesthetic", operator="ge", value=0)])
    service.freeze(recipe)
    payload = plan.model_dump(mode="json")
    payload["selection"]["recipe_digest"] = recipe.recipe_digest
    for member in payload["members"]:
        image = member["sample"]["images"][0]
        subject = Subject(asset_id=image["asset_id"], view_id=image["view_id"], checksum=image["checksum"])
        item = score(subject)
        service.import_observation(item)
        assert service.get_observation(item.observation_id)["metrics"]["aesthetic"] == 0
        decision = service.decide(recipe.recipe_digest, SelectionInput(subject=subject, observation_refs={"score": item.observation_id}))
        assert decision["passes_calibrated_rules"]
        member["decision_id"] = decision["decision_id"]
    frozen = releases.freeze(ReleasePlan.model_validate(payload))
    assert releases.build(frozen["release_id"])["loaded"] == 2


def test_rejected_and_uncalibrated_rules_cannot_enter_release(prepared):
    service, releases, plan, _ = prepared
    recipe = base_recipe(observations=[Binding(name="score", producer=score_spec(), scope="view")],
                         rules=[Rule(rule_id="score", observation="score", metric="aesthetic", operator="ge", value=0)])
    payload = bind_plan(service, plan, recipe)
    with pytest.raises(ValueError, match="CALIBRATED_RULES"):
        releases.freeze(ReleasePlan.model_validate(payload))
    recipe = base_recipe(required_review_refs=[digest("missing-review")])
    payload = bind_plan(service, plan, recipe)
    with pytest.raises(ValueError, match="DECISION_MISMATCH"):
        releases.freeze(ReleasePlan.model_validate(payload))


def test_decision_transaction_failure_rolls_back_and_recovers(prepared):
    service, _, plan, _ = prepared
    image = plan.members[0].sample.images[0]
    item = score(Subject(asset_id=image.asset_id, view_id=image.view_id, checksum=image.checksum))
    service.import_observation(item)
    recipe = base_recipe(observations=[Binding(name="score", producer=item.producer, scope="view", required=True)])
    service.freeze(recipe)
    candidate = SelectionInput(subject=item.subject, observation_refs={"score": item.observation_id})
    with service.catalog.connect() as conn:
        conn.execute("""CREATE FUNCTION reject_decision_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic commit failure'; END $$""")
        conn.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON decision_observations FOR EACH ROW EXECUTE FUNCTION reject_decision_evidence()")
    with pytest.raises(psycopg.Error):
        service.decide(recipe.recipe_digest, candidate)
    with service.catalog.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM recipe_decisions").fetchone()["n"] == 0
        conn.execute("DROP TRIGGER fail_evidence ON decision_observations")
    result = service.decide(recipe.recipe_digest, candidate)
    assert result["decision"] == "accept" and service.decide(recipe.recipe_digest, candidate) == result


def test_cli_and_pinned_integrity(prepared, tmp_path):
    service, _, plan, _ = prepared
    env = os.environ | {"IDP_DATABASE_DSN": service.catalog.dsn, "IDP_CATALOG_SCHEMA": service.catalog.schema, "PYTHONUTF8": "1"}
    path = tmp_path / "recipe.json"
    path.write_text(base_recipe().model_dump_json(), encoding="utf-8")
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "idp.cli", "recipe", *args], env=env, capture_output=True, text=True, check=True)
    result = json.loads(cli("freeze", str(path)).stdout)
    assert json.loads(cli("inspect", result["recipe_digest"]).stdout)["seed"] == 42
    image = plan.members[0].sample.images[0]
    path.write_text(SelectionInput(subject=Subject(asset_id=image.asset_id, view_id=image.view_id, checksum=image.checksum)).model_dump_json(), encoding="utf-8")
    decision = json.loads(cli("decide", result["recipe_digest"], "--input", str(path)).stdout)
    assert json.loads(cli("decision", decision["decision_id"]).stdout) == decision
    # 目录被外部错误修改时不能把不匹配的内容当成旧配方。
    with service.catalog.connect() as conn:
        conn.execute("UPDATE recipes SET payload=%s WHERE recipe_digest=%s", (Jsonb(base_recipe(seed=9).model_dump(mode="json")), result["recipe_digest"]))
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        service.get_recipe(result["recipe_digest"])

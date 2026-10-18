"""持久化追加配方、评分观测和决策，保留已固定的模型及输入版本。"""

from psycopg.types.json import Jsonb

from idp.catalog.postgres import Catalog
from idp.curation.recipes import FeatureObservation, Recipe, SelectionInput, Subject, evaluate
from idp.domain.identity import digest
from idp.execution.operators import OperatorSpec


class Recipes:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def _subject(self, conn, subject: Subject):
        if subject.view_id is not None:
            row = conn.execute("SELECT asset_id,output_checksum,config_digest FROM views WHERE view_id=%s",
                               (subject.view_id,)).fetchone()
            if not row or row["asset_id"] != subject.asset_id or row["output_checksum"] != subject.checksum:
                raise ValueError("REGISTERED_VIEW_SUBJECT_REQUIRED")
            return row["config_digest"]
        if not conn.execute("SELECT 1 FROM assets WHERE asset_id=%s", (subject.asset_id,)).fetchone():
            raise ValueError("REGISTERED_ASSET_SUBJECT_REQUIRED")
        return None

    def _observation(self, conn, item: FeatureObservation, task_key: str | None = None):
        self._subject(conn, item.subject)
        payload = item.model_dump(mode="json")
        conn.execute("""INSERT INTO feature_observations(observation_id,asset_id,view_id,task_key,payload)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                     (item.observation_id, item.subject.asset_id, item.subject.view_id, task_key, Jsonb(payload)))
        return {"observation_id": item.observation_id, "status": item.status}

    def import_observation(self, item: FeatureObservation):
        # 导入的是调用方声明的结果；不将其视作已完成真实provider推理或校准。
        with self.catalog.connect() as conn:
            return self._observation(conn, item)

    def get_observation(self, observation_id: str) -> dict:
        with self.catalog.connect() as conn:
            row = conn.execute("SELECT payload FROM feature_observations WHERE observation_id=%s", (observation_id,)).fetchone()
        if not row:
            raise ValueError("PINNED_OBSERVATION_NOT_FOUND")
        item = FeatureObservation.model_validate(row["payload"])
        if item.observation_id != observation_id:
            raise ValueError("OBSERVATION_DIGEST_MISMATCH")
        return {"observation_id": observation_id, **item.model_dump(mode="json")}

    def capture_quality(self, task_key: str):
        with self.catalog.connect() as conn:
            row = conn.execute("""SELECT o.*,j.state FROM observations o JOIN jobs j USING(task_key)
                WHERE task_key=%s""", (task_key,)).fetchone()
            if (not row or row["state"] != "succeeded" or len(row["subject_refs"]) != 1
                    or row["payload"].get("schema_version") != "quality-v1"
                    or row["producer"].get("operator_id") != "image-quality"):
                raise ValueError("COMMITTED_QUALITY_OBSERVATION_REQUIRED")
            asset = row["subject_refs"][0]
            item = FeatureObservation(subject=Subject(asset_id=asset, checksum=asset),
                                      producer=OperatorSpec.model_validate(row["producer"]),
                                      provenance_ref="committed-job:" + task_key, status="ok",
                                      metrics=row["payload"]["metrics"])
            return self._observation(conn, item, task_key)

    def freeze(self, recipe: Recipe):
        with self.catalog.connect() as conn:
            conn.execute("INSERT INTO recipes(recipe_digest,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                         (recipe.recipe_digest, Jsonb(recipe.model_dump(mode="json"))))
        return {"recipe_digest": recipe.recipe_digest, "calibrated": recipe.calibrated}

    def _recipe(self, conn, recipe_digest: str) -> Recipe:
        row = conn.execute("SELECT payload FROM recipes WHERE recipe_digest=%s", (recipe_digest,)).fetchone()
        if not row:
            raise ValueError("FROZEN_RECIPE_NOT_FOUND")
        recipe = Recipe.model_validate(row["payload"])
        if recipe.recipe_digest != recipe_digest:
            raise ValueError("FROZEN_RECIPE_DIGEST_MISMATCH")
        return recipe

    def get_recipe(self, recipe_digest: str) -> dict:
        with self.catalog.connect() as conn:
            return self._recipe(conn, recipe_digest).model_dump(mode="json")

    def decide(self, recipe_digest: str, candidate: SelectionInput):
        with self.catalog.connect() as conn:
            recipe = self._recipe(conn, recipe_digest)
            view_config = self._subject(conn, candidate.subject)
            if recipe.view_config_digest is not None and view_config != recipe.view_config_digest:
                raise ValueError("RECIPE_VIEW_CONFIG_MISMATCH")
            observations = {}
            for ref in set(candidate.observation_refs.values()):
                row = conn.execute("SELECT payload FROM feature_observations WHERE observation_id=%s", (ref,)).fetchone()
                if not row:
                    raise ValueError("PINNED_OBSERVATION_NOT_FOUND")
                observations[ref] = FeatureObservation.model_validate(row["payload"])
            decision = evaluate(recipe, candidate, observations)
            conn.execute("""INSERT INTO recipe_decisions(decision_id,recipe_digest,asset_id,view_id,payload)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (decision["decision_id"], recipe_digest, candidate.subject.asset_id,
                          candidate.subject.view_id, Jsonb(decision)))
            for name, ref in candidate.observation_refs.items():
                conn.execute("INSERT INTO decision_observations VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                             (decision["decision_id"], name, ref))
        return decision

    def get_decision(self, decision_id: str) -> dict:
        with self.catalog.connect() as conn:
            row = conn.execute("SELECT payload FROM recipe_decisions WHERE decision_id=%s", (decision_id,)).fetchone()
        if not row:
            raise ValueError("DECISION_NOT_FOUND")
        payload = dict(row["payload"])
        claimed = payload.pop("decision_id")
        if claimed != decision_id or digest(payload) != decision_id:
            raise ValueError("DECISION_DIGEST_MISMATCH")
        return {"decision_id": decision_id, **payload}

"""固定配方和观测的选择决策；不生成模型分数或替代来源、监督审核。"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from idp.domain.identity import digest
from idp.domain.models import AdapterCapabilities, Contract, Digest, TaskType, Text
from idp.execution.operators import OperatorSpec

Number = Annotated[float, Field(strict=True)]


class Subject(Contract):
    asset_id: Digest
    checksum: Digest
    view_id: Digest | None = None

    @model_validator(mode="after")
    def raw_checksum(self):
        if self.view_id is None and self.checksum != self.asset_id:
            raise ValueError("RAW_SUBJECT_CHECKSUM_MISMATCH")
        return self


class FeatureObservation(Contract):
    schema_version: Literal["feature-observation-v1"] = "feature-observation-v1"
    subject: Subject
    producer: OperatorSpec
    provenance_ref: Text
    status: Literal["ok", "unsupported", "failed"]
    metrics: dict[Text, Number | None] = Field(default_factory=dict)
    error_code: Text | None = None

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "ok" and self.error_code is not None:
            raise ValueError("SUCCESS_WITH_ERROR_CODE")
        if self.status != "ok" and (self.error_code is None or self.metrics):
            raise ValueError("FAILED_OBSERVATION_REQUIRES_CODE_AND_NO_METRICS")
        return self

    @property
    def observation_id(self) -> str:
        return digest(self.model_dump(mode="json"))


class Binding(Contract):
    name: Text
    producer: OperatorSpec
    scope: Literal["asset", "view"]
    required: bool = False


class Rule(Contract):
    rule_id: Text
    observation: Text
    metric: Text
    operator: Literal["ge", "le"]
    value: Number | None = None


class Recipe(Contract):
    schema_version: Literal["selection-recipe-v1"] = "selection-recipe-v1"
    name: Text
    version: Text
    domain: Text
    stage: Text
    task_type: TaskType
    seed: Annotated[int, Field(strict=True, ge=0)] = 42
    calibrated: bool = False
    calibration_ref: Text | None = None
    observations: tuple[Binding, ...] = ()
    rules: tuple[Rule, ...] = ()
    required_annotation_refs: tuple[Digest, ...] = ()
    required_review_refs: tuple[Digest, ...] = ()
    view_config_digest: Digest | None = None
    adapter: AdapterCapabilities | None = None

    @model_validator(mode="after")
    def coherent(self):
        names = [b.name for b in self.observations]
        if len(set(names)) != len(names) or len({r.rule_id for r in self.rules}) != len(self.rules):
            raise ValueError("DUPLICATE_BINDING_OR_RULE")
        if any(r.observation not in names for r in self.rules):
            raise ValueError("UNKNOWN_RULE_OBSERVATION")
        if self.calibrated and (not self.calibration_ref or any(r.value is None for r in self.rules)):
            raise ValueError("CALIBRATION_EVIDENCE_AND_THRESHOLDS_REQUIRED")
        if self.adapter is not None and self.task_type not in self.adapter.tasks:
            raise ValueError("RECIPE_ADAPTER_TASK_MISMATCH")
        for refs in (self.required_annotation_refs, self.required_review_refs):
            if len(set(refs)) != len(refs):
                raise ValueError("DUPLICATE_REQUIRED_REFERENCE")
        return self

    @property
    def recipe_digest(self) -> str:
        return digest(self.model_dump(mode="json"))


class SelectionInput(Contract):
    subject: Subject
    observation_refs: dict[Text, Digest] = Field(default_factory=dict)
    annotation_refs: tuple[Digest, ...] = ()
    review_refs: tuple[Digest, ...] = ()


def evaluate(recipe: Recipe, candidate: SelectionInput,
             observations: dict[str, FeatureObservation]) -> dict:
    """仅使用显式引用；从不搜索同名模型的最新分数。"""
    bindings = {b.name: b for b in recipe.observations}
    if set(candidate.observation_refs) - bindings.keys():
        raise ValueError("UNDECLARED_OBSERVATION_BINDING")
    required = {b.name for b in recipe.observations if b.required} | {r.observation for r in recipe.rules}
    evidence, missing, failures, uncalibrated = [], [], [], []
    valid = {}
    for name, binding in bindings.items():
        ref = candidate.observation_refs.get(name)
        item = observations.get(ref) if ref is not None else None
        code = None
        if item is None:
            code = "OBSERVATION_MISSING"
        elif item.observation_id != ref:
            raise ValueError("OBSERVATION_DIGEST_MISMATCH")
        elif item.producer != binding.producer:
            code = "PRODUCER_MISMATCH"
        else:
            expected = (candidate.subject if binding.scope == "view" else
                        Subject(asset_id=candidate.subject.asset_id, checksum=candidate.subject.asset_id))
            if (binding.scope == "view" and candidate.subject.view_id is None) or item.subject != expected:
                code = "OBSERVATION_SUBJECT_MISMATCH"
            elif item.status != "ok":
                code = "OBSERVATION_" + item.status.upper()
        evidence.append({"binding": name, "observation_ref": ref, "required": name in required,
                         "code": code or "OBSERVATION_MATCHED"})
        if code:
            if name in required:
                missing.append(name)
        else:
            valid[name] = item
    checks = []
    for rule in recipe.rules:
        item = valid.get(rule.observation)
        value = item.metrics.get(rule.metric) if item is not None else None
        if rule.value is None:
            code = "THRESHOLD_UNCALIBRATED"
            uncalibrated.append(rule.rule_id)
        elif value is None:
            code = "METRIC_MISSING"
            missing.append(rule.rule_id)
        elif ((rule.operator == "ge" and value < rule.value) or
              (rule.operator == "le" and value > rule.value)):
            code = "RULE_FAILED"
            failures.append(rule.rule_id)
        else:
            code = "RULE_PASSED"
        checks.append({"rule_id": rule.rule_id, "observation_ref": candidate.observation_refs.get(rule.observation),
                       "metric": rule.metric, "value": value, "operator": rule.operator,
                       "threshold": rule.value, "code": code})
    missing_annotations = sorted(set(recipe.required_annotation_refs) - set(candidate.annotation_refs))
    missing_reviews = sorted(set(recipe.required_review_refs) - set(candidate.review_refs))
    action = ("reject" if failures else "needs_calibration" if uncalibrated else
              "needs_observation" if missing else "needs_review" if missing_annotations or missing_reviews else "accept")
    payload = {"schema_version": "selection-decision-v1", "recipe_digest": recipe.recipe_digest,
               "input": candidate.model_dump(mode="json"), "decision": action,
               "evidence": evidence, "checks": checks, "missing_annotations": missing_annotations,
               "missing_reviews": missing_reviews, "calibrated": recipe.calibrated,
               "passes_calibrated_rules": recipe.calibrated and action == "accept",
               "requires_source_and_supervision_checks": True}
    return {"decision_id": digest(payload), **payload}

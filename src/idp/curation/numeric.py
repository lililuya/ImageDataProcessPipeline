import math
from typing import Literal

from pydantic import Field

from idp.domain.identity import digest
from idp.domain.models import Contract, Text


class NumericRule(Contract):
    field: Literal["width", "height", "bytes_per_pixel", "entropy_luma", "laplacian_variance",
                   "opaque_fraction", "near_black_fraction", "near_white_fraction"]
    operator: Literal["ge", "le"]
    value: float


class NumericRecipe(Contract):
    name: Text
    version: Text
    domain: Text
    calibrated: bool = False
    rules: tuple[NumericRule, ...] = Field(min_length=1)

    @property
    def recipe_digest(self) -> str:
        return digest(self.model_dump(mode="json"))


def evaluate_numeric(recipe: NumericRecipe, observation: dict) -> dict:
    if observation.get("schema_version") != "quality-v1" or "metrics" not in observation:
        raise ValueError("QUALITY_OBSERVATION_REQUIRED")
    missing, rejected = [], []
    for rule in recipe.rules:
        value = observation["metrics"].get(rule.field)
        if value is None:
            missing.append(rule.field)
            continue
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("INVALID_FEATURE_VALUE")
        if (rule.operator == "ge" and value < rule.value) or (rule.operator == "le" and value > rule.value):
            rejected.append(rule.field)
    decision = "needs_observation" if missing else "reject" if rejected else "accept"
    return {"recipe_digest": recipe.recipe_digest, "observation_digest": digest(observation),
            "domain": recipe.domain, "decision": decision, "missing_fields": missing,
            "failed_fields": rejected, "calibrated": recipe.calibrated,
            "passes_calibrated_rules": recipe.calibrated and decision == "accept",
            "requires_source_and_supervision_checks": True}

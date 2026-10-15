from typing import Literal, Protocol

from pydantic import Field

from idp.domain.identity import canonical_bytes, digest
from idp.domain.models import Contract, Digest, Text


class OperatorSpec(Contract):
    operator_id: Text
    operator_version: Text
    input_schema: Text
    output_schema: Text
    model_digest: Digest | None
    config_digest: Digest
    resource: Literal["cpu", "gpu", "api"]
    max_batch_size: int = Field(strict=True, gt=0)

    def task_key(self, input_refs: list[str]) -> str:
        if not input_refs or any(not r.strip() for r in input_refs):
            raise ValueError("INPUT_REFS_REQUIRED")
        return digest({"identity_version": "canonical-json-v1",
                       "inputs": input_refs, "operator": self.model_dump(mode="json")})


class OperatorResult(Contract):
    observations: tuple[dict, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    errors: tuple[dict, ...] = ()
    usage: dict = Field(default_factory=dict)


class Operator(Protocol):
    spec: OperatorSpec

    def run(self, input_refs: list[str]) -> OperatorResult: ...


def validate_config(config: dict) -> str:
    canonical_bytes(config)
    return digest(config)

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from idp.domain.identity import digest
from idp.domain.models import Contract, Digest, TaskSample, Text


class Caption(Contract):
    """显式导入的视图级已审描述，不代替标注模型或完整审核系统。"""

    view_id: Digest
    checksum: Digest
    text: Annotated[str, StringConstraints(min_length=1)]
    language: Text
    producer_version: Text
    provenance_ref: Text
    reviewer: Text
    review_version: Text
    review_method: Literal["view-specific-human", "synthetic-ground-truth"]
    review_reason: Text

    @model_validator(mode="after")
    def visible_text(self):
        if not self.text.strip() or "\x00" in self.text:
            raise ValueError("CAPTION_EMPTY_OR_NUL")
        return self

    @property
    def annotation_id(self) -> str:
        return digest(self.model_dump(mode="json"))


class Selection(Contract):
    name: Text
    version: Text
    description: Text
    seed: Annotated[int, Field(strict=True, ge=0)] = 42


class Member(Contract):
    sample: TaskSample
    caption: Caption
    source_ids: tuple[Digest, ...]
    split: Literal["train", "validation", "test"]
    sampling_weight: Annotated[float, Field(gt=0)] = 1.0

    @model_validator(mode="after")
    def compatible(self):
        if self.sample.task_type != "t2i":
            raise ValueError("SIDECAR_UNSUPPORTED_TASK")
        target = self.sample.images[0]
        if target.mode not in {"RGB", "L"}:
            raise ValueError("SIDECAR_UNSUPPORTED_MODE")
        if (self.caption.view_id != target.view_id or self.caption.checksum != target.checksum
                or self.sample.caption_ref != self.caption.annotation_id):
            raise ValueError("CAPTION_VIEW_OR_VERSION_MISMATCH")
        if not self.source_ids or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("UNIQUE_SOURCES_REQUIRED")
        return self


class ReleasePlan(Contract):
    schema_version: Literal["1.0"] = "1.0"
    adapter: Literal["t2i-sidecar-v1"] = "t2i-sidecar-v1"
    access_domain: Text
    selection: Selection
    augmentation: Literal["identity-v1"] = "identity-v1"
    members: tuple[Member, ...]

    @model_validator(mode="after")
    def unique_and_disjoint(self):
        if not self.members:
            raise ValueError("EMPTY_RELEASE")
        ids, splits = set(), {}
        for member in self.members:
            sample = member.sample
            if sample.sample_id in ids:
                raise ValueError("DUPLICATE_MEMBER")
            ids.add(sample.sample_id)
            image = sample.images[0]
            # 完整关联图见任务5.4；此处至少保护已知资产、同视图/输出与显式组。
            for key in (("asset", image.asset_id), ("view", image.view_id),
                        ("output", image.checksum), ("group", sample.group_id)):
                if key in splits and splits[key] != member.split:
                    raise ValueError("CROSS_SPLIT_LEAKAGE")
                splits[key] = member.split
        return self

    def frozen_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload["members"] = sorted(payload["members"], key=lambda m: m["sample"]["sample_id"])
        for member in payload["members"]:
            member["source_ids"].sort()
        return payload

"""资产、来源、视图及八类任务的不可变边界模型。"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (AwareDatetime, BaseModel, ConfigDict, Field,
                      StringConstraints, field_validator, model_validator)

from .identity import digest

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskType = Literal["image-only", "t2i", "text-rendering", "edit",
                   "multi-reference", "transparent", "style-lora", "preference"]
Role = Literal["source", "target", "reference", "mask", "chosen", "rejected"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Envelope(Contract):
    schema_version: Literal["1.0"] = "1.0"
    created_at: AwareDatetime
    producer_version: Text
    subject_ref: Text
    config_digest: Digest

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class Asset(Envelope):
    asset_id: Digest
    uri: Text
    byte_size: Annotated[int, Field(strict=True, ge=0)]
    mime: Text
    access_domain: Text


class SourceRecord(Envelope):
    asset_id: Digest
    batch_id: Text
    source_name: Text
    original_id: Text
    source_uri: Text
    acquired_at: AwareDatetime
    license_status: Literal["unknown", "approved", "withdrawn"] = "unknown"
    evidence_ref: Text | None = None

    @field_validator("acquired_at")
    @classmethod
    def acquisition_utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def evidence_required(self):
        if self.license_status == "approved" and self.evidence_ref is None:
            raise ValueError("APPROVED_SOURCE_REQUIRES_EVIDENCE")
        return self

    @property
    def source_id(self) -> str:
        return digest({"batch": self.batch_id, "source": self.source_name,
                       "original_id": self.original_id, "asset": self.asset_id})


class View(Envelope):
    asset_id: Digest
    parent_view: Digest | None = None
    input_checksum: Digest
    output_checksum: Digest
    input_width: Annotated[int, Field(strict=True, gt=0)]
    input_height: Annotated[int, Field(strict=True, gt=0)]
    crop_box: tuple[int, int, int, int]
    width: Annotated[int, Field(strict=True, gt=0)]
    height: Annotated[int, Field(strict=True, gt=0)]
    orientation: Annotated[int, Field(strict=True, ge=1, le=8)]
    interpolation: Literal["nearest", "bilinear", "bicubic", "lanczos"]
    alpha_policy: Literal["preserve", "reject", "composite"]
    background_rgb: tuple[int, int, int] | None = None
    seed: Annotated[int, Field(strict=True, ge=0)]
    operator_version: Text
    decoder_version: Text

    @model_validator(mode="after")
    def geometry(self):
        left, top, right, bottom = self.crop_box
        if not (0 <= left < right <= self.input_width and
                0 <= top < bottom <= self.input_height):
            raise ValueError("CROP_OUTSIDE_OR_EMPTY")
        if self.alpha_policy == "composite":
            if self.background_rgb is None:
                raise ValueError("COMPOSITE_REQUIRES_BACKGROUND")
        elif self.background_rgb is not None:
            raise ValueError("BACKGROUND_REQUIRES_COMPOSITE")
        if self.background_rgb and any(not 0 <= x <= 255 for x in self.background_rgb):
            raise ValueError("INVALID_BACKGROUND")
        return self

    @property
    def view_id(self) -> str:
        fields = self.model_dump(mode="json", exclude={"created_at", "subject_ref",
                                                       "output_checksum"})
        return digest(fields)


class ImageRef(Contract):
    role: Role
    ordinal: Annotated[int, Field(strict=True, ge=0)] = 0
    asset_id: Digest
    view_id: Digest
    checksum: Digest
    uri: Text
    mode: Literal["RGB", "RGBA", "L", "OTHER"]


class TextRegion(Contract):
    text: Annotated[str, StringConstraints(min_length=1)]
    language: Text
    polygon: tuple[tuple[float, float], ...]
    reading_order: Annotated[int, Field(strict=True, ge=0)]
    coordinate_system: Literal["normalized"] = "normalized"

    @model_validator(mode="after")
    def coordinates(self):
        if not self.text.strip():
            raise ValueError("VISIBLE_TEXT_REQUIRED")
        if len(self.polygon) < 3 or len(set(self.polygon)) < 3:
            raise ValueError("POLYGON_NEEDS_THREE_DISTINCT_POINTS")
        if any(not 0 <= x <= 1 or not 0 <= y <= 1 for x, y in self.polygon):
            raise ValueError("POLYGON_OUTSIDE_VIEW")
        pairs = list(zip(self.polygon, self.polygon[1:] + self.polygon[:1]))
        if abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairs)) < 1e-12:
            raise ValueError("POLYGON_HAS_ZERO_AREA")
        return self


class TaskSample(Envelope):
    sample_id: Text
    task_type: TaskType
    images: tuple[ImageRef, ...]
    group_id: Text
    caption_ref: Text | None = None
    instruction: Text | None = None
    preserve_constraints: tuple[Text, ...] = ()
    condition_strategy: Text | None = None
    render_text: tuple[TextRegion, ...] = ()
    alpha_semantics: Literal["straight", "premultiplied"] | None = None
    trigger: Text | None = None
    caption_strategy_version: Text | None = None
    chosen_condition_digest: Digest | None = None
    rejected_condition_digest: Digest | None = None
    judgment_ref: Text | None = None

    @model_validator(mode="after")
    def task_requirements(self):
        keys = [(i.role, i.ordinal) for i in self.images]
        if len(set(keys)) != len(keys):
            raise ValueError("DUPLICATE_ROLE_ORDINAL")
        by_role = {r: [i for i in self.images if i.role == r]
                   for r in ("source", "target", "reference", "mask", "chosen", "rejected")}
        for items in by_role.values():
            if [i.ordinal for i in items] != list(range(len(items))):
                raise ValueError("ROLE_ORDINALS_MUST_BE_CONTIGUOUS_AND_ORDERED")
        allowed = {
            "image-only": {"target"}, "t2i": {"target"},
            "text-rendering": {"target"}, "edit": {"source", "target", "mask"},
            "multi-reference": {"reference", "target", "mask"},
            "transparent": {"target"}, "style-lora": {"target"},
            "preference": {"reference", "chosen", "rejected"},
        }[self.task_type]
        if any(i.role not in allowed for i in self.images):
            raise ValueError("UNEXPECTED_IMAGE_ROLE")
        if self.task_type != "preference" and len(by_role["target"]) != 1:
            raise ValueError("EXACTLY_ONE_TARGET_REQUIRED")
        if len(by_role["mask"]) > 1:
            raise ValueError("AT_MOST_ONE_MASK")
        if self.task_type in {"t2i", "text-rendering", "style-lora", "transparent"}:
            if self.caption_ref is None:
                raise ValueError("CAPTION_REQUIRED")
        if self.task_type == "image-only" and self.condition_strategy is None:
            raise ValueError("CONDITION_STRATEGY_REQUIRED")
        if self.task_type == "text-rendering":
            if not self.render_text:
                raise ValueError("TEXT_REGIONS_REQUIRED")
            orders = [r.reading_order for r in self.render_text]
            if orders != list(range(len(orders))):
                raise ValueError("READING_ORDER_MUST_BE_CONTIGUOUS")
        if self.task_type == "edit":
            if len(by_role["source"]) != 1 or not self.instruction or not self.preserve_constraints:
                raise ValueError("EDIT_SOURCE_INSTRUCTION_AND_PRESERVATION_REQUIRED")
        if self.task_type == "multi-reference" and (not by_role["reference"] or not self.instruction):
            raise ValueError("REFERENCES_AND_INSTRUCTION_REQUIRED")
        if self.task_type == "transparent":
            if by_role["target"][0].mode != "RGBA" or self.alpha_semantics is None:
                raise ValueError("RGBA_AND_ALPHA_SEMANTICS_REQUIRED")
        if self.task_type == "style-lora" and (not self.trigger or not self.caption_strategy_version):
            raise ValueError("STYLE_TRIGGER_AND_STRATEGY_REQUIRED")
        if self.task_type == "preference":
            if len(by_role["chosen"]) != 1 or len(by_role["rejected"]) != 1:
                raise ValueError("PREFERENCE_PAIR_REQUIRED")
            if not self.chosen_condition_digest or not self.judgment_ref:
                raise ValueError("PREFERENCE_CONDITION_AND_JUDGMENT_REQUIRED")
            if self.chosen_condition_digest != self.rejected_condition_digest:
                raise ValueError("CONDITION_MISMATCH")
        return self

    @property
    def content_digest(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"created_at", "sample_id"}))


class AdapterCapabilities(Contract):
    adapter_id: Text
    checkpoint_digest: Digest
    tasks: tuple[TaskType, ...]
    max_references: Annotated[int, Field(strict=True, ge=0)] = 0
    supports_alpha: bool = False
    condition_strategies: tuple[Text, ...] = ()

    def check(self, sample: TaskSample) -> None:
        if sample.task_type not in self.tasks:
            raise ValueError("ADAPTER_UNSUPPORTED_TASK")
        if sum(i.role == "reference" for i in sample.images) > self.max_references:
            raise ValueError("ADAPTER_REFERENCE_LIMIT")
        if sample.task_type == "image-only" and sample.condition_strategy not in self.condition_strategies:
            raise ValueError("ADAPTER_UNSUPPORTED_CONDITION_STRATEGY")
        if any(i.mode == "RGBA" for i in sample.images) and not self.supports_alpha:
            raise ValueError("ADAPTER_UNSUPPORTED_ALPHA")

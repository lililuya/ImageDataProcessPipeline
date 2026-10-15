from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from idp.domain.identity import digest
from idp.domain.models import (AdapterCapabilities, Asset, SourceRecord,
                               TaskSample, View)
from idp.execution.operators import OperatorSpec, validate_config

D = digest("example")
ENV = dict(created_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
           producer_version="test-v1", subject_ref="test", config_digest=D)


def image(role="target", ordinal=0, **kwargs):
    return dict(role=role, ordinal=ordinal, asset_id=D, view_id=D,
                checksum=D, uri="objects/example.png", mode="RGB", **kwargs)


def sample(task="t2i", **kwargs):
    data = dict(**ENV, sample_id="sample:1", task_type=task,
                images=[image()], group_id="group:1")
    if task in {"t2i", "text-rendering", "style-lora", "transparent"}:
        data["caption_ref"] = "annotation:1"
    data.update(kwargs)
    return TaskSample.model_validate(data)


def test_asset_source_identity_and_validation():
    asset = Asset(**ENV, asset_id=D, uri="objects/1", byte_size=10,
                  mime="image/png", access_domain="pilot")
    a = SourceRecord(**ENV, asset_id=asset.asset_id, batch_id="b1",
                     source_name="s1", original_id="1", source_uri="file:a",
                     acquired_at=ENV["created_at"])
    assert a.source_id == SourceRecord(**a.model_dump()).source_id
    b = SourceRecord(**{**a.model_dump(), "source_name": "s2"})
    assert a.asset_id == b.asset_id and a.source_id != b.source_id
    for update in ({"asset_id": "sha256:abc"}, {"byte_size": -1},
                   {"byte_size": True}, {"created_at": "2026-10-15T00:00:00"},
                   {"unexpected": 1}):
        with pytest.raises(ValidationError):
            Asset(**{**asset.model_dump(), **update})
    data = asset.model_dump()
    del data["uri"]
    with pytest.raises(ValidationError):
        Asset(**data)
    with pytest.raises(ValidationError, match="REQUIRES_EVIDENCE"):
        SourceRecord(**{**a.model_dump(), "license_status": "approved"})


def test_view_identity_geometry_and_alpha():
    view = View(**ENV, asset_id=D, input_checksum=D, output_checksum=D,
                input_width=100, input_height=80, crop_box=(0, 0, 50, 50),
                width=32, height=32, orientation=1, interpolation="lanczos",
                alpha_policy="preserve", seed=42, operator_version="v1",
                decoder_version="Pillow-test")
    assert View(**{**view.model_dump(), "created_at": "2026-10-16T00:00:00Z"}).view_id == view.view_id
    assert View(**{**view.model_dump(), "seed": 43}).view_id != view.view_id
    for update in ({"crop_box": (0, 0, 101, 20)}, {"crop_box": (1, 0, 1, 20)},
                   {"alpha_policy": "composite"}, {"orientation": 9}):
        with pytest.raises(ValidationError):
            View(**{**view.model_dump(), **update})


@pytest.mark.parametrize("task,extras", [
    ("image-only", {"condition_strategy": "vlm-from-view-v1"}),
    ("t2i", {}),
    ("text-rendering", {"render_text": [{"text": "ABC", "language": "en",
        "polygon": [(0, 0), (1, 0), (1, 1)], "reading_order": 0}]}),
    ("edit", {"images": [image("source"), image()], "instruction": "Red to blue",
              "preserve_constraints": ["background"]}),
    ("multi-reference", {"images": [image("reference"), image("reference", 1), image()],
                         "instruction": "Combine references"}),
    ("transparent", {"images": [{**image(), "mode": "RGBA"}], "alpha_semantics": "straight"}),
    ("style-lora", {"trigger": "STYLE_1", "caption_strategy_version": "v1"}),
    ("preference", {"images": [image("chosen"), image("rejected")],
                    "chosen_condition_digest": D, "rejected_condition_digest": D,
                    "judgment_ref": "review:1"}),
])
def test_eight_task_contracts_roundtrip(task, extras):
    value = sample(task, **extras)
    assert TaskSample.model_validate_json(value.model_dump_json()) == value


def test_multireference_order_and_unique_roles():
    a = image("reference")
    b = {**image("reference", 1), "asset_id": digest("second")}
    valid = sample("multi-reference", images=[a, b, image()], instruction="Combine")
    swapped = sample("multi-reference", images=[{**b, "ordinal": 0}, {**a, "ordinal": 1}, image()], instruction="Combine")
    assert valid.content_digest != swapped.content_digest
    with pytest.raises(ValidationError, match="ORDINALS"):
        sample("multi-reference", images=[b, a, image()], instruction="Combine")
    with pytest.raises(ValidationError, match="DUPLICATE_ROLE"):
        sample(images=[image(), image()])


def test_preference_condition_mismatch_and_blank_caption():
    with pytest.raises(ValidationError, match="CONDITION_MISMATCH"):
        sample("preference", images=[image("chosen"), image("rejected")],
               chosen_condition_digest=D, rejected_condition_digest=digest("other"),
               judgment_ref="review:1")
    with pytest.raises(ValidationError):
        sample(caption_ref="  ")


def test_model_adapter_rejects_unsupported_conditions():
    adapter = AdapterCapabilities(adapter_id="t2i-test", checkpoint_digest=D, tasks=("t2i",))
    adapter.check(sample())
    with pytest.raises(ValueError, match="UNSUPPORTED_TASK"):
        adapter.check(sample("image-only", condition_strategy="vlm"))
    adapter = AdapterCapabilities(adapter_id="image-test", checkpoint_digest=D, tasks=("image-only",))
    with pytest.raises(ValueError, match="UNSUPPORTED_CONDITION"):
        adapter.check(sample("image-only", condition_strategy="vlm"))


def test_canonical_operator_identity():
    assert validate_config({"a": 1, "b": [2, 3]}) == validate_config({"b": [2, 3], "a": 1})
    for value in ({"bad": float("nan")}, {1: "bad"}, {"bad": {1, 2}}):
        with pytest.raises(ValueError):
            validate_config(value)
    spec = OperatorSpec(operator_id="probe", operator_version="1", input_schema="asset-v1",
                        output_schema="probe-v1", model_digest=None,
                        config_digest=D, resource="cpu", max_batch_size=8)
    key = spec.task_key([D])
    assert key == OperatorSpec(**spec.model_dump()).task_key([D])
    for update in ({"operator_version": "2"}, {"model_digest": digest("model")},
                   {"config_digest": digest("new config")}):
        assert OperatorSpec(**{**spec.model_dump(), **update}).task_key([D]) != key

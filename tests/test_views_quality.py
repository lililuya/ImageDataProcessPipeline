import io
from pathlib import Path

import pytest
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageOps

from idp.curation.numeric import NumericRecipe, evaluate_numeric
from idp.domain.identity import digest
from idp.operators.quality import quality_features
from idp.operators.views import (ImagePolicyError, ViewConfig, build_view,
                                 normalize_image, plan_view)
from idp.storage.local import LocalStore
from idp.testing.fixtures import generate


def store_image(tmp_path, image, **save_args):
    source = tmp_path / "source.png"
    image.save(source, **save_args)
    store = LocalStore(tmp_path / "objects")
    checksum, _, _ = store.put(source)
    return store, checksum, source


def test_exif_orientation_and_immutable_original(tmp_path):
    source = tmp_path / "fixtures"
    generate(source)
    original = source / "rotated.jpg"
    before = original.read_bytes()
    normalized, metadata = normalize_image(original)
    with Image.open(original) as raw:
        expected = ImageOps.exif_transpose(raw).convert("RGB")
        assert normalized.tobytes() == expected.tobytes()
    assert normalized.size == (64, 96)
    assert metadata["orientation"] == 6
    assert original.read_bytes() == before


def test_tagged_lab_to_srgb_and_invalid_icc(tmp_path):
    source = tmp_path / "lab.tiff"
    lab = Image.new("LAB", (16, 16), (140, 130, 135))
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    lab.save(source, icc_profile=profile)
    actual, metadata = normalize_image(source)
    expected = ImageCms.profileToProfile(lab, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                         ImageCms.createProfile("sRGB"), outputMode="RGB",
                                         renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    assert actual.tobytes() == expected.tobytes()
    assert metadata["color_assumption"] == "icc-to-srgb"
    broken_profile = tmp_path / "broken-profile.png"
    Image.new("RGB", (16, 16)).save(broken_profile, icc_profile=b"invalid profile")
    with pytest.raises(ImagePolicyError, match="ICC_PROFILE"):
        normalize_image(broken_profile)


@pytest.mark.parametrize("kind,reason", [("high-bit", "IMAGE_MODE"), ("animation", "ANIMATION"),
                                         ("untagged-cmyk", "UNTAGGED_COLORSPACE")])
def test_explicit_unsupported_inputs(tmp_path, kind, reason):
    path = tmp_path / "input.tiff"
    if kind == "high-bit":
        Image.new("I;16", (16, 16)).save(path)
    elif kind == "animation":
        Image.new("RGB", (16, 16), "red").save(path, format="GIF", save_all=True,
                                               append_images=[Image.new("RGB", (16, 16), "blue")])
    else:
        Image.new("CMYK", (16, 16)).save(path)
    with pytest.raises(ImagePolicyError, match=reason):
        normalize_image(path)


def test_bucket_alignment_exact_ratio_and_no_upscale():
    config = ViewConfig(target_area=512 ** 2, alignment=16)
    plan = plan_view(3500, 2400, config, digest("image"))
    assert plan["width"] % 16 == plan["height"] % 16 == 0
    assert plan["crop_width"] * plan["height"] == plan["crop_height"] * plan["width"]
    assert plan["upscale_factor"] == 1
    assert abs(plan["bucket_area"] - config.target_area) / config.target_area < .05
    with pytest.raises(ImagePolicyError, match="UPSCALE_REQUIRED"):
        plan_view(64, 64, config, digest("small"))
    upscaled = plan_view(64, 64, ViewConfig(target_area=256 ** 2, allow_upscale=True), digest("small"))
    assert upscaled["upscale_factor"] == 4


def test_random_crop_replay_and_seed_variation():
    source = digest("same image")
    config = ViewConfig(target_area=256 ** 2, aspect_ratios=((1, 1),), crop_mode="random")
    assert plan_view(2000, 500, config, source) == plan_view(2000, 500, config, source)
    boxes = {plan_view(2000, 500, ViewConfig(**{**config.model_dump(), "seed": seed}), source)["crop_box"]
             for seed in range(10)}
    assert len(boxes) > 1


def test_view_bytes_identity_and_metadata_removal(tmp_path):
    raw = Image.new("RGB", (128, 96), "white")
    ImageDraw.Draw(raw).rectangle((0, 0, 64, 48), fill="red")
    exif = Image.Exif()
    exif[270] = "synthetic metadata must not leak"
    store, asset, source = store_image(tmp_path, raw, exif=exif)
    before = source.read_bytes()
    config = ViewConfig(target_area=32 ** 2)
    first, details = build_view(store, asset, config)
    second, _ = build_view(store, asset, config)
    assert first.view_id == second.view_id and first.output_checksum == second.output_checksum
    assert source.read_bytes() == before
    assert details["supervision_status"].startswith("requires-")
    with Image.open(store.path(first.output_checksum)) as image:
        assert image.size == (32, 32)
        assert image.info.get("srgb") == 1
        assert not image.getexif() and "icc_profile" not in image.info


def test_alpha_preserve_composite_reject_and_edge_resize(tmp_path):
    raw = Image.new("RGBA", (64, 64), (0, 255, 0, 0))
    ImageDraw.Draw(raw).rectangle((16, 16, 48, 48), fill=(255, 0, 0, 128))
    store, asset, _ = store_image(tmp_path, raw)
    config = ViewConfig(target_area=64 ** 2)
    preserved, _ = build_view(store, asset, config)
    with Image.open(store.path(preserved.output_checksum)) as output:
        assert output.mode == "RGBA"
        assert output.getchannel("A").tobytes() == raw.getchannel("A").tobytes()
    with pytest.raises(ImagePolicyError, match="ALPHA_REJECTED"):
        build_view(store, asset, ViewConfig(target_area=64 ** 2, alpha_policy="reject"))
    composite, _ = build_view(store, asset, ViewConfig(target_area=64 ** 2, alpha_policy="composite", background_rgb=(0, 0, 255)))
    with Image.open(store.path(composite.output_checksum)) as output:
        assert output.mode == "RGB"
        assert output.getpixel((32, 32)) == (128, 0, 127)
    resized, _ = build_view(store, asset, ViewConfig(target_area=16 ** 2))
    with Image.open(store.path(resized.output_checksum)) as output:
        data = list(zip(*(iter(output.tobytes()),) * 4))
        assert all(g == 0 and b == 0 for r, g, b, a in data if a > 0)


def test_quality_distinguishes_zero_missing_and_blur(tmp_path):
    uniform = tmp_path / "uniform.png"
    Image.new("RGB", (128, 128), "white").save(uniform)
    values = quality_features(uniform)["metrics"]
    assert values["entropy_luma"] == 0 and values["laplacian_variance"] == 0
    transparent = tmp_path / "transparent.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(transparent)
    missing = quality_features(transparent)["metrics"]
    assert missing["laplacian_variance"] is None and missing["entropy_luma"] is None
    checker = Image.new("L", (128, 128))
    checker.putdata([255 * ((x + y) % 2) for y in range(128) for x in range(128)])
    sharp, blurred = tmp_path / "sharp.png", tmp_path / "blurred.png"
    checker.save(sharp)
    checker.filter(ImageFilter.GaussianBlur(2)).save(blurred)
    assert quality_features(sharp)["metrics"]["laplacian_variance"] > 1000
    assert quality_features(blurred)["metrics"]["laplacian_variance"] < 1000


def test_numeric_recipes_are_independent_and_uncalibrated(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (64, 64), "white").save(path)
    observation = quality_features(path)
    recipe = {"name": "strict", "version": "1", "domain": "photo",
              "rules": [{"field": "laplacian_variance", "operator": "ge", "value": 100}]}
    first = evaluate_numeric(NumericRecipe(**recipe), observation)
    second = evaluate_numeric(NumericRecipe(**{**recipe, "domain": "soft-style",
                              "rules": [{"field": "laplacian_variance", "operator": "le", "value": 100}]}), observation)
    assert first["decision"] == "reject" and second["decision"] == "accept"
    assert not second["passes_calibrated_rules"]
    assert second["requires_source_and_supervision_checks"] is True
    assert first["observation_digest"] == second["observation_digest"]
    empty = {**observation, "metrics": {**observation["metrics"], "laplacian_variance": None}}
    assert evaluate_numeric(NumericRecipe(**recipe), empty)["decision"] == "needs_observation"

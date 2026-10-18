"""可复现训练视图：方向纠正、sRGB转换、分桶、等比例裁剪及透明通道。"""

import hashlib
import io
import math
import platform
import random
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Literal
import warnings

import PIL
from PIL import Image, ImageCms, ImageOps, PngImagePlugin, features, UnidentifiedImageError
from pydantic import Field, model_validator

from idp.domain.identity import digest
from idp.domain.models import Contract, Digest, View
from idp.storage.local import LocalStore


class ImagePolicyError(ValueError):
    """消息仅为受控原因码，不包含文件路径或图片内容。"""


def image_environment() -> dict:
    return {"pillow": PIL.__version__, "lcms": features.version("littlecms2"),
            "zlib": features.version("zlib"), "jpeg": features.version("jpg"),
            "python": platform.python_version()}


class ViewConfig(Contract):
    target_area: int = Field(default=512 * 512, strict=True, ge=256, le=8192 * 8192)
    alignment: int = Field(default=16, strict=True, ge=1, le=256)
    aspect_ratios: tuple[tuple[int, int], ...] = ((1, 1), (4, 3), (3, 4), (16, 9), (9, 16))
    crop_mode: Literal["center", "random"] = "center"
    seed: int = Field(default=42, strict=True, ge=0)
    allow_upscale: bool = False
    interpolation: Literal["nearest", "bilinear", "bicubic", "lanczos"] = "lanczos"
    alpha_policy: Literal["preserve", "reject", "composite"] = "preserve"
    background_rgb: tuple[int, int, int] | None = None
    color_policy: Literal["normalize-srgb"] = "normalize-srgb"
    max_pixels: int = Field(default=100_000_000, strict=True, ge=1)

    @model_validator(mode="after")
    def check(self):
        if not self.aspect_ratios or len(self.aspect_ratios) > 64:
            raise ValueError("INVALID_ASPECT_RATIOS")
        if any(not 1 <= n <= 64 or not 1 <= d <= 64 for n, d in self.aspect_ratios):
            raise ValueError("INVALID_ASPECT_RATIOS")
        if len(set(self.aspect_ratios)) != len(self.aspect_ratios):
            raise ValueError("DUPLICATE_ASPECT_RATIOS")
        if self.target_area < self.alignment ** 2:
            raise ValueError("AREA_SMALLER_THAN_PATCH")
        if (self.alpha_policy == "composite") != (self.background_rgb is not None):
            raise ValueError("COMPOSITE_BACKGROUND_REQUIRED_EXCLUSIVELY")
        if self.background_rgb is not None and any(not 0 <= x <= 255 for x in self.background_rgb):
            raise ValueError("INVALID_BACKGROUND")
        return self


def normalize_image(path: Path, max_pixels: int = 100_000_000) -> tuple[Image.Image, dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(path) as opened:
                if opened.width * opened.height > max_pixels:
                    raise ImagePolicyError("PIXEL_LIMIT")
                if getattr(opened, "n_frames", 1) != 1:
                    raise ImagePolicyError("ANIMATION_UNSUPPORTED")
                if opened.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK", "LAB"}:
                    raise ImagePolicyError("IMAGE_MODE_UNSUPPORTED")
                orientation = opened.getexif().get(274, 1)
                if type(orientation) is not int or not 1 <= orientation <= 8:
                    raise ImagePolicyError("INVALID_ORIENTATION")
                icc = opened.info.get("icc_profile")
                original_size = opened.size
                original_mode = opened.mode
                image = ImageOps.exif_transpose(opened)
                image.load()
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise ImagePolicyError("PIXEL_LIMIT") from exc
        except (UnidentifiedImageError, EOFError, SyntaxError) as exc:
            raise ImagePolicyError("DECODE_CORRUPT_OR_UNSUPPORTED") from exc
        except OSError as exc:
            if exc.errno is not None:
                raise
            raise ImagePolicyError("DECODE_CORRUPT_OR_UNSUPPORTED") from exc
    alpha = image.convert("RGBA").getchannel("A") if (
        image.mode in {"RGBA", "LA"} or image.mode == "P" and "transparency" in image.info) else None
    if image.mode in {"RGBA", "P"}:
        base = image.convert("RGB")
    elif image.mode in {"LA", "1"}:
        base = image.convert("L")
    else:
        base = image
    if icc:
        try:
            rgb = ImageCms.profileToProfile(base, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                            ImageCms.createProfile("sRGB"), outputMode="RGB",
                                            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
        except (ImageCms.PyCMSError, OSError, TypeError, ValueError) as exc:
            raise ImagePolicyError("ICC_PROFILE_INVALID_OR_UNSUPPORTED") from exc
        assumption = "icc-to-srgb"
    else:
        if base.mode in {"CMYK", "LAB"}:
            raise ImagePolicyError("UNTAGGED_COLORSPACE_UNSUPPORTED")
        rgb = base.convert("RGB")
        assumption = "untagged-rgb-or-gray-assumed-srgb"
    if alpha is not None:
        rgb.putalpha(alpha)
    rgb.info.clear()
    return rgb, {"original_width": original_size[0], "original_height": original_size[1],
                 "original_mode": original_mode, "orientation": orientation,
                 "color_assumption": assumption,
                 "input_icc_digest": "sha256:" + hashlib.sha256(icc).hexdigest() if icc else None,
                 "coordinate_system": "exif-transposed-pixels"}


def plan_view(width: int, height: int, config: ViewConfig, input_checksum: str) -> dict:
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("INVALID_SOURCE_DIMENSIONS")
    buckets = set()
    for n, d in config.aspect_ratios:
        w = max(config.alignment, round(math.sqrt(config.target_area * n / d) / config.alignment) * config.alignment)
        h = max(config.alignment, round(math.sqrt(config.target_area * d / n) / config.alignment) * config.alignment)
        if max(w, h) > 8192:
            raise ValueError("BUCKET_DIMENSION_LIMIT")
        if abs(w * h - config.target_area) / config.target_area <= .25:
            buckets.add((w, h))
    if not buckets:
        raise ValueError("BUCKET_AREA_INCOMPATIBLE_WITH_ALIGNMENT")
    w, h = min(buckets, key=lambda b: (abs(math.log(width / height) - math.log(b[0] / b[1])),
                                       abs(b[0] * b[1] - config.target_area), b))
    divisor = math.gcd(w, h)
    unit_w, unit_h = w // divisor, h // divisor
    k = min(width // unit_w, height // unit_h)
    if k == 0:
        raise ImagePolicyError("BUCKET_RATIO_UNREPRESENTABLE")
    crop_w, crop_h = unit_w * k, unit_h * k
    scale = w / crop_w
    if not config.allow_upscale and scale > 1:
        raise ImagePolicyError("UPSCALE_REQUIRED")
    if config.crop_mode == "center":
        left, top = (width - crop_w) // 2, (height - crop_h) // 2
    else:
        rng = random.Random(digest({"seed": config.seed, "input": input_checksum, "bucket": [w, h]}))
        left, top = rng.randrange(width - crop_w + 1), rng.randrange(height - crop_h + 1)
    return {"width": w, "height": h, "crop_box": (left, top, left + crop_w, top + crop_h),
            "crop_width": crop_w, "crop_height": crop_h, "scale": scale,
            "upscale_factor": max(1.0, scale), "effective_input_pixels": crop_w * crop_h,
            "bucket_area": w * h, "target_area": config.target_area}


def view_config_payload(config: ViewConfig) -> dict:
    return {"config": config.model_dump(mode="json"), "environment": image_environment(),
            "operator_version": "training-view-v1"}


def build_view(store: LocalStore, asset_id: Digest, config: ViewConfig) -> tuple[View, dict]:
    source = store.path(asset_id)
    if store.hash_file(source) != asset_id:
        raise ImagePolicyError("INPUT_CHECKSUM_MISMATCH")
    image, provenance = normalize_image(source, config.max_pixels)
    plan = plan_view(image.width, image.height, config, asset_id)
    if image.mode == "RGBA":
        if config.alpha_policy == "reject":
            raise ImagePolicyError("ALPHA_REJECTED_BY_POLICY")
        if config.alpha_policy == "composite":
            background = Image.new("RGBA", image.size, (*config.background_rgb, 255))
            image = Image.alpha_composite(background, image).convert("RGB")
    result = image.crop(plan["crop_box"])
    if result.size != (plan["width"], plan["height"]):
        method = getattr(Image.Resampling, config.interpolation.upper())
        if result.mode == "RGBA":
            result = result.convert("RGBa").resize((plan["width"], plan["height"]), method).convert("RGBA")
        else:
            result = result.resize((plan["width"], plan["height"]), method)
    result.info.clear()
    with tempfile.TemporaryDirectory(prefix=".view-", dir=store.root) as directory:
        output = Path(directory) / "view.png"
        metadata = PngImagePlugin.PngInfo()
        metadata.add(b"sRGB", bytes([1]))
        result.save(output, format="PNG", pnginfo=metadata, icc_profile=None, exif=b"",
                    compress_level=6, optimize=False)
        checksum, _, _ = store.put(output)
    payload = view_config_payload(config)
    config_digest = digest(payload)
    view = View(created_at=datetime.now(timezone.utc), producer_version="training-view-v1",
                subject_ref=asset_id, config_digest=config_digest, asset_id=asset_id,
                input_checksum=asset_id, output_checksum=checksum, input_width=image.width,
                input_height=image.height, crop_box=plan["crop_box"], width=plan["width"],
                height=plan["height"], orientation=provenance["orientation"],
                interpolation=config.interpolation, alpha_policy=config.alpha_policy,
                background_rgb=config.background_rgb, seed=config.seed,
                operator_version="training-view-v1", decoder_version=str(payload["environment"]))
    return view, {**plan, "crop_box": list(plan["crop_box"]), **provenance, "output_mode": result.mode,
                  "crop_mode": config.crop_mode, "environment": payload["environment"],
                  "supervision_status": "requires-view-specific-annotation-or-audit"}

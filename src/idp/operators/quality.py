"""廉价独立观测，数值不等同于审美或语义正确性结论。"""

from collections import Counter
import math
from pathlib import Path

from PIL import Image

from idp.operators.views import image_environment, normalize_image


def quality_features(path: Path, analysis_edge: int = 256) -> dict:
    if type(analysis_edge) is not int or not 16 <= analysis_edge <= 1024:
        raise ValueError("INVALID_ANALYSIS_EDGE")
    image, provenance = normalize_image(path)
    original_width, original_height = image.size
    image.thumbnail((analysis_edge, analysis_edge), Image.Resampling.LANCZOS)
    luma = image.convert("L").tobytes()
    mask = image.getchannel("A").tobytes() if image.mode == "RGBA" else bytes([255]) * len(luma)
    visible = [v for v, a in zip(luma, mask) if a == 255]
    histogram = Counter(visible)
    entropy = -sum((n / len(visible)) * math.log2(n / len(visible)) for n in histogram.values()) if visible else None
    width, height = image.size
    laplacians = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = y * width + x
            indices = (i, i - 1, i + 1, i - width, i + width)
            if all(mask[j] == 255 for j in indices):
                laplacians.append(4 * luma[i] - sum(luma[j] for j in indices[1:]))
    blur = (max(0.0, sum(v * v for v in laplacians) / len(laplacians) -
                (sum(laplacians) / len(laplacians)) ** 2) if laplacians else None)
    return {"schema_version": "quality-v1", "environment": image_environment(),
            "analysis": {"width": width, "height": height, "max_edge": analysis_edge,
                         "mask_policy": "fully-opaque-only", "luma": "pillow-8bit-srgb-luma"},
            "color": provenance,
            "metrics": {"width": original_width, "height": original_height,
                        "bytes_per_pixel": path.stat().st_size / (original_width * original_height),
                        "entropy_luma": entropy, "laplacian_variance": blur,
                        "opaque_fraction": len(visible) / len(luma),
                        "near_black_fraction": sum(v <= 4 for v in visible) / len(visible) if visible else None,
                        "near_white_fraction": sum(v >= 251 for v in visible) / len(visible) if visible else None}}

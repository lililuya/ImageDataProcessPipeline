import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError


def probe(path: Path, max_pixels: int = 100_000_000, max_frames: int = 64) -> dict:
    """对每一帧实际解码；资源上限和执行失败不等同于损坏。"""
    if type(max_pixels) is not int or max_pixels < 1 or type(max_frames) is not int or max_frames < 1:
        raise ValueError("INVALID_DECODE_LIMIT")
    metadata = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                frames = getattr(image, "n_frames", 1)
                metadata = {"format": image.format, "width": width, "height": height,
                            "mode": image.mode, "bands": list(image.getbands()),
                            "frames": frames, "exif_orientation": image.getexif().get(274, 1),
                            "icc_profile_present": bool(image.info.get("icc_profile")),
                            "has_alpha": image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info,
                            "bit_depth": 16 if image.mode.startswith("I;16") else
                                32 if image.mode in {"I", "F"} else 1 if image.mode == "1" else 8}
                if frames > max_frames:
                    return {"status": "limited", "code": "FRAME_LIMIT", "metadata": metadata}
                pixel_count = 0
                for i in range(frames):
                    image.seek(i)
                    pixel_count += image.width * image.height
                    if pixel_count > max_pixels:
                        return {"status": "limited", "code": "PIXEL_LIMIT", "metadata": metadata}
                    image.load()
        return {"status": "decoded", "code": None, "metadata": metadata}
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        return {"status": "limited", "code": "PIXEL_LIMIT", "metadata": metadata}
    except (FileNotFoundError, PermissionError, MemoryError):
        return {"status": "failed", "code": "EXECUTION_FAILURE", "metadata": metadata}
    except (UnidentifiedImageError, EOFError, SyntaxError):
        return {"status": "invalid", "code": "DECODE_CORRUPT_OR_UNSUPPORTED", "metadata": metadata}
    except OSError as exc:
        # IO errno 属于执行故障；解码器不含errno的错误视为损坏或不支持。
        if exc.errno is not None:
            return {"status": "failed", "code": "IO_FAILURE", "metadata": metadata}
        return {"status": "invalid", "code": "DECODE_CORRUPT_OR_UNSUPPORTED", "metadata": metadata}

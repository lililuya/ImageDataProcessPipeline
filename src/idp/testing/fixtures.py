import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


def generate(directory: Path) -> dict:
    """仅向新目录写入，避免覆盖用户素材。"""
    directory.mkdir(parents=True, exist_ok=False)
    image = Image.new("RGB", (96, 64), "white")
    ImageDraw.Draw(image).rectangle((8, 8, 40, 55), fill="red")
    image.save(directory / "red.png")
    (directory / "red-copy.png").write_bytes((directory / "red.png").read_bytes())
    blue = Image.new("RGB", image.size, "white")
    ImageDraw.Draw(blue).rectangle((8, 8, 40, 55), fill="blue")
    blue.save(directory / "blue.png")
    rgba = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(rgba).ellipse((10, 10, 60, 55), fill=(255, 0, 0, 128))
    rgba.save(directory / "alpha.png")
    exif = Image.Exif()
    exif[274] = 6
    image.save(directory / "rotated.jpg", exif=exif)
    image.save(directory / "frames.gif", save_all=True, append_images=[blue],
               duration=100, loop=0)
    text = Image.new("RGB", (256, 64), "white")
    ImageDraw.Draw(text).text((5, 5), "SMALL TEXT 123", fill="black")
    text.save(directory / "small-text.png")
    (directory / "broken.png").write_bytes(b"synthetic invalid image\x00")
    expectations = {
        "red.png": "rgb-valid", "red-copy.png": "exact-duplicate-of-red.png",
        "blue.png": "rgb-valid-edit-target", "alpha.png": "rgba-half-transparent",
        "rotated.jpg": "exif-6-displayed-size-64x96",
        "frames.gif": "two-frames", "small-text.png": "text-SMALL TEXT 123",
        "broken.png": "decode-corrupt",
    }
    records = [{"file": name, "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                "expected": expected} for name, expected in expectations.items()]
    manifest = {"schema_version": "1.0", "provenance": "synthetic",
                "generator": "idp-fixtures-v1", "records": records,
                "edit_cases": [
                    {"source": "red.png", "target": "blue.png",
                     "instruction": "Change red to blue; preserve background and shape.", "expected": "direction-valid"},
                    {"source": "blue.png", "target": "red.png",
                     "instruction": "Change red to blue; preserve background and shape.", "expected": "direction-reversed"}]}
    (directory / "fixture-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

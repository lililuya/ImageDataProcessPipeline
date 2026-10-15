import hashlib
import json
import subprocess
import sys

import pytest
from PIL import Image, ImageOps, UnidentifiedImageError

from idp.testing.fixtures import generate


def test_fixture_expectations(tmp_path):
    path = tmp_path / "fixtures"
    manifest = generate(path)
    assert manifest["provenance"] == "synthetic"
    for row in manifest["records"]:
        assert hashlib.sha256((path / row["file"]).read_bytes()).hexdigest() == row["sha256"]
    assert (path / "red.png").read_bytes() == (path / "red-copy.png").read_bytes()
    with Image.open(path / "alpha.png") as image:
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema() == (0, 128)
    with Image.open(path / "rotated.jpg") as image:
        assert image.getexif()[274] == 6
        assert ImageOps.exif_transpose(image).size == (64, 96)
    with Image.open(path / "frames.gif") as image:
        assert image.n_frames == 2
    with pytest.raises(UnidentifiedImageError):
        Image.open(path / "broken.png")
    assert manifest["edit_cases"][1]["expected"] == "direction-reversed"
    with pytest.raises(FileExistsError):
        generate(path)


def test_installed_cli(tmp_path):
    result = subprocess.run([sys.executable, "-m", "idp.cli", "--help"],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "fixtures" in result.stdout
    result = subprocess.run([sys.executable, "-m", "idp.cli", "fixtures", str(tmp_path / "generated")],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert json.loads(result.stdout)["provenance"] == "synthetic"

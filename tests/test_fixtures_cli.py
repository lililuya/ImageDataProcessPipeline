import hashlib
import json
import os
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
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0 and "fixtures" in result.stdout
    result = subprocess.run([sys.executable, "-m", "idp.cli", "fixtures", str(tmp_path / "generated")],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert json.loads(result.stdout)["provenance"] == "synthetic"


@pytest.mark.parametrize("encoding", ["cp1252", "gbk"])
def test_cli_uses_utf8_with_legacy_redirected_streams(tmp_path, encoding):
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    help_result = subprocess.run([sys.executable, "-m", "idp.cli", "--help"],
                                 env=env, capture_output=True, text=True, encoding="utf-8")
    assert help_result.returncode == 0, help_result.stderr
    assert "图像数据框架" in help_result.stdout
    generated = tmp_path / "中文-fixtures"
    result = subprocess.run([sys.executable, "-m", "idp.cli", "fixtures", str(generated)],
                            env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["provenance"] == "synthetic"
    invalid = subprocess.run([sys.executable, "-m", "idp.cli", "无效命令"],
                             env=env, capture_output=True, text=True, encoding="utf-8")
    assert invalid.returncode == 2 and "无效命令" in invalid.stderr


def test_quality_and_recipe_cli_without_database(tmp_path):
    path = tmp_path / "fixtures"
    generate(path)
    observed = subprocess.run([sys.executable, "-m", "idp.cli", "quality", str(path / "red.png")],
                              capture_output=True, text=True, encoding="utf-8")
    assert observed.returncode == 0
    observation = tmp_path / "observation.json"
    observation.write_text(observed.stdout, encoding="utf-8")
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps({"name": "pilot", "version": "1", "domain": "synthetic",
                                  "rules": [{"field": "width", "operator": "ge", "value": 32}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "idp.cli", "quality-check", "--recipe", str(recipe),
                             "--observation", str(observation)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "accept"
    assert decision["passes_calibrated_rules"] is False

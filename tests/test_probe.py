from PIL import Image

from idp.operators.probe import probe
from idp.testing.fixtures import generate


def test_decode_formats_limits_and_failure(tmp_path):
    fixtures = tmp_path / "fixture"
    generate(fixtures)
    assert probe(fixtures / "red.png")["status"] == "decoded"
    assert probe(fixtures / "alpha.png")["metadata"]["has_alpha"] is True
    assert probe(fixtures / "rotated.jpg")["metadata"]["exif_orientation"] == 6
    assert probe(fixtures / "frames.gif")["metadata"]["frames"] == 2
    assert probe(fixtures / "frames.gif", max_frames=1)["code"] == "FRAME_LIMIT"
    assert probe(fixtures / "red.png", max_pixels=10)["code"] == "PIXEL_LIMIT"
    assert probe(fixtures / "broken.png")["status"] == "invalid"
    assert probe(fixtures / "absent.png")["status"] == "failed"
    high = fixtures / "high.tiff"
    Image.new("I;16", (8, 8)).save(high)
    assert probe(high)["metadata"]["bit_depth"] == 16


def test_io_failure_is_not_bad_image(monkeypatch, tmp_path):
    def failure(*args, **kwargs):
        raise PermissionError("synthetic permission failure")
    monkeypatch.setattr(Image, "open", failure)
    assert probe(tmp_path / "image.png")["status"] == "failed"

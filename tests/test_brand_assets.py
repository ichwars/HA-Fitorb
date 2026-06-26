from __future__ import annotations

from pathlib import Path
import struct


BRAND_DIR = Path("custom_components/fitorb/brand")


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_brand_images_exist() -> None:
    assert (BRAND_DIR / "icon.png").is_file()
    assert (BRAND_DIR / "icon@2x.png").is_file()
    assert (BRAND_DIR / "dark_icon.png").is_file()
    assert (BRAND_DIR / "dark_icon@2x.png").is_file()
    assert (BRAND_DIR / "logo.png").is_file()
    assert (BRAND_DIR / "logo@2x.png").is_file()
    assert (BRAND_DIR / "dark_logo.png").is_file()
    assert (BRAND_DIR / "dark_logo@2x.png").is_file()


def test_brand_images_have_expected_dimensions() -> None:
    assert _png_size(BRAND_DIR / "icon.png") == (256, 256)
    assert _png_size(BRAND_DIR / "icon@2x.png") == (512, 512)
    assert _png_size(BRAND_DIR / "dark_icon.png") == (256, 256)
    assert _png_size(BRAND_DIR / "dark_icon@2x.png") == (512, 512)
    assert _png_size(BRAND_DIR / "logo.png") == (512, 256)
    assert _png_size(BRAND_DIR / "logo@2x.png") == (1024, 512)
    assert _png_size(BRAND_DIR / "dark_logo.png") == (512, 256)
    assert _png_size(BRAND_DIR / "dark_logo@2x.png") == (1024, 512)

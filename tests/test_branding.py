"""Window/taskbar branding: the shipped assets, and graceful degradation.

No Tk root is created here. The GUI is covered elsewhere; what matters for
branding is that the assets are actually present in the package (a missing
one is a silent packaging bug - windows just open un-branded) and that every
loader returns None/[] rather than raising when they are not.
"""
import importlib.util
import os

import pytest
from PIL import Image

from dat.gui import branding

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def generator():
    """tools/make_branding_assets.py, which is a script rather than a module."""
    path = os.path.join(REPO_ROOT, "tools", "make_branding_assets.py")
    spec = importlib.util.spec_from_file_location("make_branding_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestShippedAssets:
    def test_every_asset_branding_looks_for_exists(self):
        for path in (branding.WORDMARK_PATH, branding.ICON_PATH, branding.ICON_ICO_PATH):
            assert os.path.isfile(path), f"missing branding asset: {path}"

    def test_the_icon_is_a_square_rgba_master(self):
        icon = Image.open(branding.ICON_PATH)
        assert icon.size == (256, 256)
        assert icon.mode == "RGBA"

    def test_the_ico_carries_the_small_sizes_windows_asks_for(self):
        # Windows picks a size from inside the file; if only 256 were stored
        # it would downscale that one image and the 16px taskbar icon would
        # be mush.
        with Image.open(branding.ICON_ICO_PATH) as ico:
            available = {size for size in ico.info["sizes"]}
        for expected in ((16, 16), (32, 32), (48, 48), (256, 256)):
            assert expected in available

    def test_the_wordmark_has_a_transparent_backdrop(self):
        wordmark = Image.open(branding.WORDMARK_PATH)
        assert wordmark.mode == "RGBA"
        # Corner transparent: otherwise it paints a coloured rectangle onto
        # the panel instead of sitting on it.
        assert wordmark.getpixel((0, 0))[3] == 0

    def test_the_wordmark_is_cropped_to_its_ink(self):
        wordmark = Image.open(branding.WORDMARK_PATH)
        assert wordmark.getbbox() == (0, 0, wordmark.width, wordmark.height)

    def test_icon_and_wordmark_are_different_assets(self):
        # They are read at different sizes and must not be conflated: the
        # taskbar needs a mark, the panel needs the name.
        assert branding.ICON_PATH != branding.WORDMARK_PATH
        assert Image.open(branding.ICON_PATH).size != Image.open(branding.WORDMARK_PATH).size

    def test_the_assets_are_declared_as_package_data(self):
        # Without this they are absent from an installed wheel, and the GUI
        # silently loses its icon only for users who pip-installed.
        with open(os.path.join(REPO_ROOT, "pyproject.toml"), encoding="utf-8") as f:
            pyproject = f.read()
        assert "assets/*.png" in pyproject
        assert "assets/*.ico" in pyproject


class TestGracefulDegradation:
    def test_a_missing_wordmark_yields_none_rather_than_raising(self, monkeypatch, tmp_path):
        monkeypatch.setattr(branding, "WORDMARK_PATH", str(tmp_path / "gone.png"))
        monkeypatch.setattr(branding, "_wordmark_cache", {})

        assert branding.wordmark_image(22) is None

    def test_a_missing_icon_yields_no_photos(self, monkeypatch, tmp_path):
        monkeypatch.setattr(branding, "ICON_PATH", str(tmp_path / "gone.png"))
        monkeypatch.setattr(branding, "_icon_photos", [])

        assert branding._load_icon_photos(None) == []

    def test_apply_survives_a_window_that_refuses_every_call(self, monkeypatch, tmp_path):
        # A Tk build (or a remote display) can reject wm calls; the GUI must
        # still open. `None` here stands in for such a window: every
        # attribute access on it raises.
        import tkinter as tk

        class HostileWindow:
            def iconphoto(self, *_args):
                raise tk.TclError("no")

            def iconbitmap(self, *_args, **_kwargs):
                raise tk.TclError("no")

        monkeypatch.setattr(branding, "_load_icon_photos", lambda _w: ["not-a-real-photo"])
        branding.apply(HostileWindow())  # must not raise

    def test_the_macos_dock_path_is_skipped_without_pyobjc(self, monkeypatch):
        # PyObjC is deliberately not a dependency, so on a stock macOS
        # install this must return False quietly rather than explode.
        monkeypatch.setattr(branding, "_dock_icon_done", False)
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def no_appkit(name, *args, **kwargs):
            if name == "AppKit":
                raise ImportError("No module named 'AppKit'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", no_appkit)
        assert branding._apply_macos_dock_icon() is False


class TestIconGeneration:
    """The margin handling is what made the icon legible at 16px."""

    def _artwork(self, canvas, mark_box, background=(1, 10, 33, 255), mark=(255, 255, 255, 255)):
        image = Image.new("RGBA", canvas, background)
        for x in range(mark_box[0], mark_box[2]):
            for y in range(mark_box[1], mark_box[3]):
                image.putpixel((x, y), mark)
        return image

    def test_ink_bbox_ignores_the_artwork_margins(self, generator):
        art = self._artwork((200, 100), (40, 30, 160, 70))
        assert generator.ink_bbox(art) == (40, 30, 160, 70)

    def test_ink_bbox_uses_alpha_when_the_artwork_is_transparent(self, generator):
        art = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        for x in range(20, 60):
            for y in range(10, 40):
                art.putpixel((x, y), (255, 255, 255, 255))
        assert generator.ink_bbox(art) == (20, 10, 60, 40)

    def test_ink_bbox_finds_a_mark_both_lighter_and_darker_than_its_ground(self, generator):
        # This logo's D is white and its T is blue: a luminance test would
        # miss one of them, so the bbox is computed by colour distance.
        art = Image.new("RGBA", (120, 60), (128, 128, 128, 255))
        for x in range(10, 30):
            for y in range(20, 40):
                art.putpixel((x, y), (255, 255, 255, 255))
        for x in range(80, 100):
            for y in range(20, 40):
                art.putpixel((x, y), (0, 0, 0, 255))
        assert generator.ink_bbox(art) == (10, 20, 100, 40)

    def test_the_mark_is_recentred_to_fill_the_tile(self, generator):
        # A mark occupying a third of its canvas must not stay a third of
        # the icon - that is the bug that made the first icon unreadable.
        art = self._artwork((300, 300), (100, 100, 200, 200))
        icon = generator.square_icon(art, 64)

        assert icon.size == (64, 64)
        bbox = generator.ink_bbox(icon)
        occupied = (bbox[2] - bbox[0]) / 64
        assert occupied > 0.7

    def test_a_prepared_square_icon_is_left_alone(self, generator):
        art = self._artwork((256, 256), (100, 100, 156, 156))
        resized = generator.square_icon(art, 64, recenter=False)

        assert resized.size == (64, 64)
        bbox = generator.ink_bbox(resized)
        # Same proportions as the source: ~22% inset each side, untouched.
        assert 20 <= bbox[0] <= 28

    def test_the_padding_matches_the_artwork_background(self, generator):
        art = self._artwork((300, 200), (120, 80, 180, 120), background=(7, 8, 9, 255))
        icon = generator.square_icon(art, 32)
        assert icon.getpixel((0, 0)) == (7, 8, 9, 255)

    def test_transparent_artwork_keeps_transparent_padding(self, generator):
        art = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        for x in range(60, 140):
            for y in range(20, 80):
                art.putpixel((x, y), (255, 255, 255, 255))
        icon = generator.square_icon(art, 32)
        assert icon.getpixel((0, 0))[3] == 0

    def test_smaller_icons_get_less_padding(self, generator):
        # At 16px, padding is pixels that could have been the mark.
        assert generator.FILL_SMALL > generator.FILL_LARGE

    def test_each_flag_rewrites_only_its_own_asset(self, generator, monkeypatch, tmp_path):
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "dat_wordmark.png").write_bytes(b"untouched")
        monkeypatch.setattr(generator, "ASSETS_DIR", str(assets))

        source = tmp_path / "icon.png"
        self._artwork((300, 300), (100, 100, 200, 200)).save(source)

        assert generator.main(["--icon", str(source)]) == 0
        assert (assets / "dat_icon.png").is_file()
        assert (assets / "dat_wordmark.png").read_bytes() == b"untouched"

    def test_running_it_with_no_flags_is_an_error(self, generator):
        with pytest.raises(SystemExit):
            generator.main([])
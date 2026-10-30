"""The per-page preview images (biwiki/ogimage.py)."""
from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from biwiki import ogimage


class OgImageTest(unittest.TestCase):
    def test_small_palette_png(self):
        data = ogimage.png("setPos", "command", "object setPos pos")
        img = Image.open(io.BytesIO(data))
        self.assertEqual((img.format, img.size, img.mode), ("PNG", (1200, 630), "P"))
        self.assertLessEqual(len(img.getcolors()), 64)
        self.assertLess(len(data), 30_000)
        self.assertNotIn(b"tIME", data, "no timestamp")

    def test_deterministic(self):
        args = ("BIS_fnc_spawnGroup", "function", "[position, side, toSpawn] call BIS_fnc_spawnGroup")
        self.assertEqual(ogimage.png(*args), ogimage.png(*args))

    def test_name_only_and_long_names(self):
        for name, kind in (("Description.ext", "topic"),
                           ("BIS_fnc_OM_moduleCheckpoint_checkDistanceFromObject", "function"),
                           ("Arma 3: Animals: Override Default Animal Behaviour Via Script", "topic")):
            self.assertEqual(Image.open(io.BytesIO(ogimage.png(name, kind))).size, (1200, 630), name)
        font, lines = ogimage.wrap_name("BIS_fnc_OM_moduleCheckpoint_checkDistanceFromObject", ogimage.MONO_B, 1040,
                                        range(104, 71, -2), range(84, 47, -2))
        self.assertEqual(len(lines), 2, "too long for one line: wrapped at a break point")

    def test_unchanged_image_is_kept(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            path = tmp / "setPos.og.png"
            self.assertTrue(ogimage.write(path, "setPos", "command", "object setPos pos"))
            self.assertFalse(ogimage.write(path, "setPos", "command", "object setPos pos"))
            self.assertTrue(ogimage.write(path, "setPos", "command", "object setPos [x, y, z]"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

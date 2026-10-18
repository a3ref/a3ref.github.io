"""End-to-end: build the mirror from the pages in tests/fixtures/raw/ and check the files agents rely on."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from biwiki.render import build

RAW = Path(__file__).parent / "fixtures" / "raw"


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out, cls.dataset = cls.tmp / "out", cls.tmp / "dataset"
        cls.dataset.mkdir()
        with redirect_stdout(StringIO()):
            build(RAW, cls.out, dataset=cls.dataset)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_page_files(self):
        for path in ("commands/setPos", "commands/a_~21~3D_b", "functions/BIS_fnc_spawnGroup", "topics/Position"):
            for ext in ("md", "json", "html"):
                self.assertTrue((self.out / f"{path}.{ext}").is_file(), f"{path}.{ext}")

    def test_markdown_page(self):
        md = (self.out / "commands" / "setPos.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("---\n"), "YAML front matter")
        self.assertIn("object setPos pos", md)
        self.assertNotIn("community.bistudio.com/wiki/Position", md, "Markdown links only to mirrored pages")

    def test_indexes(self):
        index = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        names = {e["name"] for e in index["items"]}
        self.assertTrue({"setPos", "diag_fps", "BIS_fnc_spawnGroup", "Position"} <= names)
        syntax = json.loads((self.out / "syntax.json").read_text(encoding="utf-8"))
        self.assertIn("setPos", json.dumps(syntax))
        for f in ("llms.txt", "llms-full.txt", "names.txt", "sitemap.xml", "robots.txt", "404.html", "report.json"):
            self.assertTrue((self.out / f).is_file(), f)

    def test_dataset_bundles(self):
        for f in ("commands.json", "functions.json", "topics.json", "index.json", "syntax.json", "schema.json"):
            self.assertTrue((self.dataset / f).is_file(), f)
        bundle = (self.dataset / "commands.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(bundle)["count"], 9)
        self.assertGreater(bundle.count("\n"), 7, "one record per line keeps git diffs readable")

    def test_no_crashes(self):
        report = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual((report["counts"]["error"], report["counts"]["skipped"]), (0, 0), report["problems"])


if __name__ == "__main__":
    unittest.main()

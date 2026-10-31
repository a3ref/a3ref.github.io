"""End-to-end: build the mirror from the pages in tests/fixtures/raw/ and check the files agents rely on."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from biwiki.indexnow import KEY
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

    def test_mcp_page(self):
        page = (self.out / "mcp.html").read_text(encoding="utf-8")
        self.assertEqual(page.count("<h1"), 1, "the Markdown's title is the header's h1, not a second one")
        self.assertIn('<h3 id="codex">Codex</h3>', page)
        self.assertIn('<nav class="clients" aria-label="Clients"><ul><li><a href="#claude-code">Claude Code</a></li>', page)
        self.assertIn('<p class="lede">The a3ref MCP server gives', page)
        self.assertIn('<figure class="code-file"><figcaption>~/.codex/config.toml</figcaption>', page)
        self.assertNotIn("data-title", page)
        self.assertIn('<span class="t-key">&quot;mcpServers&quot;</span>', page)
        self.assertIn('<span class="t-section">[mcp_servers.a3ref]</span>', page)
        self.assertIn('<span class="t-prog">claude</span> mcp add <span class="t-flag">--scope</span>', page)
        self.assertIn("SoftwareSourceCode", page)
        self.assertTrue((self.out / "mcp.md").is_file())
        self.assertEqual((self.out / f"{KEY}.txt").read_text(encoding="utf-8"), KEY, "IndexNow's key file")
        self.assertIn("https://a3ref.github.io/mcp.html", (self.out / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertIn("https://a3ref.github.io/mcp.md", (self.out / "llms.txt").read_text(encoding="utf-8"))
        self.assertIn('href="../mcp.html"', (self.out / "commands" / "setPos.html").read_text(encoding="utf-8"))

    def test_dataset_bundles(self):
        for f in ("commands.json", "functions.json", "topics.json", "index.json", "syntax.json", "schema.json"):
            self.assertTrue((self.dataset / f).is_file(), f)
        bundle = (self.dataset / "commands.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(bundle)["count"], 9)
        self.assertGreater(bundle.count("\n"), 7, "one record per line keeps git diffs readable")

    def test_json_records(self):
        """Format 2: empty and derivable fields are left out of command and function records, not of topics."""
        for kind in ("commands", "functions"):
            items = json.loads((self.dataset / f"{kind}.json").read_text(encoding="utf-8"))["items"]
            for r in items:
                # the change feed reads these from every bundle in the data repository's history
                self.assertLessEqual({"name", "title", "type", "url", "revid", "updated"}, set(r), r["name"])
                self.assertNotIn("categories", r)
                self.assertIsInstance(r["games"], dict)
                self.assertRegex(r["since"], r"^[a-z0-9]+ \d")
                for k, v in r.items():
                    if k not in ("updated", "description", "syntaxes", "groups"):
                        self.assertNotIn(v, (None, [], {}, False, ""), f"{r['name']}.{k}")
                for s in r["syntaxes"]:
                    self.assertNotIn("operator", s)
                    self.assertNotIn("exec", s)
                if r["name"] in ("setPos", "BIS_fnc_spawnGroup"):
                    page = json.loads((self.out / kind / f"{r['name']}.json").read_text(encoding="utf-8"))
                    self.assertEqual(page, r, "page and bundle hold the same record")
        set_pos = json.loads((self.out / "commands" / "setPos.json").read_text(encoding="utf-8"))
        self.assertEqual(set_pos["since"], "ofp 1.00")
        self.assertEqual(set_pos["games"]["arma3"], "0.50")
        pos = set_pos["syntaxes"][0]["params"][1]
        self.assertNotIn("text", pos, "pos: PositionAGL or Position2D - ... is rebuilt from name, type and description")
        self.assertNotIn("types", pos, "the names in type_expr")
        self.assertEqual(set_pos["syntaxes"][0]["left"], {"text": "object"})
        topic = json.loads((self.out / "topics" / "Position.json").read_text(encoding="utf-8"))
        self.assertIn("categories", topic, "topics keep their categories: feed.py reads them")

    def test_json_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        schema = json.loads((self.out / "schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        sub = lambda name: {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"}  # noqa: E731
        for f, d in (("commands.json", "bundle"), ("functions.json", "bundle"), ("topics.json", "bundle"),
                     ("index.json", "index"), ("syntax.json", "syntaxIndex")):
            jsonschema.validate(json.loads((self.dataset / f).read_text(encoding="utf-8")), sub(d))
        for path in ("commands/setPos", "functions/BIS_fnc_spawnGroup", "topics/Position"):
            jsonschema.validate(json.loads((self.out / f"{path}.json").read_text(encoding="utf-8")), schema)

    def test_theme_switcher(self):
        page = (self.out / "commands" / "setPos.html").read_text(encoding="utf-8")
        head, body = page.split("</head>")
        # blocking (no defer/async) in <head>, after the metas it adjusts, so the choice applies before first paint
        self.assertIn('<script src="../assets/theme.js"></script>', head)
        self.assertLess(head.index('data-scheme="dark"'), head.index("theme.js"))
        topbar = body[body.index('<header class="topbar">'):body.index("</header>")]
        # hidden without scripts; its name carries the state
        self.assertRegex(topbar, r'<button type="button" class="theme-switch" id="theme-switch" aria-label="Theme: Auto"[^>]* hidden>')
        for state in ("auto", "light", "dark"):
            self.assertIn(f'class="ti-{state}"', topbar)
        self.assertTrue((self.out / "assets" / "theme.js").is_file())

    def test_content_terms(self):
        terms = "https://community.bistudio.com/wiki/Meta:General_disclaimer"
        for path in ("index.html", "commands/setPos.html", "topics/Position.html"):
            page = (self.out / path).read_text(encoding="utf-8")
            foot = page[page.index('<footer class="footer">'):]
            self.assertIn(f'<a href="{terms}">wiki\'s terms</a> (non-commercial)', foot, path)
        page = (self.out / "commands" / "setPos.html").read_text(encoding="utf-8")
        self.assertIn(f'"license": "{terms}"', page)

    def test_seo_metadata(self):
        page = (self.out / "commands" / "setPos.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="canonical" href="https://a3ref.github.io/commands/setPos.html">\n'
                      '<meta name="color-scheme" content="light dark">', page)
        self.assertIn('"mainEntityOfPage": {"@type": "WebPage", "@id": "https://a3ref.github.io/commands/setPos.html"}', page)
        # served at every missing address, so it names none as its own
        self.assertNotIn('rel="canonical"', (self.out / "404.html").read_text(encoding="utf-8"))

    def test_preview_images(self):
        url = "https://a3ref.github.io/commands/setPos.og.png"
        page = (self.out / "commands" / "setPos.html").read_text(encoding="utf-8")
        self.assertIn(f'<meta property="og:image" content="{url}">', page)
        self.assertIn(f'<meta name="twitter:image" content="{url}">', page)
        self.assertIn('<meta property="og:image:width" content="1200">', page)
        self.assertIn('<meta property="og:image:alt" content="setPos, Arma 3 scripting command: object setPos pos">', page)
        self.assertIn(f'"image": "{url}"', page)
        for path in ("commands/setPos", "functions/BIS_fnc_spawnGroup", "topics/Position"):
            self.assertEqual((self.out / f"{path}.og.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n", path)
        home = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn('<meta property="og:image" content="https://a3ref.github.io/assets/og.png">', home)

    def test_no_crashes(self):
        report = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual((report["counts"]["error"], report["counts"]["skipped"]), (0, 0), report["problems"])


if __name__ == "__main__":
    unittest.main()

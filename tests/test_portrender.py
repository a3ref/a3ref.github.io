"""biwiki.portrender: the Renderer interface over the MediaWiki parser port (no data clone needed)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from biwiki.parse import parse_page
from biwiki.portrender import PortContext, PortRenderer, mw_timestamp
from biwiki.render import build

RAW = Path(__file__).parent / "fixtures" / "raw"

TEMPLATES = {
    "Template:hl": "<code>{{{1}}}</code>",  # titles are case-sensitive on the wiki
    "Template:Year": "{{CURRENTYEAR}}",
}
PAGE = {
    "title": "setThing",
    "revid": "42",
    "timestamp": "2021-03-04T05:06:07Z",
    "wikitext": "{{RV|type=command\n"
                "|descr= Sets the thing of {{hl|obj}}, see [[Number]]s and [[Missing page]]. Written in {{Year}}.\n"
                "|s1= obj [[setThing]] value\n"
                "|p1= obj: [[Object]] - the object\n"
                "|p2= value: [[Number]] - the new value\n"
                "|r1= [[Nothing]]\n"
                "}}",
}
PAGES = {**TEMPLATES, "setThing": PAGE["wikitext"], "Number": "x", "Object": "x", "Nothing": "x"}


def resolve(title: str, anchor: str):
    return f"../{title}.md" if title in ("Number", "Object", "Nothing", "setThing") else None


class PortRendererTest(unittest.TestCase):
    def setUp(self):
        self.ctx = PortContext(PAGES, commands=["setThing"],
                               revisions={PAGE["title"]: (PAGE["timestamp"], PAGE["revid"])})

    def test_page_through_parse_page(self):
        rec = parse_page(PAGE, "commands", self.ctx.renderer(resolve))
        self.assertEqual(rec["syntaxes"][0]["syntax"], "obj setThing value")
        # link trail and red links as on the wiki; the revision's year, not today's
        self.assertEqual(rec["description"], "Sets the thing of `obj`, see [Numbers](../Number.md) and Missing page. "
                                             "Written in 2021.")
        p1, p2 = rec["syntaxes"][0]["params"]
        # "|p1= obj: ..." is trimmed as MediaWiki trims named parameters: no preformatted first line
        self.assertEqual((p1["name"], p1["types"], p1["description"]), ("obj", ["Object"], "the object"))
        self.assertEqual((p2["name"], p2["types"]), ("value", ["Number"]))

    def test_fragments_parsed_once_per_page(self):
        for _ in range(3):  # the build's three flavours of a page
            r = self.ctx.renderer(None, hard_breaks=False)
            r.page_title = "setThing"
            self.assertEqual(r.md(" '''bold''' {{hl|x}}"), "**bold** `x`")
            self.assertEqual(r.plain(" '''bold''' {{hl|x}}"), "bold `x`")  # as Renderer: code keeps its marks
        self.assertEqual(self.ctx.parses, 1)

    def test_unknown_templates(self):
        r = self.ctx.renderer(None)
        r.page_title = "setThing"
        r.md("{{NoSuchTemplate}}")
        self.assertEqual(r.unknown, {"template:NoSuchTemplate": 1})

    def test_unclosed_pre(self):
        # "|descr= <pre>\n{{Wiki|placeholder}} {{Feature|...}}": the port, as the wiki, wraps the boxes in a <pre>
        ctx = PortContext({**PAGES, "Template:Box": '<div class="biki-messagebox feature-arma3contact"><div>i</div>'
                                                    '<div>Exclusive.</div></div>'})
        r = ctx.renderer(None)
        r.page_title = "setThing"
        self.assertEqual(r.md("<pre>\n{{Box}} "), "> [!NOTE]\n> **Arma 3 Contact:** Exclusive.")

    def test_timestamp(self):
        self.assertEqual(mw_timestamp("2021-03-04T05:06:07Z"), "20210304050607")
        self.assertIsNone(mw_timestamp(None))


class PortBuildTest(unittest.TestCase):
    def test_build(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            templates = tmp / "templates.json"
            templates.write_text(json.dumps({t: {"wikitext": w} for t, w in TEMPLATES.items()}), encoding="utf-8")
            with redirect_stdout(StringIO()):
                build(RAW, tmp / "out", renderer="port", templates=templates)
            report = json.loads((tmp / "out" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["error"], 0, report["problems"])
            md = (tmp / "out" / "commands" / "setPos.md").read_text(encoding="utf-8")
            self.assertIn("object setPos pos", md)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_default_renderer(self):
        # the port when the data clone's raw/templates.json exists (keyed by page id), else legacy with a warning
        from biwiki.render import _renderer_factory
        from biwiki.wikitext import Renderer

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            for f in RAW.glob("*.json"):
                shutil.copyfile(f, raw / f.name)
            out = StringIO()
            with redirect_stdout(out):
                self.assertIs(_renderer_factory("auto", None, raw, {}), Renderer)
            self.assertIn("warning: no templates file", out.getvalue())
            (raw / "templates.json").write_text(json.dumps(
                {str(i): {"title": t, "revid": i, "timestamp": "2026-01-01T00:00:00Z", "wikitext": w}
                 for i, (t, w) in enumerate(sorted(TEMPLATES.items()), 1)}), encoding="utf-8")
            r = _renderer_factory("auto", None, raw, {})(None)
            self.assertIsInstance(r, PortRenderer)
            r.page_title = "setThing"
            self.assertEqual(r.md("{{hl|x}}"), "`x`")
            self.assertIs(_renderer_factory("legacy", None, raw, {}), Renderer)


if __name__ == "__main__":
    unittest.main()

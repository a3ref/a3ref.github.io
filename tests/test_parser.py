"""Unit tests for the wikitext → Markdown renderer and the record parser. Run: python -m unittest"""
from __future__ import annotations

import unittest
from pathlib import Path

from biwiki import docblock
from biwiki.fetch import load_cache
from biwiki.parse import parse_page, split_param, syntax_form
from biwiki.render import page_slug, slug, summary
from biwiki.wikitext import Renderer

RAW = Path(__file__).parent / "fixtures" / "raw"


def fixture(kind: str, title: str) -> dict:
    return next(v for v in load_cache(RAW / f"{kind}.json").values() if v["title"] == title)


def command(title: str) -> dict:
    return parse_page(fixture("commands", title), "commands", Renderer(None))


class WikitextTest(unittest.TestCase):
    def md(self, text: str) -> str:
        return Renderer(None).md(text)

    def test_inline_styles(self):
        self.assertEqual(self.md("'''bold''' and ''it''"), "**bold** and *it*")

    def test_links_without_resolver_become_text(self):
        self.assertEqual(self.md("[[setPos]] and [[Position|pos]]"), "setPos and pos")

    def test_links_with_resolver(self):
        md = Renderer(lambda title, anchor: f"../commands/{title}.md").md("[[setPos]]")
        self.assertEqual(md, "[setPos](../commands/setPos.md)")

    def test_lists_code_headings_alerts(self):
        self.assertEqual(self.md("* a\n* b"), "- a\n- b")
        self.assertEqual(self.md("<sqf>player setPos [0,0,0];</sqf>"), "```sqf\nplayer setPos [0,0,0];\n```")
        self.assertEqual(self.md("== Head ==\ntext"), "### Head\n\ntext")
        self.assertEqual(self.md("{{Feature|warning|Careful}}"), "> [!WARNING]\n> Careful")


class ParamTest(unittest.TestCase):
    def test_split_param(self):
        p = split_param("unit: [[Object]] - (Optional, default objNull) the unit")
        self.assertEqual((p["name"], p["optional"], p["default"], p["description"]), ("unit", True, "objNull", "the unit"))

    def test_syntax_forms(self):
        f = syntax_form("setPos", "obj setPos pos", [{"name": "obj", "types": ["Object"]}, {"name": "pos", "types": ["Array"]}])
        self.assertEqual((f["form"], f["left"]["types"], f["right"]["types"]), ("binary", ["Object"], ["Array"]))
        self.assertEqual(syntax_form("a != b", "a != b", [])["operator"], "!=")
        self.assertEqual(syntax_form("time", "time", [])["form"], "nullary")


class PageTest(unittest.TestCase):
    def test_binary_command(self):
        rec = command("setPos")
        s = rec["syntaxes"][0]
        self.assertEqual((rec["name"], rec["type"], rec["status"]), ("setPos", "command", "ok"))
        self.assertEqual((s["syntax"], s["form"], s["returns"]["type"]), ("object setPos pos", "binary", "Nothing"))
        self.assertEqual(rec["locality"]["argument"], "global")

    def test_nullary_unary_operator(self):
        self.assertEqual(command("time")["syntaxes"][0]["form"], "nullary")
        self.assertEqual(command("alive")["syntaxes"][0]["form"], "unary")
        op = command("a != b")["syntaxes"][0]
        self.assertEqual((op["form"], op["operator"]), ("binary", "!="))

    def test_script_name_differs_from_title(self):
        self.assertEqual(command("diag fps")["name"], "diag_fps")

    def test_deprecated_names_replacement(self):
        rec = command("ctrlSetEventHandler")
        self.assertEqual(rec["status"], "deprecated")
        self.assertIn("ctrlAddEventHandler", rec["replaced_by"])

    def test_function(self):
        rec = parse_page(fixture("functions", "BIS fnc spawnGroup"), "functions", Renderer(None))
        self.assertEqual(rec["name"], "BIS_fnc_spawnGroup")
        self.assertEqual([p["name"] for p in rec["syntaxes"][0]["params"]][:2], ["position", "side"])

    def test_placeholder_function_filled_from_docblock(self):
        rec = parse_page(fixture("functions", "BIS fnc taskHandler"), "functions", Renderer(None))
        self.assertTrue(rec["filled_from_docblock"])
        self.assertTrue(rec["description"])


class DocblockTest(unittest.TestCase):
    def test_parse(self):
        d = docblock.parse("""
            Author: X

            Description:
            Does things.

            Parameter(s):
                0: OBJECT - curator
                1: ARRAY of STRINGs (Optional) - attributes. Default: []

            Returns:
            BOOL
        """)
        self.assertEqual((d["author"], d["description"]), ("X", "Does things."))
        self.assertEqual([p["types"] for p in d["params"]], [["Object"], ["Array", "String"]])
        self.assertEqual((d["params"][1]["optional"], d["params"][1]["default"]), (True, "[]"))
        self.assertEqual(d["returns"]["types"], ["Boolean"])


class SlugTest(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(slug("setPos"), "setPos")
        self.assertEqual(slug("a != b"), "a_~21~3D_b")
        self.assertEqual(slug("con"), "con_")  # reserved file name on Windows
        self.assertEqual(page_slug("Arma 3: Event Handlers", "topics"), "Event_Handlers")

    def test_summary(self):
        self.assertEqual(summary("First [link](x.md) here. Second.\n\nMore."), "First link here. Second.")


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the wikitext → Markdown renderer and the record parser. Run: python -m unittest"""
from __future__ import annotations

import unittest
from pathlib import Path

from biwiki import docblock, typeexpr
from biwiki.fetch import load_cache
from biwiki.parse import parse_page, split_param, syntax_form
from biwiki.render import page_markdown, page_slug, slug, summary, topic_group
from biwiki.report import leftover_markup, load_known, position, save_known
from biwiki.site import ANCHOR, Site, _description, _place_anchors, _toc, heading_id
from biwiki.wikitext import Renderer, wiki_anchor

RAW = Path(__file__).parent / "fixtures" / "raw"


def fixture(kind: str, title: str) -> dict:
    return next(v for v in load_cache(RAW / f"{kind}.json").values() if v["title"] == title)


def command(title: str) -> dict:
    return parse_page(fixture("commands", title), "commands", Renderer(None))


def function(title: str) -> dict:
    return parse_page(fixture("functions", title), "functions", Renderer(None))


class WikitextTest(unittest.TestCase):
    def md(self, text: str) -> str:
        return Renderer(None).md(text)

    def test_wiki_anchor(self):
        self.assertEqual(wiki_anchor("Machine_Network_ID"), "Machine Network ID")
        self.assertEqual(wiki_anchor("_this"), "_this")  # a magic variable keeps its "_"
        # MediaWiki's legacy encoding: "." for "%" of urlencode
        self.assertEqual(wiki_anchor(".23include"), "#include")
        self.assertEqual(wiki_anchor("Modes.5B.5D.3D.7B.22this.22.7D"), 'Modes[]={"this"}')
        self.assertEqual(wiki_anchor("Caf.C3.A9"), "Café")
        # not escapes: a version number, letters or digits (urlencode leaves them alone), broken UTF-8
        self.assertEqual(wiki_anchor("Arma_3_v1.22"), "Arma 3 v1.22")
        self.assertEqual(wiki_anchor("a.41b"), "a.41b")
        self.assertEqual(wiki_anchor("x.C3"), "x.C3")

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


    def test_space_led_lines_are_preformatted(self):
        md = self.md("Run it:\n AddonBuilder.exe\n AddonBuilder.exe -help\nDone.")
        self.assertEqual(md, "Run it:\n\n```\nAddonBuilder.exe\nAddonBuilder.exe -help\n```\n\nDone.")
        # not after <br> (the space is not at the start of a source line) nor before a block element
        self.assertNotIn("```", self.md("Text.<br><br> More text."))
        self.assertNotIn("```", self.md("a\n <div>b</div>"))

    def test_quotes_like_mediawiki(self):
        # odd '' and ''': one ''' is an apostrophe plus ''; what is left open closes at the end of the line
        self.assertEqual(self.md("'''DO NOT'' use it"), "'*DO NOT* use it")
        self.assertEqual(self.md("when ''layer is a [[String]]"), "when *layer is a String*")
        self.assertEqual(self.md("''a'''s type"), "*a'*s type")
        self.assertEqual(self.md("''a''<nowiki/>'s type"), "*a*'s type")  # <nowiki/> ends the run of quotes
        self.assertEqual(self.md("''Caliber<br />Rounds''"), "*Caliber\\\nRounds*")  # <br> is no line end here

    def test_line_breaks(self):
        self.assertEqual(self.md("a<br>b"), "a\\\nb")  # a hard break: a plain newline would be a space
        self.assertEqual(self.md("a<br><br>b"), "a\n\nb")
        self.assertEqual(self.md("a<br>\n\nb<br>"), "a\n\nb")  # at the end of a paragraph it shows nothing
        self.assertEqual(self.md("lowest*:<br><small>* not true</small>"), "lowest*:\\\n\\* not true")  # no list
        self.assertEqual(self.md("Options:<br>\n* one\n* two"), "Options:\n- one\n- two")  # a real list stays one
        self.assertEqual(Renderer(None, hard_breaks=False).md("a<br>b"), "a\nb")  # plain text: a newline
        self.assertEqual(self.md("see [[x]] command.<br>\n<br>\n{{Feature|informative|n}}"), "see x command.\n\n> [!NOTE]\n> n")

    def test_literal_backslashes(self):
        self.assertEqual(self.md("Copy it to P:\\\nthen \\*.pbo"), "Copy it to P:\\\\\nthen \\\\*.pbo")
        self.assertEqual(self.md("{{hl|P:\\}}"), "`P:\\`")  # code shows it as is
        self.assertEqual(self.md("{{hl|c= a = 1}}"), "`a = 1`")  # c= when the code holds "="
        self.assertEqual(self.md("x\n C:\\Arma 3\\\n"), "x\n\n```\nC:\\Arma 3\\\n```")
        self.assertEqual(self.md("{{hl|'''name''' {{=}} 1}}"), "`name = 1`")

    def test_list_marks_that_do_not_start_a_line(self):
        # template arguments inside code and table cell text after "|" continue a line on the wiki
        self.assertEqual(self.md("Always {{hl|*/*}}, then {{hl|#login}} and <code>#define X</code>"),
                         "Always `*/*`, then `#login` and `#define X`")
        self.assertEqual(self.md("a {{hl|;}} or {{hl|&nbsp;}} (space)"), "a `;` or ` ` (space)")
        self.assertEqual(self.md('{| class="wikitable"\n! Key\n|-\n| * (numpad)\n|-\n|\n* a list\n|}'),
                         "| Key |\n|---|\n| * (numpad) |\n| - a list |")

    def test_unknown_tags_are_text(self):
        self.assertEqual(self.md('{{hl|bone {{=}} "<string>"}} in <GroundContacts>'), '`bone = "<string>"` in <GroundContacts>')

    def test_unclosed_table_in_a_parameter(self):
        self.assertIn("| A | B |", self.md("Mines:\n{{{!}} class=\"wikitable\"\n! A\n! B\n{{!}}-\n{{!}} 1\n{{!}} 2"))

    def test_code_display_block(self):
        md = self.md('<code style="display: block">[[player]] setPos [0, 0, 0];<br>{{cc|done}}</code>')
        self.assertEqual(md, "```\nplayer setPos [0, 0, 0];\n// done\n```")

    def test_magic_words_and_pipe_trick(self):
        self.assertEqual(self.md("__NOTOC__\n[[raP (ArmA)|]] and [[Seattle, Washington|]]"), "raP and Seattle")

    def test_definition_line_with_colon(self):
        self.assertEqual(self.md("; Type: String\n; Description: Text."), "**Type:** String\n\n**Description:** Text.")

    def test_infobox_templates(self):
        md = self.md("{{Tool\n|AUTHOR= BI\n|COMMAND=\n tool.exe -help\n|SEEALSO= [[Other]]\n}}")
        self.assertEqual(md, "**Author:** BI\n\n**Command:**\n\n```\ntool.exe -help\n```\n\n**See also:** Other")

    def test_control_type_attribute(self):
        md = self.md("{{CT|attribute\n|name=colorText\n|type1=Array\n|value1={1,1,1,1}\n|description=Text colour.\n}}")
        self.assertIn("##### colorText", md)
        self.assertIn("**Type:** Array\n\n**Description:** Text colour.", md)
        self.assertIn("```cpp\ncolorText[] = {1,1,1,1};\n```", md)


class ParamTest(unittest.TestCase):
    def test_split_param(self):
        p = split_param("unit: [[Object]] - (Optional, default objNull) the unit")
        self.assertEqual((p["name"], p["optional"], p["default"], p["description"]), ("unit", True, "objNull", "the unit"))

    def test_optional_in_name(self):
        p = split_param("instant (Optional, default false):\n* Boolean - when true, animation is instant")
        self.assertEqual((p["name"], p["optional"], p["default"]), ("instant", True, "false"))
        p = split_param("expected (Optional, default: nil): Anything - expected type.")
        self.assertEqual((p["name"], p["optional"], p["default"]), ("expected", True, "nil"))
        p = split_param("(optional) defaultValue - anything: return this value (Default: nil)")
        self.assertEqual((p["name"], p["optional"], p["default"]), ("defaultValue", True, "nil"))

    def test_optional_of_array_elements_is_not_the_params(self):
        p = split_param("pos: Array with [a, b]\n- a: Number\n- b: Number - (Optional, default 0) offset")
        self.assertEqual((p["optional"], p["default"]), (False, None))

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

    def test_types_listed_below_the_param(self):
        shadow = next(p for p in command("drawIcon3D")["syntaxes"][0]["params"] if p["name"] == "shadow")
        self.assertEqual((shadow["type_expr"], shadow["types"]), ("Number | Boolean", ["Number", "Boolean"]))
        self.assertEqual((shadow["optional"], shadow["default"]), (True, "0"))
        lines = function("BIS fnc typeText2")["syntaxes"][0]["params"][0]
        self.assertEqual(lines["type_expr"], "Array<String> | Array<Array<String>>")
        self.assertFalse(lines["optional"], "the (Optional, ...) of an array element is not the parameter's")

    def test_type_after_dash(self):
        p = function("BIS fnc dbClassCheck")["syntaxes"][0]["params"][0]  # "databaseArray - [[Array]]: An array ..."
        self.assertEqual((p["name"], p["type"], p["type_expr"]), ("databaseArray", "Array", "Array"))
        self.assertFalse(p["description"].startswith("Array"))

    def test_type_from_name_with_optional(self):
        p = function("BIS fnc animateFlag")["syntaxes"][0]["params"][2]
        self.assertEqual((p["name"], p["optional"], p["default"], p["type_expr"]), ("instant", True, "false", "Boolean | Number"))

    def test_types_in_a_possible_type_table(self):
        for title in ("a != b", "a == b"):
            types = command(title)["syntaxes"][0]["params"][0]["types"]
            self.assertTrue({"Number", "Side", "Structured Text", "Location", "Boolean"} <= set(types), title)

    def test_param_slots_that_are_no_plain_param(self):
        raw = {"title": "BIS fnc test", "wikitext": (
            "{{RV|type=function\n|game1= arma3\n|s1= [a, b] call [[BIS_fnc_test]]\n"
            "|p1= <nowiki/>\n{{{!}} class=\"wikitable\"\n! Game\n{{!}} v1\n{{!}}}\n"
            "a - vector starting point, [[Position]] '''or''' [[Object]]\n"
            "|p2= <!-- to delete if unused -->\n}}")}
        params = parse_page(raw, "functions", Renderer(None))["syntaxes"][0]["params"]
        self.assertEqual([p["name"] for p in params], ["a"])  # the comment-only p2 is no parameter
        self.assertEqual(params[0]["types"], ["Position", "Object"])  # types after the description
        self.assertIn("| Game |", params[0]["description"])  # the table before it moves after the description

    def test_docblock_alternatives_with_the_same_name(self):
        p = function("BIS fnc getCfgDataPool")["syntaxes"][0]["params"][0]  # "_this: CFG" / "_this: ARRAY of STRINGS"
        self.assertEqual(p["type_expr"], "Config | Array<String>")

    def test_placeholder_function_filled_from_docblock(self):
        rec = parse_page(fixture("functions", "BIS fnc taskHandler"), "functions", Renderer(None))
        self.assertTrue(rec["filled_from_docblock"])
        self.assertTrue(rec["description"])
    def test_legacy_notes(self):
        # notes from before {{Note}}: raw <dl> HTML after {{RV}}, often with unclosed tags
        raw = {"title": "weapons", "wikitext": (
            "{{RV|type=command\n|game1= arma3\n|s1= [[weapons]] vehicle\n|r1= [[Array]]\n}}\n\n"
            '<dl class="command_description">\n\n<dt></dt>\n'
            '<dd class="notedate">Posted on 12:07, 20 January 2007</dd>\n'
            '<dt class="note">[[User:Bdfy|Bdfy]]</dt>\n<dd class="note">\nOnly the primary turret, see [[weaponsTurret]].\n</dd>\n\n'
            '<dt><dt>\n<dd class="notedate">Posted on 2016-12-03 - 21:35 (UTC)</dd>\n'
            '<dt class="note">[[User:Killzone_Kid|Killzone_Kid]]</dt>\n<dd class="note">\n'
            "''weapons'' skips \"Throw\".\n<sqf>player weapons;</sqf>\n"
            '<dt><dt>\n<dd class="notedate">Posted: Sep 10 2014</dd>\n<dt class="note">Unknown </dt>\n'
            '<dd class="note">No link.\n</dl>\n\n'
            "{{Note\n|user= Sa-Matra\n|timestamp= 20220828050658\n|text= A newer note.\n}}\n"
            "{{Note\n|user= Sa-Matra\n|timestamp= 20220828050658\n|text= Only the primary turret, see [[weaponsTurret]].\n}}")}
        notes = parse_page(raw, "commands", Renderer(None))["notes"]
        self.assertEqual([(n["user"], n["date"]) for n in notes], [
            ("Bdfy", "2007-01-20"), ("Killzone_Kid", "2016-12-03T21:35:00Z"), ("Unknown", "2014-09-10"),
            ("Sa-Matra", "2022-08-28T05:06:58Z")])  # page order; the note given both ways is kept once
        self.assertEqual(notes[0]["text"], "Only the primary turret, see weaponsTurret.")
        self.assertEqual(notes[1]["text"], '*weapons* skips "Throw".\n\n```sqf\nplayer weapons;\n```')
        self.assertEqual(notes[2]["text"], "No link.")
        md = page_markdown(parse_page(raw, "commands", Renderer(None)), lambda t, a: None)
        self.assertIn("**Bdfy** — 2007-01-20\n\nOnly the primary turret", md)



class TypeExprTest(unittest.TestCase):
    def test_wiki_types(self):
        cases = {
            "[[Array]] of [[Number]]s": "Array<Number>",
            "[[Array]] of [[Object]]s": "Array<Object>",
            "[[Object]] or [[Array]] of [[Object]]s": "Object | Array<Object>",
            "[[Array]] of [[Array]] of [[Number]]s": "Array<Array<Number>>",
            "[[Boolean]], [[String]] or [[Array]] of [[String]]s": "Boolean | String | Array<String>",
            "[[Array]] of [[Object]]s and/or [[Position]]s": "Array<Object | Position>",
            "[[Color|Color (RGBA)]] or [[Array]] of two [[Color|Color (RGBA)]]": "Color | Array<Color>",
            "[[Array]] format [[Position]]": "Position",
            "[[Number]] in range 0..1": "Number",
            "[[Position#PositionAGL|PositionAGL]] or [[Position#Introduction|Position2D]]": "PositionAGL | Position2D",
            "[[Object]] or array": "Object | Array",
            "unit that is inspected": None,
        }
        for text, expr in cases.items():
            self.assertEqual(typeexpr.of_wikitext(text), expr, text)

    def test_header_types(self):
        self.assertEqual(typeexpr.of_text("ARRAY of STRINGs (Optional)"), "Array<String>")
        self.assertEqual(typeexpr.of_text("scalar or BOOL"), "Number | Boolean")

    def test_names(self):
        self.assertEqual(typeexpr.names("Array<Object> | Side"), ["Array", "Object", "Side"])


class TableTest(unittest.TestCase):
    def test_row_and_column_spans(self):
        md = Renderer(None).md('{|\n! A !! B !! C\n|-\n| rowspan="2" | x || y || z\n|-\n| y2 || z2\n|-\n| colspan="3" | all\n|}')
        self.assertEqual(md.split("\n")[2:], ["| x | y | z |", "| x | y2 | z2 |", "| all |  |  |"])


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


class ReportTest(unittest.TestCase):
    def test_leftover_markup_and_where(self):
        self.assertEqual(leftover_markup("torqueCurve[] = {{0.0, 0.8}, {1.0, 0.8}} in prose"), {})
        md = "intro\nsee {{hl|x}} and `''code''`\n''dangling }}"
        found = leftover_markup(md)
        self.assertEqual(sorted(found), ["''", "{{", "}}"])  # the }} of {{hl|x}} closes its {{: only the last one
        self.assertEqual(position(md, found["{{"]), (2, 5))
        self.assertEqual(position(md, found["''"]), (3, 1))  # not the one in inline code

    def test_known_problems_keep_the_key(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "known.json"
            save_known(path, {"markup|topics/X|''": {"where": {"md": "3:1", "wiki": "7:2", "context": "''x"}}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             [{"key": "markup|topics/X|''", "md": "3:1", "wiki": "7:2", "context": "''x"}])
            self.assertEqual(load_known(path), {"markup|topics/X|''"})
            path.write_text('["markup|topics/Y|{{"]', encoding="utf-8")  # the older format: keys only
            self.assertEqual(load_known(path), {"markup|topics/Y|{{"})


class SiteHtmlTest(unittest.TestCase):
    def setUp(self):
        self.site = Site(Path("unused"), {}, {})

    def test_code_and_tables_inside_table_cells(self):
        md = ("| A | B |\n|---|---|\n"
              "| ```cpp<br>x[] = {<br>    1<br>};<br>``` | \\| P \\| D \\|<br>\\|---\\|---\\|<br>\\| t \\| one<br>two \\|<br>after |\n")
        out = self.site.html(md)
        self.assertIn('<td><pre class="code" tabindex="0"><code class="language-cpp">x[] = {\n    '
                      '<span class="t-number">1</span>\n};</code></pre></td>', out)
        self.assertIn("<td>t</td>\n<td>one<br>two</td>", out)  # the inner table is a table
        self.assertEqual(out.count('<div class="table-wrap">'), 2)  # each table wrapped once
        self.assertNotIn("\\|", out)

    def test_notes_inside_table_cells(self):
        out = self.site.html("| A | B |\n|---|---|\n| text<br>> [!NOTE]<br>> - one<br>> - two | > 0 seconds |\n")
        self.assertIn('<blockquote class="alert alert-note">', out)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<td>&gt; 0 seconds</td>", out)  # a comparison, not a note
        two = self.site.html("| A |\n|---|\n| > [!NOTE]<br>> one<br>> [!WARNING]<br>> two |\n")
        self.assertEqual(two.count("<blockquote"), 2)

    def test_links_in_code_blocks(self):
        md = Renderer(lambda t, a: f"../commands/{t}.html", code_links=True).md("x\n [[player]] setDamage 1")
        self.assertIn('<code><a href="../commands/player.html">player</a> setDamage 1', self.site.html(md))
        self.assertEqual(Renderer(lambda t, a: f"{t}.md").md("x\n [[player]] setDamage 1"), "x\n\n```\nplayer setDamage 1\n```")

    def test_anchors(self):
        # the wiki's anchors become ids, once each and never one the page has already (a heading's, the shell's)
        a, b = ANCHOR
        md = (f"## {a}x{b}_x\n\n## {a}intro{b}Intro\n\n| A |\n|---|\n| {a}b-soldier{b}**B_Soldier** |\n\n"
              f"{a}content{b}{a}b-soldier{b}{a}lone{b}\n")
        body, heads = self.site._ids(self.site.html(md))
        self.assertEqual(heads, [(2, "v-x", "_x"), (2, "intro", "Intro")])  # the marks are not part of the text
        doc = _place_anchors('<main id="content">' + body + "</main>")
        self.assertIn('<h2 id="v-x"><span id="x"></span>_x</h2>', doc)
        self.assertIn('<h2 id="intro">Intro</h2>', doc)
        self.assertIn('<td><span id="b-soldier"></span><strong>B_Soldier</strong></td>', doc)
        self.assertIn('</table></div>\n<span id="lone"></span>', doc)  # no empty paragraph
        self.assertNotIn(a, doc)
        self.assertEqual(doc.count('id="content"'), 1)
        # never inside an attribute
        self.assertEqual(_place_anchors(f'<a title="{a}t{b}x">y{a}t{b}</a>'), '<a title="x">y<span id="t"></span></a>')

    def test_nested_contents(self):
        # nested lists follow the levels; an entry with subsections gets a toggle for its sublist
        toc = _toc([(2, "a", "A &amp; B"), (3, "b", "B"), (4, "c", "C"), (2, "d", "D"), (4, "e", "E")])
        self.assertEqual(
            toc,
            '<li class="toc-2"><a href="#a">A &amp; B</a><button type="button" class="toc-fold" aria-expanded="true" '
            'aria-controls="toc--a" aria-label="A &amp; B: subsections"></button><ol id="toc--a">'
            '<li class="toc-3"><a href="#b">B</a><button type="button" class="toc-fold" aria-expanded="true" '
            'aria-controls="toc--b" aria-label="B: subsections"></button><ol id="toc--b">'
            '<li class="toc-4"><a href="#c">C</a></li></ol></li></ol></li>'
            '<li class="toc-2"><a href="#d">D</a><button type="button" class="toc-fold" aria-expanded="true" '
            'aria-controls="toc--d" aria-label="D: subsections"></button><ol id="toc--d">'
            '<li class="toc-3"><a href="#e">E</a></li></ol></li>')  # a skipped level is closed up

    def test_heading_levels_follow_nesting(self):
        # Description.ext: "== Respawn ==" then "{{ArgTitle|4|...}}" entries; siblings stay siblings and the next
        # h2 is back at the top, as in the wiki's contents
        body, heads = self.site._ids("<h3>Info</h3><h5>author</h5><h5>onLoadName</h5><h3>Respawn</h3><h5>respawn</h5>"
                                     "<h5>respawnDelay</h5><h6>deep</h6><h4>Mid</h4>")
        self.assertEqual([(lvl, t) for lvl, _, t in heads],
                         [(2, "Info"), (3, "author"), (3, "onLoadName"), (2, "Respawn"), (3, "respawn"),
                          (3, "respawnDelay"), (4, "deep"), (3, "Mid")])
        self.assertIn('<h3 id="respawndelay">respawnDelay</h3>', body)

    def test_notes_levelled_with_the_page(self):
        # playSound: a note's own "=== ... ===" heading came out as h5 under the author's h3
        body, heads = self.site._ids('<h2>Examples</h2><h3>Example 1</h3><section class="notes">'
                                     '<h2 id="community-notes">Community notes</h2><article class="note"><header>'
                                     '<h3 class="note-author">Kk</h3></header><h5>Sound</h5></article></section>')
        self.assertEqual([(lvl, i) for lvl, i, _ in heads],
                         [(2, "examples"), (3, "example-1"), (2, "community-notes"), (3, "kk"), (4, "sound")])
        self.assertIn('<h2 id="community-notes">Community notes</h2>', body)
        self.assertIn('<h3 id="kk" class="note-author">Kk</h3>', body)
        self.assertIn('<h4 id="sound">Sound</h4>', body)

    def test_arg_title_anchor_is_the_name(self):
        # {{ArgTitle|4|allowProfileGlasses|{{GVI|arma3|2.04}}}}: the wiki's anchor is #allowProfileGlasses
        md = Renderer(None, anchors=True).md("{{ArgTitle|4|allowProfileGlasses|{{GVI|arma3|2.04}}}}\ntext")
        body, heads = self.site._ids(self.site.html(md))
        self.assertEqual(heads[0][1], "allowprofileglasses-arma-3-v2-04")
        self.assertIn('<span id="allowprofileglasses"></span>', _place_anchors(body))
        self.assertNotIn(ANCHOR[0], Renderer(None).md("{{ArgTitle|4|allowProfileGlasses|{{GVI|arma3|2.04}}}}"))

    def test_legacy_renderer_anchors(self):
        r = Renderer(lambda t, a: f"{t}.html#{heading_id(a)}", anchors=True)
        self.assertEqual(r.md('<span id="B_Soldier">x</span> [[P#.23include|i]] [[P#a_b|ab]]'),
                         f"{ANCHOR[0]}b-soldier{ANCHOR[1]}x [i](P.html#include) [ab](P.html#a-b)")
        self.assertEqual(Renderer(None).md('<span id="B_Soldier">x</span>'), "x")


class TopicGroupTest(unittest.TestCase):
    def test_groups(self):
        def group(title, *categories):
            return topic_group({"title": title, "categories": list(categories)})

        self.assertEqual(group("Number", "Data Types"), "Data Types")
        self.assertEqual(group("CT LISTBOX", "Control Types"), "GUI")
        # only the broad category, or none: the title decides
        self.assertEqual(group("Arma 3: CfgVehicles WEST"), "Reference Lists")
        self.assertEqual(group("Arma 3: CfgVehicles Plane class config reference", "Arma 3: Editing"), "Configuration")
        self.assertEqual(group("Arma 3: Prof-Branch Change Log v2.22", "Arma 3: Editing"), "Change Logs")
        self.assertEqual(group("Arma 3: Play on Linux", "Arma 3"), "Game and Troubleshooting")
        self.assertEqual(group("Arma 3: Stamina", "Arma 3: Editing"), "General")


class SlugTest(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(slug("setPos"), "setPos")
        self.assertEqual(slug("a != b"), "a_~21~3D_b")
        self.assertEqual(slug("con"), "con_")  # reserved file name on Windows
        self.assertEqual(page_slug("Arma 3: Event Handlers", "topics"), "Event_Handlers")
        # both "Publisher" and "Arma 3: Publisher" are topics: the prefixed one keeps its prefix
        topics = {"Publisher", "Arma 3: Publisher"}
        self.assertEqual(page_slug("Publisher", "topics", topics), "Publisher")
        self.assertEqual(page_slug("Arma 3: Publisher", "topics", topics), "Arma_3~3A_Publisher")

    def test_summary(self):
        self.assertEqual(summary("First [link](x.md) here. Second.\n\nMore."), "First link here. Second.")

    def test_summary_skips_code_with_blank_lines(self):
        # BIS_fnc_missionHandlers: a code block with a blank line in it is not split into a prose tail
        self.assertEqual(summary("```\n#define A 1\n\n//--- Mission end type\n```"), "")
        self.assertEqual(summary("````sqf\na\n\n```\nb\n````\n\nText after."), "Text after.")

    def test_summary_is_plain_text(self):
        self.assertEqual(summary("Remainder of *a* divided by **b**, so `true` is \\*not\\* <kbd>Ctrl</kbd> &amp; _x."),
                         "Remainder of a divided by b, so true is *not* Ctrl & _x.")
        self.assertEqual(summary("Selected with <kbd><</kbd> and <kbd>></kbd>; a * b."), "Selected with < and >; a * b.")

    def test_summary_passes_over_placeholders(self):
        self.assertEqual(summary("*N/A*"), "")
        self.assertEqual(summary("/*\n\nInitialize the queue."), "Initialize the queue.")
        self.assertEqual(summary("**Author:** Bohemia Interactive\n\n**Version:** 1.3\n\n**Description:**\n\nLauncher runs the game."),
                         "Launcher runs the game.")
        self.assertEqual(summary("**Description:** : n/a\n\nIntroduced with Arma 2."), "Introduced with Arma 2.")
        self.assertEqual(summary("Arma 3 v1.68\n\nJets DLC adds catapults."), "Jets DLC adds catapults.")
        self.assertEqual(summary("Arma 3 v1.66 The class disables commands."), "The class disables commands.")


class DescriptionTest(unittest.TestCase):
    """The meta description of a page: its summary or, when that says nothing, a sentence from the record."""

    @staticmethod
    def rec(**kw) -> dict:
        rec = {"name": "setPos", "type": "command", "groups": ["Positions"],
               "syntaxes": [{"syntax": "object setPos pos", "returns": {"type": "Nothing", "type_expr": "Nothing"}}]}
        return {**rec, **kw}

    def test_composed_from_the_record(self):
        self.assertEqual(_description("", self.rec()),
                         "setPos (Arma 3 scripting command, Positions): object setPos pos. Returns Nothing.")
        rec = self.rec(syntaxes=[{"syntax": "random x", "returns": {"type": None, "type_expr": "Number"}}], name="random",
                       groups=["Math"])
        self.assertEqual(_description("", rec), "random (Arma 3 scripting command, Math): random x. Returns Number. "
                                                "From the Bohemia Interactive Community Wiki, as HTML, Markdown and JSON.")

    def test_placeholders_rejected(self):
        for junk in ("*N/A*", "N/A - see Teams", "/*", "Author: Bohemia Interactive", "REDIRECT Model Config",
                     "Arma 3 v1.68", "setPos", "SetPos."):
            self.assertTrue(_description(junk, self.rec()).startswith("setPos (Arma 3 scripting command"), junk)

    def test_function_without_syntax(self):
        rec = self.rec(name="BIN_fnc_x", type="function", groups=["Contact"], syntaxes=[{"syntax": "", "returns": None}])
        desc = _description("", rec)
        self.assertTrue(desc.startswith("BIN_fnc_x (Arma 3 function, Contact). From the Bohemia"), desc)
        self.assertLessEqual(len(desc), 160)

    def test_topic_lists_its_sections(self):
        rec = {"name": "Mission.sqm", "type": "topic", "groups": ["Mission Editing"], "syntaxes": [],
               "sections": [{"heading": None, "level": 1}, {"heading": "Header", "level": 2},
                            {"heading": "Sub", "level": 3}, {"heading": "*Mission*", "level": 2}]}
        self.assertEqual(_description("", rec),
                         "Mission.sqm (Arma 3 scripting topic, Mission Editing): Covers Header and Mission.")

    def test_summary_kept_plain_and_bounded(self):
        long = "Sets the `object` position over *surface*. " * 6
        desc = _description(long, self.rec())
        self.assertLessEqual(len(desc), 160)
        self.assertTrue(desc.startswith("Sets the object position over surface.") and desc.endswith("…"), desc)
        # a short summary gets the context and the syntax
        self.assertEqual(_description("Sets a position.", self.rec()),
                         "setPos (Arma 3 scripting command, Positions): Sets a position. Syntax: object setPos pos.")


if __name__ == "__main__":
    unittest.main()

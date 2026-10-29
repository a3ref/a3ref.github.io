# Ported from RemexHtml 3.0.2 tests/phpunit/Tokenizer/TokenizerTest.php and
# tests/phpunit/TreeBuilder/TreeBuilderTest.php (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia
# Foundation, MIT license (see biwiki/mediawiki/remex/LICENSE), and from MediaWiki 1.39.0
# tests/phpunit/unit/includes/tidy/RemexDriverTest.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the RemexDriverTest cases are copied unchanged;
# its html5lib-tests.json smoke test runs on the tree construction inputs of tests/mediawiki/html5lib-tests/.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the RemexHtml port (biwiki/mediawiki/remex/) and of tidy (biwiki/mediawiki/tidy.py).

The html5lib tests are those RemexHtml 3.0.2 runs, from the html5lib-tests revision it bundles
(tests/mediawiki/html5lib-tests/, MIT; see its README.md), with RemexHtml's skip list: tokenizer
pendingSpecChanges.test (draft changes) and unicodeCharsProblematic.test (bare surrogates), tree construction
menuitem-element.dat (a newer version of the HTML spec). Each tokenizer test runs with and without ignoreErrors, and
each tree construction test without a #script-on/#script-off section runs with scripting off and on, as in
RemexHtml. Parse error counts are not compared (RemexHtml's $testErrorCount is false).

TIDY_CASES are MediaWiki 1.39.0's RemexDriverTest::$remexTidyTestData (GPL-2.0-or-later).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

from biwiki.mediawiki.remex import HTMLData
from biwiki.mediawiki.remex.serializer import Serializer, TestFormatter
from biwiki.mediawiki.remex.tokenizer import TestTokenHandler, Tokenizer
from biwiki.mediawiki.remex.treebuilder import Dispatcher, TreeBuilder
from biwiki.mediawiki.sanitizer import armor_french_spaces, normalize_char_references
from biwiki.mediawiki.tidy import RemexDriver, tidy

HTML5LIB = Path(__file__).parent / "mediawiki" / "html5lib-tests"
TREE_CONSTRUCTION_DIRS = [HTML5LIB / "tree-construction", HTML5LIB / "remex-local"]

# TokenizerTest::$skippedFiles and TreeBuilderTest::$fileBlacklist (the fixtures leave these files out anyway)
SKIPPED_TOKENIZER_FILES = {"pendingSpecChanges.test", "unicodeCharsProblematic.test"}
SKIPPED_TREE_FILES = {"menuitem-element.dat"}

STATES = {
    "data state": Tokenizer.STATE_DATA,
    "RCDATA state": Tokenizer.STATE_RCDATA,
    "RAWTEXT state": Tokenizer.STATE_RAWTEXT,
    "PLAINTEXT state": Tokenizer.STATE_PLAINTEXT,
}


def _unescape(value: Any) -> Any:
    """Unescape "double-escaped" JSON strings -- in practise this means decoding unusual unicode characters such as
    bare surrogates."""
    if isinstance(value, list):
        return [_unescape(v) for v in value]
    if isinstance(value, dict):
        return {_unescape(k): _unescape(v) for k, v in value.items()}
    if isinstance(value, str):
        return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    return value


def _normalize_errors(tokens: list, remove: bool = False) -> list:
    """Merge adjacent character tokens and replace the parse errors by a single one at the start (or remove them)."""
    error_count = 0
    output: list = []
    last_token = None
    for token in tokens:
        if token == "ParseError":
            error_count += 1
            continue
        if last_token and last_token[0] == "Character" and token[0] == "Character":
            output[-1] = ["Character", output[-1][1] + token[1]]
        else:
            output.append(list(token))
        last_token = token
    if error_count and not remove:
        output.insert(0, "ParseError")
    return output


def tokenizer_cases():
    """TokenizerTest::provider(): (description, state, appropriate end tag, input, expected output)"""
    for path in sorted((HTML5LIB / "tokenizer").glob("*.test")):
        if path.name in SKIPPED_TOKENIZER_FILES:
            continue
        test_data = json.loads(path.read_text(encoding="utf-8"))
        for test in test_data.get("tests", []):
            states = test.get("initialStates", ["data state"])
            input_, output = test["input"], test["output"]
            if test.get("doubleEscaped"):
                input_, output = _unescape(input_), _unescape(output)
            for state in states:
                description = f"{path.name}: {test.get('description', '<no description>')}"
                if len(states) > 1:
                    description += f" ({state})"
                yield description, state, test.get("lastStartTag"), input_, output


def _read_section(text: str, pos: int, line_num: int):
    m = re.compile(r"#([a-z-]*)\n").match(text, pos)
    if not m:
        return None, pos, line_num
    section_line_num = line_num
    line_num += 1
    name = m.group(1)
    pos = m.end()
    value = ""
    is_end = False
    while not is_end and pos < len(text):
        line_start = pos
        newline = text.find("\n", pos)
        line_length = (len(text) if newline == -1 else newline) - pos
        pos += line_length
        if pos >= len(text):
            is_end = True
        elif text[pos] == "\n":
            pos += 1
            line_num += 1
        line = text[line_start:line_start + line_length]
        if name == "data":
            pass  # Double line breaks can appear in #data
        elif name == "document" and re.compile(r'\s*"').match(text, pos):
            pass  # Line breaks in #document can be escaped with quotes
        elif line == "":
            is_end = True
            break
        if re.fullmatch(r"#([a-z-]*)", line):
            pos = line_start
            line_num -= 1
            break
        if value != "":
            value += "\n"
        value += line
    return {"name": name, "value": value, "line": section_line_num, "end": is_end}, pos, line_num


def _read_tree_file(path: Path) -> list[dict]:
    """TreeBuilderTest::readFile()"""
    text = path.read_bytes().decode("utf-8")
    pos, line_num, tests = 0, 1, []
    while True:
        start_line = line_num
        section, pos, line_num = _read_section(text, pos, line_num)
        if not section:
            break
        if section["name"] != "data":
            raise ValueError(f"Invalid section at start of test: {section['name']}")
        test = {"data": section["value"], "file": f"tree-construction/{path.name}", "line": start_line}
        while True:
            section, pos, line_num = _read_section(text, pos, line_num)
            if not section:
                break
            if section["name"] == "errors":
                test["errors"] = section["value"].split("\n") if section["value"] else []
            elif section["name"] == "document":
                test["document"] = section["value"]
            elif section["name"] == "document-fragment":
                test["fragment"] = section["value"].strip()
            elif section["name"] == "script-on":
                test["scripting"] = True
            elif section["name"] == "script-off":
                test["scripting"] = False
            if section["end"]:
                break
        tests.append(test)
    return tests


def tree_construction_cases():
    """TreeBuilderTest::provider( 'serializer' )"""
    for directory in TREE_CONSTRUCTION_DIRS:
        for path in sorted(directory.glob("*.dat")):
            if path.name in SKIPPED_TREE_FILES:
                continue
            for test in _read_tree_file(path):
                if "scripting" in test:
                    yield test
                else:
                    yield dict(test, scripting=False)
                    yield dict(test, scripting=True)


# PCRE's /^/m: the start of the string and after every newline but a final one
_LINE_START = re.compile(r"\A|(?<=\n)(?!\Z)")
_ADJACENT_TEXT = re.compile(r'^([ ]*)"([^"]*)"\n\1"([^"]*)"\n', re.M)


def run_tree_construction(test: dict) -> tuple[str, str]:
    """TreeBuilderTest::runWithSerializer(): the serialized result and the expected document"""
    serializer = Serializer(TestFormatter())
    tree_builder = TreeBuilder(serializer, {"scriptingFlag": test["scripting"]})
    dispatcher = Dispatcher(tree_builder)
    tokenizer = Tokenizer(dispatcher, test["data"], {})
    tokenizer_options = {}
    if "fragment" in test:
        fragment = test["fragment"].split(" ")
        if len(fragment) > 1:
            if fragment[0] == "svg":
                ns = HTMLData.NS_SVG
            elif fragment[0] == "math":
                ns = HTMLData.NS_MATHML
            else:
                ns = HTMLData.NS_HTML
            name = fragment[1]
        else:
            ns = HTMLData.NS_HTML
            name = fragment[0]
        tokenizer_options = {"fragmentNamespace": ns, "fragmentName": name}
    tokenizer.execute(tokenizer_options)
    result = serializer.get_result()

    # Normalize adjacent text nodes
    while True:
        prev_result = result
        result = _ADJACENT_TEXT.sub(lambda m: f'{m.group(1)}"{m.group(2)}{m.group(3)}"\n', result)
        if prev_result == result:
            break

    # Format appropriately
    result = _LINE_START.sub("| ", result)
    result = result.replace("<EOL>", "\n")

    # Normalize terminating line break
    return result.rstrip("\n"), test["document"].rstrip("\n")


class TokenizerTest(unittest.TestCase):
    def _run(self, ignore_errors: bool) -> None:
        failures = []
        count = 0
        for description, state, appropriate_end_tag, input_, expected in tokenizer_cases():
            handler = TestTokenHandler()
            tokenizer = Tokenizer(handler, input_, {"ignoreErrors": True} if ignore_errors else {})
            tokenizer.execute({"state": STATES[state], "appropriateEndTag": appropriate_end_tag})
            output = _normalize_errors(handler.get_tokens(), ignore_errors)
            if output != _normalize_errors(expected, ignore_errors):
                failures.append(description)
            count += 1
        self.assertGreater(count, 6000)
        self.assertEqual([], failures[:20], f"{len(failures)} of {count} tokenizer tests fail")

    def test_default(self):
        self._run(False)

    def test_ignore_errors(self):
        self._run(True)

    def test_double_decode(self):
        for ignore_errors in (False, True):
            handler = TestTokenHandler()
            tokenizer = Tokenizer(handler, "&amp;amp;", {"ignoreErrors": ignore_errors})
            tokenizer.execute({"state": Tokenizer.STATE_DATA})
            self.assertEqual([["Character", "&amp;"]], _normalize_errors(handler.get_tokens()))

    def test_named_entity_longest_match(self):
        """Named references without a semicolon: the longest name wins; in attributes a legacy name followed by an
        alphanumeric or "=" stays literal."""
        handler = TestTokenHandler()
        Tokenizer(handler, '&notin; &notit; &amp &ampx <a b="&notit;" c="&not=" d="&not;i">',
                  {"ignoreErrors": True}).execute()
        self.assertEqual([["Character", "∉ ¬it; & &x "],
                          ["StartTag", "a", {"b": "&notit;", "c": "&not=", "d": "¬i"}]], handler.get_tokens())


class TreeBuilderTest(unittest.TestCase):
    def test_serializer(self):
        failures = []
        count = 0
        for test in tree_construction_cases():
            if "document" not in test:
                raise ValueError(f"Test lacks #document: {test['file']}:{test['line']}")
            result, expected = run_tree_construction(test)
            if result != expected:
                failures.append(f"{test['file']}:{test['line']} (scripting {test['scripting']})")
            count += 1
        self.assertGreater(count, 3000)
        self.assertEqual([], failures[:20], f"{len(failures)} of {count} tree construction tests fail")


MATHML = """<math xmlns="http://www.w3.org/1998/Math/MathML">
    <mrow>
      <mi>a</mi>
      <mo>&InvisibleTimes;</mo>
      <msup>
        <mi>x</mi>
        <mn>2</mn>
      </msup>
      <mo>+</mo>
      <mi>b</mi>
      <mo>&InvisibleTimes; </mo>
      <mi>x</mi>
      <mo>+</mo>
      <mi>c</mi>
    </mrow>
  </math>"""

TIDY_CASES = [
    ("Empty string", "", ""),
    ("Simple p-wrap", "x", "<p>x</p>"),
    ("No p-wrap of blank node", " ", " "),
    ("p-wrap terminated by div", "x<div></div>", "<p>x</p><div></div>"),
    ("p-wrap not terminated by span", "x<span></span>", "<p>x<span></span></p>"),
    ("An element is non-blank and so gets p-wrapped", "<span></span>", "<p><span></span></p>"),
    ("The blank flag is set after a block-level element", "<div></div> ", "<div></div> "),
    ("Blank detection between two block-level elements", "<div></div> <div></div>", "<div></div> <div></div>"),
    ("But p-wrapping of non-blank content works after an element", "<div></div>x", "<div></div><p>x</p>"),
    ("p-wrapping between two block-level elements", "<div></div>x<div></div>", "<div></div><p>x</p><div></div>"),
    ("p-wrap inside blockquote", "<blockquote>x</blockquote>", "<blockquote><p>x</p></blockquote>"),
    ("A comment is blank for p-wrapping purposes", "<!-- x -->", "<!-- x -->"),
    ("A comment is blank even when a p-wrap was opened by a text node", " <!-- x -->", " <!-- x -->"),
    ("A comment does not open a p-wrap", "<!-- x -->x", "<!-- x --><p>x</p>"),
    ("A comment does not close a p-wrap", "x<!-- x -->", "<p>x<!-- x --></p>"),
    ("Empty li", "<ul><li></li></ul>", '<ul><li class="mw-empty-elt"></li></ul>'),
    ("li with element", "<ul><li><span></span></li></ul>", "<ul><li><span></span></li></ul>"),
    ("li with text", "<ul><li>x</li></ul>", "<ul><li>x</li></ul>"),
    ("Empty tr", "<table><tbody><tr></tr></tbody></table>",
     '<table><tbody><tr class="mw-empty-elt"></tr></tbody></table>'),
    ("Empty p", "<p>\n</p>", '<p class="mw-empty-elt">\n</p>'),
    ("No p-wrapping of an inline element which contains a block element (T150317)",
     "<small><div>x</div></small>", "<small><div>x</div></small>"),
    ("p-wrapping of an inline element which contains an inline element",
     "<small><b>x</b></small>", "<p><small><b>x</b></small></p>"),
    ("p-wrapping is enabled in a blockquote in an inline element",
     "<small><blockquote>x</blockquote></small>", "<small><blockquote><p>x</p></blockquote></small>"),
    ("All bare text should be p-wrapped even when surrounded by block tags",
     "<small><blockquote>x</blockquote></small>y<div></div>z",
     "<small><blockquote><p>x</p></blockquote></small><p>y</p><div></div><p>z</p>"),
    ("Split tag stack 1", "<small>x<div>y</div>z</small>",
     "<p><small>x</small></p><small><div>y</div></small><p><small>z</small></p>"),
    ("Split tag stack 2", "<small><div>y</div>z</small>", "<small><div>y</div></small><p><small>z</small></p>"),
    ("Split tag stack 3", "<small>x<div>y</div></small>", "<p><small>x</small></p><small><div>y</div></small>"),
    ("Split tag stack 4 (modified to use splittable tag)", "a<code>b<i>c<div>d</div></i>e</code>",
     "<p>a<code>b<i>c</i></code></p><code><i><div>d</div></i></code><p><code>e</code></p>"),
    ("Split tag stack regression check 1", "x<span><div>y</div></span>", "<p>x</p><span><div>y</div></span>"),
    ("Split tag stack regression check 2 (modified to use splittable tag)", "a<code><i><div>d</div></i>e</code>",
     "<p>a</p><code><i><div>d</div></i></code><p><code>e</code></p>"),
    # Simple tests from pwrap.js
    ("Simple pwrap test 1", "a", "<p>a</p>"),
    ("<span> is not a splittable tag", "<span>x<div>a</div>y</span> <span>x<div></div>y</span>",
     "<span>x<div>a</div>y</span> <span>x<div></div>y</span>"),
    ("<span> is not a splittable tag, but gets p-wrapped in simple wrapping scenarios", "<span>a</span>",
     "<p><span>a</span></p>"),
    ("Simple pwrap test 3", "x <div>a</div> <div>b</div> y", "<p>x </p><div>a</div> <div>b</div><p> y</p>"),
    ("Simple pwrap test 4", "x<!--c--> <div>a</div> <div>b</div> <!--c-->y",
     "<p>x<!--c--> </p><div>a</div> <div>b</div> <!--c--><p>y</p>"),
    # Complex tests from pwrap.js
    ("Complex pwrap test 1", "<i>x<div>a</div>y</i>", "<p><i>x</i></p><i><div>a</div></i><p><i>y</i></p>"),
    ("Complex pwrap test 2", "a<small>b</small><i>c<div>d</div>e</i>f",
     "<p>a<small>b</small><i>c</i></p><i><div>d</div></i><p><i>e</i>f</p>"),
    ("Complex pwrap test 3", "a<small>b<i>c<div>d</div></i>e</small>",
     "<p>a<small>b<i>c</i></small></p><small><i><div>d</div></i></small><p><small>e</small></p>"),
    ("Complex pwrap test 4", "x<small><div>y</div></small>", "<p>x</p><small><div>y</div></small>"),
    ("Complex pwrap test 5", "a<small><i><div>d</div></i>e</small>",
     "<p>a</p><small><i><div>d</div></i></small><p><small>e</small></p>"),
    ("Complex pwrap test 6", "<i>a<div>b</div>c<b>d<div>e</div>f</b>g</i>",
     "<p><i>a</i></p><i><div>b</div></i><p><i>c<b>d</b></i></p><i><b><div>e</div></b></i><p><i><b>f</b>g</i></p>"),
    # (MediaWiki's "Complex pwrap test 7" is commented out: FIXME the second <b> causes a stack split which clones
    # the <i> even though no <p> is actually generated)
    # New local tests
    ("Blank text node after block end", "<small>x<div>y</div> <b>z</b></small>",
     "<p><small>x</small></p><small><div>y</div></small><p><small> <b>z</b></small></p>"),
    ("Text node fostering (FIXME: wrap missing)", "<table>x</table>", "x<table></table>"),
    ("Blockquote fostering", "<table><blockquote>x</blockquote></table>",
     "<blockquote><p>x</p></blockquote><table></table>"),
    ("Block element fostering", "<table><div>x", "<div>x</div><table></table>"),
    ("Formatting element fostering (FIXME: wrap missing)", "<table><b>x", "<b>x</b><table></table>"),
    ("AAA clone of p-wrapped element (FIXME: empty b)", "<b>x<p>y</b>z</p>",
     "<p><b>x</b></p><b></b><p><b>y</b>z</p>"),
    ("AAA with fostering (FIXME: wrap missing)", "<table><b>1<p>2</b>3</p>",
     "<b>1</b><p><b>2</b>3</p><table></table>"),
    ("AAA causes reparent of p-wrapped text node (T178632)", "<i><blockquote>x</i></blockquote>",
     "<i></i><blockquote><p><i>x</i></p></blockquote>"),
    ("p-wrap ended by reparenting (T200827)", "<i><blockquote><p></i>",
     "<i></i><blockquote><p><i></i></p><p><i></i></p></blockquote>"),
    ("style tag isn't p-wrapped (T186965)", "<style>/* ... */</style>", "<style>/* ... */</style>"),
    ("link tag isn't p-wrapped (T186965)", '<link rel="foo" href="bar" />', '<link rel="foo" href="bar" />'),
    ("style tag doesn't split p-wrapping (T208901)", "foo <style>/* ... */</style> bar",
     "<p>foo <style>/* ... */</style> bar</p>"),
    ("link tag doesn't split p-wrapping (T208901)", 'foo <link rel="foo" href="bar" /> bar',
     '<p>foo <link rel="foo" href="bar" /> bar</p>'),
    # From the old TidyTest class
    ("<mw:editsection> should survive tidy", '<mw:editsection page="foo" section="bar">foo</mw:editsection>',
     '<mw:editsection page="foo" section="bar">foo</mw:editsection>'),
    ("<editsection> should survive tidy", '<editsection page="foo" section="bar">foo</editsection>',
     '<editsection page="foo" section="bar">foo</editsection>'),
    ("<mw:toc> should survive tidy", "<mw:toc>foo</mw:toc>", "<mw:toc>foo</mw:toc>"),
    ("<link> should survive tidy", '<link foo="bar"/>foo', '<link foo="bar" /><p>foo</p>'),
    ("<meta> should survive tidy", '<meta foo="bar"/>foo', '<meta foo="bar" /><p>foo</p>'),
]


class RemexDriverTest(unittest.TestCase):
    @staticmethod
    def _driver() -> RemexDriver:
        # As RemexDriverTest: $wgTidyConfig = [], $wgParserEnableLegacyMediaDOM = false
        return RemexDriver({}, enable_legacy_media_dom=False)

    def test_tidy(self):
        test_mathml = normalize_char_references(MATHML)
        cases = TIDY_CASES + [("<math> should survive tidy", test_mathml, test_mathml)]
        driver = self._driver()
        for desc, input_, expected in cases:
            with self.subTest(desc):
                self.assertEqual(expected, driver.tidy(input_))

    def test_html5lib(self):
        """This is a quick and dirty test to make sure none of the html5lib tests generate exceptions. We don't
        really know what the expected output is. (MediaWiki runs it on html5lib-tests.json, the tree construction
        tests of its own html5lib-tests copy; here the inputs of tests/mediawiki/html5lib-tests/ are used.)"""
        driver = self._driver()
        for directory in TREE_CONSTRUCTION_DIRS:
            for path in sorted(directory.glob("*.dat")):
                for test in _read_tree_file(path):
                    with self.subTest(f"{path.name}:{test['line']}"):
                        self.assertIsInstance(driver.tidy(test["data"]), str)
                        self.assertIsInstance(tidy(test["data"]), str)

    def test_default_configuration(self):
        """tidy() is RemexDriver with MediaWiki 1.39's defaults: p-wrapping on, the plain TreeBuilder (legacy
        media DOM), so formatting elements are reconstructed in file figures too."""
        figure = '<figure typeof="mw:File"><p><b>x</p>y</figure>'
        self.assertEqual('<figure typeof="mw:File"><p><b>x</b></p><b>y</b></figure>', tidy(figure))
        # RemexCompatBuilder ($wgParserEnableLegacyMediaDOM = false) does not reconstruct them there
        self.assertEqual('<figure typeof="mw:File"><p><b>x</b></p>y</figure>', self._driver().tidy(figure))
        self.assertEqual("x", RemexDriver({"pwrap": False}).tidy("x"))

    def test_text_processor(self):
        """The text processor runs on text nodes, not on attributes or the contents of raw text elements (and
        <style> stays in the paragraph, as a metadata element)."""
        self.assertEqual('<p>a&#160;: b <span title="c : d">e&#160;!</span><style>f : g</style></p>',
                         tidy('a : b <span title="c : d">e !</span><style>f : g</style>', armor_french_spaces))


if __name__ == "__main__":
    unittest.main()

# Tests of biwiki/mediawiki/parser_preprocess.py, the port of the template half of MediaWiki 1.39's
# includes/parser/Parser.php and includes/parser/CoreTagHooks.php (https://www.mediawiki.org/),
# (C) MediaWiki contributors. Expected outputs follow MediaWiki's behaviour (tests/parser/parserTests.txt where it
# has a case).
# Written by a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Templates, arguments, parser functions and tag hooks of the preprocessing mixin, on a small Parser stand-in
(the real Parser's later stages are not needed here)."""
from __future__ import annotations

import unittest

from biwiki.mediawiki.config import TEST
from biwiki.mediawiki.magicword import MagicWordFactory
from biwiki.mediawiki.parser import Parser, ParserOutput
from biwiki.mediawiki.parser_preprocess import (OT_HTML, OT_PREPROCESS, OT_WIKI, SFH_NO_HASH, SFH_OBJECT_ARGS,
                                                PreprocessingMixin, extract_tags_and_params, normalize_subpage_link,
                                                strip_outer_paragraph, wf_escape_wiki_text)
from biwiki.mediawiki.site import test_site
from biwiki.mediawiki.stripstate import MARKER_PREFIX, MARKER_SUFFIX, StripState
from biwiki.mediawiki.title import Title

PAGES = {
    "Template:Foo": "bar",
    "Template:Args": "{{{1}}}-{{{name}}}-{{{2|default}}}",
    "Template:Redirect": "#REDIRECT [[Template:Foo]]",
    "Template:Loop1": "{{loop2}}",
    "Template:Loop2": "{{loop1}}",
    "Template:List": "* item",
    "Template:Wiki": "''a'' [[b]]",
    "Template:Include": "a<noinclude>b</noinclude><includeonly>c</includeonly>",
    "Template:=": "=",
    "Template:Equals": "x",
    "Template:Nested": "<{{Nested}}>",
    "Template:Big": "x" * 600,
    "Main": "main page",
    "Parser test/sub": "subpage",
}


class StandIn(PreprocessingMixin):
    """What PreprocessingMixin needs of Parser: pages, config, magic words, title, strip state, output and the two
    parse stages (here: only the preprocessing of internalParse(), and unstripping)."""

    def __init__(self, pages=None, config=TEST, title="Parser test", magic_words=None, subpages=False,
                 output_type=OT_HTML):
        self.pages = PAGES if pages is None else pages
        self.config = config
        self.magic_words = magic_words or MagicWordFactory()
        self.site = test_site(subpages, config)
        self.title = title
        self.strip_state = StripState(self)
        self.output = ParserOutput()
        self._init_preprocessing(output_type)

    def internal_parse(self, text: str, is_main: bool = True, frame=None) -> str:
        return self.replace_variables_for_internal_parse(text, frame)

    def internal_parse_half_parsed(self, text: str, is_main: bool = True, linestart: bool = True) -> str:
        return self.strip_state.unstrip_both(text)

    def expand(self, text: str) -> str:
        return self.strip_state.unstrip_both(self.replace_variables(text))


class TemplateTest(unittest.TestCase):
    def test_transclusion(self):
        p = StandIn()
        self.assertEqual("bar", p.expand("{{Foo}}"))
        self.assertEqual("bar", p.expand("{{ foo }}"))
        self.assertEqual("bar", p.expand("{{Template:Foo}}"))
        self.assertEqual("main page", p.expand("{{:Main}}"))
        self.assertEqual("[[:Template:Missing]]", p.expand("{{Missing}}"))
        self.assertEqual("{{wikipedia:Foo}}", p.expand("{{wikipedia:Foo}}"))  # interwiki, not transcludable
        self.assertEqual(["Template:Foo", "Main", "Template:Missing"], p.output.templates)

    def test_arguments(self):
        p = StandIn()
        self.assertEqual("a-b-default", p.expand("{{Args|a|name= b }}"))
        self.assertEqual(" a -{{{name}}}-c", p.expand("{{Args| a |c}}"))
        self.assertEqual("{{{1}}} x", p.expand("{{{1}}} {{{1|x}}}"))

    def test_inclusion_tags(self):
        self.assertEqual("ac", StandIn().expand("{{Include}}"))

    def test_redirect(self):
        p = StandIn()
        self.assertEqual("bar", p.expand("{{Redirect}}"))
        self.assertEqual(["Template:Redirect", "Template:Foo"], p.output.templates)
        # the redirect is cached
        self.assertEqual("bar", p.expand("{{Redirect}}"))

    def test_loop(self):
        p = StandIn()
        self.assertEqual('<span class="error">Template loop detected: [[Template:Loop1]]</span>',
                         p.expand("{{loop1}}"))
        self.assertIn("template-loop-category", p.output.tracking_categories)
        self.assertIn(("template-loop-warning", "Template:Loop1"), p.output.warnings)

    def test_depth_limit(self):
        pages = {"Template:N1": "<{{N2}}>", "Template:N2": "<{{N3}}>", "Template:N3": "<{{N4}}>", "Template:N4": "x"}
        p = StandIn(pages=pages, config=TEST.with_(max_template_depth=3))
        self.assertEqual('<<<<<span class="error">Template recursion depth limit exceeded (3)</span>>>>>',
                         p.expand("<{{N1}}>"))
        self.assertEqual("<<<<x>>>>", StandIn(pages=pages).expand("<{{N1}}>"))
        # a template that includes itself is a loop, found before the depth limit
        self.assertEqual('<<span class="error">Template loop detected: [[Template:Nested]]</span>>',
                         StandIn().expand("{{Nested}}"))

    def test_subst(self):
        p = StandIn()
        self.assertEqual("{{subst:Foo}}", p.expand("{{subst:Foo}}"))
        self.assertEqual("bar", p.expand("{{safesubst:Foo}}"))
        pst = StandIn(output_type=OT_WIKI)
        self.assertEqual("{{Foo}} bar bar", pst.expand("{{Foo}} {{subst:Foo}} {{safesubst:Foo}}"))

    def test_msgnw_and_msg(self):
        p = StandIn()
        self.assertEqual("&#39;&#39;a&#39;&#39; &#91;&#91;b&#93;&#93;", p.expand("{{msgnw:Wiki}}"))
        self.assertEqual("''a'' [[b]]", p.expand("{{msg:Wiki}}"))

    def test_block_level_start(self):
        # T2529: a template that starts with a list item starts a new line
        p = StandIn()
        self.assertEqual("x\n* item", p.expand("x{{List}}"))
        self.assertEqual("x\n* item", p.expand("x\n{{List}}"))

    def test_relative_title(self):
        p = StandIn(subpages=True)
        self.assertEqual("subpage", p.expand("{{/sub}}"))
        self.assertEqual("[[:Template:/sub]]", StandIn().expand("{{/sub}}"))  # no subpages in the namespace

    def test_template_equals(self):
        p = StandIn()
        self.assertEqual("=", p.expand("{{=}}"))
        self.assertNotIn("template-equals-category", p.output.tracking_categories)
        p = StandIn(pages={"Template:=": "x"})
        self.assertEqual("x", p.expand("{{=}}"))
        self.assertIn("template-equals-category", p.output.tracking_categories)

    def test_post_expand_include_size(self):
        p = StandIn(config=TEST.with_(max_article_size=1))  # 1024 bytes
        out = p.replace_variables("{{Big}}{{Big}}")
        self.assertEqual("x" * 600 + "[[:Template:Big]]", p.strip_state.kill_markers(out))
        self.assertIn("<!-- WARNING: template omitted, post-expand include size too large -->",
                      p.strip_state.unstrip_both(out))
        self.assertIn("post-expand-template-inclusion-category", p.output.tracking_categories)

    def test_variables_hook(self):
        p = StandIn()
        # get_variable_value() knows no variable yet: {{PAGENAME}} is looked up as a template
        self.assertEqual("[[:Template:PAGENAME]]", p.expand("{{PAGENAME}}"))

        class WithVariables(StandIn):
            def get_variable_value(self, index, frame=None):
                return "Parser test" if index == "pagename" else None

        self.assertEqual("Parser test", WithVariables().expand("{{PAGENAME}}"))

    def test_preprocess_output_type(self):
        p = StandIn(output_type=OT_PREPROCESS)
        self.assertEqual("bar <gallery>x</gallery>", p.expand("{{Foo}} <gallery>x</gallery>"))


class ParserFunctionTest(unittest.TestCase):
    def setUp(self):
        self.words = MagicWordFactory()
        self.words.register("myfunc", False, "myfunc")
        self.words.register("objfunc", False, "objfunc")
        self.words.register("CaseFunc", True, "CaseFunc")

    def test_plain_arguments(self):
        p = StandIn(magic_words=self.words)
        p.set_function_hook("lc", lambda parser, s="": s.lower(), SFH_NO_HASH)
        p.set_function_hook("myfunc", lambda parser, *args: "|".join(args))
        self.assertEqual("abc", p.expand("{{lc: ABC }}"))
        self.assertEqual("abc", p.expand("{{LC:ABC}}"))
        # a named argument is expanded whole ("k = v") and trimmed
        self.assertEqual("a|bar|k = v", p.expand("{{#myfunc: a | {{Foo}} | k = v }}"))
        self.assertEqual("x", p.expand("{{#MyFunc:x}}"))  # case insensitive
        self.assertEqual("[[:Template:Myfunc:x]]", p.expand("{{myfunc:x}}"))  # needs the hash
        self.assertEqual({"found": False}, p.call_parser_function(p.get_preprocessor().new_frame(), "#nope", []))
        self.assertIn("myfunc", p.get_function_hooks())

    def test_case_sensitive(self):
        p = StandIn(magic_words=self.words)
        p.set_function_hook("CaseFunc", lambda parser, *args: "yes")
        self.assertEqual("yes", p.expand("{{#CaseFunc:}}"))
        # not the function, and "#casefunc:" is no valid title (only a fragment): left as it is
        self.assertEqual("{{#casefunc:}}", p.expand("{{#casefunc:}}"))

    def test_object_arguments(self):
        p = StandIn(magic_words=self.words)

        def objfunc(parser, frame, args):
            # expand only the branch that is used
            first = frame.expand(args[0])
            return frame.expand(args[1] if first else args[2]).strip()

        p.set_function_hook("objfunc", objfunc, SFH_OBJECT_ARGS)
        self.assertEqual("bar", p.expand("{{#objfunc: 1 | {{Foo}} | {{loop1}} }}"))
        self.assertNotIn("template-loop-category", p.output.tracking_categories)

    def test_result_flags(self):
        p = StandIn(magic_words=self.words)
        # noparse false: the result is wikitext to preprocess; by default it is left as it is
        p.set_function_hook("myfunc", lambda parser, arg="": {0: "{{" + arg + "}}", "noparse": False})
        self.assertEqual("bar", p.expand("{{#myfunc:Foo}}"))
        p.set_function_hook("myfunc", lambda parser, arg="": "{{" + arg + "}}")
        self.assertEqual("{{Foo}}", p.expand("{{#myfunc:Foo}}"))
        p.set_function_hook("myfunc", lambda parser, arg="": {0: "<b>", "isHTML": True})
        out = p.replace_variables("{{#myfunc:}}")
        self.assertTrue(out.startswith(MARKER_PREFIX + "-item-"))
        self.assertEqual("<b>", p.strip_state.unstrip_both(out))
        p.set_function_hook("myfunc", lambda parser, arg="": {0: "''x''", "nowiki": True})
        self.assertEqual("&#39;&#39;x&#39;&#39;", p.expand("{{#myfunc:}}"))
        p.set_function_hook("myfunc", lambda parser, arg="": {"found": False})
        self.assertEqual("{{#myfunc:a}}", p.expand("{{#myfunc:a}}"))


class TagHookTest(unittest.TestCase):
    def test_nowiki_and_pre(self):
        p = StandIn()
        out = p.replace_variables("<nowiki>''a'' {{Foo}} <b> -{x}-</nowiki>")
        self.assertEqual("", p.strip_state.kill_markers(out))
        self.assertEqual("''a'' {{Foo}} &lt;b&gt; -&#123;x&#125;-", p.strip_state.unstrip_both(out))
        self.assertEqual('<pre class="x">a&lt;b&gt; \'\'c\'\'</pre>',
                         p.expand("<pre class=\"x\" onclick=\"y\">a<b> <nowiki>''c''</nowiki></pre>"))

    def test_indicator(self):
        p = StandIn()
        self.assertEqual("", p.expand('<indicator name=" help ">[[Help]]</indicator>'))
        self.assertEqual({"help": "[[Help]]"}, p.output.indicators)
        self.assertEqual('<span class="error"><strong>Error:</strong> Page status indicators\' <code>name</code> '
                         "attribute must not be empty.</span>", p.expand("<indicator>x</indicator>"))

    def test_langconvert_gallery_and_unknown(self):
        p = StandIn()
        self.assertTrue(p.expand('<langconvert from="zh" to="zh-tw">x</langconvert>').startswith(
            '<span class="error"><strong>Error:</strong> Langconvert tag'))
        # the gallery needs the whole Parser (links, images): a bogus title is skipped, a missing file shows its name
        parser = Parser(config=TEST, site=test_site(False, TEST))
        self.assertEqual('<ul class="gallery mw-gallery-traditional">\n</ul>',
                         parser.parse("<gallery>a <b></gallery>", "Parser test"))
        self.assertIn('<div class="thumb" style="height: 150px;">Foo.jpg</div>',
                      parser.parse("<gallery>\nFile:Foo.jpg|x\n</gallery>", "Parser test"))
        self.assertEqual("<html>x</html>", p.expand("<html>x</html>"))  # $wgRawHtml is off: not a tag
        raw = StandIn(config=TEST.with_(raw_html=True))
        self.assertEqual("<b>x</b>", raw.expand("<html><b>x</b></html>"))

    def test_custom_hook(self):
        p = StandIn()
        p.set_hook("Echo", lambda content, attribs, parser, frame: f"[{content}|{attribs.get('a')}]")
        self.assertIn("echo", p.get_tags())
        self.assertIn("echo", p.get_strip_list())
        self.assertEqual("[x {{Foo}}|1][None|None]", p.expand('<echo a="1">x {{Foo}}</echo><echo/>'))
        self.assertEqual("<echo>x</echo>", StandIn().expand("<echo>x</echo>"))
        p.set_hook("parsed", lambda content, attribs, parser, frame: parser.recursive_tag_parse(content, frame))
        self.assertEqual("bar", p.expand("<parsed>{{Foo}}</parsed>"))

    def test_error_name(self):
        p = StandIn()
        p.strip_list.append("nohook")
        self.assertEqual('<span class="error">Invalid tag extension name: nohook</span>',
                         p.expand("<nohook>x</nohook>"))


class HelperTest(unittest.TestCase):
    def test_wf_escape_wiki_text(self):
        self.assertEqual("&#91;&#91;a&#93;&#93; &#123;&#123;b&#125;&#125;\n&#42; c _&#95;X_&#95; http&#58;//x "
                         "mailto&#58;y ISBN&#32;1",
                         wf_escape_wiki_text("[[a]] {{b}}\n* c __X__ http://x mailto:y ISBN 1", TEST))

    def test_normalize_subpage_link(self):
        site = test_site(True)
        context = Title.new_from_text("A/B/C", site=site)
        self.assertEqual(("A/B/C/D", "D"), normalize_subpage_link(context, "/D/", "", site))
        self.assertEqual(("A/B/C/D", "/D"), normalize_subpage_link(context, "/D", "", site))
        self.assertEqual(("A/B/E", ""), normalize_subpage_link(context, "../E", "", site))
        self.assertEqual(("A", ""), normalize_subpage_link(context, "../../", "", site))
        self.assertEqual(("../../../X", ""), normalize_subpage_link(context, "../../../X", "", site))
        self.assertEqual(("/D", ""), normalize_subpage_link(context, "/D", "", test_site(False)))

    def test_strip_outer_paragraph(self):
        self.assertEqual("a", strip_outer_paragraph("<p>a\n</p>"))
        self.assertEqual("<p>a</p><p>b</p>", strip_outer_paragraph("<p>a</p><p>b</p>"))
        self.assertEqual('<p class="x">a</p>', strip_outer_paragraph('<p class="x">a</p>'))

    def test_extract_tags_and_params(self):
        stripped, matches = extract_tags_and_params(["ref"], 'a<ref name="x">b</ref>c<!-- d -->e<ref/>')
        markers = list(matches)
        self.assertEqual(f"a{markers[0]}c{markers[1]}e{markers[2]}", stripped)
        self.assertEqual(["ref", "b", {"name": "x"}, '<ref name="x">b</ref>'], matches[markers[0]])
        self.assertEqual(["!--", " d ", {}, "<!-- d -->"], matches[markers[1]])
        self.assertEqual(["ref", None, {}, "<ref/>"], matches[markers[2]])

    def test_marker_skip_callback(self):
        marker = f"{MARKER_PREFIX}-x-1-{MARKER_SUFFIX}"
        self.assertEqual(f"AA{marker}BB", StandIn.marker_skip_callback(f"aa{marker}bb", str.upper))

    def test_state(self):
        p = StandIn()
        self.assertEqual({"html": True, "wiki": False, "pre": False, "plain": False}, p.ot)
        self.assertEqual("Parser test", p.get_title().prefixed_text)
        self.assertEqual("Special:Badtitle/Parser", StandIn(title="").get_title().prefixed_text)
        p.limitation_warn("node-count-exceeded", 5, 4)
        self.assertEqual([("node-count-exceeded-warning", 5, 4)], p.output.warnings)
        self.assertIn("node-count-exceeded-category", p.output.tracking_categories)
        self.assertEqual("x", p.recursive_preprocess("{{{1|x}}}"))
        self.assertEqual("{{Foo}} y", p.replace_variables("{{Foo}} {{{1|y}}}", args_only=True))
        self.assertEqual("v", p.replace_variables("{{{k}}}", {"k": "v"}))


if __name__ == "__main__":
    unittest.main()

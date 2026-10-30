"""biwiki.htmlmd: the MediaWiki port's HTML -> a3ref's Markdown, one construct per test."""
from __future__ import annotations

import unittest

from biwiki.htmlmd import HtmlMarkdown, html_to_md, html_to_plain, link_target
from biwiki.site import ANCHOR
from biwiki.markdown import CODE_LINK

PAGES = {"setPos": "../commands/setPos.md", "Multiplayer Scripting": "../topics/Multiplayer_Scripting.md",
         "Array": "../topics/Array.md"}


def resolve(title: str, anchor: str):
    url = PAGES.get(title)
    return url + ("#" + anchor.lower().replace(" ", "-") if anchor else "") if url else None


def md(html: str, **options) -> str:
    return HtmlMarkdown(resolve, **options).md(html)


class TextTest(unittest.TestCase):
    def test_paragraphs_and_emphasis(self):
        self.assertEqual(md("<p>a <b>bold </b>and <i>it</i> <i><b>both</b></i>\n</p><p>next</p>"),
                         "a **bold** and *it* ***both***\n\nnext")
        self.assertEqual(md("<p><s>gone</s> <u>u</u> <sup>2</sup></p>"), "~~gone~~ u 2")

    def test_emphasis_off(self):
        self.assertEqual(md("<p><b>bold</b></p>", emphasis=False), "bold")

    def test_escapes(self):
        # "![" is no image; a backslash of the text is literal
        self.assertEqual(md('<p>!<a href="/wiki/setPos">alive</a> P:\\ dir\\*</p>'),
                         "\\![alive](../commands/setPos.md) P:\\ dir\\\\*")
        # a later line of a paragraph never starts a list, heading or quote
        self.assertEqual(md("<p>a<br />\n1. one<br />\n- two<br />\n# three<br />\n&gt; q</p>"),
                         "a\\\n1\\. one\\\n\\- two\\\n\\# three\\\n\\> q")
        # only "1." can interrupt a paragraph: "2." needs no escape
        self.assertEqual(md("<p>1) one<br />\n2) two<br />\n10. ten</p>"), "1) one\\\n2) two\\\n10. ten")
        # the first line keeps a list mark, as Renderer does, but not a heading or quote mark
        self.assertEqual(md("<p>- item</p><p># no heading</p><p>&gt; no quote</p>"),
                         "- item\n\n\\# no heading\n\n\\> no quote")

    def test_breaks(self):
        self.assertEqual(md("<p>a<br />\nb<br /></p>"), "a\\\nb")
        self.assertEqual(md("<p>a<br /><br />b</p>"), "a\n\nb")
        self.assertEqual(md("<p><br />\n</p><p>a</p>"), "a")
        self.assertEqual(md("<p>a<br />b</p>", hard_breaks=False), "a\nb")
        self.assertEqual(md("<p>a<br />b</p>", inline=True), "a\nb")

    def test_hidden_parts(self):
        self.assertEqual(md('<div id="toc" class="toc"><h2>Contents</h2></div><p class="mw-empty-elt"></p>'
                            '<span style="display:none">x</span><p>text</p>'), "text")

    def test_nbsp_kept(self):
        self.assertEqual(md("<p>a&#160;b</p>"), "a\xa0b")

    def test_french_spacing(self):
        # MediaWiki's &#160; before "!?:;%»" and after "«" is a plain space of the wiki text
        self.assertEqual(md("<p>Go&#160;! a&#160;: b&#160;:c 5&#160;% «&#160;q&#160;» 8&#160;+&#160;1</p>"),
                         "Go ! a : b\xa0:c 5 % « q » 8\xa0+\xa01")
        self.assertEqual(html_to_plain("<p>why&#160;?</p>"), "why ?")
        # code has no non-breaking spaces at all
        self.assertEqual(md('<p><code>a&#160;;</code></p><div class="sqfhighlighter-block">hint "a&#160;!"; x&#160;=1;'
                            '</div><pre>pre&#160;?\n</pre>'), '`a ;`\n\n```sqf\nhint "a !"; x =1;\n```\n\n```\npre ?\n```')


class LinkTest(unittest.TestCase):
    def test_internal(self):
        self.assertEqual(md('<p><a href="/wiki/setPos" title="setPos">setPos</a> '
                            '<a href="/wiki/Other" title="Other">other</a></p>'),
                         "[setPos](../commands/setPos.md) other")

    def test_red_link_goes_through_the_resolver(self):
        r = HtmlMarkdown(resolve)
        html = ('<p><a href="/wiki?title=Array&amp;action=edit&amp;redlink=1" class="new">arrays</a> '
                '<a href="/wiki?title=Template:Spoiler&amp;action=edit&amp;redlink=1" class="new" '
                'title="Template:Spoiler (page does not exist)">Template:Spoiler</a></p>')
        self.assertEqual(r.md(html), "[arrays](../topics/Array.md) Template:Spoiler")
        self.assertEqual(r.unknown["template:Spoiler"], 1)

    def test_anchor(self):
        # the wiki's "_" for a heading's spaces; a leading "_" belongs to the name
        self.assertEqual(md('<p><a href="/wiki/Multiplayer_Scripting#Join_In_Progress">JIP</a></p>'),
                         "[JIP](../topics/Multiplayer_Scripting.md#join-in-progress)")
        self.assertEqual(link_target("/wiki/Magic_Variables#_this"), ("Magic Variables", "_this"))

    def test_self_and_fragment_links(self):
        self.assertEqual(md('<p><a class="mw-selflink selflink">setPos</a> <a href="#Example_1">ex</a></p>',
                            page_title="setPos"),
                         "[setPos](../commands/setPos.md) [ex](../commands/setPos.md#example-1)")

    def test_text(self):
        # spaces stay outside the brackets, brackets inside are escaped, an icon-only link gets a text
        self.assertEqual(md('<p><a href="/wiki/Array"> list </a> <a href="/wiki/Array">[a]</a> '
                            '<a href="/wiki/Array#Copy"><img src="x"/></a></p>'),
                         "[list](../topics/Array.md) [\\[a\\]](../topics/Array.md) "
                         "[Copy](../topics/Array.md#copy)")

    def test_external(self):
        self.assertEqual(md('<p><a class="external text" href="https://a.com">A</a> '
                            '<a class="external free" href="https://b.com">https://b.com</a> '
                            '<a class="external autonumber" href="https://c.com">[1]</a></p>'),
                         "[A](https://a.com) https://b.com <https://c.com>")

    def test_files_are_not_images(self):
        self.assertEqual(md('<p><a href="/wiki/File:Logo.png" title="File:Logo.png">File:Logo.png</a>x '
                            '<a href="/wiki/File:Ico_ok.png">Checked</a> '
                            '<a href="/wiki/File:Info.png">Read me</a></p>'), "x ✓ Read me")

    def test_plain_has_no_links(self):
        self.assertEqual(md('<p><a href="/wiki/setPos">setPos</a> <a class="external text" href="https://a.com">A'
                            '</a> <b>b</b></p>', plain=True), "setPos A b")

    def test_legacy_anchor_is_decoded(self):
        # old links write "#include" as ".23include" (MediaWiki's legacy anchors); the resolver gets the heading
        self.assertEqual(md('<p><a href="/wiki/Array#.23include">i</a> <a href="/wiki/Array#Modes.5B.5D">m</a> '
                            '<a href="/wiki/Array#Arma_3_v1.22">v</a></p>'),
                         "[i](../topics/Array.md##include) [m](../topics/Array.md#modes[])"
                         " [v](../topics/Array.md#arma-3-v1.22)")

    def test_link_target(self):
        self.assertEqual(link_target("/index.php?title=A_b&action=edit&redlink=1"), ("A b", ""))
        self.assertEqual(link_target("/wiki/Arma_3:_Event_Handlers#Killed"), ("Arma 3: Event Handlers", "Killed"))
        self.assertIsNone(link_target("https://example.com/wiki/x"))


class BlockTest(unittest.TestCase):
    def test_headings(self):
        self.assertEqual(md('<h2><span class="mw-headline" id="Usage">Usage</span>'
                            '<mw:editsection page="P" section="1">Usage</mw:editsection></h2><p>x</p>'),
                         "### Usage\n\nx")
        self.assertEqual(md("<h3>The # operator #</h3>"), "#### The # operator \\#")
        self.assertEqual(md("<h6>Deep</h6>"), "###### Deep")

    def test_lists(self):
        self.assertEqual(md("<ul><li>a\n<ul><li>b</li></ul></li><li>c</li></ul>\n<ol><li>one\n<ol><li>two</li></ol>"
                            "</li></ol>"),
                         "- a\n  - b\n- c\n\n1. one\n   1. two")

    def test_list_item_with_block(self):
        self.assertEqual(md('<ul><li>run:<div class="sqfhighlighter-block">a;\nb;</div></li></ul>'),
                         "- run:\n\n  ```sqf\n  a;\n  b;\n  ```")

    def test_definition_lists(self):
        self.assertEqual(md("<dl><dt>Type</dt><dd>String</dd><dt>Author:</dt><dd>BI</dd></dl>"),
                         "**Type:** String\n\n**Author:** BI")
        self.assertEqual(md("<dl><dt>Boundary cases</dt><dd></dd></dl>"), "**Boundary cases**")
        self.assertEqual(md("<p>text</p><dl><dd>indented</dd></dl>"), "text\n\nindented")
        # ": a" lines are lines of one paragraph, as Renderer writes them; a block ends the run
        self.assertEqual(md("<dl><dd>one</dd><dd>two <b>2</b></dd><dd><ul><li>x</li></ul></dd><dd>three</dd>"
                            "<dt>T</dt><dd>d</dd><dd>four</dd></dl>"),
                         "one\ntwo **2**\n\n- x\n\nthree\n\n**T:** d\n\nfour")

    def test_blockquote_and_rule(self):
        self.assertEqual(md("<blockquote><p>quoted</p></blockquote><hr />"), "> quoted\n\n---")

    def test_block_inside_inline(self):
        self.assertEqual(md('<p>a <span>b <div class="mw-highlight mw-highlight-lang-cpp"><pre>x;</pre></div>'
                            ' c</span></p>'),
                         "a b\n\n```cpp\nx;\n```\n\nc")


class CodeTest(unittest.TestCase):
    def test_highlighters(self):
        self.assertEqual(md('<div class="sqfhighlighter-block"><div class="sqfhighlighter-scroller">'
                            '<a href="/wiki/hint">hint</a> <span class="s">"x"</span>;</div></div>'),
                         '```sqf\nhint "x";\n```')
        self.assertEqual(md('<div class="sqfhighlighter-block sqshighlighter-block">_a = 1</div>'),
                         "```sqs\n_a = 1\n```")
        self.assertEqual(md('<div class="enforcescripthighlighter-block armar"><span>int</span> a;</div>'),
                         "```enforce\nint a;\n```")
        self.assertEqual(md('<div class="mw-highlight mw-highlight-lang-cpp mw-content-ltr" dir="ltr">'
                            '<pre><span></span>class A\n{\n\tx = 1;\n};\n</pre></div>'),
                         "```cpp\nclass A\n{\n    x = 1;\n};\n```")

    def test_fence_longer_than_content(self):
        self.assertEqual(md("<pre>a ``` b</pre>"), "````\na ``` b\n````")

    def test_preformatted_lines(self):
        html = '<pre>space <a href="/wiki/setPos">setPos</a> <b>x</b>\nmore\n</pre>'
        self.assertEqual(md(html), "```\nspace setPos x\nmore\n```")
        self.assertEqual(md(html, code_links=True),
                         f"```\nspace {CODE_LINK[0]}setPos{CODE_LINK[1]}../commands/setPos.md{CODE_LINK[2]} x\n"
                         "more\n```")
        self.assertEqual(md(html, preformat=False, hard_breaks=False), "space [setPos](../commands/setPos.md) **x**"
                         "\nmore")

    def test_code_display_block(self):
        self.assertEqual(md('<ul><li>put<code style="display: block">C:\\x<br />y</code></li></ul>'),
                         "- put\n\n  ```\n  C:\\x\n  y\n  ```")

    def test_inline_code(self):
        self.assertEqual(md('<p><var>a = 1</var> <code>c <a href="/wiki/setPos">setPos</a> <b>b</b></code> '
                            '<tt>t</tt> <var>&#160;</var> <code>x`y</code></p>'),
                         "`a = 1` `c setPos b` `t` ` ` ``x`y``")
        self.assertEqual(md('<p><span class="sqfhighlighter-block"><a href="/wiki/hint">hint</a> 1</span> and '
                            '<code class="mw-highlight mw-highlight-lang-cpp">class A;</code></p>'),
                         "`hint 1` and `class A;`")
        self.assertEqual(md('<pre>a <span class="code-comment">// c</span></pre><p><span class="code-comment">// c'
                            '</span></p>'), "```\na // c\n```\n\n`// c`")

    def test_inline_code_not_escaped(self):
        self.assertEqual(md("<p>a<br />\n<code>- x</code> <code>![y]</code></p>"), "a\\\n`- x` `![y]`")

    def test_kbd(self):
        self.assertEqual(md("<p><kbd>Ctrl</kbd>&#32;+ <kbd>A</kbd></p>"), "<kbd>Ctrl</kbd> + <kbd>A</kbd>")
        self.assertEqual(md("<p><kbd>Ctrl</kbd></p>", plain=True), "Ctrl")


class TableTest(unittest.TestCase):
    def test_header_row(self):
        self.assertEqual(md('<table class="wikitable">\n<tbody><tr>\n<th>A</th>\n<th>B\n</th></tr>\n<tr>\n'
                            '<td>1</td>\n<td>2\n</td></tr></tbody></table>'),
                         "| A | B |\n|---|---|\n| 1 | 2 |")

    def test_no_header_row(self):
        self.assertEqual(md("<table><tr><td>1</td><td>2</td></tr></table>"), "|  |  |\n|---|---|\n| 1 | 2 |")

    def test_spans(self):
        self.assertEqual(md('<table><tr><th>H1</th><th>H2</th></tr><tr><td rowspan="2">R</td><td>x</td></tr>'
                            '<tr><td>y</td></tr><tr><td colspan="2">wide</td></tr></table>'),
                         "| H1 | H2 |\n|---|---|\n| R | x |\n| R | y |\n| wide |  |")

    def test_cells(self):
        self.assertEqual(md('<table><tr><td>a<br />b | c<ul><li>i</li><li>j</li></ul></td>'
                            '<td><div class="sqfhighlighter-block">hint 1;</div></td></tr></table>'),
                         "|  |  |\n|---|---|\n| a<br>b \\| c<br>- i<br>- j | `hint 1;` |")

    def test_heading_in_cell(self):
        # "| ===== Campaigns =====" (topic CfgMissions): a cell cannot hold a Markdown heading, so it is bold
        self.assertEqual(md('<table><tr><td>\n<h5><span class="mw-headline" id="Campaigns">Campaigns</span></h5>\n'
                            '</td><td>x</td></tr></table>'),
                         "|  |  |\n|---|---|\n| **Campaigns** | x |")
        # for the site the heading keeps its anchor
        self.assertEqual(md('<table><tr><td><h5><span class="mw-headline" id="Campaigns">Campaigns</span></h5>'
                            '</td></tr></table>', anchors=True),
                         f"|  |\n|---|\n| **{ANCHOR[0]}campaigns{ANCHOR[1]}Campaigns** |")

    def test_anchors(self):
        # the class tables' "<span id=B_TargetSoldier>", ids of rows and cells, a heading's own anchor: marks for
        # the site, as heading_id makes them (as links to them get it); nothing in the Markdown flavour
        a, b = ANCHOR
        html = ('<table><tr id="row_1"><td><span id="B_TargetSoldier"><b>B_TargetSoldier</b></span></td>'
                '<td id="Cell">c</td></tr></table>')
        self.assertEqual(md(html, anchors=True),
                         f"|  |  |\n|---|---|\n| {a}row-1{b}{a}b-targetsoldier{b}**B_TargetSoldier** | {a}cell{b}c |")
        self.assertEqual(md(html), "|  |  |\n|---|---|\n| **B_TargetSoldier** | c |")
        # Magic Variables: the heading "_x" has the anchor "x"; the legacy fallback <span> is decoded as links are
        self.assertEqual(md('<h3><span class="mw-headline" id="x">_x</span></h3>', anchors=True), f"#### {a}x{b}_x")
        self.assertEqual(md('<h3><span id=".23include"></span><span class="mw-headline" id="#include">#include'
                            '</span></h3>', anchors=True), f"#### {a}include{b}{a}include{b}#include")
        # the wiki's interface and reference ids are no anchors; plain text never has marks
        self.assertEqual(md('<p><sup id="cite_ref-1" class="x">s</sup><span id="mw-x">t</span></p>', anchors=True),
                         "st")
        self.assertEqual(md('<p><span id="A">t</span></p>', anchors=True, plain=True), "t")

    def test_caption(self):
        self.assertEqual(md("<table><caption>Dates\n</caption><tr><th>A</th></tr><tr><td>1</td></tr></table>"),
                         "**Dates**\n\n| A |\n|---|\n| 1 |")

    def test_caption_with_box(self):
        # "|+ Edition Details {{Feature|important|...}}": the box stays a GitHub alert, not text in the bold line
        box = ('<div class="biki-messagebox feature-important"><div>!</div><div>Note that <b>no</b> CDLCs.'
               '</div></div>')
        self.assertEqual(md(f"<table><caption>Edition Details\n{box}</caption><tr><th>A</th></tr></table>"),
                         "**Edition Details**\n\n> [!IMPORTANT]\n> Note that **no** CDLCs.\n\n| A |\n|---|")
        self.assertEqual(md(f"<table><caption>\n{box}</caption><tr><th>A</th></tr></table>"),
                         "> [!IMPORTANT]\n> Note that **no** CDLCs.\n\n| A |\n|---|")


class TemplateTest(unittest.TestCase):
    @staticmethod
    def box(kind: str, icon: str, body: str) -> str:
        return f'<div class="biki-messagebox {kind}"><div>{icon}</div><div>{body}</div></div>'

    def test_feature_alerts(self):
        self.assertEqual(md(self.box("feature-informative", "ⓘ", "Read <b>this</b>.")),
                         "> [!NOTE]\n> Read **this**.")
        self.assertEqual(md(self.box("feature-important", "⚠", "Careful")), "> [!IMPORTANT]\n> Careful")
        self.assertEqual(md(self.box("feature-warning", "⚠", "Warn\n<ul><li>a</li></ul>")),
                         "> [!WARNING]\n> Warn\n>\n> - a")
        self.assertEqual(md(self.box("feature-obsolete", "🕖", "Old.")), "> [!CAUTION]\n> Old.")

    def test_feature_quote(self):
        self.assertEqual(md(self.box("feature-quote", "«", '<span class="feature-quote">« Hi »</span> – Me')),
                         "> « Hi » – Me")

    def test_feature_games(self):
        self.assertEqual(md(self.box("feature-arma3", '<a href="/wiki/File:A3.png">Arma 3</a>', "Only here.")),
                         "> [!NOTE]\n> **Arma 3:** Only here.")
        self.assertEqual(md(self.box("feature-arma3contact", '<a href="/wiki/File:c.png">File:c.png</a>',
                                     "This content is exclusive.")),
                         "> [!NOTE]\n> This content is exclusive.")
        self.assertEqual(md(self.box("feature-afm", '<a href="/wiki/File:h.png">Advanced Flight Model</a>',
                                     "Enable it.")),
                         "> [!NOTE]\n> **Advanced Flight Model:** Enable it.")

    def test_feature_gvi(self):
        icon = ('<div><span class="gvi2 gvi-arma3"><span class="icon"><a href="/wiki/File:A3.png">File:A3.png</a>'
                '</span><span class="version"><a href="/wiki?title=Category:X&amp;redlink=1"> 2.00</a></span></span>'
                '</div>')
        self.assertEqual(md(self.box("feature-gvi", icon, "Since then.")),
                         "> [!NOTE]\n> **Since Arma 3 v2.00:** Since then.")

    def test_messageboxes(self):
        self.assertEqual(md('<div class="biki-messagebox messagebox-bi"><div><a href="/wiki/File:bi.png">'
                            'File:bi.png</a></div><div><b>One</b><br />Two</div></div>'), "> **One**\\\n> Two")
        # {{Wiki|placeholder}}: maintenance, no content
        self.assertEqual(md('<div class="biki-messagebox" style="background-color:DarkGray"><div>🏗</div>'
                            '<div>Placeholder</div></div>'), "")
        self.assertEqual(md('<div class="biki-messagebox" style="background-color:#AAB8C6"><div>QGIS</div>'
                            '<div>Tip</div></div>'), "> Tip")
        # {{Wiki|stub}}: its link is the wiki's edit form, which Markdown must not link to
        self.assertEqual(md('<div class="notice metadata" id="stub"><i>This article is a <a href="/wiki/Category:Stubs">'
                            'Stub</a>. You can help by <span class="plainlinks"><a class="external text" href="https://'
                            'community.bistudio.com/wiki?title=X&amp;action=edit">expanding it</a></span>.</i></div>'
                            '<p>text</p>'), "text")
        # an unclosed <pre> before the boxes (placeholder function pages): the wiki shows boxes, not code
        self.assertEqual(md('<pre><div class="biki-messagebox" style="background-color:DarkGray"><div>🏗</div><div>'
                            'Placeholder</div></div> <div class="biki-messagebox feature-arma3contact"><div><a href="'
                            '/wiki/Arma_3_Contact"><img alt="enoch icon ca.png" /></a></div><div>This content is '
                            'exclusive to the Arma 3 Contact Expansion.</div></div></pre>'),
                         "> [!NOTE]\n> This content is exclusive to the Arma 3 Contact Expansion.")
        # the text around the boxes stays code
        self.assertEqual(md('<pre>/***\n *\tname: x\n<div class="biki-messagebox" style="background-color:DarkGray">'
                            '<div>🏗</div><div>Placeholder</div></div>\nafter</pre>'),
                         "```\n/***\n *    name: x\n```\n\n```\nafter\n```")

    def test_game_versions(self):
        gvi = ('<span class="gvi2 gvi-arma3 gvi-alpha" style="font-size: 10px"><span class="icon"><a href="/wiki/'
               'File:A3.png">File:A3.png</a></span><span class="version"><a href="/wiki?title=Category:I&amp;'
               'action=edit&amp;redlink=1" class="new"> 1.00</a></span></span>')
        self.assertEqual(md(f"<p>{gvi} text <span class=\"gvi2 gvi-arma2oa\"></span></p>"),
                         "Arma 3 v1.00 text Arma 2: Operation Arrowhead")
        # {{GVI|arma0|1.85}} has the class gvi-ofp: the game comes from its category
        cwa = ('<span class="gvi2 gvi-ofp"><span class="version"><a href="/wiki?title=Category:Introduced_with_Arma:'
               '_Cold_War_Assault_version_1.85&amp;action=edit&amp;redlink=1" class="new" title="Category:Introduced '
               'with Arma: Cold War Assault version 1.85 (page does not exist)"> 1.85</a></span></span>')
        self.assertEqual(md(f"<p>{cwa}</p>"), "Arma: Cold War Assault v1.85")
        # {{GVI|arma3}} without a version shows "?" on the wiki; Renderer writes the game only
        self.assertEqual(md('<p><span class="gvi2 gvi-arma3"><span class="version">?</span></span></p>'), "Arma 3")

    def test_arg_title(self):
        self.assertEqual(md('<div style="display: flex; align-items: baseline"><div><span class="gvi2 gvi-arma3">'
                            '<span class="version"> 1.00</span></span></div><div style="flex-grow: 1">\n'
                            '<h3><span class="mw-headline" id="AnimChanged">AnimChanged</span></h3>\n</div></div>'),
                         "#### AnimChanged (Arma 3 v1.00)")
        # {{ArgTitle|3|Modules||{{GVI|...}}}}: what is right of the title stays out of it, as with Renderer
        self.assertEqual(md('<div style="display: flex; align-items: baseline"><div style="flex-grow: 1">\n'
                            '<h3><span class="mw-headline" id="Modules">Modules</span></h3>\n</div>'
                            '<div style="margin-left: 0.5em">\n<p><span class="gvi2 gvi-arma2"><span class="version">'
                            ' 1.00</span></span>\n<span class="gvi2 gvi-tkoh"></span>\n</p></div></div><p>Text</p>'),
                         "#### Modules\n\nText")
        # several versions on the left: as the wiki text separates them
        self.assertEqual(md('<div style="display: flex"><div style="margin-right: 0.5em"><span class="gvi2 gvi-tkoh">'
                            '<span class="version">1.00</span></span>\n<span class="gvi2 gvi-arma3"><span class="version">'
                            '1.00</span></span></div><div style="flex-grow: 1">\n<h2>Scripting</h2>\n</div></div>'),
                         "### Scripting (Take On Helicopters v1.00 Arma 3 v1.00)")

    def test_icons_and_marks(self):
        self.assertEqual(md('<p><a href="/wiki/Multiplayer_Scripting#Locality"><span class="icon2" '
                            'title="Local argument"><span class="letter-1">L</span><span class="subtext">Local</span>'
                            '</span></a> <span class="sic">Controler</span><sup class="sic"><a href="/wiki/'
                            'Template:sic">sic</a></sup> <div style="border-radius: 50%; width: 1em"></div> x</p>'),
                         "[Local argument](../topics/Multiplayer_Scripting.md#locality) Controler [sic] ● x")

    def test_references(self):
        self.assertEqual(md('<p>text<sup id="cite_ref-1" class="reference"><a href="#cite_note-1">[1]</a></sup> more'
                            '</p><div class="mw-references-wrap"><ol class="references"><li id="cite_note-1">'
                            '<span class="mw-cite-backlink"><a href="#cite_ref-1">↑</a></span> '
                            '<span class="reference-text">a <i>ref</i></span></li></ol></div>'),
                         "text (ref: a *ref*) more")

    def test_user_note(self):
        html = ('<dl class="command_description" id="usernote20200101120000">\n<dt class="noteauthor">'
                '<a href="/wiki?title=User:Foo&amp;action=edit&amp;redlink=1" class="new">Foo</a> <small>- '
                '<a href="/wiki/Special:Contributions/Foo">c</a></small></dt>\n<dd class="notedate">Posted on Jan 01, '
                '2020 - 12:00 (UTC)</dd>\n<dt></dt>\n<dd class="note">\nHello <b>there</b>\n</dd>\n</dl>')
        self.assertEqual(md(html), "> **Foo** (2020-01-01):\n>\n> Hello **there**")

    def test_spoiler(self):
        self.assertEqual(md('<p><button class="biki-spoiler">Show text</button></p><div class="biki-spoiler"><div>'
                            '<p>hidden</p><a href="#bikisp1" class="bikispoiler-top">↑ Back</a></div></div>'),
                         "hidden")

    def test_tabs(self):
        self.assertEqual(md('<div class="biki-tabs"><div class="biki-tab-title"><a href="/wiki/File:x.png">File:x.png'
                            '</a> Arma 3 <b>only</b></div><div class="biki-tab-title">Old</div>'
                            '<div class="biki-tab-content"><p>new text</p></div>'
                            '<div class="biki-tab-content"><p>old text</p></div></div>'),
                         "**Arma 3 only**\n\nnew text\n\n**Old**\n\nold text")

    def test_hatnote(self):
        self.assertEqual(md('<div class="dablink">ⓘ <i>See also <a href="/wiki/Array">Array</a>.</i></div>'),
                         "*See also [Array](../topics/Array.md).*")


class PlainTest(unittest.TestCase):
    def test_plain(self):
        html = ('<p><a href="/wiki/Array">Array</a> of <b>numbers</b><br />see <code>x</code></p>'
                '<ul><li>one</li></ul>')
        self.assertEqual(HtmlMarkdown(resolve).plain_lines(html), "Array of numbers\nsee `x`\n\n- one")
        self.assertEqual(HtmlMarkdown(resolve).plain(html), "Array of numbers see `x` - one")
        self.assertEqual(html_to_plain(html), "Array of numbers see `x` - one")

    def test_module_function(self):
        self.assertEqual(html_to_md('<p><a href="/wiki/setPos">setPos</a></p>', resolve), "[setPos](../commands/setPos.md)")


if __name__ == "__main__":
    unittest.main()

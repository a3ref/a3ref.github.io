"""Convert the HTML of the MediaWiki parser port (biwiki/mediawiki/) to Markdown in a3ref's conventions.

The port renders wikitext as the BI Community Wiki does; this module turns that HTML into the Markdown that
``wikitext.Renderer`` writes: GitHub alerts for the wiki's notes, fenced code with a language, pipe tables,
"- " lists, headings one level down, ``**``/``*`` emphasis, "Arma 3 v2.00" for game versions, ``\\`` hard breaks.
Links go through a resolver (title, anchor) -> URL or None, as with the Renderer, so Markdown links only to
mirrored pages. Images are never emitted.

The input is the port's output, not arbitrary HTML: the shapes of the wiki's templates are recognised by the
class names they emit (biki-messagebox feature-*, gvi2, sqfhighlighter-block, command_description, ...).
Original a3ref code (MIT); it reads HTML only and shares no code with MediaWiki.
"""
from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser
from typing import Optional, Union
from urllib.parse import parse_qs, unquote, urlsplit

# shared with the wikitext renderer while both exist
from .wikitext import (CODE_LINK, FEATURE_ALERT, GAME_NAMES, LinkResolver, _inline_code, _MD_BACKSLASH, _quote,
                       _split_ws, _unspan, game_name)

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
             "wbr"}
BLOCK_TAGS = {"address", "article", "aside", "blockquote", "center", "dd", "div", "dl", "dt", "figure", "footer",
              "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
              "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul"}
# never shown: interface widgets, the table of contents, images and galleries, edit links, the reference list
# (its notes are inlined where they are cited)
SKIP_TAGS = {"button", "img", "input", "mw:editsection", "noscript", "script", "style", "audio", "video", "map"}
SKIP_CLASSES = {"toc", "toc-side", "mw-references-wrap", "references", "thumb", "gallery", "mw-editsection",
                "bikispoiler-top", "catlinks", "printfooter", "mw-empty-elt"}
INLINE_CODE_TAGS = {"code", "tt", "var", "samp"}
FILE_PREFIXES = ("file:", "image:", "media:")
# captions of images that stand for a symbol: {{Icon|checked}} in the comparison tables
FILE_CAPTIONS = {"checked": "✓", "unchecked": "✗"}
# a <div class="..."> holding highlighted code -> the fence's language
HIGHLIGHT_BLOCKS = {"sqshighlighter-block": "sqs", "sqfhighlighter-block": "sqf",
                    "enforcescripthighlighter-block": "enforce"}

BR = "\ue010"  # <br>, resolved when a paragraph is finished
_SLOT = re.compile("\ue011(\\d+)\ue012")  # finished blocks inside inline content (a <div> in a <span>)
_CODE_SLOT = re.compile("\ue013(\\d+)\ue014")  # inline code, kept away from the text passes
_STAR = "\ue015"  # emphasis mark, a "*" only once the paragraph's text has been escaped
_LINE_MARK = re.compile(r"(?m)^([ \t]*)([*+-](?=[ \t])|#{1,6}(?=[ \t]|$)|>|\d{1,9}[.)](?=[ \t]|$))")
_NOTE_ID = re.compile(r"usernote(\d{12,14})")
# {{Wiki|placeholder}}, {{Wiki|TODO}} ...: maintenance message boxes, told apart by the colours Template:Wiki
# gives Template:Messagebox; they carry no reference content (Renderer drops {{Wiki}} too)
MAINTENANCE_COLOURS = {"#f00", "burlywood", "blueviolet", "darkgray", "#96c", "dodgerblue"}


class Element:
    """A node of the parsed HTML: tag name, attributes and children (Elements and text)."""

    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list[Union[Element, str]] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def elements(self, tag: Optional[str] = None):
        return [c for c in self.children if isinstance(c, Element) and (tag is None or c.tag == tag)]

    def find(self, pred) -> list[Element]:
        """Descendants matching ``pred``, in document order (not below a match)."""
        out = []
        for c in self.children:
            if isinstance(c, Element):
                if pred(c):
                    out.append(c)
                else:
                    out += c.find(pred)
        return out

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else ("\n" if c.tag == "br" else c.text()) for c in self.children)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        el = Element(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(el)
        if tag not in VOID_TAGS:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):  # a stray end tag is ignored
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        kids = self.stack[-1].children
        if kids and isinstance(kids[-1], str):
            kids[-1] += data
        else:
            kids.append(data)


def parse_html(html: str) -> Element:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def link_target(href: str) -> Optional[tuple[str, str]]:
    """(title, anchor) of a wiki-internal href: /wiki/Title#anchor, /wiki?title=X&action=edit&redlink=1 (a red
    link: the page X), /index.php?title=X; None for anything else. Titles have spaces, anchors are decoded."""
    if href.startswith("#"):
        return "", unquote(href[1:])
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return None
    if parts.path.startswith("/wiki/"):
        title = unquote(parts.path[len("/wiki/"):])
    elif parts.path in ("/wiki", "/index.php", "/w/index.php") and "title" in parse_qs(parts.query):
        title = parse_qs(parts.query)["title"][0]
    else:
        return None
    return title.replace("_", " ").strip(), unquote(parts.fragment)


class HtmlMarkdown:
    """Converter of the port's HTML; options as Renderer's:

    ``resolve``: wiki title, anchor -> URL, or None to keep only the link's text.
    ``page_title``: the page being rendered, for self links and "#anchor" links.
    ``preformat``: <pre> blocks of space-led lines as code fences (off: as text lines).
    ``emphasis``: bold/italic as ``**``/``*`` (off: text only).
    ``inline``: the result continues a line, so a <br> is a plain newline.
    ``hard_breaks``: a <br> as a Markdown hard break; off for plain text, where it is a newline.
    ``code_links``: links in <pre> blocks kept as wikitext.CODE_LINK marks for the site.
    ``plain``: no Markdown links and no emphasis (plain()/plain_lines() use it).

    ``unknown`` counts templates the wiki would show as red links (missing from the pages given to the port)."""

    def __init__(self, resolve: Optional[LinkResolver] = None, page_title: str = "", preformat: bool = True,
                 emphasis: bool = True, inline: bool = False, hard_breaks: bool = True, code_links: bool = False,
                 plain: bool = False):
        self.resolve = resolve or (lambda title, anchor: None)
        self.page_title = page_title
        self.preformat = preformat
        self.emphasis = emphasis and not plain
        self.inline = inline
        self.hard_breaks = hard_breaks
        self.code_links = code_links
        self.plain_mode = plain
        self.unknown: Counter = Counter()
        self._hard = hard_breaks and not inline
        self._in_cell = False
        self._blocks: list[list[str]] = []
        self._codes: list[str] = []
        self._refs: dict[str, Element] = {}

    # ---- public API -------------------------------------------------------------------------

    def md(self, html: Union[str, Element]) -> str:
        """The finished Markdown of an HTML fragment or page."""
        root = parse_html(html) if isinstance(html, str) else html
        self._blocks, self._codes = [], []
        self._refs = {li.attrs["id"]: li for li in root.find(lambda e: e.tag == "li" and
                                                              e.attrs.get("id", "").startswith("cite_note-"))}
        text = self._join(self._flow(root.children))
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def plain_lines(self, html: Union[str, Element]) -> str:
        """Text without links or emphasis, keeping line breaks (JSON fields)."""
        r = HtmlMarkdown(None, self.page_title, preformat=False, hard_breaks=False, plain=True)
        out = r.md(html)
        self.unknown.update(r.unknown)
        return out

    def plain(self, html: Union[str, Element]) -> str:
        """A single line of text (syntax lines, types)."""
        return re.sub(r"\s+", " ", self.plain_lines(html)).strip()

    # ---- blocks -----------------------------------------------------------------------------

    @staticmethod
    def _join(blocks: list[str]) -> str:
        return "\n\n".join(b for b in blocks if b.strip())

    def _skip(self, el: Element) -> bool:
        if el.tag in SKIP_TAGS or el.attrs.get("id") == "toc" or el.classes & SKIP_CLASSES:
            return True
        if any(c.startswith(("navbox", "mw-gallery")) for c in el.classes):
            return True
        return bool(re.search(r"display:\s*none", el.attrs.get("style", "")))

    def _is_block(self, el: Element) -> bool:
        if el.tag == "code" and re.search(r"display:\s*block", el.attrs.get("style", "")):
            return True
        return el.tag in BLOCK_TAGS and not _is_ball(el)

    def _flow(self, nodes) -> list[str]:
        """Finished Markdown blocks of a run of nodes: inline content gathers into paragraphs."""
        out: list[str] = []
        buf: list[str] = []

        def flush():
            if buf:
                out.extend(self._paragraphs("".join(buf)))
                buf.clear()

        for n in nodes:
            if isinstance(n, str):
                buf.append(self._text(n))
            elif self._skip(n):
                continue
            elif self._is_block(n):
                flush()
                out.extend(self._block(n))
            else:
                buf.append(self._inline(n))
        flush()
        return out

    def _block(self, el: Element) -> list[str]:
        tag, cls = el.tag, el.classes
        if re.fullmatch(r"h[1-6]", tag):
            return self._heading(int(tag[1]), self._line(el.children))
        if tag in ("ul", "ol"):
            return [self._list(el)]
        if tag == "dl":
            return self._note(el) if "command_description" in cls else self._dl(el)
        if tag == "table":
            return self._table(el)
        if tag == "hr":
            return ["---"]
        if tag == "pre":
            if not self.preformat:
                return self._paragraphs("".join(self._text(c) if isinstance(c, str) else self._inline(c)
                                                for c in el.children).replace("\n", BR))
            return self._code_block(self._code_text(el, links=self.code_links and not self.plain_mode), "")
        if tag == "code":  # <code style="display: block">
            return self._code_block(self._code_text(el), "")
        if tag == "blockquote":
            return [_quote(self._join(self._flow(el.children)))]
        if tag == "div":
            for name, lang in HIGHLIGHT_BLOCKS.items():
                if name in cls:
                    return self._code_block(self._code_text(el), lang)
            if "mw-highlight" in cls:
                return self._code_block(self._code_text(el), self._highlight_lang(cls))
            if "biki-messagebox" in cls:
                return self._messagebox(el)
            if "biki-tabs" in cls:
                return self._tabs(el)
            if "dablink" in cls:  # {{Hatnote}}: "ⓘ" and an italic line
                kids = list(el.children)
                if kids and isinstance(kids[0], str):
                    kids[0] = kids[0].lstrip().lstrip("ⓘ")
                return self._flow(kids)
            if "flex" in el.attrs.get("style", ""):
                titled = self._arg_title(el)
                if titled:
                    return titled
        return self._flow(el.children)

    def _paragraphs(self, text: str) -> list[str]:
        """Inline content -> paragraphs, with the blocks found inside it (slots) in between."""
        out: list[str] = []
        pos = 0
        for m in _SLOT.finditer(text):
            out += self._para(text[pos:m.start()])
            out += self._blocks[int(m.group(1))]
            pos = m.end()
        out += self._para(text[pos:])
        return out

    def _para(self, text: str) -> list[str]:
        """One paragraph's inline Markdown: whitespace as HTML shows it, <br> as breaks, line starts escaped.
        One <br> is a hard break (a "\\" at the end of the line), a run of them a new paragraph, and one at the
        start or end shows nothing."""
        text = re.sub(r"[ \t\r]*\n[ \t\r\n]*", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(f"^[ \t\n{BR}]+|[ \t\n{BR}]+$", "", text)
        out = []
        for part in re.split(f"{BR}[ \t\n]*(?:{BR}[ \t\n]*)+", text):
            part = re.sub(f"{BR}[ \t]*\n?[ \t]*", "\\\\\n" if self._hard else "\n", part).strip(" \t\n")
            if not part:
                continue
            if self._hard:  # nothing in a paragraph starts a list, heading or quote; "![" is no image
                part = _LINE_MARK.sub(lambda m: m.group(1) + (re.sub(r"[.)]", r"\\\g<0>", m.group(2))
                                                              if m.group(2)[0].isdigit() else "\\" + m.group(2)),
                                      part)
            if not self.plain_mode:
                part = part.replace("![", "\\![")
            part = part.replace(_STAR, "*")
            out.append(_CODE_SLOT.sub(lambda m: self._codes[int(m.group(1))], part))
        return out

    def _line(self, nodes) -> str:
        """Inline content as one line (headings, table titles)."""
        hard, self._hard = self._hard, False
        try:
            text = " ".join(self._paragraphs("".join(self._text(n) if isinstance(n, str) else
                                                     ("" if self._skip(n) else self._inline(n)) for n in nodes)))
        finally:
            self._hard = hard
        return re.sub(r"\s*\n\s*", " ", text).strip()

    def _heading(self, level: int, title: str) -> list[str]:
        if not title:
            return []
        # a trailing "#" would read as the closing sequence of a Markdown heading
        title = re.sub(r"(#+)\s*$", lambda m: "\\#" * len(m.group(1)), title)
        return [f"{'#' * min(level + 1, 6)} {title}"]

    def _code_block(self, code: str, lang: str) -> list[str]:
        code = code.strip("\n").rstrip()
        if not code.strip():
            return []
        code = code.replace("\t", "    ")
        if self._in_cell and "\n" not in code:  # a fence cannot live in a table cell; one line reads as code
            return [_inline_code(code)]
        fence = "````" if "```" in code else "```"
        return [f"{fence}{lang}\n{code}\n{fence}"]

    @staticmethod
    def _highlight_lang(cls: set[str]) -> str:
        return next((c[len("mw-highlight-lang-"):] for c in cls if c.startswith("mw-highlight-lang-")), "")

    def _code_text(self, el: Element, links: bool = False) -> str:
        """The text of code; links in <pre> become CODE_LINK marks with ``links``."""
        out = []
        for c in el.children:
            if isinstance(c, str):
                out.append(c)
            elif c.tag == "br":
                out.append("\n")
            elif c.tag in SKIP_TAGS:
                continue
            elif c.tag == "a" and links:
                text = c.text()
                url = self._link_url(c)
                out.append(CODE_LINK[0] + text + CODE_LINK[1] + url + CODE_LINK[2] if url and text else text)
            else:
                out.append(self._code_text(c, links))
        return "".join(out)

    def _list(self, el: Element) -> str:
        marker = "1. " if el.tag == "ol" else "- "
        pad = " " * len(marker)
        items = []
        for li in el.children:
            if isinstance(li, str) or self._skip(li):
                continue
            blocks = self._flow(li.children if li.tag == "li" else [li])
            if not blocks:
                continue
            body = blocks[0]
            for b in blocks[1:]:  # a nested list continues the item, anything else is a paragraph of it
                body += ("\n" if re.match(r"(?:- |1\. )", b) else "\n\n") + b
            lines = body.split("\n")
            items.append("\n".join([marker + lines[0]] + [pad + ln if ln.strip() else "" for ln in lines[1:]]))
        return "\n".join(items)

    def _dl(self, el: Element) -> list[str]:
        """; term : definition. A term with a one-line definition reads "**Term:** definition" (the config
        references' "; Type: String", the {{Tool}} infobox); otherwise the term is a bold line of its own."""
        out: list[str] = []
        kids = [c for c in el.children if isinstance(c, Element) and not self._skip(c)]
        i = 0
        while i < len(kids):
            c = kids[i]
            if c.tag == "dt":
                term = self._line(c.children)
                nxt = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tag == "dd" else None
                body = self._flow(nxt.children) if nxt is not None else []
                if not term:
                    out += body
                elif len(body) == 1 and "\n" not in body[0] and not re.match(r"(?:- |1\. |```|\|)", body[0]):
                    label = term if term.endswith((":", "?")) else term + ":"
                    out.append(self._bold(label) + " " + body[0])
                else:
                    out += [self._bold(term)] + body
                i += 2 if nxt is not None else 1
            else:
                out += self._flow(c.children)
                i += 1
        return out

    def _bold(self, text: str) -> str:
        return f"**{text}**" if self.emphasis else text

    def _table(self, el: Element) -> list[str]:
        rows: list[list[tuple[str, bool, int, int]]] = []

        def span(cell: Element, attr: str) -> int:
            m = re.match(r"\s*(\d+)", cell.attrs.get(attr, ""))
            return max(1, min(int(m.group(1)), 50)) if m else 1

        def walk(node: Element):
            for c in node.elements():
                if c.tag == "tr":
                    rows.append([cell(x) for x in c.elements() if x.tag in ("td", "th")])
                elif c.tag in ("thead", "tbody", "tfoot"):
                    walk(c)

        def cell(c: Element) -> tuple[str, bool, int, int]:
            hard, in_cell = self._hard, self._in_cell
            self._hard, self._in_cell = False, True
            try:
                text = self._join(self._flow(c.children))
            finally:
                self._hard, self._in_cell = hard, in_cell
            text = text.replace("\n\n", "<br>").replace("\n", "<br>").replace("|", "\\|")
            return text.strip(), c.tag == "th", span(c, "rowspan"), span(c, "colspan")

        walk(el)
        captions = [self._line(c.children) for c in el.elements("caption")]
        grid = _unspan([r for r in rows if r])
        if not grid:
            return [c for c in captions if c]
        width = max(len(r) for r in grid)
        header = grid[0] if all(is_th for _, is_th in grid[0]) else [("", True)] * width
        body = grid[1:] if header is grid[0] else grid

        def line(r):
            vals = [c for c, _ in r] + [""] * (width - len(r))
            return "| " + " | ".join(vals) + " |"

        table = "\n".join([line(header), "|" + "---|" * width] + [line(r) for r in body])
        return [self._bold(c) for c in captions if c] + [table]

    # ---- the wiki's templates ---------------------------------------------------------------

    def _messagebox(self, el: Element) -> list[str]:
        """{{Feature|type|text}} and {{Messagebox/BI}}: an icon <div>, then the text <div>."""
        cls = el.classes
        kids = [c for c in el.elements() if not self._skip(c)]
        icon, body_els = (kids[0], kids[1:]) if len(kids) > 1 else (None, kids)
        body = self._join(self._flow(body_els))
        ftype = next((c[len("feature-"):] for c in cls if c.startswith("feature-")), None)
        colour = re.search(r"background-color:\s*([^;\s]+)", el.attrs.get("style", ""))
        if ftype is None and "messagebox-bi" not in cls and colour and colour.group(1).lower() in MAINTENANCE_COLOURS:
            return []
        if ftype is None or ftype == "quote":
            return [_quote(body)]
        if ftype in FEATURE_ALERT:
            return [_quote(body, FEATURE_ALERT[ftype])]
        gvi = icon.find(lambda e: "gvi2" in e.classes) if icon is not None else []
        if gvi:
            return [_quote(body, "NOTE", "Since " + self._gvi(gvi[0]))]
        label = GAME_NAMES.get(ftype.lower())
        if label is None and icon is not None:  # the icon's caption, e.g. "Advanced Helicopter Flight Model"
            text = re.sub(r"\s+", " ", icon.text()).strip()
            label = text if re.search(r"\w{2}", text) and not text.lower().startswith(FILE_PREFIXES) else None
        return [_quote(body, "NOTE", label if label and body and not body.startswith("This ") else None)]

    def _tabs(self, el: Element) -> list[str]:
        """{{Tabview}}: the titles, then the contents; each content under its title in bold."""
        titles = [c for c in el.elements() if "biki-tab-title" in c.classes]
        contents = [c for c in el.elements() if "biki-tab-content" in c.classes]
        out: list[str] = []
        emphasis, self.emphasis = self.emphasis, False
        try:
            names = [self._line(t.children) for t in titles]
        finally:
            self.emphasis = emphasis
        for i, content in enumerate(contents):
            if i < len(names) and names[i]:
                out.append(self._bold(names[i]))
            out += self._flow(content.children)
        return out

    def _arg_title(self, el: Element) -> Optional[list[str]]:
        """{{ArgTitle|3|Name|{{GVI|arma3|1.00}}}}: a game version beside a heading -> "Name (Arma 3 v1.00)"."""
        heads = el.find(lambda e: re.fullmatch(r"h[1-6]", e.tag) is not None)
        if len(heads) != 1:
            return None
        gvis = el.find(lambda e: "gvi2" in e.classes)
        if not gvis:
            return None
        title = self._line(heads[0].children)
        versions = ", ".join(self._gvi(g) for g in gvis)
        return self._heading(int(heads[0].tag[1]), f"{title} ({versions})" if title else "")

    def _note(self, el: Element) -> list[str]:
        """A user note ({{Note}}): author, date, text -> "> **Author** (2020-01-01):" and the text."""
        author = next((c for c in el.elements("dt") if "noteauthor" in c.classes), None)
        user = ""
        if author is not None:
            user = re.sub(r"\s+", " ", "".join(c if isinstance(c, str) else c.text() for c in author.children
                                               if isinstance(c, str) or c.tag != "small")).strip()
        head = self._bold(user or "Anonymous")
        m = _NOTE_ID.search(el.attrs.get("id", ""))
        if m:
            ts = m.group(1)
            head += f" ({ts[0:4]}-{ts[4:6]}-{ts[6:8]})"
        text = next((c for c in el.elements("dd") if "note" in c.classes), None)
        body = self._join(self._flow(text.children)) if text is not None else ""
        return [_quote(head + ":\n\n" + body)]

    def _gvi(self, el: Element) -> str:
        """{{GVI|arma3|2.00}}: class "gvi2 gvi-arma3" and a "version" span -> "Arma 3 v2.00"."""
        game = next((c[len("gvi-"):] for c in el.attrs.get("class", "").split() if c.startswith("gvi-")), "")
        version = next((v.text().strip() for v in el.find(lambda e: "version" in e.classes)), "")
        name = game_name(game)
        return f"{name} v{version}" if version else name

    # ---- inline -----------------------------------------------------------------------------

    def _text(self, s: str) -> str:
        # a backslash of the wiki text ("P:\") is literal; Markdown would read it as an escape or a line break
        if self.hard_breaks and self.emphasis:
            s = _MD_BACKSLASH.sub(r"\\\\", s)
        return s

    def _inline_children(self, el: Element) -> str:
        return "".join(self._text(c) if isinstance(c, str) else ("" if self._skip(c) else self._inline(c))
                       for c in el.children)

    def _code(self, code: str) -> str:
        md = _inline_code(code)
        if not md:
            return ""
        self._codes.append(md)
        return f"\ue013{len(self._codes) - 1}\ue014"

    def _inline(self, el: Element) -> str:
        tag, cls = el.tag, el.classes
        if self._skip(el):
            return ""
        if self._is_block(el):  # a block inside inline content: finished on its own, put back in a slot
            self._blocks.append(self._block(el))
            return f"\ue011{len(self._blocks) - 1}\ue012"
        if tag == "br":
            return BR
        if _is_ball(el):
            return "●"
        if tag == "a":
            return self._link(el)
        if tag in ("b", "strong", "i", "em"):
            inner = self._inline_children(el)
            if not inner.strip() or not self.emphasis:
                return inner
            mark = _STAR * (2 if tag in ("b", "strong") else 1)
            core = inner.strip()
            start = inner.index(core[0])
            return f"{inner[:start]}{mark}{core}{mark}{inner[start + len(core):]}"
        if tag in ("s", "del", "strike"):
            return f"~~{self._inline_children(el)}~~"
        if tag in INLINE_CODE_TAGS or (tag == "span" and (cls & set(HIGHLIGHT_BLOCKS) or "code-comment" in cls)):
            return self._code(el.text())
        if tag == "kbd":
            text = el.text().strip()
            return text if self.plain_mode or not text else f"<kbd>{text}</kbd>"
        if "gvi2" in cls:
            return self._gvi(el)
        if "icon2" in cls and el.attrs.get("title"):  # {{Icon|localArgument}}: letters drawn in CSS
            return el.attrs["title"]
        if tag == "sup" and "reference" in cls:
            return self._reference(el)
        if tag == "sup" and "sic" in cls:
            return " [sic]"
        return self._inline_children(el)

    def _reference(self, sup: Element) -> str:
        """<ref>: " (ref: text)" in place of the number, the note's text taken from the reference list."""
        a = next(iter(sup.elements("a")), None)
        note = self._refs.get(a.attrs.get("href", "")[1:]) if a is not None else None
        if note is None:
            return ""
        texts = note.find(lambda e: "reference-text" in e.classes)
        inner = "".join(self._inline_children(t) for t in texts).strip()
        return f" (ref: {inner})" if inner else ""

    def _link_url(self, a: Element) -> Optional[str]:
        """The URL a link gets in the output: external URLs as they are, wiki pages through the resolver."""
        href = a.attrs.get("href")
        if href is None:
            return self.resolve(self.page_title, "") if "mw-selflink" in a.classes else None
        target = link_target(href)
        if target is None:
            return href if re.match(r"(?:https?:)?//", href) else None
        title, anchor = target
        if title.lower().startswith(FILE_PREFIXES):
            return None
        # the wiki writes a heading's spaces as "_" in its anchor; a leading "_" ("_this") is part of the name
        lead = re.match(r"_*", anchor).group(0)
        return self.resolve(title or self.page_title, lead + anchor[len(lead):].replace("_", " "))

    def _link(self, a: Element) -> str:
        text = self._inline_children(a)
        href = a.attrs.get("href")
        target = link_target(href) if href is not None else None
        if target is not None:
            title = target[0]
            if title.lower().startswith(FILE_PREFIXES):
                # an image the port shows as a link: its caption only ({{Icon|checked}}), never the file name
                if text.strip().lower().startswith(FILE_PREFIXES):
                    return ""
                return FILE_CAPTIONS.get(text.strip().lower(), text)
            if title.startswith("Template:") and "new" in a.classes:
                self.unknown["template:" + title[len("Template:"):]] += 1
        if self.plain_mode:
            return text
        if href is not None and target is None and re.match(r"(?:https?:)?//", href):
            if "autonumber" in a.classes:  # [http://site] shows "[1]" on the wiki
                return f"<{href}>"
            if "free" in a.classes:
                return href
            return f"[{text.strip()}]({href})" if text.strip() else f"<{href}>"
        url = self._link_url(a)
        lead, core, trail = _split_ws(text)  # [[Group | group]]: the spaces stay outside the brackets
        if not core:  # an icon-only link: the anchor or the page's name
            if target is None:
                return ""
            core = target[1].replace("_", " ") or target[0].split(":")[-1]
        if not url:
            return lead + core + trail
        return lead + "[" + re.sub(r"([\[\]])", r"\\\1", core) + f"]({url})" + trail


def _is_ball(el: Element) -> bool:
    """{{Colorball}}: an empty inline-block <div> drawn as a coloured circle by CSS."""
    return not el.children and "border-radius: 50%" in el.attrs.get("style", "")


def html_to_md(html: str, resolve: Optional[LinkResolver] = None, **options) -> str:
    """Markdown of the port's HTML; ``options`` as HtmlMarkdown's."""
    return HtmlMarkdown(resolve, **options).md(html)


def html_to_plain(html: str, page_title: str = "", lines: bool = False) -> str:
    """Plain text of the port's HTML: one line, or with ``lines`` its line breaks kept."""
    r = HtmlMarkdown(None, page_title)
    return r.plain_lines(html) if lines else r.plain(html)

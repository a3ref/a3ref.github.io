"""Convert BI Community Wiki wikitext to Markdown.

Covers the subset of MediaWiki markup and wiki templates that actually occur on
the mirrored pages. Anything it does not know is listed in report.json (unknown-template, unknown-tag, markup).
"""
from __future__ import annotations

import html
import re
from collections import Counter
from typing import Callable, Optional

import mwparserfromhell as mw
from mwparserfromhell.nodes import (
    Argument,
    Comment,
    ExternalLink,
    Heading,
    HTMLEntity,
    Tag,
    Template,
    Text,
    Wikilink,
)

# Returns a URL for a wiki page title (+ optional anchor), or None to render the link as plain text.
LinkResolver = Callable[[str, str], Optional[str]]

GAME_NAMES = {
    "arma": "Arma",
    "ofp": "Operation Flashpoint",
    "arma0": "Arma: Cold War Assault",
    "ofpr": "Operation Flashpoint: Resistance",
    "ofpe": "Operation Flashpoint: Elite",
    "arma1": "Armed Assault",
    "arma2": "Arma 2",
    "arma2oa": "Arma 2: Operation Arrowhead",
    "tkoh": "Take On Helicopters",
    "arma3": "Arma 3",
    "arma3contact": "Arma 3 Contact",
    "arma3zeus": "Arma 3 Zeus",
    "armar": "Arma Reforger",
    "arma4": "Arma 4",
    "tkom": "Take On Mars",
    "dayz": "DayZ",
    "vbs1": "VBS1",
    "vbs2": "VBS2",
}

GAME_SHORT = {"ofp": "OFP", "arma0": "Arma:CWA", "ofpe": "OFP:E", "arma1": "ArmA", "arma2oa": "Arma 2:OA"}

ICON_TEXT = {
    "localargument": "Local Argument",
    "globalargument": "Global Argument",
    "localeffect": "Local Effect",
    "globaleffect": "Global Effect",
    "serverexec": "Server Execution",
    "checked": "✓",
    "unchecked": "✗",
}

FEATURE_ALERT = {"informative": "NOTE", "important": "IMPORTANT", "warning": "WARNING", "obsolete": "CAUTION"}

FEATURE_DEFAULT_TEXT = {
    "afm": "For this command to have any effect, the Advanced Flight Model (AFM) has to be enabled. "
    "AFM status can be checked with [[difficultyEnabledRTD]].",
    "arma3contact": "This content is exclusive to the [[Arma 3 Contact]] Expansion.",
    "arma3oldman": "This function is used by the [[Arma 3 Apex: Old Man]] content. "
    "It might only work properly inside this scenario.",
    "eden editor": "This is an [[:Category:Eden Editor|Eden Editor]] feature.",
}

# Maintenance/navigation templates that carry no reference content.
DROP_TEMPLATES = {"wiki", "tabview/gametitle", "template:tabview/gametitle", "clear", "toc", "displaytitle",
                  "table/rvscripting", "clarify", "topmenu"}

# Infobox-style templates rendered as one "**Label:** value" line per parameter; labels for the names that
# do not read well as written.
FIELD_TEMPLATES = {"tool", "terrainprocessormanual"}
FIELD_LABELS = {"seealso": "See also", "taskparameters": "Task parameters", "dll": "DLL", "heightmap": "Height map",
                "objectprototypeparameters": "Object prototype parameters"}
FIELD_SKIP = {"image", "gallery"}
# {{TerrainProcessorManual|task|dll|geometry|heightMap|...}} also takes these four positionally
TERRAIN_TASK_FIELDS = ["task", "dll", "geometry", "heightMap"]

MAGIC_WORDS = re.compile(r"__(NOTOC|TOC|FORCETOC|NOEDITSECTION|NEWSECTIONLINK|NOGALLERY|HIDDENCAT|INDEX|NOINDEX)__")

CODE_TAGS = {"sqf", "sqs", "syntaxhighlight", "source", "pre", "cpp", "hpp", "ext", "enforce"}
INLINE_CODE_TAGS = {"code", "tt", "var", "t", "kbd", "samp"}
DROP_TAGS = {"img", "gallery", "references", "imagemap", "wbr"}

_SLOT = re.compile("(\\d+)")
BR = ""  # <br>, a line break only after the preformatted-line pass: "<br> text" does not start a line on the wiki
BLOCK = ""  # marks where a block element such as <div> was, until the preformatted-line pass is done
# MediaWiki does not preformat a space-led line that opens or closes a block element
BLOCK_TAGS = {"div", "table", "tr", "td", "th", "p", "pre", "blockquote", "ul", "ol", "li", "dl", "dt", "dd", "center",
              *(f"h{i}" for i in range(1, 7))}
_BLOCK_TAG = re.compile(rf"</?({'|'.join(BLOCK_TAGS)})\b|{BLOCK}", re.I)
STAR = ""  # emphasis marker, hidden from the wiki-list pass and swapped for "*" at the very end
_LIST_LINE = re.compile(r"^([*#:;]+)[ \t]*(.*)$")
# The wiki's <sqf> highlighter turns piped [[target|text]] into links; plain [[x]] is valid SQF (nested arrays).
_CODE_LINK = re.compile(r"\[\[([A-Za-z][^\[\]|\n,\"]*)\|([^\[\]\n]+)\]\]")


_CODE_TEMPLATE = re.compile(r"\{\{\s*([^{}|\n]+?)\s*(?:\|([^{}\n]*))?\}\}")
_TABLE_ESCAPED = re.compile(r"(?:^|\n)[ \t:]*\{\{\{!\}\}")


def _code_template(m: re.Match) -> str:
    name, args = m.group(1).strip().lower(), (m.group(2) or "").split("|")
    if name == "=":
        return "="
    if name == "!":
        return "|"
    if name in GAME_NAMES:
        return GAME_NAMES[name]
    if name == "name":
        return game_name(args[0], short=len(args) > 1 and args[1].strip() == "short")
    if name == "gvi":
        return game_name(args[0]) + (f" v{args[1].strip()}" if len(args) > 1 else "")
    if name == "hl":
        return re.sub(r"^\s*c\s*=\s*", "", args[0])  # {{hl|c= a = 1}}
    if name == "link":
        return args[-1]
    if name == "cc":
        return "// " + args[0]
    if name == "color":
        return args[-1]
    return m.group(0)


def clean_code(code: str) -> str:
    """Code inside <sqf> etc. is mostly raw, but the wiki still expands links and a few templates."""
    code = _CODE_LINK.sub(r"\2", code)
    code = re.sub(r"</?nowiki\s*/?>", "", code, flags=re.I)
    return _CODE_TEMPLATE.sub(_code_template, code)


def parse_wikitext(text: str) -> mw.wikicode.Wikicode:
    # Bold/italic are converted per line by _styles(): mwparserfromhell's own style parsing
    # can run across template parameters and swallow "|p2=" etc.
    return mw.parse(text, skip_style_tags=True)


def preprocess(wikitext: str) -> str:
    """Fix markup that mwparserfromhell reads differently from MediaWiki."""
    # tables indented with ':' are still tables
    wikitext = re.sub(r"(?m)^:+[ \t]*(\{\||\{\{\{!\}\})", r"\1", wikitext)
    return _escape_unknown_tags(wikitext)


# Tags the wiki (MediaWiki 1.39: Sanitizer's HTML tags, the parser's own, the extension tags listed by
# meta=siteinfo) treats as markup; any other <name> is plain text there, e.g. "<string>", the XML of a config
# format or Arma structured text, while mwparserfromhell would read it as a tag and lose it.
KNOWN_TAGS = {
    "abbr", "b", "bdi", "bdo", "big", "blockquote", "br", "caption", "center", "cite", "code", "data", "dd", "del",
    "dfn", "div", "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "ins", "kbd", "li", "mark",
    "ol", "p", "pre", "q", "rb", "rp", "rt", "rtc", "ruby", "s", "samp", "small", "span", "strike", "strong", "sub",
    "sup", "table", "td", "th", "time", "tr", "tt", "u", "ul", "var", "wbr",
    "nowiki", "includeonly", "noinclude", "onlyinclude",
    "gallery", "indicator", "langconvert", "dynamicpagelist", "templatedata", "source", "syntaxhighlight", "youtube",
    "aovideo", "aoaudio", "wegame", "tangler", "gtrailer", "nicovideo", "sqf", "sqs", "enforce", "spoiler",
    "categorytree", "charinsert", "section", "ref", "references", "math", "ce", "chem",
}
_RAW_REGIONS = re.compile(r"(?s)<!--.*?(?:-->|$)|<(nowiki|pre|sqf|sqs|syntaxhighlight|source|cpp|hpp|ext|enforce)\b.*?</\1\s*>")
_TAG_START = re.compile(r"<(/?)([A-Za-z][\w:.-]*)")


def _escape_unknown_tags(wikitext: str) -> str:
    def escape(text: str) -> str:
        return _TAG_START.sub(lambda m: m.group(0) if m.group(2).lower() in KNOWN_TAGS else "&lt;" + m.group(0)[1:], text)

    out, pos = [], 0
    for m in _RAW_REGIONS.finditer(wikitext):  # code and comments are left as they are
        out += [escape(wikitext[pos:m.start()]), m.group(0)]
        pos = m.end()
    out.append(escape(wikitext[pos:]))
    return "".join(out)


def close_tables(wikitext: str) -> str:
    """MediaWiki closes a table left open at the end of a page or template parameter; mwparserfromhell would
    leave it as text."""
    opened = len(re.findall(r"(?m)^[ \t:]*\{\|", wikitext))
    closed = len(re.findall(r"(?m)^[ \t]*\|\}", wikitext))
    return wikitext + "\n|}" * (opened - closed) if opened > closed else wikitext


def game_name(code: str, short: bool = False) -> str:
    key = re.sub(r"[ :/-]", "", code.strip().lower())
    if short and key in GAME_SHORT:
        return GAME_SHORT[key]
    return GAME_NAMES.get(key, code.strip())


def _norm(name) -> str:
    return str(name).strip()


class Renderer:
    """Stateless-per-call converter; ``unknown`` collects templates/tags it had no rule for."""

    def __init__(self, resolve: Optional[LinkResolver] = None, page_title: str = "", preformat: bool = True,
                 emphasis: bool = True, inline: bool = False, hard_breaks: bool = True, code_links: bool = False):
        self.resolve = resolve or (lambda title, anchor: None)
        self.page_title = page_title
        self.preformat = preformat  # off where the result is a single line or already code
        self.emphasis = emphasis  # off for the text of inline code, where "**" would show as is
        self.inline = inline  # the text continues a line (see _finish)
        # <br> as a Markdown hard break; off for plain text (JSON fields, syntax lines), where it is a newline
        self.hard_breaks = hard_breaks
        # links in preformatted lines kept as CODE_LINK marks for the site (Markdown code cannot hold links)
        self.code_links = code_links
        self.unknown: Counter = Counter()

    # ---- public API -------------------------------------------------------------------------

    def md(self, wikitext) -> str:
        """Render wikitext (str or Wikicode) to a finished Markdown string."""
        src = str(wikitext)
        if "{{!}}" in src and _TABLE_ESCAPED.search(src):
            # Tables written with {{!}} so they survive inside template parameters.
            code = parse_wikitext(close_tables(src.strip().replace("{{!}}", "|")))
        else:
            code = wikitext if isinstance(wikitext, mw.wikicode.Wikicode) else parse_wikitext(src)
        slots: list[str] = []
        text = self._nodes(code.nodes, slots)
        return self._finish(text, slots)

    def plain(self, wikitext) -> str:
        """Render to a single-line plain string (no links, no emphasis) - for syntax lines and types."""
        return re.sub(r"\s+", " ", self.plain_lines(wikitext)).strip()

    def plain_lines(self, wikitext) -> str:
        """Like :meth:`plain` but keeps line breaks."""
        r = Renderer(None, self.page_title, preformat=False, hard_breaks=False)
        s = r.md(wikitext)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
        self.unknown.update(r.unknown)
        return s.strip()

    # ---- rendering --------------------------------------------------------------------------

    def _slot(self, slots: list[str], content: str) -> str:
        slots.append(content)
        return f"{len(slots) - 1}"

    def _finish(self, text: str, slots: list[str], inline: bool = False) -> str:
        """``inline``: the piece continues a line, as a template argument inside <code> or a table cell's text
        after its "|" does, so its first line is no line start: {{hl|*/*}} and | * (numpad) are no lists."""
        text = MAGIC_WORDS.sub("", text)
        text = self._preformatted(text, slots)
        # lists and emphasis work on source lines: a <br> is no line start, and ''...<br>...'' is one span
        text = self._lists(text, skip_first=inline or self.inline)
        text = "\n".join(_styles(line) for line in text.split("\n")).replace(STAR, "*" if self.emphasis else "")
        text = self._breaks(text, slots, hard=self.hard_breaks and not (inline or self.inline)).replace(BLOCK, "")
        # We never emit images, so "![" is always text such as SQF "!" before a link ("![[alive]]" -> "!alive").
        # Code is still in slots here, so it is not affected.
        text = text.replace("![", "\\![")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        while _SLOT.search(text):
            text = _SLOT.sub(lambda m: slots[int(m.group(1))], text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _breaks(self, text: str, slots: list[str], hard: bool) -> str:
        """<br> -> Markdown. A plain newline in Markdown is only a space, so one <br> is a hard break (a "\\" at the
        end of the line), several are a new paragraph, and one at the end of a paragraph shows nothing. Text right
        after it does not start a line on the wiki: "<br>* note" is no list there, so the mark is escaped."""
        if not hard or BR not in text:
            return text.replace(BR, "\n")

        def block_follows(rest: str) -> bool:
            m = _SLOT.match(rest.lstrip(" \t"))
            return bool(_MD_BLOCK.match(rest)) or bool(m and slots[int(m.group(1))].startswith("\n"))

        def sub(m: re.Match) -> str:
            newline, indent, mark = m.group(1), m.group(2), m.group(3) or ""
            rest = text[m.end(2):].replace(BLOCK, "")  # the mark of a closing </div> is no text
            if not rest.strip() or rest.startswith("\n"):  # the end of the text or of a paragraph
                return newline + indent + mark
            if m.group(0).count(BR) > 1:
                return "\n\n" + indent + mark
            if newline:  # <br> at the end of a source line: a list, heading or table on the next line stays one
                return newline + indent + mark if block_follows(rest) else "\\\n" + indent + mark
            if block_follows(rest[len(mark):]) and not mark:
                return "\n\n"
            return "\\\n" + indent + (re.sub(r"[.)]", r"\\\g<0>", mark, count=1) if mark[:1].isdigit() else
                                      ("\\" + mark if mark else ""))

        return _BREAK_RUN.sub(sub, text)

    def _preformatted(self, text: str, slots: list[str]) -> str:
        """Lines starting with a space are a preformatted block on the wiki, often config or console snippets.
        The first line of a piece is not checked: it follows a template parameter's "=" or a table cell's "|"."""
        if not self.preformat or "\n " not in text:
            return text

        def is_pre(line: str) -> bool:
            body = line.lstrip(" ")
            if not line.startswith(" ") or not body.strip() or _BLOCK_TAG.search(line):
                return False
            m = _SLOT.match(body)  # a line starting with a table, heading or note is not preformatted
            return not (m and slots[int(m.group(1))].startswith("\n"))

        lines = text.split("\n")
        out, block = [lines[0]], []

        def flush():
            if block:
                code = "\n".join(_pre_line(line, slots, self.code_links) for line in block)
                fence = "````" if "```" in code else "```"
                out.append(self._slot(slots, f"\n\n{fence}\n{_dedent(code)}\n{fence}\n\n"))
                block.clear()

        i = 1
        while i < len(lines):
            line = lines[i]
            if is_pre(line):
                block.append(line[1:])
            elif block and not line.strip():
                # a blank line only ends the block if no preformatted line follows
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and is_pre(lines[j]):
                    block.extend([""] * (j - i))
                    i = j
                    continue
                flush()
                out.append(line)
            else:
                flush()
                out.append(line)
            i += 1
        flush()
        return "\n".join(out)

    def _block(self, code, slots: list[str], inline: bool = False) -> str:
        """Render a nested piece as an independent, finished Markdown block (``inline``: see _finish)."""
        inner: list[str] = []
        nodes = code.nodes if hasattr(code, "nodes") else parse_wikitext(str(code)).nodes
        return self._finish(self._nodes(nodes, inner), inner, inline)

    def _nodes(self, nodes, slots: list[str]) -> str:
        return "".join(self._node(n, slots) for n in nodes)

    def _node(self, node, slots: list[str]) -> str:
        if isinstance(node, Text):
            # a backslash of the wiki text ("P:\", "\Steam\") is literal; Markdown would read it as an escape or,
            # at the end of a line, as a line break. Not in code or plain text, where it already is literal.
            return _MD_BACKSLASH.sub(r"\\\\", node.value) if self.hard_breaks and self.emphasis else node.value
        if isinstance(node, Comment):
            return ""
        if isinstance(node, HTMLEntity):
            return node.normalize()
        if isinstance(node, Wikilink):
            return self._wikilink(node, slots)
        if isinstance(node, ExternalLink):
            url = str(node.url).strip().replace("{{=}}", "=").replace("{{!}}", "|")
            if node.title is None:
                return url if node.brackets is False else f"<{url}>"
            return f"[{self._nodes(node.title.nodes, slots).strip()}]({url})"
        if isinstance(node, Heading):
            return self._heading(node.level, self._block(node.title, slots, inline=True), slots)
        if isinstance(node, Template):
            return self._template(node, slots)
        if isinstance(node, Tag):
            return self._tag(node, slots)
        if isinstance(node, Argument):
            return str(node.default) if node.default is not None else ""
        return str(node)

    def _wikilink(self, node: Wikilink, slots: list[str]) -> str:
        target = self._expand(node.title)
        lower = target.lower()
        if lower.startswith(("category:", "file:", "image:", "media:")):
            return ""  # categorisation / embedded images
        target = target.lstrip(":")
        if node.text is not None:
            text = self._nodes(node.text.nodes, slots).strip()
        else:
            text = target
        page, _, anchor = target.partition("#")
        if not text:  # MediaWiki's pipe trick: [[Page (Game)|]] and [[Page, Detail|]] show "Page"
            name = page.split(":")[-1].strip()
            text = re.sub(r"\s*\([^()]*\)$", "", name) if name.endswith(")") else name.split(",")[0].strip()
            text = text or anchor or target
        fallback = anchor.replace("_", " ") or page.split(":")[-1] or target
        if not page:
            page = self.page_title
        url = self.resolve(page.replace("_", " ").strip(), anchor)
        return self._md_link(text, url, fallback, slots)

    def _md_link(self, text: str, url: Optional[str], fallback: str, slots: list[str]) -> str:
        """[text](url), with brackets in the text escaped and never an empty text (e.g. an icon-only wiki link)."""
        visible = _SLOT.sub(lambda m: slots[int(m.group(1))] if int(m.group(1)) < len(slots) else "", text)
        if not visible.strip():
            text = fallback
        if not url:
            return text
        escaped = re.sub(r"([\[\]])", r"\\\1", text)
        return f"[{escaped}]({url})"

    def _expand(self, code) -> str:
        """Plain text of a link target, which may itself contain templates like {{arma2oa}} or {{=}}."""
        src = str(code).strip()
        if "{{" not in src:
            return src
        return Renderer(None, self.page_title, preformat=False, hard_breaks=False).md(src).replace("`", "")

    def _heading(self, level: int, title: str, slots: list[str]) -> str:
        # In a slot, so the wiki-list pass does not read the leading "#" as a numbered list.
        if not title.strip():
            return ""  # "==== ====" on the wiki: an empty heading carries nothing
        # a trailing "#" would read as the closing sequence of a Markdown heading ("=== # ===" is about the # operator)
        title = re.sub(r"(#+)\s*$", lambda m: "\\#" * len(m.group(1)), title.strip())
        return self._slot(slots, f"\n\n{'#' * min(level + 1, 6)} {title}\n\n")

    def _link_to(self, target: str, text: Optional[str]) -> str:
        if re.match(r"^(https?:)?//", target):
            target = target.split()[0]  # {{Link|http://site.com feedback|text}}: a URL ends at a space
            return f"[{text}]({target})" if text else f"<{target}>"
        target = target.lstrip(":")
        if target.lower().startswith("category:") and not text:
            text = target.split(":", 1)[1]
        page, _, anchor = target.partition("#")
        url = self.resolve((page or self.page_title).replace("_", " ").strip(), anchor)  # "#Section" = this page
        return self._md_link(text or target, url, anchor.replace("_", " ") or target, [])

    # ---- templates --------------------------------------------------------------------------

    def _template(self, t: Template, slots: list[str]) -> str:
        name = _norm(t.name)
        key = name.lower()
        pos = [p for p in t.params if not p.showkey]

        def arg(i: int, default: str = "") -> str:
            return self._nodes(pos[i].value.nodes, slots).strip() if len(pos) > i else default

        def raw(i: int, default: str = "") -> str:
            return str(pos[i].value).strip() if len(pos) > i else default

        if key == "!":
            return "|"
        if key == "=":
            return "="
        if key in ("hl", "cc"):
            # the code is the first argument, or c= when it contains "=": {{hl|c= a = 1}}
            value = t.get("c").value if t.has("c") else (pos[0].value if pos else None)
            code = html.unescape(self._plain_inner(value) if value is not None else "")
            if not code and value is not None and str(value).strip():  # {{hl|&nbsp;}}: the rendering trimmed the space
                code = " "
            if key == "cc":
                code = "// " + code
            return self._slot(slots, _inline_code(code))
        if key == "pagename":
            return self.page_title
        if key in DROP_TEMPLATES:
            return ""
        if key == "n/a":
            return "N/A"
        if key in GAME_NAMES:
            return GAME_NAMES[key]
        if key == "name":
            return game_name(raw(0), short=raw(1).lower() == "short")
        if key == "gvi":
            ver = raw(1)
            return f"{game_name(raw(0))} v{ver}" if ver else game_name(raw(0))
        if key == "link":  # {{Link|target|text}} or {{Link|link= target|text= text}}
            target = t.get("link").value if t.has("link") else (pos[0].value if pos else "")
            text = self._nodes(t.get("text").value.nodes, slots).strip() if t.has("text") else arg(1)
            return self._link_to(self._expand(target), text or None)
        if key == "icon":
            return ICON_TEXT.get(raw(0).lower(), "")
        if key in ("columns",):
            return arg(1)
        if key == "color":
            return arg(1)
        if key == "controls":
            keys = [str(p.value).strip() for p in pos]
            return self._slot(slots, "<kbd>" + "</kbd>+<kbd>".join(keys) + "</kbd>")
        if key == "sic":
            return f"{arg(0)} [sic]"
        if key == "user":
            return raw(0)
        if key == "gamecategory":
            text = t.get("text").value if t.has("text") else None
            if text is not None:
                return self._nodes(text.nodes, slots).strip()
            return " ".join(x for x in (game_name(raw(0)), arg(1)) if x)
        if key == "feature":
            return self._slot(slots, "\n\n" + self._feature(t, pos) + "\n\n")
        if key == "note":
            return self._slot(slots, "\n\n" + self.note_md(parse_note(t, self)) + "\n\n")
        if key == "messagebox":
            return self._slot(slots, "\n\n" + _quote(self._block(pos[0].value, slots)) + "\n\n") if pos else ""
        if key in ("spoiler", "sticky"):
            return arg(0)
        if key == "argtitle":  # {{ArgTitle|3|AnimChanged|{{GVI|arma3|1.00}}}}: one entry of an event handler list
            level = int(raw(0)) if raw(0).isdigit() else 3
            extra = arg(2)
            return self._heading(level, arg(1) + (f" ({extra})" if extra else ""), slots)
        if key == "codecomment":
            return self._slot(slots, _inline_code(html.unescape(self._plain_inner(pos[0].value) if pos else "")))
        if key == "colorball":
            return "●"
        if key == "hatnote":
            return STAR + arg(0) + STAR
        if key.startswith("navbox/"):
            return ""
        if key == "cn":  # "citation needed" mark, optionally around the doubted text
            return arg(0)
        if key == "#link":  # a typo of {{Link}} that the wiki still renders as a link
            return self._link_to(self._expand(raw(0)), arg(1) or None)
        if key == "youtube":  # the title may itself be a link to the video: keep its text only
            title = _MD_LINK.sub(lambda m: m.group(1), arg(1)).strip()
            return self._link_to(f"https://www.youtube.com/watch?v={raw(0)}", title or "YouTube video")
        if key == "messagebox/bi":
            body = "\n\n".join(self._block(p.value, slots) for p in pos)
            return self._slot(slots, "\n\n" + _quote(body) + "\n\n")
        if key in FIELD_TEMPLATES or key.startswith("infobox/"):
            return self._slot(slots, "\n\n" + self._fields(t, key) + "\n\n")
        if key == "ct" or key.startswith("ct/"):
            return self._control_type(t, key.partition("/")[2] or raw(0).lower(), slots)
        if key == "tabview":
            parts = []
            for i in range(1, 100):
                if not t.has(f"title{i}"):
                    break
                title = self._block(t.get(f"title{i}").value, slots)
                content = self._block(t.get(f"content{i}").value, slots) if t.has(f"content{i}") else ""
                parts.append(f"**{title}**\n\n{content}")
            return self._slot(slots, "\n\n" + "\n\n".join(parts) + "\n\n")
        if key == "timeline_item":  # {{Timeline_Item|game||year|date|content}}
            when = ", ".join(x for x in (arg(2), arg(3)) if x)
            return self._slot(slots, f"\n\n**{when}**\n\n" + (self._block(pos[4].value, slots) if len(pos) > 4 else "") + "\n\n")
        if key == "keyboard":  # {{Keyboard|F1= action|colorF1= ...}}: what each key does
            keys = [p for p in t.params if p.showkey and not _norm(p.name).startswith("color") and str(p.value).strip()]
            lines = [f"- <kbd>{_norm(p.name)}</kbd>: {self._block(p.value, slots)}" for p in keys]
            return self._slot(slots, "\n\n" + "\n".join(lines) + "\n\n")
        if name.startswith(":"):  # transcluded page, e.g. {{:Order of Precedence}}
            return "See " + self._link_to(name[1:], None) + "."
        self.unknown["template:" + name] += 1
        # Best effort: keep the first positional argument's content.
        return arg(0)

    def _plain_inner(self, code) -> str:
        r = Renderer(None, self.page_title, preformat=False, emphasis=False, inline=True)
        out = r.md(code)
        self.unknown.update(r.unknown)
        # Inline code must not contain Markdown wrapping from nested code spans.
        return out.replace("`", "") if out.count("`") % 2 == 0 else out

    def _feature(self, t: Template, pos) -> str:
        ftype = str(pos[0].value).strip().lower() if pos else "informative"
        slots: list[str] = []
        if ftype == "gvi":
            game, ver = (str(pos[1].value).strip() if len(pos) > 1 else ""), (str(pos[2].value).strip() if len(pos) > 2 else "")
            body = self._block(pos[3].value, slots) if len(pos) > 3 else f"This feature was introduced with {game_name(game)} v{ver}."
            return _quote(body, "NOTE", f"Since {game_name(game)} v{ver}")
        if ftype == "obsolete":
            body = "This information is **obsolete**."
            if len(pos) > 1:
                body += " " + self._block(pos[1].value, slots)
            return _quote(body, "CAUTION")
        if len(pos) > 1 and str(pos[1].value).strip():
            body = self._block(pos[1].value, slots)
        elif ftype in FEATURE_DEFAULT_TEXT:
            body = self._block(parse_wikitext(FEATURE_DEFAULT_TEXT[ftype]), slots)
        elif ftype in GAME_NAMES:
            body = f"This is an {GAME_NAMES[ftype]} feature."
        else:
            body = ""
        if ftype == "quote":
            return _quote(body)
        if ftype in FEATURE_ALERT:
            return _quote(body, FEATURE_ALERT[ftype])
        label = GAME_NAMES.get(ftype, str(pos[0].value).strip() if pos else "")
        return _quote(body, "NOTE", label if body and not body.startswith("This ") else None)

    def _fields(self, t: Template, key: str) -> str:
        """Infobox-style templates such as {{Tool}}: one "**Label:** value" paragraph per filled parameter."""
        params = [(_norm(p.name), p.value) for p in t.params if p.showkey]
        if key == "terrainprocessormanual":
            pos = [p.value for p in t.params if not p.showkey]
            params = list(zip(TERRAIN_TASK_FIELDS, pos)) + params
        out = []
        for name, value in params:
            text = self._block(value, []) if name.lower() not in FIELD_SKIP else ""
            if text:
                label = FIELD_LABELS.get(name.lower(), name.replace("_", " ").capitalize())
                out.append(f"**{label}:**" + ("\n\n" + text if "\n" in text else " " + text))
        return "\n\n".join(out)

    def _control_type(self, t: Template, part: str, slots: list[str]) -> str:
        """{{CT|intro|...}} and {{CT|attribute|...}} on the GUI control type pages, expanded as Template:CT does."""

        def get(name: str) -> str:
            return str(t.get(name).value).strip() if t.has(name) else ""

        if part == "intro":
            src = (f"== Introduction ==\n{get('description')}\n\n=== Related commands & functions ===\n"
                   "* [[:Category:Command_Group:_GUI_Control|Commands: General]]\n"
                   "* [[:Category:Command_Group:_GUI_Control_-_Event_Handlers|Commands: UI Eventhandlers]]\n"
                   f"{get('commands')}\n\n=== Related User Interface Eventhandlers ===\n"
                   f"* [[User_Interface_Event_Handlers#Generic_Events|Events: General]]\n{get('events')}\n\n"
                   "== Alphabetical Order ==\n"
                   "{{Feature|informative|TokenNames common to most controls, such as x, y, w, h, text, idc... can be "
                   "found [[Arma:_GUI_Configuration#Common_Properties|'''here''']].}}\n"
                   f"<syntaxhighlight lang=\"cpp\">#define {get('macro')} {get('value')}</syntaxhighlight>")
        elif part == "attribute":
            name = get("name")
            types = [(get(f"type{i}"), get(f"value{i}")) for i in range(1, 5) if get(f"type{i}")]
            src = f"==== {name} ====\n"
            if get("mandatory"):
                src += "{{Feature|important|This attribute is mandatory for the control to work!}}\n"
            src += "; Type: " + ", ".join(f"[[TokenNameValueTypes|{ty}]]" for ty, _ in types) + "\n"
            src += f"; Description: {get('description') or 'n/a'}\n"
            for ty, value in types:
                example = {"array": f"{name}[] = {value};", "class": value}.get(ty.lower(), f"{name} = {value};")
                src += (f"{ty} example:\n" if len(types) > 1 else "") + f"<syntaxhighlight lang=\"cpp\">{example}</syntaxhighlight>\n"
        elif part == "examples":
            src = ("== Default Classes ==\n{{Feature|arma3|'''AddOns:''' Classes need to be initialised first with "
                   "<syntaxhighlight lang=\"cpp\" inline>class SomeClass;</syntaxhighlight>\n----\n'''Missions:''' Since "
                   "{{arma3}} v2.02 one can use <syntaxhighlight lang=\"cpp\" inline>import SomeClass;</syntaxhighlight> to "
                   "initialise a class (see the [[import (Config)|import]] keyword).\nIn older versions, use <sqf inline>"
                   "\"Default\" call BIS_fnc_exportGUIBaseClasses;</sqf> and paste the result into the "
                   "[[Description.ext|description.ext]].}}")
        else:  # abc start / abc end: layout only
            return ""
        return self._slot(slots, "\n\n" + self._block(parse_wikitext(src), []) + "\n\n")

    def note_md(self, note: dict) -> str:
        head = f"**{note['user'] or 'Anonymous'}**"
        if note.get("date"):
            head += f" ({note['date'][:10]})"
        return _quote(head + ":\n\n" + note["text"])

    # ---- tags ------------------------------------------------------------------------------

    def _tag(self, tag: Tag, slots: list[str]) -> str:
        name = str(tag.tag).strip().lower()
        markup = tag.wiki_markup

        if markup in ("*", "#", ":", ";"):
            return markup
        if name in ("b", "strong", "i", "em"):
            inner = self._nodes(tag.contents.nodes, slots) if tag.contents else ""
            if not inner.strip():
                return inner
            mark = STAR * 2 if name in ("b", "strong") else STAR
            lead, core, trail = _split_ws(inner)
            return f"{lead}{mark}{core}{mark}{trail}"
        if name == "hr":
            return "\n\n---\n\n"
        if name == "br":
            return BR
        if name == "nowiki":
            # in a slot, so no later pass reads its text as markup; even an empty one ends a run of quotes:
            # ''a''<nowiki/>'s is "a" in italics, then "'s"
            return self._slot(slots, html.unescape(str(tag.contents)) if tag.contents else "")
        if name == "table":
            return self._slot(slots, "\n\n" + self._table(tag) + "\n\n")
        if name in CODE_TAGS:
            code = clean_code(html.unescape(str(tag.contents))) if tag.contents else ""
            lang = name
            if name in ("syntaxhighlight", "source"):
                lang = str(tag.get("lang").value).strip() if tag.has("lang") else ""
            elif name == "pre":
                lang = ""
            if tag.has("inline"):
                return self._slot(slots, _inline_code(code.strip()))
            code = code.strip("\n").rstrip()
            fence = "````" if "```" in code else "```"
            return self._slot(slots, f"\n\n{fence}{lang}\n{_dedent(code)}\n{fence}\n\n")
        if name == "code" and tag.has("style") and re.search(r"display:\s*block", str(tag.get("style").value)):
            # a multi-line code block; unlike <sqf>, links and templates inside are wiki markup
            code = str(tag.contents) if tag.contents else ""
            code = re.sub(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]", r"\1", code)
            code = re.sub(r"<br\s*/?>", "\n", code, flags=re.I)
            code = re.sub(r"'{3}|</?(span|b|i|u|small)\b[^>]*>", "", code)
            code = clean_code(html.unescape(code)).strip("\n").rstrip()
            fence = "````" if "```" in code else "```"
            return self._slot(slots, f"\n\n{fence}\n{_dedent(code)}\n{fence}\n\n") if code.strip() else ""
        if re.fullmatch(r"h[1-6]", name):
            inner = self._block(tag.contents, slots) if tag.contents else ""
            return self._heading(int(name[1]), inner, slots)
        if name in INLINE_CODE_TAGS:
            inner = html.unescape(self._plain_inner(tag.contents)) if tag.contents else ""
            return self._slot(slots, _inline_code(clean_code(inner)))
        if name in DROP_TAGS:
            return ""
        if name == "ref":
            inner = self._nodes(tag.contents.nodes, slots).strip() if tag.contents else ""
            return f" (ref: {inner})" if inner else ""
        if name in ("s", "del", "strike"):
            inner = self._nodes(tag.contents.nodes, slots) if tag.contents else ""
            return f"~~{inner}~~"
        if name == "li":
            inner = self._nodes(tag.contents.nodes, slots).strip() if tag.contents else ""
            return f"\n- {inner}\n"
        if name in ("ul", "ol", "dl"):
            return "\n" + (self._nodes(tag.contents.nodes, slots) if tag.contents else "") + "\n"
        if name == "dt":
            inner = self._nodes(tag.contents.nodes, slots).strip() if tag.contents else ""
            return f"\n**{inner}**\n"
        if name == "dd":
            inner = self._nodes(tag.contents.nodes, slots).strip() if tag.contents else ""
            return f"\n{inner}\n"
        if name in ("tr", "td", "th", "caption"):
            # Stray table parts outside a <table>; keep the text.
            return (self._nodes(tag.contents.nodes, slots) if tag.contents else "") + " "
        if name not in ("span", "div", "small", "big", "sup", "sub", "u", "font", "center", "spoiler", "p",
                        "blockquote", "abbr", "includeonly", "onlyinclude", "noinclude", "execute", "ins", "a",
                        "executeclose", "log", "marker"):
            self.unknown["tag:" + name] += 1
        if name == "noinclude":
            return ""
        inner = self._nodes(tag.contents.nodes, slots) if tag.contents else ""
        return BLOCK + inner + BLOCK if name in BLOCK_TAGS else inner

    def _table(self, table: Tag) -> str:
        rows: list[list[tuple[str, bool]]] = []
        current: Optional[list] = None

        def span(node: Tag, attr: str) -> int:
            if not node.has(attr):
                return 1
            m = re.match(r"\s*(\d+)", str(node.get(attr).value))
            return max(1, min(int(m.group(1)), 50)) if m else 1

        def cell(node: Tag) -> tuple[str, bool, int, int]:
            text = self._block(node.contents, [], inline=True) if node.contents else ""
            text = text.replace("\n\n", "<br>").replace("\n", "<br>").replace("|", "\\|")
            return text.strip(), str(node.tag).lower() == "th", span(node, "rowspan"), span(node, "colspan")

        for node in table.contents.nodes if table.contents else []:
            if not isinstance(node, Tag):
                continue
            tname = str(node.tag).lower()
            if tname == "tr":
                current = []
                rows.append(current)
                for c in node.contents.nodes if node.contents else []:
                    if isinstance(c, Tag) and str(c.tag).lower() in ("td", "th"):
                        current.append(cell(c))
            elif tname in ("td", "th"):
                if current is None:
                    current = []
                    rows.append(current)
                current.append(cell(node))
        rows = _unspan([r for r in rows if r])
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        header = rows[0] if all(is_th for _, is_th in rows[0]) else [("", True)] * width
        body = rows[1:] if header is rows[0] else rows

        def line(r):
            vals = [c for c, _ in r] + [""] * (width - len(r))
            return "| " + " | ".join(vals) + " |"

        return "\n".join([line(header), "|" + "---|" * width] + [line(r) for r in body])

    # ---- wiki list lines -> Markdown -------------------------------------------------------

    def _lists(self, text: str, skip_first: bool = False) -> str:
        out = []
        for i, line in enumerate(text.split("\n")):
            m = None if skip_first and i == 0 else _LIST_LINE.match(line)
            if not m:
                out.append(line)
                continue
            prefix, rest = m.groups()
            depth = len(prefix)
            last = prefix[-1]
            if last == "*":
                out.append("  " * (depth - 1) + "- " + rest)
            elif last == "#":
                out.append("   " * (depth - 1) + "1. " + rest)
            elif last == ";":
                term, sep, definition = rest.partition(" : ")
                short = None if sep else re.match(r"([^:\[\]()`{}<]+?):\s+(\S.*)$", rest)
                if short:  # "; Type: String" on the config references: only the term is bold
                    out.append(f"**{short.group(1).strip()}:** {short.group(2)}\n")  # own paragraph, not run on
                else:
                    out.append(f"**{term.strip()}**" + (f"\n{definition.strip()}" if sep else ""))
            else:  # ':' indentation / list continuation
                listish = any(c in "*#" for c in prefix)
                out.append(("  " * (depth - 1) if listish else "") + rest)
        return "\n".join(out)


def _unspan(rows: list[list[tuple[str, bool, int, int]]]) -> list[list[tuple[str, bool]]]:
    """Markdown tables have no row/column spans. A row-spanning cell is repeated in every row it covers, so
    each row reads on its own ("Arma 3 v2.00 | Location", not "Location" under the version column); a
    column-spanning cell keeps its first column and leaves the others empty (titles across the whole table)."""
    out: list[list[tuple[str, bool]]] = []
    pending: dict[int, tuple[tuple[str, bool], int]] = {}  # column -> (cell, rows still covered)
    for row in rows:
        line: list[tuple[str, bool]] = []
        cells = iter(row)
        while True:
            col = len(line)
            if col in pending:
                c, left = pending.pop(col)
                line.append(c)
                if left > 1:
                    pending[col] = (c, left - 1)
                continue
            nxt = next(cells, None)
            if nxt is None:
                if pending and max(pending) > col:
                    line.append(("", False))
                    continue
                break
            text, is_th, rowspan, colspan = nxt
            for k in range(colspan):
                c = (text if k == 0 else "", is_th)
                if rowspan > 1:
                    pending[len(line)] = (c, rowspan - 1)
                line.append(c)
        out.append(line)
    return out


def parse_note(t: Template, r: Renderer) -> dict:
    def get(name: str) -> str:
        return str(t.get(name).value).strip() if t.has(name) else ""

    ts = get("timestamp")
    date = ""
    if re.fullmatch(r"\d{12,14}", ts):
        ts = ts.ljust(14, "0")
        date = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"
    return {"user": get("user"), "date": date, "text": r.md(t.get("text").value) if t.has("text") else ""}


_I_OPEN, _I_CLOSE, _B_OPEN, _B_CLOSE = "", "", "", ""
_EMPHASIS = {_I_OPEN: (_I_CLOSE, STAR), _B_OPEN: (_B_CLOSE, STAR * 2)}


def _styles(line: str) -> str:
    """MediaWiki ''italic'' / '''bold''' / '''''both''''' -> Markdown, by MediaWiki's own rules (Parser::doQuotes):
    with an odd number of both '' and ''', one ''' is read as an apostrophe plus ''; whatever is still open is
    closed at the end of the line, so "'''DO NOT'' use" is "'*DO NOT* use", not a markup error."""
    if "''" not in line:
        return line
    parts = re.split(r"('{2,})", line)
    italics = bold = 0
    for i in range(1, len(parts), 2):
        n = len(parts[i])
        if n == 4:  # an apostrophe, then bold
            parts[i - 1] += "'"
            parts[i] = "'''"
        elif n > 5:  # apostrophes, then bold italic
            parts[i - 1] += "'" * (n - 5)
            parts[i] = "'''''"
        n = len(parts[i])
        italics += n in (2, 5)
        bold += n in (3, 5)
    if italics % 2 and bold % 2:
        single = multi = space = None
        for i in range(1, len(parts), 2):
            if len(parts[i]) != 3:
                continue
            before = parts[i - 1]
            x1, x2 = before[-1:], (before[-2] if len(before) > 1 else before[:1])
            if x1 == " ":
                space = i if space is None else space
            elif x2 == " ":  # after a one-letter word
                single = i
                break
            elif multi is None:
                multi = i
        pick = next((i for i in (single, multi, space) if i is not None), None)
        if pick is not None:
            parts[pick - 1] += "'"
            parts[pick] = "''"

    i_, b_, ic, bc = _I_OPEN, _B_OPEN, _I_CLOSE, _B_CLOSE
    out, state, buffer = [], "", ""
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if state == "both":
                buffer += part
            else:
                out.append(part)
            continue
        n = len(part)
        if n == 2:
            out.append({"i": ic, "bi": ic, "ib": bc + ic + b_, "both": b_ + i_ + buffer + ic}.get(state, i_))
            state = {"i": "", "bi": "b", "ib": "b", "both": "b"}.get(state, state + "i")
        elif n == 3:
            out.append({"b": bc, "bi": ic + bc + i_, "ib": bc, "both": i_ + b_ + buffer + bc}.get(state, b_))
            state = {"b": "", "bi": "i", "ib": "i", "both": "i"}.get(state, state + "b")
        else:  # 5
            out.append({"b": bc + i_, "i": ic + b_, "bi": ic + bc, "ib": bc + ic,
                        "both": i_ + b_ + buffer + bc + ic}.get(state, ""))
            state = {"b": "i", "i": "b", "bi": "", "ib": "", "both": ""}.get(state, "both")
            buffer = ""
    if state in ("b", "ib"):
        out.append(bc)
    if state in ("i", "bi", "ib"):
        out.append(ic)
    if state == "bi":
        out.append(bc)
    if state == "both" and buffer:
        out.append(b_ + i_ + buffer + ic + bc)
    return _emphasis("".join(out))


def _emphasis(text: str) -> str:
    """Opening/closing marks from _styles -> Markdown, innermost first, whitespace kept outside the marks."""
    marks = "".join(_EMPHASIS) + "".join(c for c, _ in _EMPHASIS.values())
    inner = re.compile(f"([{_I_OPEN}{_B_OPEN}])([^{marks}]*)([{_I_CLOSE}{_B_CLOSE}])")

    def sub(m: re.Match) -> str:
        close, mark = _EMPHASIS[m.group(1)]
        if m.group(3) != close:  # not a pair (cannot happen with doQuotes' output); keep the text
            return m.group(2)
        lead, core, trail = _split_ws(m.group(2))
        return f"{lead}{mark}{core}{mark}{trail}" if core else m.group(2)

    while True:
        new = inner.sub(sub, text)
        if new == text:
            return re.sub(f"[{marks}]", "", new)
        text = new


def _quote(body: str, alert: Optional[str] = None, label: Optional[str] = None) -> str:
    lines = []
    if alert:
        lines.append(f"[!{alert}]")
    if label:
        if _MD_BLOCK.match(body):  # a code block, table or list cannot continue the label's line
            body = f"**{label}:**\n\n{body}"
        else:
            body = f"**{label}:** {body}" if body else f"**{label}**"
    lines += body.split("\n")
    return "\n".join(("> " + l) if l.strip() else ">" for l in lines)


def _inline_code(code: str) -> str:
    if code and not code.strip():  # {{hl|&nbsp;}}: a space shown as code
        return "` `"
    code = re.sub(r"\s*\n\s*", " ", code).strip()
    if not code:
        return ""
    ticks = "``" if "`" in code else "`"
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{ticks}{pad}{code}{pad}{ticks}"


_MD_LINK = re.compile(r"\[((?:\\.|[^\]\\])*)\]\([^)\s]*\)")
# a run of <br>, then what starts the next line: a mark that Markdown would read as a list, heading or quote
_BREAK_RUN = re.compile(BR + r"(?:[ \t]*\n?[ \t]*" + BR + r")*[ \t]*(\n?)([ \t]*)((?:[*+-](?=[ \t])|#{1,6}(?=[ \t]|$)|>|\d{1,9}[.)](?=[ \t]|$)))?")
# a backslash that Markdown would not show as is: before ASCII punctuation or at the end of a line
_MD_BACKSLASH = re.compile(r"\\(?=[!-/:-@\[-`{-~]|\n|$)")
# a line Markdown reads as a block of its own
_MD_BLOCK = re.compile(r"[ \t]*(?:[*+-][ \t]|\d+[.)][ \t]|#{1,6}[ \t]|>|\||`{3,}|~{3,})")


# A link inside a code block, for the site only: CODE_LINK[0] text CODE_LINK[1] url CODE_LINK[2]
CODE_LINK = ("\ue030", "\ue031", "\ue032")


def _pre_line(line: str, slots: list[str], keep_links: bool = False) -> str:
    """One line of a preformatted block: wiki markup still applies there, so links keep only their text (or
    become CODE_LINK marks, ``keep_links``) and inline code and emphasis lose their marks."""
    # code shows backslashes as they are: undo _MD_BACKSLASH of the wiki text (before the slots come back)
    line = re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", line)
    line = _SLOT.sub(lambda m: re.sub(r"^(`+) ?(.*?) ?\1$", r"\2", slots[int(m.group(1))], flags=re.S), line)

    def link(m: re.Match) -> str:
        text = re.sub(r"\\([\[\]])", r"\1", m.group(1))
        url = re.search(r"\]\(([^)\s]*)\)$", m.group(0)).group(1)
        return CODE_LINK[0] + text + CODE_LINK[1] + url + CODE_LINK[2] if keep_links else text

    line = _MD_LINK.sub(link, line)
    return re.sub(r"'{2,5}", "", line).replace(STAR, "").replace(BR, "\n")


def _dedent(code: str) -> str:
    return code.replace("\t", "    ")


def _split_ws(s: str) -> tuple[str, str, str]:
    core = s.strip()
    if not core:
        return s, "", ""
    start = s.index(core[0])
    return s[:start], core, s[start + len(core):]

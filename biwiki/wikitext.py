"""Convert BI Community Wiki wikitext to Markdown.

Covers the subset of MediaWiki markup and wiki templates that actually occur on
the Arma 3 command/function pages (see ``python -m biwiki stats``).
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
                  "table/rvscripting"}

CODE_TAGS = {"sqf", "sqs", "syntaxhighlight", "source", "pre", "cpp", "hpp", "ext", "enforce"}
INLINE_CODE_TAGS = {"code", "tt", "var", "t", "kbd", "samp"}
DROP_TAGS = {"img", "gallery", "references", "imagemap", "wbr"}

_SLOT = re.compile("(\\d+)")
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
        return args[0]
    if name == "link":
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
    return re.sub(r"(?m)^:+[ \t]*(\{\||\{\{\{!\}\})", r"\1", wikitext)


def game_name(code: str, short: bool = False) -> str:
    key = re.sub(r"[ :/-]", "", code.strip().lower())
    if short and key in GAME_SHORT:
        return GAME_SHORT[key]
    return GAME_NAMES.get(key, code.strip())


def _norm(name) -> str:
    return str(name).strip()


class Renderer:
    """Stateless-per-call converter; ``unknown`` collects templates/tags it had no rule for."""

    def __init__(self, resolve: Optional[LinkResolver] = None, page_title: str = ""):
        self.resolve = resolve or (lambda title, anchor: None)
        self.page_title = page_title
        self.unknown: Counter = Counter()

    # ---- public API -------------------------------------------------------------------------

    def md(self, wikitext) -> str:
        """Render wikitext (str or Wikicode) to a finished Markdown string."""
        src = str(wikitext)
        if "{{!}}" in src and _TABLE_ESCAPED.search(src):
            # Tables written with {{!}} so they survive inside template parameters.
            code = parse_wikitext(src.strip().replace("{{!}}", "|"))
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
        r = Renderer(None, self.page_title)
        s = r.md(wikitext)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
        self.unknown.update(r.unknown)
        return s.strip()

    # ---- rendering --------------------------------------------------------------------------

    def _slot(self, slots: list[str], content: str) -> str:
        slots.append(content)
        return f"{len(slots) - 1}"

    def _finish(self, text: str, slots: list[str]) -> str:
        text = self._lists(text)
        text = "\n".join(_styles(line) for line in text.split("\n")).replace(STAR, "*")
        # We never emit images, so "![" is always text such as SQF "!" before a link ("![[alive]]" -> "!alive").
        # Code is still in slots here, so it is not affected.
        text = text.replace("![", "\\![")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        while _SLOT.search(text):
            text = _SLOT.sub(lambda m: slots[int(m.group(1))], text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _block(self, code, slots: list[str]) -> str:
        """Render a nested piece as an independent, finished Markdown block."""
        inner: list[str] = []
        return self._finish(self._nodes(code.nodes if hasattr(code, "nodes") else parse_wikitext(str(code)).nodes, inner), inner)

    def _nodes(self, nodes, slots: list[str]) -> str:
        return "".join(self._node(n, slots) for n in nodes)

    def _node(self, node, slots: list[str]) -> str:
        if isinstance(node, Text):
            return node.value
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
            return self._heading(node.level, self._block(node.title, slots), slots)
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
        if not page:
            page = self.page_title
        url = self.resolve(page.replace("_", " ").strip(), anchor)
        return f"[{text}]({url})" if url else text

    def _expand(self, code) -> str:
        """Plain text of a link target, which may itself contain templates like {{arma2oa}} or {{=}}."""
        src = str(code).strip()
        if "{{" not in src:
            return src
        return Renderer(None, self.page_title).md(src).replace("`", "")

    def _heading(self, level: int, title: str, slots: list[str]) -> str:
        # In a slot, so the wiki-list pass does not read the leading "#" as a numbered list.
        return self._slot(slots, f"\n\n{'#' * min(level + 1, 6)} {title.strip()}\n\n")

    def _link_to(self, target: str, text: Optional[str]) -> str:
        if re.match(r"^(https?:)?//", target):
            return f"[{text}]({target})" if text else f"<{target}>"
        target = target.lstrip(":")
        if target.lower().startswith("category:") and not text:
            text = target.split(":", 1)[1]
        page, _, anchor = target.partition("#")
        url = self.resolve((page or self.page_title).replace("_", " ").strip(), anchor)  # "#Section" = this page
        text = text or target
        return f"[{text}]({url})" if url else text

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
            code = html.unescape(self._plain_inner(pos[0].value) if pos else "")
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
        if key == "link":
            return self._link_to(self._expand(pos[0].value) if pos else "", arg(1) or None)
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
        if name.startswith(":"):  # transcluded page, e.g. {{:Order of Precedence}}
            return "See " + self._link_to(name[1:], None) + "."
        self.unknown["template:" + name] += 1
        # Best effort: keep the first positional argument's content.
        return arg(0)

    def _plain_inner(self, code) -> str:
        r = Renderer(None, self.page_title)
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
            return "\n"
        if name == "nowiki":
            return str(tag.contents) if tag.contents else ""
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
                        "blockquote", "abbr", "includeonly", "onlyinclude", "noinclude", "execute",
                        "executeclose", "log", "marker"):
            self.unknown["tag:" + name] += 1
        if name == "noinclude":
            return ""
        return self._nodes(tag.contents.nodes, slots) if tag.contents else ""

    def _table(self, table: Tag) -> str:
        rows: list[list[tuple[str, bool]]] = []
        current: Optional[list] = None

        def cell(node: Tag) -> tuple[str, bool]:
            text = self._block(node.contents, []) if node.contents else ""
            text = text.replace("\n\n", "<br>").replace("\n", "<br>").replace("|", "\\|")
            return text.strip(), str(node.tag).lower() == "th"

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
        rows = [r for r in rows if r]
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

    def _lists(self, text: str) -> str:
        out = []
        for line in text.split("\n"):
            m = _LIST_LINE.match(line)
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
                out.append(f"**{term.strip()}**" + (f"\n{definition.strip()}" if sep else ""))
            else:  # ':' indentation / list continuation
                listish = any(c in "*#" for c in prefix)
                out.append(("  " * (depth - 1) if listish else "") + rest)
        return "\n".join(out)


def parse_note(t: Template, r: Renderer) -> dict:
    def get(name: str) -> str:
        return str(t.get(name).value).strip() if t.has(name) else ""

    ts = get("timestamp")
    date = ""
    if re.fullmatch(r"\d{12,14}", ts):
        ts = ts.ljust(14, "0")
        date = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"
    return {"user": get("user"), "date": date, "text": r.md(t.get("text").value) if t.has("text") else ""}


def _styles(line: str) -> str:
    """MediaWiki ''italic'' / '''bold''' / '''''both''''' -> Markdown; emphasis never spans lines."""
    if "''" not in line:
        return line

    def wrap(mark: str):
        def sub(m: re.Match) -> str:
            lead, core, trail = _split_ws(m.group(1))
            return f"{lead}{mark}{core}{mark}{trail}" if core else m.group(1)

        return sub

    line = re.sub(r"'{5}(.+?)'{5}", wrap(STAR * 3), line)
    line = re.sub(r"'{3}(.+?)'{3}", wrap(STAR * 2), line)
    line = re.sub(r"(?<!')''(?!')(.+?)''", wrap(STAR), line)
    # an unclosed ''/''' at the end of a line styles nothing in MediaWiki (a common typo); drop it
    return re.sub(r"(?<!')'{2,5}\s*$", "", line)


def _quote(body: str, alert: Optional[str] = None, label: Optional[str] = None) -> str:
    lines = []
    if alert:
        lines.append(f"[!{alert}]")
    if label:
        body = f"**{label}:** {body}" if body else f"**{label}**"
    lines += body.split("\n")
    return "\n".join(("> " + l) if l.strip() else ">" for l in lines)


def _inline_code(code: str) -> str:
    code = re.sub(r"\s*\n\s*", " ", code).strip()
    if not code:
        return ""
    ticks = "``" if "`" in code else "`"
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{ticks}{pad}{code}{pad}{ticks}"


def _dedent(code: str) -> str:
    return code.replace("\t", "    ")


def _split_ws(s: str) -> tuple[str, str, str]:
    core = s.strip()
    if not core:
        return s, "", ""
    start = s.index(core[0])
    return s[:start], core, s[start + len(core):]

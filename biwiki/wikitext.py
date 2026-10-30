"""Helpers for reading the BI Community Wiki's wikitext: cutting a page into its fields with mwparserfromhell
(``parse_wikitext``, ``preprocess``), the code of a <sqf> block as the wiki shows it (``clean_code``), the games'
names and the wiki's anchors. Rendering the fields is the MediaWiki parser port's job (see portrender.py).

Original a3ref code (MIT).
"""
from __future__ import annotations

import re

import mwparserfromhell as mw

from .site import ANCHOR, heading_id

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

# The wiki's <sqf> highlighter turns piped [[target|text]] into links; plain [[x]] is valid SQF (nested arrays).
_CODE_LINK = re.compile(r"\[\[([A-Za-z][^\[\]|\n,\"]*)\|([^\[\]\n]+)\]\]")
_CODE_TEMPLATE = re.compile(r"\{\{\s*([^{}|\n]+?)\s*(?:\|([^{}\n]*))?\}\}")


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
    # bold/italic are left as text: mwparserfromhell's own style parsing can run across template parameters and
    # swallow "|p2=" etc.
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


def game_name(code: str, short: bool = False) -> str:
    key = re.sub(r"[ :/-]", "", code.strip().lower())
    if short and key in GAME_SHORT:
        return GAME_SHORT[key]
    return GAME_NAMES.get(key, code.strip())


# MediaWiki's legacy anchor encoding (Sanitizer::escapeIdLegacy, still in old links and in the fallback <span>
# before a heading): urlencode with "%" written as ".", so ".23include" is "#include". urlencode leaves letters,
# digits and "_.-" alone, and ":" is put back, so only the other bytes are escapes.
_LEGACY_RUN = re.compile(r"(?:\.[0-9A-F]{2})+")
_LEGACY_BYTES = {b for b in range(0x21, 0x7F) if not chr(b).isalnum() and chr(b) not in "_.-:"} | set(range(0x80, 0x100))


def wiki_anchor(anchor: str) -> str:
    """A wiki #anchor (of a link, or an element's id) as the heading text it stands for, the form the link
    resolvers take: legacy escapes decoded, "_" read as spaces. A leading "_" is part of the name ("_this")."""
    lead = re.match(r"_*", anchor).group(0)
    rest = anchor[len(lead):]

    def decode(m: re.Match) -> str:
        run = m.group(0)
        raw = bytes(int(run[i + 1:i + 3], 16) for i in range(0, len(run), 3))
        # "Arma 3 v1.22" is a version, not an escaped '"'
        if not all(b in _LEGACY_BYTES for b in raw) or (run[1:3].isdigit() and rest[m.start() - 1:m.start()].isdigit()):
            return run
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return run

    return lead + _LEGACY_RUN.sub(decode, rest).replace("_", " ")


def anchor_mark(ident: str) -> str:
    """The ANCHOR mark of a wiki element's id="..." (empty for no id): the site's id for it, which links to that
    anchor get from the resolver (site.heading_id of wiki_anchor)."""
    ident = heading_id(wiki_anchor(ident)) if ident else ""
    return ANCHOR[0] + ident + ANCHOR[1] if ident else ""

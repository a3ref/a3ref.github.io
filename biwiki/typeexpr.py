"""Normalise the wiki's prose types ("[[Array]] of [[Number]]s or [[String]]") to ``Array<Number> | String``.

The wiki writes types as English: "Object or Array of Objects", "Array of Array of Numbers",
"Array of two Arrays format Color (RGBA)", "Number in range 0..1". Agents and linters need the
structure, so a type is read as a small grammar:

    union := term ((',' | 'or' | 'and/or' | 'and' | '/') term)*
    term  := TYPE ['of' element | ['in'] 'format' TYPE]   # both only after Array
    element := term (('and/or' | 'and') term)*     # "Array of Objects and/or Positions"

"of" binds tighter than "or", so "Object or Array of Objects" is ``Object | Array<Object>``; inside
"of", plain "or" continues the element only between two plurals ("Array of Objects or Groups").
Reading stops at the first word that is not part of a type ("in range 0..1", "(RGBA)", "but ..."),
so qualifiers are dropped. A text that does not start with a type gives ``None``.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

import mwparserfromhell as mw
from mwparserfromhell.nodes import Comment, HTMLEntity, Template, Text, Wikilink

# Type names in function header comments, which are plain text ("ARRAY of STRINGs", "scalar").
TYPE_WORDS = {
    "object": "Object", "array": "Array", "string": "String", "number": "Number", "scalar": "Number",
    "float": "Number", "integer": "Number", "int": "Number", "bool": "Boolean", "boolean": "Boolean",
    "code": "Code", "group": "Group", "side": "Side", "config": "Config", "cfg": "Config", "control": "Control",
    "display": "Display", "nothing": "Nothing", "none": "Nothing", "void": "Nothing", "any": "Anything",
    "anything": "Anything", "hashmap": "HashMap", "location": "Location", "namespace": "Namespace",
    "text": "Structured Text", "structuredtext": "Structured Text", "task": "Task", "team": "Team",
    "position": "Position", "position2d": "Position2D", "position3d": "Position3D", "positionatl": "PositionATL",
    "positionasl": "PositionASL", "positionagl": "PositionAGL", "positionagls": "PositionAGLS",
    "color": "Color", "colour": "Color", "vector": "Vector3D", "script": "Script Handle",
}
# Unlinked words accepted as types in wiki text ("[[Object]] or array"): only those that are not
# also common English in descriptions ("text", "team", "position", "any" ...).
WIKI_WORDS = {"object", "array", "string", "number", "boolean", "code", "group", "side", "config",
              "control", "display", "nothing", "anything", "hashmap", "namespace"}

_SEPARATORS = {",", "or", "and/or", "and", "/"}
_FILLERS = {"a", "an", "the", "empty", "non-empty", "two", "three", "four", "single"}
_LEX = re.compile(r"'''|''|and/or|[A-Za-z][\w.\-]*|\S")


class Token(NamedTuple):
    kind: str  # "type", "word" or "stop"
    value: str
    plural: bool = False


def _word_tokens(text: str, words: set[str], tokens: list[Token]) -> None:
    for m in _LEX.finditer(text):
        w = m.group(0)
        if w in ("'''", "''"):
            continue
        low = w.lower()
        base = low[:-1] if low.endswith("s") and low[:-1] in words else low
        if base in words and (low == base or low == base + "s"):
            tokens.append(Token("type", TYPE_WORDS[base], low != base))
        elif low in _SEPARATORS or low in _FILLERS or low in ("of", "in", "format"):
            tokens.append(Token("word", low))
        else:
            tokens.append(Token("stop", w))


def link_type(link: Wikilink) -> Optional[str]:
    """The type a link names: its text when it points into a section (``[[Position#PositionAGL|PositionAGL]]``)."""
    target = str(link.title).strip().lstrip(":").replace("_", " ")
    if target.lower().startswith(("category:", "file:", "image:", "media:")):
        return None
    name = str(link.text).strip() if link.text is not None and "#" in target else target.split("#")[0].strip()
    low = name.lower()
    if low.endswith("s") and low[:-1] in WIKI_WORDS:  # [[Objects]]
        low = low[:-1]
    return TYPE_WORDS[low] if low in WIKI_WORDS else (name or None)  # [[array]] -> Array


def wiki_tokens(code) -> list[Token]:
    """Tokens of wikitext: links are types, templates (version icons) are skipped, tags end the type."""
    if not isinstance(code, mw.wikicode.Wikicode):
        code = mw.parse(str(code), skip_style_tags=True)
    tokens: list[Token] = []
    nodes = list(code.nodes)
    for i, node in enumerate(nodes):
        if isinstance(node, Wikilink):
            name = link_type(node)
            if name:
                nxt = nodes[i + 1] if i + 1 < len(nodes) else None
                plural = isinstance(nxt, Text) and re.match(r"s(?!\w)", nxt.value) is not None
                tokens.append(Token("type", name, plural))
        elif isinstance(node, Text):
            text = node.value
            if tokens and tokens[-1].kind == "type" and tokens[-1].plural and i and isinstance(nodes[i - 1], Wikilink):
                text = text[1:]  # the plural "s" of "[[Number]]s"
            _word_tokens(text, WIKI_WORDS, tokens)
        elif isinstance(node, (Template, Comment, HTMLEntity)):
            continue
        else:
            tokens.append(Token("stop", str(node)))
    return tokens


def text_tokens(text: str) -> list[Token]:
    """Tokens of plain text such as a function header ("ARRAY of STRINGs or OBJECT")."""
    tokens: list[Token] = []
    _word_tokens(text, set(TYPE_WORDS), tokens)
    return tokens


def parse(tokens: list[Token]) -> Optional[str]:
    """The type expression of the tokens, or None when they do not start with a type."""
    pos = 0

    def peek(k: int = 0) -> Optional[Token]:
        return tokens[pos + k] if pos + k < len(tokens) else None

    def skip_fillers() -> None:
        nonlocal pos
        while (t := peek()) and t.kind == "word" and t.value in _FILLERS:
            pos += 1

    def term() -> Optional[tuple[str, bool]]:
        nonlocal pos
        skip_fillers()
        t = peek()
        if not t or t.kind != "type":
            return None
        pos += 1
        name, plural = t.value, t.plural
        nxt = peek()
        if nxt and nxt.kind == "word" and nxt.value == "of" and name == "Array":  # not "Tree View Path of ..."
            start = pos
            pos += 1
            inner = element()
            if inner:
                return f"{name}<{inner}>", plural
            pos = start
        elif nxt and nxt.kind == "word" and (nxt.value == "format" or nxt.value == "in" and (peek(1) or Token("", "")).value == "format"):
            # "Array format Position", "Array in format Date": the format is the type
            start = pos
            pos += 2 if nxt.value == "in" else 1
            fmt = term()
            if fmt and name == "Array":
                return fmt[0], plural
            pos = start
        return name, plural

    def element() -> Optional[str]:
        nonlocal pos
        first = term()
        if not first:
            return None
        parts = [first[0]]
        while (t := peek()) and t.kind == "word" and t.value in ("and/or", "and", "or"):
            start = pos
            pos += 1
            nxt = term()
            if not nxt or (t.value == "or" and not (first[1] and nxt[1])):
                pos = start
                break
            parts.append(nxt[0])
        return union(parts)

    first = term()
    if not first:
        return None
    parts = [first[0]]
    while (t := peek()) and t.kind == "word" and t.value in _SEPARATORS:
        start = pos
        pos += 1
        nxt = term()
        if not nxt:
            pos = start
            break
        parts.append(nxt[0])
    return union(parts)


def union(parts: list[str]) -> Optional[str]:
    """Join alternatives with " | ", dropping repeats."""
    seen: list[str] = []
    for p in parts:
        for alt in split_union(p):
            if alt not in seen:
                seen.append(alt)
    return " | ".join(seen) or None


def split_union(expr: str) -> list[str]:
    """The top-level alternatives of an expression (``Array<A | B> | C`` -> ``Array<A | B>``, ``C``)."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(expr):
        depth += c == "<"
        depth -= c == ">"
        if c == "|" and depth == 0:
            out.append(expr[start:i].strip())
            start = i + 1
    out.append(expr[start:].strip())
    return [x for x in out if x]


def names(expr: Optional[str]) -> list[str]:
    """The type names an expression uses, in order (``Array<Object> | Side`` -> Array, Object, Side)."""
    return list(dict.fromkeys(x.strip() for x in re.split(r"[<>|]", expr or "") if x.strip()))


def of_wikitext(code) -> Optional[str]:
    return parse(wiki_tokens(code))


def of_text(text: str) -> Optional[str]:
    return parse(text_tokens(text))

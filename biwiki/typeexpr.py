"""Normalise the wiki's prose types ("[[Array]] of [[Number]]s or [[String]]") to ``Array<Number> | String``.

The wiki writes types as English: "Object or Array of Objects", "Array of Array of Numbers",
"Array of two Arrays format Color (RGBA)", "Number in range 0..1". Agents and linters need the
structure, so a type is read as a small grammar:

    union := term ((',' | 'or' | 'and/or' | 'and' | '/') term)*
    term  := TYPE ['of' element | ['in'] 'format' TYPE]   # both only after Array
    element := term (('and/or' | 'and') term)*     # "Array of Objects and/or Positions"

"of" binds tighter than "or", so "Object or Array of Objects" is ``Object | Array<Object>``; inside
"of", "or" and "," continue the element between terms of the same number: "Array of Objects, Groups or
Strings", "Array of Eden Entity or Eden ID" (singulars joined by commas only if an "or" ends the list).
Qualifiers are dropped but do not end the type: a version note before an alternative ("String, since
{{GVI|arma3|1.06}} also Code", "Boolean or (since 1.66) Number"), a note in parentheses ("Color (RGBA)",
"PositionAGL (PositionASL if radius is negative!) or Object", whose types are alternatives too), "of type
Unit" after a type, and a few words of prose before the next separator ("String only in OFP or Code").
Reading stops at punctuation that ends the type part (" - ", ":", "[") and at links to pages that are no
types (commands such as [[while]], values such as [[true]]). A text that does not start with a type gives
``None``.
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
_LEX = re.compile(r"'''|''|and/or|\d[\d.]*|[A-Za-z][\w.\-]*|\S")
# "since {{GVI|arma3|1.06}} also [[Code]]", ", since Arma 3 v2.12 [[Array]]": skipped before a term
_VERSION = re.compile(r"(?i)arma|v?\d[\d.]*")
# punctuation that ends the type part; prose between a type and the next separator may not contain it
_HARD = {"-", "–", ":", ";", ".", "[", "]", "=", '"', "{", "}", "!", "?", "<", ">"}
# words that may come before the type in a parenthesised alternative: "(or [[Boolean]] since 2.22)"
_PAREN_LEADS = {"or", "and/or", "and", ",", "also", "since", "must", "be", "usually", "only", "can", "may",
                "especially", "e.g.", "i.e."}
# words of prose skipped after a type before the next alternative ("[[String]] only in ... or [[Code]]")
_MAX_PROSE = 8


class Token(NamedTuple):
    kind: str  # "type", "word" or "stop"
    value: str
    plural: bool = False
    word: bool = False  # a type written as a plain word ("array"), not linked: also common in prose


def _word_tokens(text: str, words: set[str], tokens: list[Token]) -> None:
    for m in _LEX.finditer(text):
        w = m.group(0)
        if w in ("'''", "''"):
            continue
        low = w.lower()
        base = low[:-1] if low.endswith("s") and low[:-1] in words else low
        if base in words and (low == base or low == base + "s"):
            tokens.append(Token("type", TYPE_WORDS[base], low != base, True))
        elif low in _SEPARATORS or low in _FILLERS or low in ("of", "in", "format"):
            tokens.append(Token("word", low))
        else:
            tokens.append(Token("stop", w))


def _is_file_link(target: str) -> bool:
    return target.lower().startswith(("category:", "file:", "image:", "media:"))


def link_type(link: Wikilink) -> Optional[str]:
    """The type a link names: its text when it points into a section (``[[Position#PositionAGL|PositionAGL]]``).

    None for links that name no type: files and categories, and pages whose title starts in lower case,
    which are commands ([[while]], [[typeOf]]) and values ([[true]], [[objNull]]); [[nil]] is Nothing.
    """
    target = str(link.title).strip().lstrip(":").replace("_", " ")
    if _is_file_link(target):
        return None
    name = str(link.text).strip() if link.text is not None and "#" in target else target.split("#")[0].strip()
    low = name.lower()
    if low.endswith("s") and low[:-1] in WIKI_WORDS:  # [[Objects]]
        low = low[:-1]
    if low in WIKI_WORDS:
        return TYPE_WORDS[low]  # [[array]] -> Array
    if low == "nil":
        return "Nothing"
    return name if name[:1].isupper() else None


def wiki_tokens(code) -> list[Token]:
    """Tokens of wikitext: links are types, templates (version icons) are skipped, tags and links to pages
    that are no types end the type."""
    if not isinstance(code, mw.wikicode.Wikicode):
        code = mw.parse(str(code), skip_style_tags=True)
    tokens: list[Token] = []
    nodes = list(code.nodes)
    for i, node in enumerate(nodes):
        if isinstance(node, Wikilink):
            name = link_type(node)
            if name:
                nxt = nodes[i + 1] if i + 1 < len(nodes) else None
                label = str(node.text).strip().lower() if node.text is not None else ""
                plural = (isinstance(nxt, Text) and re.match(r"s(?!\w)", nxt.value) is not None
                          or label.endswith("s") and label[:-1] == name.lower())  # [[Config|configs]]
                tokens.append(Token("type", name, plural))
            elif not _is_file_link(str(node.title).strip().lstrip(":")):
                tokens.append(Token("stop", str(node.title).strip()))
        elif isinstance(node, Text):
            text = node.value
            if (tokens and tokens[-1].kind == "type" and tokens[-1].plural and i and isinstance(nodes[i - 1], Wikilink)
                    and re.match(r"s(?!\w)", text)):
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


def _is_word(t: Optional[Token], *values: str) -> bool:
    return t is not None and t.kind == "word" and t.value in values


def _is_stop(t: Optional[Token], *values: str) -> bool:
    return t is not None and t.kind == "stop" and t.value.lower() in values


def _is_hard(t: Token) -> bool:
    return t.kind == "stop" and (t.value in _HARD or t.value.startswith("<"))


def _parse(tokens: list[Token]) -> tuple[Optional[str], dict[int, str]]:
    """The type expression of the tokens and the type tokens it was read from (index -> name)."""
    pos = 0
    used: dict[int, str] = {}

    def peek(k: int = 0) -> Optional[Token]:
        return tokens[pos + k] if pos + k < len(tokens) else None

    def rollback(start: int) -> None:
        nonlocal pos
        pos = start
        for i in [i for i in used if i >= start]:
            del used[i]

    def close(i: int) -> int:
        """Index of the ")" that closes the "(" at ``i``; the end when it is not closed."""
        depth = 0
        for j in range(i, len(tokens)):
            if _is_stop(tokens[j], "("):
                depth += 1
            elif _is_stop(tokens[j], ")"):
                depth -= 1
                if depth == 0:
                    return j
        return len(tokens)

    def untyped_paren() -> bool:
        """Skip a parenthesised note without types ("(RGBA)", "(since 1.66)")."""
        nonlocal pos
        if not _is_stop(peek(), "("):
            return False
        end = close(pos)
        if any(t.kind == "type" for t in tokens[pos:end]):
            return False
        pos = end + 1
        return True

    def skip_noise() -> None:
        nonlocal pos
        while (t := peek()):
            if _is_word(t, *_FILLERS) or _is_stop(t, "also"):
                pos += 1
            elif _is_stop(t, "since"):  # "since {{GVI|arma3|1.06}}" (the template is no token), "since Arma 3 v2.12"
                pos += 1
                while (v := peek()) and v.kind == "stop" and _VERSION.fullmatch(v.value):
                    pos += 1
            elif not untyped_paren():
                return

    def term() -> Optional[tuple[str, bool]]:
        nonlocal pos
        skip_noise()
        t = peek()
        if not t or t.kind != "type":
            return None
        used[pos] = t.value
        pos += 1
        name, plural = t.value, t.plural
        nxt, after = peek(), peek(1)
        if _is_word(nxt, "of") and name == "Array":  # not "Tree View Path of ..."
            start = pos
            pos += 1
            inner = element()
            if inner:
                return f"{name}<{inner}>", plural
            rollback(start)
        elif _is_word(nxt, "of") and _is_stop(after, "type"):
            # "[[Object]] of type [[Object|Unit]]": a kind of the type, no alternative
            start = pos
            pos += 2
            if not term():
                rollback(start)
        elif _is_word(nxt, "format") or _is_word(nxt, "in") and _is_word(after, "format"):
            # "Array format Position", "Array in format Date": the format is the type
            start = pos
            pos += 2 if nxt.value == "in" else 1
            fmt = term()
            if fmt and name == "Array":
                return fmt[0], plural
            rollback(start)
        elif name == "Array" and _is_word(nxt, "in") and after and after.kind == "type" and _is_word(peek(2), "format"):
            used[pos + 1] = after.value  # "Array in Date format"
            pos += 3
            return after.value, plural
        elif name == "Array" and _is_stop(nxt, ":") and after and after.kind == "type" and after.plural:
            used[pos + 1] = after.value  # a return value's "[[Array]]: [[Number]]s"
            pos += 2
            return f"{name}<{after.value}>", plural
        return name, plural

    def element() -> Optional[str]:
        nonlocal pos
        first = term()
        if not first:
            return None
        parts, plural = [first[0]], first[1]
        keep = (pos, 1)  # up to the last term joined by a conjunction (or by a comma between plurals)
        while True:
            untyped_paren()  # "[[String]] (marker) and/or [[Position]]"
            start, t = pos, peek()
            if not _is_word(t, "and/or", "and", "or", ","):
                break
            pos += 1
            joint = t.value
            if joint == "," and _is_word(peek(), "and/or", "and", "or"):  # "Groups, or Strings"
                joint = tokens[pos].value
                pos += 1
            nxt = term()
            # "or" and "," only between terms of the same number: "Array of Numbers or Nothing" ends at "or"
            if not nxt or joint in (",", "or") and nxt[1] != plural:
                rollback(start)
                break
            parts.append(nxt[0])
            if joint != "," or plural:
                keep = (pos, len(parts))
        if keep[0] != pos:  # singulars joined by commas only: "Array of Number, Array" are two alternatives
            rollback(keep[0])
            del parts[keep[1]:]
        return union(parts)

    def is_separator(t: Token) -> bool:
        return t.kind == "word" and t.value in _SEPARATORS

    first = term()
    if not first:
        return None, {}
    parts = [first[0]]
    while (t := peek()):
        if _is_stop(t, "("):
            # "[[PositionAGL]] ([[PositionASL]] if radius is negative!)", "[[Number]] (or [[Boolean]] since 2.22)":
            # the types in it are alternatives too
            end = close(pos)
            k = pos + 1
            while (k < end and k - pos <= 3 and tokens[k].kind != "type"
                   and (tokens[k].value.lower() in _PAREN_LEADS or _VERSION.fullmatch(tokens[k].value))):
                k += 1
            if k < end and tokens[k].kind == "type" and not tokens[k].word:  # not "(object position)"
                expr, inner = _parse(tokens[k:end])
                if expr:
                    parts.append(expr)
                    used.update({k + i: n for i, n in inner.items()})
            pos = end + 1
            continue
        if is_separator(t):
            start = pos
            pos += 1
            if t.value == "," and _is_word(peek(), "or", "and", "and/or"):
                pos += 1
            nxt = term()
            if not nxt:
                rollback(start)
                break
            parts.append(nxt[0])
            continue
        # a few words of prose before the next alternative: "[[String]] only in {{ofp}} until v1.85 or [[Code]]";
        # prose that names types ("[[Array]] of pairs [[Number]], [[Number]]", "[[Array]] containing all hostile
        # sides of given side or object") describes the value and ends the type
        j = pos
        while (j < len(tokens) and j - pos < _MAX_PROSE and tokens[j].kind != "type" and not _is_hard(tokens[j])
               and not is_separator(tokens[j]) and not _is_stop(tokens[j], "(")):
            j += 1
        if j == pos or j == len(tokens) or not is_separator(tokens[j]):
            break
        nxt = tokens[j + 1] if j + 1 < len(tokens) else None
        if _is_word(nxt, "or", "and", "and/or") and j + 2 < len(tokens):
            nxt = tokens[j + 2]
        if not nxt or nxt.kind != "type" or nxt.word:  # only a linked type after prose is an alternative
            break
        pos = j
    return union(parts), used


def parse(tokens: list[Token]) -> Optional[str]:
    """The type expression of the tokens, or None when they do not start with a type."""
    return _parse(tokens)[0]


def parse_types(tokens: list[Token]) -> tuple[Optional[str], list[str]]:
    """The type expression and the names of the types it was read from, in order: only the types in the type
    position, not those mentioned in prose or notes after it."""
    expr, used = _parse(tokens)
    return expr, list(dict.fromkeys(used[i] for i in sorted(used)))


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


def wikitext_types(code) -> tuple[Optional[str], list[str]]:
    """``of_wikitext`` and the types it was read from (see parse_types)."""
    return parse_types(wiki_tokens(code))


def of_text(text: str) -> Optional[str]:
    return parse(text_tokens(text))

# Written by a3ref contributors on 2026-10-30 after the HTML of the BI wiki's SQF Highlighter extension
# (https://community.bistudio.com/, not public), for the MediaWiki parser port (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The <sqf> and <sqs> tags of the BI wiki's own SQF Highlighter extension.

The extension is not public; this module reproduces the HTML the wiki's action=parse gives for it, token class
by token class (sampled on 2026-10-30). The rules, as observed:

- Output: ``<div class="sqfhighlighter-block"><div class="sqfhighlighter-scroller">CODE</div></div>``, or with
  ``inline`` ``<span class="sqfhighlighter-block">CODE</span>``; <sqs> adds the class ``sqshighlighter-block``.
  Code that is empty after trim() gives ``-no <a>SQF</a> code provided-`` in a ``sqfhighlighter-error`` div (or
  span). The code is trim()med, or with ``notrim`` only loses a blank first line. The HTML is returned as a nowiki
  strip item, so it is put back after the block-level pass (hence the ``<p class="mw-empty-elt">`` around a block)
  and only tidy (French spaces) touches it. Other attributes are ignored.
- Tokens: ``cc`` comments (``//``, ``/* */``; their text is parsed as wikitext and only <a>, <i>, <u>, <s> and <b>
  (as ``<span class="b">``) are kept), ``s`` strings ("" and '' without escapes, so ``'it''s'`` is two strings),
  ``n`` numbers, ``m`` preprocessor directives at a line start and some ``__MACROS__`` (titled with the page
  title), ``lv`` local variables, ``mv`` magic variables (linked to Magic Variables), ``k`` keywords and plain
  links for commands and known functions, ``fe`` unknown ``*_fnc_*`` names, ``gv`` other identifiers, ``o``
  operators (linked to their pages), ``as``/``ae``, ``cs``/``ce``, ``ps``/``pe`` brackets, ``sl`` a token that would
  link to the current page, ``bv`` (with a title) unexpected characters and improperly closed strings or comments,
  ``bvl`` identifiers that start with a digit. Whitespace, ``,`` and ``;`` are not wrapped.
- SQS (<sqs>) is tokenized line by line: a line starting with ``;`` is a comment; ``#``, ``~``, ``@`` and ``?``
  at a line start are linked to their sections of SQS Syntax, and the first ``:`` of a ``?`` line too.

Which identifiers are commands and functions is the wiki's knowledge; ``register`` takes the names. a3ref gets
them from the titles in its data clone: ``raw/commands.json`` and ``raw/functions.json`` (a dict page id ->
{"title", ...}; a title's spaces are underscores in code, "BIS fnc spawnGroup" is ``BIS_fnc_spawnGroup``), see
``names_from_raw``.
"""
from __future__ import annotations

import json
import re
from html.entities import codepoint2name
from pathlib import Path
from typing import Iterable, Optional

# Keywords: commands that get the class "k" (and a link)
KEYWORDS = frozenset(
    "if then else exitWith while do for from to step forEach switch case default waitUntil true false try catch "
    "throw with and or exit break continue breakOut breakTo continueWith".split())

# Magic variables -> their anchor on the page Magic Variables
MAGIC_VARIABLES = {
    "_this": "this", "_x": "x", "_y": "y", "_exception": "exception", "_fnc_scriptName": "fnc_scriptName",
    "_fnc_scriptNameParent": "fnc_scriptNameParent", "_forEachIndex": "forEachIndex", "_self": "self",
    "_thisArgs": "thisArgs", "_thisEvent": "thisEvent", "_thisEventHandler": "thisEventHandler",
    "_thisFSM": "thisFSM", "_thisScript": "thisScript", "_thisScriptedEventHandler": "thisScriptedEventHandler",
    "_time": "time", "this": "this_2", "thisList": "thisList", "thisTrigger": "thisTrigger",
}

# Preprocessor macros that get the class "m" (the wiki titles them with the page's title)
MACROS = frozenset(
    "__FILE__ __LINE__ __TIME__ __TIME_UTC__ __COUNTER__ __COUNTER_RESET__ __GAME_VER__ __GAME_VER_MAJ__ "
    "__GAME_VER_MIN__ __GAME_BUILD__ __ARMA__ __ARMA3__ __A3_DEBUG__ __has_include __DATE_ARR__ __DATE_STR__ "
    "__DATE_STR_ISO8601__ __TIMESTAMP_UTC__".split())

# Operators -> (the page they link to, as a database key; the path of the link)
OPERATORS = {
    "=": ("a_=_b", "a_=_b"), "==": ("a_==_b", "a_==_b"), "!=": ("a_!=_b", "a_!=_b"),
    ">": ("a_greater_b", "a_greater_b"), "<": ("a_less_b", "a_less_b"), ">=": ("a_greater=_b", "a_greater=_b"),
    "<=": ("a_less=_b", "a_less=_b"), ">>": ("config_greater_greater_name", "config_greater_greater_name"),
    "&&": ("a_&&_b", "a_&&_b"), "||": ("a_or_b", "a_or_b"), "!": ("!_a", "!_a"), "+": ("+", "+"), "-": ("-", "-"),
    "*": ("a_*_b", "a_*_b"), "/": ("a_/_b", "a_/_b"), "%": ("a_%_b", "a_%25_b"), "^": ("a_^_b", "a_^_b"),
    "#": ("a_hash_b", "a_hash_b"), ":": ("a_:_b", "a_:_b"),
}
_OPERATOR_CHARS = frozenset("=!<>&|^%*/+#:-")

# SQS line-start signs -> their section of SQS Syntax
SQS_SIGNS = {"#": "Label", "~": "Tilde", "@": "@", "?": "Conditional"}

_BRACKETS = {"[": "as", "]": "ae", "{": "cs", "}": "ce", "(": "ps", ")": "pe"}
_WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
# what ends a run of unexpected characters
_FALLBACK_STOP = _WORD_CHARS | frozenset(" \t\n[]{}(),;\"'.") | _OPERATOR_CHARS

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?(?:0x[0-9a-fA-F]+|[0-9]+(?:\.[0-9]*)?(?:e-?[0-9]+)?|\.[0-9]*(?:e-?[0-9]+)?)")
_MALFORMED_NUMBER = re.compile(r"-?[A-Za-z0-9_.\-]*")
_DIGIT_IDENTIFIER = re.compile(r"[0-9][A-Za-z0-9_]*")
_DIRECTIVE = re.compile(r"#define(?:[ \t]+[A-Za-z0-9_]+(?:\([^)\n]*\))?(?=[ \t]))?"
                        r"|#(?:include|ifdef|ifndef|else|endif|undef|if)(?![A-Za-z0-9_])")
_WHITESPACE = re.compile(r"[ \t\n]+")
_SQS_SIGN = re.compile(r"[ \t]*([#~@?])")
_KEPT_TAG = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9]*)\b[^>]*>", re.S)
_BOLD_OPEN = re.compile(r"<b\b[^>]*>")

UNEXPECTED = "Unexpected character"
UNCLOSED_STRING = "Improperly closed string"
DIGIT_START = "A variable's identifier cannot start with a number"


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


def escape(text: str) -> str:
    """PHP htmlentities(ENT_QUOTES) as Sanitizer::normalizeCharReferences() leaves it: the special characters and
    every character with an HTML 4 entity name become references (é is &#233;, ' is &#39;); other characters stay."""
    out = []
    for ch in text:
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        elif ch == "'":
            out.append("&#39;")
        elif ord(ch) in codepoint2name:
            out.append(f"&#{ord(ch)};")
        else:
            out.append(ch)
    return "".join(out)


def _span(cls: str, html: str, title: Optional[str] = None) -> str:
    if title is not None:
        return f'<span class="{cls}" title="{escape(title)}">{html}</span>'
    return f'<span class="{cls}">{html}</span>'


def _db_key(name: str) -> str:
    return name.replace(" ", "_")


class SqfHighlighter:
    """The commands and functions the highlighter knows, and its rendering of <sqf> and <sqs>."""

    def __init__(self, commands: Iterable[str] = (), functions: Iterable[str] = ()):
        self.commands = frozenset(_db_key(c) for c in commands)
        self.functions = frozenset(_db_key(f) for f in functions)

    # ---- tag hooks --------------------------------------------------------------------------------------------

    def sqf_hook(self, content: Optional[str], attributes: dict, parser, frame=None) -> dict:
        return self.render(content, attributes, parser, frame, sqs=False)

    def sqs_hook(self, content: Optional[str], attributes: dict, parser, frame=None) -> dict:
        return self.render(content, attributes, parser, frame, sqs=True)

    def render(self, content: Optional[str], attributes: dict, parser, frame=None, *, sqs: bool = False) -> dict:
        attributes = attributes or {}
        inline = "inline" in attributes
        code = content or ""
        if _php_trim(code) == "":
            language = "SQS" if sqs else "SQF"
            link = f'<a href="{self._href(parser, language + "_Syntax")}">{language}</a>'
            tag = "span" if inline else "div"
            html = f'<{tag} class="sqfhighlighter-error">-no {link} code provided-</{tag}>'
            return {0: html, "markerType": "nowiki"}
        if "notrim" in attributes:
            code = re.sub(r"\A[ \t]*\n", "", code)
        else:
            code = _php_trim(code)
        body = _Run(self, parser, frame).sqs(code) if sqs else _Run(self, parser, frame).sqf(code)
        cls = "sqfhighlighter-block sqshighlighter-block" if sqs else "sqfhighlighter-block"
        if inline:
            html = f'<span class="{cls}">{body}</span>'
        else:
            html = f'<div class="{cls}"><div class="sqfhighlighter-scroller">{body}</div></div>'
        return {0: html, "markerType": "nowiki"}

    @staticmethod
    def _href(parser, path: str) -> str:
        return escape(parser.config.article_path.replace("$1", path))


class _Run:
    """One rendering: the tokenizer over a piece of code, writing HTML."""

    def __init__(self, highlighter: SqfHighlighter, parser, frame):
        self.hl = highlighter
        self.parser = parser
        self.frame = frame
        self.title = parser.title or ""
        self.self_key = _db_key(self.title)

    # ---- languages --------------------------------------------------------------------------------------------

    def sqf(self, code: str) -> str:
        return self.tokens(code, preprocessor=True)

    def sqs(self, code: str) -> str:
        lines = []
        for line in code.split("\n"):
            if re.match(r"[ \t]*;", line):
                lines.append(self.comment(line))
                continue
            m = _SQS_SIGN.match(line)
            if not m:
                lines.append(self.tokens(line))
                continue
            sign = m.group(1)
            # the indentation before ?, but not before #, ~ and @, is kept
            out = (line[:m.start(1)] if sign == "?" else "") + self.sqs_sign(sign)
            rest = line[m.end():]
            if sign == "?" and ":" in rest:
                condition, statement = rest.split(":", 1)
                out += self.tokens(condition, line_start=False) + self.sqs_sign(":")
                out += self.tokens(statement, line_start=False)
            else:
                out += self.tokens(rest, line_start=False)
            lines.append(out)
        return "\n".join(lines)

    def sqs_sign(self, sign: str) -> str:
        section = SQS_SIGNS.get(sign, "Conditional")
        return _span("o", f'<a href="{self.href("SQS_Syntax#" + section)}">{escape(sign)}</a>')

    # ---- links ------------------------------------------------------------------------------------------------

    def href(self, path: str) -> str:
        return SqfHighlighter._href(self.parser, path)

    def link(self, text: str, page: str, path: Optional[str] = None, cls: Optional[str] = None) -> str:
        """A link to ``page`` (a database key), or the "sl" span if that is the current page."""
        if page == self.self_key:
            return _span("sl", escape(text))
        html = f'<a href="{self.href(path or page)}">{escape(text)}</a>'
        return _span(cls, html) if cls else html

    # ---- tokenizer --------------------------------------------------------------------------------------------

    def tokens(self, s: str, *, preprocessor: bool = False, line_start: bool = True) -> str:
        out = []
        i, n = 0, len(s)
        while i < n:
            c = s[i]
            m = _WHITESPACE.match(s, i)
            if m:
                ws = m.group(0)
                out.append(ws)
                line_start = line_start or "\n" in ws
                i = m.end()
                continue
            start_of_line, line_start = line_start, False
            if s.startswith("//", i):
                end = s.find("\n", i)
                end = n if end < 0 else end
                out.append(self.comment(s[i:end]))
                i = end
            elif s.startswith("/*", i):
                end = s.find("*/", i + 2)
                if end < 0:
                    out.append(_span("bv", escape(s[i:]), UNEXPECTED))
                    i = n
                else:
                    out.append(self.comment(s[i:end + 2]))
                    i = end + 2
            elif c in "\"'":
                end = s.find(c, i + 1)
                if end < 0:
                    out.append(_span("bv", escape(s[i:]), UNCLOSED_STRING))
                    i = n
                else:
                    out.append(_span("s", escape(s[i:end + 1])))
                    i = end + 1
            elif c == "#" and preprocessor and start_of_line and _DIRECTIVE.match(s, i):
                m = _DIRECTIVE.match(s, i)
                out.append(_span("m", escape(m.group(0))))
                i = m.end()
            elif c in _BRACKETS:
                out.append(_span(_BRACKETS[c], c))
                i += 1
            elif c in ",;":
                out.append(c)
                i += 1
            elif c in _WORD_CHARS and not c.isdigit():
                m = _IDENTIFIER.match(s, i)
                word = m.group(0)
                out.append(self.identifier(word))
                i = m.end()
            elif c.isdigit() and c.isascii() or c == "." or (
                    c == "-" and i + 1 < n and (s[i + 1] == "." or s[i + 1].isascii() and s[i + 1].isdigit())):
                html, i = self.number(s, i)
                out.append(html)
            elif c in _OPERATOR_CHARS:
                html, i = self.operator(s, i)
                out.append(html)
            else:
                j = i + 1
                while j < n and s[j] not in _FALLBACK_STOP:
                    j += 1
                out.append(_span("bv", escape(s[i:j]), UNEXPECTED))
                i = j
        return "".join(out)

    def identifier(self, word: str) -> str:
        if word == "_":
            return _span("bv", "_", UNEXPECTED)
        if word in MACROS:
            return _span("m", escape(word), self.title)
        if word in MAGIC_VARIABLES:
            return _span("mv", f'<a href="{self.href("Magic_Variables#" + MAGIC_VARIABLES[word])}">{word}</a>')
        if word.startswith("_"):
            return _span("lv", word)
        if word in KEYWORDS:
            return self.link(word, word, cls="k")
        if word in self.hl.commands:
            return self.link(word, word)
        if re.search(r"_fnc_[A-Za-z0-9_]", word):
            if word in self.hl.functions or word == self.self_key:
                return self.link(word, word)
            return _span("fe", word)
        return _span("gv", word)

    def number(self, s: str, i: int) -> tuple[str, int]:
        m = _NUMBER.match(s, i)
        end = m.end()
        nxt = s[end] if end < len(s) else ""
        if nxt == "." or nxt == "-" or nxt in _WORD_CHARS and nxt and not m.group(0).endswith("."):
            word = _MALFORMED_NUMBER.match(s, i).group(0)
            if _DIGIT_IDENTIFIER.fullmatch(word):
                return _span("bvl", f'<a href="{self.href("Identifier")}">{word}</a>', DIGIT_START), i + len(word)
            return _span("bv", escape(word), UNEXPECTED), i + len(word)
        return _span("n", m.group(0)), end

    def operator(self, s: str, i: int) -> tuple[str, int]:
        j = i + 1
        while j < len(s) and s[j] in _OPERATOR_CHARS and not (s.startswith("//", j) or s.startswith("/*", j)):
            j += 1
        if j - i > 1 and s[j - 1] == "-":
            while j < len(s) and (s[j] in _WORD_CHARS or s[j] == "."):
                j += 1
        run = s[i:j]
        if run in OPERATORS:
            page, path = OPERATORS[run]
            return self.link(run, page, path, cls="o"), j
        if run.startswith("<"):
            return escape(run), j
        return _span("bv", escape(run), UNEXPECTED), j

    # ---- comments ---------------------------------------------------------------------------------------------

    def comment(self, text: str) -> str:
        """A comment: its text parsed as wikitext, keeping only links and <i>, <u>, <s> and <b> (as a span)."""
        parser = self.parser
        html = parser.recursive_tag_parse(text, self.frame)
        html = parser.replace_link_holders(html)
        html = parser.strip_state.unstrip_both(html)
        return _span("cc", _keep_outer_tags(html))


def _keep_outer_tags(html: str) -> str:
    """The HTML of a comment as the wiki shows it: the outermost <a>, <i>, <u>, <s> and <b> (as
    ``<span class="b">``) elements stay, every other tag goes (so ''''' gives only <i>), the text stays."""
    out = []
    stack: list[Optional[str]] = []  # the open elements; the name of a kept outermost one, else None
    pos = 0
    for m in _TAG.finditer(html):
        out.append(html[pos:m.start()])
        pos = m.end()
        closing, name = m.group(1), (m.group(2) or "").lower()
        if not name or name in _VOID_TAGS or m.group(0).endswith("/>"):
            continue
        if not closing:
            if not stack and name in _KEPT_TAGS:
                out.append('<span class="b">' if name == "b" else m.group(0))
                stack.append(name)
            else:
                stack.append(None)
        elif stack:
            kept = stack.pop()
            if kept is not None:
                out.append("</span>" if kept == "b" else f"</{kept}>")
    out.append(html[pos:])
    while stack:
        kept = stack.pop()
        if kept is not None:
            out.append("</span>" if kept == "b" else f"</{kept}>")
    return "".join(out)


_TAG = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9]*)\b[^>]*>", re.S)
_KEPT_TAGS = frozenset(("a", "i", "u", "s", "b"))
_VOID_TAGS = frozenset(("br", "hr", "img", "wbr", "meta", "link", "input", "col", "area", "base", "source"))


def names_from_raw(path) -> list[str]:
    """The names of the pages in a raw file of the data clone (``raw/commands.json``, ``raw/functions.json``)."""
    pages = json.loads(Path(path).read_text(encoding="utf-8"))
    return sorted(_db_key(page["title"]) for page in pages.values())


def register(parser, *, commands: Iterable[str] = (), functions: Iterable[str] = ()) -> SqfHighlighter:
    """ParserFirstCallInit: the <sqf> and <sqs> tags. ``commands`` and ``functions`` are the names (or page
    titles) of the scripting commands and functions that get links; see ``names_from_raw``."""
    highlighter = SqfHighlighter(commands, functions)
    parser.set_hook("sqf", highlighter.sqf_hook)
    parser.set_hook("sqs", highlighter.sqs_hook)
    return highlighter

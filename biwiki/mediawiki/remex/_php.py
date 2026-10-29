# Part of the port of RemexHtml 3.0.2 (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation.
# MIT license: see biwiki/mediawiki/remex/LICENSE.
# Written by a3ref contributors on 2026-10-30: Python equivalents of the PHP built-in string functions that
# RemexHtml's src/ relies on, with PHP's semantics (ASCII-only case folding, byte-string offsets become code
# point offsets).
"""Python versions of the PHP string functions RemexHtml uses."""
from __future__ import annotations

import re
from typing import Optional

_SPAN_CACHE: dict[str, re.Pattern[str]] = {}
_CSPAN_CACHE: dict[str, re.Pattern[str]] = {}
_ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}


def _class(mask: str) -> str:
    return "[" + "".join(re.escape(c) for c in mask) + "]"


def strspn(text: str, mask: str, start: int = 0, length: Optional[int] = None) -> int:
    """PHP strspn(): the length of the initial segment of ``text[start:start+length]`` consisting of characters
    in ``mask``."""
    pattern = _SPAN_CACHE.get(mask)
    if pattern is None:
        pattern = _SPAN_CACHE[mask] = re.compile(_class(mask) + "+")
    end = len(text) if length is None else min(len(text), start + length)
    m = pattern.match(text, start, end)
    return m.end() - start if m else 0


def strcspn(text: str, mask: str, start: int = 0, length: Optional[int] = None) -> int:
    """PHP strcspn(): the length of the initial segment of ``text[start:start+length]`` consisting of characters
    not in ``mask``."""
    pattern = _CSPAN_CACHE.get(mask)
    if pattern is None:
        pattern = _CSPAN_CACHE[mask] = re.compile("[^" + _class(mask)[1:] + "*")
    end = len(text) if length is None else min(len(text), start + length)
    if start >= end:
        return 0
    m = pattern.match(text, start, end)
    return m.end() - start


def strtolower(s: str) -> str:
    """PHP strtolower(): folds ASCII letters only."""
    return s.translate(_ASCII_LOWER)


def strcasecmp(a: str, b: str) -> int:
    """PHP strcasecmp(), as far as RemexHtml uses it: 0 if the strings are equal ignoring ASCII case."""
    a = strtolower(a)
    b = strtolower(b)
    return 0 if a == b else (-1 if a < b else 1)

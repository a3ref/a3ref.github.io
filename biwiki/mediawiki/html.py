# Ported from MediaWiki 1.39 includes/Html.php (https://www.mediawiki.org/), (C) MediaWiki contributors:
# Html::rawElement(), element(), openElement(), closeElement(), expandAttributes(), dropDefaults().
# Changed by a3ref contributors on 2026-10-30: translated to Python; attributes are a dict (or a list of pairs) whose
# order is kept, as PHP's arrays keep theirs; no warnings.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Building HTML elements the way MediaWiki writes them (attribute order, quoting, escaping)."""
from __future__ import annotations

from typing import Mapping, Optional, Union

# List of void elements from HTML5, section 8.1.2 as of 2016-09-19
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "keygen", "link", "meta", "param",
                 "source", "track", "wbr"}

# Boolean attributes, which may have the value omitted entirely. Manually collected from the HTML5 spec as of
# 2011-08-12.
BOOL_ATTRIBS = {"async", "autofocus", "autoplay", "checked", "controls", "default", "defer", "disabled",
                "formnovalidate", "hidden", "ismap", "itemscope", "loop", "multiple", "muted", "novalidate", "open",
                "pubdate", "readonly", "required", "reversed", "scoped", "seamless", "selected", "truespeed",
                "typemustmatch"}

_INPUT_TYPES = {"hidden", "text", "password", "checkbox", "radio", "file", "submit", "image", "reset", "button",
                "datetime", "datetime-local", "date", "month", "time", "week", "number", "range", "email", "url",
                "search", "tel", "color"}

_ATTRIB_DEFAULTS = {
    "area": {"shape": "rect"},
    "button": {"formaction": "GET", "formenctype": "application/x-www-form-urlencoded"},
    "canvas": {"height": "150", "width": "300"},
    "form": {"action": "GET", "autocomplete": "on", "enctype": "application/x-www-form-urlencoded"},
    "input": {"formaction": "GET", "type": "text"},
    "keygen": {"keytype": "rsa"},
    "link": {"media": "all"},
    "menu": {"type": "list"},
    "script": {"type": "text/javascript"},
    "style": {"media": "all", "type": "text/css"},
    "textarea": {"wrap": "soft"},
}

Value = Union[str, int, float, bool, None, list, dict]
Attribs = Union[Mapping[str, Value], list]


def htmlspecialchars(text: str, quotes: bool = True) -> str:
    """PHP htmlspecialchars() with ENT_QUOTES (or ENT_COMPAT when ``quotes`` is false: only double quotes)."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return text.replace("'", "&#039;") if quotes else text


def _items(attribs: Optional[Attribs]) -> list[tuple]:
    if not attribs:
        return []
    return list(attribs.items()) if isinstance(attribs, Mapping) else list(attribs)


def raw_element(element: str, attribs: Optional[Attribs] = None, contents: Optional[str] = "") -> str:
    """Returns an HTML element in a string. The major advantage here over manually typing out the HTML is that it
    will escape all attribute values. This is quite similar to Xml::tags(), but it implements some useful HTML5
    features. The contents are not escaped."""
    start = open_element(element, attribs)
    if element in VOID_ELEMENTS:
        return start[:-1] + "/>"
    from .sanitizer import escape_combining_char

    return start + escape_combining_char(contents or "") + close_element(element)


def element(element_: str, attribs: Optional[Attribs] = None, contents: Optional[str] = "") -> str:
    """Identical to raw_element(), but HTML-escapes contents (like Xml::element())."""
    return raw_element(element_, attribs, (contents or "").replace("&", "&amp;").replace("<", "&lt;"))


def open_element(element_: str, attribs: Optional[Attribs] = None) -> str:
    """Identical to raw_element(), but has no third parameter and omits the end tag (and the self-closing '/' in
    XML mode for empty elements)."""
    items = _items(attribs)
    element_ = element_.lower()
    if element_ == "input":
        items = [(k, v) for k, v in items if not (k == "type" and v not in _INPUT_TYPES)]
    if element_ == "button" and not any(k == "type" for k, _ in items):
        items.append(("type", "submit"))
    return f"<{element_}" + expand_attributes(drop_defaults(element_, items)) + ">"


def close_element(element_: str) -> str:
    """Returns "</$element>" """
    return f"</{element_.lower()}>"


def drop_defaults(element_: str, items: list[tuple]) -> list[tuple]:
    """Given an element name and an associative array of element attributes, return an array that is functionally
    identical to the input array, but possibly smaller. In particular, attributes might be stripped if they are
    given their default values."""
    out = []
    for attrib, value in items:
        if attrib == "class":
            if value in ("", [], [""]):
                continue
        elif attrib in _ATTRIB_DEFAULTS.get(element_, {}):
            text = " ".join(value) if isinstance(value, list) else _strval(value)
            if _ATTRIB_DEFAULTS[element_][attrib] == text:
                continue
        out.append((attrib, value))
    attribs = dict(out)
    if element_ == "link" and _strval(attribs.get("type")) == "text/css":
        out = [(k, v) for k, v in out if k != "type"]
    if element_ == "input":
        type_, value = attribs.get("type"), attribs.get("value")
        if type_ in ("checkbox", "radio"):
            if value == "on":
                out = [(k, v) for k, v in out if k != "value"]
        elif type_ != "submit" and value == "":
            out = [(k, v) for k, v in out if k != "value"]
    if element_ == "select" and "size" in attribs:
        multiple = "multiple" in [v for _, v in out] or attribs.get("multiple", False) is not False
        if _strval(attribs["size"]) == ("4" if multiple else "1"):
            out = [(k, v) for k, v in out if k != "size"]
    return out


def _strval(value) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "1"
    return str(value)


def expand_attributes(attribs: Attribs) -> str:
    """Given an associative array of element attributes, generate a string to stick after the element name in HTML
    output. Like ['href' => 'https://www.mediawiki.org/'] becomes something like ' href="https://www.mediawiki.org"'.
    Again, this is like Xml::expandAttributes(), but it implements some HTML5-specific tweaks. A value of False or
    None omits the attribute; a list of values for class/accesskey/rel is joined with spaces."""
    ret = []
    for key, value in _items(attribs):
        if value is False or value is None:
            continue
        # For boolean attributes, support ['foo'] instead of requiring ['foo' => 'meaningless'].
        if isinstance(key, int) and str(value).lower() in BOOL_ATTRIBS:
            key = value
        key = str(key).lower()
        if key in ("class", "accesskey", "rel"):  # space-separated list attributes
            if isinstance(value, dict):
                parts = []
                for k, v in value.items():
                    if isinstance(v, str):
                        if v not in value:
                            parts += [p for p in v.split(" ") if p not in ("", " ")]
                    elif v:
                        parts.append(k)
            elif isinstance(value, list):
                parts = [p for v in value for p in str(v).split(" ") if p not in ("", " ")]
            else:
                parts = [p for p in _strval(value).split(" ") if p not in ("", " ")]
            value = " ".join(dict.fromkeys(parts))  # array_unique keeps the first occurrence
        elif isinstance(value, (list, dict)):
            raise ValueError(f"HTML attribute {key} can not contain a list of values")
        elif key in BOOL_ATTRIBS:
            ret.append(f' {key}=""')
            continue
        enc = htmlspecialchars(_strval(value)).replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;")
        ret.append(f' {key}="{enc}"')
    return "".join(ret)

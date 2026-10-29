# Ported from the ParserFunctions extension 1.6.0 for MediaWiki 1.39 (branch REL1_39 as released with MediaWiki
# 1.39.0, commit 4b0abc7f9fdc4593dc9b2db0b3fd5a4e76fc8e7a): includes/ParserFunctions.php, includes/Hooks.php,
# ParserFunctions.i18n.magic.php and extension.json (https://www.mediawiki.org/wiki/Extension:ParserFunctions),
# (C) Tim Starling, Robert Rohde, Ross McClure, Juraj Simlovic and other ParserFunctions contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; English only (#time's language argument is
# ignored); no Scribunto library, no language variants; the time cache and #time counter are per parse, relative
# dates ("+1 day") count from the parse's timestamp (PHP's DateTime: from the clock), and year 0 is out of range;
# LinkCache is the titles #ifexist looked up in the parse; the string functions follow PHP's mb_* functions on
# Python strings; #explode with a non-numeric negative position returns '' (as the later fix T403241) and #pos with
# a negative offset before the start of the string returns '' instead of raising PHP's TypeError/ValueError.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""ParserFunctions: {{#if:}}, {{#ifeq:}}, {{#switch:}}, {{#expr:}}, {{#time:}}, ... and the string functions.

Settings (MediaWiki's $wgPF... globals), fields of the parser's Config:
  - pf_enable_string_functions ($wgPFEnableStringFunctions): default False (MediaWiki), True on the BI wiki
    (config.BIKI) and in the parser tests (the extension's ParserTestGlobals hook, parsertests.EXT_TEST_GLOBALS);
  - pf_string_length_limit ($wgPFStringLengthLimit): default 1000.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Optional, Union

from ..html import htmlspecialchars
from ..messages import msg
from ..parser_preprocess import SFH_OBJECT_ARGS
from ..sanitizer import decode_char_references
from ..site import NS_MEDIA
from ..title import Title
from .expr import ExprError, ExprParser
from .phpdatetime import YearOutOfRange, parse_datetime, sprintf_date

# $wgPFEnableStringFunctions and $wgPFStringLengthLimit (extension.json defaults)
ENABLE_STRING_FUNCTIONS = False
STRING_LENGTH_LIMIT = 1000

# ~10 seconds
MAX_TIME_CHARS = 6000

# ParserFunctions.i18n.magic.php, English: id -> (case sensitive, synonyms)
MAGIC_WORDS = {
    "expr": (False, ("expr",)),
    "if": (False, ("if",)),
    "ifeq": (False, ("ifeq",)),
    "ifexpr": (False, ("ifexpr",)),
    "iferror": (False, ("iferror",)),
    "switch": (False, ("switch",)),
    "default": (False, ("#default",)),
    "ifexist": (False, ("ifexist",)),
    "time": (False, ("time",)),
    "timel": (False, ("timel",)),
    "rel2abs": (False, ("rel2abs",)),
    "titleparts": (False, ("titleparts",)),
    "len": (False, ("len",)),
    "pos": (False, ("pos",)),
    "rpos": (False, ("rpos",)),
    "sub": (False, ("sub",)),
    "count": (False, ("count",)),
    "replace": (False, ("replace",)),
    "explode": (False, ("explode",)),
    "urldecode": (False, ("urldecode",)),
}

_PHP_WS = " \t\n\r\0\x0b"
_NUMERIC = re.compile(r"[ \t\n\r\x0b\f]*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[ \t\n\r\x0b\f]*\Z")
_INTEGER = re.compile(r"[ \t\n\r\x0b\f]*[+-]?\d+[ \t\n\r\x0b\f]*\Z")
_LEADING_NUMERIC = re.compile(r"[ \t\n\r\x0b\f]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
_ERROR_REGEX = re.compile(r'<(?:strong|span|p|div)[ \t\n\r\x0b\f](?:[^ \t\n\r\x0b\f>]*[ \t\n\r\x0b\f]+)*?'
                          r'class="(?:[^" \t\n\r\x0b\f>]*[ \t\n\r\x0b\f]+)*?error(?:[ \t\n\r\x0b\f][^">]*)?"')
PHP_INT_MAX = 2 ** 63 - 1


# ---- PHP helpers -------------------------------------------------------------------------------------------------


def _trim(s: str) -> str:
    return s.strip(_PHP_WS)


def php_is_numeric(s) -> bool:
    """is_numeric() of PHP 8: leading and trailing whitespace allowed, no hex."""
    if isinstance(s, bool):
        return False
    if isinstance(s, (int, float)):
        return True
    return isinstance(s, str) and _NUMERIC.match(s) is not None


def _numeric_value(s: str) -> Union[int, float]:
    if _INTEGER.match(s):
        v = int(s.strip())
        if -PHP_INT_MAX - 1 <= v <= PHP_INT_MAX:
            return v
        return float(v)
    return float(s.strip())


def _numeric_string(s: str) -> Optional[tuple[bool, Union[int, float], int]]:
    """is_numeric_string_ex() of PHP 8: None for a non-numeric string, else (is_double, value, oflow), where oflow
    is 1 or -1 for an integer string beyond PHP_INT_MAX/PHP_INT_MIN (then a double), else 0."""
    if _NUMERIC.match(s) is None:
        return None
    if _INTEGER.match(s):
        v = int(s.strip(" \t\n\r\x0b\f"))
        if -PHP_INT_MAX - 1 <= v <= PHP_INT_MAX:
            return False, v, 0
        return True, float(v), 1 if v > 0 else -1
    return True, float(s.strip(" \t\n\r\x0b\f")), 0


def php_loose_equals(a: str, b: str) -> bool:
    """$a == $b on two strings in PHP 8 (zendi_smart_str_equals()): numeric strings compare as numbers
    ("01" == "1", "1e3" == "1000"), others as strings."""
    n1 = _numeric_string(a)
    n2 = _numeric_string(b) if n1 is not None else None
    if n1 is None or n2 is None:
        return a == b
    (double1, v1, oflow1), (double2, v2, oflow2) = n1, n2
    if oflow1 != 0 and oflow1 == oflow2 and v1 - v2 == 0.0:
        # both values are integers overflown to the same side, both are double comparison may have resulted in
        # crucial accuracy lost
        return a == b
    if double1 or double2:
        if not double1:
            if oflow2:
                # 2nd operand is integer > LONG_MAX (oflow2==1) or < LONG_MIN (-1)
                return False
            v1 = float(v1)
        elif not double2:
            if oflow1:
                return False
            v2 = float(v2)
        elif v1 == v2 and not math.isfinite(v1):
            # Both values overflowed and have the same sign, so a numeric comparison would be inaccurate
            return a == b
        return v1 == v2
    # they both have to be long's
    return v1 == v2


def php_intval(s) -> int:
    """(int) of a string: its leading number ("12abc" is 12, "1e3" is 1000), 0 if there is none."""
    if isinstance(s, bool):
        return int(s)
    if isinstance(s, int):
        return s
    if isinstance(s, float):
        return int(s) if s == s and abs(s) != float("inf") else 0
    m = _LEADING_NUMERIC.match(s or "")
    if not m:
        return 0
    num = m.group(1)
    if re.fullmatch(r"[+-]?\d+", num):
        return max(min(int(num), PHP_INT_MAX), -PHP_INT_MAX - 1)
    f = float(num)
    return int(f) if abs(f) < 2 ** 63 else (PHP_INT_MAX if f > 0 else -PHP_INT_MAX - 1)


def _php_number(s) -> Union[int, float]:
    """The number a string is in PHP arithmetic: a numeric or leading-numeric string's int or float ("-1.5abc" is
    -1.5, with a warning in PHP); 0 for one without a number (PHP 8 throws a TypeError there)."""
    if isinstance(s, (int, float)):
        return s
    m = _LEADING_NUMERIC.match(s or "")
    if not m:
        return 0
    num = m.group(1)
    if re.fullmatch(r"[+-]?\d+", num):
        v = int(num)
        return v if -PHP_INT_MAX - 1 <= v <= PHP_INT_MAX else float(v)
    return float(num)


def php_truthy(value) -> bool:
    """PHP's boolean conversion: "", "0", 0, 0.0, null and false are false."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value not in ("", "0")
    return bool(value)


def _compare_with_zero(s, zero_cmp: str) -> bool:
    """``$s >= 0`` / ``$s < 0`` in PHP 8 for a string or int ``s``: numerically for numbers and numeric strings,
    else as strings against "0"."""
    if isinstance(s, (int, float)) or php_is_numeric(s):
        v = s if isinstance(s, (int, float)) else _numeric_value(s)
        return v >= 0 if zero_cmp == ">=" else v < 0
    return s >= "0" if zero_cmp == ">=" else s < "0"


def mb_substr(s: str, start: int, length: Optional[int] = None) -> str:
    n = len(s)
    if start < 0:
        start = max(n + start, 0)
    if start > n:
        return ""
    if length is None:
        return s[start:]
    if length < 0:
        end = n + length
        return s[start:end] if end > start else ""
    return s[start:start + length]


def php_array_slice(items: list, offset: int, length: Optional[int] = None) -> list:
    n = len(items)
    if offset > n:
        return []
    if offset < 0:
        offset = max(n + offset, 0)
    if length is None:
        return items[offset:]
    if length < 0:
        end = n + length
        return items[offset:end] if end > offset else []
    return items[offset:offset + length]


def _error(message: str) -> str:
    return '<strong class="error">' + message + "</strong>"


def _site(parser):
    return parser._preprocessing_site()


# ---- per-parse state ----------------------------------------------------------------------------------------------


def _parse_state(parser) -> dict:
    """The extension's state for the current parse (PHP keeps it in statics reset by the ParserClearState hook)."""
    state = getattr(parser, "_parserfunctions_state", None)
    if state is None or state["output"] is not parser.output:
        state = {"output": parser.output, "time_chars": 0, "time_cache": {}, "checked_links": {}}
        parser._parserfunctions_state = state
    return state


_EXPR_PARSER = ExprParser()


# ---- the functions ------------------------------------------------------------------------------------------------


def expr(parser, expr_: str = "") -> str:
    """{{#expr: expression }}"""
    try:
        return _EXPR_PARSER.do_expression(expr_)
    except ExprError as e:
        return _error(htmlspecialchars(e.get_user_friendly_message()))


def ifexpr(parser, frame, args: list):
    """{{#ifexpr: expression | value if true | value if false }}"""
    expr_ = _trim(frame.expand(args[0])) if len(args) > 0 else ""
    then = args[1] if len(args) > 1 else ""
    else_ = args[2] if len(args) > 2 else ""

    try:
        result = _EXPR_PARSER.do_expression(expr_)
        if php_is_numeric(result):
            result = float(result)
        result = then if php_truthy(result) else else_
    except ExprError as e:
        return _error(htmlspecialchars(e.get_user_friendly_message()))

    if not isinstance(result, str):
        result = _trim(frame.expand(result))
    return result


def if_(parser, frame, args: list) -> str:
    """{{#if: test string | value if test string is not empty | value if test string is empty }}"""
    test = _trim(frame.expand(args[0])) if len(args) > 0 else ""
    if test != "":
        return _trim(frame.expand(args[1])) if len(args) > 1 else ""
    return _trim(frame.expand(args[2])) if len(args) > 2 else ""


def ifeq(parser, frame, args: list) -> str:
    """{{#ifeq: string 1 | string 2 | value if identical | value if different }}"""
    left = _decode_trim_expand(args[0], frame)[0] if len(args) > 0 else ""
    right = _decode_trim_expand(args[1], frame)[0] if len(args) > 1 else ""

    # Strict compare is not possible here. 01 should equal 1 for example.
    if php_loose_equals(left, right):
        return _trim(frame.expand(args[2])) if len(args) > 2 else ""
    return _trim(frame.expand(args[3])) if len(args) > 3 else ""


def iferror(parser, frame, args: list) -> str:
    """{{#iferror: test string | value if error | value if no error }}

    Error is when the input string contains an HTML object with class="error", as generated by other parser
    functions such as #expr, #time and #rel2abs."""
    test = _trim(frame.expand(args[0])) if len(args) > 0 else ""
    then = args[1] if len(args) > 1 else False
    else_ = args[2] if len(args) > 2 else False

    if _ERROR_REGEX.search(test):
        result = then
    elif else_ is False:
        result = test
    else:
        result = else_
    if result is False:
        return ""
    return _trim(frame.expand(result))


def switch(parser, frame, args: list) -> str:
    """{{#switch: comparison string | case = result | case = result | ... | default result }}"""
    if not args:
        return ""
    args = list(args)
    primary = _decode_trim_expand(args.pop(0), frame)[0]
    found = default_found = False
    default = None
    last_item_had_no_equals = False
    last_item = ""
    mw_default = parser.magic_words.get("default")
    for arg in args:
        bits = arg.split_arg()
        name_node = bits["name"]
        index = bits["index"]
        value_node = bits["value"]

        if index == "":
            # Found "="
            last_item_had_no_equals = False
            if found:
                # Multiple input match
                return _trim(frame.expand(value_node))
            test = _decode_trim_expand(name_node, frame)[0]
            if php_loose_equals(test, primary):
                # Found a match, return now
                return _trim(frame.expand(value_node))
            elif default_found or mw_default.match_start_to_end(test):
                default = value_node
                default_found = False
            # else wrong case, continue
        else:
            # Multiple input, single output
            # If the value matches, set a flag and continue
            last_item_had_no_equals = True
            # last_item is an "out" variable
            decoded_test, last_item = _decode_trim_expand(value_node, frame)
            if php_loose_equals(decoded_test, primary):
                found = True
            elif mw_default.match_start_to_end(decoded_test):
                default_found = True
    # Default case
    # Check if the last item had no = sign, thus specifying the default case
    if last_item_had_no_equals:
        return last_item
    elif default is not None:
        return _trim(frame.expand(default))
    return ""


def rel2abs(parser, to: str = "", from_: str = "") -> str:
    """{{#rel2abs: path }} or {{#rel2abs: path | base path }}

    Returns the absolute path to a subpage, relative to the current article title. Treats titles as slash-separated
    paths. Following subpage link syntax instead of standard path syntax, an initial slash is treated as a relative
    path, and vice versa."""
    from_ = _trim(from_)
    if from_ == "":
        from_ = parser.get_title().prefixed_text

    to = to.rstrip(" /")

    # if we have an empty path, or just one containing a dot
    if to in ("", "."):
        return from_

    # if the path isn't relative
    if not to.startswith("/") and not to.startswith("./") and not to.startswith("../") and to != "..":
        from_ = ""
    # Make a long path, containing both, enclose it in /.../
    full_path = "/" + from_ + "/" + to + "/"

    # remove redundant current path dots
    full_path = re.sub(r"/(\./)+", "/", full_path)

    # remove double slashes
    full_path = re.sub(r"/{2,}", "/", full_path)

    # remove the enclosing slashes now
    full_path = full_path.strip("/")
    exploded = full_path.split("/")
    new_exploded: list[str] = []

    for current in exploded:
        if current == "..":  # removing one level
            if not new_exploded:
                # attempted to access a node above root node
                return _error(htmlspecialchars(msg("pfunc_rel2abs_invalid_depth", full_path)))
            # remove last level from the stack
            new_exploded.pop()
        else:
            # add the current level to the stack
            new_exploded.append(current)

    # we can now join it again
    return "/".join(new_exploded)


def _ifexist_internal(parser, frame, titletext: str = "", then=None, else_=None):
    title = Title.new_from_text(titletext, site=_site(parser))
    # (LanguageConverter::findVariantLink(): no variants)
    if title:
        link_cache = parser.get_link_cache()
        if title.namespace == NS_MEDIA:
            # If namespace is specified as NS_MEDIA, then we want to check the physical file, not the "description"
            # page.
            if not parser.increment_expensive_function_count():
                return else_
            # (RepoGroup::findFile() follows a redirect of the file page, as for bug 32031)
            file = link_cache.find_file(title)
            if not file:
                parser.output_add_image(title.db_key)
                return else_
            parser.output_add_image(file.get_name())
            return then if file.exists() else else_
        elif title.is_special_page():
            # Don't bother with the count for special pages, since their existence can be checked without accessing
            # the database.
            return then if link_cache.special_pages.exists(title.db_key) else else_
        elif title.is_external():
            # Can't check the existence of pages on other sites, so just return else. Makes a sort of sense, since
            # they don't exist _locally_.
            return else_
        else:
            pdbk = title.prefixed_db_key
            # (LinkCache::getGoodLinkID() / isBadLink(): the titles looked up so far in this parse)
            checked = _parse_state(parser)["checked_links"]
            if pdbk in checked and checked[pdbk] != 0:
                parser.output_add_link(title, checked[pdbk])
                return then
            elif pdbk in checked:
                parser.output_add_link(title, 0)
                return else_
            if not parser.increment_expensive_function_count():
                return else_
            id_ = 1 if link_cache.exists(title) else 0  # $title->getArticleID(): pages have no IDs here
            checked[pdbk] = id_
            parser.output_add_link(title, id_)

            # bug 70495: don't just check whether the ID != 0
            if link_cache.exists(title):
                return then
    return else_


def ifexist(parser, frame, args: list) -> str:
    """{{#ifexist: page title | value if exists | value if doesn't exist }}"""
    title = _trim(frame.expand(args[0])) if len(args) > 0 else ""
    then = args[1] if len(args) > 1 else None
    else_ = args[2] if len(args) > 2 else None

    result = _ifexist_internal(parser, frame, title, then, else_)
    if result is None:
        return ""
    return _trim(frame.expand(result))


def _now(parser) -> datetime:
    """ParserOptions::getTimestamp() as a datetime: ``parser.timestamp`` (a datetime, Unix time or TS_MW string),
    else the current time."""
    from ..coreparserfunctions import options_timestamp, to_datetime

    return to_datetime(options_timestamp(parser))


def _time_common(parser, frame=None, format_: str = "", date: str = "", language: str = "",
                 local: bool = False) -> str:
    """Used by time() and local_time()"""
    from ..coreparserfunctions import local_zone, php_date

    state = _parse_state(parser)
    now = _now(parser)
    if date == "":
        cache_key = php_date(now, "YmdHis")
        u = now.astimezone(timezone.utc)
        date = f"{u.year:04d}-{u.month:02d}-{u.day:02d}T{u.hour:02d}:{u.minute:02d}:{u.second:02d}Z"  # TS_ISO_8601
    else:
        cache_key = date
    key = (format_, cache_key, language, bool(local))
    if key in state["time_cache"]:
        return state["time_cache"][key]

    # compute the timestamp string ts
    invalid_time = False
    too_small = too_big = False
    ts = ""
    tz = timezone.utc
    try:
        # Default input timezone is UTC.
        utc = timezone.utc

        # Correct for DateTime interpreting 'XXXX' as XX:XX o'clock
        if re.fullmatch(r"[0-9]{4}", date):
            date = "00:00 " + date

        # Parse date
        # UTC is a default input timezone.
        date_object = parse_datetime(date, utc, now)

        # Set output timezone.
        tz = local_zone(parser) if local else utc
        try:
            date_object = date_object.astimezone(tz)
        except OverflowError:
            # the zone moves the date out of the years Python holds: after 9999 ($ts >= 100000000000000) or, from
            # 0001-01-01, into year 0 (PHP formats year 0; Python cannot, so it is reported as too small)
            raise YearOutOfRange(10000 if date_object.year == 9999 else 0) from None
        # Generate timestamp (format( 'YmdHis' ))
        d = date_object
        ts = f"{d.year:04d}{d.month:02d}{d.day:02d}{d.hour:02d}{d.minute:02d}{d.second:02d}"
    except YearOutOfRange as e:
        # PHP holds the year and the checks of $ts below reject it: "-0001..." < 0 is too small, a fifteen-digit
        # year 10000 or later too big. (Year 0, which PHP accepts, is reported as too small: Python's datetime
        # cannot hold it.)
        if e.year < 1:
            too_small = True
        else:
            too_big = True
    except (ValueError, OverflowError):
        invalid_time = True

    # format the timestamp and return the result
    if invalid_time:
        result = _error(htmlspecialchars(msg("pfunc_time_error")))
    else:
        state["time_chars"] += len(format_.encode("utf-8"))
        if state["time_chars"] > MAX_TIME_CHARS:
            return _error(htmlspecialchars(msg("pfunc_time_too_long")))
        if too_small:  # Language can't deal with BC years
            return _error(htmlspecialchars(msg("pfunc_time_too_small")))
        if too_big:  # Language can't deal with years after 9999
            return _error(htmlspecialchars(msg("pfunc_time_too_big")))
        # (A valid language code would use that language; only English is ported: the content language.)
        result = sprintf_date(format_, ts, tz)
    state["time_cache"][key] = result
    return result


def time(parser, frame, args: list) -> str:
    """{{#time: format string }}, {{#time: format string | date/time object }},
    {{#time: format string | date/time object | language code }}"""
    format_ = _trim(frame.expand(args[0])) if len(args) > 0 else ""
    date = _trim(frame.expand(args[1])) if len(args) > 1 else ""
    language = _trim(frame.expand(args[2])) if len(args) > 2 else ""
    local = len(args) > 3 and php_truthy(_trim(frame.expand(args[3])))
    return _time_common(parser, frame, format_, date, language, local)


def local_time(parser, frame, args: list) -> str:
    """{{#timel: ... }}: identical to {{#time: ... }}, except that it uses the local time of the wiki (as set in
    $wgLocaltimezone) when no date is given."""
    format_ = _trim(frame.expand(args[0])) if len(args) > 0 else ""
    date = _trim(frame.expand(args[1])) if len(args) > 1 else ""
    language = _trim(frame.expand(args[2])) if len(args) > 2 else ""
    return _time_common(parser, frame, format_, date, language, True)


def titleparts(parser, title: str = "", parts="0", offset="0") -> str:
    """Obtain a specified number of slash-separated parts of a title, e.g. {{#titleparts:Hello/World|1}} =>
    "Hello". ``parts``: number of parts to keep; ``offset``: offset starting at 1."""
    parts = php_intval(parts)
    offset = php_intval(offset)
    ntitle = Title.new_from_text(title, site=_site(parser))
    if ntitle is not None:
        bits = ntitle.prefixed_text.split("/", 24)
        if offset > 0:
            offset -= 1
        if parts == 0:
            return "/".join(php_array_slice(bits, offset))
        return "/".join(php_array_slice(bits, offset, parts))
    return title


def _length_limit(parser) -> int:
    return getattr(parser.config, "pf_string_length_limit", STRING_LENGTH_LIMIT)


def _check_length(parser, text: str) -> bool:
    """Verifies parameter is less than max string length."""
    return len(text) < _length_limit(parser)


def _too_long_error(parser) -> str:
    """Generates error message. Called when string is too long."""
    return _error(htmlspecialchars(msg("pfunc_string_too_long", f"{_length_limit(parser):,}")))


def run_len(parser, in_str: str = "") -> int:
    """{{#len:string}}: reports number of characters in string."""
    return len(parser.kill_markers(str(in_str)))


def run_pos(parser, in_str: str = "", in_needle: str = "", in_offset="0"):
    """{{#pos: string | needle | offset}}: finds first occurrence of "needle" in "string" starting at "offset".

    Note: If the needle is an empty string, single space is used instead.
    Note: If the needle is not found, empty string is returned."""
    in_str = parser.kill_markers(str(in_str))
    in_needle = parser.kill_markers(str(in_needle))

    if not _check_length(parser, in_str) or not _check_length(parser, in_needle):
        return _too_long_error(parser)

    if in_needle == "":
        in_needle = " "

    offset = min(php_intval(in_offset), len(in_str))
    if offset < 0:
        offset += len(in_str)
        if offset < 0:
            return ""  # PHP: ValueError (offset not contained in string)
    pos = in_str.find(in_needle, offset)
    return "" if pos == -1 else pos


def run_rpos(parser, in_str: str = "", in_needle: str = ""):
    """{{#rpos: string | needle}}: finds last occurrence of "needle" in "string".

    Note: If the needle is an empty string, single space is used instead.
    Note: If the needle is not found, -1 is returned."""
    in_str = parser.kill_markers(str(in_str))
    in_needle = parser.kill_markers(str(in_needle))

    if not _check_length(parser, in_str) or not _check_length(parser, in_needle):
        return _too_long_error(parser)

    if in_needle == "":
        in_needle = " "

    return in_str.rfind(in_needle)


def run_sub(parser, in_str: str = "", in_start="0", in_length="0") -> str:
    """{{#sub: string | start | length }}: returns substring of "string" starting at "start" and having "length"
    characters.

    Note: If length is zero, the rest of the input is returned.
    Note: A negative value for "start" operates from the end of the "string".
    Note: A negative value for "length" returns a string reduced in length by that amount."""
    in_str = parser.kill_markers(str(in_str))

    if not _check_length(parser, in_str):
        return _too_long_error(parser)

    if php_intval(in_length) == 0:
        return mb_substr(in_str, php_intval(in_start))
    return mb_substr(in_str, php_intval(in_start), php_intval(in_length))


def run_count(parser, in_str: str = "", in_sub_str: str = ""):
    """{{#count: string | substr }}: returns number of occurrences of "substr" in "string".

    Note: If "substr" is empty, a single space is used."""
    in_str = parser.kill_markers(str(in_str))
    in_sub_str = parser.kill_markers(str(in_sub_str))

    if not _check_length(parser, in_str) or not _check_length(parser, in_sub_str):
        return _too_long_error(parser)

    if in_sub_str == "":
        in_sub_str = " "

    return in_str.count(in_sub_str)


def run_replace(parser, in_str: str = "", in_replace_from: str = "", in_replace_to: str = "", in_limit="-1") -> str:
    """{{#replace:string | from | to | limit }}: replaces each occurrence of "from" in "string" with "to". At most
    "limit" replacements are performed.

    Note: Armored against replacements that would generate huge strings.
    Note: If "from" is an empty string, single space is used instead."""
    in_str = parser.kill_markers(str(in_str))
    in_replace_from = parser.kill_markers(str(in_replace_from))
    in_replace_to = parser.kill_markers(str(in_replace_to))

    if (not _check_length(parser, in_str) or not _check_length(parser, in_replace_from)
            or not _check_length(parser, in_replace_to)):
        return _too_long_error(parser)

    if in_replace_from == "":
        in_replace_from = " "

    # Precompute limit to avoid generating enormous string:
    diff = len(in_replace_to) - len(in_replace_from)
    if diff > 0:
        limit = int((_length_limit(parser) - len(in_str)) / diff) + 1
    else:
        limit = -1

    in_limit = php_intval(in_limit)
    if in_limit >= 0:
        if limit > in_limit or limit == -1:
            limit = in_limit

    # (preg_replace with a quoted pattern and an escaped replacement: a plain replacement; limit -1 is no limit)
    result = in_str.replace(in_replace_from, in_replace_to, limit if limit >= 0 else -1)

    if not _check_length(parser, result):
        return _too_long_error(parser)
    return result


def run_explode(parser, in_str: str = "", in_div: str = "", in_pos="0", in_lim=None) -> str:
    """{{#explode:string | delimiter | position | limit}}: breaks "string" into chunks separated by "delimiter"
    and returns the chunk identified by "position".

    Note: Negative position can be used to specify tokens from the end.
    Note: If the divider is an empty string, single space is used instead.
    Note: Empty string is returned if there are not enough exploded chunks."""
    from ..ppframe import _php_key

    in_str = parser.kill_markers(str(in_str))
    in_div = parser.kill_markers(str(in_div))

    if in_div == "":
        in_div = " "

    if not _check_length(parser, in_str) or not _check_length(parser, in_div):
        return _too_long_error(parser)

    # preg_split( '/' . preg_quote( $inDiv ) . '/u', $inStr, (int)$inLim )
    limit = php_intval(in_lim) if in_lim is not None else 0
    if limit in (0, -1):
        matches = in_str.split(in_div)
    elif limit > 0:
        matches = in_str.split(in_div, limit - 1)
    else:
        matches = [in_str]

    if _compare_with_zero(in_pos, ">="):
        key = _php_key(in_pos)
        if isinstance(key, int) and 0 <= key < len(matches):
            return matches[key]
        return ""
    if _compare_with_zero(in_pos, "<"):
        # count( $matches ) + $inPos: an int, or a float for "-1.5" (truncated as an array key: -0.5 is key 0)
        index = len(matches) + _php_number(in_pos)
        if isinstance(index, float):
            index = int(index) if math.isfinite(index) else 0
        if 0 <= index < len(matches):
            return matches[index]
    return ""


def run_url_decode(parser, in_str: str = "") -> str:
    """{{#urldecode:string}}: decodes URL-encoded (like%20that) strings."""
    from ..coreparserfunctions import urldecode

    in_str = parser.kill_markers(str(in_str))
    if not _check_length(parser, in_str):
        return _too_long_error(parser)
    return urldecode(in_str)


def _decode_trim_expand(obj, frame) -> tuple[str, str]:
    """Take a PPNode (-ish thing), expand it, remove entities, and trim. For use when doing string comparisons,
    where user expects entities to be equal for what they stand for (e.g. comparisons with {{PAGENAME}}). Returns
    the trimmed, expanded and entity reference decoded version, and the expanded and trimmed version with char
    refs intact (PHP's by-reference argument)."""
    expanded = frame.expand(obj)
    return _trim(decode_char_references(expanded)), _trim(expanded)


# ---- registration (Hooks::onParserFirstCallInit) ------------------------------------------------------------------


def register_magic_words(factory) -> None:
    """The extension's magic words (ParserFunctions.i18n.magic.php, English)."""
    for id_, (case_sensitive, synonyms) in MAGIC_WORDS.items():
        if id_ not in factory.words:
            factory.register(id_, case_sensitive, *synonyms)


def register(parser, enable_string_functions: Optional[bool] = None) -> None:
    """Registers our parser functions with a fresh parser. ``enable_string_functions``: $wgPFEnableStringFunctions
    (default: the parser config's pf_enable_string_functions, else MediaWiki's default, False)."""
    register_magic_words(parser.magic_words)

    # These functions accept DOM-style arguments
    parser.set_function_hook("if", if_, SFH_OBJECT_ARGS)
    parser.set_function_hook("ifeq", ifeq, SFH_OBJECT_ARGS)
    parser.set_function_hook("switch", switch, SFH_OBJECT_ARGS)
    parser.set_function_hook("ifexist", ifexist, SFH_OBJECT_ARGS)
    parser.set_function_hook("ifexpr", ifexpr, SFH_OBJECT_ARGS)
    parser.set_function_hook("iferror", iferror, SFH_OBJECT_ARGS)
    parser.set_function_hook("time", time, SFH_OBJECT_ARGS)
    parser.set_function_hook("timel", local_time, SFH_OBJECT_ARGS)

    parser.set_function_hook("expr", expr)
    parser.set_function_hook("rel2abs", rel2abs)
    parser.set_function_hook("titleparts", titleparts)

    # String Functions: enable if configured
    if enable_string_functions is None:
        enable_string_functions = getattr(parser.config, "pf_enable_string_functions", ENABLE_STRING_FUNCTIONS)
    if enable_string_functions:
        parser.set_function_hook("len", run_len)
        parser.set_function_hook("pos", run_pos)
        parser.set_function_hook("rpos", run_rpos)
        parser.set_function_hook("sub", run_sub)
        parser.set_function_hook("count", run_count)
        parser.set_function_hook("replace", run_replace)
        parser.set_function_hook("explode", run_explode)
        parser.set_function_hook("urldecode", run_url_decode)

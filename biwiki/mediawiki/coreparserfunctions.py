# Ported from MediaWiki 1.39 includes/parser/CoreParserFunctions.php (https://www.mediawiki.org/), (C) MediaWiki
# contributors; with the parts of other files these functions need: the English behaviour of
# includes/language/Language.php (formatNum, parseFormattedNumber, ucfirst/lcfirst/uc/lc, convertPlural, gender,
# convertGrammar, embedBidi, getDirMark, month and weekday names, time, sprintfDate, userAdjust),
# includes/language/LanguageCode.php (bcp47), includes/languages/data/Names.php and LanguageNameUtils
# (getLanguageName), includes/parser/DateFormatter.php, includes/specialpage/SpecialPageFactory.php (resolveAlias,
# getLocalNameFor, the core page list) with $specialPageAliases of languages/messages/MessagesEn.php, and from
# includes/parser/Parser.php: guessSectionNameFromWikiText, stripSectionName, parseWidthParam, getRevisionRecordObject,
# getRevisionTimestamp, getRevisionUser, getRevisionSize, fetchCurrentRevisionRecordOfTitle,
# isCurrentRevisionOfTitleCached.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the class of static methods became module-level
# functions; English only; no database: page revisions, site statistics, category counts, restrictions and files
# come from optional parser attributes (see "Parser interface" below), and are empty by default, as for MediaWiki's
# parser tests with an empty database; no hooks, user preferences or language variants.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Parser functions provided by MediaWiki core: {{ns:}}, {{urlencode:}}, {{formatnum:}}, {{#tag:}}, ...

Callbacks are called as ``cb(parser, *trimmed_args)`` (or ``cb(parser, frame, args)`` with SFH_OBJECT_ARGS) and
return a string or a dict mirroring PHP's mixed array: the text under key 0 plus flags such as ``found`` and
``noparse``.

Parser interface: besides PreprocessingMixin (get_title, get_output, kill_markers, marker_skip_callback,
add_tracking_category, increment_expensive_function_count, get_strip_list, extension_substitution,
fetch_current_revision_text, config, ot, input_size, var_cache) these optional attributes are read:

- ``timestamp``: ParserOptions::getTimestamp(), a ``datetime`` (UTC), a Unix time (int) or a TS_MW string;
  MediaWiki's parser tests use the int 123. Default: now.
- ``revision_id``: the revision being parsed (Parser::getRevisionId(); the parser tests use 1337). Default None.
- ``current_revision_record_callback(title, parser)``: the current RevisionRecord of a page, or None
  (ParserOptions::getCurrentRevisionRecordCallback()). Default: ``default_revision_record_callback``, a record
  built from ``parser.fetch_current_revision_text(title)`` (size and text; no id, timestamp or user).
- ``site_stats``: a SiteStats (SiteStats::pages() etc.). Default: all zero.
- ``category_counts(title)``: dict with all/pages/subcats/files for a category. Default: zeros.
- ``restrictions(title, action)``: list of protection levels. Default: none.
- ``find_file(name)``: an object with ``get_full_url()`` for {{filepath:}}. Default: no files.
- ``user_name``: the user (ParserOptions::getUserIdentity()). Default '127.0.0.1', as the parser tests.
- ``nowiki_stripped_tags``: extension tags whose {{#tag:}} contents get nowiki stripped (Parsoid's
  stripNowiki option, T299103; none in core).

Settings that are not in Config are read with getattr() and MediaWiki's defaults: allow_display_title (True),
restrict_display_title (True), allow_slow_parser_functions (False), miser_mode (False), american_dates (False),
local_tz_offset (from localtimezone).
"""
from __future__ import annotations

import functools
import inspect
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Callable, Optional, Union

from .html import htmlspecialchars, raw_element
from .messages import MESSAGES
from .parser_preprocess import SFH_NO_HASH, SFH_OBJECT_ARGS, wf_escape_wiki_text
from .ppframe import PROCESS_NOWIKI, STRIP_COMMENTS
from .quotes import do_quotes
from .sanitizer import (check_css, decode_char_references, decode_char_references_and_normalize, escape_id_for_link,
                        normalize_section_name_whitespace, remove_some_tags, safe_encode_attribute, strip_all_tags,
                        wf_url_protocols)
from .site import NS_CATEGORY, NS_FILE, NS_MEDIA, NS_MEDIAWIKI, NS_SPECIAL, php_urlencode, wf_urlencode
from .stringutils import delimiter_replace, php_strtr
from .title import MalformedTitleException, Title, get_title_codec

# ======================================================================================================================
# PHP helpers
# ======================================================================================================================

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_PHP_WS = " \t\n\r\v\f"
_NUMERIC = re.compile(r"[ \t\n\r\v\f]*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[ \t\n\r\v\f]*\Z")
_LEADING_NUMERIC = re.compile(r"[ \t\n\r\v\f]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
PHP_INT_MAX = 2 ** 63 - 1


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


def _php_strtolower(s: str) -> str:
    """strtolower(): ASCII letters only."""
    return s.translate(_ASCII_LOWER)


def _php_is_numeric(s: Any) -> bool:
    """is_numeric() of PHP 8: leading and trailing whitespace allowed, no hex."""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return True
    return isinstance(s, str) and _NUMERIC.match(s) is not None


def _php_floatval(s: Any) -> float:
    """(float) of a string: the leading numeric part, 0.0 if there is none."""
    if isinstance(s, (int, float)):
        return float(s)
    m = _LEADING_NUMERIC.match(s or "")
    return float(m.group(1)) if m else 0.0


def _php_intval(s: Any) -> int:
    """intval() of a string (PHP >= 7.1: "1e3" is 1000), saturating at the 64-bit limits."""
    if isinstance(s, bool):
        return int(s)
    if isinstance(s, int):
        return s
    if isinstance(s, float):
        return 0 if math.isnan(s) else int(max(min(s, PHP_INT_MAX), -PHP_INT_MAX - 1))
    m = _LEADING_NUMERIC.match(s or "")
    if not m:
        return 0
    num = m.group(1)
    if re.fullmatch(r"[+-]?\d+", num):
        return max(min(int(num), PHP_INT_MAX), -PHP_INT_MAX - 1)
    return _php_intval(float(num))


def _php_float_to_string(f: float) -> str:
    """(string) of a float: precision 14, PHP's spelling of exponents ("1.0E+20")."""
    if math.isnan(f):
        return "NAN"
    if math.isinf(f):
        return "INF" if f > 0 else "-INF"
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    s = "%.14G" % f
    if "E" in s:
        mantissa, exp = s.split("E")
        if "." not in mantissa:
            mantissa += ".0"
        sign = exp[0]
        exp = exp[1:].lstrip("0") or "0"
        s = f"{mantissa}E{sign}{exp}"
    return s


def _php_strval(value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "1"
    if isinstance(value, float):
        return _php_float_to_string(value)
    return str(value)


def _php_equals_zero_string(s: str) -> bool:
    """``$s == "0"`` in PHP 8: numeric strings compare as numbers."""
    return s == "0" or (_php_is_numeric(s) and float(s) == 0)


def rawurlencode(s: str) -> str:
    """rawurlencode(): RFC 3986, '~' kept, space as %20."""
    out = []
    for b in s.encode("utf-8", "surrogatepass"):
        c = chr(b)
        if c.isascii() and (c.isalnum() or c in "-_.~"):
            out.append(c)
        else:
            out.append(f"%{b:02X}")
    return "".join(out)


def urldecode(s: str) -> str:
    """urldecode(): '+' is a space, %XX a byte. Byte sequences that are not UTF-8 become U+FFFD, which no title
    accepts (PHP keeps the bytes, which no title accepts either)."""
    data = bytearray()
    i = 0
    raw = s.replace("+", " ").encode("utf-8", "surrogatepass")
    while i < len(raw):
        if raw[i] == 0x25 and re.fullmatch(rb"[0-9A-Fa-f]{2}", raw[i + 1:i + 3]):
            data.append(int(raw[i + 1:i + 3], 16))
            i += 3
        else:
            data.append(raw[i])
            i += 1
    return data.decode("utf-8", "replace")


def _site(parser):
    return parser.get_title().site


def _title_from_text(parser, text: Optional[str], default_namespace: int = 0) -> Optional[Title]:
    """Title::newFromText()"""
    return Title.new_from_text(text, default_namespace, site=_site(parser))


def _config_setting(parser, name: str, default: Any) -> Any:
    return getattr(parser.config, name, default)


def _set_output_flag(parser, flag: str) -> None:
    """ParserOutput::setOutputFlag(): kept in ``output.output_flags`` (a set) if the ParserOutput has one."""
    output = parser.get_output()
    setter = getattr(output, "set_output_flag", None)
    if callable(setter):
        setter(flag)
        return
    flags = getattr(output, "output_flags", None)
    if flags is None:
        try:
            flags = output.output_flags = set()
        except AttributeError:
            return
    flags.add(flag)


def _get_page_property(output, name: str) -> Optional[str]:
    return output.page_properties.get(name)


def _set_page_property(output, name: str, value: str) -> None:
    output.page_properties[name] = value


# ======================================================================================================================
# Messages (MessageCache and Message, as far as {{int:}} and the error messages here need them)
# ======================================================================================================================

def _replace_message_params(text: str, params: tuple) -> str:
    """Message::replaceParameters() for plain parameters: $1, $2, ... (missing ones stay)."""
    def sub(m: re.Match) -> str:
        n = int(m.group(1)) - 1
        return _php_strval(params[n]) if 0 <= n < len(params) else m.group(0)

    return re.sub(r"\$(\d+)", sub, text)


def _normalize_message_key(key: str) -> str:
    """MessageCache::normalizeKey(): spaces to underscores, first letter lower case."""
    lckey = key.replace(" ", "_")
    if lckey and ord(lckey[0]) < 128:
        return _php_strtolower(lckey[0]) + lckey[1:]
    return ENGLISH.lcfirst(lckey)


def fetch_message(parser, key: str) -> Optional[str]:
    """MessageCache::get() in the content language: the page MediaWiki:Key if it exists (database messages), else
    the English message; None (PHP false) if there is neither."""
    if key == "":
        return None
    lckey = _normalize_message_key(key)
    title = Title.make_title(NS_MEDIAWIKI, ENGLISH.ucfirst(lckey), site=_site(parser))
    rev = fetch_current_revision_record_of_title(parser, title)
    if rev is not None and rev.content is not None:
        return rev.content
    return MESSAGES.get(lckey)


def message_plain(parser, key: str, params: tuple = ()) -> str:
    """wfMessage( $key, $params )->plain(): the message with its parameters, not transformed; '⧼key⧽' if the
    message does not exist."""
    text = fetch_message(parser, key)
    if text is None:
        # Err on the side of safety, ensure that the output is always html safe in the event the message key is
        # missing, since in that case its highly likely the message key is user-controlled.
        return "⧼" + htmlspecialchars(key) + "⧽"
    return _replace_message_params(text, params)


def message_text(key: str, *params) -> str:
    """wfMessage( $key, ...$params )->inContentLanguage()->text() for messages without {{...}} transformations."""
    text = MESSAGES.get(key)
    if text is None:
        return "⧼" + htmlspecialchars(key) + "⧽"
    return _replace_message_params(text, params)


# ======================================================================================================================
# Language (English)
# ======================================================================================================================

WEEKDAY_MESSAGES = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
MONTH_MESSAGES = ("january", "february", "march", "april", "may_long", "june", "july", "august", "september",
                  "october", "november", "december")
MONTH_GENITIVE_MESSAGES = ("january-gen", "february-gen", "march-gen", "april-gen", "may-gen", "june-gen",
                           "july-gen", "august-gen", "september-gen", "october-gen", "november-gen", "december-gen")
MONTH_ABBREVIATED_MESSAGES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

LRE = "‪"  # U+202A LEFT-TO-RIGHT EMBEDDING
RLE = "‫"  # U+202B RIGHT-TO-LEFT EMBEDDING
PDF = "‬"  # U+202C POP DIRECTIONAL FORMATTING

_VALID_NUMBER_RE = re.compile(r"(-(?=[\d.]))?(\d+|(?=\.\d))(\.\d*)?([Ee][-+]?\d+)?")


class Language:
    """Language.php with the data of MessagesEn.php: no digit or separator transform tables, grouping "#,##0.###",
    the date format "dmy or mdy" ('dmy' unless $wgAmericanDates), 'H:i' as the time format."""

    def __init__(self, code: str = "en"):
        self.code = code

    def get_code(self) -> str:
        return self.code

    def get_html_code(self) -> str:
        return bcp47(self.code)

    def is_rtl(self) -> bool:
        return False

    # --- case ---

    def ucfirst(self, s: str) -> str:
        if not s:
            return ""
        octet_code = ord(s[0])
        # See https://en.wikipedia.org/wiki/ASCII#Printable_characters
        if octet_code < 96:
            # Assume this is an uppercase/uncased ASCII character
            return s
        elif octet_code < 128:
            # Assume this is a lowercase/uncased ASCII character
            return s[0].translate(_ASCII_UPPER) + s[1:]
        # Assume this is a multibyte character and mb_internal_encoding() is appropriate
        # (mbUpperChar(): mb_strtoupper(); $wgOverrideUcfirstCharacters is empty by default)
        return s[0].upper() + s[1:]

    def lcfirst(self, s: str) -> str:
        if not s:
            return ""
        octet_code = ord(s[0])
        if octet_code < 96:
            # Assume this is an uppercase/uncased ASCII character
            return s[0].translate(_ASCII_LOWER) + s[1:]
        elif octet_code < 128:
            # Assume this is a lowercase/uncased ASCII character
            return s
        return s[0].lower() + s[1:]

    def uc(self, s: str, first: bool = False) -> str:
        """mb_strtoupper(), or strtoupper() for ASCII text (the same thing then)."""
        return self.ucfirst(s) if first else s.upper()

    def lc(self, s: str, first: bool = False) -> str:
        return self.lcfirst(s) if first else s.lower()

    def case_fold(self, s: str) -> str:
        return self.uc(s)

    # --- numbers ---

    def format_num(self, number: Any) -> str:
        """Normally we output all numbers in plain en_US style, that is 293,291.235 for twohundredninetythreethousand-
        twohundredninetyone point twohundredthirtyfive. However this is not suitable for all languages, some such as
        Bengali (bn) want ২,৯৩,২৯১.২৩৫ and others such as Pakistan want ۲۹۳۲۹۱٫۲۳۵."""
        return self._format_num_internal(_php_strval(number), False, False)

    def format_num_no_separators(self, number: Any) -> str:
        """Front-end for non-commafied formatNum"""
        return self._format_num_internal(_php_strval(number), False, True)

    def _format_num_internal(self, number: str, no_translate: bool, no_separators: bool) -> str:
        if number == "":
            return number
        if number == "NAN":
            return message_text("formatnum-nan")
        if number == "INF":
            return "∞"
        if number == "-INF":
            return "−∞"
        if not _php_is_numeric(number):
            # For backwards-compat, apply formatNum piecewise on the valid numbers in the string. Don't split on
            # NAN/INF in this legacy case as they are likely to be found embedded inside non-numeric text.
            return _VALID_NUMBER_RE.sub(
                lambda m: self._format_num_internal(m.group(0), no_translate, no_separators), number)

        if not no_separators:
            # minimumGroupingDigits is null for English
            if number != "-0":
                number = _icu_format_en(number)

        if not no_translate:
            # T10327: Make our formatted numbers prettier by using a proper Unicode 'minus' character.
            number = number.replace("-", "−")

        # Remove any LRM or RLM characters generated from NumberFormatter, since directionality is handled outside
        # of this context.
        return php_strtr(number, {"‎": "", "‏": "", "؜": ""})

    def parse_formatted_number(self, number: str) -> str:
        if number == message_text("formatnum-nan"):
            return "NAN"
        if number == "∞":
            return "INF"
        # Accept either ASCII hyphen-minus or the unicode minus emitted by ::formatNum()
        number = number.replace("−", "-")
        if number == "-∞":
            return "-INF"
        # (no digit or separator transform tables in English)
        return number.replace(",", "")

    # --- plural, gender, grammar ---

    def convert_plural(self, count: Union[int, float], forms: list[str]) -> str:
        # Handle explicit n=pluralform cases
        result = self._handle_explicit_plural_forms(count, forms)
        if isinstance(result, str):
            return result
        forms = result
        if not forms:
            return ""
        plural_form = _plural_rule_index_en(count)
        plural_form = min(plural_form, len(forms) - 1)
        return forms[plural_form]

    @staticmethod
    def _handle_explicit_plural_forms(count: Union[int, float], forms: list[str]) -> Union[str, list[str]]:
        count_str = _php_strval(count)
        remaining = []
        for form in forms:
            if re.search(r"\d+=", form, re.I):
                pos = form.find("=")
                if form[:pos] == count_str:
                    return form[pos + 1:]
            else:
                remaining.append(form)
        return remaining

    @staticmethod
    def _pre_convert_plural(forms: list[str], count: int) -> list[str]:
        """array_pad( $forms, $count, end( $forms ) )"""
        forms = list(forms)
        while len(forms) < count:
            forms.append(forms[-1])
        return forms

    def gender(self, gender: str, forms: list[str]) -> str:
        if not forms:
            return ""
        forms = self._pre_convert_plural(forms, 2)
        if gender == "male":
            return forms[0]
        if gender == "female":
            return forms[1]
        return forms[2] if len(forms) > 2 else forms[0]

    def convert_grammar(self, word: str, case: str) -> str:
        """English has no $wgGrammarForms and no languages/data/grammarTransformations/en.json: the word itself."""
        return word

    # --- direction ---

    def embed_bidi(self, text: str = "") -> str:
        direction = _strong_dir_from_content(text)
        if direction == "ltr":
            # Wrap in LEFT-TO-RIGHT EMBEDDING ... POP DIRECTIONAL FORMATTING
            return LRE + text + PDF
        if direction == "rtl":
            # Wrap in RIGHT-TO-LEFT EMBEDDING ... POP DIRECTIONAL FORMATTING
            return RLE + text + PDF
        # No strong directionality: do not wrap
        return text

    def get_dir_mark(self, opposite: bool = False) -> str:
        lrm = "‎"  # LEFT-TO-RIGHT MARK, commonly abbreviated LRM
        rlm = "‏"  # RIGHT-TO-LEFT MARK, commonly abbreviated RLM
        if opposite:
            return lrm if self.is_rtl() else rlm
        return rlm if self.is_rtl() else lrm

    # --- dates ---

    def get_month_name(self, key: int) -> str:
        return message_text(MONTH_MESSAGES[key - 1])

    def get_month_name_gen(self, key: int) -> str:
        return message_text(MONTH_GENITIVE_MESSAGES[key - 1])

    def get_month_abbreviation(self, key: int) -> str:
        return message_text(MONTH_ABBREVIATED_MESSAGES[key - 1])

    def get_weekday_name(self, key: int) -> str:
        return message_text(WEEKDAY_MESSAGES[key - 1])

    def time(self, ts: str, adj: bool = False, format_: Union[bool, str] = True, local_tz_offset: int = 0) -> str:
        """The time of a TS_MW timestamp: the 'time' format of the default date preference, 'H:i' in English."""
        if adj:
            ts = self.user_adjust(ts, "", local_tz_offset)
        return self.sprintf_date("H:i", ts)

    @staticmethod
    def user_adjust(ts: Any, tz: str = "", local_tz_offset: int = 0) -> str:
        """Language::userAdjust() with the site's offset ($tz '' or 'System'): the TS_MW timestamp moved by
        $wgLocalTZoffset minutes; returned unchanged when the offset is 0 (whatever its form, e.g. "123")."""
        min_diff = local_tz_offset
        ts = _php_strval(ts)
        # No difference ? Return time unchanged
        if min_diff == 0:
            return ts
        # mktime() normalises out-of-range values, as timedelta arithmetic does
        parts = [_php_intval(ts[a:b]) for a, b in ((0, 4), (4, 6), (6, 8), (8, 10), (10, 12), (12, 14))]
        try:
            date = datetime(max(parts[0], 1), 1, 1) + timedelta(
                days=_month_days(parts[0], parts[1]) + parts[2] - 1, hours=parts[3], minutes=parts[4] + min_diff,
                seconds=parts[5])
        except (OverflowError, ValueError):
            return ts
        return date.strftime("%Y%m%d%H%M%S").rjust(14, "0")

    def sprintf_date(self, format_: str, ts: str) -> str:
        """A subset of Language::sprintfDate(): the date() letters dDjlNwzWFmMntLoYyaAgGhHis of a TS_MW
        timestamp; other characters are copied (no escapes, raw or xg/xn-style codes)."""
        dt = _parse_ts_mw(ts)
        out = []
        for ch in format_:
            out.append(_php_date_char(dt, ch, self) if ch in _DATE_CHARS else ch)
        return "".join(out)


def _month_days(year: int, month: int) -> int:
    """Days before the first of ``month`` (1-based, may be out of range) in ``year``."""
    base = datetime(max(year, 1), 1, 1)
    y, m = max(year, 1) + (month - 1) // 12, (month - 1) % 12 + 1
    return (datetime(y, m, 1) - base).days


def _plural_rule_index_en(count: Union[int, float]) -> int:
    """CLDR plural rules of English (one: i = 1 and v = 0), as CLDRPluralRuleParser's Evaluator computes the
    operands from strval( $number )."""
    s = _php_strval(count)
    m = re.match(r"^-?(([0-9]+)(?:\.([0-9]+))?)$", s)
    if not m:
        return 1
    i = int(m.group(2))
    v = len(m.group(3) or "")
    return 0 if i == 1 and v == 0 else 1


def _strong_dir_from_content(text: str) -> Optional[str]:
    """The direction of the first strongly directional character. (PHP: a regex generated from the Unicode
    character data; here unicodedata's bidirectional classes L and R/AL.)"""
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi == "L":
            return "ltr"
        if bidi in ("R", "AL"):
            return "rtl"
    return None


def _icu_format_en(number: str) -> str:
    """NumberFormatter( 'en', DECIMAL ) as Language::formatNumInternal() configures it: keep the number of digits
    before and after the decimal point (and the point) of the input; otherwise the pattern "#,##0.###". ICU formats
    the shortest representation of the double, rounding half-even."""
    m = re.match(r"^-?(\d*)(\.(\d*))?$", number)
    value = float(number)
    if m:
        min_int = len(m.group(1))
        always_point = m.group(2) is not None
        min_frac = max_frac = len(m.group(3) or "")
    else:
        min_int, always_point, min_frac, max_frac = 1, False, 0, 3
    negative = value < 0 or (value == 0 and math.copysign(1.0, value) < 0)
    if math.isinf(value):
        return ("-" if negative else "") + "∞"
    d = Decimal(repr(abs(value))).quantize(Decimal(1).scaleb(-max_frac), rounding=ROUND_HALF_EVEN)
    int_part, _, frac_part = format(d, "f").partition(".")
    while len(frac_part) > min_frac and frac_part.endswith("0"):
        frac_part = frac_part[:-1]
    int_part = int_part.lstrip("0").rjust(min_int, "0")
    groups = []
    while len(int_part) > 3:
        groups.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    if int_part:
        groups.insert(0, int_part)
    result = ",".join(groups)
    if frac_part or always_point:
        result += "." + frac_part
    return ("-" if negative else "") + result


ENGLISH = Language("en")

# ----------------------------------------------------------------------------------------------------------------------
# Timestamps (MWTimestamp, PHP date())
# ----------------------------------------------------------------------------------------------------------------------

_DATE_CHARS = set("dDjlNwzWFmMntLoYyaAgGhHis")


def _parse_ts_mw(ts: str) -> datetime:
    ts = _php_strval(ts)
    if re.fullmatch(r"\d{14}", ts):
        return datetime(int(ts[0:4]) or 1, int(ts[4:6]) or 1, int(ts[6:8]) or 1, int(ts[8:10]), int(ts[10:12]),
                         int(ts[12:14]))
    return to_datetime(ts).replace(tzinfo=None)


def to_datetime(value: Any) -> datetime:
    """A ConvertibleTimestamp as an aware UTC datetime: a datetime, a Unix time or a TS_MW string."""
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = _php_strval(value)
    if re.fullmatch(r"\d{14}", s):
        return datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]), int(s[12:14]),
                        tzinfo=timezone.utc)
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return datetime.fromtimestamp(float(s), timezone.utc).replace(microsecond=0)
    raise ValueError(f"Unrecognized timestamp: {s!r}")


def php_date(dt: datetime, format_: str, lang: Language = ENGLISH) -> str:
    """PHP date()/DateTime::format() for the letters MediaWiki's magic variables use."""
    return "".join(_php_date_char(dt, ch, lang) if ch in _DATE_CHARS else ch for ch in format_)


def _php_date_char(dt: datetime, ch: str, lang: Language) -> str:
    w = (dt.weekday() + 1) % 7
    if ch == "d":
        return f"{dt.day:02d}"
    if ch == "D":
        return lang.get_weekday_name(w + 1)[:3]
    if ch == "j":
        return str(dt.day)
    if ch == "l":
        return lang.get_weekday_name(w + 1)
    if ch == "N":
        return str(dt.isoweekday())
    if ch == "w":
        return str(w)
    if ch == "z":
        return str(dt.timetuple().tm_yday - 1)
    if ch == "W":
        return f"{dt.isocalendar()[1]:02d}"
    if ch == "F":
        return lang.get_month_name(dt.month)
    if ch == "m":
        return f"{dt.month:02d}"
    if ch == "M":
        return lang.get_month_abbreviation(dt.month)
    if ch == "n":
        return str(dt.month)
    if ch == "t":
        nxt = datetime(dt.year + dt.month // 12, dt.month % 12 + 1, 1)
        return str((nxt - timedelta(days=1)).day)
    if ch == "L":
        y = dt.year
        return "1" if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else "0"
    if ch == "o":
        return str(dt.isocalendar()[0])
    if ch == "Y":
        return f"{dt.year:04d}"
    if ch == "y":
        return f"{dt.year % 100:02d}"
    if ch == "a":
        return "am" if dt.hour < 12 else "pm"
    if ch == "A":
        return "AM" if dt.hour < 12 else "PM"
    if ch == "g":
        return str(dt.hour % 12 or 12)
    if ch == "G":
        return str(dt.hour)
    if ch == "h":
        return f"{dt.hour % 12 or 12:02d}"
    if ch == "H":
        return f"{dt.hour:02d}"
    if ch == "i":
        return f"{dt.minute:02d}"
    if ch == "s":
        return f"{dt.second:02d}"
    return ch


def local_zone(parser):
    """$wgLocaltimezone as a tzinfo (UTC if the zone is unknown or there is no time zone database)."""
    name = getattr(parser.config, "localtimezone", "UTC") or "UTC"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError, or no tzdata on Windows
        return timezone.utc


def local_tz_offset(parser) -> int:
    """$wgLocalTZoffset: the offset of $wgLocaltimezone in minutes (MainConfigSchema::getDefaultLocalTZoffset(),
    taken at the time of the parse rather than of the request)."""
    offset = getattr(parser.config, "local_tz_offset", None)
    if offset is not None:
        return int(offset)
    now = to_datetime(getattr(parser, "timestamp", None))
    delta = now.astimezone(local_zone(parser)).utcoffset()
    return int(delta.total_seconds() // 60) if delta is not None else 0


def get_local_instance(parser, ts: Any) -> datetime:
    """MWTimestamp::getLocalInstance(): the timestamp in $wgLocaltimezone."""
    return to_datetime(ts).astimezone(local_zone(parser))


# ======================================================================================================================
# Language names and codes (LanguageNameUtils, Names.php, LanguageCode)
# ======================================================================================================================

# includes/languages/data/Names.php: the native names of the languages MediaWiki knows
LANGUAGE_NAMES: dict[str, str] = {
    "aa": "Qafár af", "ab": "аԥсшәа", "abs": "bahasa ambon", "ace": "Acèh", "ady": "адыгабзэ",
    "ady-cyrl": "адыгабзэ", "aeb": "تونسي/Tûnsî", "aeb-arab": "تونسي", "aeb-latn": "Tûnsî", "af": "Afrikaans",
    "ak": "Akan", "aln": "Gegë", "als": "Alemannisch", "alt": "алтай тил", "am": "አማርኛ", "ami": "Pangcah",
    "an": "aragonés", "ang": "Ænglisc", "anp": "अंगिका", "ar": "العربية", "arc": "ܐܪܡܝܐ", "arn": "mapudungun",
    "arq": "جازايرية", "ary": "الدارجة", "arz": "مصرى", "as": "অসমীয়া", "ase": "American sign language",
    "ast": "asturianu", "atj": "Atikamekw", "av": "авар", "avk": "Kotava", "awa": "अवधी", "ay": "Aymar aru",
    "az": "azərbaycanca", "azb": "تۆرکجه", "ba": "башҡортса", "ban": "Basa Bali", "ban-bali": "ᬩᬲᬩᬮᬶ",
    "bar": "Boarisch", "bat-smg": "žemaitėška", "bbc": "Batak Toba", "bbc-latn": "Batak Toba",
    "bcc": "جهلسری بلوچی", "bci": "wawle", "bcl": "Bikol Central", "be": "беларуская",
    "be-tarask": "беларуская (тарашкевіца)", "be-x-old": "беларуская (тарашкевіца)", "bg": "български",
    "bgn": "روچ کپتین بلوچی", "bh": "भोजपुरी", "bho": "भोजपुरी", "bi": "Bislama", "bjn": "Banjar",
    "blk": "ပအိုဝ်ႏဘာႏသာႏ", "bm": "bamanankan", "bn": "বাংলা", "bo": "བོད་ཡིག", "bpy": "বিষ্ণুপ্রিয়া মণিপুরী",
    "bqi": "بختیاری", "br": "brezhoneg", "brh": "Bráhuí", "bs": "bosanski", "btm": "Batak Mandailing",
    "bto": "Iriga Bicolano", "bug": "ᨅᨔ ᨕᨘᨁᨗ", "bxr": "буряад", "ca": "català",
    "cbk-zam": "Chavacano de Zamboanga", "cdo": "Mìng-dĕ̤ng-ngṳ̄", "ce": "нохчийн", "ceb": "Cebuano",
    "ch": "Chamoru", "cho": "Choctaw", "chr": "ᏣᎳᎩ", "chy": "Tsetsêhestâhese", "ckb": "کوردی", "co": "corsu",
    "cps": "Capiceño", "cr": "Nēhiyawēwin / ᓀᐦᐃᔭᐍᐏᐣ", "crh": "qırımtatarca", "crh-cyrl": "къырымтатарджа (Кирилл)",
    "crh-latn": "qırımtatarca (Latin)", "cs": "čeština", "csb": "kaszëbsczi", "cu": "словѣньскъ / ⰔⰎⰑⰂⰡⰐⰠⰔⰍⰟ",
    "cv": "чӑвашла", "cy": "Cymraeg", "da": "dansk", "dag": "dagbanli", "de": "Deutsch",
    "de-at": "Österreichisches Deutsch", "de-ch": "Schweizer Hochdeutsch", "de-formal": "Deutsch (Sie-Form)",
    "din": "Thuɔŋjäŋ", "diq": "Zazaki", "dsb": "dolnoserbski", "dtp": "Dusun Bundu-liwan", "dty": "डोटेली",
    "dv": "ދިވެހިބަސް", "dz": "ཇོང་ཁ", "ee": "eʋegbe", "egl": "Emiliàn", "el": "Ελληνικά",
    "eml": "emiliàn e rumagnòl", "en": "English", "en-ca": "Canadian English", "en-gb": "British English",
    "eo": "Esperanto", "es": "español", "es-419": "español de América Latina", "es-formal": "español (formal)",
    "et": "eesti", "eu": "euskara", "ext": "estremeñu", "fa": "فارسی", "fat": "mfantse", "ff": "Fulfulde",
    "fi": "suomi", "fit": "meänkieli", "fiu-vro": "võro", "fj": "Na Vosa Vakaviti", "fo": "føroyskt",
    "fon": "fɔ̀ngbè", "fr": "français", "frc": "français cadien", "frp": "arpetan", "frr": "Nordfriisk",
    "fur": "furlan", "fy": "Frysk", "ga": "Gaeilge", "gaa": "Ga", "gag": "Gagauz", "gan": "贛語",
    "gan-hans": "赣语（简体）", "gan-hant": "贛語（繁體）", "gcr": "kriyòl gwiyannen", "gd": "Gàidhlig", "gl": "galego",
    "gld": "на̄ни", "glk": "گیلکی", "gn": "Avañe'ẽ", "gom": "गोंयची कोंकणी / Gõychi Konknni",
    "gom-deva": "गोंयची कोंकणी", "gom-latn": "Gõychi Konknni", "gor": "Bahasa Hulontalo", "got": "𐌲𐌿𐍄𐌹𐍃𐌺",
    "gpe": "Ghanaian Pidgin", "grc": "Ἀρχαία ἑλληνικὴ", "gsw": "Alemannisch", "gu": "ગુજરાતી", "guc": "wayuunaiki",
    "gur": "farefare", "guw": "gungbe", "gv": "Gaelg", "ha": "Hausa", "hak": "客家語/Hak-kâ-ngî", "haw": "Hawaiʻi",
    "he": "עברית", "hi": "हिन्दी", "hif": "Fiji Hindi", "hif-latn": "Fiji Hindi", "hil": "Ilonggo",
    "ho": "Hiri Motu", "hr": "hrvatski", "hrx": "Hunsrik", "hsb": "hornjoserbsce", "hsn": "湘语",
    "ht": "Kreyòl ayisyen", "hu": "magyar", "hu-formal": "magyar (formal)", "hy": "հայերեն",
    "hyw": "Արեւմտահայերէն", "hz": "Otsiherero", "ia": "interlingua", "id": "Bahasa Indonesia",
    "ie": "Interlingue", "ig": "Igbo", "ii": "ꆇꉙ", "ik": "Iñupiatun", "ike-cans": "ᐃᓄᒃᑎᑐᑦ",
    "ike-latn": "inuktitut", "ilo": "Ilokano", "inh": "гӀалгӀай", "io": "Ido", "is": "íslenska", "it": "italiano",
    "iu": "ᐃᓄᒃᑎᑐᑦ/inuktitut", "ja": "日本語", "jam": "Patois", "jbo": "la .lojban.", "jut": "jysk", "jv": "Jawa",
    "ka": "ქართული", "kaa": "Qaraqalpaqsha", "kab": "Taqbaylit", "kbd": "адыгэбзэ", "kbd-cyrl": "адыгэбзэ",
    "kbp": "Kabɩyɛ", "kcg": "Tyap", "kea": "kabuverdianu", "kg": "Kongo", "khw": "کھوار", "ki": "Gĩkũyũ",
    "kiu": "Kırmancki", "kj": "Kwanyama", "kjp": "ဖၠုံလိက်", "kk": "қазақша", "kk-arab": "قازاقشا (تٴوتە)",
    "kk-cn": "قازاقشا (جۇنگو)", "kk-cyrl": "қазақша (кирил)", "kk-kz": "қазақша (Қазақстан)",
    "kk-latn": "qazaqşa (latın)", "kk-tr": "qazaqşa (Türkïya)", "kl": "kalaallisut", "km": "ភាសាខ្មែរ",
    "kn": "ಕನ್ನಡ", "ko": "한국어", "ko-kp": "조선말", "koi": "перем коми", "kr": "kanuri", "krc": "къарачай-малкъар",
    "kri": "Krio", "krj": "Kinaray-a", "krl": "karjal", "ks": "कॉशुर / کٲشُر", "ks-arab": "کٲشُر",
    "ks-deva": "कॉशुर", "ksh": "Ripoarisch", "ksw": "စှီၤ", "ku": "kurdî", "ku-arab": "كوردي (عەرەبی)",
    "ku-latn": "kurdî (latînî)", "kum": "къумукъ", "kv": "коми", "kw": "kernowek", "ky": "кыргызча",
    "la": "Latina", "lad": "Ladino", "lb": "Lëtzebuergesch", "lbe": "лакку", "lez": "лезги",
    "lfn": "Lingua Franca Nova", "lg": "Luganda", "li": "Limburgs", "lij": "Ligure", "liv": "Līvõ kēļ",
    "lki": "لەکی", "lld": "Ladin", "lmo": "lombard", "ln": "lingála", "lo": "ລາວ", "loz": "Silozi",
    "lrc": "لۊری شومالی", "lt": "lietuvių", "ltg": "latgaļu", "lus": "Mizo ţawng", "luz": "لئری دوٙمینی",
    "lv": "latviešu", "lzh": "文言", "lzz": "Lazuri", "mad": "Madhurâ", "mai": "मैथिली",
    "map-bms": "Basa Banyumasan", "mdf": "мокшень", "mg": "Malagasy", "mh": "Ebon", "mhr": "олык марий",
    "mi": "Māori", "min": "Minangkabau", "mk": "македонски", "ml": "മലയാളം", "mn": "монгол", "mni": "ꯃꯤꯇꯩ ꯂꯣꯟ",
    "mnw": "ဘာသာ မန်", "mo": "молдовеняскэ", "mos": "moore", "mr": "मराठी", "mrh": "Mara", "mrj": "кырык мары",
    "ms": "Bahasa Melayu", "ms-arab": "بهاس ملايو", "mt": "Malti", "mus": "Mvskoke", "mwl": "Mirandés",
    "my": "မြန်မာဘာသာ", "myv": "эрзянь", "mzn": "مازِرونی", "na": "Dorerin Naoero", "nah": "Nāhuatl",
    "nan": "Bân-lâm-gú", "nap": "Napulitano", "nb": "norsk bokmål", "nds": "Plattdüütsch",
    "nds-nl": "Nedersaksies", "ne": "नेपाली", "new": "नेपाल भाषा", "ng": "Oshiwambo", "nia": "Li Niha",
    "niu": "Niuē", "nl": "Nederlands", "nl-informal": "Nederlands (informeel)", "nmz": "nawdm",
    "nn": "norsk nynorsk", "no": "norsk", "nod": "ᨣᩤᩴᨾᩮᩬᩥᨦ", "nov": "Novial", "nqo": "ߒߞߏ", "nrm": "Nouormand",
    "nso": "Sesotho sa Leboa", "nv": "Diné bizaad", "ny": "Chi-Chewa", "nyn": "runyankore", "nys": "Nyunga",
    "oc": "occitan", "ojb": "Ojibwemowin", "olo": "livvinkarjala", "om": "Oromoo", "or": "ଓଡ଼ିଆ", "os": "ирон",
    "pa": "ਪੰਜਾਬੀ", "pag": "Pangasinan", "pam": "Kapampangan", "pap": "Papiamentu", "pcd": "Picard",
    "pcm": "Naijá", "pdc": "Deitsch", "pdt": "Plautdietsch", "pfl": "Pälzisch", "pi": "पालि",
    "pih": "Norfuk / Pitkern", "pl": "polski", "pms": "Piemontèis", "pnb": "پنجابی", "pnt": "Ποντιακά",
    "prg": "prūsiskan", "ps": "پښتو", "pt": "português", "pt-br": "português do Brasil", "pwn": "pinayuanan",
    "qu": "Runa Simi", "qug": "Runa shimi", "rgn": "Rumagnôl", "rif": "Tarifit", "rm": "rumantsch",
    "rmc": "romaňi čhib", "rmy": "romani čhib", "rn": "ikirundi", "ro": "română", "roa-rup": "armãneashti",
    "roa-tara": "tarandíne", "rsk": "руски", "ru": "русский", "rue": "русиньскый", "rup": "armãneashti",
    "ruq": "Vlăheşte", "ruq-cyrl": "Влахесте", "ruq-latn": "Vlăheşte", "rw": "Ikinyarwanda", "ryu": "うちなーぐち",
    "sa": "संस्कृतम्", "sah": "саха тыла", "sat": "ᱥᱟᱱᱛᱟᱲᱤ", "sc": "sardu", "scn": "sicilianu", "sco": "Scots",
    "sd": "سنڌي", "sdc": "Sassaresu", "sdh": "کوردی خوارگ", "se": "davvisámegiella",
    "se-fi": "davvisámegiella (Suoma bealde)", "se-no": "davvisámegiella (Norgga bealde)",
    "se-se": "davvisámegiella (Ruoŧa bealde)", "sei": "Cmique Itom", "ses": "Koyraboro Senni", "sg": "Sängö",
    "sgs": "žemaitėška", "sh": "srpskohrvatski / српскохрватски", "shi": "Taclḥit", "shi-latn": "Taclḥit",
    "shi-tfng": "ⵜⴰⵛⵍⵃⵉⵜ", "shn": "ၽႃႇသႃႇတႆး ", "shy": "tacawit", "shy-latn": "tacawit", "si": "සිංහල",
    "simple": "Simple English", "sjd": "кӣллт са̄мь кӣлл", "sje": "bidumsámegiella", "sk": "slovenčina",
    "skr": "سرائیکی", "skr-arab": "سرائیکی", "sl": "slovenščina", "sli": "Schläsch", "sm": "Gagana Samoa",
    "sma": "åarjelsaemien", "smn": "anarâškielâ", "sms": "nuõrttsääʹmǩiõll", "sn": "chiShona", "so": "Soomaaliga",
    "sq": "shqip", "sr": "српски / srpski", "sr-ec": "српски (ћирилица)", "sr-el": "srpski (latinica)",
    "srn": "Sranantongo", "sro": "sardu campidanesu", "ss": "SiSwati", "st": "Sesotho", "stq": "Seeltersk",
    "sty": "себертатар", "su": "Sunda", "sv": "svenska", "sw": "Kiswahili", "syl": "ꠍꠤꠟꠐꠤ", "szl": "ślůnski",
    "szy": "Sakizaya", "ta": "தமிழ்", "tay": "Tayal", "tcy": "ತುಳು", "tdd": "ᥖᥭᥰᥖᥬᥳᥑᥨᥒᥰ", "te": "తెలుగు",
    "tet": "tetun", "tg": "тоҷикӣ", "tg-cyrl": "тоҷикӣ", "tg-latn": "tojikī", "th": "ไทย", "ti": "ትግርኛ",
    "tk": "Türkmençe", "tl": "Tagalog", "tly": "tolışi", "tly-cyrl": "толыши", "tn": "Setswana",
    "to": "lea faka-Tonga", "tpi": "Tok Pisin", "tr": "Türkçe", "tru": "Ṫuroyo", "trv": "Seediq", "ts": "Xitsonga",
    "tt": "татарча/tatarça", "tt-cyrl": "татарча", "tt-latn": "tatarça", "tum": "chiTumbuka", "tw": "Twi",
    "ty": "reo tahiti", "tyv": "тыва дыл", "tzm": "ⵜⴰⵎⴰⵣⵉⵖⵜ", "udm": "удмурт", "ug": "ئۇيغۇرچە / Uyghurche",
    "ug-arab": "ئۇيغۇرچە", "ug-latn": "Uyghurche", "uk": "українська", "ur": "اردو", "uz": "oʻzbekcha/ўзбекча",
    "uz-cyrl": "ўзбекча", "uz-latn": "oʻzbekcha", "ve": "Tshivenda", "vec": "vèneto", "vep": "vepsän kel’",
    "vi": "Tiếng Việt", "vls": "West-Vlams", "vmf": "Mainfränkisch", "vmw": "emakhuwa", "vo": "Volapük",
    "vot": "Vaďďa", "vro": "võro", "wa": "walon", "war": "Winaray", "wls": "Fakaʻuvea", "wo": "Wolof", "wuu": "吴语",
    "xal": "хальмг", "xh": "isiXhosa", "xmf": "მარგალური", "xsy": "saisiyat", "yi": "ייִדיש", "yo": "Yorùbá",
    "yrl": "Nhẽẽgatú", "yue": "粵語", "za": "Vahcuengh", "zea": "Zeêuws", "zgh": "ⵜⴰⵎⴰⵣⵉⵖⵜ ⵜⴰⵏⴰⵡⴰⵢⵜ", "zh": "中文",
    "zh-classical": "文言", "zh-cn": "中文（中国大陆）", "zh-hans": "中文（简体）", "zh-hant": "中文（繁體）", "zh-hk": "中文（香港）",
    "zh-min-nan": "Bân-lâm-gú", "zh-mo": "中文（澳門）", "zh-my": "中文（马来西亚）", "zh-sg": "中文（新加坡）", "zh-tw": "中文（臺灣）",
    "zh-yue": "粵語", "zu": "isiZulu",
}

_DEPRECATED_LANGUAGE_CODE_MAPPING = {
    # Note that als is actually a valid ISO 639 code (Tosk Albanian), but it was previously used in MediaWiki for
    # Alsatian, which comes under gsw
    "als": "gsw",  # T25215
    "bat-smg": "sgs",  # T27522
    "be-x-old": "be-tarask",  # T11823
    "fiu-vro": "vro",  # T31186
    "roa-rup": "rup",  # T17988
    "zh-classical": "lzh",  # T30443
    "zh-min-nan": "nan",  # T30442
    "zh-yue": "yue",  # T30441
}

_NON_STANDARD_LANGUAGE_CODE_MAPPING = {
    "cbk-zam": "cbk",  # T124657
    "de-formal": "de-x-formal",
    "eml": "egl",  # T36217
    "en-rtl": "en-x-rtl",
    "es-formal": "es-x-formal",
    "hu-formal": "hu-x-formal",
    "map-bms": "jv-x-bms",  # [[en:Banyumasan_dialect]] T125073
    "mo": "ro-Cyrl-MD",  # T125073
    "nrm": "nrf",  # [[en:Norman_language]] T25216
    "nl-informal": "nl-x-informal",
    "roa-tara": "nap-x-tara",  # [[en:Tarantino_dialect]]
    "simple": "en-simple",
    "sr-ec": "sr-Cyrl",  # T117845
    "sr-el": "sr-Latn",  # T117845
    # Although these next codes aren't *wrong* per se, including both the script and the country code helps
    # compatibility with other BCP 47 users.
    "zh-cn": "zh-Hans-CN",
    "zh-sg": "zh-Hans-SG",
    "zh-my": "zh-Hans-MY",
    "zh-tw": "zh-Hant-TW",
    "zh-hk": "zh-Hant-HK",
    "zh-mo": "zh-Hant-MO",
}


def bcp47(code: str) -> str:
    """LanguageCode::bcp47(): get the normalised IANA language tag."""
    code = _php_strtolower(code)
    code = _DEPRECATED_LANGUAGE_CODE_MAPPING.get(code, code)
    code = _NON_STANDARD_LANGUAGE_CODE_MAPPING.get(code, code)
    segments = code.split("-")
    out = []
    for seg_no, seg in enumerate(segments):
        # when previous segment is x, it is a private segment and should be lc
        if seg_no > 0 and _php_strtolower(segments[seg_no - 1]) == "x":
            out.append(_php_strtolower(seg))
        # ISO 3166 country code
        elif len(seg.encode("utf-8")) == 2 and seg_no > 0:
            out.append(seg.translate(_ASCII_UPPER))
        # ISO 15924 script code
        elif len(seg.encode("utf-8")) == 4 and seg_no > 0:
            seg = _php_strtolower(seg)
            out.append(seg[:1].translate(_ASCII_UPPER) + seg[1:])
        # Use lowercase for other cases
        else:
            out.append(_php_strtolower(seg))
    return "-".join(out)


def get_language_name(code: str, in_language: Optional[str] = None) -> str:
    """LanguageNameUtils::getLanguageName(): the native name (no CLDR extension, so the names in other languages
    are the native ones too); '' for an unknown code."""
    return LANGUAGE_NAMES.get(_php_strtolower(code), "")


# ======================================================================================================================
# Special pages (SpecialPageFactory)
# ======================================================================================================================

# SpecialPageFactory::CORE_LIST and the pages getPageList() adds with the default settings (Search,
# Confirmemail, Invalidateemail, ChangeEmail)
SPECIAL_PAGE_LIST = (
    "BrokenRedirects Deadendpages DoubleRedirects Longpages Ancientpages Lonelypages Fewestrevisions "
    "Withoutinterwiki Protectedpages Protectedtitles Shortpages Uncategorizedcategories Uncategorizedimages "
    "Uncategorizedpages Uncategorizedtemplates Unusedcategories Unusedimages Unusedtemplates Unwatchedpages "
    "Wantedcategories Wantedfiles Wantedpages Wantedtemplates Allpages Prefixindex Categories Listredirects "
    "PagesWithProp TrackingCategories Userlogin Userlogout CreateAccount LinkAccounts UnlinkAccounts "
    "ChangeCredentials RemoveCredentials Activeusers Block Unblock BlockList AutoblockList ChangePassword "
    "BotPasswords PasswordReset DeletedContributions Preferences ResetTokens Contributions Listgrouprights Listgrants "
    "Listusers Listadmins Listbots Userrights EditWatchlist PasswordPolicies Newimages Log Watchlist Newpages "
    "Recentchanges Recentchangeslinked Tags Listfiles Filepath MediaStatistics MIMEsearch FileDuplicateSearch Upload "
    "UploadStash ListDuplicatedFiles ApiSandbox Statistics Allmessages Version Lockdb Unlockdb LinkSearch Randompage "
    "RandomInCategory Randomredirect Randomrootpage GoToInterwiki Mostlinkedcategories Mostimages Mostinterwikis "
    "Mostlinked Mostlinkedtemplates Mostcategories Mostrevisions ComparePages Export Import Undelete Whatlinkshere "
    "MergeHistory ExpandTemplates ChangeContentModel Booksources ApiHelp Blankpage DeletePage Diff EditPage EditTags "
    "Emailuser Movepage Mycontributions MyLanguage Mypage Mytalk PageHistory PageInfo ProtectPage Purge Myuploads "
    "AllMyUploads NewSection PermanentLink Redirect Revisiondelete RunJobs Specialpages PageData "
    "Search Confirmemail Invalidateemail ChangeEmail"
).split()

# languages/messages/MessagesEn.php $specialPageAliases
SPECIAL_PAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "Activeusers": ("ActiveUsers",), "Allmessages": ("AllMessages",), "AllMyUploads": ("AllMyUploads", "AllMyFiles"),
    "Allpages": ("AllPages",), "Ancientpages": ("AncientPages",), "ApiHelp": ("ApiHelp",),
    "ApiSandbox": ("ApiSandbox",), "AutoblockList": ("AutoblockList", "ListAutoblocks"), "Badtitle": ("Badtitle",),
    "Blankpage": ("BlankPage",), "Block": ("Block", "BlockIP", "BlockUser"),
    "BlockList": ("BlockList", "ListBlocks", "IPBlockList"), "Booksources": ("BookSources",),
    "BotPasswords": ("BotPasswords",), "BrokenRedirects": ("BrokenRedirects",), "Categories": ("Categories",),
    "ChangeContentModel": ("ChangeContentModel",), "ChangeCredentials": ("ChangeCredentials",),
    "ChangeEmail": ("ChangeEmail",), "ChangePassword": ("ChangePassword", "ResetPass", "ResetPassword"),
    "ComparePages": ("ComparePages",), "Confirmemail": ("ConfirmEmail",),
    "Contributions": ("Contributions", "Contribs"), "CreateAccount": ("CreateAccount",),
    "Deadendpages": ("DeadendPages",), "DeletedContributions": ("DeletedContributions",),
    "DeletePage": ("DeletePage", "Delete"), "Diff": ("Diff",), "DoubleRedirects": ("DoubleRedirects",),
    "EditPage": ("EditPage", "Edit"), "EditTags": ("EditTags",), "EditWatchlist": ("EditWatchlist",),
    "Emailuser": ("EmailUser", "Email"), "ExpandTemplates": ("ExpandTemplates",), "Export": ("Export",),
    "Fewestrevisions": ("FewestRevisions",), "FileDuplicateSearch": ("FileDuplicateSearch",),
    "Filepath": ("FilePath",), "GoToInterwiki": ("GoToInterwiki",), "Import": ("Import",),
    "Invalidateemail": ("InvalidateEmail",), "JavaScriptTest": ("JavaScriptTest",), "LinkAccounts": ("LinkAccounts",),
    "LinkSearch": ("LinkSearch",), "Listadmins": ("ListAdmins",), "Listbots": ("ListBots",),
    "ListDuplicatedFiles": ("ListDuplicatedFiles", "ListFileDuplicates"),
    "Listfiles": ("ListFiles", "FileList", "ImageList"), "Listgrants": ("ListGrants",),
    "Listgrouprights": ("ListGroupRights", "UserGroupRights"), "Listredirects": ("ListRedirects",),
    "Listusers": ("ListUsers", "UserList", "Users"), "Lockdb": ("LockDB",), "Log": ("Log", "Logs"),
    "Lonelypages": ("LonelyPages", "OrphanedPages"), "Longpages": ("LongPages",),
    "MediaStatistics": ("MediaStatistics",), "MergeHistory": ("MergeHistory",), "MIMEsearch": ("MIMESearch",),
    "Mostcategories": ("MostCategories",), "Mostimages": ("MostLinkedFiles", "MostFiles", "MostImages"),
    "Mostinterwikis": ("MostInterwikis",), "Mostlinked": ("MostLinkedPages", "MostLinked"),
    "Mostlinkedcategories": ("MostLinkedCategories", "MostUsedCategories"),
    "Mostlinkedtemplates": ("MostTranscludedPages", "MostLinkedTemplates", "MostUsedTemplates"),
    "Mostrevisions": ("MostRevisions",), "Movepage": ("MovePage",), "Mute": ("Mute",),
    "Mycontributions": ("MyContributions", "MyContribs"), "MyLanguage": ("MyLanguage",), "Mypage": ("MyPage",),
    "Mytalk": ("MyTalk",), "Myuploads": ("MyUploads", "MyFiles"), "Newimages": ("NewFiles", "NewImages"),
    "Newpages": ("NewPages",), "NewSection": ("NewSection", "Newsection"), "PageData": ("PageData",),
    "PageHistory": ("PageHistory", "History"), "PageInfo": ("PageInfo", "Info"), "PageLanguage": ("PageLanguage",),
    "PagesWithProp": ("PagesWithProp", "Pageswithprop", "PagesByProp", "Pagesbyprop"),
    "PasswordPolicies": ("PasswordPolicies",), "PasswordReset": ("PasswordReset",),
    "PermanentLink": ("PermanentLink", "PermaLink"), "Preferences": ("Preferences",), "Prefixindex": ("PrefixIndex",),
    "Protectedpages": ("ProtectedPages",), "Protectedtitles": ("ProtectedTitles",),
    "ProtectPage": ("ProtectPage", "Protect"), "Purge": ("Purge",), "RandomInCategory": ("RandomInCategory",),
    "Randompage": ("Random", "RandomPage"), "Randomredirect": ("RandomRedirect",),
    "Randomrootpage": ("RandomRootpage",), "Recentchanges": ("RecentChanges",),
    "Recentchangeslinked": ("RecentChangesLinked", "RelatedChanges"), "Redirect": ("Redirect",),
    "RemoveCredentials": ("RemoveCredentials",), "ResetTokens": ("ResetTokens",),
    "Revisiondelete": ("RevisionDelete",), "RunJobs": ("RunJobs",), "Search": ("Search",),
    "Shortpages": ("ShortPages",), "Specialpages": ("SpecialPages",), "Statistics": ("Statistics", "Stats"),
    "Tags": ("Tags",), "TrackingCategories": ("TrackingCategories",), "Unblock": ("Unblock",),
    "Uncategorizedcategories": ("UncategorizedCategories",),
    "Uncategorizedimages": ("UncategorizedFiles", "UncategorizedImages"),
    "Uncategorizedpages": ("UncategorizedPages",), "Uncategorizedtemplates": ("UncategorizedTemplates",),
    "Undelete": ("Undelete",), "UnlinkAccounts": ("UnlinkAccounts",), "Unlockdb": ("UnlockDB",),
    "Unusedcategories": ("UnusedCategories",), "Unusedimages": ("UnusedFiles", "UnusedImages"),
    "Unusedtemplates": ("UnusedTemplates",), "Unwatchedpages": ("UnwatchedPages",), "Upload": ("Upload",),
    "UploadStash": ("UploadStash",), "Userlogin": ("UserLogin", "Login"), "Userlogout": ("UserLogout", "Logout"),
    "Userrights": ("UserRights", "MakeSysop", "MakeBot"), "Version": ("Version",),
    "Wantedcategories": ("WantedCategories",), "Wantedfiles": ("WantedFiles",),
    "Wantedpages": ("WantedPages", "BrokenLinks"), "Wantedtemplates": ("WantedTemplates",),
    "Watchlist": ("Watchlist",), "Whatlinkshere": ("WhatLinksHere",), "Withoutinterwiki": ("WithoutInterwiki",),
}

_special_alias_list: Optional[dict[str, str]] = None


def _get_alias_list() -> dict[str, str]:
    """SpecialPageFactory::getAliasList(): case-folded alias -> canonical special page name."""
    global _special_alias_list
    if _special_alias_list is None:
        aliases: dict[str, str] = {}
        keep_alias: dict[str, str] = {}
        # Force every canonical name to be an alias for itself.
        for name in SPECIAL_PAGE_LIST:
            case_folded = ENGLISH.case_fold(name)
            aliases[case_folded] = name
            keep_alias[case_folded] = "canonical"
        for real_name, alias_list in SPECIAL_PAGE_ALIASES.items():
            for i, alias in enumerate(alias_list):
                case_folded = ENGLISH.case_fold(alias)
                if case_folded in aliases and real_name == aliases[case_folded]:
                    # Ignore same-realName conflicts
                    continue
                if case_folded not in keep_alias:
                    aliases[case_folded] = real_name
                    if not i:
                        keep_alias[case_folded] = "first"
        _special_alias_list = aliases
    return _special_alias_list


def resolve_alias(alias: str) -> tuple[Optional[str], Optional[str]]:
    """SpecialPageFactory::resolveAlias(): the canonical special page name and the subpage, (None, None) if the
    alias is unknown."""
    bits = alias.split("/", 1)
    case_folded = ENGLISH.case_fold(bits[0]).replace(" ", "_")
    aliases = _get_alias_list()
    if case_folded not in aliases:
        return None, None
    name = aliases[case_folded]
    par = bits[1] if len(bits) > 1 else None  # T4087
    return name, par


def get_local_name_for(name: str, subpage: Optional[str] = None) -> str:
    """SpecialPageFactory::getLocalNameFor(): the local name of a special page (its first usable alias)."""
    alias_list = _get_alias_list()
    # Find the first alias that maps back to $name
    if name in SPECIAL_PAGE_ALIASES:
        for alias in SPECIAL_PAGE_ALIASES[name]:
            case_folded = ENGLISH.case_fold(alias).replace(" ", "_")
            if alias_list.get(case_folded) == name:
                name = alias
                break
    else:
        # Check if someone misspelled the correct casing
        for n in SPECIAL_PAGE_ALIASES:
            if n.lower() == name.lower():
                return get_local_name_for(n, subpage)
    if subpage is not None and subpage is not False:
        # Make sure it's in dbkey form
        name = f"{name}/{subpage.replace(' ', '_')}"
    return ENGLISH.ucfirst(name)


def special_page_title_for(name: str, subpage: Optional[str], site) -> Title:
    """SpecialPage::getTitleFor()"""
    return Title.make_title(NS_SPECIAL, get_local_name_for(name, subpage), site=site)


# ======================================================================================================================
# Date formatter (DateFormatter)
# ======================================================================================================================

class DateFormatter:
    """Date formatter. Recognises dates and formats them according to a specified preference. Only used by the
    {{#dateformat}} parser function; able to format incomplete dates with an unspecified year."""

    ALL = -1  # Used as a preference ID for rules that apply regardless of preference
    NONE = 0  # No preference: the date may be left in the same format as the input
    MDY = 1  # e.g. January 15, 2001
    DMY = 2  # e.g. 15 January 2001
    YMD = 3  # e.g. 2001 January 15
    ISO = 4  # e.g. 2001-01-15
    YDM = 5  # e.g. 2001, 15 January
    DM = 6  # e.g. 15 January
    MD = 7  # e.g. January 15
    LAST = 7  # The highest ID that is a valid target format

    # Special rules: preference ID -> detected source format -> target format
    RULES = {
        ALL: {MD: MD, DM: DM},
        NONE: {ISO: ISO},
        MDY: {DM: MD},
        DMY: {MD: DM},
    }
    PREFERENCE_IDS = {"default": NONE, "dmy": DMY, "mdy": MDY, "ymd": YMD, "ISO 8601": ISO}
    # Format strings similar to those used by date(), indexed by ID
    TARGET_FORMATS = {DMY: "j F Y", YDM: "Y, j F", MDY: "F j, Y", YMD: "Y F j", DM: "j F", MD: "F j", ISO: "y-m-d"}

    def __init__(self, lang: Language = ENGLISH):
        month_regex_parts = []
        self.month_names: dict[int, str] = {}
        self.x_months: dict[str, int] = {}
        for i in range(1, 13):
            month_name = lang.get_month_name(i)
            month_abbrev = lang.get_month_abbreviation(i)
            self.month_names[i] = month_name
            month_regex_parts.append(re.escape(month_name))
            month_regex_parts.append(re.escape(month_abbrev))
            self.x_months[month_name.lower()] = i
            self.x_months[month_abbrev.lower()] = i

        # Partial regular expressions
        month_names = "|".join(month_regex_parts)
        dm = rf"(?P<day>\d{{1,2}})[ _](?P<monthName>{month_names})"
        md = rf"(?P<monthName>{month_names})[ _](?P<day>\d{{1,2}})"
        y = r"(?P<year>\d{1,4}([ _]BC|))"
        iso = r"(?P<isoYear>-?\d{4})-(?P<isoMonth>\d{2})-(?P<isoDay>\d{2})"
        self.regexes = {
            self.DMY: re.compile(rf"^{dm}(?: *, *| +){y}$", re.I),
            self.YDM: re.compile(rf"^{y}(?: *, *| +){dm}$", re.I),
            self.MDY: re.compile(rf"^{md}(?: *, *| +){y}$", re.I),
            self.YMD: re.compile(rf"^{y}(?: *, *| +){md}$", re.I),
            self.DM: re.compile(rf"^{dm}$", re.I),
            self.MD: re.compile(rf"^{md}$", re.I),
            self.ISO: re.compile(rf"^{iso}$", re.I),
        }

    def reformat(self, preference: str, text: str) -> str:
        """``preference``: "default", "dmy", "mdy", "ymd" or "ISO 8601". ('match-whole' is implied.)"""
        user_format_id = self.PREFERENCE_IDS.get(preference, self.NONE)
        for source in range(1, self.LAST + 1):
            if source in self.RULES.get(user_format_id, {}):
                # Specific rules
                target = self.RULES[user_format_id][source]
            elif source in self.RULES[self.ALL]:
                # General rules
                target = self.RULES[self.ALL][source]
            elif user_format_id:
                # User preference
                target = user_format_id
            else:
                # Default
                target = source
            format_ = self.TARGET_FORMATS[target]
            text = self.regexes[source].sub(lambda m: self._replace(m, format_), text)
        return text

    def _replace(self, m: re.Match, format_: str) -> str:
        match = {k: v for k, v in m.groupdict().items() if v is not None}
        # Pre-generate y/Y stuff because we need the year for the <span> title.
        if "isoYear" not in match and "year" in match:
            match["isoYear"] = self._make_iso_year(match["year"])
        if "year" not in match and "isoYear" in match:
            match["year"] = self._make_normal_year(match["isoYear"])
        if "isoMonth" not in match:
            month = self._make_iso_month(match["monthName"])
            if month is None:
                # Fail
                return m.group(0)
            match["isoMonth"] = month
        if "isoDay" not in match:
            match["isoDay"] = "%02d" % _php_intval(match["day"])

        text = []
        for char in format_:
            if char == "d":  # ISO day of month
                text.append(match["isoDay"])
            elif char == "m":  # ISO month
                text.append(match["isoMonth"])
            elif char == "y":  # ISO year
                text.append(match["isoYear"])
            elif char == "j":  # ordinary day of month
                text.append(str(_php_intval(match["isoDay"])) if "day" not in match else match["day"])
            elif char == "F":  # long month
                month_no = _php_intval(match["isoMonth"])
                if month_no > 12 or month_no < 1:
                    # Fail
                    return m.group(0)
                text.append(self.month_names[month_no])
            elif char == "Y":  # ordinary (optional BC) year
                text.append(str(match["year"]))
            else:
                text.append(char)

        iso_bits = []
        if "isoYear" in match:
            iso_bits.append(match["isoYear"])
        iso_bits.append(match["isoMonth"])
        iso_bits.append(match["isoDay"])
        iso_date = "-".join(iso_bits)
        # Output is not strictly HTML (it's wikitext), but <span> is allowed.
        return raw_element("span", {"class": "mw-formatted-date", "title": iso_date}, "".join(text))

    def _make_iso_month(self, month_name: str) -> Optional[str]:
        """Makes an ISO month, e.g. 02, from a month name"""
        iso_month = self.x_months.get(month_name.lower())
        return None if iso_month is None else "%02d" % iso_month

    @staticmethod
    def _make_iso_year(year: str) -> str:
        """Make an ISO year from a year name, for instance: '-1199' from '1200 BC'"""
        # Assumes the year is in a nice format, as enforced by the regex
        if year[-2:] == "BC":
            num = _php_intval(year[:-3]) - 1
            # PHP bug note: sprintf( "%04d", -1 ) fails poorly
            return "-%04d" % num
        return "%04d" % _php_intval(year)

    @staticmethod
    def _make_normal_year(iso: str) -> Union[int, str]:
        """Make a year from an ISO year, for instance: '400 BC' from '-0399'."""
        if iso[0] == "-":
            return f"{_php_intval(iso[1:]) + 1} BC"
        return _php_intval(iso)


_DATE_FORMATTER: Optional[DateFormatter] = None


def get_date_formatter() -> DateFormatter:
    global _DATE_FORMATTER
    if _DATE_FORMATTER is None:
        _DATE_FORMATTER = DateFormatter(ENGLISH)
    return _DATE_FORMATTER


# ======================================================================================================================
# Parser.php helpers
# ======================================================================================================================

@dataclass
class RevisionRecord:
    """What the parser functions read from a revision (RevisionRecord): ids, TS_MW timestamp, user name, size in
    bytes, and the wikitext."""
    id: int = 0
    page_id: int = 0
    timestamp: Optional[str] = None
    user: Optional[str] = None
    size: Optional[int] = None
    content: Optional[str] = None
    sha1: Optional[str] = None

    def is_current(self) -> bool:
        return True


@dataclass
class SiteStats:
    """SiteStats: the counts of the site_stats table, and group sizes (SiteStats::numberingroup())."""
    pages: int = 0
    articles: int = 0
    edits: int = 0
    images: int = 0
    users: int = 0
    active_users: int = 0
    groups: dict[str, int] = field(default_factory=dict)

    def numberingroup(self, group: str) -> int:
        return self.groups.get(group, 0)

    def pages_in_ns(self, ns: int) -> int:
        return 0


# MediaWiki's parser tests: seven files are uploaded (ParserTestRunner::setupUploads())
TEST_SITE_STATS = SiteStats(images=7)


def _parse_state(parser) -> dict:
    """Per-parse state (Parser::clearState() resets mRevisionTimestamp etc.): tied to ``parser.var_cache``, which
    PreprocessingMixin replaces at the start of each parse."""
    cache = getattr(parser, "var_cache", None)
    state = getattr(parser, "_core_parse_state", None)
    if state is None or state[0] is not cache:
        state = (cache, {})
        parser._core_parse_state = state
    return state[1]


def default_revision_record_callback(title: Title, parser) -> Optional[RevisionRecord]:
    """The current revision of a page from ``parser.fetch_current_revision_text()`` (Parser::
    statelessFetchRevisionRecord() without a database): its text and size; no id, timestamp or user."""
    fetch = getattr(parser, "fetch_current_revision_text", None)
    text = fetch(title) if callable(fetch) else None
    if text is None:
        return None
    return RevisionRecord(size=len(text.encode("utf-8")), content=text)


def _current_revision_record(parser, title: Title) -> Optional[RevisionRecord]:
    callback = getattr(parser, "current_revision_record_callback", None) or default_revision_record_callback
    return callback(title, parser) or None


def _page_key(title: Title) -> str:
    """CacheKeyHelper::getKeyForPage()"""
    return f"{title.namespace}:{title.db_key}"


def fetch_current_revision_record_of_title(parser, title: Title) -> Optional[RevisionRecord]:
    """Parser::fetchCurrentRevisionRecordOfTitle(): fetch the current revision of a given title (cached per parse)."""
    cache = _parse_state(parser).setdefault("current_revisions", {})
    key = _page_key(title)
    if key not in cache:
        cache[key] = _current_revision_record(parser, title)
    return cache[key]


def is_current_revision_of_title_cached(parser, title: Title) -> bool:
    """Parser::isCurrentRevisionOfTitleCached()"""
    return _page_key(title) in _parse_state(parser).get("current_revisions", {})


def get_revision_id(parser) -> Optional[int]:
    """Parser::getRevisionId(): the ID of the revision we are parsing"""
    return getattr(parser, "revision_id", None)


def get_revision_record_object(parser) -> Optional[RevisionRecord]:
    """Parser::getRevisionRecordObject(): the revision record object for getRevisionId()"""
    state = _parse_state(parser)
    if state.get("revision_record"):
        return state["revision_record"]
    # NOTE: try to get the RevisionRecord object even if mRevisionId is null. This is useful when parsing a revision
    # that has not yet been saved.
    rev = _current_revision_record(parser, parser.get_title())
    revision_id = get_revision_id(parser)
    if revision_id is None and rev and rev.id:
        # We are in preview mode (mRevisionId is null), and the current revision callback returned an existing
        # revision. Ignore it and return null, it's probably the page's current revision, which is not what we want
        # here.
        return None
    # If the parse is for a new revision, then the callback should have already been set to force the object and
    # should match mRevisionId. If not, try to fetch by mRevisionId instead (no database: nothing).
    if revision_id and rev and rev.id != revision_id:
        rev = None
    state["revision_record"] = rev
    return rev


def options_timestamp(parser) -> Any:
    """ParserOptions::getTimestamp(): the value as given (MediaWiki's parser tests give the int 123), a TS_MW string
    for a datetime, now if unset."""
    ts = getattr(parser, "timestamp", None)
    if ts is None or isinstance(ts, datetime):
        return php_date(to_datetime(ts), "YmdHis")
    return ts


def get_revision_timestamp(parser) -> str:
    """Parser::getRevisionTimestamp(): the timestamp associated with the current revision, adjusted for the default
    server-local timestamp"""
    state = _parse_state(parser)
    if state.get("revision_timestamp") is not None:
        return state["revision_timestamp"]
    # Use specified revision timestamp, falling back to the current timestamp
    rev = get_revision_record_object(parser)
    timestamp = rev.timestamp if rev and rev.timestamp else options_timestamp(parser)
    # The cryptic '' timezone parameter tells to use the site-default timezone offset instead of the user settings.
    state["revision_timestamp"] = ENGLISH.user_adjust(timestamp, "", local_tz_offset(parser))
    return state["revision_timestamp"]


def get_revision_user(parser) -> Optional[str]:
    """Parser::getRevisionUser(): the name of the user that edited the last revision"""
    state = _parse_state(parser)
    if state.get("revision_user") is None:
        rev = get_revision_record_object(parser)
        # if this template is subst: the revision id will be blank, so just use the current user's name
        if rev and rev.user:
            state["revision_user"] = rev.user
        elif getattr(parser, "ot", {}).get("wiki") or getattr(parser, "is_preview", False):
            state["revision_user"] = getattr(parser, "user_name", "127.0.0.1")
    return state.get("revision_user")


def get_revision_size(parser) -> Optional[int]:
    """Parser::getRevisionSize(): the size of the revision, or of the parser input when there is none"""
    state = _parse_state(parser)
    if state.get("revision_size") is None:
        rev = get_revision_record_object(parser)
        if rev:
            state["revision_size"] = rev.size
        else:
            size = getattr(parser, "input_size", None)
            state["revision_size"] = None if size is False else size
    return state.get("revision_size")


def get_function_lang(parser) -> Language:
    """Parser::getFunctionLang(): the page language, English here."""
    return ENGLISH


def get_content_language(parser) -> Language:
    return ENGLISH


def strip_section_name(parser, text: str) -> str:
    """Parser::stripSectionName(): strips a text string of wikitext for use in a section anchor"""
    # Strip internal link markup
    text = re.sub(r"\[\[:?([^[|]+)\|([^[]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[:?([^[]+)\|?\]\]", r"\1", text)
    # Strip external link markup
    # @todo FIXME: Not tolerant to blank link text
    # I.E. [https://www.mediawiki.org] will render as [1] or something depending on how many empty links there are
    # on the page - need to figure that out.
    text = re.sub(r"\[(?i:" + wf_url_protocols(config=parser.config) + r")([^ ]+?) ([^[]+)\]", r"\2", text)
    # Parse wikitext quotes (italics & bold)
    text = do_quotes(text)
    # Strip HTML tags
    return delimiter_replace("<", ">", "", text)


def _normalize_section_name(parser, text: str) -> str:
    """T90902: ensure the same normalization is applied for IDs as to links"""
    try:
        parts = get_title_codec(_site(parser)).split_title_string("#" + text)
    except MalformedTitleException:
        return text
    return parts["fragment"]


def guess_section_name_from_wiki_text(parser, text: str) -> str:
    """Parser::guessSectionNameFromWikiText(): try to guess the section anchor name based on a wikitext fragment
    presumably extracted from a heading, for example "Header" from "== Header ==". Returns '#' and the anchor."""
    text = strip_section_name(parser, text)
    text = normalize_section_name_whitespace(text)
    text = decode_char_references(text)
    section_name = _normalize_section_name(parser, text)
    return "#" + escape_id_for_link(section_name, config=parser.config)


def parse_width_param(value: str, parse_height: bool = True) -> dict[str, int]:
    """Parser::parseWidthParam(): parse the width (and height) of an image size like "200px" or "200x300px"."""
    parsed: dict[str, int] = {}
    if value == "":
        return parsed
    # (T15500) In both cases (width/height and width only), permit trailing "px" for backward compatibility.
    m = re.match(r"^([0-9]*)x([0-9]*)\s*(?:px)?\s*$", value) if parse_height else None
    if m:
        parsed["width"] = _php_intval(m.group(1))
        parsed["height"] = _php_intval(m.group(2))
    elif re.match(r"^[0-9]*\s*(?:px)?\s*$", value):
        parsed["width"] = _php_intval(value)
    return parsed


def tag_needs_nowiki_stripped_in_tag_pf(parser, lower_tag_name: str) -> bool:
    """Parser::tagNeedsNowikiStrippedInTagPF(): Parsoid's SiteConfig lists the extension tags registered with the
    stripNowiki option (T299103); core has none."""
    return lower_tag_name in getattr(parser, "nowiki_stripped_tags", ())


# ======================================================================================================================
# CoreParserFunctions
# ======================================================================================================================

def int_function(parser, part1: str = "", *params: str) -> dict:
    if _php_strval(part1) != "":
        return {0: message_plain(parser, part1, params), "noparse": False}
    return {"found": False}


def format_date(parser, date: str, default_pref: Optional[str] = None) -> str:
    df = get_date_formatter()
    date = _php_trim(date)
    pref = getattr(parser, "date_format", "default")  # ParserOptions::getDateFormat()
    # Specify a different default date format other than the normal default if the user has 'default' for their
    # setting
    if pref == "default" and default_pref:
        pref = default_pref
    return df.reformat(pref, date)


def ns(parser, part1: str = "") -> Union[str, dict]:
    if _php_intval(part1) or _php_equals_zero_string(part1):
        index: Optional[int] = _php_intval(part1)
    else:
        index = _site(parser).get_ns_index(part1.replace(" ", "_"))
    if index is not None:
        return _site(parser).get_formatted_ns_text(index)
    return {"found": False}


def nse(parser, part1: str = "") -> Union[str, dict]:
    ret = ns(parser, part1)
    if isinstance(ret, str):
        ret = wf_urlencode(ret.replace(" ", "_"))
    return ret


def urlencode(parser, s: str = "", arg: Optional[str] = None) -> str:
    """urlencodes a string according to one of three patterns: (T24474)

    By default (for HTTP "query" strings), spaces are encoded as '+'. Or to encode a value for the HTTP "path",
    spaces are encoded as '%20'. For links to "wiki"s, or similar software, spaces are encoded as '_'."""
    magic_words = parser.magic_words.new_array(["url_path", "url_query", "url_wiki"])
    which = magic_words.match_start_to_end(arg if arg is not None else "")
    if which == "url_wiki":
        # Encode as though it's a wiki page, '_' for ' '.
        func = wf_urlencode
        s = s.replace(" ", "_")
    elif which == "url_path":
        # Encode for an HTTP Path, '%20' for ' '.
        func = rawurlencode
    else:
        # Encode for HTTP query, '+' for ' '.
        func = php_urlencode
    # See T105242, where the choice to kill markers and various other options were discussed.
    return func(parser.kill_markers(s))


def lcfirst(parser, s: str = "") -> str:
    return get_content_language(parser).lcfirst(s)


def ucfirst(parser, s: str = "") -> str:
    return get_content_language(parser).ucfirst(s)


def lc(parser, s: str = "") -> str:
    return parser.marker_skip_callback(s, get_content_language(parser).lc)


def uc(parser, s: str = "") -> str:
    return parser.marker_skip_callback(s, get_content_language(parser).uc)


def localurl(parser, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    return url_function(parser, "get_local_url", s, arg)


def localurle(parser, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    temp = url_function(parser, "get_local_url", s, arg)
    return temp if not isinstance(temp, str) else htmlspecialchars(temp, quotes=False)


def fullurl(parser, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    return url_function(parser, "get_full_url", s, arg)


def fullurle(parser, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    temp = url_function(parser, "get_full_url", s, arg)
    return temp if not isinstance(temp, str) else htmlspecialchars(temp, quotes=False)


def canonicalurl(parser, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    return url_function(parser, "get_canonical_url", s, arg)


def canonicalurle(parser, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    temp = url_function(parser, "get_canonical_url", s, arg)
    return temp if not isinstance(temp, str) else htmlspecialchars(temp, quotes=False)


def url_function(parser, func: str, s: str = "", arg: Optional[str] = None) -> Union[str, dict]:
    site = _site(parser)
    title = Title.new_from_text(s, site=site)
    # Due to order of execution of a lot of bits, the values might be encoded before arriving here; if that's true,
    # then the title can't be created and the variable will fail. If we can't get a decent title from the first
    # attempt, url-decode and try for a second.
    if title is None:
        # Title::newFromURL(): '+' is a legal title character, so it is not turned into a space
        title = Title.new_from_db_key(urldecode(s).replace(" ", "_"), site=site)
    if title is not None:
        # Convert NS_MEDIA -> NS_FILE
        if title.in_namespace(NS_MEDIA):
            title = Title.make_title(NS_FILE, title.db_key, site=site)
        method = getattr(title, func)
        return method(arg) if arg is not None else method()
    return {"found": False}


def formatnum(parser, num: str = "", arg: Optional[str] = None) -> str:
    lang = get_function_lang(parser)
    if _match_against_magicword(parser, "rawsuffix", arg):
        func = lang.parse_formatted_number
    elif _match_against_magicword(parser, "nocommafysuffix", arg):
        func = _get_legacy_format_num(parser, lang.format_num_no_separators)
    else:
        func = _get_legacy_format_num(parser, lang.format_num)
    return parser.marker_skip_callback(num, func)


def _get_legacy_format_num(parser, callback: Callable[[str], str]) -> Callable[[str], str]:
    """For historic reasons, the formatNum parser function will take arguments which are not actually formatted
    numbers, which then trigger deprecation warnings in Language::formatNum*. Instead emit a tracking category
    instead to allow linting."""
    def wrapped(number: str) -> str:
        if not _php_is_numeric(number) and number not in ("NAN", "INF", "-INF"):
            parser.add_tracking_category("nonnumeric-formatnum")
            # Don't split on NAN/INF in the legacy case since they are likely to be found embedded inside non-numeric
            # text.
            return _VALID_NUMBER_RE.sub(lambda m: callback(m.group(0)), number)
        return callback(number)

    return wrapped


def grammar(parser, case: str = "", word: str = "") -> str:
    word = parser.kill_markers(word)
    return get_function_lang(parser).convert_grammar(word, case)


def gender(parser, username: str = "", *forms: str) -> str:
    # Some shortcuts to avoid loading user data unnecessarily
    if len(forms) == 0:
        return ""
    elif len(forms) == 1:
        return forms[0]
    # Without a user database every user has the default gender option, 'unknown' (GenderCache::getGenderOf()).
    gender_ = "unknown"
    return get_function_lang(parser).gender(gender_, list(forms))


def plural(parser, text: str = "", *forms: str) -> str:
    lang = get_function_lang(parser)
    text = lang.parse_formatted_number(text)
    count: Union[int, float] = _php_intval(text) if text.isascii() and text.isdigit() else _php_floatval(text)
    return lang.convert_plural(count, list(forms))


def bidi(parser, text: str = "") -> str:
    return get_function_lang(parser).embed_bidi(text)


def displaytitle(parser, text: str = "", uarg: str = "") -> str:
    """Override the title of the page when viewed, provided we've been given a title which will normalise to the
    canonical title"""
    restrict_display_title = _config_setting(parser, "restrict_display_title", True)
    magic_words = parser.magic_words.new_array(["displaytitle_noerror", "displaytitle_noreplace"])
    arg = magic_words.match_start_to_end(uarg)

    # parse a limited subset of wiki markup (just the single quote items)
    text = do_quotes(text)
    # remove stripped text (e.g. the UNIQ-QINU stuff) that was generated by tag extensions/whatever
    text = parser.kill_markers(text)

    # See T28547 for rationale for this processing.
    # list of disallowed tags for DISPLAYTITLE
    # these will be escaped even though they are allowed in normal wiki text
    bad = ["h1", "h2", "h3", "h4", "h5", "h6", "div", "blockquote", "ol", "ul", "li", "hr",
           "table", "tr", "th", "td", "dl", "dd", "caption", "p", "ruby", "rb", "rt", "rtc", "rp", "br"]

    # disallow some styles that could be used to bypass $wgRestrictDisplayTitle
    html_tags_callback = None
    if restrict_display_title:
        # This code is tested with the cases marked T28547 in parserTests.txt
        def html_tags_callback(attrs: dict) -> dict:
            decoded = dict(attrs)
            if "style" in decoded:
                # this is called later anyway, but we need it right now for the regexes below to be safe
                # calling it twice doesn't hurt
                decoded["style"] = check_css(decoded["style"])
                if re.search(r"(display|user-select|visibility)\s*:", decoded["style"], re.I | re.A):
                    decoded["style"] = "/* attempt to bypass $wgRestrictDisplayTitle */"
            return decoded

    # only requested titles that normalize to the actual title are allowed through
    # if $wgRestrictDisplayTitle is true (it is by default)
    # mimic the escaping process that occurs in OutputPage::setPageTitle
    text = remove_some_tags(text, attr_callback=html_tags_callback, remove_tags=bad, config=parser.config)
    title = _title_from_text(parser, strip_all_tags(text))
    # Decode entities in $text the same way that Title::newFromText does
    filtered_text = decode_char_references_and_normalize(text)

    if not restrict_display_title or (title is not None and not title.has_fragment()
                                       and title.equals(parser.get_title())):
        output = parser.get_output()
        old = _get_page_property(output, "displaytitle")
        if old is None or arg != "displaytitle_noreplace":
            # ParserOutput::setDisplayTitle()
            output.display_title = text
            _set_page_property(output, "displaytitle", text)
        if old is not None and old != text and not arg:
            return ('<span class="error">'
                    + message_text("duplicate-displaytitle", wf_escape_wiki_text(old, parser.config),
                                   wf_escape_wiki_text(filtered_text, parser.config))
                    + "</span>")
        return ""
    parser.get_output().add_warning_msg("restricted-displaytitle", filtered_text)
    parser.add_tracking_category("restricted-displaytitle-ignored")
    return ""


def _match_against_magicword(parser, magicword: str, value: Optional[str]) -> bool:
    """Matches the given value against the value of given magic word"""
    value = _php_trim(_php_strval(value))
    if value == "":
        return False
    return parser.magic_words.get(magicword).match_start_to_end(value)


def format_raw(parser, num: Union[int, float], raw: Optional[str], language: Optional[Language] = None) -> str:
    """Formats a number according to a language."""
    if raw is not None and _match_against_magicword(parser, "rawsuffix", raw):
        return _php_strval(num)
    return (language or get_function_lang(parser)).format_num(num)


def _site_stats(parser) -> SiteStats:
    return getattr(parser, "site_stats", None) or SiteStats()


def numberofpages(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).pages, raw)


def numberofusers(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).users, raw)


def numberofactiveusers(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).active_users, raw)


def numberofarticles(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).articles, raw)


def numberoffiles(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).images, raw)


def numberofadmins(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).numberingroup("sysop"), raw)


def numberofedits(parser, raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).edits, raw)


def pagesinnamespace(parser, namespace: str = "0", raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).pages_in_ns(_php_intval(namespace)), raw)


def numberingroup(parser, name: str = "", raw: Optional[str] = None) -> str:
    return format_raw(parser, _site_stats(parser).numberingroup(_php_strtolower(name)), raw)


def namespace(parser, title: Optional[str] = None) -> str:
    """Given a title, return the namespace name that would be given by the corresponding magic word. @since 1.39"""
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return (t.ns_text or "").replace("_", " ")


def mwnamespace(parser, title: Optional[str] = None) -> str:
    """@deprecated Use namespace() instead."""
    return namespace(parser, title)


def namespacee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return wf_urlencode(t.ns_text or "")


def namespacenumber(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return str(t.namespace)


def talkspace(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None or not t.can_have_talk_page():
        return ""
    return (t.talk_ns_text or "").replace("_", " ")


def talkspacee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None or not t.can_have_talk_page():
        return ""
    return wf_urlencode(t.talk_ns_text or "")


def subjectspace(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return (t.subject_ns_text or "").replace("_", " ")


def subjectspacee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return wf_urlencode(t.subject_ns_text or "")


def _escape(parser, text: str) -> str:
    return wf_escape_wiki_text(text, parser.config)


def pagename(parser, title: Optional[str] = None) -> str:
    """Functions to get and normalize pagenames, corresponding to the magic words of the same names"""
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.text)


def pagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.partial_url)


def fullpagename(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None or not t.can_have_talk_page():
        return ""
    return _escape(parser, t.prefixed_text)


def fullpagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None or not t.can_have_talk_page():
        return ""
    return _escape(parser, t.prefixed_url)


def subpagename(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.subpage_text)


def subpagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.subpage_url_form)


def rootpagename(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.root_text)


def rootpagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, wf_urlencode(t.root_text.replace(" ", "_")))


def basepagename(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.base_text)


def basepagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, wf_urlencode(t.base_text.replace(" ", "_")))


def talkpagename(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None or not t.can_have_talk_page():
        return ""
    return _escape(parser, t.get_talk_page().prefixed_text)


def talkpagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None or not t.can_have_talk_page():
        return ""
    return _escape(parser, t.get_talk_page().prefixed_url)


def subjectpagename(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.get_subject_page().prefixed_text)


def subjectpagenamee(parser, title: Optional[str] = None) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    return _escape(parser, t.get_subject_page().prefixed_url)


def pagesincategory(parser, name: str = "", arg1: str = "", arg2: str = "") -> str:
    """Return the number of pages, files or subcats in the given category, or 0 if it's nonexistent. This is an
    expensive parser function and can't be called too many times per page."""
    magic_words = parser.magic_words.new_array(["pagesincategory_all", "pagesincategory_pages",
                                                "pagesincategory_subcats", "pagesincategory_files"])
    cache = _parse_state(parser).setdefault("pagesincategory", {})

    # split the given option to its variable
    if _match_against_magicword(parser, "rawsuffix", arg1):
        # {{pagesincategory:|raw[|type]}}
        raw: Optional[str] = arg1
        type_ = magic_words.match_start_to_end(arg2)
    else:
        # {{pagesincategory:[|type[|raw]]}}
        type_ = magic_words.match_start_to_end(arg1)
        raw = arg2
    if not type_:  # backward compatibility
        type_ = "pagesincategory_all"

    title = Title.make_title_safe(NS_CATEGORY, name, site=_site(parser))
    if not title:  # invalid title
        return format_raw(parser, 0, raw)

    # Normalize name for cache
    name = title.db_key
    if name not in cache:
        counts = {"all": 0, "pages": 0, "subcats": 0, "files": 0}
        if parser.increment_expensive_function_count():
            getter = getattr(parser, "category_counts", None)
            if callable(getter):
                counts.update(getter(title) or {})
        cache[name] = {
            "pagesincategory_all": counts["all"],
            "pagesincategory_pages": counts["pages"],
            "pagesincategory_subcats": counts["subcats"],
            "pagesincategory_files": counts["files"],
        }
    return format_raw(parser, cache[name][type_], raw)


def pagesize(parser, page: str = "", raw: Optional[str] = None) -> str:
    """Return the size of the given page, or 0 if it's nonexistent. This is an expensive parser function and can't
    be called too many times per page."""
    title = _title_from_text(parser, page)
    if title is None:
        return format_raw(parser, 0, raw)
    # fetch revision from cache/database and return the value
    rev = get_cached_revision_object(parser, title, "vary-revision-sha1")
    length = rev.size if rev else 0
    if length is None:
        # We've had bugs where rev_len was not being recorded for empty pages, see T135414
        length = 0
    return format_raw(parser, length, raw)


def _restrictions_loaded(parser, title: Title) -> bool:
    return _page_key(title) in _parse_state(parser).get("restrictions_loaded", set())


def _load_restrictions(parser, title: Title) -> None:
    _parse_state(parser).setdefault("restrictions_loaded", set()).add(_page_key(title))


def _get_restrictions(parser, title: Title, action: str) -> list[str]:
    _load_restrictions(parser, title)
    getter = getattr(parser, "restrictions", None)
    return list(getter(title, action) or []) if callable(getter) else []


def _get_restriction_expiry(parser, title: Title, action: str) -> Optional[str]:
    """RestrictionStore::getRestrictionExpiry(): 'infinity' for the applicable restriction types of an unprotected
    page (edit and move, upload for files; create for a page that does not exist), None for other actions."""
    _load_restrictions(parser, title)
    exists = fetch_current_revision_record_of_title(parser, title) is not None
    if not exists:
        types = ["create"]
    else:
        types = ["edit", "move"] + (["upload"] if title.namespace == NS_FILE else [])
    expiry = getattr(parser, "restriction_expiry", None)
    if callable(expiry):
        return expiry(title, action)
    return "infinity" if action in types else None


def protectionlevel(parser, type_: str = "", title: str = "") -> str:
    """Returns the requested protection level for the current page. This is an expensive parser function and can't
    be called too many times per page, unless the protection levels/expiries for the given title have already been
    retrieved"""
    title_object = _title_from_text(parser, title) or parser.get_title()
    if _restrictions_loaded(parser, title_object) or parser.increment_expensive_function_count():
        restrictions = _get_restrictions(parser, title_object, _php_strtolower(type_))
        # RestrictionStore::getRestrictions returns an array, its possible it may have multiple values in the future
        return ",".join(restrictions)
    return ""


def protectionexpiry(parser, type_: str = "", title: str = "") -> str:
    """Returns the requested protection expiry for the current page."""
    title_object = _title_from_text(parser, title) or parser.get_title()
    if _restrictions_loaded(parser, title_object) or parser.increment_expensive_function_count():
        expiry = _get_restriction_expiry(parser, title_object, _php_strtolower(type_))
        # getRestrictionExpiry() returns null on invalid type; trying to match protectionlevel() function that
        # returns empty string instead
        return "" if expiry is None else expiry
    return ""


def language(parser, code: str = "", in_language: str = "") -> str:
    """Gives language names."""
    code = _php_strtolower(code)
    in_language = _php_strtolower(in_language)
    lang = get_language_name(code, in_language)
    return lang if lang != "" else bcp47(code)


def pad(parser, string: str, length: Any, padding: str = "0", direction: str = "right") -> str:
    """Unicode-safe str_pad with the restriction that $length is forced to be <= 500"""
    padding = parser.kill_markers(padding)
    length_of_padding = len(padding)
    if length_of_padding == 0:
        return string
    # The remaining length to add counts down to 0 as padding is added
    length = min(_php_intval(length), 500) - len(string)
    if length <= 0:
        # Nothing to add
        return string
    # final_padding is just padding repeated enough times so that len(string) + len(final_padding) == length
    final_padding = ""
    while length > 0:
        # If $length < $lengthofPadding, truncate $padding so we get the exact length desired.
        final_padding += padding[:length]
        length -= length_of_padding
    if direction == "left":
        return final_padding + string
    return string + final_padding


def padleft(parser, string: str = "", length: Any = 0, padding: str = "0") -> str:
    return pad(parser, string, length, padding, "left")


def padright(parser, string: str = "", length: Any = 0, padding: str = "0") -> str:
    return pad(parser, string, length, padding)


def anchorencode(parser, text: str = "") -> str:
    text = parser.kill_markers(text)
    section = guess_section_name_from_wiki_text(parser, text)[1:]
    encoded_section = safe_encode_attribute(section, config=parser.config)
    # decode underscores to avoid breaking templates (T407131)
    return encoded_section.replace("&#95;", "_")


def special(parser, text: str = "") -> str:
    page, subpage = resolve_alias(text)
    site = _site(parser)
    if page:
        return special_page_title_for(page, subpage, site).prefixed_text
    # unknown special page, just use the given text as its title, if at all possible
    title = Title.make_title_safe(NS_SPECIAL, text, site=site)
    return title.prefixed_text if title else special(parser, "Badtitle")


def speciale(parser, text: str = "") -> str:
    return wf_urlencode(special(parser, text).replace(" ", "_"))


def defaultsort(parser, text: str = "", uarg: str = "") -> str:
    """``text``: the sortkey to use. ``uarg``: either "noreplace" or "noerror" (in en); both suppress errors, and
    noreplace does nothing if a default sortkey already exists."""
    magic_words = parser.magic_words.new_array(["defaultsort_noerror", "defaultsort_noreplace"])
    arg = magic_words.match_start_to_end(uarg)

    text = _php_trim(text)
    if len(text) == 0:
        return ""
    output = parser.get_output()
    old = _get_page_property(output, "defaultsort")
    if old is None or arg != "defaultsort_noreplace":
        _set_page_property(output, "defaultsort", text)

    if old is None or old == text or arg:
        return ""
    return ('<span class="error">'
            + message_text("duplicate-defaultsort", wf_escape_wiki_text(old, parser.config),
                           wf_escape_wiki_text(text, parser.config))
            + "</span>")


def filepath(parser, name: str = "", arg_a: str = "", arg_b: str = "") -> Union[str, dict]:
    """Usage {{filepath|300}}, {{filepath|nowiki}}, {{filepath|nowiki|300}} or {{filepath|300|nowiki}} or
    {{filepath|300px}}, {{filepath|200x300px}}, {{filepath|nowiki|200x300px}}, {{filepath|200x300px|nowiki}}.

    Files come from ``parser.find_file(name)`` (RepoGroup::findFile()); thumbnails need ``file.transform(params)``
    returning an object with ``get_url()`` (and optionally ``is_error()``)."""
    finder = getattr(parser, "find_file", None)
    file = finder(name) if callable(finder) else None

    if arg_a == "nowiki":
        # {{filepath: | option [| size] }}
        is_nowiki = True
        parsed_width_param = parse_width_param(arg_b)
    else:
        # {{filepath: [| size [|option]] }}
        parsed_width_param = parse_width_param(arg_a)
        is_nowiki = arg_b == "nowiki"

    if file:
        url = file.get_full_url()
        # If a size is requested...
        if parsed_width_param and hasattr(file, "transform"):
            mto = file.transform(parsed_width_param)
            # ... and we can
            if mto and not (hasattr(mto, "is_error") and mto.is_error()):
                # ... change the URL to point to a thumbnail.
                url = mto.get_url()
        if is_nowiki:
            return {0: url, "nowiki": True}
        return url
    return ""


def tag_obj(parser, frame, args: list) -> str:
    """Parser function to extension tag adaptor"""
    if not args:
        return ""
    args = list(args)
    tag_name = _php_strtolower(_php_trim(frame.expand(args.pop(0))))
    process_nowiki = PROCESS_NOWIKI if tag_needs_nowiki_stripped_in_tag_pf(parser, tag_name) else 0

    inner = frame.expand(args.pop(0), process_nowiki) if args else None

    attributes: dict[str, str] = {}
    for arg in args:
        bits = arg.split_arg()
        if _php_strval(bits.get("index", "")) == "":
            name = _php_trim(frame.expand(bits["name"], STRIP_COMMENTS))
            value = _php_trim(frame.expand(bits["value"]))
            m = re.match(r"^(?:[\"'](.+)[\"']|\"\"|'')$", value, re.S)
            if m:
                value = m.group(1) or ""
            attributes[name] = value

    strip_list = parser.get_strip_list()
    if tag_name not in strip_list:
        # we can't handle this tag (at least not now), so just re-emit it as an ordinary tag
        attr_text = "".join(f' {htmlspecialchars(name)}="{htmlspecialchars(value, quotes=False)}"'
                            for name, value in attributes.items())
        if inner is None:
            return f"<{tag_name}{attr_text}/>"
        return f"<{tag_name}{attr_text}>{inner}</{tag_name}>"

    params = {
        "name": tag_name,
        "inner": inner,
        "attributes": attributes,
        "close": f"</{tag_name}>",
    }
    return parser.extension_substitution(params, frame)


def get_cached_revision_object(parser, title: Optional[Title], vary: str) -> Optional[RevisionRecord]:
    """Fetched the current revision of the given title and return this. Will increment the expensive function count
    and add a template link to get the value refreshed on changes. For a given title, which is equal to the current
    parser title, the RevisionRecord object from the parser is used, when that is the current one"""
    if not title:
        return None
    revision_record = None
    is_self_referential = title.equals(parser.get_title())
    if is_self_referential:
        # Revision is for the same title that is currently being parsed. Only use the last saved revision, regardless
        # of Parser::getRevisionId() or fake revision injection callbacks against the current title.
        parser_revision_record = get_revision_record_object(parser)
        if parser_revision_record and parser_revision_record.is_current():
            revision_record = parser_revision_record

    output = parser.get_output()
    if not revision_record:
        if not is_current_revision_of_title_cached(parser, title) and not parser.increment_expensive_function_count():
            return None  # not allowed
        # Get the current revision, ignoring Parser::getRevisionId() being null/old
        revision_record = fetch_current_revision_record_of_title(parser, title)
        # Register dependency in templatelinks
        output.add_template(title.prefixed_text)

    if is_self_referential:
        # Upon page save, the result of the parser function using this might change
        _set_output_flag(parser, vary)
    return revision_record


def _article_id(parser, title: Title) -> int:
    """Title::getArticleID() without a database: the page id of the current revision record, 0 if none."""
    rev = fetch_current_revision_record_of_title(parser, title)
    return rev.page_id if rev else 0


def pageid(parser, title: Optional[str] = None) -> str:
    """Get the pageid of a specified page"""
    t = _title_from_text(parser, title)
    if not t:
        return ""
    elif not t.can_exist() or t.is_external():
        return "0"  # e.g. special page or interwiki link
    if t.equals(parser.get_title()):
        # Revision is for the same title that is currently being parsed. Use the title from Parser in case a new
        # page ID was injected into it.
        _set_output_flag(parser, "vary-page-id")
        return str(_article_id(parser, parser.get_title()))
    # We need to load it from the DB, so mark expensive
    if parser.increment_expensive_function_count():
        return str(_article_id(parser, t))
    return ""


def revisionid(parser, title: Optional[str] = None) -> str:
    """Get the id from the last revision of a specified page."""
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    site = _site(parser)
    if (t.equals(parser.get_title()) and _config_setting(parser, "miser_mode", False)
            and not getattr(parser, "interface_message", False) and site.is_subject(t.namespace)):
        # Use a stub result instead of the actual revision ID in order to avoid double parses on page save but still
        # allow preview detection (T137900)
        if get_revision_id(parser):
            return "-"
        _set_output_flag(parser, "vary-revision-exists")
        return ""
    # fetch revision from cache/database and return the value
    rev = get_cached_revision_object(parser, t, "vary-revision-id")
    return str(rev.id) if rev else ""


def _revision_timestamp_format(parser, title: Optional[str], fmt: str) -> str:
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    # fetch revision from cache/database and return the value
    rev = get_cached_revision_object(parser, t, "vary-revision-timestamp")
    if not rev or not rev.timestamp:
        return ""
    return php_date(get_local_instance(parser, rev.timestamp), fmt)


def revisionday(parser, title: Optional[str] = None) -> str:
    """Get the day from the last revision of a specified page."""
    return _revision_timestamp_format(parser, title, "j")


def revisionday2(parser, title: Optional[str] = None) -> str:
    """Get the day with leading zeros from the last revision of a specified page."""
    return _revision_timestamp_format(parser, title, "d")


def revisionmonth(parser, title: Optional[str] = None) -> str:
    """Get the month with leading zeros from the last revision of a specified page."""
    return _revision_timestamp_format(parser, title, "m")


def revisionmonth1(parser, title: Optional[str] = None) -> str:
    """Get the month from the last revision of a specified page."""
    return _revision_timestamp_format(parser, title, "n")


def revisionyear(parser, title: Optional[str] = None) -> str:
    """Get the year from the last revision of a specified page."""
    return _revision_timestamp_format(parser, title, "Y")


def revisiontimestamp(parser, title: Optional[str] = None) -> str:
    """Get the timestamp from the last revision of a specified page."""
    return _revision_timestamp_format(parser, title, "YmdHis")


def revisionuser(parser, title: Optional[str] = None) -> str:
    """Get the user from the last revision of a specified page."""
    t = _title_from_text(parser, title)
    if t is None:
        return ""
    rev = get_cached_revision_object(parser, t, "vary-user")
    if rev is None:
        return ""
    return rev.user or ""


def cascadingsources(parser, title: str = "") -> str:
    """Returns the sources of any cascading protection acting on a specified page. Pages will not return their own
    title unless they transclude themselves. This is an expensive parser function and can't be called too many
    times per page, unless cascading protection sources for the page have already been loaded."""
    title_object = _title_from_text(parser, title) or parser.get_title()
    loaded = _parse_state(parser).setdefault("cascade_sources_loaded", set())
    if _page_key(title_object) in loaded or parser.increment_expensive_function_count():
        loaded.add(_page_key(title_object))
        getter = getattr(parser, "cascade_protection_sources", None)
        sources = list(getter(title_object) or []) if callable(getter) else []
        return "|".join(source.prefixed_text for source in sources)
    return ""


# Syntax for arguments (see Parser::setFunctionHook):
#  "name for lookup in localized magic words array", function callback, optional SFH_NO_HASH to omit the hash from
#  calls (e.g. {{int:...}} instead of {{#int:...}})
NO_HASH_FUNCTIONS: dict[str, Callable] = {
    "ns": ns, "nse": nse, "urlencode": urlencode, "lcfirst": lcfirst, "ucfirst": ucfirst, "lc": lc, "uc": uc,
    "localurl": localurl, "localurle": localurle, "fullurl": fullurl, "fullurle": fullurle,
    "canonicalurl": canonicalurl, "canonicalurle": canonicalurle, "formatnum": formatnum, "grammar": grammar,
    "gender": gender, "plural": plural, "bidi": bidi,
    "numberofpages": numberofpages, "numberofusers": numberofusers, "numberofactiveusers": numberofactiveusers,
    "numberofarticles": numberofarticles, "numberoffiles": numberoffiles, "numberofadmins": numberofadmins,
    "numberingroup": numberingroup, "numberofedits": numberofedits, "language": language,
    "padleft": padleft, "padright": padright, "anchorencode": anchorencode, "defaultsort": defaultsort,
    "filepath": filepath, "pagesincategory": pagesincategory, "pagesize": pagesize,
    "protectionlevel": protectionlevel, "protectionexpiry": protectionexpiry,
    "namespace": namespace,
    "namespacee": namespacee, "namespacenumber": namespacenumber, "talkspace": talkspace, "talkspacee": talkspacee,
    "subjectspace": subjectspace, "subjectspacee": subjectspacee, "pagename": pagename, "pagenamee": pagenamee,
    "fullpagename": fullpagename, "fullpagenamee": fullpagenamee, "rootpagename": rootpagename,
    "rootpagenamee": rootpagenamee, "basepagename": basepagename, "basepagenamee": basepagenamee,
    "subpagename": subpagename, "subpagenamee": subpagenamee, "talkpagename": talkpagename,
    "talkpagenamee": talkpagenamee, "subjectpagename": subjectpagename, "subjectpagenamee": subjectpagenamee,
    "pageid": pageid, "revisionid": revisionid, "revisionday": revisionday, "revisionday2": revisionday2,
    "revisionmonth": revisionmonth, "revisionmonth1": revisionmonth1, "revisionyear": revisionyear,
    "revisiontimestamp": revisiontimestamp, "revisionuser": revisionuser, "cascadingsources": cascadingsources,
}


def _ignore_surplus_args(callback: Callable) -> Callable:
    """PHP drops the arguments a function does not declare ({{lc:a|b}} calls lc( $parser, 'a', 'b' )); Python
    would raise TypeError."""
    params = inspect.signature(callback).parameters.values()
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return callback
    count = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))

    @functools.wraps(callback)
    def wrapper(*args):
        return callback(*args[:count])

    return wrapper


def register(parser) -> None:
    """CoreParserFunctions::register(): the core parser functions, with $wgAllowDisplayTitle (default true) and
    $wgAllowSlowParserFunctions (default false) read from the parser's config if it has them."""
    allow_display_title = _config_setting(parser, "allow_display_title", True)
    allow_slow_parser_functions = _config_setting(parser, "allow_slow_parser_functions", False)

    def hook(name: str, callback: Callable, flags: int = 0) -> None:
        parser.set_function_hook(name, _ignore_surplus_args(callback), flags)

    for func, callback in NO_HASH_FUNCTIONS.items():
        hook(func, callback, SFH_NO_HASH)

    hook("int", int_function, SFH_NO_HASH)
    hook("special", special)
    hook("speciale", speciale)
    hook("tag", tag_obj, SFH_OBJECT_ARGS)
    hook("formatdate", format_date)

    if allow_display_title:
        hook("displaytitle", displaytitle, SFH_NO_HASH)
    if allow_slow_parser_functions:
        hook("pagesinnamespace", pagesinnamespace, SFH_NO_HASH)

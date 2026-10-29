# Ported from MediaWiki 1.39 includes/libs/StringUtils.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the class of static methods became
# module-level functions; isValidPCRERegex() is left out (it checks PHP regex syntax, which Python cannot).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Methods to play with strings.

PHP strings are bytes and Python strings are code points. All offsets here come from matching literal
delimiters, so working on code points gives the same results as PHP's byte offsets.
"""
from __future__ import annotations

import re
from typing import Callable, Iterator, Sequence, Union


def is_utf8(value: Union[bytes, str]) -> bool:
    """Test whether a string is valid UTF-8.

    The function check for invalid byte sequences, overlong encoding but not for different normalisations.

    PHP uses ``mb_check_encoding( $value, 'UTF-8' )``; Python's strict UTF-8 decoder rejects the same sequences
    (overlong forms, surrogates, code points above U+10FFFF). A Python ``str`` is valid unless it holds lone
    surrogates, which cannot be encoded.
    """
    try:
        if isinstance(value, str):
            value.encode("utf-8")
        else:
            bytes(value).decode("utf-8")
    except UnicodeError:
        return False
    return True


def delimiter_explode(start_delim: str, end_delim: str, separator: str, subject: str,
                      nested: bool = False) -> Iterator[str]:
    """Explode a string, but ignore any instances of the separator inside the given start and end delimiters,
    which may optionally nest. The delimiters are literal strings, not regular expressions.

    ``nested``: true iff the delimiters are allowed to nest. Returns an iterator, as PHP's ArrayIterator.
    """
    input_pos = 0
    last_pos = 0
    depth = 0
    pattern = re.compile(f"{re.escape(start_delim)}|{re.escape(end_delim)}|{re.escape(separator)}")
    length = len(subject)
    exploded: list[str] = []
    while input_pos < length:
        m = pattern.search(subject, input_pos)
        if not m:
            break
        match = m.group(0)
        match_pos = m.start()
        input_pos = match_pos + len(match)
        if match == separator:
            if depth == 0:
                exploded.append(subject[last_pos:match_pos])
                last_pos = input_pos
        elif match == start_delim:
            if depth == 0 or nested:
                depth += 1
        else:
            depth -= 1
    exploded.append(subject[last_pos:])
    # This method could be rewritten in the future to avoid creating an intermediate array, since the return type
    # is just an iterator.
    return iter(exploded)


def hungry_delimiter_replace(start_delim: str, end_delim: str, replace: str, subject: str) -> str:
    """Perform an operation equivalent to ``preg_replace()``

    Matches this code::

        preg_replace( "!$startDelim(.*?)$endDelim!", $replace, $subject );

    ..except that it's worst-case O(N) instead of O(N^2). Compared to delimiterReplace(), this implementation is
    fast but memory-hungry and inflexible. The memory requirements are such that I don't recommend using it on
    anything but guaranteed small chunks of text.
    """
    segments = subject.split(start_delim)
    output = segments.pop(0)
    for s in segments:
        end_delim_pos = s.find(end_delim)
        if end_delim_pos == -1:
            output += start_delim + s
        else:
            output += replace + s[end_delim_pos + len(end_delim):]
    return output


def _regex_flags(flags: str) -> int:
    """PHP regex modifier letters as Python flags. 'S' (study) and 'u' (UTF-8) have no Python equivalent and need
    none: Python matches code points anyway."""
    result = 0
    for flag, value in (("i", re.I), ("m", re.M), ("s", re.S), ("x", re.X)):
        if flag in flags:
            result |= value
    return result


def _php_strcasecmp_equal(a: str, b: str) -> bool:
    """strcasecmp() == 0: PHP folds only ASCII letters."""
    return _ascii_lower(a) == _ascii_lower(b)


def _ascii_lower(s: str) -> str:
    return s.translate(_ASCII_LOWER)


_ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}


def delimiter_replace_callback(start_delim: str, end_delim: str, callback: Callable[[Sequence[str]], str],
                               subject: str, flags: str = "") -> str:
    """Perform an operation equivalent to ``preg_replace_callback()``

    Matches this code::

        preg_replace_callback( "!$startDelim(.*)$endDelim!s$flags", $callback, $subject );

    If the start delimiter ends with an initial substring of the end delimiter, e.g. in the case of C-style
    comments, the behavior differs from the model regex. In this implementation, the end must share no characters
    with the start, so e.g. ``/*/`` is not considered to be both the start and end of a comment. ``/*/xy/*/`` is
    considered to be a single comment with contents ``/xy/``.

    The implementation of delimiterReplaceCallback() is slower than hungryDelimiterReplace() but uses far less
    memory. The delimiters are literal strings, not regular expressions.

    ``callback`` gets ``[whole match, text between the delimiters]``. ``flags``: PHP regular expression flags
    (e.g. "i"). Private in PHP; public here because the table code uses it.
    """
    input_pos = 0
    output_pos = 0
    content_pos = 0
    output = []
    found_start = False
    case_insensitive = "i" in flags
    end_length = len(end_delim)
    pattern = re.compile(f"({re.escape(start_delim)})|({re.escape(end_delim)})",
                         _regex_flags(flags) | (re.ASCII if case_insensitive else 0))  # byte regex: ASCII /i

    while input_pos < len(subject):
        m = pattern.search(subject, input_pos)
        if not m:
            break
        token_offset = m.start()
        if m.group(1) is not None and m.group(1) != "":
            candidate = subject[token_offset:token_offset + end_length]
            same = (_php_strcasecmp_equal(end_delim, candidate) if case_insensitive else end_delim == candidate)
            if found_start and same:
                # An end match is present at the same location
                token_type = "end"
                token_length = end_length
            else:
                token_type = "start"
                token_length = len(m.group(0))
        elif m.group(2) is not None and m.group(2) != "":
            token_type = "end"
            token_length = len(m.group(0))
        else:
            raise ValueError("Invalid delimiter given to delimiter_replace_callback")

        if token_type == "start":
            # Only move the start position if we haven't already found a start
            # This means that START START END matches outer pair
            if not found_start:
                # Found start
                input_pos = token_offset + token_length
                # Write out the non-matching section
                output.append(subject[output_pos:token_offset])
                output_pos = token_offset
                content_pos = input_pos
                found_start = True
            else:
                # Move the input position past the *first character* of START,
                # to protect against missing END when it overlaps with START
                input_pos = token_offset + 1
        else:
            if found_start:
                # Found match
                output.append(callback([
                    subject[output_pos:token_offset + token_length],
                    subject[content_pos:token_offset],
                ]))
                found_start = False
            else:
                # Non-matching end, write it out
                # (PHP: substr( $subject, $inputPos, $tokenOffset + $tokenLength - $outputPos ); the two
                # positions are always equal here)
                output.append(subject[input_pos:input_pos + token_offset + token_length - output_pos])
            input_pos = output_pos = token_offset + token_length
    if output_pos < len(subject):
        output.append(subject[output_pos:])

    return "".join(output)


def delimiter_replace(start_delim: str, end_delim: str, replace: str, subject: str, flags: str = "") -> str:
    """Perform an operation equivalent to ``preg_replace()`` with flags.

    Matches this code::

        preg_replace( "!$startDelim(.*)$endDelim!$flags", $replace, $subject );

    ``replace``: replacement string. May contain $1, which will be replaced by the text between the delimiters
    (and $0, the whole match). Returns the string with the matches replaced.
    """
    def callback(matches: Sequence[str]) -> str:
        return php_strtr(replace, {"$0": matches[0], "$1": matches[1]})

    return delimiter_replace_callback(start_delim, end_delim, callback, subject, flags)


def replace_markup(search: str, replace: str, text: str) -> str:
    """More or less "markup-safe" str_replace()
    Ignores any instances of the separator inside ``<...>``
    """
    placeholder = "\x00"

    # Remove placeholder instances
    text = text.replace(placeholder, "")

    # Replace instances of the separator inside HTML-like tags with the placeholder
    cleaned = delimiter_replace_callback(
        "<", ">",
        lambda matches: php_str_replace(search, placeholder, matches[0]),
        text,
    )

    # Explode, then put the replaced separators back in
    cleaned = php_str_replace(search, replace, cleaned)
    text = cleaned.replace(placeholder, search)

    return text


def escape_regex_replacement(string: str) -> str:
    """Escape a string to make it suitable for inclusion in a preg_replace() replacement parameter.

    This escapes for PHP's replacement syntax (``\\`` and ``$``); Python's ``re.sub`` uses another syntax
    (``\\g<1>``), for which ``string.replace("\\\\", "\\\\\\\\")`` is enough.
    """
    string = string.replace("\\", "\\\\")
    return string.replace("$", "\\$")


def explode(separator: str, subject: str) -> Iterator[str]:
    """Workalike for explode() with limited memory usage. (PHP switches to an ExplodeIterator above 1000 parts;
    a Python iterator over ``str.split`` serves both cases.)"""
    return iter(subject.split(separator))


def php_str_replace(search: str, replace: str, subject: str) -> str:
    """str_replace() with one search string: PHP returns the subject unchanged for an empty search, Python's
    str.replace would insert ``replace`` between every character."""
    if search == "":
        return subject
    return subject.replace(search, replace)


def php_strtr(text: str, pairs: dict[str, str]) -> str:
    """strtr( $text, $pairs ): one pass, longest key first at each position, replaced text is not searched again.
    Empty keys are ignored, as in PHP."""
    keys = sorted((k for k in pairs if k != ""), key=len, reverse=True)
    if not keys:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    return pattern.sub(lambda m: pairs[m.group(0)], text)

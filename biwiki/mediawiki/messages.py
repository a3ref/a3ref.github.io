# English interface messages from MediaWiki 1.39 languages/i18n/en.json (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: only the messages the parser uses, as a Python dict; a simple
# wfMessage() that replaces $1, $2, ... (no PLURAL/GRAMMAR, which these messages do not use).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The parser's interface messages, in English (the BI wiki's content language)."""
from __future__ import annotations

MESSAGES = {
    "parser-unstrip-loop-warning": "Unstrip loop detected",
    "unstrip-depth-warning": "Unstrip depth limit exceeded ($1)",
    "unstrip-size-warning": "Unstrip size limit exceeded ($1)",
    "rfcurl": "https://tools.ietf.org/html/rfc$1",
    "pubmedurl": "//www.ncbi.nlm.nih.gov/pubmed/$1?dopt=Abstract",
    "toc": "Contents",
    "showtoc": "show",
    "hidetoc": "hide",
    "editsection": "edit",
    "editsectionhint": "Edit section: $1",
    "pipe-separator": "&#32;|&#32;",
    # Language: month and weekday names, formatNum (coreparserfunctions.py)
    "january": "January", "february": "February", "march": "March", "april": "April", "may_long": "May",
    "june": "June", "july": "July", "august": "August", "september": "September", "october": "October",
    "november": "November", "december": "December",
    "january-gen": "January", "february-gen": "February", "march-gen": "March", "april-gen": "April",
    "may-gen": "May", "june-gen": "June", "july-gen": "July", "august-gen": "August", "september-gen": "September",
    "october-gen": "October", "november-gen": "November", "december-gen": "December",
    "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "may": "May", "jun": "Jun", "jul": "Jul", "aug": "Aug",
    "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec",
    "sunday": "Sunday", "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday", "thursday": "Thursday",
    "friday": "Friday", "saturday": "Saturday",
    "formatnum-nan": "Not a Number",
    # CoreParserFunctions
    "duplicate-displaytitle":
        "<strong>Warning:</strong> Display title \"$2\" overrides earlier display title \"$1\".",
    "duplicate-defaultsort":
        "<strong>Warning:</strong> Default sort key \"$2\" overrides earlier default sort key \"$1\".",
    "restricted-displaytitle":
        "<strong>Warning:</strong> Display title \"$1\" was ignored since it is not equivalent to the page's actual "
        "title.",
    "nonnumeric-formatnum": "Pages with non-numeric formatnum arguments",
    "restricted-displaytitle-ignored": "Pages with ignored display titles",
    # used by MediaWiki's parser tests through {{int:}}
    "youhavenewmessages": "{{PLURAL:$3|You have}} $1 ($2).",
    "ok": "OK",
}


def msg(key: str, *params) -> str:
    """wfMessage( $key, ...$params )->inContentLanguage()->text()"""
    text = MESSAGES[key]
    for i, p in enumerate(params, 1):
        text = text.replace(f"${i}", str(p))
    return text

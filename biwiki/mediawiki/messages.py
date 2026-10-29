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
}


def msg(key: str, *params) -> str:
    """wfMessage( $key, ...$params )->inContentLanguage()->text()"""
    text = MESSAGES[key]
    for i, p in enumerate(params, 1):
        text = text.replace(f"${i}", str(p))
    return text

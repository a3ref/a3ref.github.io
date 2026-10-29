# Ported from MediaWiki 1.39 includes/parser/StripState.php and the strip marker constants of
# includes/parser/Parser.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the warnings use the English text of
# MediaWiki's messages (messages.py, from languages/i18n/en.json) instead of the message system.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Strip markers: content (nowiki, extension tag output) hidden from the parser's later passes."""
from __future__ import annotations

import re
from typing import Callable, Optional, Union

from .messages import msg

# Parser::MARKER_PREFIX / MARKER_SUFFIX
MARKER_SUFFIX = "-QINU`\"'\x7f"
MARKER_PREFIX = "\x7f'\"`UNIQ-"

Value = Union[str, Callable[[], str]]


class StripState:
    def __init__(self, parser=None, options: Optional[dict] = None):
        options = options or {}
        self.data: dict[str, dict[str, Value]] = {"nowiki": {}, "general": {}}
        self.regex = re.compile(re.escape(MARKER_PREFIX) + "([^\x7f<>&'\"]+)" + re.escape(MARKER_SUFFIX))
        self.circular_ref_guard: dict[str, bool] = {}
        self.parser = parser
        self.depth = 0
        self.highest_depth = 0
        self.expand_size = 0
        self.depth_limit = options.get("depthLimit", 20)
        self.size_limit = options.get("sizeLimit", 5000000)

    def add_no_wiki(self, marker: str, value: Value) -> None:
        """Add a nowiki strip item"""
        self.add_item("nowiki", marker, value)

    def add_general(self, marker: str, value: Value) -> None:
        self.add_item("general", marker, value)

    def add_item(self, type_: str, marker: str, value: Value) -> None:
        m = self.regex.search(marker)
        if not m:
            raise ValueError(f"Invalid marker: {marker}")
        self.data[type_][m.group(1)] = value

    def unstrip_general(self, text: str) -> str:
        return self.unstrip_type("general", text)

    def unstrip_no_wiki(self, text: str) -> str:
        return self.unstrip_type("nowiki", text)

    def replace_no_wikis(self, text: str, callback: Callable[[str], str]) -> str:
        # Shortcut
        if not self.data["nowiki"]:
            return text

        def sub(m: re.Match) -> str:
            marker = m.group(1)
            if marker not in self.data["nowiki"]:
                return m.group(0)
            value = self.data["nowiki"][marker]
            if callable(value):
                value = value()
            self.expand_size += len(value.encode("utf-8"))  # PHP strlen() counts bytes
            if self.expand_size > self.size_limit:
                return self._limitation_warning("unstrip-size", self.size_limit)
            return callback(value)

        return self.regex.sub(sub, text)

    def unstrip_both(self, text: str) -> str:
        text = self.unstrip_type("general", text)
        text = self.unstrip_type("nowiki", text)
        return text

    def unstrip_type(self, type_: str, text: str) -> str:
        # Shortcut
        if not self.data[type_]:
            return text

        def sub(m: re.Match) -> str:
            marker = m.group(1)
            if marker not in self.data[type_]:
                return m.group(0)
            if marker in self.circular_ref_guard:
                return self._warning("parser-unstrip-loop-warning")
            if self.depth > self.highest_depth:
                self.highest_depth = self.depth
            if self.depth >= self.depth_limit:
                return self._limitation_warning("unstrip-depth", self.depth_limit)
            value = self.data[type_][marker]
            if callable(value):
                value = value()
            self.expand_size += len(value.encode("utf-8"))
            if self.expand_size > self.size_limit:
                return self._limitation_warning("unstrip-size", self.size_limit)
            self.circular_ref_guard[marker] = True
            self.depth += 1
            ret = self.unstrip_type(type_, value)
            self.depth -= 1
            del self.circular_ref_guard[marker]
            return ret

        return self.regex.sub(sub, text)

    def _limitation_warning(self, type_: str, max_: Union[int, str] = "") -> str:
        """Get warning HTML and register a limitation warning with the parser"""
        if self.parser is not None and hasattr(self.parser, "limitation_warn"):
            self.parser.limitation_warn(type_, max_)
        return self._warning(f"{type_}-warning", max_)

    @staticmethod
    def _warning(message: str, max_: Union[int, str] = "") -> str:
        """Get warning HTML"""
        number = f"{max_:,}" if isinstance(max_, int) else str(max_)  # numParams() in English: 5,000,000
        return '<span class="error">' + msg(message, number) + "</span>"

    def get_limit_report(self) -> list:
        """Parameters for ParserOutput::setLimitReportData()"""
        return [
            ["limitreport-unstrip-depth", [self.highest_depth, self.depth_limit]],
            ["limitreport-unstrip-size", [self.expand_size, self.size_limit]],
        ]

    def kill_markers(self, text: str) -> str:
        """Remove any strip markers found in the given text."""
        return self.regex.sub("", text)

# The extensions of the MediaWiki parser port, registered by name as MediaWiki's ExtensionRegistry and the
# ParserFirstCallInit hook do (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Written by a3ref contributors on 2026-10-30 after ExtensionRegistry and Parser::firstCallInit() of MediaWiki 1.39.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Parser extensions (ParserFunctions, Cite, SyntaxHighlight) and their registration.

``Parser(extensions={"ParserFunctions", "Cite", "SyntaxHighlight"})`` registers them on its first parse; their settings ($wgPF...,
$wgCite...) are fields of the parser's Config (biwiki.mediawiki.config).
"""
from __future__ import annotations

from typing import Callable, Iterable


def _register_parser_functions(parser) -> None:
    from . import parserfunctions

    parserfunctions.register(parser)


def _register_cite(parser) -> None:
    from . import cite

    cite.register(parser)


def _register_syntax_highlight(parser) -> None:
    from . import syntaxhighlight

    syntaxhighlight.register(parser)


# extension name (as in its extension.json) -> its ParserFirstCallInit handler
EXTENSIONS: dict[str, Callable] = {
    "ParserFunctions": _register_parser_functions,
    "Cite": _register_cite,
    "SyntaxHighlight": _register_syntax_highlight,
}


def register_all(parser, enabled: Iterable[str]) -> None:
    """Run the ParserFirstCallInit hook of each extension in ``enabled``, in the order of EXTENSIONS (as
    wfLoadExtension() calls in LocalSettings.php fix the order of the hook handlers). Unknown names raise
    ValueError, so a misspelt name does not silently leave an extension out."""
    enabled = set(enabled)
    unknown = enabled - set(EXTENSIONS)
    if unknown:
        raise ValueError("unknown parser extensions: " + ", ".join(sorted(unknown)))
    for name, register in EXTENSIONS.items():
        if name in enabled:
            register(parser)

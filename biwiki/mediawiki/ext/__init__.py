# The extensions of the MediaWiki parser port, registered by name as MediaWiki's ExtensionRegistry and the
# ParserFirstCallInit hook do (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Written by a3ref contributors on 2026-10-30 after ExtensionRegistry and Parser::firstCallInit() of MediaWiki 1.39.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Parser extensions (ParserFunctions, Cite, SyntaxHighlight and the BI wiki's own tags) and their registration.

``Parser(extensions={"ParserFunctions", "Cite", "SyntaxHighlight"})`` registers them on its first parse; their settings ($wgPF...,
$wgCite...) are fields of the parser's Config (biwiki.mediawiki.config).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional


def _register_parser_functions(parser, **options) -> None:
    from . import parserfunctions

    parserfunctions.register(parser, **options)


def _register_cite(parser, **options) -> None:
    from . import cite

    cite.register(parser, **options)


def _register_syntax_highlight(parser, **options) -> None:
    from . import syntaxhighlight

    syntaxhighlight.register(parser, **options)


def _register_enforce_highlighter(parser, **options) -> None:
    from . import enforcehighlighter

    enforcehighlighter.register(parser, **options)


def _register_sqf_highlighter(parser, **options) -> None:
    # without the command and function names (options commands=, functions=) no token links to a page;
    # biwiki.mediawiki.biki passes the names of a3ref's mirrored pages
    from . import sqfhighlighter

    sqfhighlighter.register(parser, **options)


def _register_spoiler(parser, **options) -> None:
    from . import spoiler

    spoiler.register(parser, **options)


# extension name (as in its extension.json) -> its ParserFirstCallInit handler
EXTENSIONS: dict[str, Callable] = {
    "ParserFunctions": _register_parser_functions,
    "Cite": _register_cite,
    "SyntaxHighlight": _register_syntax_highlight,
    # Bohemia Interactive's own, written after the wiki's HTML
    "SQFHighlighter": _register_sqf_highlighter,
    "EnforceScriptHighlighter": _register_enforce_highlighter,
    "BIKISpoiler": _register_spoiler,
}


def register_all(parser, enabled: Iterable[str],
                 options: Optional[Mapping[str, Mapping[str, Any]]] = None) -> None:
    """Run the ParserFirstCallInit hook of each extension in ``enabled``, in the order of EXTENSIONS (as
    wfLoadExtension() calls in LocalSettings.php fix the order of the hook handlers). Unknown names raise
    ValueError, so a misspelt name does not silently leave an extension out.

    ``options``: extension name -> keyword arguments of its ``register()`` (the settings that are data rather
    than Config fields, e.g. the SQF Highlighter's ``commands``/``functions``); default: the parser's
    ``extension_options`` attribute if it has one, as the Parser calls this without arguments on its first parse."""
    enabled = set(enabled)
    unknown = enabled - set(EXTENSIONS)
    if unknown:
        raise ValueError("unknown parser extensions: " + ", ".join(sorted(unknown)))
    if options is None:
        options = getattr(parser, "extension_options", None) or {}
    unknown = set(options) - enabled
    if unknown:
        raise ValueError("options for parser extensions that are not enabled: " + ", ".join(sorted(unknown)))
    for name, register in EXTENSIONS.items():
        if name in enabled:
            register(parser, **options.get(name, {}))

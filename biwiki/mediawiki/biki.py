# The MediaWiki parser port set up as the Bohemia Interactive Community wiki runs it (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Written by a3ref contributors on 2026-10-30 after the wiki's settings (Config BIKI, biki_siteinfo.json) and the
# extensions it loads in its LocalSettings.php.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""A Parser configured like the BI Community wiki, and the pages it reads from a3ref's data.

``biki_parser(pages, commands=..., functions=...)`` gives a Parser with the wiki's Config and Site and all its
parser extensions; the SQF Highlighter links the command and function names it is given. ``pages`` is what the
wiki's page table would hold: prefixed titles with spaces ("Template:RV", "BIS fnc spawnGroup") -> wikitext. Both
template transclusion (Parser.fetch_current_revision_text) and link colours (LinkCache) look titles up in it.

``load_pages(templates, raw)`` builds that mapping from a templates file and the data clone's ``raw/`` directory,
``load_names(raw)`` the command and function names.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

from .config import BIKI
from .ext import EXTENSIONS
from .ext.sqfhighlighter import names_from_raw
from .parser import Parser
from .site import biki_site

RAW_FILES = ("commands", "functions", "topics")


def biki_parser(pages: Mapping[str, str], *, commands: Iterable[str] = (), functions: Iterable[str] = (),
                timestamp=None, site=None) -> Parser:
    """A Parser as the BI wiki's: Config BIKI, its namespaces and interwikis, and every extension of
    ext.EXTENSIONS, the SQF Highlighter with ``commands``/``functions`` (names or page titles) as its links.

    ``timestamp``: the time of the parse ({{CURRENTYEAR}} ...; a datetime, Unix timestamp or TS_MW string; None:
    now). ``site``: a Site to reuse (biki_site() reads a JSON file); default: a new biki_site()."""
    parser = Parser(pages, config=BIKI, site=site if site is not None else biki_site(), timestamp=timestamp,
                    extensions=EXTENSIONS)
    # read by ext.register_all() on the first parse
    parser.extension_options = {"SQFHighlighter": {"commands": list(commands), "functions": list(functions)}}
    return parser


def _read_json(path: Union[str, Path]) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_pages(templates: Optional[Union[str, Path]], raw: Optional[Union[str, Path]]) -> dict[str, str]:
    """Title -> wikitext of the templates and of the mirrored pages in ``raw`` ({commands,functions,topics}.json,
    page id -> {title, wikitext, redirects, ...}). The templates file is the data clone's ``raw/templates.json``
    (page id -> {title, wikitext, ...}) or a JSON object "Template:X" -> {wikitext, ...}. The titles a topic's
    ``redirects`` lists become redirect pages to it, as on the wiki, so links to them are blue too. Either source
    may be None."""
    pages: dict[str, str] = {}
    if templates is not None:
        for key, page in _read_json(templates).items():
            pages[page.get("title") or key] = page["wikitext"]
    if raw is not None:
        redirects: dict[str, str] = {}
        for name in RAW_FILES:
            path = Path(raw) / f"{name}.json"
            if not path.exists():
                continue
            for page in _read_json(path).values():
                pages[page["title"]] = page["wikitext"]
                for redirect in page.get("redirects") or ():
                    redirects.setdefault(redirect, page["title"])
        for redirect, target in redirects.items():
            pages.setdefault(redirect, f"#REDIRECT [[{target}]]")
    return pages


def load_names(raw: Union[str, Path]) -> tuple[list[str], list[str]]:
    """The command and function names of the data clone's ``raw`` directory, for biki_parser()."""
    raw = Path(raw)
    return names_from_raw(raw / "commands.json"), names_from_raw(raw / "functions.json")

"""A renderer with the interface of ``wikitext.Renderer`` that renders through the MediaWiki parser port.

``parse.parse_page`` / ``parse_topic`` cut a page into fragments (parameter values, notes, the whole topic page)
and ask a renderer for their Markdown or plain text. ``PortRenderer`` parses each fragment with the port
(``biwiki.mediawiki.biki_parser``, set up as the BI wiki) into the wiki's HTML and converts that with
``htmlmd.HtmlMarkdown``. The build renders every page three times (JSON plain text, Markdown, HTML flavours), so
the HTML of a fragment is cached per (page title, fragment) and parsed once.

Unlike Renderer no ``preprocess()`` / ``close_tables()`` step is needed: the port reads unknown tags, tables
written with ``{{!}}`` and tables left open as MediaWiki does. Fragments are stripped, as MediaWiki trims a named
template parameter before it is used, so the first line of "|p1= name: Type" is no preformatted line.

Original a3ref code (MIT): it only calls the port (GPL, ``biwiki/mediawiki/``) and translates no MediaWiki code.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Mapping, Optional, Union

from .htmlmd import HtmlMarkdown
from .wikitext import LinkResolver

_ISO = re.compile(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)Z?")


def mw_timestamp(iso: Optional[str]) -> Optional[str]:
    """"2022-05-12T09:59:18Z" (the cache's revision time) -> "20220512095918" (MediaWiki's TS_MW)."""
    m = _ISO.fullmatch(iso or "")
    return "".join(m.groups()) if m else None


class PortContext:
    """One shared port Parser for a build, and the HTML of the fragments of the page being rendered.

    ``pages``: title -> wikitext, as ``biki.load_pages`` gives it (templates and mirrored pages);
    ``revisions``: page title -> (revision timestamp as in the cache, revision id), so {{CURRENTYEAR}} and the
    like give the same output on every build."""

    def __init__(self, pages: Mapping[str, str], commands=(), functions=(),
                 revisions: Optional[Mapping[str, tuple[Optional[str], Optional[str]]]] = None):
        from .mediawiki.biki import biki_parser

        self.parser = biki_parser(pages, commands=commands, functions=functions)
        self.revisions = revisions or {}
        self._title: Optional[str] = None
        self._cache: dict[str, str] = {}
        self.parses = 0

    @classmethod
    def load(cls, templates: Union[str, Path], raw_dir: Union[str, Path], raws: Mapping[str, Mapping]) -> PortContext:
        """The context of a build: templates file, the data clone's raw/ directory and its loaded caches."""
        from .mediawiki.biki import load_names, load_pages

        commands, functions = load_names(raw_dir)
        revisions = {p["title"]: (p.get("timestamp"), p.get("revid")) for pages in raws.values() for p in pages.values()}
        return cls(load_pages(templates, raw_dir), commands, functions, revisions)

    def html(self, title: str, wikitext: str) -> str:
        """The port's HTML of ``wikitext`` rendered on page ``title``. Only the current page's fragments are kept:
        the build renders one page's three flavours one after another."""
        if title != self._title:
            self._title, self._cache = title, {}
        html = self._cache.get(wikitext)
        if html is None:
            timestamp, revid = self.revisions.get(title, (None, None))
            # a page without a known revision still renders deterministically
            self.parser.timestamp = mw_timestamp(timestamp) or "20000101000000"
            self.parser.revision_id = int(revid) if revid and str(revid).isdigit() else None
            html = self._cache[wikitext] = self.parser.parse(wikitext, title or "Main Page")
            self.parses += 1
        return html

    def renderer(self, resolve: Optional[LinkResolver] = None, **options) -> PortRenderer:
        return PortRenderer(self, resolve, **options)


class PortRenderer:
    """``wikitext.Renderer``'s interface (md, plain, plain_lines, unknown, page_title) over the port."""

    def __init__(self, ctx: PortContext, resolve: Optional[LinkResolver] = None, page_title: str = "",
                 preformat: bool = True, emphasis: bool = True, inline: bool = False, hard_breaks: bool = True,
                 code_links: bool = False, anchors: bool = False):
        self.ctx = ctx
        self.resolve = resolve
        self.page_title = page_title
        self.options = dict(preformat=preformat, emphasis=emphasis, inline=inline, hard_breaks=hard_breaks,
                            code_links=code_links, anchors=anchors)
        self.unknown: Counter = Counter()

    def _html(self, wikitext) -> str:
        # str, mwparserfromhell Wikicode / Template / Parameter value: their wikitext
        return self.ctx.html(self.page_title, str(wikitext).strip())

    def _converter(self) -> HtmlMarkdown:
        return HtmlMarkdown(self.resolve, self.page_title, **self.options)

    def md(self, wikitext) -> str:
        conv = self._converter()
        out = conv.md(self._html(wikitext))
        self.unknown.update(conv.unknown)
        return out

    def plain_lines(self, wikitext) -> str:
        conv = self._converter()
        out = conv.plain_lines(self._html(wikitext))
        self.unknown.update(conv.unknown)
        return out

    def plain(self, wikitext) -> str:
        return re.sub(r"\s+", " ", self.plain_lines(wikitext)).strip()

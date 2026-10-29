# Ported from MediaWiki 1.39 includes/parser/LinkHolderArray.php (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; page existence comes from the parser's
# LinkCache (the caller's pages) instead of a database query; no language variants (English has none), no hooks.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Link holders: placeholders for internal links, replaced by blue or red links once page existence is known."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from .linker import make_self_link_obj, split_trail
from .linkrenderer import HtmlArmor
from .site import NS_SPECIAL

if TYPE_CHECKING:
    from .title import Title

_LINK_REGEX = re.compile(r"(<!--LINK'\" .*?-->)")
_IWLINK_REGEX = re.compile(r"<!--IWLINK'\" (.*?)-->")
_TEXT_REGEX = re.compile(r"<!--(IW)?LINK'\" (.*?)-->")


class LinkHolderArray:
    """The link holders of a parse. ``parent`` is the Parser (with the LinksMixin): it gives link IDs, the link
    renderer, the link cache and the output."""

    def __init__(self, parent):
        self.internals: dict[int, dict[int, dict]] = {}
        self.interwikis: dict[int, dict] = {}
        self.size = 0
        self.parent = parent

    def merge(self, other: "LinkHolderArray") -> None:
        """Merge another LinkHolderArray into this one"""
        for ns, entries in other.internals.items():
            self.size += len(entries)
            if ns not in self.internals:
                self.internals[ns] = dict(entries)
            else:
                for key, entry in entries.items():  # PHP array union: existing keys win
                    self.internals[ns].setdefault(key, entry)
        for key, entry in other.interwikis.items():
            self.interwikis.setdefault(key, entry)

    def is_big(self) -> bool:
        """Returns true if the memory requirements of this object are getting large"""
        return self.size > self.parent.config.link_holder_batch_size

    def clear(self) -> None:
        """Clear all stored link holders. Make sure you don't have any text left using these link holders, before
        you call this"""
        self.internals = {}
        self.interwikis = {}
        self.size = 0

    def make_holder(self, nt: "Title", text: str = "", trail: str = "", prefix: str = "") -> str:
        """Make a link placeholder. The text returned can be later resolved to a real link with replace_link_holders().
        This is done for two reasons: firstly to avoid further parsing of interwiki links, and secondly to allow all
        existence checks and article length checks (for stub links) to be bundled into a single query."""
        # Separate the link trail from the rest of the link
        inside, trail = split_trail(trail)

        key = self.parent.next_link_id()
        entry = {
            "title": nt,
            "text": prefix + text + inside,
            "pdbk": nt.prefixed_db_key,
        }

        self.size += 1
        if nt.is_external():
            # Use a globally unique ID to keep the objects mergable
            self.interwikis[key] = entry
            return f"<!--IWLINK'\" {key}-->{trail}"
        ns = nt.namespace
        self.internals.setdefault(ns, {})[key] = entry
        return f"<!--LINK'\" {ns}:{key}-->{trail}"

    def replace(self, text: str) -> str:
        """Replace link placeholders with actual links, in the buffer; returns the new text."""
        text = self.replace_internal(text)
        text = self.replace_interwiki(text)
        return text

    def replace_internal(self, text: str) -> str:
        """Replace internal links"""
        if not self.internals:
            return text

        classes: dict[str, str] = {}
        link_cache = self.parent.get_link_cache()
        link_renderer = self.parent.get_link_renderer()

        # Sort by namespace
        self.internals = dict(sorted(self.internals.items()))

        for ns, entries in self.internals.items():
            for entry in entries.values():
                title, pdbk = entry["title"], entry["pdbk"]
                # Skip invalid entries. Result will be ugly, but prevents crash.
                if title is None:
                    continue
                # Check if it's a static known link, e.g. interwiki
                if link_cache.is_always_known(title):
                    classes[pdbk] = ""
                elif ns == NS_SPECIAL:
                    classes[pdbk] = "new"
                elif link_cache.exists(title):
                    classes[pdbk] = link_renderer.get_link_classes(title)
                    self.parent.output_add_link(title, 1)
                else:
                    classes[pdbk] = "new"

        # Construct search and replace arrays
        replace_pairs: dict[str, str] = {}
        for ns, entries in self.internals.items():
            for index, entry in entries.items():
                pdbk = entry["pdbk"]
                title = entry["title"]
                query = entry.get("query", {})
                searchkey = f"<!--LINK'\" {ns}:{index}-->"
                display_text_html = entry["text"]
                if entry.get("selflink"):
                    replace_pairs[searchkey] = make_self_link_obj(title, display_text_html, query)
                    continue
                display_text: Optional[HtmlArmor] = None if display_text_html == "" else HtmlArmor(display_text_html)
                classes.setdefault(pdbk, "new")
                if classes[pdbk] == "new":
                    self.parent.output_add_link(title, 0)
                    link = link_renderer.make_broken_link(title, display_text, {}, query)
                else:
                    link = link_renderer.make_preloaded_link(title, display_text, classes[pdbk], {}, query)
                replace_pairs[searchkey] = link

        # Do the thing
        return _LINK_REGEX.sub(lambda m: replace_pairs.get(m.group(1), ""), text)

    def replace_interwiki(self, text: str) -> str:
        """Replace interwiki links"""
        if not self.interwikis:
            return text
        # Make interwiki link HTML
        replace_pairs: dict[str, str] = {}
        link_renderer = self.parent.get_link_renderer()
        for key, link in self.interwikis.items():
            replace_pairs[str(key)] = link_renderer.make_link(link["title"], HtmlArmor(link["text"]))
            self.parent.output_add_interwiki_link(link["title"])
        return _IWLINK_REGEX.sub(lambda m: replace_pairs.get(m.group(1), ""), text)

    def replace_text(self, text: str) -> str:
        """Replace link placeholders with plain text of links (not HTML-formatted)."""

        def callback(m: re.Match) -> str:
            unchanged, is_interwiki, key = m.group(0), m.group(1), m.group(2)
            if not is_interwiki:
                ns, _, index = key.partition(":")
                try:
                    return self.internals[int(ns)][int(index)]["text"]
                except (KeyError, ValueError):
                    return unchanged
            try:
                return self.interwikis[int(key)]["text"]
            except (KeyError, ValueError):
                return unchanged

        return _TEXT_REGEX.sub(callback, text)

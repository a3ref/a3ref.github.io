# Ported from MediaWiki 1.39 includes/parser/Parser.php (https://www.mediawiki.org/), (C) MediaWiki contributors:
# Parser::parse(), internalParse(), internalParseHalfParsed(), handleDoubleUnderscore(), handleHeadings().
# Changed by a3ref contributors on 2026-10-30: translated to Python, the stages ported so far; pages and templates
# come from the ``pages`` mapping instead of a database; ParserOutput keeps only what the stages record.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Wikitext -> HTML, as MediaWiki's legacy parser does.

Ported so far: the strip state, Sanitizer (see sanitizer.py), handleTables, horizontal rules, handleDoubleUnderscore,
handleHeadings, handleAllQuotes, doBlockLevels. Still to come, in Parser.php's order: the preprocessor (templates,
arguments, parser functions, extension tags, comments), internal and external links, magic links, the table of
contents (finalizeHeadings/formatHeadings), link holders, and tidy (RemexHtml).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .blocklevel import do_block_levels
from .config import DEFAULT, Config
from .linker import make_external_image, make_external_link, matches_domain_list, split_trail, valid_absolute_protocols, valid_protocols
from .messages import msg
from .magicword import FACTORY, MagicWordFactory
from .quotes import handle_all_quotes
from .stripstate import MARKER_PREFIX, MARKER_SUFFIX, StripState

TOC_PLACEHOLDER = "<mw:tocplace></mw:tocplace>"

# \p{Zs} of PCRE (Python's re has no Unicode properties): the space separators of Unicode
ZS = "    -   　"
# Constants needed for external link processing. Everything except bracket, space, or control characters.
# \p{Zs} is unicode 'separator, space' category. It covers the space 0x20 as well as U+3000 is IDEOGRAPHIC SPACE
# for T21052. \x{FFFD} is the Unicode replacement character, which the HTML5 spec says should not be allowed in
# hyperlinks.
EXT_LINK_URL_CLASS = rf'[^\]\[<>"\x00-\x20\x7F{ZS}�]'
# Simplified expression to match an IPv4 or IPv6 address, or at least one character of a host name (embeds
# EXT_LINK_URL_CLASS)
EXT_LINK_ADDR = rf'(?:[0-9.]+|\[(?i:[0-9a-f:.]+)\]|[^\]\[<>"\x00-\x20\x7F{ZS}�])'
# RegExp to make image URLs (embeds IPv6 part of EXT_LINK_ADDR)
EXT_IMAGE_REGEX = re.compile(
    rf'^(http://|https://)((?:\[(?i:[0-9a-f:.]+)\])?[^\]\[<>"\x00-\x20\x7F{ZS}�]+)'
    r"/([A-Za-z0-9_.,~%\-+&;#*?!=()@\x80-\xFF]+)\.(?i:gif|png|jpg|jpeg)$")
# Regular expression for a non-newline space
SPACE_NOT_NL = rf"(?:\t|&nbsp;|&\#0*160;|&\#[Xx]0*[Aa]0;|[{ZS}])"


@dataclass
class ParserOutput:
    """What a parse records besides its HTML (the part of MediaWiki's ParserOutput the ported stages fill)."""
    page_properties: dict[str, str] = field(default_factory=dict)
    tracking_categories: list[str] = field(default_factory=list)  # message keys of MediaWiki's tracking categories
    index_policy: str = ""
    no_gallery: bool = False
    warnings: list[tuple] = field(default_factory=list)  # (message key, params...) of ParserOutput::addWarningMsg()
    templates: list[str] = field(default_factory=list)  # titles of the transcluded pages, in order of first use
    categories: dict[str, str] = field(default_factory=dict)  # category name -> sort key
    indicators: dict[str, str] = field(default_factory=dict)
    display_title: str = ""

    def add_warning_msg(self, key: str, *params) -> None:
        self.warnings.append((key, *params))

    def add_tracking_category(self, key: str) -> None:
        if key not in self.tracking_categories:
            self.tracking_categories.append(key)

    def add_template(self, title: str) -> None:
        if title not in self.templates:
            self.templates.append(title)


class Parser:
    def __init__(self, pages: Optional[Mapping[str, str]] = None, config: Config = DEFAULT, site=None,
                 magic_words: MagicWordFactory = FACTORY):
        from .site import Site

        self.pages = pages or {}
        self.config = config
        self.site = site if site is not None else Site(config)
        self.magic_words = magic_words
        self.title = ""
        self.strip_state = StripState(self)
        self.output = ParserOutput()
        self.double_underscores: dict[str, object] = {}
        self.show_toc = True
        self.force_toc_position = False
        self.autonumber = 0
        self.ext_link_bracketed_regex = re.compile(
            r"\[(((?i:" + valid_protocols(config) + "))" + EXT_LINK_ADDR + EXT_LINK_URL_CLASS + "*)"
            + f"[{ZS}]*" + r"([^\]\x00-\x08\x0a-\x1F�]*?)\]")

    # ---- entry point ------------------------------------------------------------------------------------------

    def parse(self, text: str, title: str = "Main Page") -> str:
        """The HTML of ``text`` rendered on the page ``title``."""
        self.title = title
        self.strip_state = StripState(self)
        self.output = ParserOutput()
        self.double_underscores = {}
        self.show_toc, self.force_toc_position = True, False
        self.autonumber = 0
        text = self.internal_parse(text)
        return self.internal_parse_half_parsed(text, True, True)

    def internal_parse(self, text: str, is_main: bool = True) -> str:
        """Transforms wiki markup into half-parsed HTML."""
        from .sanitizer import internal_remove_html_tags
        from .tables import handle_tables

        # TODO: the preprocessor (replaceVariables / frame expansion) comes first
        text = internal_remove_html_tags(text, config=self.config)
        # Tables need to come after variable replacement for things to work properly; putting them before other
        # transformations should keep exciting things like link expansions from showing up in surprising places.
        text = handle_tables(text, self.strip_state)
        text = re.sub(r"(^|\n)-----*", r"\1<hr />", text)
        text = self.handle_double_underscore(text)
        text = self.handle_headings(text)
        # TODO: handleInternalLinks
        text = handle_all_quotes(text)
        text = self.handle_external_links(text)
        # handleInternalLinks may sometimes leave behind absolute URLs, which have to be masked to hide them from
        # handleExternalLinks
        text = text.replace(MARKER_PREFIX + "NOPARSE", "")
        text = self.handle_magic_links(text)
        # TODO: finalizeHeadings
        return text

    def internal_parse_half_parsed(self, text: str, is_main: bool = True, linestart: bool = True) -> str:
        text = self.strip_state.unstrip_general(text)
        text = do_block_levels(text, linestart)
        # TODO: replaceLinkHoldersPrivate; the language converter is a no-op for English
        text = self.strip_state.unstrip_no_wiki(text)
        text = self.strip_state.unstrip_general(text)
        # TODO: tidy (RemexHtml) with Sanitizer::armorFrenchSpaces
        return text

    # ---- stages -----------------------------------------------------------------------------------------------

    def handle_double_underscore(self, text: str) -> str:
        """Fills the double-underscore magic words (__NOTOC__ ...) found in the text, and removes them."""
        # The position of __TOC__ needs to be recorded
        mw = self.magic_words.get("toc")
        toc_alias = None
        if mw.match(text):
            self.show_toc = True
            self.force_toc_position = True
            # record the alias used
            toc_alias = mw.regex.search(text).group(0)
            # Set a placeholder. At the end we'll fill it in with the TOC.
            text = mw.replace(TOC_PLACEHOLDER, text, 1)
            # Only keep the first one.
            text = mw.replace("", text)

        # Now match and remove the rest of them
        mwa = self.magic_words.get_double_underscore_array()
        self.double_underscores, text = mwa.match_and_remove(text, True)
        if toc_alias:
            # For consistency with all other double-underscores (see below)
            self.double_underscores["toc"] = toc_alias

        if "nogallery" in self.double_underscores:
            self.output.no_gallery = True
        if "notoc" in self.double_underscores and not self.force_toc_position:
            self.show_toc = False
        if "hiddencat" in self.double_underscores and self.title.startswith("Category:"):
            self.output.tracking_categories.append("hidden-category-category")
        # (T10068) Allow control over whether robots index a page. __INDEX__ always overrides __NOINDEX__, see T16899
        if "noindex" in self.double_underscores:
            self.output.index_policy = "noindex"
            self.output.tracking_categories.append("noindex-category")
        if "index" in self.double_underscores:
            self.output.index_policy = "index"
            self.output.tracking_categories.append("index-category")

        for key, alias in self.double_underscores.items():
            # Cache all double underscores in the database
            self.output.page_properties[key] = ""
            # Check for deprecated local aliases (T407289)
            ascii_ = isinstance(alias, str) and alias.startswith("__") and alias.endswith("__")
            wide = isinstance(alias, str) and alias.startswith("＿＿") and alias.endswith("＿＿")
            if not (ascii_ or wide):
                self.output.tracking_categories.append("bad-double-underscore-category")
        return text

    @staticmethod
    def handle_headings(text: str) -> str:
        """Parse headers and return html"""
        for i in range(6, 0, -1):
            h = "=" * i
            # Trim non-newline whitespace from headings. Using \s* will break for: "==\n===\n" and parse as <h2>=</h2>
            text = re.sub(rf"(?m)^(?:{h})[ \t]*(.+?)[ \t]*(?:{h})\s*$", rf"<h{i}>\1</h{i}>", text)
        return text

    # ---- external links ---------------------------------------------------------------------------------------

    def handle_external_links(self, text: str) -> str:
        """Replace external links (REL)"""
        from .sanitizer import clean_url

        bits = self.ext_link_bracketed_regex.split(text)
        s = [bits[0]]
        i = 1
        while i < len(bits):
            url = bits[i]
            # bits[i + 1]: protocol
            text = bits[i + 2] or ""
            trail = bits[i + 3]
            i += 4

            # The characters '<' and '>' (which were escaped by internalRemoveHtmlTags()) should not be included in
            # URLs, per RFC 2396.
            m2 = re.search(r"&(lt|gt);", url)
            if m2:
                text = url[m2.start():] + " " + text
                url = url[:m2.start()]

            # If the link text is an image URL, replace it with an <img> tag. This happened by accident in the
            # original parser, but some people used it extensively
            img = self.maybe_make_external_image(text)
            if img is not False:
                text = img

            dtrail = ""
            # Set linktype for CSS
            linktype = "text"

            # No link text, e.g. [http://domain.tld/some.link]
            if text == "":
                # Autonumber
                self.autonumber += 1
                text = f"[{self.autonumber:,}]"
                linktype = "autonumber"
            else:
                # Have link text, e.g. [http://domain.tld/some.link text]s. Check for trail
                dtrail, trail = split_trail(trail)

            # Excluding protocol-relative URLs may avoid many false positives. (markNoConversion: a no-op for
            # English)
            url = clean_url(url)

            # Use the encoded URL. This means that users can paste URLs directly into the text. Funny characters
            # like ö aren't valid in URLs anyway. This was changed in August 2004
            s.append(make_external_link(url, text, False, linktype, self.get_external_link_attribs(url),
                                        rel=self.get_external_link_rel(url)) + dtrail + trail)
        return "".join(s)

    def get_external_link_rel(self, url: str = "") -> Optional[str]:
        """Get the rel attribute for a particular external link: nofollow if appropriate"""
        ns = self.title_namespace()
        if (self.config.no_follow_links and ns not in self.config.no_follow_ns_exceptions
                and not matches_domain_list(url, self.config.no_follow_domain_exceptions, self.config)):
            return "nofollow"
        return None

    def get_external_link_attribs(self, url: str) -> dict:
        """Get an associative array of additional HTML attributes appropriate for a particular external link.
        This currently may include rel => nofollow (depending on configuration, namespace, and the URL's domain)
        and/or a target attribute (depending on configuration)."""
        attribs = {}
        rel = self.get_external_link_rel(url) or ""
        target = self.config.external_link_target
        if target:
            attribs["target"] = target
            if target not in ("_self", "_parent", "_top"):
                # T133507. New windows can navigate parent cross-origin. Including noreferrer due to lacking browser
                # support of noopener. Eventually noreferrer should be removed.
                if rel != "":
                    rel += " "
                rel += "noreferrer noopener"
        if rel != "":
            attribs["rel"] = rel
        return attribs

    def maybe_make_external_image(self, url: str):
        """make an image if it's allowed, either through the global option, through the exception, or through
        the on-wiki whitelist"""
        imagesfrom = self.config.allow_external_images_from
        imagesexception = bool(imagesfrom)
        text = False
        # imagesfrom could be either a single string or an array of strings, parse out the latter
        if imagesexception and isinstance(imagesfrom, (list, tuple)):
            imagematch = any(url.startswith(match) for match in imagesfrom)
        elif imagesexception:
            imagematch = url.startswith(imagesfrom)
        else:
            imagematch = False

        if self.config.allow_external_images or (imagesexception and imagematch):
            if EXT_IMAGE_REGEX.search(url):
                # Image found
                text = make_external_image(url)
        # The on-wiki whitelist (MediaWiki:External image whitelist) is empty by default: every line of the
        # default message is a comment
        return text

    def title_namespace(self) -> int:
        """The namespace of the page being parsed (TODO: from Title once ported)."""
        return 0

    # ---- magic links ------------------------------------------------------------------------------------------

    def handle_magic_links(self, text: str) -> str:
        """Replace special strings like "ISBN xxx" and "RFC xxx" with magic external links."""
        prots = valid_absolute_protocols(self.config)
        url_char = EXT_LINK_URL_CLASS
        addr = EXT_LINK_ADDR
        space = SPACE_NOT_NL  # non-newline space
        spdash = f"(?:-|{space})"  # a dash or a non-newline space
        spaces = f"{space}++"  # possessive match of 1 or more spaces
        regex = re.compile(
            rf"""(?:                        # Start cases
                (<a[ \t\r\n>].*?</a>) |    # m[1]: Skip link text
                (<.*?>) |                  # m[2]: Skip stuff inside HTML elements
                (\b                        # m[3]: Free external links
                    (?i:{prots})
                    ({addr}{url_char}*)    # m[4]: Post-protocol path
                ) |
                \b(?:RFC|PMID){spaces}     # m[5]: RFC or PMID, capture number
                    ([0-9]+)\b |
                \bISBN{spaces}(            # m[6]: ISBN, capture number
                    (?:97[89]{spdash}?)?   #  optional 13-digit ISBN prefix
                    (?:[0-9]{spdash}?){{9}} #  9 digits with opt. delimiters
                    [0-9Xx]                #  check digit
                )\b
            )""",
            re.X | re.A,  # PCRE's /u leaves \b ASCII-only (no UCP), as re.ASCII does
        )
        return regex.sub(self.magic_link_callback, text)

    def magic_link_callback(self, m: re.Match) -> str:
        if m.group(1):
            return m.group(0)  # Skip anchor
        if m.group(2):
            return m.group(0)  # Skip HTML element
        if m.group(3):
            # Free external link; PHP strlen() counts bytes
            return self.make_free_external_link(m.group(0), len(m.group(4).encode("utf-8")))
        if m.group(5):
            # RFC or PMID
            if m.group(0).startswith("RFC"):
                if not self.config.enable_magic_links.get("RFC"):
                    return m.group(0)
                keyword, urlmsg, css_class, tracking_cat = "RFC", "rfcurl", "mw-magiclink-rfc", "magiclink-tracking-rfc"
            elif m.group(0).startswith("PMID"):
                if not self.config.enable_magic_links.get("PMID"):
                    return m.group(0)
                keyword, urlmsg, css_class = "PMID", "pubmedurl", "mw-magiclink-pmid"
                tracking_cat = "magiclink-tracking-pmid"
            else:
                # Should never happen
                raise ValueError(f'magic_link_callback: unrecognised match type "{m.group(0)[:20]}"')
            id_ = m.group(5)
            url = msg(urlmsg, id_)
            self.output.tracking_categories.append(tracking_cat)
            return make_external_link(url, f"{keyword} {id_}", True, css_class, {}, rel=self.get_external_link_rel(url))
        if m.group(6) and self.config.enable_magic_links.get("ISBN"):
            # ISBN
            isbn = re.sub(SPACE_NOT_NL, " ", m.group(6))
            num = isbn.replace("-", "").replace(" ", "").replace("x", "X")
            self.output.tracking_categories.append("magiclink-tracking-isbn")
            return self.make_known_link_to_special("Booksources", num, f"ISBN {isbn}",
                                                   {"class": "internal mw-magiclink-isbn", "title": False})
        return m.group(0)

    def make_known_link_to_special(self, special: str, subpage: str, text: str, attribs: dict) -> str:
        """LinkRenderer::makeKnownLink( SpecialPage::getTitleFor( special, subpage ), text, attribs ) (TODO: Title
        and LinkRenderer once ported; until then the article path with the canonical name)"""
        from .html import element

        href = self.config.article_path.replace("$1", f"Special:BookSources/{subpage}")
        return element("a", {"href": href, **{k: v for k, v in attribs.items() if k != "href"}}, text)

    def make_free_external_link(self, url: str, num_post_proto: int) -> str:
        """Make a free external link, given a user-supplied URL. ``num_post_proto``: the number of characters
        after the protocol."""
        from .sanitizer import clean_url

        trail = ""
        # The characters '<' and '>' (which were escaped by internalRemoveHtmlTags()) should not be included in
        # URLs, per RFC 2396. Make &nbsp; terminate a URL as well (bug T84937)
        m2 = re.search(r"&(lt|gt|nbsp|#x0*(3[CcEe]|[Aa]0)|#0*(60|62|160));", url)
        if m2:
            trail = url[m2.start():] + trail
            url = url[:m2.start()]

        # Move trailing punctuation to trail
        sep = ",;.:!?"
        # If there is no left bracket, then consider right brackets fair game too
        if "(" not in url:
            sep += ")"

        url_rev = url[::-1]
        num_sep_chars = len(url_rev) - len(url_rev.lstrip(sep))
        # Don't break a trailing HTML entity by moving the ; into trail
        if num_sep_chars and url[-num_sep_chars] == ";":
            # un-reversed regexp is: /&([a-z]+|#x[\da-f]+|#\d+)$/i
            if re.compile(r"([a-z]+|[\da-f]+x#|\d+#)&", re.I).match(url_rev, num_sep_chars):
                num_sep_chars -= 1
        if num_sep_chars:
            trail = url[-num_sep_chars:] + trail
            url = url[:-num_sep_chars]

        # Verify that we still have a real URL after trail removal, and not just lone protocol
        if len(trail.encode("utf-8")) >= num_post_proto:
            return url + trail

        url = clean_url(url)

        # Is this an external image?
        text = self.maybe_make_external_image(url)
        if text is False:
            # Not an image, make a link (markNoConversion: a no-op for English)
            text = make_external_link(url, url, True, "free", self.get_external_link_attribs(url),
                                      rel=self.get_external_link_rel(url))
        return text + trail


def parse(text: str, title: str = "Main Page", pages: Optional[Mapping[str, str]] = None,
          config: Config = DEFAULT, site=None) -> str:
    """The HTML MediaWiki renders for ``text`` on the page ``title``; ``pages`` holds the wikitext of the other
    pages (templates, pages that links may point to), by title; ``config`` the wiki's settings and ``site`` its
    namespaces and interwikis (biwiki.mediawiki.site)."""
    return Parser(pages, config, site).parse(text, title)


__all__ = ["Parser", "ParserOutput", "parse", "TOC_PLACEHOLDER", "MARKER_PREFIX", "MARKER_SUFFIX"]

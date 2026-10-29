# Ported from MediaWiki 1.39 includes/Linker.php (https://www.mediawiki.org/), (C) MediaWiki contributors:
# Linker::makeExternalLink(), makeExternalImage(), fnamePart(), splitTrail(); and from includes/utils/UrlUtils.php:
# validProtocols(), validAbsoluteProtocols(), matchesDomainList().
# Changed by a3ref contributors on 2026-10-30: translated to Python; no hooks; the content language is English
# (its link trail is MessagesEn's $linkTrail); UrlUtils::parse() uses Python's urllib instead of PHP's parse_url().
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Links and images in page content."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

from .config import Config
from .html import element, htmlspecialchars, raw_element

# MessagesEn.php $linkTrail
LINK_TRAIL = re.compile(r"^([a-z]+)(.*)$", re.S)


def valid_protocols(config: Config) -> str:
    """Returns a regular expression of URL protocols: those of $wgUrlProtocols."""
    return "|".join(re.escape(p) for p in config.url_protocols)


def valid_absolute_protocols(config: Config) -> str:
    """Like valid_protocols(), but excludes '//' from the protocol list."""
    return "|".join(re.escape(p) for p in config.url_protocols if p != "//")


def matches_domain_list(url: str, domains, config: Config) -> bool:
    """Check whether a given URL has a domain that occurs in a given set of domains"""
    host = _url_host(url, config)
    if host is None:
        return False
    host = "." + host
    return any(host.endswith("." + domain) for domain in domains)


def _url_host(url: str, config: Config) -> Optional[str]:
    """The host of UrlUtils::parse(): None for a URL it cannot parse or whose protocol is not allowed."""
    if url.startswith("//"):
        url = "http:" + url
    try:
        bits = urlsplit(url)
    except ValueError:
        return None
    scheme = bits.scheme.lower()
    if not scheme:
        return None
    if scheme + "://" in config.url_protocols:
        return bits.hostname or ""
    if scheme + ":" in config.url_protocols:
        return bits.path  # mailto: and news: have their "host" as path in parse_url()
    return None


def split_trail(trail: str) -> tuple[str, str]:
    """Split a link trail, return the "inside" portion and the remainder of the trail as a two-element array"""
    inside = ""
    if trail != "":
        m = LINK_TRAIL.match(trail)
        if m:
            inside, trail = m.group(1), m.group(2)
    return inside, trail


def fname_part(url: str) -> str:
    """Returns the filename part of an url. Used as alternative text for external images."""
    i = url.rfind("/")
    return url if i == -1 else url[i + 1:]


def make_external_image(url: str, alt: str = "") -> str:
    """Return the code for images which were added via external links, via Parser::maybeMakeExternalImage()."""
    if alt == "":
        alt = fname_part(url)
    return element("img", {"src": url, "alt": alt})


def make_external_link(url: str, text: str, escape: bool = True, linktype: str = "", attribs: Optional[dict] = None,
                       rel: Optional[str] = None) -> str:
    """Make an external link. ``rel`` is what Parser::getExternalLinkRel() gives for the URL and page."""
    attribs = dict(attribs or {})
    class_ = "external"
    if linktype:
        class_ += f" {linktype}"
    if attribs.get("class"):
        class_ += f" {attribs['class']}"
    attribs["class"] = class_

    if escape:
        text = htmlspecialchars(text, quotes=False)

    new_rel = rel
    if not attribs.get("rel"):
        attribs["rel"] = new_rel
    elif new_rel is not None:
        # Merge the rel attributes.
        attribs["rel"] = " ".join(dict.fromkeys(new_rel.split(" ") + attribs["rel"].split(" ")))
    attribs["href"] = url
    return raw_element("a", attribs, text)

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


# ---- internal links (Linker::makeSelfLinkObj(), makeMediaLinkFile(), getUploadUrl(), normalizeSubpageLink(),
# normaliseSpecialPage()); ported on 2026-10-30 with the internal links of Parser.php -----------------------------

def make_self_link_obj(nt, html: str = "", query="", trail: str = "", prefix: str = "") -> str:
    """Make appropriate markup for a link to the current article. This is since MediaWiki 1.29.0 rendered as an
    <a> tag without an href and with a class showing the link text, as it's a link to the current page. ``nt`` is a
    Title."""
    if html == "":
        html = htmlspecialchars(nt.prefixed_text)
    inside, trail = split_trail(trail)
    return f'<a class="mw-selflink selflink">{prefix}{html}{inside}</a>{trail}'


def get_upload_url(dest_file, query: str = "") -> str:
    """Get the URL to upload a certain file ($wgUploadMissingFileUrl and $wgUploadNavigationUrl are not set)."""
    from .site import NS_SPECIAL
    from .title import Title

    q = "wpDestFile=" + dest_file.partial_url
    if query != "":
        q += "&" + query
    upload = Title.make_title(NS_SPECIAL, "Upload", site=dest_file.site)
    return upload.get_local_url(q)


def make_media_link_file(title, file, html: str = "") -> str:
    """Create a direct link to a given uploaded file. ``title`` is the Title of the file, ``file`` the file object
    (None while files are not ported: the link goes to the upload form)."""
    if file and file.exists():
        url = file.get_url()
        class_ = "internal"
    else:
        url = get_upload_url(title)
        class_ = "new"
    alt = title.text
    if html == "":
        html = alt
    return raw_element("a", {"href": url, "class": class_, "title": alt}, html)


def normalize_subpage_link(context_title, target: str, text: str) -> tuple[str, str]:
    """Return (the link target, the link text) for a subpage link form relative to ``context_title`` (a Title):
    MediaWiki changes its text argument by reference.

    Valid link forms:
    Foobar -- normal
    :Foobar -- override special treatment of prefix (images, language links)
    /Foobar -- convert to CurrentPage/Foobar
    /Foobar/ -- convert to CurrentPage/Foobar, strip the initial and final / from text
    ../ -- convert to CurrentPage, from CurrentPage/CurrentSubPage
    ../Foobar -- convert to CurrentPage/Foobar, (from CurrentPage/CurrentSubPage)
    ../Foobar/ -- convert to CurrentPage/Foobar, use 'Foobar' as text (from CurrentPage/CurrentSubPage)"""
    ret = target  # default return value is no change

    # Some namespaces don't allow subpages, so only perform processing if subpages are allowed
    if context_title is not None and context_title.site.has_subpages(context_title.namespace):
        hash_pos = target.find("#")
        if hash_pos != -1:
            suffix = target[hash_pos:]
            target = target[:hash_pos]
        else:
            suffix = ""
        # T9425
        target = target.strip(" \t\n\r\0\x0b")
        context_prefixed_text = context_title.prefixed_text
        # Look at the first character
        if target != "" and target[0] == "/":
            # / at end means we don't want the slash to be shown
            m = re.search(r"(/+)$", target)
            if m:
                noslash = target = target[1:-len(m.group(1))]
            else:
                noslash = target[1:]
            ret = context_prefixed_text + "/" + noslash.strip(" \t\n\r\0\x0b") + suffix
            if text == "":
                text = target + suffix
            # this might be changed for ugliness reasons
        else:
            # check for .. subpage backlinks
            dotdotcount = 0
            nodotdot = target
            while nodotdot.startswith("../"):
                dotdotcount += 1
                nodotdot = nodotdot[3:]
            if dotdotcount > 0:
                exploded = context_prefixed_text.split("/")
                if len(exploded) > dotdotcount:  # not allowed to go below top level page
                    ret = "/".join(exploded[:-dotdotcount])
                    # / at the end means don't show full path
                    if nodotdot[-1:] == "/":
                        nodotdot = nodotdot.rstrip("/")
                        if text == "":
                            text = nodotdot + suffix
                    nodotdot = nodotdot.strip(" \t\n\r\0\x0b")
                    if nodotdot != "":
                        ret += "/" + nodotdot
                    ret += suffix
    return ret, text


def normalise_special_page(target, link_renderer):
    """Linker::normaliseSpecialPage() (deprecated in MediaWiki): LinkRenderer::normalizeTarget()."""
    return link_renderer.normalize_target(target)


# ---- table of contents and headlines (Linker::tocIndent() ... makeHeadline()) -------------------------------------


def toc_indent() -> str:
    """Add another level to the Table of Contents"""
    return "\n<ul>\n"


def toc_unindent(level: int) -> str:
    """Finish one or more sublevels on the Table of Contents"""
    return "</li>\n" + "</ul>\n</li>\n" * (level if level > 0 else 0)


def toc_line(anchor: str, tocline: str, tocnumber: str, level: int, section_index=False) -> str:
    """parameter level defines if we are on an indentation level"""
    classes = f"toclevel-{level}"
    if section_index is not False:
        classes += f" tocsection-{section_index}"

    # <li class="$classes"><a href="#$anchor"><span class="tocnumber">
    # $tocnumber</span> <span class="toctext">$tocline</span></a>
    from .html import open_element

    return (open_element("li", {"class": classes})
            + raw_element("a", {"href": f"#{anchor}"},
                          element("span", {"class": "tocnumber"}, tocnumber)
                          + " "
                          + raw_element("span", {"class": "toctext"}, tocline)))


def toc_line_end() -> str:
    """End a Table Of Contents line. toc_unindent() will be used instead if we're ending a line below the new
    level."""
    return "</li>\n"


def toc_list(toc: str, lang_code: str = "en", lang_dir: str = "ltr") -> str:
    """Wraps the TOC in a div with ARIA navigation role and provides the hide/collapse JavaScript. The language
    (for the toc title) is English."""
    from .html import open_element
    from .messages import msg

    title = htmlspecialchars(msg("toc"))  # ->escaped()

    return ('<div id="toc" class="toc" role="navigation" aria-labelledby="mw-toc-heading">'
            + element("input", {
                "type": "checkbox",
                "role": "button",
                "id": "toctogglecheckbox",
                "class": "toctogglecheckbox",
                "style": "display:none",
            })
            + open_element("div", {
                "class": "toctitle",
                "lang": lang_code,
                "dir": lang_dir,
            })
            + '<h2 id="mw-toc-heading">' + title + "</h2>"
            + '<span class="toctogglespan">'
            # Html::label( '', 'toctogglecheckbox', [ 'class' => 'toctogglelabel' ] )
            + element("label", {"class": "toctogglelabel", "for": "toctogglecheckbox"}, "")
            + "</span>"
            + "</div>"
            + toc
            + "</ul>\n</div>\n")


def generate_toc(tree: list[dict], lang_code: str = "en", lang_dir: str = "ltr") -> str:
    """Generate a table of contents from a section tree (the sections of ParserOutput)."""
    toc = ""
    last_level = 0
    for section in tree:
        if section["toclevel"] > last_level:
            toc += toc_indent()
        elif section["toclevel"] < last_level:
            toc += toc_unindent(last_level - section["toclevel"])
        else:
            toc += toc_line_end()

        toc += toc_line(section["anchor"], section["line"], section["number"], section["toclevel"],
                        section["index"])
        last_level = section["toclevel"]
    toc += toc_line_end()
    return toc_list(toc, lang_code, lang_dir)


def make_headline(level: int, attribs: str, anchor: str, html: str, link: str, fallback_anchor=False) -> str:
    """Create a headline for content. ``attribs``: any attributes for the headline, starting with a space and ending
    with '>'; this *must* be at least '>' for no attribs. ``anchor``: the anchor to give the headline (the bit after
    the #); ``html``: HTML for the text of the header; ``link``: HTML to add for the section edit link;
    ``fallback_anchor``: a second, optional anchor to give for backward compatibility (False to omit)."""
    anchor_escaped = htmlspecialchars(anchor, False)
    fallback = ""
    if fallback_anchor is not False and fallback_anchor is not None and fallback_anchor != anchor:
        fallback_anchor = htmlspecialchars(fallback_anchor, False)
        fallback = f'<span id="{fallback_anchor}"></span>'
    return (f"<h{level}{attribs}"
            f'{fallback}<span class="mw-headline" id="{anchor_escaped}">{html}</span>'
            f"{link}"
            f"</h{level}>")

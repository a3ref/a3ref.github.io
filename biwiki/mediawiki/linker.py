# Ported from MediaWiki 1.39 includes/Linker.php (https://www.mediawiki.org/), (C) MediaWiki contributors:
# Linker::makeExternalLink(), makeExternalImage(), fnamePart(), splitTrail(), makeSelfLinkObj(), getUploadUrl(),
# makeMediaLinkFile(), normalizeSubpageLink(), normaliseSpecialPage(), tocIndent(), tocUnindent(), tocLine(),
# tocLineEnd(), tocList(), generateTOC(), makeHeadline(), link(), makeImageLink(), getImageLinkMTOParams(),
# makeThumbLinkObj(), makeThumbLink2(), processResponsiveImages(), makeBrokenImageLinkObj(), makeMediaLinkObj();
# and from includes/utils/UrlUtils.php: validProtocols(),
# validAbsoluteProtocols(), matchesDomainList().
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
    if isinstance(domains, str):  # wfMatchesDomainList(): (array)$domains
        domains = (domains,)
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


# ---- images (Linker::makeImageLink(), getImageLinkMTOParams(), makeThumbLinkObj(), makeThumbLink2(),
# processResponsiveImages(), makeBrokenImageLinkObj(), makeMediaLinkObj(), link()); ported on 2026-10-30 with
# Parser::makeImage(). Where MediaWiki asks its services, these functions ask the parser: its config, link renderer,
# link cache (pages and files), bad file list and target language. -----------------------------------------------

THUMB_UPRIGHT = 0.75  # $wgThumbUpright
DEFAULT_THUMBSIZE_OPTION = 5  # $wgDefaultUserOptions['thumbsize'], an index into $wgThumbLimits


def legacy_media_dom(config) -> bool:
    """$wgParserEnableLegacyMediaDOM: true in MediaWiki 1.39 (<div class="thumb"> and class="image"); false gives
    the <figure>/<span typeof="mw:File"> output of mediaParserTests.txt."""
    return getattr(config, "parser_enable_legacy_media_dom", True)


def link(parser, target, html: Optional[str] = None, custom_attribs: Optional[dict] = None,
         query: Optional[dict] = None, options: tuple = ()) -> str:
    """Linker::link(): an HTML link to a page; ``options``: 'known', 'broken', 'noclasses'."""
    from .linkrenderer import HtmlArmor

    link_renderer = parser.get_link_renderer()
    text = HtmlArmor(html) if html is not None else None
    if "known" in options:
        return link_renderer.make_known_link(target, text, custom_attribs or {}, query or {})
    if "broken" in options:
        return link_renderer.make_broken_link(target, text, custom_attribs or {}, query or {})
    if "noclasses" in options:
        return link_renderer.make_preloaded_link(target, text, "", custom_attribs or {}, query or {})
    return link_renderer.make_link(target, text, custom_attribs or {}, query or {})


def make_image_link(parser, title, file, frame_params: Optional[dict] = None, handler_params: Optional[dict] = None,
                    time=False, query: str = "", width_option: Optional[int] = None) -> str:
    """Given parameters derived from [[Image:Foo|options...]], generate the HTML that that syntax inserts in the
    page. ``title``: the Title of the file (not the currently viewed page); ``file``: the File, or None if it
    doesn't exist.

    ``frame_params``: parameters external to the media handler; boolean parameters are indicated by presence or
    absence: thumbnail, manualthumb, framed, frameless, upright, upright_factor, border, align (left, right,
    center, none), valign, alt, title, class, caption (HTML), link-url, link-title, link-target, no-link.
    ``handler_params``: media handler parameters, to be passed to transform(): width, page, targetlang, ...
    ``width_option``: the user preference thumbnail size (an index into $wgThumbLimits)."""
    from .files import php_loose_equals_zero, php_round, php_float
    from .html import raw_element as html_raw_element

    config = parser.config
    frame_params = dict(frame_params or {})
    handler_params = dict(handler_params or {})

    if file and not file.allow_inline_display():
        return link(parser, title)

    # Clean up parameters
    page = handler_params.get("page", False)
    frame_params.setdefault("align", "")
    frame_params.setdefault("alt", "")
    frame_params.setdefault("title", "")
    frame_params.setdefault("class", "")

    enable_legacy_media_dom = legacy_media_dom(config)

    classes = []
    if "width" not in handler_params and "manualthumb" not in frame_params and "framed" not in frame_params:
        classes.append("mw-default-size")

    prefix = postfix = ""

    if enable_legacy_media_dom:
        if frame_params["align"] == "center":
            prefix = '<div class="center">'
            postfix = "</div>"
            frame_params["align"] = "none"

    if file and "width" not in handler_params:
        if "height" in handler_params and file.is_vectorized():
            # If its a vector image, and user only specifies height we don't want it to be limited by its "normal"
            # width.
            from .files import SVG_MAX_SIZE
            handler_params["width"] = SVG_MAX_SIZE
        else:
            handler_params["width"] = file.get_width(page)

        if ("thumbnail" in frame_params or "manualthumb" in frame_params or "framed" in frame_params
                or "frameless" in frame_params or not handler_params["width"]):
            thumb_limits = config.thumb_limits
            if width_option is None or not 0 <= width_option < len(thumb_limits):
                width_option = DEFAULT_THUMBSIZE_OPTION

            # Reduce width for upright images when parameter 'upright' is used
            if "upright" in frame_params and php_loose_equals_zero(frame_params["upright"]):
                frame_params["upright"] = THUMB_UPRIGHT

            # For caching health: If width scaled down due to upright parameter, round to full __0 pixel to avoid
            # the creation of a lot of odd thumbs.
            if "upright" in frame_params:
                pref_width = php_round(thumb_limits[width_option] * php_float(frame_params["upright"]), -1)
            else:
                pref_width = thumb_limits[width_option]

            # Use width which is smaller: real image width or user preference width Unless image is scalable
            # vector.
            if "height" not in handler_params and (handler_params["width"] <= 0
                                                   or pref_width < handler_params["width"] or file.is_vectorized()):
                handler_params["width"] = pref_width

    # Parser::makeImage has a similarly named variable
    has_visible_caption = "thumbnail" in frame_params or "manualthumb" in frame_params or "framed" in frame_params

    if has_visible_caption:
        if enable_legacy_media_dom:
            # Create a thumbnail. Alignment depends on the writing direction of the page content language
            # (right-aligned for LTR languages, left-aligned for RTL languages) If a thumbnail width has not been
            # provided, it is set to the default user option as specified in Language*.php
            if frame_params["align"] == "":
                frame_params["align"] = "right"  # Language::alignEnd() of English
        return prefix + make_thumb_link2(title, file, frame_params, handler_params, time, query, classes,
                                         parser) + postfix

    rdfa_type = "mw:File"

    if "frameless" in frame_params:
        rdfa_type += "/Frameless"
        if file:
            src_width = file.get_width(page)
            # For "frameless" option: do not present an image bigger than the source (for bitmap-style images).
            # This is the same behavior as the "thumb" option does it already.
            if src_width and not file.must_render() and handler_params["width"] > src_width:
                handler_params["width"] = src_width

    if file and "width" in handler_params:
        # Create a resized image, without the additional thumbnail features
        thumb = file.transform(handler_params)
    else:
        thumb = None

    is_bad_file = bool(file and thumb and parser.get_bad_file_lookup().is_bad_file(
        title.db_key, parser.get_title_object()))

    if not thumb or (not enable_legacy_media_dom and thumb.is_error()) or is_bad_file:
        rdfa_type = "mw:Error " + rdfa_type
        current_exists = bool(file and file.exists())
        if enable_legacy_media_dom:
            # This is the information for tooltips for inline images which Parsoid stores in data-mw. See T273014
            label = frame_params["title"]
        else:
            if current_exists and not thumb:
                label = "Error creating thumbnail: "
            elif thumb and thumb.is_error():
                label = thumb.to_text()
            else:
                label = ""
        s = make_broken_image_link_obj(parser, title, label, "", "", "", bool(time), handler_params, current_exists)
    else:
        process_responsive_images(parser, file, thumb, handler_params)
        params = {"alt": frame_params["alt"], "title": frame_params["title"]}
        if enable_legacy_media_dom:
            params["valign"] = frame_params.get("valign", False)
            params["img-class"] = frame_params["class"]
            if "border" in frame_params:
                params["img-class"] += (" " if params["img-class"] != "" else "") + "thumbborder"
        params = {**params, **get_image_link_mto_params(frame_params, query, parser)}
        s = thumb.to_html(params, legacy_media_dom=enable_legacy_media_dom)

    if enable_legacy_media_dom:
        if frame_params["align"] != "":
            s = html_raw_element("div", {"class": "float" + frame_params["align"]}, s)
        return (prefix + s + postfix).replace("\n", " ")

    wrapper = "span"
    caption = ""

    if frame_params["align"] != "":
        wrapper = "figure"
        # Possible values: mw-halign-left mw-halign-center mw-halign-right mw-halign-none
        classes.append(f"mw-halign-{frame_params['align']}")
        caption = html_raw_element("figcaption", {}, frame_params.get("caption") or "")
    elif frame_params.get("valign"):
        # Possible values: mw-valign-middle mw-valign-baseline mw-valign-sub mw-valign-super mw-valign-top
        # mw-valign-text-top mw-valign-bottom mw-valign-text-bottom
        classes.append(f"mw-valign-{frame_params['valign']}")

    if "border" in frame_params:
        classes.append("mw-image-border")

    if "class" in frame_params:
        classes.append(frame_params["class"])

    s = html_raw_element(wrapper, {"class": classes, "typeof": rdfa_type}, s + caption)
    return s.replace("\n", " ")


def get_image_link_mto_params(frame_params: dict, query="", parser=None) -> dict:
    """The link parameters for MediaTransformOutput::toHtml() from given frame parameters supplied by the Parser."""
    mto_params: dict = {}
    if frame_params.get("link-url"):
        mto_params["custom-url-link"] = frame_params["link-url"]
        if "link-target" in frame_params:
            mto_params["custom-target-link"] = frame_params["link-target"]
        if parser is not None:
            ext_link_attrs = parser.get_external_link_attribs(frame_params["link-url"])
            for name, val in ext_link_attrs.items():
                # Currently could include 'rel' and 'target'
                mto_params["parser-extlink-" + name] = val
    elif frame_params.get("link-title"):
        link_renderer = parser.get_link_renderer()
        mto_params["custom-title-link"] = link_renderer.normalize_target(frame_params["link-title"])
        if "link-title-query" in frame_params:
            mto_params["custom-title-link-query"] = frame_params["link-title-query"]
    elif frame_params.get("no-link"):
        pass  # No link
    else:
        mto_params["desc-link"] = True
        mto_params["desc-query"] = query
    return mto_params


def make_thumb_link_obj(parser, title, file, label: str = "", alt: str = "", align=None,
                        params: Optional[dict] = None, framed: bool = False, manualthumb: str = "") -> str:
    """Make HTML for a thumbnail including image, border and caption"""
    params = params or {}
    frame_params = {"alt": alt, "caption": label, "align": align}
    classes = []
    if manualthumb:
        frame_params["manualthumb"] = manualthumb
    elif framed:
        frame_params["framed"] = True
    elif "width" not in params:
        classes.append("mw-default-size")
    return make_thumb_link2(title, file, frame_params, params, False, "", classes, parser)


def make_thumb_link2(title, file, frame_params: Optional[dict] = None, handler_params: Optional[dict] = None,
                     time=False, query: str = "", classes: Optional[list] = None, parser=None) -> str:
    """The HTML of a framed image: a thumbnail (thumb, manualthumb) or the image at its own size (frame)."""
    from .html import raw_element as html_raw_element
    from .site import NS_FILE
    from .title import Title, wf_append_query

    frame_params = dict(frame_params or {})
    handler_params = dict(handler_params or {})
    classes = list(classes or [])
    exists = bool(file and file.exists())
    enable_legacy_media_dom = legacy_media_dom(parser.config)

    page = handler_params.get("page", False)
    if frame_params.get("align") is None:
        frame_params["align"] = "right" if enable_legacy_media_dom else ""
    frame_params.setdefault("alt", "")
    frame_params.setdefault("caption", "")

    if not handler_params.get("width"):
        # Reduce width for upright images when parameter 'upright' is used
        handler_params["width"] = 130 if "upright" in frame_params else 180

    thumb = None
    noscale = False
    manualthumb = False
    manual_title = None
    rdfa_type = "mw:File/Thumb"

    if not exists:
        # Same precedence as the exists case
        if "manualthumb" not in frame_params and "framed" in frame_params:
            rdfa_type = "mw:File/Frame"
        outer_width = handler_params["width"] + 2
    else:
        if "manualthumb" in frame_params:
            # Use manually specified thumbnail
            manual_title = Title.make_title_safe(NS_FILE, frame_params["manualthumb"], site=title.site)
            if manual_title:
                manual_img = parser.get_link_cache().find_file(manual_title)
                if manual_img:
                    thumb = manual_img.get_unscaled_thumb(handler_params)
                    manualthumb = True
        elif "framed" in frame_params:
            # Use image dimensions, don't scale
            thumb = file.get_unscaled_thumb(handler_params)
            noscale = True
            rdfa_type = "mw:File/Frame"
        else:
            # Do not present an image bigger than the source, for bitmap-style images. This is a hack to maintain
            # compatibility with arbitrary pre-1.10 behavior
            src_width = file.get_width(page)
            if src_width and not file.must_render() and handler_params["width"] > src_width:
                handler_params["width"] = src_width
            thumb = file.transform(handler_params)

        if thumb:
            outer_width = thumb.get_width() + 2
        else:
            outer_width = handler_params["width"] + 2

    url = title.get_local_url(query or "")
    link_title_query: dict = {}

    if page:
        link_title_query["page"] = page
        # ThumbnailImage::toHtml() already adds page= onto the end of DjVu URLs. So we don't need to pass it here
        # in query. However, the URL for the zoom icon still needs it, so we make a unique query for it. See T16771
        url = wf_append_query(url, link_title_query)

    if (manualthumb and "link-title" not in frame_params and "link-url" not in frame_params
            and "no-link" not in frame_params):
        frame_params["link-title"] = title
        frame_params["link-title-query"] = link_title_query

    if frame_params["align"] != "":
        # Possible values: mw-halign-left mw-halign-center mw-halign-right mw-halign-none
        classes.append(f"mw-halign-{frame_params['align']}")

    if "class" in frame_params:
        classes.append(frame_params["class"])

    s = ""

    if enable_legacy_media_dom:
        s += (f'<div class="thumb t{frame_params["align"]}">'
              f'<div class="thumbinner" style="width:{_php_number(outer_width)}px;">')

    is_bad_file = bool(exists and thumb and parser is not None and parser.get_bad_file_lookup().is_bad_file(
        manual_title.db_key if manualthumb else title.db_key, parser.get_title_object()))

    if not exists:
        rdfa_type = "mw:Error " + rdfa_type
        s += make_broken_image_link_obj(parser, title, "", "", "", "", bool(time), handler_params, False)
        zoom_icon = ""
    elif not thumb or (not enable_legacy_media_dom and thumb.is_error()) or is_bad_file:
        rdfa_type = "mw:Error " + rdfa_type
        if enable_legacy_media_dom:
            if not thumb:
                s += htmlspecialchars("Error creating thumbnail: ")
            else:
                s += make_broken_image_link_obj(parser, title, "", "", "", "", bool(time), handler_params, True)
        else:
            if thumb and thumb.is_error():
                label = thumb.to_text()
            elif not thumb:
                label = "Error creating thumbnail: "
            else:
                label = ""
            s += make_broken_image_link_obj(parser, title, label, "", "", "", bool(time), handler_params, True)
        zoom_icon = ""
    else:
        if not noscale and not manualthumb:
            process_responsive_images(parser, file, thumb, handler_params)
        params = {"alt": frame_params["alt"]}
        if enable_legacy_media_dom:
            params["img-class"] = ((frame_params["class"] + " " if frame_params.get("class") else "")
                                   + "thumbimage")
        params = {**params, **get_image_link_mto_params(frame_params, query, parser)}
        s += thumb.to_html(params, legacy_media_dom=enable_legacy_media_dom)
        if "framed" in frame_params:
            zoom_icon = ""
        else:
            zoom_icon = html_raw_element("div", {"class": "magnify"}, html_raw_element(
                "a", {"href": url, "class": "internal", "title": "Enlarge"}))  # thumbnail-more

    if enable_legacy_media_dom:
        s += '  <div class="thumbcaption">' + zoom_icon + frame_params["caption"] + "</div></div></div>"
        return s.replace("\n", " ")

    s += html_raw_element("figcaption", {}, frame_params.get("caption") or "")
    s = html_raw_element("figure", {"class": classes, "typeof": rdfa_type}, s)
    return s.replace("\n", " ")


def _php_number(value) -> str:
    from .files import php_number

    return php_number(value)


def process_responsive_images(parser, file, thumb, hp: dict) -> None:
    """Process responsive images: add 1.5x and 2x subimages to the thumbnail, where applicable ($wgResponsiveImages
    is true by default)."""
    from .files import php_round

    if getattr(parser.config, "responsive_images", True) and thumb and not thumb.is_error():
        hp15 = dict(hp)
        hp15["width"] = php_round(hp["width"] * 1.5)
        hp20 = dict(hp)
        hp20["width"] = hp["width"] * 2
        if "height" in hp:
            hp15["height"] = php_round(hp["height"] * 1.5)
            hp20["height"] = hp["height"] * 2
        thumb15 = file.transform(hp15)
        thumb20 = file.transform(hp20)
        if thumb15 and not thumb15.is_error() and thumb15.get_url() != thumb.get_url():
            thumb.responsive_urls["1.5"] = thumb15.get_url()
        if thumb20 and not thumb20.is_error() and thumb20.get_url() != thumb.get_url():
            thumb.responsive_urls["2"] = thumb20.get_url()


def make_broken_image_link_obj(parser, title, label: str = "", query: str = "", unused1: str = "",
                               unused2: str = "", time: bool = False, handler_params: Optional[dict] = None,
                               current_exists: bool = False) -> str:
    """Make a "broken" link to an image: to the upload form for a missing file (uploads enabled), otherwise to the
    file page. ``label``: link label (plain text)."""
    from .site import NS_FILE

    handler_params = handler_params or {}
    config = parser.config
    if label == "":
        label = title.prefixed_text

    html = element("span", {
        "class": "mw-broken-media",
        # These data attributes are used to dynamically size the span, see T273013
        "data-width": _attr_number(handler_params.get("width")),
        "data-height": _attr_number(handler_params.get("height")),
    }, label)

    if legacy_media_dom(config):
        html = htmlspecialchars(label, False)

    link_cache = parser.get_link_cache()
    current_exists = current_exists or bool(time and link_cache.find_file(title) is not None)

    if config.enable_uploads and not current_exists:
        if title.in_namespace(NS_FILE) and link_cache.check_redirect(title):
            # We already know it's a redirect, so mark it accordingly
            return link(parser, title, html, {"class": "mw-redirect"}, _cgi_to_array(query), ("known", "noclasses"))
        return raw_element("a", {"href": get_upload_url(title, query), "class": "new", "title": title.prefixed_text},
                           html)
    return link(parser, title, html, {}, _cgi_to_array(query), ("known", "noclasses"))


def _attr_number(value):
    if value is None:
        return None
    return _php_number(value)


def _cgi_to_array(query: str) -> dict:
    """wfCgiToArray() for simple queries"""
    from urllib.parse import unquote_plus

    ret = {}
    for bit in (query or "").split("&"):
        if bit == "":
            continue
        key, _, value = bit.partition("=")
        ret[unquote_plus(key)] = unquote_plus(value)
    return ret


def make_media_link_obj(parser, title, html: str = "", time=False) -> str:
    """Create a direct link to a given uploaded file."""
    return make_media_link_file(title, parser.get_link_cache().find_file(title), html)

# Ported from RemexHtml 3.0.2 src/HTMLData.php and tools/GenerateDataFiles.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the named character reference table is
# Python's html.entities.html5 (identical to HTMLData::$namedEntityTranslations, checked when this was ported)
# instead of a copy, and the named entity regex is replaced by named_entity_match(), which gives the same
# longest match; the XML name conversion tables (used only by the DOM builder) are not ported.
"""Data tables used by the tokenizer and the tree builder.

This data file is machine generated in RemexHtml, see tools/GenerateDataFiles.php.
"""
from __future__ import annotations

import re
from html.entities import html5 as _HTML5
from typing import Optional


class HTMLData:
    NS_HTML = "http://www.w3.org/1999/xhtml"
    NS_MATHML = "http://www.w3.org/1998/Math/MathML"
    NS_SVG = "http://www.w3.org/2000/svg"
    NS_XLINK = "http://www.w3.org/1999/xlink"
    NS_XML = "http://www.w3.org/XML/1998/namespace"
    NS_XMLNS = "http://www.w3.org/2000/xmlns/"

    special: dict[str, frozenset[str]] = {
        NS_HTML: frozenset("""
            address applet area article aside base basefont bgsound blockquote body br button caption center
            col colgroup dd details dir div dl dt embed fieldset figcaption figure footer form frame frameset h1 h2
            h3 h4 h5 h6 head header hr html iframe img input li link listing main marquee menu menuitem meta nav
            noembed noframes noscript object ol p param plaintext pre script section select source style summary
            table tbody td template textarea tfoot th thead title tr track ul wbr xmp
        """.split()),
        NS_MATHML: frozenset(["mi", "mo", "mn", "ms", "mtext", "annotation-xml"]),
        NS_SVG: frozenset(["foreignObject", "desc", "title"]),
    }

    # The WHATWG named character references, keys without the leading "&", some also without the trailing ";"
    # (the legacy ones)
    namedEntityTranslations: dict[str, str] = _HTML5

    # This is the character entity mapping table copied from
    # https://www.w3.org/TR/2014/REC-html5-20141028/syntax.html#tokenizing-character-references
    legacyNumericEntities: dict[int, str] = {
        0x00: "�",
        0x80: "€",
        0x82: "‚",
        0x83: "ƒ",
        0x84: "„",
        0x85: "…",
        0x86: "†",
        0x87: "‡",
        0x88: "ˆ",
        0x89: "‰",
        0x8A: "Š",
        0x8B: "‹",
        0x8C: "Œ",
        0x8E: "Ž",
        0x91: "‘",
        0x92: "’",
        0x93: "“",
        0x94: "”",
        0x95: "•",
        0x96: "–",
        0x97: "—",
        0x98: "˜",
        0x99: "™",
        0x9A: "š",
        0x9B: "›",
        0x9C: "œ",
        0x9E: "ž",
        0x9F: "Ÿ",
    }

    # The list of public identifier prefixes that cause quirks mode to be set, from § 8.2.5.4.1, as the generator
    # writes it: GenerateDataFiles::makeRegexAlternation() drops the first character of each prefix (it is meant
    # for entity names, which start with "&"), and the "x" modifier makes the spaces in the prefixes insignificant.
    # Both are reproduced as they are, since they decide which documents RemexHtml parses in quirks mode.
    quirkyPrefixRegex: re.Pattern[str] = re.compile(r"""
        //Silmaril//dtd html Pro v0r11 19970101//|
        //AS//DTD HTML 3\.0 asWedit \+ extensions//|
        //AdvaSoft Ltd//DTD HTML 3\.0 asWedit \+ extensions//|
        //IETF//DTD HTML 2\.0 Level 1//|
        //IETF//DTD HTML 2\.0 Level 2//|
        //IETF//DTD HTML 2\.0 Strict Level 1//|
        //IETF//DTD HTML 2\.0 Strict Level 2//|
        //IETF//DTD HTML 2\.0 Strict//|
        //IETF//DTD HTML 2\.0//|
        //IETF//DTD HTML 2\.1E//|
        //IETF//DTD HTML 3\.0//|
        //IETF//DTD HTML 3\.2 Final//|
        //IETF//DTD HTML 3\.2//|
        //IETF//DTD HTML 3//|
        //IETF//DTD HTML Level 0//|
        //IETF//DTD HTML Level 1//|
        //IETF//DTD HTML Level 2//|
        //IETF//DTD HTML Level 3//|
        //IETF//DTD HTML Strict Level 0//|
        //IETF//DTD HTML Strict Level 1//|
        //IETF//DTD HTML Strict Level 2//|
        //IETF//DTD HTML Strict Level 3//|
        //IETF//DTD HTML Strict//|
        //IETF//DTD HTML//|
        //Metrius//DTD Metrius Presentational//|
        //Microsoft//DTD Internet Explorer 2\.0 HTML Strict//|
        //Microsoft//DTD Internet Explorer 2\.0 HTML//|
        //Microsoft//DTD Internet Explorer 2\.0 Tables//|
        //Microsoft//DTD Internet Explorer 3\.0 HTML Strict//|
        //Microsoft//DTD Internet Explorer 3\.0 HTML//|
        //Microsoft//DTD Internet Explorer 3\.0 Tables//|
        //Netscape Comm\. Corp\.//DTD HTML//|
        //Netscape Comm\. Corp\.//DTD Strict HTML//|
        //O'Reilly and Associates//DTD HTML 2\.0//|
        //O'Reilly and Associates//DTD HTML Extended 1\.0//|
        //O'Reilly and Associates//DTD HTML Extended Relaxed 1\.0//|
        //SoftQuad Software//DTD HoTMetaL PRO 6\.0\:\:19990601\:\:extensions to HTML 4\.0//|
        //SoftQuad//DTD HoTMetaL PRO 4\.0\:\:19971010\:\:extensions to HTML 4\.0//|
        //Spyglass//DTD HTML 2\.0 Extended//|
        //SQ//DTD HTML 2\.0 HoTMetaL \+ extensions//|
        //Sun Microsystems Corp\.//DTD HotJava HTML//|
        //Sun Microsystems Corp\.//DTD HotJava Strict HTML//|
        //W3C//DTD HTML 3 1995\-03\-24//|
        //W3C//DTD HTML 3\.2 Draft//|
        //W3C//DTD HTML 3\.2 Final//|
        //W3C//DTD HTML 3\.2//|
        //W3C//DTD HTML 3\.2S Draft//|
        //W3C//DTD HTML 4\.0 Frameset//|
        //W3C//DTD HTML 4\.0 Transitional//|
        //W3C//DTD HTML Experimental 19960712//|
        //W3C//DTD HTML Experimental 970421//|
        //W3C//DTD W3 HTML//|
        //W3O//DTD W3 HTML 3\.0//|
        //WebTechs//DTD Mozilla HTML 2\.0//|
        //WebTechs//DTD Mozilla HTML//""", re.X | re.I | re.A)  # used with match(): the "A" modifier


# Candidates for a named character reference: entity names are ASCII letters and digits, some with a final ";"
_NAMED_ENTITY_CANDIDATE = re.compile(r"[a-zA-Z0-9]+;?")


def named_entity_match(text: str, pos: int) -> Optional[str]:
    """The named character reference at ``pos`` in ``text`` (without the "&"), or None.

    In RemexHtml this is the alternation HTMLData::$namedEntityRegex inside HTMLData::$charRefRegex: every entity
    name, sorted by descending length, so PCRE takes the longest name that the text starts with, e.g. "notin;"
    rather than "not" for "&notin;", but "not" for "&notit;". Every name consists of letters and digits with an
    optional final semicolon, so the longest one is a prefix of the run of such characters at ``pos``.
    """
    m = _NAMED_ENTITY_CANDIDATE.match(text, pos)
    if not m:
        return None
    candidate = m.group(0)
    if candidate in _HTML5:
        return candidate
    if candidate.endswith(";"):
        candidate = candidate[:-1]
    for length in range(min(len(candidate), 32), 0, -1):
        if candidate[:length] in _HTML5:
            return candidate[:length]
    return None

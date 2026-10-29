# Ported from MediaWiki 1.39 includes/parser/Sanitizer.php (https://www.mediawiki.org/), (C) MediaWiki contributors;
# also includes/parser/RemexStripTagHandler.php, includes/parser/RemexRemoveTagHandler.php, part of
# includes/tidy/RemexCompatFormatter.php and UrlUtils::validProtocols() (for wfUrlProtocols()).
# Changed by a3ref contributors on 2026-10-30: translated to Python; the class of static methods became
# module-level functions and MediaWiki's configuration globals a ``config`` argument (config.py); PHP's byte-string and
# PCRE behaviour is reproduced where Python's differs (see the comments); removeSomeTags() and stripAllTags() run
# on Python's html.parser instead of RemexHtml (an approximation until Remex is ported); hooks are not run.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""HTML sanitizer for MediaWiki.

Notes on the translation, valid for the whole file:

- PHP strings are bytes, Python strings are code points. Regular expressions without PHP's ``/u`` modifier work on
  bytes there: ``\\s``, ``\\w`` and ``/i`` cover ASCII only, so their Python versions use ``re.ASCII``. With ``/u``
  PHP also turns on Unicode properties (PCRE2_UCP), which is what Python does by default.
- PHP's ``trim()`` strips `` \\t\\n\\r\\0\\x0B`` (not all Unicode whitespace) and ``strtolower()`` folds only ASCII
  letters; ``_php_trim`` and ``_php_strtolower`` do the same.
- PHP's ``$`` (without ``/D``) also matches before a final newline, exactly like Python's ``$``.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from html.entities import html5 as _HTML5_ENTITIES
from html.parser import HTMLParser
from types import MappingProxyType
from typing import Any, Callable, Iterable, Literal, Mapping, Optional, Union

from .config import DEFAULT, Config
from .stringutils import delimiter_replace, php_strtr

# Configuration: MediaWiki reads $wgFragmentMode, $wgExternalInterwikiFragmentMode, $wgAllowImageTag and
# $wgUrlProtocols from globals; here the functions that depend on them take ``config`` (see config.py).


def wf_url_protocols(include_protocol_relative: bool = True, *, config: Config = DEFAULT) -> str:
    """Returns a regular expression of URL protocols (GlobalFunctions.php wfUrlProtocols(), implemented by
    UrlUtils::validProtocolsInternal()) from $wgUrlProtocols. The result is a Python regex alternation.

    ``include_protocol_relative``: if false, remove '//' from the returned protocol list.
    """
    return _url_protocols_regex(tuple(config.url_protocols), include_protocol_relative)


@functools.lru_cache(maxsize=16)
def _url_protocols_regex(url_protocols: tuple[str, ...], include_protocol_relative: bool) -> str:
    protocols = [re.escape(protocol) for protocol in url_protocols
                 if include_protocol_relative or protocol != "//"]
    return "|".join(protocols)


@functools.lru_cache(maxsize=16)
def _href_exp(url_protocols: tuple[str, ...]) -> re.Pattern[str]:
    # '/^(' . wfUrlProtocols() . ')[^\s]+$/': a byte regex, so \s is ASCII whitespace
    return re.compile("^(" + _url_protocols_regex(url_protocols, True) + r")[^\s]+$", re.ASCII)


@functools.lru_cache(maxsize=16)
def _protocols_hack_regex(url_protocols: tuple[str, ...]) -> re.Pattern[str]:
    # '/((?i)' . wfUrlProtocols() . ')/': a byte regex, so case-insensitive for ASCII only
    return re.compile("(" + _url_protocols_regex(url_protocols, True) + ")", re.I | re.ASCII)


# --- PHP helpers ---------------------------------------------------------------------------------------------------

_ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}


def _php_strtolower(s: str) -> str:
    """strtolower(): ASCII letters only (PHP 8, and any PHP in the C locale)."""
    return s.translate(_ASCII_LOWER)


def _php_trim(s: str) -> str:
    """trim() with its default character list."""
    return s.strip(" \t\n\r\0\x0b")


def _htmlspecialchars(s: str, quotes: bool = True) -> str:
    """htmlspecialchars( $s, ENT_QUOTES ) (``quotes``) or htmlspecialchars( $s, ENT_COMPAT ). With ENT_HTML401 (the
    default document type) the single quote becomes ``&#039;``. ENT_SUBSTITUTE only matters for invalid UTF-8,
    which a Python string cannot hold."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    if quotes:
        s = s.replace("'", "&#039;")
    return s


_URLENCODE_SAFE = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.")


def _php_urlencode(s: str) -> str:
    """urlencode(): every byte of the UTF-8 encoding except ``A-Za-z0-9-_.`` becomes %XX, space becomes '+'.
    (Python's quote_plus also keeps '~', which PHP's urlencode encodes.)"""
    out = []
    for byte in s.encode("utf-8", "surrogatepass"):
        if byte in _URLENCODE_SAFE:
            out.append(chr(byte))
        elif byte == 0x20:
            out.append("+")
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def _codepoint_to_utf8(codepoint: int) -> str:
    """UtfNormal\\Utils::codepointToUtf8() (wikimedia/utfnormal 3.0.2): mb_chr(), which refuses surrogates and
    values above U+10FFFF; MediaWiki throws InvalidArgumentException then, so does this (as ValueError)."""
    if codepoint == 0:
        return "\0"
    if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        raise ValueError(f"Asked for code outside of range ({codepoint})")
    return chr(codepoint)


# UtfNormal\Constants::UTF8_REPLACEMENT
UTF8_REPLACEMENT = "�"

# --- Constants -----------------------------------------------------------------------------------------------------

# Regular expression to match various types of character references in Sanitizer::normalizeCharReferences and
# Sanitizer::decodeCharReferences. Note that HTML5 allows some named entities to omit the trailing semicolon;
# wikitext entities *must* have a trailing semicolon.
# (PHP's [\x80-\xff] matches the bytes of any non-ASCII character; on code points that is \x80 and up.)
_CHAR_REFS_REGEX = re.compile(r"""&([A-Za-z0-9\x80-\U0010FFFF]+;)
    |&\#([0-9]+);
    |&\#[xX]([0-9A-Fa-f]+);
    |(&)""", re.X)

# Acceptable tag name charset from HTML5 parsing spec https://www.w3.org/TR/html5/syntax.html#tag-open-state
# PHP: '!^(/?)([A-Za-z][^\t\n\v />\0]*+)([^>]*?)(/?>)([^<]*)$!'. In a byte-mode PCRE class \v is "vertical space"
# (\n \x0B \f \r \x85), so \f and \r also end the name. Byte \x85 only occurs inside a multi-byte character there,
# where the name could no longer be a known element, so it is left out here: U+0085 stays part of the name, which
# keeps such a tag unknown, as in PHP. The possessive *+ changes nothing (backtracking into the name cannot help a
# failed match), and is dropped for Python 3.10.
_ELEMENT_BITS_REGEX = re.compile(r"^(/?)([A-Za-z][^\t\n\x0b\x0c\r />\0]*)([^>]*?)(/?>)([^<]*)$")

# Pattern matching evil uris like javascript:
# WARNING: DO NOT use this in any place that actually requires denying certain URIs for security reasons. There are
# NUMEROUS[1] ways to bypass pattern-based deny lists; the only way to be secure from javascript: uri based xss
# vectors is to allow only things that you know are safe and deny everything else.
# [1]: http://ha.ckers.org/xss.html
_EVIL_URI_PATTERN = re.compile(r"(^|\s|\*/\s*)(javascript|vbscript)([^\w]|$)", re.I | re.ASCII)
_XMLNS_ATTRIBUTE_PATTERN = re.compile(r"^xmlns:[:A-Z_a-z\-.0-9]+$")

# Tells escapeUrlForHtml() to encode the ID using the wiki's primary encoding.
ID_PRIMARY = 0

# Tells escapeUrlForHtml() to encode the ID using the fallback encoding, or return false if no fallback is
# configured.
ID_FALLBACK = 1

# Character entity aliases accepted by MediaWiki in wikitext. These are not part of the HTML standard.
_MW_ENTITY_ALIASES = {
    "רלמ;": "rlm;",
    "رلم;": "rlm;",
}

# HTMLData::$namedEntityTranslations (RemexHtml): the WHATWG list, with and without the trailing ";" for the legacy
# names, the same as Python's html.entities.html5. Sanitizer only looks names up with their ";".
_NAMED_ENTITY_TRANSLATIONS: Mapping[str, str] = _HTML5_ENTITIES

# Regular expression to match HTML/XML attribute pairs within a tag. Based on
# https://www.w3.org/TR/html5/syntax.html#before-attribute-name-state Used in Sanitizer::decodeTagAttributes
_SPACE_CHARS = r"\x09\x0a\x0c\x0d\x20"
_SPACE = f"[{_SPACE_CHARS}]"
_ATTRIB = rf"[^{_SPACE_CHARS}\/>=]"
_ATTRIB_FIRST = rf"(?:{_ATTRIB}|=)"
_ATTRIBS_REGEX = re.compile(
    rf"""({_ATTRIB_FIRST}{_ATTRIB}*)
        ({_SPACE}*={_SPACE}*
        (?:
            # The attribute value: quoted or alone
            "([^"]*)(?:"|$)
            | '([^']*)(?:'|$)
            | (((?!{_SPACE}|>).)*)
        )
    )?""", re.S | re.X)


def _is_attrib_name(name: str) -> bool:
    """Used in Sanitizer::decodeTagAttributes to filter attributes.

    PHP: ``/^([:_\\p{L}\\p{N}][:_\\.\\-\\p{L}\\p{N}]*)$/sxu``. Python's re has no \\p{...}, so the Unicode general
    categories are checked directly (L* = letters, N* = numbers)."""
    if not name:
        return False
    for i, ch in enumerate(name):
        if ch in ":_" or (i and ch in ".-"):
            continue
        if unicodedata.category(ch)[0] in "LN":
            continue
        return False
    return True


# --- Tag lists -----------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=2)
def _static_tag_data(allow_image_tag: bool) -> dict[str, frozenset[str]]:
    htmlpairs_static = [  # Tags that must be closed
        "b", "bdi", "del", "i", "ins", "u", "font", "big", "small", "sub", "sup", "h1",
        "h2", "h3", "h4", "h5", "h6", "cite", "code", "em", "s",
        "strike", "strong", "tt", "var", "div", "center",
        "blockquote", "ol", "ul", "dl", "table", "caption", "pre",
        "ruby", "rb", "rp", "rt", "rtc", "p", "span", "abbr", "dfn",
        "kbd", "samp", "data", "time", "mark",
    ]
    # These tags can be self-closed. For tags not also on $htmlsingleonly, a self-closed tag will be emitted as an
    # empty element (open-tag/close-tag pair).
    htmlsingle = [
        "br", "wbr", "hr", "li", "dt", "dd", "meta", "link",
    ]

    # Elements that cannot have close tags. This is (not coincidentally) also the list of tags for which the HTML 5
    # parsing algorithm requires you to "acknowledge the token's self-closing flag", i.e. a self-closing tag like
    # <br/> is not an HTML 5 parse error only for this list.
    htmlsingleonly = [
        "br", "wbr", "hr", "meta", "link",
    ]

    htmlnest = [  # Tags that can be nested--??
        "table", "tr", "td", "th", "div", "blockquote", "ol", "ul",
        "li", "dl", "dt", "dd", "font", "big", "small", "sub", "sup", "span",
        "var", "kbd", "samp", "em", "strong", "q", "ruby", "bdo",
    ]
    tabletags = [  # Can only appear inside table, we will close them
        "td", "th", "tr",
    ]
    htmllist = [  # Tags used by list
        "ul", "ol",
    ]
    listtags = [  # Tags that can appear in a list
        "li",
    ]

    if allow_image_tag:
        # (MediaWiki logs: Setting $wgAllowImageTag to true is deprecated since MediaWiki 1.35)
        htmlsingle.append("img")
        htmlsingleonly.append("img")

    htmlsingleallowed = htmlsingle + tabletags
    htmlelements_static = htmlsingle + htmlpairs_static + htmlnest

    # Convert them all to hashtables for faster lookup
    return {
        "htmlpairsStatic": frozenset(htmlpairs_static),
        "htmlsingle": frozenset(htmlsingle),
        "htmlsingleonly": frozenset(htmlsingleonly),
        "htmlnest": frozenset(htmlnest),
        "tabletags": frozenset(tabletags),
        "htmllist": frozenset(htmllist),
        "listtags": frozenset(listtags),
        "htmlsingleallowed": frozenset(htmlsingleallowed),
        "htmlelementsStatic": frozenset(htmlelements_static),
    }


def get_recognized_tag_data(extratags: Optional[Iterable[str]] = None, removetags: Optional[Iterable[str]] = None,
                            *, config: Config = DEFAULT) -> dict[str, frozenset[str]]:
    """Return the various lists of recognized tags

    ``extratags``: for any extra tags to include. ``removetags``: for any tags (default or extra) to exclude.
    The lists are sets (PHP: arrays with the names as keys). Reads $wgAllowImageTag. @internal
    """
    static = _static_tag_data(bool(config.allow_image_tag))
    extra = frozenset(extratags or ())
    remove = frozenset(removetags or ())
    # Populate $htmlpairs and $htmlelements with the $extratags and $removetags arrays
    htmlpairs = extra | static["htmlpairsStatic"]
    htmlelements = (extra | static["htmlelementsStatic"]) - remove

    return {
        "htmlpairs": htmlpairs,
        "htmlsingle": static["htmlsingle"],
        "htmlsingleonly": static["htmlsingleonly"],
        "htmlnest": static["htmlnest"],
        "tabletags": static["tabletags"],
        "htmllist": static["htmllist"],
        "listtags": static["listtags"],
        "htmlsingleallowed": static["htmlsingleallowed"],
        "htmlelements": htmlelements,
    }


# --- Removing tags -------------------------------------------------------------------------------------------------

def remove_html_tags(text: str, process_callback: Optional[Callable[[str, Any], str]] = None, args: Any = None,
                     extratags: Optional[Iterable[str]] = None, removetags: Optional[Iterable[str]] = None,
                     *, config: Config = DEFAULT) -> str:
    """Cleans up HTML, removes dangerous tags and attributes, and removes HTML comments; BEWARE there may be
    unmatched HTML tags in the result.

    @deprecated since 1.38. Use ::removeSomeTags(), which always gives balanced/tidy HTML.
    """
    return internal_remove_html_tags(text, process_callback, args, extratags, removetags, config=config)


def internal_remove_html_tags(text: str, process_callback: Optional[Callable[[str, Any], str]] = None,
                              args: Any = None, extratags: Optional[Iterable[str]] = None,
                              removetags: Optional[Iterable[str]] = None, *, config: Config = DEFAULT) -> str:
    """Cleans up HTML, removes dangerous tags and attributes, and removes HTML comments; BEWARE there may be
    unmatched HTML tags in the result.

    @note Callers are recommended to use ``::removeSomeTags()`` instead of this method. ``Sanitizer::removeSomeTags()``
    is safer and will always return well-formed HTML; however, it is significantly slower (especially for short
    strings where setup costs predominate). This method is for internal use by the legacy parser where we know the
    result will be cleaned up in a subsequent tidy pass.

    ``process_callback``: callback to do any variable or parameter replacements in HTML attribute values. This
    argument should be considered @internal. PHP passes the attribute text by reference; here the callback gets
    ``(params, args)`` and returns the new text.
    ``args``: arguments for the processing callback. ``extratags``: for any extra tags to include.
    ``removetags``: for any tags (default or extra) to exclude.
    """
    tag_data = get_recognized_tag_data(extratags, removetags, config=config)
    htmlsingle = tag_data["htmlsingle"]
    htmlsingleonly = tag_data["htmlsingleonly"]
    htmlelements = tag_data["htmlelements"]

    # Remove HTML comments
    text = remove_html_comments(text)
    bits = text.split("<")
    out = [bits.pop(0).replace(">", "&gt;")]

    # this might be possible using remex tidy itself
    for x in bits:
        regs = _ELEMENT_BITS_REGEX.match(x)
        if regs:
            slash, t, params, brace, rest = regs.groups()

            badtag = False
            t = _php_strtolower(t)
            if t in htmlelements:
                if callable(process_callback):
                    params = process_callback(params, args)

                if brace == "/>" and not (t in htmlsingle or t in htmlsingleonly):
                    # Remove the self-closing slash, to be consistent with HTML5 semantics. T134423
                    brace = ">"
                if not _validate_tag(params, t):
                    badtag = True

                newparams = fix_tag_attributes(params, t, config=config)
                if not badtag:
                    if brace == "/>" and t not in htmlsingleonly:
                        # Interpret self-closing tags as empty tags even when HTML 5 would interpret them as start
                        # tags. Such input is commonly seen on Wikimedia wikis with this intention.
                        brace = f"></{t}>"

                    rest = rest.replace(">", "&gt;")
                    out.append(f"<{slash}{t}{newparams}{brace}{rest}")
                    continue
        out.append("&lt;" + x.replace(">", "&gt;"))
    return "".join(out)


def remove_some_tags(text: str, *, extra_tags: Optional[Iterable[str]] = None,
                     remove_tags: Optional[Iterable[str]] = None,
                     attr_callback: Optional[Callable[..., dict[str, str]]] = None,
                     attr_callback_args: Iterable[Any] = (), config: Config = DEFAULT) -> str:
    """Cleans up HTML, removes dangerous tags and attributes, and removes HTML comments; the result will always be
    balanced and tidy HTML.

    Options (PHP: the $options array): ``extra_tags`` any extra tags to allow; ``remove_tags`` any tags (default or
    extra) to exclude; ``attr_callback`` callback to do any variable or parameter replacements in HTML attribute
    values before further cleanup (gets the attribute dict and ``*attr_callback_args``, returns a dict); should be
    considered @internal and not for external use. Returns the cleaned up HTML. @since 1.38

    APPROXIMATION of RemexHtml, to be replaced when Remex is ported: MediaWiki tokenizes with RemexHtml and builds
    an HTML5 tree from the result. Here Python's html.parser tokenizes, and a small tree builder covers the common
    HTML5 rules (implied end tags of p/li/dd/dt/headings, end tags without a matching open element, implicit
    tbody/tr, table parts outside a table); it does not do the adoption agency algorithm, the reconstruction of
    formatting elements or foster parenting.
    """
    # This disallows HTML5-style "missing trailing semicolon" attributes
    # In wikitext "clean&copy" does *not* contain an entity.
    text = normalize_char_references(text)

    tag_data = get_recognized_tag_data(extra_tags, remove_tags, config=config)
    # Use RemexHtml to tokenize $text and remove the barred tags
    tree_builder = _TreeBuilder()
    remover = _RemexRemoveTagHandler(tree_builder, tag_data, attr_callback, list(attr_callback_args), config)
    remover.run(text)
    return tree_builder.serialize()


def remove_html_comments(text: str) -> str:
    """Remove '<!--', '-->', and everything between. To avoid leaving blank lines, when a comment is both preceded
    and followed by a newline (ignoring spaces), trim leading and trailing spaces and one of the newlines."""
    while (start := text.find("<!--")) != -1:
        end = text.find("-->", start + 4)
        if end == -1:
            # Unterminated comment; bail out
            break

        end += 3

        # Trim space and newline if the comment is both preceded and followed by a newline
        space_start = max(start - 1, 0)
        space_len = end - space_start
        while text[space_start:space_start + 1] == " " and space_start > 0:
            space_start -= 1
            space_len += 1
        while text[space_start + space_len:space_start + space_len + 1] == " ":
            space_len += 1
        if (text[space_start:space_start + 1] == "\n"
                and text[space_start + space_len:space_start + space_len + 1] == "\n"):
            # Remove the comment, leading and trailing spaces, and leave only one newline.
            text = text[:space_start] + "\n" + text[space_start + space_len + 1:]
        else:
            # Remove just the comment.
            text = text[:start] + text[end:]
    return text


def _validate_tag(params: str, element: str) -> bool:
    """Takes attribute names and values for a tag and the tag name and validates that the tag is allowed to be
    present. This DOES NOT validate the attributes, nor does it validate the tags themselves. This method only
    handles the special circumstances where we may want to allow a tag within content but ONLY when it has specific
    attributes set.

    @see RemexRemoveTagHandler::validateTag()
    """
    return _validate_tag_attribs(decode_tag_attributes(params), element)


def validate_tag(params: str, element: str) -> bool:
    """Public name of Sanitizer::validateTag() (private in PHP)."""
    return _validate_tag(params, element)


def _validate_tag_attribs(params: Mapping[str, str], element: str) -> bool:
    if element == "meta" or element == "link":
        if "itemprop" not in params:
            # <meta> and <link> must have an itemprop="" otherwise they are not valid or safe in content
            return False
        if element == "meta" and "content" not in params:
            # <meta> must have a content="" for the itemprop
            return False
        if element == "link" and "href" not in params:
            # <link> must have an associated href=""
            return False

    return True


# --- Attributes ----------------------------------------------------------------------------------------------------

def validate_tag_attributes(attribs: Mapping[str, str], element: str, *, config: Config = DEFAULT) -> dict[str, str]:
    """Take an array of attribute names and values and normalize or discard illegal values for the given element
    type.

    - Discards attributes not allowed for the given element
    - Unsafe style attributes are discarded
    - Invalid id attributes are re-encoded

    @todo Check for legal values where the DTD limits things.
    @todo Check for unique id attribute :P
    """
    return validate_attributes(attribs, attributes_allowed_internal(element), config=config)


# PHP: '|^data-[^:= \t\r\n/>\0_＿]*$|i' without /u, so the class holds the three bytes of '＿' (EF BC BF) one by
# one: any character whose UTF-8 form contains one of them is refused too. Matched on the UTF-8 bytes to keep that.
_DATA_ATTRIBUTE = re.compile(b"^data-[^:= \\t\\r\\n/>\\x00_\\xef\\xbc\\xbf]*$", re.I)


def validate_attributes(attribs: Mapping[str, str], allowed: Union[Mapping[str, Any], Iterable[str]], *,
                        config: Config = DEFAULT) -> dict[str, str]:
    """Take an array of attribute names and values and normalize or discard illegal values.

    - Discards attributes not on the given list
    - Unsafe style attributes are discarded
    - Invalid id attributes are re-encoded

    ``allowed``: list of allowed attribute names, as an associative array where keys give valid attribute names
    (since 1.34). Before 1.35, passing a sequential array of valid attribute names was permitted but that is now
    deprecated.

    @todo Check for legal values where the DTD limits things.
    @todo Check for unique id attribute :P
    """
    if not isinstance(allowed, Mapping):
        # Calling this function with a sequential array is deprecated. For now just convert it.
        allowed = dict.fromkeys(allowed, True)
    href_exp = _href_exp(tuple(config.url_protocols))

    out: dict[str, str] = {}
    for attribute, value in attribs.items():
        # Allow XML namespace declaration to allow RDFa
        if _XMLNS_ATTRIBUTE_PATTERN.search(attribute):
            if not _EVIL_URI_PATTERN.search(value):
                out[attribute] = value

            continue

        # Allow any attribute beginning with "data-"
        # However:
        # * Disallow data attributes used by MediaWiki code
        # * Ensure that the attribute is not namespaced by banning
        #   colons.
        # * Ensure attribute name will be accepted by the HTML
        #   parser; see
        #   https://github.com/whatwg/dom/issues/849#issuecomment-1007541209
        # * Underscore and double-wide underscore (U+FF3F) is disallowed
        #   here (but not in Parsoid): T407131
        if ((not _DATA_ATTRIBUTE.search(attribute.encode("utf-8", "surrogatepass"))
             and attribute not in allowed) or is_reserved_data_attribute(attribute)):
            continue

        # Strip javascript "expression" from stylesheets.
        # https://msdn.microsoft.com/en-us/library/ms537634.aspx
        if attribute == "style":
            value = check_css(value)

        # Escape HTML id attributes
        if attribute == "id":
            value = escape_id_for_attribute(value, ID_PRIMARY, config=config)

        # Escape HTML id reference lists
        if attribute in ("aria-describedby", "aria-flowto", "aria-labelledby", "aria-owns"):
            value = _escape_id_reference_list_internal(value, config)

        # RDFa and microdata properties allow URLs, URIs and/or CURIs.
        if attribute in (
            "rel", "rev",
            # RDFa
            "about", "property", "resource", "datatype", "typeof",
            # HTML5 microdata
            "itemid", "itemprop", "itemref", "itemscope", "itemtype",
        ):
            # Paranoia. Allow "simple" values but suppress javascript
            if _EVIL_URI_PATTERN.search(value):
                continue

        # NOTE: even though elements using href/src are not allowed directly, supply
        #       validation code that can be used by tag hook handlers, etc
        if attribute in ("href", "src", "poster"):
            if not href_exp.search(value):
                continue  # drop any href or src attributes not using an allowed protocol.
                # NOTE: this also drops all relative URLs

        if attribute == "tabindex" and value != "0":
            # Only allow tabindex of 0, which is useful for accessibility.
            continue

        # If this attribute was previously set, override it.
        # Output should only have one attribute of each name.
        out[attribute] = value

    # itemtype, itemid, itemref don't make sense without itemscope
    if "itemscope" not in out:
        out.pop("itemtype", None)
        out.pop("itemid", None)
        out.pop("itemref", None)
    # TODO: Strip itemprop if we aren't descendants of an itemscope or pointed to by an itemref.

    return out


_RESERVED_DATA_ATTRIBUTE = re.compile(r"^data-(ooui|mw|parsoid)", re.I | re.ASCII)


def is_reserved_data_attribute(attr: str) -> bool:
    """Given an attribute name, checks whether it is a reserved data attribute (such as data-mw-foo) which is
    unavailable to user-generated HTML so MediaWiki core and extension code can safely use it to communicate with
    frontend code."""
    # data-ooui is reserved for ooui.
    # data-mw and data-parsoid are reserved for parsoid.
    # data-mw-<name here> is reserved for extensions (or core) if
    # they need to communicate some data to the client and want to be
    # sure that it isn't coming from an untrusted user.
    # We ignore the possibility of namespaces since user-generated HTML
    # can't use them anymore.
    return bool(_RESERVED_DATA_ATTRIBUTE.search(attr))


def merge_attributes(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """Merge two sets of HTML attributes. Conflicting items in the second set will override those in the first,
    except for 'class' attributes which will be combined (if they're both strings).

    @todo implement merging for other attributes such as style
    """
    out = {**a, **b}
    if (isinstance(a.get("class"), str) and isinstance(b.get("class"), str)
            and a["class"] != b["class"]):
        classes = [c for c in re.split(r"\s+", f"{a['class']} {b['class']}", flags=re.ASCII) if c]
        out["class"] = " ".join(dict.fromkeys(classes))  # array_unique keeps the first of each
    return out


# --- CSS -----------------------------------------------------------------------------------------------------------

# Decode escape sequences and line continuation. See the grammar in the CSS 2 spec, appendix D.
_CSS_DECODE_REGEX = re.compile(r"""\\
    (?:
        (\n|\r\n|\r|\f) |  # 1. Line continuation
        ([0-9A-Fa-f]{1,6})[\x20\t\r\n\f]? |  # 2. character number
        (.) | # 3. backslash cancelling special meaning
        () | # 4. backslash at end of string
    )""", re.X)
_CSS_SINGLE_COMMENT = re.compile(r"^\s*/\*[^*/]*\*/\s*$", re.ASCII)
_CSS_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_CSS_INSECURE = re.compile(r"""expression
        | filter\s*:
        | accelerator\s*:
        | -o-link\s*:
        | -o-link-source\s*:
        | -o-replace\s*:
        | url\s*\(
        | image\s*\(
        | image-set\s*\(
        | attr\s*\([^)]+[\s,]+url
    """, re.I | re.X | re.ASCII)


def normalize_css(value: str) -> str:
    """Normalize CSS into a format we can easily search for hostile input
     - decode character references
     - decode escape sequences
     - remove comments, unless the entire value is one single comment
    """
    # Decode character references like &#123;
    value = decode_char_references(value)

    # Decode escape sequences and line continuation
    # See the grammar in the CSS 2 spec, appendix D.
    # This has to be done AFTER decoding character references.
    # This means it isn't possible for this function to return
    # unsanitized escape sequences. It is possible to manufacture
    # input that contains character references that decode to
    # escape sequences that decode to character references, but
    # it's OK for the return value to contain character references
    # because the caller is supposed to escape those anyway.
    value = _CSS_DECODE_REGEX.sub(_css_decode_callback, value)

    # Let the value through if it's nothing but a single comment, to
    # allow other functions which may reject it to pass some error
    # message through.
    if not _CSS_SINGLE_COMMENT.search(value):
        # Remove any comments; IE gets token splitting wrong
        # This must be done AFTER decoding character references and
        # escape sequences, because those steps can introduce comments
        # This step cannot introduce character references or escape
        # sequences, because it replaces comments with spaces rather
        # than removing them completely.
        value = delimiter_replace("/*", "*/", " ", value)

        # Remove anything after a comment-start token, to guard against
        # incorrect client implementations.
        comment_pos = value.find("/*")
        if comment_pos != -1:
            value = value[:comment_pos]

    return value


def check_css(value: str) -> str:
    """Pick apart some CSS and check it for forbidden or unsafe structures. Returns a sanitized string. This
    sanitized string will have character references and escape sequences decoded and comments stripped (unless it
    is itself one valid comment, in which case the value will be passed through). If the input is just too evil,
    only a comment complaining about evilness will be returned.

    Currently URL references, 'expression', 'tps' are forbidden.

    NOTE: Despite the fact that character references are decoded, the returned string may contain character
    references given certain clever input strings. These character references must be escaped before the return
    value is embedded in HTML.
    """
    value = normalize_css(value)

    # Reject problematic keywords and control characters
    if _CSS_CONTROL_CHARS.search(value) or UTF8_REPLACEMENT in value:
        return "/* invalid control char */"
    elif _CSS_INSECURE.search(value):
        return "/* insecure input */"
    return value


def _css_decode_callback(matches: re.Match[str]) -> str:
    if matches.group(1) is not None:
        # Line continuation
        return ""
    elif matches.group(2) is not None:
        char = _codepoint_to_utf8(int(matches.group(2), 16))
    elif matches.group(3) is not None:
        char = matches.group(3)
    else:
        char = "\\"
    if char in ("\n", '"', "'", "\\"):
        # These characters need to be escaped in strings
        # Clean up the escape sequence to avoid parsing errors by clients
        return "\\%x " % ord(char)
    else:
        # Decode unnecessary escape
        return char


# --- Encoding attributes -------------------------------------------------------------------------------------------

def fix_tag_attributes(text: str, element: str, sorted: bool = False, *,  # noqa: A002 (PHP's name)
                       config: Config = DEFAULT) -> str:
    """Take a tag soup fragment listing an HTML element's attributes and normalize it to well-formed XML,
    discarding unwanted attributes. Output is safe for further wikitext processing, with escaping of values that
    could trigger problems.

    - Normalizes attribute names to lowercase
    - Discards attributes not allowed for the given element
    - Turns broken or invalid entities into plaintext
    - Double-quotes all attribute values
    - Attributes without values are given the name as attribute
    - Double attributes are discarded
    - Unsafe style attributes are discarded
    - Prepends space if there are attributes.
    - (Optionally) Sorts attributes by name.

    ``sorted``: whether to sort the attributes (default: false)
    """
    if _php_trim(text) == "":
        return ""

    decoded = decode_tag_attributes(text)
    stripped = validate_tag_attributes(decoded, element, config=config)

    if sorted:
        # ksort(): attribute names are non-numeric strings, compared byte-wise (= by code point)
        stripped = {key: stripped[key] for key in _builtin_sorted(stripped)}

    return safe_encode_tag_attributes(stripped, config=config)


_builtin_sorted = sorted


def encode_attribute(text: str) -> str:
    """Encode an attribute value for HTML output. Returns HTML-encoded text fragment."""
    enc_value = _htmlspecialchars(text, quotes=True)

    # Whitespace is normalized during attribute decoding,
    # so if we've been passed non-spaces we must encode them
    # ahead of time or they won't be preserved.
    enc_value = php_strtr(enc_value, {
        "\n": "&#10;",
        "\r": "&#13;",
        "\t": "&#9;",
    })

    return enc_value


_FRENCH_SPACE = re.compile(r" (?=[?:;!%»›](?!\w))")
_FRENCH_SPACE_GUILLEMET = re.compile(r"([«‹]) ")


def armor_french_spaces(text: str, space: str = "&#160;") -> str:
    """Armor French spaces with a replacement character

    ``space``: space character for the French spaces, defaults to '&#160;'. Returns armored text. @since 1.32

    (PHP escapes $ and \\ in ``space`` to use it as a preg_replace replacement; a replacement function inserts it
    literally here, which is what that escaping is for.)
    """
    # French spaces, last one Guillemet-left
    # only if it isn't followed by a word character.
    text = _FRENCH_SPACE.sub(lambda m: space, text)
    # French spaces, Guillemet-right
    return _FRENCH_SPACE_GUILLEMET.sub(lambda m: m.group(1) + space, text)


def safe_encode_attribute(text: str, *, config: Config = DEFAULT) -> str:
    """Encode an attribute value for HTML tags, with extra armoring against further wiki processing. Returns
    HTML-encoded text fragment."""
    enc_value = encode_attribute(text)

    # Templates and links may be expanded in later parsing,
    # creating invalid or dangerous output. Suppress this.
    enc_value = php_strtr(enc_value, {
        "<": "&lt;",  # This should never happen,
        ">": "&gt;",  # we've received invalid input
        '"': "&quot;",  # which should have been escaped.
        "{": "&#123;",
        "}": "&#125;",  # prevent unpaired language conversion syntax
        "[": "&#91;",
        "]": "&#93;",
        "''": "&#39;&#39;",
        "ISBN": "&#73;SBN",
        "RFC": "&#82;FC",
        "PMID": "&#80;MID",
        "|": "&#124;",
        "_": "&#95;",
        "＿": "&#xFF3F;",  # Japanese magic words
    })

    # Stupid hack
    enc_value = _protocols_hack_regex(tuple(config.url_protocols)).sub(
        lambda m: m.group(1).replace(":", "&#58;"), enc_value)
    return enc_value


# --- Ids -----------------------------------------------------------------------------------------------------------

def _fragment_mode(config: Config, mode: int) -> Optional[str]:
    """isset( $wgFragmentMode[$mode] ) ? $wgFragmentMode[$mode] : null"""
    fragment_mode = config.fragment_mode
    if 0 <= mode < len(fragment_mode):
        return fragment_mode[mode]
    return None


def escape_id_for_attribute(id_: str, mode: int = ID_PRIMARY, *,
                            config: Config = DEFAULT) -> Union[str, Literal[False]]:
    """Given a section name or other user-generated or otherwise unsafe string, escapes it to be a valid HTML id
    attribute.

    WARNING: The output of this function is not guaranteed to be HTML safe, so be sure to use proper escaping.

    ``mode``: one of ID_* constants, specifying whether the primary or fallback encoding should be used. Returns the
    escaped ID or false if fallback encoding is requested but it's not configured. Reads $wgFragmentMode.
    @since 1.30
    """
    internal_mode = _fragment_mode(config, mode)
    if internal_mode is None:
        if mode == ID_PRIMARY:
            # (PHP: UnexpectedValueException)
            raise ValueError("$wgFragmentMode is configured with no primary mode")
        return False

    return escape_id_internal(id_, internal_mode)


def escape_id_for_link(id_: str, *, config: Config = DEFAULT) -> str:
    """Given a section name or other user-generated or otherwise unsafe string, escapes it to be a valid URL
    fragment.

    WARNING: The output of this function is not guaranteed to be HTML safe, so be sure to use proper escaping.
    Reads $wgFragmentMode. @since 1.30
    """
    mode = _fragment_mode(config, ID_PRIMARY)
    if mode is None:
        # (PHP: UnexpectedValueException)
        raise ValueError("$wgFragmentMode is configured with no primary mode")

    id_ = _escape_id_internal_url(id_, mode)

    return id_


def escape_id_for_external_interwiki(id_: str, *, config: Config = DEFAULT) -> str:
    """Given a section name or other user-generated or otherwise unsafe string, escapes it to be a valid URL
    fragment for external interwikis. Reads $wgExternalInterwikiFragmentMode. @since 1.30"""
    id_ = _escape_id_internal_url(id_, config.external_interwiki_fragment_mode)

    return id_


def _escape_id_internal_url(id_: str, mode: str) -> str:
    """Do percent encoding of percent signs for href (but not id) attributes

    @since 1.35 @see https://phabricator.wikimedia.org/T238385
    ``mode``: one of modes from $wgFragmentMode
    """
    id_ = escape_id_internal(id_, mode)
    if mode == "html5":
        id_ = re.sub(r"%([a-fA-F0-9]{2})", r"%25\1", id_)
    return id_


def escape_id_internal(id_: str, mode: str) -> str:
    """Helper for escapeIdFor*() functions. Performs most of the actual escaping. (Private in PHP.)

    ``mode``: one of modes from $wgFragmentMode
    """
    # Truncate overly-long IDs.  This isn't an HTML limit, it's just
    # griefer protection. [T251506]
    id_ = id_[:1024]  # mb_substr: code points

    if mode == "html5":
        # html5 spec says ids must not have any of the following:
        # U+0009 TAB, U+000A LF, U+000C FF, U+000D CR, or U+0020 SPACE
        # In practice, in wikitext, only tab, LF, CR (and SPACE) are
        # possible using either Lua or html entities.
        for ch in ("\t", "\n", "\f", "\r", " "):
            id_ = id_.replace(ch, "_")
    elif mode == "legacy":
        # This corresponds to 'noninitial' mode of the former escapeId()
        id_ = _php_urlencode(id_.replace(" ", "_"))
        id_ = php_strtr(id_, {"%3A": ":", "%": "."})
    else:
        # (PHP: InvalidArgumentException)
        raise ValueError(f"Invalid mode '{mode}' passed to 'Sanitizer::escapeIdInternal")

    return id_


def escape_id_reference_list(reference_string: str, *, config: Config = DEFAULT) -> str:
    """Given a string containing a space delimited list of ids, escape each id to match ids escaped by the
    escapeIdForAttribute() function.

    @since 1.27 @deprecated since 1.36. Unused outside this class, will be made private.
    """
    return _escape_id_reference_list_internal(reference_string, config)


def _escape_id_reference_list_internal(reference_string: str, config: Config = DEFAULT) -> str:
    """Given a string containing a space delimited list of ids, escape each id to match ids escaped by the
    escapeIdForAttribute() function."""
    # Explode the space delimited list string into an array of tokens
    references = [r for r in re.split(r"\s+", reference_string, flags=re.ASCII) if r]

    # Escape each token as an id
    references = [escape_id_for_attribute(ref, config=config) for ref in references]

    # Merge the array back to a space delimited list string
    # If the array is empty, the result will be an empty string ('')
    return " ".join(references)


_ESCAPE_CLASS = re.compile(r"""(^[0-9\-])|[\x00-\x20!"#$%&'()*+,./:;<=>?@\[\]^`{|}~]|\xa0""")


def escape_class(class_: str) -> str:
    """Given a value, escape it so that it can be used as a CSS class and return it.

    @todo For extra validity, input should be validated UTF-8.
    @see https://www.w3.org/TR/CSS21/syndata.html Valid characters/format
    """
    # Convert ugly stuff to underscores and kill underscores in ugly places
    # (PHP matches the bytes \xC2\xA0, i.e. U+00A0.)
    class_ = _ESCAPE_CLASS.sub("_", class_)
    class_ = re.sub(r"_+", "_", class_)
    return class_.rstrip("_")


def escape_combining_char(html: str) -> str:
    return php_strtr(html, {
        "̸": "&#x338;",  # T387130
    })


def escape_html_allow_entities(html: str) -> str:
    """Given HTML input, escape with htmlspecialchars but un-escape entities. This allows (generally harmless)
    entities like &#160; to survive."""
    html = decode_char_references(html)
    # It seems wise to escape ' as well as ", as a matter of course.  Can't
    # hurt. Use ENT_SUBSTITUTE so that incorrectly truncated multibyte characters
    # don't cause the entire string to disappear.
    html = _htmlspecialchars(html, quotes=True)
    return escape_combining_char(html)


# --- Decoding attributes -------------------------------------------------------------------------------------------

def decode_tag_attributes(text: str) -> dict[str, str]:
    """Return an associative array of attribute names and values from a partial tag string. Attribute names are
    forced to lowercase, character references are decoded to UTF-8 text."""
    if _php_trim(text) == "":
        return {}

    attribs: dict[str, str] = {}
    for pair in _ATTRIBS_REGEX.finditer(text):
        attribute = _php_strtolower(pair.group(1))

        # Filter attribute names with unacceptable characters
        if not _is_attrib_name(attribute):
            continue

        value = _get_tag_attribute_callback(pair)

        # Normalize whitespace
        value = re.sub(r"[\t\r\n ]+", " ", value)
        value = _php_trim(value)

        # Decode character references
        attribs[attribute] = decode_char_references(value)
    return attribs


def safe_encode_tag_attributes(assoc_array: Mapping[str, str], *, config: Config = DEFAULT) -> str:
    """Build a partial tag string from an associative array of attribute names and values as returned by
    decodeTagAttributes."""
    attribs = []
    for attribute, value in assoc_array.items():
        enc_attribute = _htmlspecialchars(attribute, quotes=False)
        enc_value = safe_encode_attribute(value, config=config)

        attribs.append(f'{enc_attribute}="{enc_value}"')
    return " " + " ".join(attribs) if attribs else ""


def _get_tag_attribute_callback(set_: re.Match[str]) -> str:
    """Pick the appropriate attribute value from a match set from the attribs regex matches."""
    if set_.group(5) is not None:
        # No quotes.
        return set_.group(5)
    elif set_.group(4) is not None:
        # Single-quoted
        return set_.group(4)
    elif set_.group(3) is not None:
        # Double-quoted
        return set_.group(3)
    elif set_.group(2) is None:
        # In XHTML, attributes must have a value so return an empty string.
        # See "Empty attribute syntax",
        # https://www.w3.org/TR/html5/syntax.html#syntax-attribute-name
        return ""
    else:
        raise RuntimeError("Tag conditions not met. This should never happen and is a bug.")


def _normalize_whitespace(text: str) -> str:
    normalized = re.sub(r"[ \r\n\t]+", " ", text)
    return _php_trim(normalized)


def normalize_section_name_whitespace(section: str) -> str:
    """Normalizes whitespace in a section name, such as might be returned by Parser::stripSectionName(), for use in
    the id's that are used for section links."""
    normalized = re.sub(r"[ _]+", " ", section)
    return _php_trim(normalized)


# --- Character references ------------------------------------------------------------------------------------------

def normalize_char_references(text: str) -> str:
    """Ensure that any entities and character references are legal for XML and XHTML specifically. Any stray bits
    will be &amp;-escaped to result in a valid text fragment.

    a. named char refs can only be &lt; &gt; &amp; &quot;, others are
      numericized (this way we're well-formed even without a DTD)
    b. any numeric char refs must be legal chars, not invalid or forbidden
    c. use lower cased "&#x", not "&#X"
    d. fix or reject non-valid attributes

    @internal
    """
    return _CHAR_REFS_REGEX.sub(_normalize_char_references_callback, text)


def _normalize_char_references_callback(matches: re.Match[str]) -> str:
    ret = None
    if matches.group(1):
        ret = _normalize_entity(matches.group(1))
    elif matches.group(2):
        ret = _dec_char_reference(matches.group(2))
    elif matches.group(3):
        ret = _hex_char_reference(matches.group(3))
    if ret is None:
        return _htmlspecialchars(matches.group(0), quotes=False)
    else:
        return ret


def _normalize_entity(name: str) -> str:
    """If the named entity is defined in HTML5 return the equivalent numeric entity reference (except for the core
    &lt; &gt; &amp; &quot;). If the entity is a MediaWiki-specific alias, returns the HTML equivalent. Otherwise,
    returns HTML-escaped text of pseudo-entity source (eg &amp;foo;)

    ``name``: semicolon-terminated name
    """
    if name in _MW_ENTITY_ALIASES:
        # Non-standard MediaWiki-specific entities
        return "&" + _MW_ENTITY_ALIASES[name]
    elif name in ("lt;", "gt;", "amp;", "quot;"):
        # Keep these in word form
        return f"&{name}"
    elif name in _NAMED_ENTITY_TRANSLATIONS:
        # Beware: some entities expand to more than 1 codepoint
        return "".join(f"&#{ord(c)};" for c in _NAMED_ENTITY_TRANSLATIONS[name])
    else:
        return f"&amp;{name}"


def _dec_char_reference(codepoint: str) -> Optional[str]:
    point = int(codepoint)
    if _validate_codepoint(point):
        return "&#%d;" % point
    else:
        return None


def _hex_char_reference(codepoint: str) -> Optional[str]:
    point = int(codepoint, 16)
    if _validate_codepoint(point):
        return "&#x%x;" % point
    else:
        return None


def _validate_codepoint(codepoint: int) -> bool:
    """Returns true if a given Unicode codepoint is a valid character in both HTML5 and XML."""
    # U+000C is valid in HTML5 but not allowed in XML.
    # U+000D is valid in XML but not allowed in HTML5.
    # U+007F - U+009F are disallowed in HTML5 (control characters).
    return (codepoint == 0x09
            or codepoint == 0x0a
            or 0x20 <= codepoint <= 0x7e
            or 0xa0 <= codepoint <= 0xd7ff
            or 0xe000 <= codepoint <= 0xfffd
            or 0x10000 <= codepoint <= 0x10ffff)


def decode_char_references(text: str) -> str:
    """Decode any character references, numeric or named entities, in the text and return a UTF-8 string."""
    return _CHAR_REFS_REGEX.sub(_decode_char_references_callback, text)


def decode_char_references_and_normalize(text: str) -> str:
    """Decode any character references, numeric or named entities, in the next and normalize the resulting string.
    (T16952)

    This is useful for page titles, not for text to be displayed, MediaWiki allows HTML entities to escape
    normalization as a feature.

    ``text``: already normalized, containing entities. Returns the text still normalized, without entities.

    (The content language's normalize() is UtfNormal\\Validator::cleanUp(), i.e. NFC, for English; the languages
    with extra normalization tables, such as Arabic and Malayalam, are not reproduced.)
    """
    text, count = _CHAR_REFS_REGEX.subn(_decode_char_references_callback, text)

    if count:
        return unicodedata.normalize("NFC", text)
    else:
        return text


def _decode_char_references_callback(matches: re.Match[str]) -> str:
    if matches.group(1):
        return _decode_entity(matches.group(1))
    elif matches.group(2):
        return _decode_char(int(matches.group(2)))
    elif matches.group(3):
        return _decode_char(int(matches.group(3), 16))
    # Last case should be an ampersand by itself
    return matches.group(0)


def _decode_char(codepoint: int) -> str:
    """Return UTF-8 string for a codepoint if that is a valid character reference, otherwise U+FFFD REPLACEMENT
    CHARACTER. @internal"""
    if _validate_codepoint(codepoint):
        return _codepoint_to_utf8(codepoint)
    else:
        return UTF8_REPLACEMENT


def _decode_entity(name: str) -> str:
    """If the named entity is defined in HTML5 return the UTF-8 encoding of that character. Otherwise, returns
    pseudo-entity source (eg "&foo;")

    ``name``: semicolon-terminated entity name
    """
    # These are MediaWiki-specific entities, not in the HTML standard
    if name in _MW_ENTITY_ALIASES:
        name = _MW_ENTITY_ALIASES[name]
    trans = _NAMED_ENTITY_TRANSLATIONS.get(name)
    return trans if trans is not None else f"&{name}"


# --- Allowed attributes --------------------------------------------------------------------------------------------

def attributes_allowed_internal(element: str) -> Mapping[str, bool]:
    """Fetch the list of acceptable attributes for a given element name.

    Returns an associative array where keys are acceptable attribute names (read-only here). (Private in PHP.)
    """
    return _setup_attributes_allowed_internal().get(element, _EMPTY_MAPPING)


_EMPTY_MAPPING: Mapping[str, bool] = MappingProxyType({})


@functools.lru_cache(maxsize=1)
def _setup_attributes_allowed_internal() -> dict[str, Mapping[str, bool]]:
    """Foreach array key (an allowed HTML element), return an array of allowed attributes.

    Returns an associative array: keys are HTML element names; values are associative arrays where the keys are
    allowed attribute names.
    """
    # For lookup efficiency flip each attributes array so the keys are
    # the valid attributes.
    def merge(a: Mapping[str, bool], b: list[str], c: Iterable[str] = ()) -> Mapping[str, bool]:
        return MappingProxyType({**a, **dict.fromkeys(b, True), **dict.fromkeys(c, True)})

    common = merge({}, [
        # HTML
        "id",
        "class",
        "style",
        "lang",
        "dir",
        "title",
        "tabindex",

        # WAI-ARIA
        "aria-describedby",
        "aria-flowto",
        "aria-hidden",
        "aria-label",
        "aria-labelledby",
        "aria-owns",
        "role",

        # RDFa
        # These attributes are specified in section 9 of
        # https://www.w3.org/TR/2008/REC-rdfa-syntax-20081014
        "about",
        "property",
        "resource",
        "datatype",
        "typeof",

        # Microdata. These are specified by
        # https://html.spec.whatwg.org/multipage/microdata.html#the-microdata-model
        "itemid",
        "itemprop",
        "itemref",
        "itemscope",
        "itemtype",
    ])

    block = merge(common, ["align"])

    tablealign = ["align", "valign"]
    tablecell = [
        "abbr",
        "axis",
        "headers",
        "scope",
        "rowspan",
        "colspan",
        "nowrap",  # deprecated
        "width",  # deprecated
        "height",  # deprecated
        "bgcolor",  # deprecated
    ]

    # Numbers refer to sections in HTML 4.01 standard describing the element.
    # See: https://www.w3.org/TR/html4/
    allowed = {
        # 7.5.4
        "div": block,
        "center": common,  # deprecated
        "span": common,

        # 7.5.5
        "h1": block,
        "h2": block,
        "h3": block,
        "h4": block,
        "h5": block,
        "h6": block,

        # 7.5.6
        # address

        # 8.2.4
        "bdo": common,

        # 9.2.1
        "em": common,
        "strong": common,
        "cite": common,
        "dfn": common,
        "code": common,
        "samp": common,
        "kbd": common,
        "var": common,
        "abbr": common,
        # acronym

        # 9.2.2
        "blockquote": merge(common, ["cite"]),
        "q": merge(common, ["cite"]),

        # 9.2.3
        "sub": common,
        "sup": common,

        # 9.3.1
        "p": block,

        # 9.3.2
        "br": merge(common, ["clear"]),

        # https://www.w3.org/TR/html5/text-level-semantics.html#the-wbr-element
        "wbr": common,

        # 9.3.4
        "pre": merge(common, ["width"]),

        # 9.4
        "ins": merge(common, ["cite", "datetime"]),
        "del": merge(common, ["cite", "datetime"]),

        # 10.2
        "ul": merge(common, ["type"]),
        "ol": merge(common, ["type", "start", "reversed"]),
        "li": merge(common, ["type", "value"]),

        # 10.3
        "dl": common,
        "dd": common,
        "dt": common,

        # 11.2.1
        "table": merge(common,
                       ["summary", "width", "border", "frame",
                        "rules", "cellspacing", "cellpadding",
                        "align", "bgcolor",
                        ]),

        # 11.2.2
        "caption": block,

        # 11.2.3
        "thead": common,
        "tfoot": common,
        "tbody": common,

        # 11.2.4
        "colgroup": merge(common, ["span"]),
        "col": merge(common, ["span"]),

        # 11.2.5
        "tr": merge(common, ["bgcolor"], tablealign),

        # 11.2.6
        "td": merge(common, tablecell, tablealign),
        "th": merge(common, tablecell, tablealign),

        # 12.2
        # NOTE: <a> is not allowed directly, but this list of allowed
        # attributes is used from the Parser object
        "a": merge(common, ["href", "rel", "rev"]),  # rel/rev esp. for RDFa

        # 13.2
        # Not usually allowed, but may be used for extension-style hooks
        # such as <math> when it is rasterized, or if $wgAllowImageTag is
        # true
        "img": merge(common, ["alt", "src", "width", "height", "srcset"]),
        # Attributes for A/V tags added in T163583 / T133673
        "audio": merge(common, ["controls", "preload", "width", "height"]),
        "video": merge(common, ["poster", "controls", "preload", "width", "height"]),
        "source": merge(common, ["type", "src"]),
        "track": merge(common, ["type", "src", "srclang", "kind", "label"]),

        # 15.2.1
        "tt": common,
        "b": common,
        "i": common,
        "big": common,
        "small": common,
        "strike": common,
        "s": common,
        "u": common,

        # 15.2.2
        "font": merge(common, ["size", "color", "face"]),
        # basefont

        # 15.3
        "hr": merge(common, ["width"]),

        # HTML Ruby annotation text module, simple ruby only.
        # https://www.w3.org/TR/html5/text-level-semantics.html#the-ruby-element
        "ruby": common,
        # rbc
        "rb": common,
        "rp": common,
        "rt": common,  # $merge( $common, [ 'rbspan' ] ),
        "rtc": common,

        # MathML root element, where used for extensions
        # 'title' may not be 100% valid here; it's XHTML
        # https://www.w3.org/TR/REC-MathML/
        "math": merge({}, ["class", "style", "id", "title"]),

        # HTML 5 section 4.5
        "figure": common,
        "figcaption": common,

        # HTML 5 section 4.6
        "bdi": common,

        # HTML5 elements, defined by:
        # https://html.spec.whatwg.org/multipage/semantics.html#the-data-element
        "data": merge(common, ["value"]),
        "time": merge(common, ["datetime"]),
        "mark": common,

        # meta and link are only permitted by internalRemoveHtmlTags when Microdata
        # is enabled so we don't bother adding a conditional to hide these
        # Also meta and link are only valid in WikiText as Microdata elements
        # (ie: validateTag rejects tags missing the attributes needed for Microdata)
        # So we don't bother including $common attributes that have no purpose.
        "meta": merge({}, ["itemprop", "content"]),
        "link": merge({}, ["itemprop", "href", "title"]),

        # HTML 5 section 4.3.5
        "aside": common,
    }

    return allowed


# --- Plain text ----------------------------------------------------------------------------------------------------

def strip_all_tags(html: str) -> str:
    """Take a fragment of (potentially invalid) HTML and return a version with any tags removed, encoded as plain
    text.

    Warning: this return value must be further escaped for literal inclusion in HTML output as of 1.10!

    APPROXIMATION of RemexHtml, to be replaced when Remex is ported: MediaWiki runs RemexHtml's tokenizer (no tree
    builder) with RemexStripTagHandler; here Python's html.parser tokenizes. Both decode character references in
    text by the HTML5 rules and treat <script>/<style> content as markup; corner cases of malformed markup may
    tokenize differently.
    """
    # Use RemexHtml to tokenize $html and extract the text
    handler = _RemexStripTagHandler()
    handler.run(html)
    text = handler.get_result()

    text = _normalize_whitespace(text)
    return text


def hack_doc_type() -> str:
    """Hack up a private DOCTYPE with HTML's standard entity declarations. PHP 4 seemed to know these if you gave it
    an HTML doctype, but PHP 5.1 doesn't.

    Use for passing XHTML fragments to PHP's XML parsing functions

    @deprecated since 1.36; will be made private or removed in a future release.
    """
    out = ["<!DOCTYPE html [\n"]
    for entity in _NAMED_ENTITY_TRANSLATIONS:
        if entity[-1:] != ";":
            # Some HTML entities omit the trailing semicolon;
            # wikitext does not permit these.
            continue
        name = entity[:-1]
        expansion = _normalize_entity(entity)
        if entity == expansion:
            # Skip &lt; &gt; etc
            continue
        out.append(f'<!ENTITY {name} "{expansion}">')
    out.append("]>\n")
    return "".join(out)


# --- URLs and e-mail -----------------------------------------------------------------------------------------------

_CLEAN_URL_CHARS = re.compile(r'[\][<>"\x00-\x20\x7F|]')
_URL_PARTS = re.compile(r"^([^:]+:)(//[^/]+)?(.*)\Z", re.I)  # PHP /D: $ is the very end
# Characters that will be ignored in IDNs.
# https://datatracker.ietf.org/doc/html/rfc8264#section-9.13
# https://www.unicode.org/Public/UCD/latest/ucd/DerivedCoreProperties.txt
# Strip them before further processing so deny lists and such work.
_IDN_IGNORED = re.compile(r"""
    \s|      # general whitespace
    ­|               # SOFT HYPHEN
    ͏|               # COMBINING GRAPHEME JOINER
    ؜|               # ARABIC LETTER MARK
    [ᅟ-ᅠ]|    # HANGUL CHOSEONG FILLER..
                # HANGUL JUNGSEONG FILLER
    [឴-឵]|    # KHMER VOWEL INHERENT AQ..
                # KHMER VOWEL INHERENT AA
    [᠋-᠍]|    # MONGOLIAN FREE VARIATION SELECTOR ONE..
                # MONGOLIAN FREE VARIATION SELECTOR THREE
    ᠎|               # MONGOLIAN VOWEL SEPARATOR
    [​-‏]|    # ZERO WIDTH SPACE..
                # RIGHT-TO-LEFT MARK
    [‪-‮]|    # LEFT-TO-RIGHT EMBEDDING..
                # RIGHT-TO-LEFT OVERRIDE
    [⁠-⁤]|    # WORD JOINER..
                # INVISIBLE PLUS
    ⁥|               # <reserved-2065>
    [⁦-⁯]|    # LEFT-TO-RIGHT ISOLATE..
                # NOMINAL DIGIT SHAPES
    ㅤ|               # HANGUL FILLER
    [︀-️]|    # VARIATION SELECTOR-1..
                # VARIATION SELECTOR-16
    ﻿|               # ZERO WIDTH NO-BREAK SPACE
    ﾠ|               # HALFWIDTH HANGUL FILLER
    [￰-￸]|    # <reserved-FFF0>..
                # <reserved-FFF8>
    [\U0001BCA0-\U0001BCA3]|  # SHORTHAND FORMAT LETTER OVERLAP..
                # SHORTHAND FORMAT UP STEP
    [\U0001D173-\U0001D17A]|  # MUSICAL SYMBOL BEGIN BEAM..
                # MUSICAL SYMBOL END PHRASE
    \U000E0000|              # <reserved-E0000>
    \U000E0001|              # LANGUAGE TAG
    [\U000E0002-\U000E001F]|  # <reserved-E0002>..
                # <reserved-E001F>
    [\U000E0020-\U000E007F]|  # TAG SPACE..
                # CANCEL TAG
    [\U000E0080-\U000E00FF]|  # <reserved-E0080>..
                # <reserved-E00FF>
    [\U000E0100-\U000E01EF]|  # VARIATION SELECTOR-17..
                # VARIATION SELECTOR-256
    [\U000E01F0-\U000E0FFF]|  # <reserved-E01F0>..
                # <reserved-E0FFF>
    """, re.X)
_IPV6_HOST = re.compile(r"^//%5B([0-9A-Fa-f:.]+)%5D((:\d+)?)$", re.ASCII)


def clean_url(url: str) -> str:
    # Normalize any HTML entities in input. They will be
    # re-escaped by makeExternalLink().
    url = decode_char_references(url)

    # Escape any control characters introduced by the above step
    url = _CLEAN_URL_CHARS.sub(_clean_url_callback, url)

    # Validate hostname portion
    matches = _URL_PARTS.match(url)
    if matches:
        protocol, host, rest = matches.group(1), matches.group(2) or "", matches.group(3)

        host = _IDN_IGNORED.sub("", host)

        # IPv6 host names are bracketed with [].  Url-decode these.
        if host.startswith("//%5B"):
            ipv6 = _IPV6_HOST.search(host)
            if ipv6:
                host = "//[" + ipv6.group(1) + "]" + ipv6.group(2)

        # @todo FIXME: Validate hostnames here

        return protocol + host + rest
    else:
        return url


def _clean_url_callback(matches: re.Match[str]) -> str:
    return _php_urlencode(matches.group(0))


# Please note strings below are enclosed in brackets [], this make the
# hyphen "-" a range indicator. Hence it is double backslashed below.
# See T28948
_RFC5322_ATEXT = r"a-z0-9!#$%&'*+\-\/=?^_`{|}~"
_RFC1034_LDH_STR = r"a-z0-9\-"
_HTML5_EMAIL_REGEXP = re.compile(rf"""
    ^                      # start of string
    [{_RFC5322_ATEXT}\.]+    # user part which is liberal :p
    @                      # 'apostrophe'
    [{_RFC1034_LDH_STR}]+       # First domain part
    (\.[{_RFC1034_LDH_STR}]+)*  # Following part prefixed with a dot
    $                      # End of string
    """, re.I | re.X | re.ASCII)  # case Insensitive, eXtended


def validate_email(addr: str) -> bool:
    """Does a string look like an e-mail address?

    This validates an email address using an HTML5 specification found at:
    http://www.whatwg.org/html/states-of-the-type-attribute.html#valid-e-mail-address
    Which as of 2011-01-24 says:

      A valid e-mail address is a string that matches the ABNF production
      1*( atext / "." ) "@" ldh-str *( "." ldh-str ) where atext is defined
      in RFC 5322 section 3.2.3, and ldh-str is defined in RFC 1034 section
      3.5.

    This function is an implementation of the specification as requested in T24449.

    Client-side forms will use the same standard validation rules via JS or HTML 5 validation; additional
    restrictions can be enforced server-side by extensions via the 'isValidEmailAddr' hook (not run here).

    Note that this validation doesn't 100% match RFC 2822, but is believed to be liberal enough for wide use. Some
    invalid addresses will still pass validation here.

    @since 1.18
    """
    return bool(_HTML5_EMAIL_REGEXP.search(addr))


# --- RemexHtml approximation ---------------------------------------------------------------------------------------
# What follows stands in for RemexHtml (Tokenizer, TreeBuilder, Serializer) as Sanitizer uses it, until Remex is
# ported. The token handlers are ports of RemexStripTagHandler and RemexRemoveTagHandler; the tokenizer, the tree
# builder and the serializer are approximations.

class _RemexTokenizer(HTMLParser):
    """Tokenizes HTML like RemexHtml's Tokenizer with no tree builder attached: character references in text and
    attribute values are decoded, comments are reported (and the handlers drop them), and <script>, <style> etc.
    do not switch to raw text, because Remex switches only when a tree builder asks it to.

    Subclasses implement ``start_tag(name, attrs, self_close, source)``, ``end_tag(name, source)`` and
    ``characters(text)``; ``source`` is the tag as written in the input.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pending: Optional[tuple[str, str, dict[str, str], bool]] = None
        self._in_tag = False

    def run(self, text: str) -> None:
        self.feed(text)
        self.close()

    # Python's HTMLParser reports a tag before it knows where the tag ends; hold the token until the parse_* call
    # returns, so the handler can get the tag's source text.
    def parse_starttag(self, i: int) -> int:
        return self._parse_tag(super().parse_starttag, i)

    def parse_endtag(self, i: int) -> int:
        return self._parse_tag(super().parse_endtag, i)

    def _parse_tag(self, parse: Callable[[int], int], i: int) -> int:
        self._pending = None
        self._in_tag = True
        try:
            j = parse(i)
        finally:
            self._in_tag = False
        pending, self._pending = self._pending, None
        if pending is not None:
            self._dispatch(pending, self.rawdata[i:j] if j > i else "")
        return j

    def _queue(self, token: tuple[str, str, dict[str, str], bool]) -> None:
        if self._in_tag:
            self._pending = token
        else:
            name = token[1]
            self._dispatch(token, f"</{name}>" if token[0] == "end" else f"<{name}>")

    def _dispatch(self, token: tuple[str, str, dict[str, str], bool], source: str) -> None:
        kind, name, attrs, self_close = token
        if kind == "start":
            self.start_tag(name, attrs, self_close, source)
        else:
            self.end_tag(name, source)

    def set_cdata_mode(self, *args: Any, **kwargs: Any) -> None:
        pass  # no raw text switching without a tree builder (see the class docstring)

    @staticmethod
    def _attributes(attrs: list[tuple[str, Optional[str]]]) -> dict[str, str]:
        values: dict[str, str] = {}
        for name, value in attrs:
            if name not in values:  # HTML5: a repeated attribute is dropped
                values[name] = value if value is not None else ""
        return values

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._queue(("start", tag, self._attributes(attrs), False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._queue(("start", tag, self._attributes(attrs), True))

    def handle_endtag(self, tag: str) -> None:
        self._queue(("end", tag, {}, False))

    def handle_data(self, data: str) -> None:
        self.characters(data)

    # Comments, doctypes and processing instructions (bogus comments in HTML5) are not relayed.
    def handle_comment(self, data: str) -> None:
        pass

    def handle_decl(self, decl: str) -> None:
        pass

    def handle_pi(self, data: str) -> None:
        pass

    def unknown_decl(self, data: str) -> None:
        pass

    def start_tag(self, name: str, attrs: dict[str, str], self_close: bool, source: str) -> None:
        raise NotImplementedError

    def end_tag(self, name: str, source: str) -> None:
        raise NotImplementedError

    def characters(self, text: str) -> None:
        raise NotImplementedError


class _RemexStripTagHandler(_RemexTokenizer):
    """Helper class for Sanitizer::stripAllTags(). (RemexStripTagHandler) @internal"""

    # Per https://developer.mozilla.org/en-US/docs/Web/HTML/Block-level_elements
    # retrieved on sept 12, 2018. <br> is not block level but was added anyways.
    # The following is a complete list of all HTML block level elements
    # (although "block-level" is not technically defined for elements that are
    # new in HTML5).
    BLOCK_LEVEL_TAGS = frozenset([
        "address", "article", "aside", "blockquote", "br", "canvas", "dd", "div", "dl", "dt", "fieldset",
        "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li",
        "main", "nav", "noscript", "ol", "output", "p", "pre", "section", "table", "td", "tfoot", "th", "tr", "ul",
        "video",
    ])

    NON_VISIBLE_TAGS = frozenset(["style", "script"])

    def __init__(self) -> None:
        super().__init__()
        self._inside_non_visible_tag = False
        self._text: list[str] = []

    def get_result(self) -> str:
        return "".join(self._text)

    def characters(self, text: str) -> None:
        if not self._inside_non_visible_tag:
            self._text.append(text)

    def start_tag(self, name: str, attrs: dict[str, str], self_close: bool, source: str) -> None:
        if self._is_non_visible_tag(name):
            self._inside_non_visible_tag = True
        # Inject whitespace for typical block-level tags to
        # prevent merging unrelated<br>words.
        if self._is_block_level_tag(name):
            self._text.append(" ")

    def end_tag(self, name: str, source: str) -> None:
        if self._is_non_visible_tag(name):
            self._inside_non_visible_tag = False
        # Inject whitespace for typical block-level tags to
        # prevent merging unrelated<br>words.
        if self._is_block_level_tag(name):
            self._text.append(" ")

    def _is_block_level_tag(self, tag_name: str) -> bool:
        """Detect block level tags. Of course css can make anything a block level tag, but this is still better
        than nothing."""
        return _php_strtolower(_php_trim(tag_name)) in self.BLOCK_LEVEL_TAGS

    def _is_non_visible_tag(self, tag_name: str) -> bool:
        """Detect block tags which by default are non-visible items. Of course css can make anything non-visible,
        but this is still better than nothing.

        We use this primarily to hide TemplateStyles from output in notifications/emails etc.
        """
        return _php_strtolower(_php_trim(tag_name)) in self.NON_VISIBLE_TAGS


class _RemexRemoveTagHandler(_RemexTokenizer):
    """Helper class for Sanitizer::removeSomeTags(). (RemexRemoveTagHandler) @internal"""

    def __init__(self, next_handler: _TreeBuilder, tag_data: Mapping[str, frozenset[str]],
                 attr_callback: Optional[Callable[..., dict[str, str]]], callback_args: list[Any],
                 config: Config) -> None:
        super().__init__()
        self.next_handler = next_handler
        self.config = config
        # Set of HTML tags which can be self-closed.
        self.htmlsingle = tag_data["htmlsingle"]
        # Self-closed tags which are on $htmlsingle but not on $htmlsingleonly will be emitted as an empty element.
        self.htmlsingleonly = tag_data["htmlsingleonly"]
        # Set of allowed HTML open/close tags.
        self.htmlelements = tag_data["htmlelements"]
        # Callback to mutate or sanitize attributes.
        self.attr_callback = attr_callback
        # Optional extra arguments to provide to the $attrCallback.
        self.callback_args = callback_args

    def characters(self, text: str) -> None:
        self.next_handler.characters(text)

    def start_tag(self, name: str, attrs: dict[str, str], self_close: bool, source: str) -> None:
        # Handle a start tag from the tokenizer: either relay it to the
        # next stage, or re-emit it as raw text.

        badtag = False
        t = _php_strtolower(name)
        if t in self.htmlelements:
            if self.attr_callback:
                attrs = self.attr_callback(attrs, *self.callback_args)
            if self_close and not (t in self.htmlsingle or t in self.htmlsingleonly):
                # Remove the self-closing slash, to be consistent with
                # HTML5 semantics. T134423
                self_close = False
            if not _validate_tag_attribs(attrs, t):
                badtag = True
            attrs = validate_tag_attributes(attrs, t, config=self.config)
            if not badtag:
                if self_close and t not in self.htmlsingleonly:
                    # Interpret self-closing tags as empty tags even when
                    # HTML5 would interpret them as start tags.  Such input
                    # is commonly seen on Wikimedia wikis with this intention.
                    self.next_handler.start_tag(name, attrs, False)
                    self.next_handler.end_tag(name)
                else:
                    self.next_handler.start_tag(name, attrs, self_close)
                return
        # Emit this as a text node instead.
        self.next_handler.characters(source)

    def end_tag(self, name: str, source: str) -> None:
        # Handle an end tag from the tokenizer: either relay it to the
        # next stage, or re-emit it as raw text.

        t = _php_strtolower(name)
        if t in self.htmlelements:
            # This is a good tag, relay it.
            self.next_handler.end_tag(name)
        else:
            # Emit this as a text node instead.
            self.next_handler.characters(source)


class _Element:
    __slots__ = ("name", "attrs", "children")

    def __init__(self, name: str, attrs: dict[str, str]) -> None:
        self.name = name
        self.attrs = attrs
        self.children: list[Union[str, _Element]] = []


_VOID_ELEMENTS = frozenset("area base basefont bgsound br col embed frame hr image img input keygen link meta param "
                           "source track wbr".split())
_PREFIX_LF_ELEMENTS = frozenset(["pre", "textarea", "listing"])
_MARKED_EMPTY_ELEMENTS = frozenset(["li", "p", "tr"])
_SPECIAL_ELEMENTS = frozenset(
    "address applet area article aside base basefont bgsound blockquote body br button caption center col colgroup "
    "dd details dir div dl dt embed fieldset figcaption figure footer form frame frameset h1 h2 h3 h4 h5 h6 head "
    "header hgroup hr html iframe img input keygen li link listing main marquee menu meta nav noembed noframes "
    "noscript object ol p param plaintext pre script search section select source style summary table tbody td "
    "template textarea tfoot th thead title tr track ul wbr xmp".split())
_SCOPE = frozenset("applet caption html table td th marquee object template".split())
_BUTTON_SCOPE = _SCOPE | {"button"}
_LIST_ITEM_SCOPE = _SCOPE | {"ol", "ul"}
_TABLE_SCOPE = frozenset(["html", "table", "template"])
_CLOSES_P = frozenset(
    "address article aside blockquote center details dialog dir div dl fieldset figcaption figure footer header "
    "hgroup main menu nav ol p search section summary ul h1 h2 h3 h4 h5 h6 pre listing table hr form li dd dt".split())
_HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())
_TABLE_PARTS = frozenset("caption col colgroup tbody td tfoot th thead tr".split())
_IMPLIED_END = frozenset("dd dt li optgroup option p rb rp rt rtc".split())


class _TreeBuilder:
    """APPROXIMATION of RemexHtml's TreeBuilder (fragment parsing with a <body> context) and of its serialization
    by RemexCompatFormatter."""

    def __init__(self) -> None:
        self.root = _Element("html", {})
        self.stack: list[_Element] = [self.root]
        self._skip_lf = False

    @property
    def current(self) -> _Element:
        return self.stack[-1]

    # Scopes

    def _in_scope(self, names: Iterable[str], boundaries: frozenset[str]) -> bool:
        names = frozenset(names)
        for node in reversed(self.stack):
            if node.name in names:
                return True
            if node.name in boundaries:
                return False
        return False

    def _pop_until(self, names: Iterable[str]) -> None:
        names = frozenset(names)
        while len(self.stack) > 1:
            node = self.stack.pop()
            if node.name in names:
                return

    def _generate_implied_end_tags(self, exclude: str = "") -> None:
        while self.current.name in _IMPLIED_END and self.current.name != exclude:
            self.stack.pop()

    def _close_p(self) -> None:
        self._generate_implied_end_tags("p")
        self._pop_until(["p"])

    def _insert(self, name: str, attrs: dict[str, str]) -> _Element:
        element = _Element(name, attrs)
        self.current.children.append(element)
        if name not in _VOID_ELEMENTS:
            self.stack.append(element)
        return element

    # Tokens

    def characters(self, text: str) -> None:
        if self._skip_lf:
            self._skip_lf = False
            if text.startswith("\n"):
                text = text[1:]
        if not text:
            return
        children = self.current.children
        if children and isinstance(children[-1], str):
            children[-1] += text
        else:
            children.append(text)

    def start_tag(self, name: str, attrs: dict[str, str], self_close: bool = False) -> None:
        self._skip_lf = False
        name = _php_strtolower(name)
        if name in _TABLE_PARTS:
            self._table_part(name, attrs)
            return
        if name in ("li", "dd", "dt"):
            stop_names = {"li"} if name == "li" else {"dd", "dt"}
            for node in reversed(self.stack):
                if node.name in stop_names:
                    self._generate_implied_end_tags(node.name)
                    self._pop_until([node.name])
                    break
                if node.name in _SPECIAL_ELEMENTS and node.name not in ("address", "div", "p"):
                    break
        if name in _CLOSES_P and self._in_scope(["p"], _BUTTON_SCOPE):
            self._close_p()
        if name in _HEADINGS and self.current.name in _HEADINGS:
            self.stack.pop()
        self._insert(name, attrs)
        if name in ("pre", "listing"):
            self._skip_lf = True

    def _table_part(self, name: str, attrs: dict[str, str]) -> None:
        if not any(node.name == "table" for node in self.stack):
            return  # in body: a parse error, ignored
        if name in ("caption", "colgroup", "tbody", "thead", "tfoot", "col"):
            self._pop_to_context({"table"})
            if name == "col":
                self._insert("colgroup", {})
            self._insert(name, attrs)
            return
        if name == "tr":
            self._pop_to_context({"table", "tbody", "thead", "tfoot"})
        else:  # td, th
            self._pop_to_context({"table", "tbody", "thead", "tfoot", "tr"})
        if self.current.name == "table":
            self._insert("tbody", {})
        if name != "tr" and self.current.name in ("tbody", "thead", "tfoot"):
            self._insert("tr", {})
        self._insert(name, attrs)

    def _pop_to_context(self, names: set[str]) -> None:
        while self.current.name not in names and self.current.name != "table" and len(self.stack) > 1:
            self.stack.pop()

    def end_tag(self, name: str) -> None:
        self._skip_lf = False
        name = _php_strtolower(name)
        if name == "p":
            if not self._in_scope(["p"], _BUTTON_SCOPE):
                self._insert("p", {})
            self._close_p()
        elif name == "br":
            self._insert("br", {})
        elif name == "li":
            if self._in_scope(["li"], _LIST_ITEM_SCOPE):
                self._generate_implied_end_tags("li")
                self._pop_until(["li"])
        elif name in _HEADINGS:
            if self._in_scope(_HEADINGS, _SCOPE):
                self._generate_implied_end_tags()
                self._pop_until(_HEADINGS)
        elif name in _TABLE_PARTS or name == "table":
            if self._in_scope([name], _TABLE_SCOPE):
                self._generate_implied_end_tags()
                self._pop_until([name])
        elif name in _SPECIAL_ELEMENTS:
            if self._in_scope([name], _SCOPE):
                self._generate_implied_end_tags(name)
                self._pop_until([name])
        else:
            # "Any other end tag" (also standing in for the adoption agency algorithm)
            for index in range(len(self.stack) - 1, 0, -1):
                node = self.stack[index]
                if node.name == name:
                    self._generate_implied_end_tags(name)
                    del self.stack[index:]
                    return
                if node.name in _SPECIAL_ELEMENTS:
                    return

    # Serialization (RemexCompatFormatter)

    def serialize(self) -> str:
        return "".join(self._serialize_node(child) for child in self.root.children)

    def _serialize_node(self, node: Union[str, _Element]) -> str:
        if isinstance(node, str):
            # HtmlFormatter::characters() with RemexCompatFormatter's escapes ('&' is not escaped, because we
            # expect to see entities), then: Ensure a consistent representation for all entities
            text = php_strtr(node, {"<": "&lt;", ">": "&gt;", " ": "&#160;", "̸": "&#x338;"})
            return normalize_char_references(text)

        contents = "".join(self._serialize_node(child) for child in node.children)
        name = node.name
        attrs = node.attrs
        if name in _MARKED_EMPTY_ELEMENTS and not attrs and contents.strip("\t\n\f\r ") == "":
            return f'<{name} class="mw-empty-elt">{contents}</{name}>'

        s = [f"<{name}"]
        for attr_name, attr_value in attrs.items():
            enc_value = php_strtr(attr_value, {'"': "&quot;", " ": "&#160;"})
            enc_value = normalize_char_references(enc_value)
            s.append(f' {attr_name}="{enc_value}"')
        if name in _VOID_ELEMENTS:
            s.append(" />")
            return "".join(s)

        s.append(">")
        if contents[:1] == "\n" and name in _PREFIX_LF_ELEMENTS:
            s.append(f"\n{contents}</{name}>")
        else:
            s.append(f"{contents}</{name}>")
        return "".join(s)

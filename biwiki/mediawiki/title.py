# Ported from MediaWiki 1.39 includes/title/MediaWikiTitleCodec.php, includes/title/MalformedTitleException.php,
# includes/title/TitleValue.php (assertValidSpec), includes/Title.php (the parts the parser uses), and the helpers
# they call: Sanitizer::decodeCharReferencesAndNormalize() and Sanitizer::escapeIdForLink() /
# escapeIdForExternalInterwiki() (includes/parser/Sanitizer.php), wfArrayToCgi(), wfAppendQuery() and wfExpandUrl()
# (includes/GlobalFunctions.php, includes/utils/UrlUtils.php), IPUtils::sanitizeIP() (wikimedia/ip-utils 3.0.2)
# (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; Title and the codec take a Site instead of
# MediaWikiServices; no database (article IDs, existence, content models, restrictions), hooks, gender
# namespaces, language variants or action paths; getters as properties; error messages in English.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Page titles: parsing, validation and normalisation of title text (MediaWikiTitleCodec) and the Title class."""
from __future__ import annotations

import html.entities
import re
import unicodedata
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from typing import Mapping, Optional, Union

from .site import (NS_MAIN, NS_SPECIAL, NS_TALK, NS_USER, NS_USER_TALK, Site, php_urlencode, wf_urlencode)

UTF8_REPLACEMENT = "�"  # UtfNormal\Constants::UTF8_REPLACEMENT

# PROTO_* (includes/Defines.php)
PROTO_HTTP = "http://"
PROTO_HTTPS = "https://"
PROTO_RELATIVE = "//"
PROTO_FALLBACK = None
PROTO_CURRENT = PROTO_FALLBACK
PROTO_CANONICAL = 1
PROTO_INTERNAL = 2

# English text of the title-invalid-* messages (languages/i18n/en.json)
_MESSAGES = {
    "title-invalid": "The requested page title is invalid",
    "title-invalid-empty": "The requested page title is empty or contains only the name of a namespace.",
    "title-invalid-utf8": "The requested page title contains an invalid UTF-8 sequence.",
    "title-invalid-interwiki": "The requested page title contains an interwiki link which cannot be used in titles.",
    "title-invalid-talk-namespace": "The requested page title refers to a talk page that cannot exist.",
    "title-invalid-characters": "The requested page title contains invalid characters: \"$1\".",
    "title-invalid-relative": "Title has relative path. Relative page titles (./, ../) are invalid, because they "
                              "will often be unreachable when handled by user's browser.",
    "title-invalid-magic-tilde": "The requested page title contains invalid magic tilde sequence (~~~).",
    "title-invalid-too-long": "The requested page title is too long. It must be no longer than $1 bytes in UTF-8 "
                              "encoding.",
    "title-invalid-leading-colon": "The requested page title contains an invalid colon at the beginning.",
}


class MalformedTitleException(Exception):
    """MalformedTitleException is thrown when a TitleParser is unable to parse a title string."""

    def __init__(self, error_message: str, title_text: Optional[str] = None,
                 error_message_parameters: tuple = ()):
        self.error_message = error_message
        self.title_text = title_text
        params = list(error_message_parameters)
        if title_text is not None:
            params.append(title_text)  # PHP: wfEscapeWikiText( $titleText )
        self.error_message_parameters = params
        text = _MESSAGES.get(error_message, error_message)
        for i, param in enumerate(params, 1):
            text = text.replace(f"${i}", str(param))
        super().__init__(text)

    def get_title_text(self) -> Optional[str]:
        return self.title_text

    def get_error_message(self) -> str:
        return self.error_message

    def get_error_message_parameters(self) -> list:
        return self.error_message_parameters


# --- Sanitizer helpers ---

# Sanitizer::CHAR_REFS_REGEX, over characters instead of UTF-8 bytes (\x80-\xff: any non-ASCII character)
_CHAR_REFS_REGEX = re.compile(
    r"&([A-Za-z0-9\u0080-\U0010ffff]+;)"
    r"|&\#([0-9]+);"
    r"|&\#[xX]([0-9A-Fa-f]+);"
    r"|(&)")

# Sanitizer::MW_ENTITY_ALIASES: MediaWiki-specific entities, not in the HTML standard
_MW_ENTITY_ALIASES = {"רלמ;": "rlm;", "رلم;": "rlm;"}


def _validate_codepoint(codepoint: int) -> bool:
    """Sanitizer::validateCodepoint(): true if a given Unicode codepoint is a valid character in both HTML5 and
    XML."""
    # U+000C is valid in HTML5 but not allowed in XML.
    # U+000D is valid in XML but not allowed in HTML5.
    # U+007F - U+009F are disallowed in HTML5 (control characters).
    return (codepoint == 0x09
            or codepoint == 0x0a
            or 0x20 <= codepoint <= 0x7e
            or 0xa0 <= codepoint <= 0xd7ff
            or 0xe000 <= codepoint <= 0xfffd
            or 0x10000 <= codepoint <= 0x10ffff)


def _decode_char(codepoint: int) -> str:
    """Sanitizer::decodeChar(): the character for a codepoint if that is a valid character reference, otherwise
    U+FFFD REPLACEMENT CHARACTER."""
    return chr(codepoint) if _validate_codepoint(codepoint) else UTF8_REPLACEMENT


def _decode_entity(name: str) -> str:
    """Sanitizer::decodeEntity(): the character of a named entity defined in HTML5, otherwise the pseudo-entity
    source (eg "&foo;")."""
    name = _MW_ENTITY_ALIASES.get(name, name)
    trans = html.entities.html5.get(name)  # HTMLData::$namedEntityTranslations
    return trans if trans is not None else "&" + name


def _decode_char_references_callback(m: re.Match) -> str:
    if m.group(1):
        return _decode_entity(m.group(1))
    elif m.group(2):
        return _decode_char(int(m.group(2)))
    elif m.group(3):
        return _decode_char(int(m.group(3), 16))
    # Last case should be an ampersand by itself
    return m.group(0)


_CLEANUP_REGEX = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _normalize(s: str) -> str:
    """Language::normalize() ($wgAllUnicodeFixes off): UtfNormal\\Validator::cleanUp(), which replaces forbidden
    control characters and non-characters with U+FFFD and normalizes to NFC."""
    return unicodedata.normalize("NFC", _CLEANUP_REGEX.sub(UTF8_REPLACEMENT, s))


def decode_char_references_and_normalize(text: str) -> str:
    """Sanitizer::decodeCharReferencesAndNormalize(): decode any character references, numeric or named entities,
    in the text and normalize the resulting string. (T16952)

    This is useful for page titles, not for text to be displayed, MediaWiki allows HTML entities to escape
    normalization as a feature."""
    text, count = _CHAR_REFS_REGEX.subn(_decode_char_references_callback, text)
    return _normalize(text) if count else text


def _escape_id_internal(id_: str, mode: str) -> str:
    """Sanitizer::escapeIdInternal(): performs most of the actual escaping of the escapeIdFor*() functions."""
    # Truncate overly-long IDs. This isn't an HTML limit, it's just griefer protection. [T251506]
    id_ = id_[:1024]
    if mode == "html5":
        # html5 spec says ids must not have any of the following: U+0009 TAB, U+000A LF, U+000C FF, U+000D CR, or
        # U+0020 SPACE
        for c in "\t\n\f\r ":
            id_ = id_.replace(c, "_")
    elif mode == "legacy":
        # This corresponds to 'noninitial' mode of the former escapeId()
        id_ = php_urlencode(id_.replace(" ", "_"))
        id_ = id_.replace("%3A", "\x00").replace("%", ".").replace("\x00", ":")  # strtr: '%3A' => ':', '%' => '.'
    else:
        raise ValueError(f"Invalid mode '{mode}' passed to escapeIdInternal")
    return id_


def _escape_id_internal_url(id_: str, mode: str) -> str:
    """Sanitizer::escapeIdInternalUrl(): do percent encoding of percent signs for href (but not id) attributes"""
    id_ = _escape_id_internal(id_, mode)
    if mode == "html5":
        id_ = re.sub(r"%([a-fA-F0-9]{2})", r"%25\1", id_)
    return id_


def escape_id_for_link(id_: str, site: Site) -> str:
    """Sanitizer::escapeIdForLink(): escapes a section name or other user-generated string to be a valid URL
    fragment, in the primary $wgFragmentMode."""
    if not site.config.fragment_mode:
        raise ValueError("$wgFragmentMode is configured with no primary mode")
    return _escape_id_internal_url(id_, site.config.fragment_mode[0])


def escape_id_for_external_interwiki(id_: str, site: Site) -> str:
    """Sanitizer::escapeIdForExternalInterwiki(): a valid URL fragment for external interwikis
    ($wgExternalInterwikiFragmentMode)."""
    return _escape_id_internal_url(id_, site.config.external_interwiki_fragment_mode)


# --- URL helpers (GlobalFunctions.php, UrlUtils.php) ---

def wf_array_to_cgi(array1: Mapping, prefix: str = "") -> str:
    """wfArrayToCgi(): a query string from an associative array (no nested arrays beyond one level of lists)"""
    parts = []
    for key, value in array1.items():
        if value is None or value is False:
            continue
        if prefix != "":
            key = f"{prefix}[{key}]"
        if isinstance(value, Mapping):
            parts.append(wf_array_to_cgi(value, str(key)))
        elif isinstance(value, (list, tuple)):
            parts.append("&".join(f"{php_urlencode(f'{key}[{k}]')}={php_urlencode(_php_str(v))}"
                                  for k, v in enumerate(value)))
        else:
            parts.append(f"{php_urlencode(str(key))}={php_urlencode(_php_str(value))}")
    return "&".join(parts)


def _php_str(value) -> str:
    """PHP string conversion: true -> '1'."""
    if value is True:
        return "1"
    return str(value)


def wf_append_query(url: str, query: Union[str, Mapping]) -> str:
    """wfAppendQuery(): append a query string to an existing URL, which may or may not already have query string
    parameters already. If so, they will be combined."""
    if isinstance(query, Mapping):
        query = wf_array_to_cgi(query)
    if query != "":
        # Remove the fragment, if there is one
        fragment = None
        hash_pos = url.find("#")
        if hash_pos != -1:
            fragment = url[hash_pos:]
            url = url[:hash_pos]
        # Add parameter
        url += "&" if "?" in url else "?"
        url += query
        # Put the fragment back
        if fragment is not None:
            url += fragment
    return url


def remove_dot_segments(url_path: str) -> str:
    """UrlUtils::removeDotSegments(): remove all dot-segments in the provided URL path (RFC 3986 section 5.2.4)."""
    output = ""
    path = list(url_path)
    input_offset = 0
    input_length = len(path)
    while input_offset < input_length:
        rest = "".join(path[input_offset:input_offset + 4])
        prefix1, prefix2, prefix3, prefix4 = rest[:1], rest[:2], rest[:3], rest[:4]
        trim_output = False
        if prefix2 == "./":
            # Step A, remove leading "./"
            input_offset += 2
        elif prefix3 == "../":
            # Step A, remove leading "../"
            input_offset += 3
        elif prefix2 == "/." and input_offset + 2 == input_length:
            # Step B, replace leading "/.$" with "/"
            input_offset += 1
            path[input_offset] = "/"
        elif prefix3 == "/./":
            # Step B, replace leading "/./" with "/"
            input_offset += 2
        elif prefix3 == "/.." and input_offset + 3 == input_length:
            # Step C, replace leading "/..$" with "/" and remove last path component in output
            input_offset += 2
            path[input_offset] = "/"
            trim_output = True
        elif prefix4 == "/../":
            # Step C, replace leading "/../" with "/" and remove last path component in output
            input_offset += 3
            trim_output = True
        elif prefix1 == "." and input_offset + 1 == input_length:
            # Step D, remove "^.$"
            input_offset += 1
        elif prefix2 == ".." and input_offset + 2 == input_length:
            # Step D, remove "^..$"
            input_offset += 2
        else:
            # Step E, move leading path segment to output
            text = "".join(path)
            slash_pos = text.find("/", input_offset + 1 if prefix1 == "/" else input_offset)
            if slash_pos == -1:
                output += text[input_offset:]
                input_offset = input_length
            else:
                output += text[input_offset:slash_pos]
                input_offset = slash_pos
        if trim_output:
            slash_pos = output.rfind("/")
            output = "" if slash_pos == -1 else output[:slash_pos]
    return output


# scheme (or "//"), authority, path, rest: the parts UrlUtils::parse() and assemble() round-trip
_URL_PARTS = re.compile(r"^((?:[A-Za-z][A-Za-z0-9+.-]*:)?//[^/?#]*)([^?#]*)(.*)$", re.S)


def wf_expand_url(url: str, site: Site, default_proto: Union[str, int, None, bool] = PROTO_CURRENT) -> str:
    """wfExpandUrl() / UrlUtils::expand(): expand a potentially local URL to a fully-qualified URL using $wgServer
    (also for PROTO_CANONICAL and PROTO_INTERNAL: $wgCanonicalServer and $wgInternalServer default to it).

    Approximation: instead of parse_url() and wfAssembleUrl(), only the path of URLs of the form [scheme:]//host/path
    has its dot segments removed; other URLs are returned unchanged."""
    server_url = site.config.server
    if default_proto is PROTO_FALLBACK:
        default_proto = "http://"  # the fallback protocol of a request-less run
    if url.startswith("/"):
        m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", server_url)
        server_proto = m.group(1).lower() + "://" if m else None
        if default_proto in (PROTO_CANONICAL, PROTO_INTERNAL):
            # Fall back to HTTP in the ridiculous case that CanonicalServer or InternalServer doesn't have a protocol
            default_proto = server_proto or PROTO_HTTP
        default_proto_without_slashes = default_proto[:-2] if isinstance(default_proto, str) else ""
        if url.startswith("//"):
            url = default_proto_without_slashes + url
        elif server_proto:
            url = server_url + url
        else:
            url = default_proto_without_slashes + server_url + url
    m = _URL_PARTS.match(url)
    if m:
        return m.group(1) + remove_dot_segments(m.group(2)) + m.group(3)
    return url


# --- IPUtils ---

_RE_IP_BYTE = r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|0?[0-9]?[0-9])"
_RE_IP_ADD = rf"{_RE_IP_BYTE}\.{_RE_IP_BYTE}\.{_RE_IP_BYTE}\.{_RE_IP_BYTE}"
_RE_IP_PREFIX = r"(3[0-2]|[12][0-9]|[0-9])"
_RE_IPV6_WORD = r"([0-9A-Fa-f]{1,4})"
_RE_IPV6_PREFIX = r"(12[0-8]|1[01][0-9]|[1-9][0-9]|[0-9])"
_IPV4_REGEX = re.compile(rf"{_RE_IP_ADD}(?:/{_RE_IP_PREFIX})?")
# IPUtils::RE_IPV6_ADD, one regex per alternative: Python's re has no relative conditional groups, so the "one
# '::' in the middle" alternative is checked by _is_ipv6_add()
_IPV6_START = re.compile(rf":(?::|(?::{_RE_IPV6_WORD}){{1,7}})")  # starts with "::" (including "::")
_IPV6_END = re.compile(rf"{_RE_IPV6_WORD}(?::{_RE_IPV6_WORD}){{0,6}}::")  # ends with "::" (except "::")
_IPV6_MIDDLE = re.compile(rf"{_RE_IPV6_WORD}((?::{_RE_IPV6_WORD})*)::{_RE_IPV6_WORD}((?::{_RE_IPV6_WORD})*)")
_IPV6_FULL = re.compile(rf"{_RE_IPV6_WORD}(?::{_RE_IPV6_WORD}){{7}}")  # contains no "::"
_IPV6_PREFIX_REGEX = re.compile(_RE_IPV6_PREFIX)


def _is_ipv6_add(ip: str) -> bool:
    if _IPV6_START.fullmatch(ip) or _IPV6_END.fullmatch(ip) or _IPV6_FULL.fullmatch(ip):
        return True
    # contains one "::" in the middle: 2 to 7 words
    m = _IPV6_MIDDLE.fullmatch(ip)
    return bool(m) and 2 + m.group(2).count(":") + m.group(5).count(":") <= 7


def _is_ipv6(ip: str) -> bool:
    """IPUtils::isIPv6()"""
    address, slash, prefix = ip.partition("/")
    return _is_ipv6_add(address) and (not slash or _IPV6_PREFIX_REGEX.fullmatch(prefix) is not None)


def _is_ipv4(ip: str) -> bool:
    """IPUtils::isIPv4()"""
    return _IPV4_REGEX.fullmatch(ip) is not None


def sanitize_ip(ip: str) -> Optional[str]:
    """IPUtils::sanitizeIP(): convert an IP into a verbose, uppercase, normalized form. Both IPv4 and IPv6
    addresses are supported; anything else is returned trimmed."""
    ip = ip.strip(" \t\n\r\0\x0b")
    if ip == "":
        return None
    # If not an IP, just return trimmed value, since sanitizeIP() is called in a number of contexts where usernames
    # are supplied as input.
    if not (_is_ipv4(ip) or _is_ipv6(ip)):  # isIPAddress()
        return ip
    if _is_ipv4(ip):
        # Remove leading 0's from octet representation of IPv4 address
        return re.sub(r"(?:^|(?<=\.))0+(?=[1-9]|0[./]|0$)", "", ip)
    # Remove any whitespaces, convert to upper case
    ip = ip.upper()
    # Expand zero abbreviations
    abbrev_pos = ip.find("::")
    if abbrev_pos != -1:
        # We know this is valid IPv6. Find the last index of the address before any CIDR number (e.g. "a:b:c::/24").
        cidr_start = ip.find("/")
        address_end = cidr_start - 1 if cidr_start != -1 else len(ip) - 1
        if abbrev_pos == 0:
            # If the '::' is at the beginning...
            repeat = "0:"
            extra = "0" if ip == "::" else ""  # for the address '::'
            pad = 9  # 7+2 (due to '::')
        elif abbrev_pos == address_end - 1:
            # If the '::' is at the end...
            repeat = ":0"
            extra = ""
            pad = 9  # 7+2 (due to '::')
        else:
            # If the '::' is in the middle...
            repeat = ":0"
            extra = ":"
            pad = 8  # 6+2 (due to '::')
        ip = ip.replace("::", repeat * (pad - ip.count(":")) + extra)
    # Remove leading zeros from each bloc as needed
    return re.sub(rf"(^|:)0+{_RE_IPV6_WORD}", r"\1\2", ip)


# --- MediaWikiTitleCodec ---

@dataclass(frozen=True)
class TitleValue:
    """Representation of a page title within MediaWiki (includes/title/TitleValue.php), without validation."""
    namespace: int
    db_key: str
    fragment: str = ""
    interwiki: str = ""

    @property
    def text(self) -> str:
        return self.db_key.replace("_", " ")


def assert_valid_spec(namespace: int, title: str, fragment: str = "", interwiki: str = "") -> None:
    """TitleValue::assertValidSpec(): raise ValueError if the arguments do not make a valid TitleValue."""
    if re.search(r"^[_ ]|[\r\n\t]|[_ ]$", title):
        raise ValueError(f"Bad value for parameter $title: invalid name '{title}'")
    # NOTE: As of MW 1.34, [[#]] is rendered as a valid link, pointing to the empty page title, effectively leading
    # to the wiki's main page. This means that a completely empty TitleValue has to be considered valid, for
    # consistency with Title. Also note that [[#foo]] is a valid on-page section links, and that [[acme:#foo]] is a
    # valid interwiki link.
    if title == "" and namespace != NS_MAIN:
        raise ValueError("Bad value for parameter $title: should not be empty unless namespace is main")


def _legal_chars_to_python(legal_chars: str) -> str:
    """$wgLegalTitleChars is a class over UTF-8 bytes, in which \\x80-\\xFF stands for every non-ASCII character."""
    return re.sub(r"\\x80-\\xFF", lambda m: "\\u0080-\\U0010ffff", legal_chars, flags=re.I)


class MediaWikiTitleCodec:
    """A codec for MediaWiki page titles.

    Normalization and validation is applied while parsing, not when formatting."""

    def __init__(self, site: Site):
        self.site = site
        self.local_interwikis = list(site.local_interwikis)
        self._title_invalid_regex: Optional[re.Pattern] = None

    def get_namespace_name(self, namespace: int, text: str) -> str:
        """Namespace name with underscores (not spaces), e.g. 'User_talk'. English has no gender distinction.
        Raises ValueError if the namespace is invalid."""
        name = self.site.get_ns_text(namespace)
        if name is None:
            raise ValueError(f"Unknown namespace ID: {namespace}")
        return name

    def format_title(self, namespace: Union[int, bool], text: str, fragment: str = "", interwiki: str = "") -> str:
        """The page title text, minimally normalized: underscores are replaced."""
        out = ""
        if interwiki != "":
            out = interwiki + ":"
        if namespace is not False and namespace != 0:
            try:
                ns_name = self.get_namespace_name(namespace, text)
            except ValueError:
                # See T165149. Awkward, but better than erroneously linking to the main namespace.
                ns_name = f"{self.site.get_ns_text(NS_SPECIAL)}:Badtitle/NS{namespace}"
            out += ns_name + ":"
        out += text
        if fragment != "":
            out += "#" + fragment
        return out.replace("_", " ")

    def parse_title(self, text: str, default_namespace: int = NS_MAIN) -> TitleValue:
        """Parses the given text and constructs a TitleValue. Raises MalformedTitleException."""
        # Convert things like &eacute; &#257; or &#x3017; into normalized (T16952) text
        filtered_text = decode_char_references_and_normalize(text)
        parts = self.split_title_string(filtered_text, default_namespace)
        return TitleValue(parts["namespace"], parts["dbkey"], parts["fragment"], parts["interwiki"])

    def make_title_value_safe(self, namespace: int, text: str, fragment: str = "",
                              interwiki: str = "") -> Optional[TitleValue]:
        """Given a namespace and title, return a TitleValue if valid, or None if invalid."""
        if not self.site.exists(namespace):
            return None
        canonical_ns = self.site.get_canonical_name(namespace)
        full_text = text if canonical_ns == "" else f"{canonical_ns}:{text}"
        if str(interwiki) != "":
            full_text = f"{interwiki}:{full_text}"
        if str(fragment) != "":
            full_text += "#" + fragment
        try:
            parts = self.split_title_string(full_text)
        except MalformedTitleException:
            return None
        return TitleValue(parts["namespace"], parts["dbkey"], parts["fragment"], parts["interwiki"])

    def split_title_string(self, text: str, default_namespace: int = NS_MAIN) -> dict:
        """Validates, normalizes and splits a title string. This is the "source of truth" for title validity.

        This function removes illegal characters, splits off the interwiki and namespace prefixes, sets the other
        forms, and canonicalizes everything.

        Returns a map with the fields 'interwiki', 'local_interwiki', 'fragment', 'namespace' and 'dbkey'; raises
        MalformedTitleException if text is not a valid title string."""
        site = self.site
        dbkey = text.replace(" ", "_")

        # Initialisation
        parts = {
            "interwiki": "",
            "local_interwiki": False,
            "fragment": "",
            "namespace": int(default_namespace),
            "dbkey": dbkey,
        }

        # Strip Unicode bidi override characters.
        # Sometimes they slip into cut-n-pasted page titles, where the override chars get included in list
        # displays.
        dbkey = re.sub("[‎‏‪-‮]+", "", dbkey)

        if re.search("[\ud800-\udfff]", dbkey):
            # Regex had an error. Most likely this is caused by invalid UTF-8 (in Python: lone surrogates, e.g.
            # from bytes decoded with errors="surrogateescape")
            raise MalformedTitleException("title-invalid-utf8", text)

        # Clean up whitespace
        dbkey = re.sub("[ _\xa0 ᠎ -     　]+", "_", dbkey)
        dbkey = dbkey.strip("_")

        if UTF8_REPLACEMENT in dbkey:
            # Contained illegal UTF-8 sequences or forbidden Unicode chars.
            raise MalformedTitleException("title-invalid-utf8", text)

        parts["dbkey"] = dbkey

        # Initial colon indicates main namespace rather than specified default
        # but should not create invalid {ns,title} pairs such as {0,Project:Foo}
        if dbkey != "" and dbkey[0] == ":":
            parts["namespace"] = NS_MAIN
            dbkey = dbkey[1:]  # remove the colon but continue processing
            dbkey = dbkey.strip("_")  # remove any subsequent whitespace

        if dbkey == "":
            raise MalformedTitleException("title-invalid-empty", text)

        # Namespace or interwiki prefix
        prefix_regexp = re.compile(r"^(.+?)_*:_*(.*)$")
        while True:
            m = prefix_regexp.match(dbkey)
            if m:
                p = m.group(1)
                ns = site.get_ns_index(p)
                if ns is not None:
                    # Ordinary namespace
                    dbkey = m.group(2)
                    parts["namespace"] = ns
                    # For Talk:X pages, check if X has a "namespace" prefix
                    x = prefix_regexp.match(dbkey) if ns == NS_TALK else None
                    if x:
                        if site.get_ns_index(x.group(1)):  # PHP truthiness: NS_MAIN does not count
                            # Disallow Talk:File:x type titles...
                            raise MalformedTitleException("title-invalid-talk-namespace", text)
                        elif site.is_valid_interwiki(x.group(1)):
                            # Disallow Talk:Interwiki:x type titles...
                            raise MalformedTitleException("title-invalid-talk-namespace", text)
                elif site.is_valid_interwiki(p):
                    # Interwiki link
                    dbkey = m.group(2)
                    parts["interwiki"] = site.lc(p)

                    # Redundant interwiki prefix to the local wiki
                    is_local = False
                    for local_iw in self.local_interwikis:
                        if _ascii_lower(parts["interwiki"]) == _ascii_lower(local_iw):  # strcasecmp()
                            is_local = True
                            break
                    if is_local:
                        if dbkey == "":
                            # Empty self-links should point to the Main Page, to ensure compatibility with
                            # cross-wiki transclusions and the like.
                            main_page = Title.new_main_page(site=site)
                            return {
                                "interwiki": main_page.interwiki,
                                "local_interwiki": True,
                                "fragment": main_page.fragment,
                                "namespace": main_page.namespace,
                                "dbkey": main_page.db_key,
                            }
                        parts["interwiki"] = ""
                        # local interwikis should behave like initial-colon links
                        parts["local_interwiki"] = True
                        # Do another namespace split...
                        continue

                    # If there's an initial colon after the interwiki, that also resets the default namespace
                    if dbkey != "" and dbkey[0] == ":":
                        parts["namespace"] = NS_MAIN
                        dbkey = dbkey[1:]
                        dbkey = dbkey.strip("_")
                # If there's no recognized interwiki or namespace, then let the colon expression be part of the
                # title.
            break

        hash_pos = dbkey.find("#")
        if hash_pos != -1:
            fragment = dbkey[hash_pos:]
            parts["fragment"] = fragment[1:].replace("_", " ")
            dbkey = dbkey[:hash_pos]
            # remove whitespace again: prevents "Foo_bar_#" becoming "Foo_bar_"
            dbkey = re.sub(r"_*$", "", dbkey)

        # Reject illegal characters.
        m = self.get_title_invalid_regex().search(dbkey)
        if m:
            raise MalformedTitleException("title-invalid-characters", text, (m.group(0),))

        # Pages with "/./" or "/../" appearing in the URLs will often be un-reachable due to the way web browsers
        # deal with 'relative' URLs. Also, they conflict with subpage syntax. Forbid them explicitly.
        if "." in dbkey and (
            dbkey == "." or dbkey == ".."
            or dbkey.startswith("./")
            or dbkey.startswith("../")
            or "/./" in dbkey
            or "/../" in dbkey
            or dbkey.endswith("/.")
            or dbkey.endswith("/..")
        ):
            raise MalformedTitleException("title-invalid-relative", text)

        # Magic tilde sequences? Nu-uh!
        if "~~~" in dbkey:
            raise MalformedTitleException("title-invalid-magic-tilde", text)

        # Limit the size of titles to 255 bytes. This is typically the size of the underlying database field. We
        # make an exception for special pages, which don't need to be stored in the database, and may edge over 255
        # bytes due to subpage syntax for long titles, e.g. [[Special:Block/Long name]]
        max_length = 255 if parts["namespace"] != NS_SPECIAL else 512
        if len(dbkey.encode("utf-8")) > max_length:
            raise MalformedTitleException("title-invalid-too-long", text, (max_length,))

        # Normally, all wiki links are forced to have an initial capital letter so [[foo]] and [[Foo]] point to the
        # same place. Don't force it for interwikis, since the other site might be case-sensitive.
        if parts["interwiki"] == "" and site.is_capitalized(parts["namespace"]):
            dbkey = site.ucfirst(dbkey)

        # Can't make a link to a namespace alone... "empty" local links can only be self-links with a fragment
        # identifier.
        if dbkey == "" and parts["interwiki"] == "" and parts["namespace"] != NS_MAIN:
            raise MalformedTitleException("title-invalid-empty", text)

        # Allow IPv6 usernames to start with '::' by canonicalizing IPv6 titles.
        # IP names are not allowed for accounts, and can only be referring to edits from the IP. Given '::'
        # abbreviations and caps/lowercaps, there are numerous ways to present the same IP. Having sp:contribs scan
        # them all is silly and having some show the edits and others not is inconsistent. Same for
        # talk/userpages. Keep them normalized instead.
        if parts["namespace"] in (NS_USER, NS_USER_TALK):
            dbkey = sanitize_ip(dbkey) or ""

        # Any remaining initial :s are illegal.
        if dbkey != "" and dbkey[0] == ":":
            raise MalformedTitleException("title-invalid-leading-colon", text)

        # Fill fields
        parts["dbkey"] = dbkey

        # Check to ensure that the return value can be used to construct a TitleValue.
        # All issues should in theory be caught above, this is here to enforce consistency.
        try:
            assert_valid_spec(parts["namespace"], parts["dbkey"], parts["fragment"], parts["interwiki"])
        except ValueError as ex:
            raise MalformedTitleException("title-invalid", text, (str(ex),)) from ex

        return parts

    def get_title_invalid_regex(self) -> re.Pattern:
        """A simple regex that will match on characters and sequences invalid in titles. Note that this doesn't
        pick up many things that could be wrong with titles, but that replacing this regex with something valid
        will make many titles valid."""
        if self._title_invalid_regex is None:
            # Matching titles will be held as illegal.
            self._title_invalid_regex = re.compile(
                # Any character not allowed is forbidden...
                "[^" + _legal_chars_to_python(self.site.legal_title_chars) + "]"
                # URL percent encoding sequences interfere with the ability to round-trip titles -- you can't link
                # to them consistently.
                r"|%[0-9A-Fa-f]{2}"
                # XML/HTML character references produce similar issues.
                r"|&[A-Za-z0-9\u0080-\U0010ffff]+;")
        return self._title_invalid_regex


def _ascii_lower(s: str) -> str:
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in s)


class _SiteState:
    """What MediaWikiServices keeps per wiki: the title codec and Title::newFromText()'s cache."""
    _MAX_CACHE = 1000  # Title::CACHE_MAX

    def __init__(self, site: Site):
        self.codec = MediaWikiTitleCodec(site)
        self.title_cache: OrderedDict[str, Title] = OrderedDict()  # MapCacheLRU
        self.main_page_recursion_guard = False

    def cache_get(self, key: str) -> Optional[Title]:
        t = self.title_cache.get(key)
        if t is not None:
            self.title_cache.move_to_end(key)
        return t

    def cache_set(self, key: str, title: Title) -> None:
        self.title_cache[key] = title
        self.title_cache.move_to_end(key)
        while len(self.title_cache) > self._MAX_CACHE:
            self.title_cache.popitem(last=False)


_site_states: "weakref.WeakKeyDictionary[Site, _SiteState]" = weakref.WeakKeyDictionary()


def _state(site: Site) -> _SiteState:
    state = _site_states.get(site)
    if state is None:
        state = _site_states[site] = _SiteState(site)
    return state


def get_title_codec(site: Site) -> MediaWikiTitleCodec:
    """MediaWikiServices::getTitleParser() / getTitleFormatter() for a site."""
    return _state(site).codec


# --- Title ---

class Title:
    """Represents a title within MediaWiki. Optionally may contain an interwiki designation or namespace.

    The getters of the PHP class are properties here: getText() is .text, getPrefixedText() .prefixed_text,
    getDBkey() .db_key, getNsText() .ns_text, and so on. Titles compare equal (==) as Title::equals() does: same
    interwiki, namespace and DB key, fragment ignored."""

    DEFAULT_NAMESPACE = NS_MAIN

    def __init__(self, site: Site):
        self.site = site
        self._interwiki = ""
        self._local_interwiki = False
        self._fragment = ""
        self._namespace = NS_MAIN
        self._dbkeyform = ""
        self._urlform = ""
        self._textform = ""
        self._is_valid: Optional[bool] = None
        self._prefixed_text: Optional[str] = None
        self._instance_cache_key: Optional[str] = None

    # --- constructors ---

    @classmethod
    def new_from_db_key(cls, key: str, *, site: Site) -> Optional[Title]:
        """Create a new Title from a prefixed DB key; None on an error"""
        t = cls(site)
        try:
            t._secure_and_split(key)
            return t
        except MalformedTitleException:
            return None

    @classmethod
    def new_from_text(cls, text: Union[str, int, None], default_namespace: int = NS_MAIN, *,
                      site: Site) -> Optional[Title]:
        """Create a new Title from text, such as what one would find in a link. Decodes any HTML entities in the
        text. Titles returned by this method are guaranteed to be valid; None if the text is not a valid title.

        The Title instance returned by this method is not guaranteed to be a fresh instance. It may instead be a
        cached instance created previously, with references to it remaining elsewhere."""
        # DWIM: Integers can be passed in here when page titles are used as array keys.
        if text is not None and not isinstance(text, (str, int)):
            raise TypeError("$text must be a string.")
        if text is None or text == "":
            return None
        try:
            return cls.new_from_text_throw(str(text), int(default_namespace), site=site)
        except MalformedTitleException:
            return None

    @classmethod
    def new_from_text_throw(cls, text: str, default_namespace: int = NS_MAIN, *, site: Site) -> Title:
        """Like new_from_text(), but raises MalformedTitleException when the title is invalid, rather than returning
        None."""
        if text is None:
            raise MalformedTitleException("title-invalid-empty")
        state = _state(site)
        # Wiki pages often contain multiple links to the same page. Title normalization and parsing can become
        # expensive on pages with many links, so we can save a little time by caching them.
        if default_namespace == NS_MAIN:
            t = state.cache_get(text)
            if t is not None:
                return t
        # Convert things like &eacute; &#257; or &#x3017; into normalized (T16952) text
        filtered_text = decode_char_references_and_normalize(text)
        t = cls(site)
        db_key_form = filtered_text.replace(" ", "_")
        t._secure_and_split(db_key_form, int(default_namespace))
        if default_namespace == NS_MAIN:
            t._instance_cache_key = text
            state.cache_set(text, t)
        return t

    @classmethod
    def make_title(cls, ns: int, title: str, fragment: str = "", interwiki: str = "", *, site: Site) -> Title:
        """Create a new Title from a namespace index and a DB key.

        It's assumed that ns and title are safe, for instance when they came directly from the database or a
        special page name, not from user input. No validation is applied. For convenience, spaces are normalized to
        underscores."""
        t = cls(site)
        t._interwiki = interwiki
        t._fragment = cls._normalize_fragment(fragment)
        t._namespace = int(ns)
        t._dbkeyform = title.replace(" ", "_")
        t._urlform = wf_urlencode(t._dbkeyform)
        t._textform = title.replace("_", " ")
        return t

    @classmethod
    def make_title_safe(cls, ns: int, title: str, fragment: str = "", interwiki: str = "", *,
                        site: Site) -> Optional[Title]:
        """Create a new Title from a namespace index and a DB key. The parameters will be checked for validity,
        which is a bit slower than make_title() but safer for user-provided data. None on an error."""
        if not site.exists(ns):
            return None
        t = cls(site)
        db_key_form = cls.make_name(ns, title, fragment, interwiki, True, site=site)
        try:
            t._secure_and_split(db_key_form)
            return t
        except MalformedTitleException:
            return None

    @classmethod
    def new_main_page(cls, *, site: Site) -> Title:
        """Create a new Title for the Main Page (the 'mainpage' message)"""
        state = _state(site)
        if state.main_page_recursion_guard:
            # Somehow parsing the message contents has fallen back to the main page (bare local interwiki), so use
            # the hardcoded fallback (T297571).
            return cls.new_from_text("Main Page", site=site)
        state.main_page_recursion_guard = True
        try:
            title = cls.new_from_text(site.main_page, site=site)
        finally:
            state.main_page_recursion_guard = False
        # If the localised value is invalid, don't produce fatal errors that would make the wiki inaccessible (and
        # hard to fix the invalid message). Gracefully fallback...
        if title is None:
            title = cls.new_from_text("Main Page", site=site)
        return title

    @staticmethod
    def legal_chars(site: Site) -> str:
        """A regex character class describing the legal characters in a link ($wgLegalTitleChars, PCRE byte
        notation)"""
        return site.legal_title_chars

    @staticmethod
    def make_name(ns: int, title: str, fragment: str = "", interwiki: str = "", canonical_namespace: bool = False,
                  *, site: Site) -> str:
        """Make a prefixed DB key from a DB key and a namespace index"""
        if canonical_namespace:
            namespace = site.get_canonical_name(ns)
        else:
            namespace = site.get_ns_text(ns)
        name = title if not namespace else f"{namespace}:{title}"
        if str(interwiki) != "":
            name = f"{interwiki}:{name}"
        if str(fragment) != "":
            name += "#" + fragment
        return name

    @staticmethod
    def compare(a: Title, b: Title) -> int:
        """Callback for sorting titles by (namespace, title)"""
        if a.namespace != b.namespace:
            return -1 if a.namespace < b.namespace else 1
        return (a.db_key > b.db_key) - (a.db_key < b.db_key)

    @classmethod
    def capitalize(cls, text: str, ns: int = NS_MAIN, *, site: Site) -> str:
        """Capitalize a text string for a title if it belongs to a namespace that capitalizes"""
        return site.ucfirst(text) if site.is_capitalized(ns) else text

    def _secure_and_split(self, text: str, default_namespace: Optional[int] = None) -> None:
        """Secure and split - main initialisation function for this object.

        Assumes that text is urldecoded and uses underscores, but not otherwise munged. Raises
        MalformedTitleException on malformed titles; if this method returns normally, the Title is valid."""
        if default_namespace is None:
            default_namespace = self.DEFAULT_NAMESPACE
        parts = get_title_codec(self.site).split_title_string(text, default_namespace)
        # Fill fields
        self.set_fragment("#" + parts["fragment"])
        self._interwiki = parts["interwiki"]
        self._local_interwiki = parts["local_interwiki"]
        self._namespace = parts["namespace"]
        self._dbkeyform = parts["dbkey"]
        self._urlform = wf_urlencode(self._dbkeyform)
        self._textform = self._dbkeyform.replace("_", " ")
        # splitTitleString() guarantees that this title is valid.
        self._is_valid = True

    def _uncache(self) -> None:
        """Remove this instance from Title::newFromText()'s cache, before it changes."""
        if self._instance_cache_key is not None:
            _state(self.site).title_cache.pop(self._instance_cache_key, None)
            self._instance_cache_key = None

    # --- validity ---

    def is_valid(self) -> bool:
        """True if the title is a valid link target, and that it has been properly normalized. This method checks
        that the title is syntactically valid, and that the namespace it refers to exists."""
        if self._is_valid is not None:
            return self._is_valid
        try:
            text = self.full_text
            parts = get_title_codec(self.site).split_title_string(text, self._namespace)
            # Check that nothing changed! This ensures that text was already properly normalized.
            if (parts["fragment"] != self._fragment
                    or parts["interwiki"] != self._interwiki
                    or parts["local_interwiki"] != self._local_interwiki
                    or parts["namespace"] != self._namespace
                    or parts["dbkey"] != self._dbkeyform):
                self._is_valid = False
                return self._is_valid
        except MalformedTitleException:
            self._is_valid = False
            return self._is_valid
        self._is_valid = True
        return self._is_valid

    def can_exist(self) -> bool:
        """Can this title represent a page in the wiki's database? Titles can exist as pages in the database if
        they are valid, and they are not Special pages, interwiki links, or fragment-only links."""
        if self._is_valid is False:
            return False
        if self._namespace < NS_MAIN:
            return False
        if self.is_external():
            return False
        if self._textform == "":
            return False
        return self.is_valid()

    # --- interwiki ---

    def is_local(self) -> bool:
        """True if this is an in-project interwiki link or a wikilink, false otherwise"""
        if self.is_external():
            iw = self.site.fetch_interwiki(self._interwiki)
            if iw is not None:
                return iw.is_local()
        return True

    def is_external(self) -> bool:
        """Is this Title interwiki?"""
        return self._interwiki != ""

    @property
    def interwiki(self) -> str:
        """The interwiki prefix"""
        return self._interwiki

    def was_local_interwiki(self) -> bool:
        """Was this a local interwiki link?"""
        return self._local_interwiki

    def is_trans(self) -> bool:
        """True if this is a transcludable interwiki link (MediaWiki fails on an unknown prefix; this returns
        False)."""
        if not self.is_external():
            return False
        iw = self.site.fetch_interwiki(self._interwiki)
        return iw is not None and iw.is_transcludable()

    def get_trans_wiki_id(self) -> Optional[str]:
        """The DB name of the distant wiki which owns the object; None (PHP false) for a local title."""
        if not self.is_external():
            return None
        iw = self.site.fetch_interwiki(self._interwiki)
        return iw.wiki_id if iw is not None else None

    def get_title_value(self) -> Optional[TitleValue]:
        """A TitleValue representing this Title, None if there is none (e.g. invalid titles)."""
        try:
            assert_valid_spec(self._namespace, self._dbkeyform, self._fragment, self._interwiki)
        except ValueError:
            return None
        return TitleValue(self._namespace, self._dbkeyform, self._fragment, self._interwiki)

    # --- text forms ---

    @property
    def text(self) -> str:
        """The text form (spaces not underscores) of the main part"""
        return self._textform

    @property
    def partial_url(self) -> str:
        """The URL-encoded form of the main part"""
        return self._urlform

    @property
    def db_key(self) -> str:
        """The main part with underscores"""
        return self._dbkeyform

    @property
    def namespace(self) -> int:
        """The namespace index, i.e. one of the NS_xxxx constants."""
        return self._namespace

    @property
    def ns_text(self) -> Optional[str]:
        """The namespace text with underscores (not spaces), e.g. 'User_talk'; None (PHP false) for an unknown
        namespace"""
        if self.is_external():
            # This probably shouldn't even happen, except for interwiki transclusion. If possible, use the canonical
            # name for the foreign namespace.
            if self._namespace == NS_MAIN:
                # Optimisation
                return ""
            ns_text = self.site.get_canonical_name(self._namespace)
            if ns_text is not None:
                return ns_text
        try:
            return get_title_codec(self.site).get_namespace_name(self._namespace, self._dbkeyform)
        except ValueError:
            return None

    @property
    def subject_ns_text(self) -> Optional[str]:
        """The namespace text of the subject (rather than talk) page"""
        return self.site.get_ns_text(self.site.get_subject(self._namespace))

    @property
    def talk_ns_text(self) -> Optional[str]:
        """The namespace text of the talk page"""
        return self.site.get_ns_text(self.site.get_talk(self._namespace))

    def can_have_talk_page(self) -> bool:
        """False for relative section links (with text ''), interwiki links and pages in NS_SPECIAL."""
        if self._textform == "" or self._interwiki != "":
            return False
        return self._namespace >= NS_MAIN

    def is_special_page(self) -> bool:
        """True if this is a special page."""
        return self._namespace == NS_SPECIAL

    def in_namespace(self, ns: int) -> bool:
        """True if the title is inside the specified namespace."""
        return self._namespace == ns

    def in_namespaces(self, *namespaces) -> bool:
        """True if the title is inside one of the specified namespaces."""
        if namespaces and isinstance(namespaces[0], (list, tuple, set, frozenset)):
            namespaces = tuple(namespaces[0])
        return any(self.in_namespace(ns) for ns in namespaces)

    def has_subject_namespace(self, ns: int) -> bool:
        """True if the title has the same subject namespace as the namespace specified."""
        return self.site.subject_equals(self._namespace, ns)

    def is_main_page(self) -> bool:
        """Is this the mainpage?"""
        return self.equals(Title.new_main_page(site=self.site))

    def is_subpage(self) -> bool:
        """Is this a subpage?"""
        return "/" in self._textform if self.site.has_subpages(self._namespace) else False

    def is_talk_page(self) -> bool:
        """Is this a talk page of some sort?"""
        return self.site.is_talk(self._namespace)

    def get_talk_page(self) -> Title:
        """A Title object associated with the talk page of this article"""
        # Is this the same title?
        talk_ns = self.site.get_talk(self._namespace)
        if self._namespace == talk_ns:
            return self
        return Title.make_title(talk_ns, self._dbkeyform, site=self.site)

    def get_talk_page_if_defined(self) -> Optional[Title]:
        if not self.can_have_talk_page():
            return None
        return self.get_talk_page()

    def get_subject_page(self) -> Title:
        """A title object associated with the subject page of this talk page"""
        # Is this the same title?
        subject_ns = self.site.get_subject(self._namespace)
        if self._namespace == subject_ns:
            return self
        return Title.make_title(subject_ns, self._dbkeyform, site=self.site)

    def get_other_page(self) -> Title:
        """The other title for this page, if this is a subject page get the talk page, if it is a talk page get
        the subject page"""
        if self.is_special_page():
            raise ValueError("Special pages cannot have other pages")
        if self.is_talk_page():
            return self.get_subject_page()
        if not self.can_have_talk_page():
            raise ValueError(f"{self.prefixed_text} does not have an other page")
        return self.get_talk_page()

    # --- fragment ---

    @property
    def fragment(self) -> str:
        """The Title fragment (i.e. the bit after the #) in text form"""
        return self._fragment

    def has_fragment(self) -> bool:
        """Check if a Title fragment is set"""
        return self._fragment != ""

    @property
    def fragment_for_url(self) -> str:
        """The fragment in URL form, including the "#" character if there is one"""
        if not self.has_fragment():
            return ""
        elif self.is_external():
            # Note: If the interwiki is unknown, it's treated as a namespace on the local wiki, so we treat it like a
            # local interwiki.
            interwiki = self.site.fetch_interwiki(self._interwiki)
            if interwiki is not None and not interwiki.is_local():
                return "#" + escape_id_for_external_interwiki(self._fragment, self.site)
        return "#" + escape_id_for_link(self._fragment, self.site)

    def set_fragment(self, fragment: str) -> None:
        """Set the fragment for this title. Removes the first character from the specified fragment before setting,
        so it assumes you're passing it with an initial "#"."""
        self._uncache()
        self._fragment = self._normalize_fragment(fragment)

    def create_fragment_target(self, fragment: str) -> Title:
        """Creates a new Title for a different fragment of the same page."""
        return Title.make_title(self._namespace, self.text, fragment, self._interwiki, site=self.site)

    @staticmethod
    def _normalize_fragment(fragment: str) -> str:
        """Normalizes fragment part of the title."""
        if fragment.startswith("#"):
            fragment = fragment[1:]
        return fragment.replace("_", " ")

    # --- prefixed forms ---

    def _prefix(self, name: str) -> str:
        """Prefix some arbitrary text with the namespace or interwiki prefix of this object"""
        p = ""
        if self.is_external():
            p = self._interwiki + ":"
        if self._namespace != 0:
            ns_text = self.ns_text
            if ns_text is None:
                # See T165149. Awkward, but better than erroneously linking to the main namespace.
                ns_text = f"{self.site.get_ns_text(NS_SPECIAL)}:Badtitle/NS{self._namespace}"
            p += ns_text + ":"
        return p + name

    @property
    def prefixed_db_key(self) -> str:
        """The prefixed title, with underscores and any interwiki and namespace prefixes"""
        return self._prefix(self._dbkeyform).replace(" ", "_")

    @property
    def prefixed_text(self) -> str:
        """The prefixed title, with spaces. This is the form usually used for display"""
        if self._prefixed_text is None:
            self._prefixed_text = self._prefix(self._textform).replace("_", " ")
        return self._prefixed_text

    def __str__(self) -> str:
        return self.prefixed_text

    def __repr__(self) -> str:
        return f"Title({self.full_text!r})"

    @property
    def full_text(self) -> str:
        """The prefixed title with spaces, plus any fragment (part beginning with '#')"""
        text = self.prefixed_text
        if self.has_fragment():
            text += "#" + self._fragment
        return text

    # --- subpages ---

    @staticmethod
    def _find_subpage_divider(text: str, dir_: int) -> Optional[int]:
        """Finds the first or last subpage divider (slash) in the string. Any leading sequence of slashes is ignored,
        since it does not divide two parts of the string. Considering leading slashes dividers would result in
        empty root title or base title (T229443).

        Note that trailing slashes are considered dividers, and empty subpage names are allowed."""
        if dir_ > 0:
            # Skip leading slashes, but keep the last one when there is nothing but slashes
            bottom = len(text[:-1]) - len(text[:-1].lstrip("/"))  # strspn( $text, '/', 0, -1 )
            idx = text.find("/", bottom)
        else:
            # Any slash from the end can be a divider, as subpage names can be empty
            idx = text.rfind("/")
        # The first character can never be a divider, as that would result in an empty base
        return None if idx in (0, -1) else idx

    def _has_subpages_enabled(self) -> bool:
        """Whether this Title's namespace has subpages enabled."""
        return self.site.has_subpages(self._namespace)

    @property
    def root_text(self) -> str:
        """The root page name text without a namespace, i.e. the leftmost part before any slashes"""
        text = self.text
        if not self._has_subpages_enabled():
            return text
        first_slash_pos = self._find_subpage_divider(text, +1)
        # Don't discard the real title if there's no subpage involved
        if first_slash_pos is None:
            return text
        return text[:first_slash_pos]

    def get_root_title(self) -> Title:
        """The root page name title, i.e. the leftmost part before any slashes"""
        title = Title.make_title_safe(self._namespace, self.root_text, site=self.site)
        assert title is not None, "makeTitleSafe() should always return a Title for the text returned by getRootText()."
        return title

    @property
    def base_text(self) -> str:
        """The base page name without a namespace, i.e. the part before the subpage name"""
        text = self.text
        if not self._has_subpages_enabled():
            return text
        last_slash_pos = self._find_subpage_divider(text, -1)
        # Don't discard the real title if there's no subpage involved
        if last_slash_pos is None:
            return text
        return text[:last_slash_pos]

    def get_base_title(self) -> Title:
        """The base page name title, i.e. the part before the subpage name."""
        title = Title.make_title_safe(self._namespace, self.base_text, site=self.site)
        assert title is not None, "makeTitleSafe() should always return a Title for the text returned by getBaseText()."
        return title

    @property
    def subpage_text(self) -> str:
        """The lowest-level subpage name, i.e. the rightmost part after any slashes"""
        text = self.text
        if not self._has_subpages_enabled():
            return text
        last_slash_pos = self._find_subpage_divider(text, -1)
        if last_slash_pos is None:
            # T256922 - Return the title text if no subpages
            return text
        return text[last_slash_pos + 1:]

    def get_subpage(self, text: str) -> Optional[Title]:
        """The title for a subpage of the current page; None on an error"""
        return Title.make_title_safe(self._namespace, self.text + "/" + text, "", self._interwiki, site=self.site)

    @property
    def subpage_url_form(self) -> str:
        """A URL-encoded form of the subpage text"""
        return wf_urlencode(self.subpage_text.replace(" ", "_"))

    @property
    def prefixed_url(self) -> str:
        """A URL-encoded title (not an actual URL) including interwiki"""
        return wf_urlencode(self._prefix(self._dbkeyform).replace(" ", "_"))

    def is_subpage_of(self, title: Title) -> bool:
        """Check if this title is a subpage of another title"""
        return (self._interwiki == title._interwiki
                and self._namespace == title._namespace
                and self._dbkeyform.startswith(title._dbkeyform + "/"))

    # --- URLs ---

    @staticmethod
    def _fix_url_query_args(query: Union[str, Mapping]) -> str:
        """Title::fixUrlQueryArgs() without the deprecated second argument"""
        if isinstance(query, Mapping):
            query = wf_array_to_cgi(query)
        return query

    def get_full_url(self, query: Union[str, Mapping] = "", proto: Union[str, int, None, bool] = PROTO_RELATIVE) -> str:
        """A real URL referring to this title, with interwiki link and fragment"""
        query = self._fix_url_query_args(query)
        # Hand off all the decisions on urls to getLocalURL
        url = self.get_local_url(query)
        # Expand the url to make it a full url. Note that getLocalURL has the potential to output full urls for a
        # variety of reasons, so we use wfExpandUrl instead of simply prepending $wgServer
        url = wf_expand_url(url, self.site, proto)
        # Finally, add the fragment.
        url += self.fragment_for_url
        return url

    def get_local_url(self, query: Union[str, Mapping] = "") -> str:
        """A URL with no fragment or server name (relative URL). Interwiki titles give the interwiki's URL; the
        query is appended. ($wgActionPaths and $wgVariantArticlePath are not supported: as in the parser tests,
        a query gives "$wgScript?title=...&query".)"""
        config = self.site.config
        query = self._fix_url_query_args(query)
        interwiki = self.site.fetch_interwiki(self._interwiki)
        if interwiki is not None:
            namespace = self.ns_text or ""
            if namespace != "":
                # Can this actually happen? Interwikis shouldn't be parsed.
                # Yes! It can in interwiki transclusion. But... it probably shouldn't.
                namespace += ":"
            url = interwiki.get_url(namespace + self._dbkeyform)
            url = wf_append_query(url, query)
        else:
            dbkey = wf_urlencode(self.prefixed_db_key)
            if query == "":
                url = config.article_path.replace("$1", dbkey)
            else:
                if query == "-":
                    query = ""
                url = f"{config.script}?title={dbkey}&{query}"
        return url

    def get_link_url(self, query: Union[str, Mapping] = "", proto: Union[str, int, None, bool] = False) -> str:
        """The simplest URL that will be valid to link, locally, to the current Title. It includes the fragment,
        but does not include the server unless the link is external (or proto is given). If there's a fragment but
        the prefixed text is empty, we just return a link to the fragment.

        The result obviously should not be URL-escaped, but does need to be HTML-escaped if it's being output in
        HTML."""
        if self.is_external() or proto is not False:
            ret = self.get_full_url(query, proto)
        elif self.prefixed_text == "" and self.has_fragment():
            ret = self.fragment_for_url
        else:
            ret = self.get_local_url(query) + self.fragment_for_url
        return ret

    def get_internal_url(self, query: Union[str, Mapping] = "") -> str:
        """The URL form for an internal link ($wgInternalServer defaults to $wgServer)."""
        query = self._fix_url_query_args(query)
        return wf_expand_url(self.site.config.server + self.get_local_url(query), self.site, PROTO_HTTP)

    def get_canonical_url(self, query: Union[str, Mapping] = "") -> str:
        """The URL for a canonical link ($wgCanonicalServer defaults to $wgServer); includes the fragment."""
        query = self._fix_url_query_args(query)
        return wf_expand_url(self.get_local_url(query) + self.fragment_for_url, self.site, PROTO_CANONICAL)

    def get_edit_url(self) -> str:
        """The edit URL for this Title, or '' if this is an interwiki link"""
        if self.is_external():
            return ""
        return self.get_local_url("action=edit")

    # --- comparison ---

    def equals(self, other: object) -> bool:
        """True if other is a Title and refers to the same page (the fragment is ignored)."""
        if isinstance(other, Title):
            return (self._interwiki == other._interwiki
                    and self._namespace == other._namespace
                    and self._dbkeyform == other._dbkeyform)
        return False

    def is_same_link_as(self, other: Title) -> bool:
        """Like equals(), but also compares the fragment."""
        return self.equals(other) and self._fragment == other._fragment

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Title):
            return NotImplemented
        return self.equals(other)

    def __hash__(self) -> int:
        return hash((self._interwiki, self._namespace, self._dbkeyform))

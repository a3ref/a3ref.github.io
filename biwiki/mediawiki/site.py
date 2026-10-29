# Ported from MediaWiki 1.39 includes/title/NamespaceInfo.php, the namespace parts of
# includes/language/Language.php, languages/messages/MessagesEn.php ($namespaceNames, $namespaceAliases),
# includes/Defines.php (NS_* constants), includes/MainConfigSchema.php ($wgLegalTitleChars,
# $wgNamespacesWithSubpages), includes/interwiki/ClassicInterwikiLookup.php and Interwiki.php (lookup only),
# wfUrlencode() of includes/GlobalFunctions.php, maintenance/interwiki.list, and the interwiki and namespace setup
# of tests/parser/ParserTestRunner.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the wiki's namespaces, language (English
# only, no gender namespaces, no variants) and interwiki map gathered in one Site object built from a Config; no
# hooks, caches or database.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The wiki a title belongs to: namespaces, namespace names in English, the interwiki map."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .config import BIKI, TEST, Config

# includes/Defines.php
NS_MEDIA = -2
NS_SPECIAL = -1
NS_MAIN = 0
NS_TALK = 1
NS_USER = 2
NS_USER_TALK = 3
NS_PROJECT = 4
NS_PROJECT_TALK = 5
NS_FILE = 6
NS_FILE_TALK = 7
NS_MEDIAWIKI = 8
NS_MEDIAWIKI_TALK = 9
NS_TEMPLATE = 10
NS_TEMPLATE_TALK = 11
NS_HELP = 12
NS_HELP_TALK = 13
NS_CATEGORY = 14
NS_CATEGORY_TALK = 15

# NamespaceInfo::CANONICAL_NAMES ($wgCanonicalNamespaceNames)
CANONICAL_NAMES: dict[int, str] = {
    NS_MEDIA: "Media",
    NS_SPECIAL: "Special",
    NS_MAIN: "",
    NS_TALK: "Talk",
    NS_USER: "User",
    NS_USER_TALK: "User_talk",
    NS_PROJECT: "Project",
    NS_PROJECT_TALK: "Project_talk",
    NS_FILE: "File",
    NS_FILE_TALK: "File_talk",
    NS_MEDIAWIKI: "MediaWiki",
    NS_MEDIAWIKI_TALK: "MediaWiki_talk",
    NS_TEMPLATE: "Template",
    NS_TEMPLATE_TALK: "Template_talk",
    NS_HELP: "Help",
    NS_HELP_TALK: "Help_talk",
    NS_CATEGORY: "Category",
    NS_CATEGORY_TALK: "Category_talk",
}

# languages/messages/MessagesEn.php $namespaceNames
NAMESPACE_NAMES_EN: dict[int, str] = {
    NS_MEDIA: "Media",
    NS_SPECIAL: "Special",
    NS_MAIN: "",
    NS_TALK: "Talk",
    NS_USER: "User",
    NS_USER_TALK: "User_talk",
    # NS_PROJECT set by $wgMetaNamespace
    NS_PROJECT_TALK: "$1_talk",
    NS_FILE: "File",
    NS_FILE_TALK: "File_talk",
    NS_MEDIAWIKI: "MediaWiki",
    NS_MEDIAWIKI_TALK: "MediaWiki_talk",
    NS_TEMPLATE: "Template",
    NS_TEMPLATE_TALK: "Template_talk",
    NS_HELP: "Help",
    NS_HELP_TALK: "Help_talk",
    NS_CATEGORY: "Category",
    NS_CATEGORY_TALK: "Category_talk",
}

# languages/messages/MessagesEn.php $namespaceAliases
NAMESPACE_ALIASES_EN: dict[str, int] = {
    # The canonical names of namespaces 6 and 7 are, as of MediaWik 1.14, "File" and "File_talk". The old names
    # "Image" and "Image_talk" are retained as aliases for backwards compatibility.
    "Image": NS_FILE,
    "Image_talk": NS_FILE_TALK,
}

# $wgLegalTitleChars (MainConfigSchema default), a PCRE character class over UTF-8 *bytes*: \x80-\xFF lets every
# non-ASCII character through. MediaWikiTitleCodec turns it into a Python class over characters.
LEGAL_TITLE_CHARS = " %!\"$&'()*,\\-.\\/0-9:;=?@A-Z\\\\^_`a-z~\\x80-\\xFF+"

# $wgNamespacesWithSubpages (MainConfigSchema default)
NAMESPACES_WITH_SUBPAGES: dict[int, bool] = {
    NS_TALK: True,
    NS_USER: True,
    NS_USER_TALK: True,
    NS_PROJECT: True,
    NS_PROJECT_TALK: True,
    NS_FILE_TALK: True,
    NS_MEDIAWIKI: True,
    NS_MEDIAWIKI_TALK: True,
    NS_TEMPLATE: True,
    NS_TEMPLATE_TALK: True,
    NS_HELP: True,
    NS_HELP_TALK: True,
    NS_CATEGORY_TALK: True,
}

# English text of the 'mainpage' message (languages/i18n/en.json)
MAIN_PAGE = "Main Page"


def php_urlencode(s: str) -> str:
    """PHP urlencode() of the UTF-8 bytes: everything but [A-Za-z0-9_.-] percent-encoded, space as '+'."""
    out = []
    for b in s.encode("utf-8", "surrogatepass"):
        c = chr(b)
        if c.isascii() and (c.isalnum() or c in "_.-"):
            out.append(c)
        elif c == " ":
            out.append("+")
        else:
            out.append(f"%{b:02X}")
    return "".join(out)


_WF_URLENCODE = {"%3B": ";", "%40": "@", "%24": "$", "%21": "!", "%2A": "*", "%28": "(", "%29": ")", "%2C": ",",
                 "%2F": "/", "%7E": "~", "%3A": ":"}


def wf_urlencode(s: str) -> str:
    """wfUrlencode(): urlencode(), but keep ;@$!*(),/~: readable (not running on IIS 7)."""
    s = php_urlencode(s)
    for needle, char in _WF_URLENCODE.items():
        s = s.replace(needle, char)
    return s


def _parse_interwiki_list(text: str) -> tuple[dict, ...]:
    """Rows of maintenance/interwiki.list ("prefix|url|local|api"), as Installer::populateInterwikiTable() reads
    them."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        prefix, url, local, api = (line.split("|") + ["", "", "", ""])[:4]
        rows.append({"iw_prefix": prefix, "iw_url": url, "iw_local": int(local or 0), "iw_api": api})
    return tuple(rows)


# maintenance/interwiki.list: the interwiki table a new MediaWiki 1.39 installation starts with
DEFAULT_INTERWIKIS = _parse_interwiki_list("""
# Based more or less on the public interwiki map from MeatballWiki
# Default interwiki prefixes...
acronym|https://www.acronymfinder.com/~/search/af.aspx?string=exact&Acronym=$1|0|
advogato|http://www.advogato.org/$1|0|
arxiv|https://www.arxiv.org/abs/$1|0|
c2find|http://c2.com/cgi/wiki?FindPage&value=$1|0|
cache|https://www.google.com/search?q=cache:$1|0|
commons|https://commons.wikimedia.org/wiki/$1|0|https://commons.wikimedia.org/w/api.php
dictionary|http://www.dict.org/bin/Dict?Database=*&Form=Dict1&Strategy=*&Query=$1|0|
doi|https://dx.doi.org/$1|0|
drumcorpswiki|http://www.drumcorpswiki.com/$1|0|http://drumcorpswiki.com/api.php
dwjwiki|http://www.suberic.net/cgi-bin/dwj/wiki.cgi?$1|0|
elibre|http://enciclopedia.us.es/index.php/$1|0|http://enciclopedia.us.es/api.php
emacswiki|https://www.emacswiki.org/emacs/$1|0|
foldoc|https://foldoc.org/?$1|0|
foxwiki|https://fox.wikis.com/wc.dll?Wiki~$1|0|
freebsdman|https://www.FreeBSD.org/cgi/man.cgi?apropos=1&query=$1|0|
gentoo-wiki|http://gentoo-wiki.com/$1|0|
google|https://www.google.com/search?q=$1|0|
googlegroups|https://groups.google.com/groups?q=$1|0|
hammondwiki|http://www.dairiki.org/HammondWiki/$1|0|
hrwiki|http://www.hrwiki.org/wiki/$1|0|http://www.hrwiki.org/w/api.php
imdb|http://www.imdb.com/find?q=$1&tt=on|0|
kmwiki|https://kmwiki.wikispaces.com/$1|0|
linuxwiki|http://linuxwiki.de/$1|0|
lojban|https://mw.lojban.org/papri/$1|0|
lqwiki|http://wiki.linuxquestions.org/wiki/$1|0|
meatball|http://meatballwiki.org/wiki/$1|0|
mediawikiwiki|https://www.mediawiki.org/wiki/$1|0|https://www.mediawiki.org/w/api.php
memoryalpha|http://en.memory-alpha.org/wiki/$1|0|http://en.memory-alpha.org/api.php
metawiki|http://sunir.org/apps/meta.pl?$1|0|
metawikimedia|https://meta.wikimedia.org/wiki/$1|0|https://meta.wikimedia.org/w/api.php
mozillawiki|https://wiki.mozilla.org/$1|0|https://wiki.mozilla.org/api.php
mw|https://www.mediawiki.org/wiki/$1|0|https://www.mediawiki.org/w/api.php
oeis|https://oeis.org/$1|0|
openwiki|http://openwiki.com/ow.asp?$1|0|
pmid|https://www.ncbi.nlm.nih.gov/pubmed/$1?dopt=Abstract|0|
pythoninfo|https://wiki.python.org/moin/$1|0|
rfc|https://tools.ietf.org/html/rfc$1|0|
s23wiki|http://s23.org/wiki/$1|0|http://s23.org/w/api.php
seattlewireless|http://seattlewireless.net/$1|0|
senseislibrary|https://senseis.xmp.net/?$1|0|
shoutwiki|http://www.shoutwiki.com/wiki/$1|0|http://www.shoutwiki.com/w/api.php
squeak|http://wiki.squeak.org/squeak/$1|0|
tmbw|http://www.tmbw.net/wiki/$1|0|http://tmbw.net/wiki/api.php
tmnet|http://www.technomanifestos.net/?$1|0|
theopedia|https://www.theopedia.com/$1|0|
twiki|http://twiki.org/cgi-bin/view/$1|0|
uncyclopedia|https://en.uncyclopedia.co/wiki/$1|0|https://en.uncyclopedia.co/w/api.php
unreal|https://wiki.beyondunreal.com/$1|0|https://wiki.beyondunreal.com/w/api.php
usemod|http://www.usemod.com/cgi-bin/wiki.pl?$1|0|
wiki|http://c2.com/cgi/wiki?$1|0|
wikia|http://www.wikia.com/wiki/$1|0|
wikibooks|https://en.wikibooks.org/wiki/$1|0|https://en.wikibooks.org/w/api.php
wikidata|https://www.wikidata.org/wiki/$1|0|https://www.wikidata.org/w/api.php
wikif1|http://www.wikif1.org/$1|0|
wikihow|https://www.wikihow.com/$1|0|https://www.wikihow.com/api.php
wikinfo|http://wikinfo.co/English/index.php/$1|0|
wikimedia|https://foundation.wikimedia.org/wiki/$1|0|https://foundation.wikimedia.org/w/api.php
wikinews|https://en.wikinews.org/wiki/$1|0|https://en.wikinews.org/w/api.php
wikipedia|https://en.wikipedia.org/wiki/$1|0|https://en.wikipedia.org/w/api.php
wikiquote|https://en.wikiquote.org/wiki/$1|0|https://en.wikiquote.org/w/api.php
wikisource|https://wikisource.org/wiki/$1|0|https://wikisource.org/w/api.php
wikispecies|https://species.wikimedia.org/wiki/$1|0|https://species.wikimedia.org/w/api.php
wikiversity|https://en.wikiversity.org/wiki/$1|0|https://en.wikiversity.org/w/api.php
wikivoyage|https://en.wikivoyage.org/wiki/$1|0|https://en.wikivoyage.org/w/api.php
wikt|https://en.wiktionary.org/wiki/$1|0|https://en.wiktionary.org/w/api.php
wiktionary|https://en.wiktionary.org/wiki/$1|0|https://en.wiktionary.org/w/api.php
""")

# ParserTestRunner::appendInterwikiSetup() $testInterwikis
TEST_INTERWIKIS: tuple[dict, ...] = (
    # This is a "local interwiki" (see wgLocalInterwikis elsewhere in this file)
    {"iw_prefix": "local", "iw_url": "http://example.org/wiki/$1", "iw_local": 1},
    # Local interwiki that matches a namespace name (T228616)
    {"iw_prefix": "project", "iw_url": "http://example.org/wiki/$1", "iw_local": 1},
    {"iw_prefix": "wikipedia", "iw_url": "http://en.wikipedia.org/wiki/$1", "iw_local": 0},
    # this has been updated in the live wikis, but the parser tests expect the old value
    {"iw_prefix": "meatball", "iw_url": "http://www.usemod.com/cgi-bin/mb.pl?$1", "iw_local": 0},
    {"iw_prefix": "memoryalpha", "iw_url": "http://www.memory-alpha.org/en/index.php/$1", "iw_local": 0},
    {"iw_prefix": "zh", "iw_url": "http://zh.wikipedia.org/wiki/$1", "iw_local": 1},
    {"iw_prefix": "es", "iw_url": "http://es.wikipedia.org/wiki/$1", "iw_local": 1},
    {"iw_prefix": "fr", "iw_url": "http://fr.wikipedia.org/wiki/$1", "iw_local": 1},
    {"iw_prefix": "ru", "iw_url": "http://ru.wikipedia.org/wiki/$1", "iw_local": 1},
    # This is a "local interwiki" (see wgLocalInterwikis elsewhere in this file)
    {"iw_prefix": "mi", "iw_url": "http://example.org/wiki/$1", "iw_local": 1},
    {"iw_prefix": "mul", "iw_url": "http://wikisource.org/wiki/$1", "iw_local": 1},
    # Additions from Parsoid
    {"iw_prefix": "en", "iw_url": "//en.wikipedia.org/wiki/$1", "iw_local": 1},
    {"iw_prefix": "stats", "iw_url": "https://stats.wikimedia.org/$1", "iw_local": 1},
    {"iw_prefix": "gerrit", "iw_url": "https://gerrit.wikimedia.org/$1", "iw_local": 1},
    # Deliberately missing a $1 in the URL to exercise a common misconfiguration.
    {"iw_prefix": "wikinvest", "iw_url": "https://meta.wikimedia.org/wiki/Interwiki_map/discontinued#Wikinvest",
     "iw_local": 1},
)

# ParserTestRunner::appendInterwikiSetup(): "These interwikis should have 'iw_url' that matches wgServer."
TEST_LOCAL_INTERWIKIS = ("local", "project", "mi")

# ParserTestRunner::appendNamespaceSetup(): a namespace shadowing a interwiki link, to test proper precedence when
# resolving links. (T53680)
TEST_EXTRA_NAMESPACES = {100: "MemoryAlpha", 101: "MemoryAlpha_talk"}


@dataclass(frozen=True)
class Interwiki:
    """One row of the interwiki table (includes/interwiki/Interwiki.php)."""
    prefix: str
    url: str
    api: str = ""
    wiki_id: str = ""
    local: bool = False
    trans: bool = False

    def is_valid(self) -> bool:
        """Check whether an interwiki prefix exists"""
        return self.url != ""

    def get_url(self, title: Optional[str] = None) -> str:
        """Get the URL for a particular title (or with $1 if no title given)"""
        url = self.url
        if title is not None:
            url = url.replace("$1", wf_urlencode(title))
        return url

    def is_local(self) -> bool:
        """Is this a local link from a sister project, or is it something outside, like Google"""
        return self.local

    def is_transcludable(self) -> bool:
        """Can pages from this wiki be transcluded? Still requires $wgEnableScaryTransclusion."""
        return self.trans


class Site:
    """The wiki: its Config, namespaces (NamespaceInfo and the namespace parts of Language for English) and its
    interwiki map (InterwikiLookup)."""

    def __init__(self, config: Config, *, extra_namespaces: Optional[Mapping[int, str]] = None,
                 namespace_aliases: Optional[Mapping[str, int]] = None, meta_namespace_talk: Optional[str] = None,
                 namespaces_with_subpages: Optional[Mapping[int, bool]] = None,
                 capital_link_overrides: Optional[Mapping[int, bool]] = None,
                 interwikis: Iterable[Mapping] = (), local_interwikis: Iterable[str] = (),
                 legal_title_chars: str = LEGAL_TITLE_CHARS, main_page: str = MAIN_PAGE):
        self.config = config
        # $wgMetaNamespace; Setup.php derives it from $wgSitename with underscores, namespace names never have
        # spaces
        self.meta_namespace = config.meta_namespace.replace(" ", "_")
        self.meta_namespace_talk = meta_namespace_talk
        self.extra_namespaces: dict[int, str] = dict(extra_namespaces or {})
        self.config_namespace_aliases: dict[str, int] = dict(namespace_aliases or {})  # $wgNamespaceAliases
        self.namespaces_with_subpages: dict[int, bool] = dict(
            NAMESPACES_WITH_SUBPAGES if namespaces_with_subpages is None else namespaces_with_subpages)
        self.capital_link_overrides: dict[int, bool] = dict(capital_link_overrides or {})
        self.local_interwikis: tuple[str, ...] = tuple(local_interwikis)  # $wgLocalInterwikis
        self.legal_title_chars = legal_title_chars
        self.main_page = main_page  # the 'mainpage' message
        self.interwikis: dict[str, Interwiki] = {}
        for row in interwikis:
            prefix = row["iw_prefix"]
            self.interwikis[self.lc(prefix)] = Interwiki(
                prefix, row["iw_url"], row.get("iw_api", ""), row.get("iw_wikiid", ""),
                bool(row.get("iw_local", 0)), bool(row.get("iw_trans", 0)))

        # NamespaceInfo::getCanonicalNamespaces()
        self.canonical_namespaces: dict[int, str] = {NS_MAIN: "", **CANONICAL_NAMES}
        for index, name in self.extra_namespaces.items():
            self.canonical_namespaces.setdefault(index, name)
        self._namespace_indexes = {name.lower(): index for index, name in self.canonical_namespaces.items()}
        self.namespace_names = self._get_namespaces()
        self.namespace_aliases = self._get_namespace_aliases()
        self.namespace_ids = self._get_namespace_ids()

    # --- Language (English) ---

    @staticmethod
    def lc(text: str) -> str:
        """Language::lc(): mb_strtolower(), or strtolower() for ASCII text (the same thing)."""
        return text.lower()

    @staticmethod
    def ucfirst(text: str) -> str:
        """Language::ucfirst()"""
        if not text:
            return text
        octet_code = ord(text[0])
        if octet_code < 96:
            # Assume this is an uppercase/uncased ASCII character
            return text
        elif octet_code < 128:
            # Assume this is a lowercase/uncased ASCII character
            return text[0].upper() + text[1:]
        # mbUpperChar(): mb_strtoupper(), $wgOverrideUcfirstCharacters is empty by default
        return text[0].upper() + text[1:]

    def _fix_variable_in_namespace(self, talk: str) -> str:
        """Language::fixVariableInNamespace(); English has no {{grammar:}} forms."""
        if "$1" not in talk:
            return talk
        talk = talk.replace("$1", self.meta_namespace)
        return talk.replace(" ", "_")

    def _get_namespaces(self) -> dict[int, str]:
        """Language::getNamespaces(): localised namespaces indexed by their numbers."""
        names: dict[int, str] = dict(self.extra_namespaces)
        for index, name in NAMESPACE_NAMES_EN.items():
            names.setdefault(index, name)
        for index, name in self.canonical_namespaces.items():
            names.setdefault(index, name)
        names[NS_PROJECT] = self.meta_namespace
        if self.meta_namespace_talk:
            names[NS_PROJECT_TALK] = self.meta_namespace_talk
        else:
            names[NS_PROJECT_TALK] = self._fix_variable_in_namespace(names[NS_PROJECT_TALK])
        # Sometimes a language will be localised but not actually exist on this wiki.
        names = {index: name for index, name in names.items() if index in self.canonical_namespaces}
        # Re-order by namespace ID number...
        return dict(sorted(names.items()))

    def _get_namespace_aliases(self) -> dict[str, int]:
        """Language::getNamespaceAliases()"""
        aliases: dict[str, int] = {}
        for name, index in NAMESPACE_ALIASES_EN.items():
            if index == NS_PROJECT_TALK:
                name = self._fix_variable_in_namespace(name)
            aliases[name] = index
        # In the case of conflicts between $wgNamespaceAliases and other sources of aliasing, $wgNamespaceAliases
        # wins.
        aliases = {**aliases, **self.config_namespace_aliases}
        # Filter out aliases to namespaces that don't exist
        return {name: index for name, index in aliases.items() if index in self.namespace_names}

    def _get_namespace_ids(self) -> dict[str, int]:
        """Language::getNamespaceIds(): namespace IDs indexed by lower-cased localized name"""
        ids: dict[str, int] = {}
        for index, name in self.namespace_names.items():
            ids[self.lc(name)] = index
        for name, index in self.namespace_aliases.items():
            ids[self.lc(name)] = index
        return ids

    def get_ns_text(self, index: int) -> Optional[str]:
        """Language::getNsText(): namespace name with underscores, e.g. 'MediaWiki_talk'; None (PHP false) if
        the namespace does not exist."""
        return self.namespace_names.get(index)

    def get_formatted_ns_text(self, index: int) -> str:
        """Language::getFormattedNsText(): getNsText() with spaces, '' for an unknown namespace."""
        return (self.get_ns_text(index) or "").replace("_", " ")

    def get_local_ns_index(self, text: str) -> Optional[int]:
        """Language::getLocalNsIndex(): only the local names, case insensitive."""
        return self.namespace_ids.get(self.lc(text))

    def get_ns_index(self, text: str) -> Optional[int]:
        """Language::getNsIndex(): a namespace key by value, case insensitive. Canonical namespace names override
        custom ones defined for the current language. None stands for PHP false."""
        lctext = self.lc(text)
        ns = self.get_canonical_index(lctext)
        if ns is not None:
            return ns
        return self.namespace_ids.get(lctext)

    # --- NamespaceInfo ---

    def get_canonical_name(self, index: int) -> Optional[str]:
        """NamespaceInfo::getCanonicalName(); None (PHP false) for an unknown namespace."""
        return self.canonical_namespaces.get(index)

    def get_canonical_index(self, name: str) -> Optional[int]:
        """NamespaceInfo::getCanonicalIndex(): the index for a lower-cased canonical name, or None."""
        return self._namespace_indexes.get(name)

    def exists(self, index: int) -> bool:
        """NamespaceInfo::exists(): returns whether the specified namespace exists"""
        return index in self.canonical_namespaces

    def get_valid_namespaces(self) -> list[int]:
        """NamespaceInfo::getValidNamespaces(): the namespaces that can hold pages (index >= 0)"""
        return sorted(ns for ns in self.canonical_namespaces if ns >= 0)

    @staticmethod
    def is_talk(index: int) -> bool:
        """NamespaceInfo::isTalk()"""
        return index > NS_MAIN and index % 2 == 1

    def is_subject(self, index: int) -> bool:
        return not self.is_talk(index)

    def get_talk(self, index: int) -> int:
        """NamespaceInfo::getTalk(): the talk namespace index for a given namespace"""
        if index < NS_MAIN:
            raise ValueError(f"getTalk does not make any sense for given namespace {index}")
        return index if self.is_talk(index) else index + 1

    def get_subject(self, index: int) -> int:
        """NamespaceInfo::getSubject(): the subject namespace index for a given namespace"""
        # Handle special namespaces
        if index < NS_MAIN:
            return index
        return index - 1 if self.is_talk(index) else index

    def subject_equals(self, ns1: int, ns2: int) -> bool:
        return self.get_subject(ns1) == self.get_subject(ns2)

    def has_subpages(self, index: int) -> bool:
        """NamespaceInfo::hasSubpages(): does the namespace allow subpages?"""
        return bool(self.namespaces_with_subpages.get(index))

    def is_capitalized(self, index: int) -> bool:
        """NamespaceInfo::isCapitalized(): is the namespace first-letter capitalized?"""
        # Turn NS_MEDIA into NS_FILE
        index = NS_FILE if index == NS_MEDIA else index
        # Make sure to get the subject of our namespace
        index = self.get_subject(index)
        # Some namespaces are special and should always be upper case
        if index in (NS_SPECIAL, NS_USER, NS_MEDIAWIKI):
            return True
        if index in self.capital_link_overrides:
            # CapitalLinkOverrides is explicitly set
            return self.capital_link_overrides[index]
        # Default to the global setting
        return self.config.capital_links

    # --- InterwikiLookup ---

    def fetch_interwiki(self, prefix: str) -> Optional[Interwiki]:
        """InterwikiLookup::fetch(): the Interwiki for a prefix (case insensitive), or None."""
        if prefix == "":
            return None
        return self.interwikis.get(self.lc(prefix))

    def is_valid_interwiki(self, prefix: str) -> bool:
        """InterwikiLookup::isValidInterwiki()"""
        return self.fetch_interwiki(prefix) is not None


def test_site(subpages: bool = False, config: Config = TEST) -> Site:
    """The wiki of MediaWiki's parser tests (ParserTestRunner): Config TEST, Project namespace "TestWiki", the
    MemoryAlpha namespaces, the test interwikis. Subpages are off in every namespace unless a test has the
    "subpage" option."""
    site = Site(config, extra_namespaces=TEST_EXTRA_NAMESPACES, interwikis=TEST_INTERWIKIS,
                local_interwikis=TEST_LOCAL_INTERWIKIS)
    site.namespaces_with_subpages = {ns: subpages for ns in site.get_valid_namespaces()}
    return site


test_site.__test__ = False  # not a test for test runners that collect test_* functions


def biki_site(config: Config = BIKI) -> Site:
    """The Bohemia Interactive Community wiki: Config BIKI (case-sensitive titles), and its namespaces (with their
    capitalisation and subpage settings), namespace aliases, interwiki map and main page as its API reports them
    (biki_siteinfo.json, from meta=siteinfo)."""
    import json
    from pathlib import Path

    info = json.loads((Path(__file__).with_name("biki_siteinfo.json")).read_text(encoding="utf-8"))
    namespaces = {int(k): v for k, v in info["namespaces"].items()}
    # canonical names with underscores, as $wgExtraNamespaces holds them (the API shows them with spaces)
    extra = {i: ns.get("canonical", ns["name"]).replace(" ", "_") for i, ns in namespaces.items()
             if i not in CANONICAL_NAMES and i != NS_MAIN}
    interwikis = [{"iw_prefix": iw["prefix"], "iw_url": iw["url"], "iw_local": int(bool(iw.get("local"))),
                   "iw_trans": int(bool(iw.get("trans")))} for iw in info["interwikimap"]]
    return Site(
        config,
        extra_namespaces=extra,
        namespace_aliases={a["alias"].replace(" ", "_"): a["id"] for a in info["namespacealiases"]},
        namespaces_with_subpages={i: bool(ns.get("subpages")) for i, ns in namespaces.items()},
        # 'case' per namespace: first-letter or case-sensitive
        capital_link_overrides={i: ns["case"] == "first-letter" for i, ns in namespaces.items() if i >= 0},
        interwikis=interwikis,
        local_interwikis=[iw["prefix"] for iw in info["interwikimap"] if iw.get("localinterwiki")],
        main_page=info["general"]["mainpage"],
    )

# Ported from MediaWiki 1.39 includes/MagicWord.php, includes/MagicWordArray.php and includes/MagicWordFactory.php
# (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; English only (the content language of the
# BI wiki), magic words from magicwords_en.py and extensions; no hooks. Python group names cannot hold magic word
# IDs such as "!" or "img_width", so MagicWordArray numbers its groups and keeps the IDs aside.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Magic words: __NOTOC__, {{PAGENAME}}, #REDIRECT, ... in the content language (English)."""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional, Union

from . import magicwords_en


def lc(text: str) -> str:
    """Language::lc() for English: mb_strtolower()."""
    return text.lower()


class MagicWord:
    """One magic word: an ID, its synonyms, and whether they are case sensitive."""

    def __init__(self, id_: str, synonyms: Iterable[str], case_sensitive: bool):
        self.id = id_
        self.synonyms = list(synonyms)
        self.case_sensitive = case_sensitive
        self._regex: Optional[re.Pattern] = None
        self.modified = False
        self._found = False

    def init_regex(self) -> None:
        # Sort the synonyms by length, descending, so that the longest synonym matches in precedence to the shortest
        synonyms = sorted(self.synonyms, key=lambda s: len(s.encode("utf-8")), reverse=True)
        self.base_regex = "|".join(re.escape(s) for s in synonyms)
        flags = 0 if self.case_sensitive else re.I
        self._regex = re.compile(self.base_regex, flags)
        self.regex_start = re.compile(f"^(?:{self.base_regex})", flags)
        self.regex_start_to_end = re.compile(f"^(?:{self.base_regex})$", flags)
        self.variable_regex = re.compile(self.base_regex.replace(r"\$1", "(.*?)"), flags)
        self.variable_start_to_end_regex = re.compile(f"^(?:{self.base_regex})$".replace(r"\$1", "(.*?)"), flags)

    @property
    def regex(self) -> re.Pattern:
        """Gets a regex representing matching the word"""
        if self._regex is None:
            self.init_regex()
        return self._regex

    def get_base_regex(self) -> str:
        """regex without the slashes and what not"""
        self.regex  # noqa: B018 - initialises the regexes
        return self.base_regex

    def match(self, text: Optional[str]) -> bool:
        """Returns true if the text contains the word"""
        return self.regex.search(text or "") is not None

    def match_start(self, text: str) -> bool:
        """Returns true if the text starts with the word"""
        self.regex  # noqa: B018
        return self.regex_start.search(text) is not None

    def match_start_to_end(self, text: Optional[str]) -> bool:
        """Returns true if the text matched the word"""
        self.regex  # noqa: B018
        return self.regex_start_to_end.search(text or "") is not None

    def match_variable_start_to_end(self, text: str) -> Optional[str]:
        """Returns None if there's no match, the value of $1 otherwise. The return code is the matched string, if
        there's no variable part in the regex and the matched variable part ($1) if there is one."""
        self.regex  # noqa: B018
        m = self.variable_start_to_end_regex.search(text)
        if not m:
            return None
        # multiple matched parts (variable match); some will be empty because of synonyms. The variable will be the
        # second non-empty one so remove any blank elements and re-sort the indices. See also T8526
        matches = [x for x in (m.group(0), *m.groups()) if x]
        return matches[0] if len(matches) == 1 else matches[1]

    def match_and_remove(self, text: str) -> tuple[bool, str]:
        """Whether the text matches the word, and the text with all instances of the word removed."""
        new, n = self.regex.subn("", text or "")
        return n > 0, new

    def match_start_and_remove(self, text: str) -> tuple[bool, str]:
        self.regex  # noqa: B018
        new, n = self.regex_start.subn("", text or "")
        return n > 0, new

    def replace(self, replacement: str, subject: str, limit: int = -1) -> str:
        """Replaces the word with something else"""
        res = self.regex.sub(lambda m: replacement, subject or "", count=0 if limit < 0 else limit)
        self.modified = res != subject
        return res

    def substitute_callback(self, text: str, callback: Callable[[re.Match], str]) -> str:
        """Variable handling: {{SUBST:xxx}} style words. Calls back a function to determine what to replace xxx
        with. Input word must contain $1"""
        self.regex  # noqa: B018
        res = self.variable_regex.sub(callback, text)
        self.modified = res != text
        return res

    def get_synonym(self, i: int) -> str:
        return self.synonyms[i]

    def add_to_array(self, array: dict, value) -> None:
        """Adds all the synonyms of this MagicWord to an array, to allow quick lookup in a list of magic words"""
        for syn in self.synonyms:
            array[lc(syn)] = value


class MagicWordArray:
    """A collection of magic words, matched together."""

    def __init__(self, names: Iterable[str] = (), factory: Optional["MagicWordFactory"] = None):
        self.names = list(names)
        self.factory = factory or FACTORY
        self._hash: Optional[dict[int, dict[str, str]]] = None
        self._base: Optional[tuple[dict[int, str], dict[str, str]]] = None

    def add(self, name: str) -> None:
        """Add a magic word by name"""
        self.names.append(name)
        self._hash = self._base = None

    def add_array(self, names: Iterable[str]) -> None:
        """Add a number of magic words by name"""
        self.names.extend(names)
        self._hash = self._base = None

    def get_hash(self) -> dict[int, dict[str, str]]:
        """Get a 2-d hashtable for this array: case sensitive (1) or not (0) -> synonym -> ID"""
        if self._hash is None:
            self._hash = {0: {}, 1: {}}
            for name in self.names:
                magic = self.factory.get(name)
                case = int(magic.case_sensitive)
                for syn in magic.synonyms:
                    if not case:
                        syn = lc(syn)
                    self._hash[case][syn] = name
        return self._hash

    def get_base_regex(self) -> tuple[dict[int, str], dict[str, str]]:
        """The base regex for case-insensitive (0) and case-sensitive (1) synonyms, with one named group per
        synonym, and the magic word ID of each group name."""
        if self._base is not None:
            return self._base
        regex: dict[int, list[str]] = {0: [], 1: []}
        groups: dict[str, str] = {}
        for name in self.names:
            magic = self.factory.get(name)
            case = 1 if magic.case_sensitive else 0
            for syn in magic.synonyms:
                group = f"g{len(groups)}"
                groups[group] = name
                regex[case].append(f"(?P<{group}>{re.escape(syn)})")
        base = {}
        for case, parts in regex.items():
            re_ = "|".join(parts) if parts else "(?!)"
            base[case] = re_ if case else f"(?i:{re_})"
        self._base = (base, groups)
        return self._base

    def _compiled(self, template: str, variable: bool) -> list[tuple[re.Pattern, dict[str, str]]]:
        base, groups = self.get_base_regex()
        out = []
        for case in (0, 1):
            re_ = template.format(base[case])
            if variable:
                re_ = re_.replace(r"\$1", "(.*?)")
            out.append((re.compile(re_), groups))
        return out

    def get_regex(self):
        """Get an unanchored regex that does not match parameters"""
        return self._compiled("{}", False)

    def get_variable_regex(self):
        """Get a regex for matching variables with parameters"""
        return self._compiled("{}", True)

    def get_regex_start(self):
        """Get a regex anchored to the start of the string that does not match parameters"""
        return self._compiled("^(?:{})", False)

    def get_variable_start_to_end_regex(self):
        """Get an anchored regex for matching variables with parameters"""
        return self._compiled("^(?:{})$", True)

    @staticmethod
    def _parse_match(m: re.Match, groups: dict[str, str]) -> tuple[str, str, Union[str, bool]]:
        """(magic word ID, matched synonym, parameter value, or False if there is none)"""
        for group, name in groups.items():
            if group in m.re.groupindex and m.group(group):  # each regex holds the groups of one case only
                index = m.re.groupindex[group]
                # PHP's match array leaves out unmatched groups at the end: no parameter is False there
                last = max((i for i in range(1, m.re.groups + 1) if m.group(i) is not None), default=0)
                param: Union[str, bool] = (m.group(index + 1) or "") if index + 1 <= last else False
                return name, m.group(group), param
        raise ValueError("MagicWordArray: parameter not found")

    def match_variable_start_to_end(self, text: str) -> tuple[Union[str, bool], Union[str, bool]]:
        """Match some text, with parameter capture: (magic word ID, parameter), both False if there was no match."""
        for regex, groups in self.get_variable_start_to_end_regex():
            m = regex.search(text)
            if m:
                id_, _alias, param = self._parse_match(m, groups)
                return id_, param
        return False, False

    def match_start_to_end(self, text: str) -> Union[str, bool]:
        """Match some text, without parameter capture: the magic word ID, or False if there was no match"""
        hash_ = self.get_hash()
        if text in hash_[1]:
            return hash_[1][text]
        return hash_[0].get(lc(text), False)

    def match_and_remove(self, text: str, return_alias: bool = False) -> tuple[dict[str, Union[str, bool]], str]:
        """ID -> parameter value (or the alias matched, ``return_alias``) for all items that match, and the text
        with the matched items removed."""
        found: dict[str, Union[str, bool]] = {}
        for regex, groups in self.get_regex():
            def sub(m: re.Match) -> str:
                name, alias, param = self._parse_match(m, groups)
                found[name] = alias if return_alias else param
                return ""

            text = regex.sub(sub, text)
        return found, text

    def match_start_and_remove(self, text: str) -> tuple[Union[str, bool], str]:
        """The ID of the magic word at the start of text and the text without it; (False, text) if none."""
        for regex, groups in self.get_regex_start():
            m = regex.search(text)
            if m:
                id_, _alias, _param = self._parse_match(m, groups)
                return id_, text[len(m.group(0)):]
        return False, text


class MagicWordFactory:
    """Creates and caches the MagicWord objects; extensions add their words with ``register``."""

    def __init__(self):
        self.words: dict[str, tuple[bool, tuple[str, ...]]] = dict(magicwords_en.MAGIC_WORDS)
        self.variable_ids: list[str] = list(magicwords_en.VARIABLE_IDS)
        self.double_underscore_ids: list[str] = list(magicwords_en.DOUBLE_UNDERSCORE_IDS)
        self.subst_ids: list[str] = list(magicwords_en.SUBST_IDS)
        self.cache_ttls: dict[str, int] = dict(magicwords_en.CACHE_TTLS)
        self._objects: dict[str, MagicWord] = {}
        self._double_underscore_array: Optional[MagicWordArray] = None

    def register(self, id_: str, case_sensitive: bool, *synonyms: str) -> None:
        """An extension's magic word ($magicWords of its i18n.magic.php)."""
        self.words[id_] = (case_sensitive, tuple(synonyms))
        self._objects.pop(id_, None)

    def get(self, id_: str) -> MagicWord:
        """Factory: creates an object representing an ID"""
        if id_ not in self._objects:
            if id_ not in self.words:
                raise KeyError(f"Error: invalid magic word '{id_}'")
            case, synonyms = self.words[id_]
            self._objects[id_] = MagicWord(id_, synonyms, case)
        return self._objects[id_]

    def get_variable_ids(self) -> list[str]:
        """Get an array of parser variable IDs"""
        return self.variable_ids

    def get_subst_ids(self) -> list[str]:
        """Get an array of parser substitution modifier IDs"""
        return self.subst_ids

    def get_cache_ttl(self, id_: str) -> int:
        """Allow external reads of TTL array"""
        return self.cache_ttls.get(id_, -1)

    def get_double_underscore_array(self) -> MagicWordArray:
        """Get a MagicWordArray of double-underscore entities"""
        if self._double_underscore_array is None:
            self._double_underscore_array = self.new_array(self.double_underscore_ids)
        return self._double_underscore_array

    def new_array(self, names: Iterable[str] = ()) -> MagicWordArray:
        """Get a new MagicWordArray with provided names"""
        return MagicWordArray(names, self)


FACTORY = MagicWordFactory()

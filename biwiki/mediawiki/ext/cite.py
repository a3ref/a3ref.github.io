# Ported from the Cite extension of MediaWiki 1.39.0 (https://www.mediawiki.org/wiki/Extension:Cite,
# https://gerrit.wikimedia.org/r/mediawiki/extensions/Cite, commit 951ea9c64b72b0bd1ed8119f8d4c8ca4e2948454, the
# submodule of MediaWiki's tag 1.39.0): src/Cite.php, src/ReferenceStack.php, src/ReferencesFormatter.php,
# src/FootnoteMarkFormatter.php, src/AnchorFormatter.php, src/ErrorReporter.php, src/ReferenceMessageLocalizer.php,
# src/Hooks/CiteParserTagHooks.php and src/Hooks/CiteParserHooks.php. (C) Ævar Arnfjörð Bjarmason and the Cite
# contributors, GPL-2.0-or-later.
# Changed by a3ref contributors on 2026-10-30: translated to Python; one module; English content and interface
# language; no ResourceLoader modules, section previews or VisualEditor configuration; $wgCiteBookReferencing and
# $wgCiteResponsiveReferences are read from the parser's Config (cite_book_referencing, cite_responsive_references);
# MessageCache::get()'s whitespace fix of message texts is done in ReferenceMessageLocalizer; ParserClearState is
# emulated by keeping the state per ParserOutput.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""A parser extension that adds two tags, <ref> and <references> for adding citations to pages.

Parser interface: set_hook, recursive_tag_parse, get_strip_state, get_output (page_properties),
add_tracking_category, config, frame.set_volatile(); and a ParserAfterParse hook point to add the references of a
page without <references /> (see ``register``).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional, Union

from ..coreparserfunctions import ENGLISH, _replace_message_params, fetch_message
from ..html import close_element, element, expand_attributes, htmlspecialchars, open_element, raw_element
from ..sanitizer import escape_class, escape_id_for_link, safe_encode_attribute
from ..stripstate import MARKER_PREFIX

DEFAULT_GROUP = ""

# Wikitext attribute name for Book Referencing.
BOOK_REF_ATTRIBUTE = "extends"

# Page property key for the Book Referencing `extends` attribute.
BOOK_REF_PROPERTY = "ref-extends"

Error = tuple  # (message key, *params), an error of a StatusValue


def _truthy(value: Optional[str]) -> bool:
    """PHP's truthiness of a string: '' and '0' are false."""
    return value is not None and value != "" and value != "0"


def _ctype_digit(value: Optional[str]) -> bool:
    return bool(value) and value.isascii() and value.isdigit()


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


# ======================================================================================================================
# Messages (ReferenceMessageLocalizer, ErrorReporter)
# ======================================================================================================================

class ReferenceMessageLocalizer:
    """Interface abstracts everything a Cite needs to do with languages: messages of the content language (pages in
    the MediaWiki namespace override the English ones)."""

    def __init__(self, parser):
        self.parser = parser

    def localize_separators(self, number: str) -> str:
        # Filter to make sure characters are never removed (English has no separator transform table)
        return number

    def localize_digits(self, number: Any) -> str:
        """Transliterate numerals, without adding or changing separators."""
        return ENGLISH.format_num_no_separators(number)

    def _fetch(self, key: str) -> Optional[str]:
        """MessageCache::get(), including its whitespace fix (``&#32;`` and the ``&nbsp;`` forms in message texts
        become the characters), which ``fetch_message`` does not do yet."""
        text = fetch_message(self.parser, key)
        if text is not None:
            # Fix whitespace
            for search, replace in (("&#32;", " "), ("&nbsp;", " "), ("&#160;", " "),
                                    ("&#xA0;", " ")):
                text = text.replace(search, replace)
        return text

    def plain(self, key: str, *params) -> str:
        """wfMessage( $key, ...$params )->plain()"""
        text = self._fetch(key)
        if text is None:
            # (Message::toString() for a missing message)
            return "⧼" + htmlspecialchars(key) + "⧽"
        return _replace_message_params(text, tuple(str(p) for p in params))

    text = plain  # Message::text() equals plain() for messages without {{...}}

    def is_disabled(self, key: str) -> bool:
        """Message::isDisabled(): the message does not exist, is empty or is '-'."""
        text = self._fetch(key)
        return text is None or text == "" or text == "-"


class ErrorReporter:
    def __init__(self, message_localizer: ReferenceMessageLocalizer):
        self.message_localizer = message_localizer

    def half_parsed(self, parser, key: str, *params) -> str:
        """The error message, parsed as wikitext, in a <span class="error mw-ext-cite-error"> (HTML)"""
        msg = self._msg(parser, key, *params)
        wikitext = parser.recursive_tag_parse(msg)
        return self._wrap_in_html_container(wikitext, key)

    def plain(self, parser, key: str, *params) -> str:
        """The error message as wikitext, in a <span class="error mw-ext-cite-error">"""
        msg = self._msg(parser, key, *params)
        return self._wrap_in_html_container(msg, key)

    def _msg(self, parser, key: str, *params) -> str:
        msg = self.message_localizer.plain(key, *params)
        type_ = self._parse_type_and_id_from_message_key(key)[0]
        if type_ == "error":
            # Take care; this is a sideeffect that might not belong to this class.
            parser.add_tracking_category("cite-tracking-category-cite-error")
        # Messages: cite_error, cite_warning
        return self.message_localizer.plain(f"cite_{type_}", msg)

    def _wrap_in_html_container(self, wikitext: str, key: str) -> str:
        type_, id_ = self._parse_type_and_id_from_message_key(key)
        extra_class = " mw-ext-cite-warning-" + escape_class(id_) if type_ == "warning" else ""
        return raw_element("span", {
            "class": f"{type_} mw-ext-cite-{type_}" + extra_class,
            "lang": ENGLISH.get_html_code(),
            "dir": "ltr",
        }, wikitext)

    @staticmethod
    def _parse_type_and_id_from_message_key(message_key: str) -> list[str]:
        """array_slice( explode( '_', str_replace( '-', '_', $messageKey ), 3 ), 1 )"""
        parts = message_key.replace("-", "_").split("_", 2)[1:]
        return parts + [""] * (2 - len(parts))


# ======================================================================================================================
# Anchors and footnote marks
# ======================================================================================================================

class AnchorFormatter:
    def __init__(self, message_localizer: ReferenceMessageLocalizer, config):
        self.message_localizer = message_localizer
        self.config = config

    def ref_key(self, key: Any, num: Optional[str] = None) -> str:
        """Return an id for use in wikitext output based on a key and optionally the number of it, used in
        <references>, not <ref> (since otherwise it would link to itself)"""
        prefix = self.message_localizer.text("cite_reference_link_prefix")
        suffix = self.message_localizer.text("cite_reference_link_suffix")
        key = str(key)
        if num is not None:
            key = self.message_localizer.plain("cite_reference_link_key_with_num", key, num)
        return self._normalize_key(prefix + key + suffix)

    def get_references_key(self, key: Any) -> str:
        """Return an id for use in wikitext output based on a key and optionally the number of it, used in <ref>,
        not <references> (since otherwise it would link to itself)"""
        prefix = self.message_localizer.text("cite_references_link_prefix")
        suffix = self.message_localizer.text("cite_references_link_suffix")
        return self._normalize_key(prefix + str(key) + suffix)

    def _normalize_key(self, key: str) -> str:
        """Normalizes and sanitizes a reference key"""
        ret = escape_id_for_link(key, config=self.config)
        ret = re.sub(r"__+", "_", ret)
        return safe_encode_attribute(ret, config=self.config)


class FootnoteMarkFormatter:
    def __init__(self, error_reporter: ErrorReporter, anchor_formatter: AnchorFormatter,
                 message_localizer: ReferenceMessageLocalizer):
        self.link_labels: dict[str, list[str]] = {}
        self.anchor_formatter = anchor_formatter
        self.error_reporter = error_reporter
        self.message_localizer = message_localizer

    def link_ref(self, parser, group: str, ref: dict) -> str:
        """Generate a link (<sup ...) for the <ref> element from a key and return XHTML ready for output"""
        label = self._get_link_label(parser, group, ref["number"])
        if label is None:
            label = self.message_localizer.localize_digits(ref["number"])
            if group != DEFAULT_GROUP:
                label = f"{group} {label}"
        if ref.get("extendsIndex") is not None:
            label += "." + self.message_localizer.localize_digits(ref["extendsIndex"])

        key = ref["name"] if ref.get("name") is not None else ref["key"]
        count = f"{ref['key']}-{ref['count']}" if _truthy(ref.get("name")) else None
        subkey = f"-{ref['key']}" if _truthy(ref.get("name")) else ""

        return parser.recursive_tag_parse(self.message_localizer.plain(
            "cite_reference_link",
            self.anchor_formatter.ref_key(key, count),
            self.anchor_formatter.get_references_key(f"{key}{subkey}"),
            safe_encode_attribute(label, config=parser.config),
        ))

    def _get_link_label(self, parser, group: str, number: int) -> Optional[str]:
        """Generate a custom format link for a group given an offset, e.g. the second <ref group="foo"> is b if
        $this->mLinkLabels["foo"] = [ 'a', 'b', 'c', ...]. Return an error if the offset > the # of array items"""
        message = f"cite_link_label_group-{group}"
        if group not in self.link_labels:
            self.link_labels[group] = ([] if self.message_localizer.is_disabled(message)
                                       else re.split(r"\s+", self.message_localizer.plain(message), flags=re.A))
        if not self.link_labels[group]:
            return None
        labels = self.link_labels[group]
        if 0 <= number - 1 < len(labels):
            return labels[number - 1]
        return self.error_reporter.plain(parser, "cite_error_no_link_label_group", group, message)


# ======================================================================================================================
# ReferenceStack
# ======================================================================================================================

class ReferenceStack:
    """Encapsulates most of Cite state during parsing. This includes metadata about each ref tag, and a rollback
    stack to correct confusion caused by lost context when `{{#tag` is used.

    ``refs``: all <ref> tags parsed so far, indexed by group name (an empty string for the default group) and
    reference name. References without a name get a numeric index, starting from 0. Elements (almost all are
    optional): 'name', 'key' (sequence number for all references), 'number' (sequence number per group, the [1]
    footnote marker), 'extendsIndex', 'count' (how often a reference is reused; -1 for anonymous references),
    'extends', 'follow', '__placeholder__', 'text', 'dir'."""

    def __init__(self, error_reporter: ErrorReporter):
        self.refs: dict[str, dict[Union[str, int], dict]] = {}
        # Auto-incrementing sequence number for all <ref>, no matter which group
        self.ref_sequence = 0
        # Counter for the number of refs in each group.
        self.group_ref_sequence: dict[str, int] = {}
        self.extends_count: dict[str, dict[str, int]] = {}
        # <ref> call stack. Used to cleanup out of sequence ref calls created by #tag
        self.ref_call_stack: list = []
        self.error_reporter = error_reporter
        # PHP's next free integer key of each group array ($array[] = ...)
        self._next_index: dict[str, int] = {}

    def _append(self, group: str, ref: dict) -> None:
        index = self._next_index.get(group, 0)
        self.refs[group][index] = ref
        self._next_index[group] = index + 1

    def push_invalid_ref(self) -> None:
        """Leave a mark in the stack which matches an invalid ref tag."""
        self.ref_call_stack.append(False)

    def push_ref(self, parser, strip_state, text: Optional[str], argv: dict, group: str, name: Optional[str],
                 extends: Optional[str], follow: Optional[str], dir_: Optional[str]) -> Optional[dict]:
        """Populate self.refs and self.ref_call_stack based on input and arguments to <ref>"""
        self.refs.setdefault(group, {})
        self.group_ref_sequence.setdefault(group, 0)

        self.ref_sequence += 1
        ref: dict = {
            "count": 0 if _truthy(name) else -1,
            "dir": dir_,
            # This assumes we are going to register a new reference, instead of reusing one
            "key": self.ref_sequence,
            "name": name,
            "text": text,
        }

        if _truthy(follow):
            if follow not in self.refs[group]:
                # Mark an incomplete follow="…" as such. This is valid e.g. in the Page:… namespace on Wikisource.
                self._append(group, {**ref, "follow": follow})
                self.ref_call_stack.append(["new", self.ref_sequence, group, name, extends, text, argv])
            elif text is not None:
                # We know the parent already, so just perform the follow="…" and bail out
                self.append_text(group, follow, " " + text)
                self.ref_sequence -= 1
            # A follow="…" never gets its own footnote marker
            return None

        if not _truthy(name):
            # This is an anonymous reference, which will be given a numeric index.
            self._append(group, ref)
            action = "new"
        elif self.refs[group].get(name, {}).get("__placeholder__"):
            # Populate a placeholder.
            existing = self.refs[group][name]
            del existing["__placeholder__"]
            ref.pop("number", None)
            ref = {**ref, **existing}
            self.refs[group][name] = ref
            action = "new-from-placeholder"
        elif name not in self.refs[group]:
            # Valid key with first occurrence
            self.refs[group][name] = ref
            action = "new"
        else:
            # Change an existing entry.
            ref = self.refs[group][name]
            ref["count"] = ref.get("count", 0) + 1
            # Rollback the global counter since we won't create a new ref.
            self.ref_sequence -= 1
            if ref.get("text") is None and text is not None:
                # If no text was set before, use this text
                ref["text"] = text
                # Use the dir parameter only from the full definition of a named ref tag
                ref["dir"] = dir_
                action = "assign"
            else:
                if text is not None and (
                        # T205803 different strip markers might hide the same text
                        strip_state.unstrip_both(text) != strip_state.unstrip_both(ref.get("text") or "")):
                    # two refs with same name and different text; add error message to the original ref
                    ref["text"] = (ref.get("text") or "") + " " + self.error_reporter.plain(
                        parser, "cite_error_references_duplicate_key", name)
                action = "increment"

        if ref.get("number") is None:
            self.group_ref_sequence[group] += 1
            ref["number"] = self.group_ref_sequence[group]

        # Do not mess with a known parent a second time
        if _truthy(extends) and ref.get("extendsIndex") is None:
            counts = self.extends_count.setdefault(group, {})
            counts[extends] = counts.get(extends, 0) + 1
            ref["extends"] = extends
            ref["extendsIndex"] = counts[extends]

            parent = self.refs[group].get(extends)
            if parent is not None and parent.get("number") is not None:
                # Adopt the parent's number.
                ref["number"] = parent["number"]
                # Roll back the group sequence number.
                self.group_ref_sequence[group] -= 1
            else:
                # Transfer my number to parent ref.
                self.refs[group][extends] = {"number": ref["number"], "__placeholder__": True}
        elif _truthy(extends) and ref.get("extends") != extends:
            # TODO: Change the error message to talk about "conflicting content or parent"?
            error = self.error_reporter.plain(parser, "cite_error_references_duplicate_key", name)
            if ref.get("text") is not None:
                ref["text"] += " " + error
            else:
                ref["text"] = error

        self.ref_call_stack.append([action, ref["key"], group, name, extends, text, argv])
        return ref

    def rollback_refs(self, count: int) -> list[tuple[Optional[str], dict]]:
        """Undo the changes made by the last ``count`` ref tags. This is used when we discover that the last few
        tags were actually inside of a references tag."""
        redo_stack = []
        while count and self.ref_call_stack:
            count -= 1
            call = self.ref_call_stack.pop()
            if call:
                redo_stack.append(self._rollback_ref(*call))
        # Drop unused rollbacks, this group is finished.
        self.ref_call_stack = []
        return list(reversed(redo_stack))

    def _rollback_ref(self, action: str, key: int, group: str, name: Optional[str], extends: Optional[str],
                      text: Optional[str], argv: dict) -> tuple[Optional[str], dict]:
        """Partially undoes the effect of calls to stack(). Called by guardedReferences().

        The option to define <ref> within <references> makes the behavior of <ref> context dependent. This is
        normally fine but certain operations (especially #tag) lead to out-of-order parser evaluation with the <ref>
        tags being processed before their containing <reference> element is read. This leads to stack corruption
        that this function works to fix.

        This function is not a total rollback since some internal counters remain incremented. Doing so prevents
        accidentally corrupting certain links."""
        if not self.has_group(group):
            raise RuntimeError(f'Cannot roll back ref with unknown group "{group}".')

        lookup: Optional[Union[str, int]] = name if _truthy(name) else None
        if lookup is None:
            # Find anonymous ref by key.
            for k, v in self.refs[group].items():
                if v.get("key") == key:
                    lookup = k
                    break

        # Obsessive sanity checks that the specified element exists.
        if lookup is None:
            raise RuntimeError(f"Cannot roll back unknown ref by key {key}.")
        elif lookup not in self.refs[group]:
            raise RuntimeError(f'Cannot roll back missing named ref "{lookup}".')
        elif self.refs[group][lookup].get("key") != key:
            raise RuntimeError(f'Cannot roll back corrupt named ref "{lookup}" which should have had key {key}.')

        if _truthy(extends):
            counts = self.extends_count.setdefault(group, {})
            if counts.get(extends) is not None:  # (PHP's null-- stays null)
                counts[extends] -= 1

        if action == "new":
            # Rollback the addition of new elements to the stack
            del self.refs[group][lookup]
            if not self.refs[group]:
                self.pop_group(group)
            elif group in self.group_ref_sequence:
                self.group_ref_sequence[group] -= 1
            # TODO: Don't we need to rollback extendsCount as well?
        elif action == "new-from-placeholder":
            self.refs[group][lookup]["__placeholder__"] = True
            self.refs[group][lookup].pop("count", None)
        elif action == "assign":
            # Rollback assignment of text to pre-existing elements
            self.refs[group][lookup]["text"] = None
            self.refs[group][lookup]["count"] -= 1
        elif action == "increment":
            # Rollback increase in named ref occurrences
            self.refs[group][lookup]["count"] -= 1
        else:
            raise RuntimeError(f'Unknown call stack action "{action}"')
        return text, argv

    def pop_group(self, group: str) -> dict:
        """Clear state for a single group."""
        refs = self.get_group_refs(group)
        self.refs.pop(group, None)
        self.group_ref_sequence.pop(group, None)
        self.extends_count.pop(group, None)
        self._next_index.pop(group, None)
        return refs

    def has_group(self, group: str) -> bool:
        """Returns true if the group exists and contains references."""
        return bool(self.refs.get(group))

    def get_groups(self) -> list[str]:
        """Returns a list of all groups with references."""
        return [group for group, refs in self.refs.items() if refs]

    def get_group_refs(self, group: str) -> dict:
        """Return all references for a group."""
        return self.refs.get(group, {})

    def append_text(self, group: str, name: Union[str, int], text: str) -> None:
        refs = self.refs.setdefault(group, {})
        entry = refs.setdefault(name, {})
        if entry.get("text") is not None:
            entry["text"] += text
        else:
            entry["text"] = text


# ======================================================================================================================
# ReferencesFormatter
# ======================================================================================================================

class ReferencesFormatter:
    def __init__(self, error_reporter: ErrorReporter, anchor_formatter: AnchorFormatter,
                 message_localizer: ReferenceMessageLocalizer):
        # The backlinks, in order, to pass as $3 to 'cite_references_link_many_format', defined in
        # 'cite_references_link_many_format_backlink_labels
        self.backlink_labels: Optional[list[str]] = None
        self.error_reporter = error_reporter
        self.anchor_formatter = anchor_formatter
        self.message_localizer = message_localizer

    def format_references(self, parser, group_refs: dict, responsive: bool, is_section_preview: bool) -> str:
        if not group_refs:
            return ""
        wikitext = self._format_refs_list(parser, group_refs, is_section_preview)
        # Live hack: parse() adds two newlines on WM, can't reproduce it locally -ævar
        html = parser.recursive_tag_parse(wikitext).rstrip("\n")
        if responsive:
            wrap_classes = ["mw-references-wrap"]
            if len(group_refs) > 10:
                wrap_classes.append("mw-references-columns")
            # Use a DIV wrap because column-count on a list directly is broken in Chrome.
            # See https://bugs.chromium.org/p/chromium/issues/detail?id=498730.
            return raw_element("div", {"class": wrap_classes}, html)
        return html

    def _format_refs_list(self, parser, group_refs: dict, is_section_preview: bool) -> str:
        # After sorting the list, we can assume that references are in the same order as their numbering.
        # Subreferences will come immediately after their parent.
        items = sorted(group_refs.items(), key=lambda kv: (kv[1].get("number") or 0, kv[1].get("extendsIndex") or 0))
        group_refs = dict(items)

        # Add new lines between the list items (ref entries) to avoid confusing tidy (T15073).
        # Note: This builds a string of wikitext, not html.
        parser_input = "\n"
        indented: Union[bool, str] = False
        for key, value in group_refs.items():
            # Make sure the parent is not a subreference.
            # FIXME: Move to a validation function.
            parent = group_refs.get(value.get("extends")) if value.get("extends") is not None else None
            if parent is not None and parent.get("extends") is not None:
                value = dict(value)
                value["text"] = (value.get("text") or "") + " " + self.error_reporter.plain(
                    parser, "cite_error_ref_nested_extends", value["extends"], parent["extends"])

            if not indented and value.get("extends") is not None:
                # The nested <ol> must be inside the parent's <li>
                m = re.search(r"</li>\s*\Z", parser_input)
                if m:
                    parser_input = parser_input[:m.start()]
                parser_input += open_element("ol", {"class": "mw-extended-references"})
                indented = m.group(0) if m else True
            elif indented and value.get("extends") is None:
                parser_input += self._close_indention(indented)
                indented = False
            parser_input += self._format_list_item(parser, key, value, is_section_preview) + "\n"
        parser_input += self._close_indention(indented)
        return raw_element("ol", {"class": "references"}, parser_input)

    @staticmethod
    def _close_indention(closing_li: Union[bool, str]) -> str:
        if not closing_li:
            return ""
        return close_element("ol") + (closing_li if isinstance(closing_li, str) else "")

    def _format_list_item(self, parser, key: Union[str, int], val: dict, is_section_preview: bool) -> str:
        text = self._reference_text(parser, key, val.get("text"), is_section_preview)
        error = ""
        extra_attributes = ""

        if val.get("dir") is not None:
            dir_ = val["dir"].lower()
            extra_attributes = expand_attributes({"class": "mw-cite-dir-" + dir_})

        # Special case for an incomplete follow="…". This is valid e.g. in the Page:… namespace on Wikisource. Note
        # this returns a <p>, not an <li> as expected!
        if val.get("follow") is not None:
            return self.message_localizer.plain(
                "cite_references_no_link", self.anchor_formatter.get_references_key(val["follow"]), text)

        # This counts the number of reuses. 0 means the reference appears only 1 time.
        if val.get("count") is not None and val["count"] < 1:
            # Anonymous, auto-numbered references can't be reused and get marked with a -1.
            if val["count"] < 0:
                id_ = str(val["key"])
                backlink_id = self.anchor_formatter.ref_key(val["key"])
            else:
                id_ = f"{key}-{val['key']}"
                backlink_id = self.anchor_formatter.ref_key(key, f"{val['key']}-{val['count']}")
            return self.message_localizer.plain(
                "cite_references_link_one", self.anchor_formatter.get_references_key(id_), backlink_id,
                text + error, extra_attributes)

        # Named references with >1 occurrences
        backlinks = []
        # There is no count in case of a section preview
        count = val.get("count")
        for i in range((count if count is not None else -1) + 1):
            backlinks.append(self.message_localizer.plain(
                "cite_references_link_many_format",
                self.anchor_formatter.ref_key(key, f"{val['key']}-{i}"),
                self._numeric_backlink_label(
                    f"{val['number']}" + (f".{val['extendsIndex']}" if val.get("extendsIndex") is not None else ""),
                    i, count),
                self._alternate_backlink_label(parser, i),
            ))
        return self.message_localizer.plain(
            "cite_references_link_many",
            self.anchor_formatter.get_references_key(f"{key}-{val.get('key', '')}"),
            self._list_to_text(backlinks),
            text + error,
            extra_attributes,
        )

    def _reference_text(self, parser, key: Union[str, int], text: Optional[str], is_section_preview: bool) -> str:
        if text is None:
            return self.error_reporter.plain(
                parser,
                "cite_warning_sectionpreview_no_text" if is_section_preview else "cite_error_references_no_text",
                key)
        return '<span class="reference-text">' + text.rstrip("\n") + "</span>\n"

    def _numeric_backlink_label(self, base: str, offset: int, max_: int) -> str:
        """Generate a numeric backlink given a base number and an offset, e.g. $base = 1, $offset = 2; = 1.2. Since
        bug #5525, it correctly does 1.9 -> 1.10 as well as 1.099 -> 1.100"""
        return (self.message_localizer.localize_digits(base)
                + self.message_localizer.localize_separators(".")
                + self.message_localizer.localize_digits(str(offset).rjust(len(str(max_)), "0")))

    def _alternate_backlink_label(self, parser, offset: int) -> str:
        """Generate a custom format backlink given an offset, e.g. $offset = 2; = c if $this->mBacklinkLabels = [ 'a',
        'b', 'c', ...]. Return an error if the offset > the # of array items"""
        if self.backlink_labels is None:
            self.backlink_labels = re.split(
                r"\s+", self.message_localizer.plain("cite_references_link_many_format_backlink_labels"), flags=re.A)
        if 0 <= offset < len(self.backlink_labels):
            return self.backlink_labels[offset]
        return self.error_reporter.plain(parser, "cite_error_references_no_backlink_label")

    def _list_to_text(self, arr: list[str]) -> str:
        """This does approximately the same thing as Language::listToText() but due to this being used for a slightly
        different purpose (people might not want , as the first separator and not 'and' as the second, and this has
        to use messages from the content language) I'm rolling my own."""
        if not arr:
            return ""
        last_element = arr[-1]
        rest = arr[:-1]
        if not rest:
            return last_element
        sep = self.message_localizer.plain("cite_references_link_many_sep")
        and_ = self.message_localizer.plain("cite_references_link_many_and")
        return sep.join(rest) + and_ + last_element


# ======================================================================================================================
# Cite
# ======================================================================================================================

class Cite:
    def __init__(self, parser):
        self.is_section_preview = False
        message_localizer = ReferenceMessageLocalizer(parser)
        # (wfMessage() of checkRefsNoReferences(); English is both the content and the interface language here)
        self.message_localizer = message_localizer
        self.error_reporter = ErrorReporter(message_localizer)
        self.reference_stack = ReferenceStack(self.error_reporter)
        anchor_formatter = AnchorFormatter(message_localizer, parser.config)
        self.footnote_mark_formatter = FootnoteMarkFormatter(self.error_reporter, anchor_formatter,
                                                             message_localizer)
        self.references_formatter = ReferencesFormatter(self.error_reporter, anchor_formatter, message_localizer)
        # True when a <ref> tag is being processed. Used to avoid infinite recursion
        self.in_cite = False
        # The current group name while parsing nested <ref> in <references>. None when parsing <ref> outside of
        # <references>. Warning, an empty string is a valid group name!
        self.in_references_group: Optional[str] = None
        # Error stack used when defining refs in <references>
        self.references_errors: list[str] = []

    def ref(self, parser, text: Optional[str], argv: dict) -> Union[str, bool]:
        """Callback function for <ref>. ``text``: raw, untrimmed wikitext content of the <ref> tag, if any.
        ``argv``: arguments as given in <ref name=…>, already trimmed. False in case a <ref> tag is not allowed in
        the current context."""
        if self.in_cite:
            return False
        self.in_cite = True
        try:
            return self._guarded_ref(parser, text, argv)
        finally:
            self.in_cite = False

    def _validate_ref(self, parser, text: Optional[str], group: str, name: Optional[str], extends: Optional[str],
                      follow: Optional[str], dir_: Optional[str]) -> list[Error]:
        if _ctype_digit(name) or _ctype_digit(extends) or _ctype_digit(follow):
            # Numeric names mess up the resulting id's, potentially producing duplicate id's in the XHTML. The Right
            # Thing To Do would be to mangle them, but it's not really high-priority (and would produce weird id's
            # anyway).
            return [("cite_error_ref_numeric_key",)]

        if _truthy(extends):
            # Temporary feature flag until mainstreamed, see T236255
            if not getattr(parser.config, "cite_book_referencing", False):
                return [("cite_error_ref_too_many_keys",)]
            group_refs = self.reference_stack.get_group_refs(group)
            if name in group_refs and group_refs[name].get("extends") is None:
                # T242141: A top-level <ref> can't be changed into a sub-reference
                return [("cite_error_references_duplicate_key", name)]
            elif group_refs.get(extends, {}).get("extends") is not None:
                # A sub-reference can not be extended a second time (no nesting)
                return [("cite_error_ref_nested_extends", extends, group_refs[extends]["extends"])]

        if _truthy(follow) and (_truthy(name) or _truthy(extends)):
            # TODO: Introduce a specific error for this case.
            return [("cite_error_ref_too_many_keys",)]

        if dir_ is not None and dir_.lower() not in ("ltr", "rtl"):
            return [("cite_error_ref_invalid_dir", dir_)]

        if self.in_references_group is None:
            return self._validate_ref_outside_of_references(text, name)
        return self._validate_ref_in_references(parser, text, group, name)

    @staticmethod
    def _validate_ref_outside_of_references(text: Optional[str], name: Optional[str]) -> list[Error]:
        if not _truthy(name):
            if text is None:
                # Completely empty ref like <ref /> is forbidden.
                return [("cite_error_ref_no_key",)]
            elif _php_trim(text) == "":
                # Must have content or reuse another ref by name.
                return [("cite_error_ref_no_input",)]

        # (Possessive quantifiers of PHP emulated with a lookahead.)
        if text is not None and re.search(
                r"<ref(erences)?\b[^>]*>",
                re.sub(r"<(\w+)(?!\w)[^>]*>.*?</\1\s*>|<!--.*?-->", "", text, flags=re.S | re.A),
                re.I | re.A):
            # (bug T8199) This most likely implies that someone left off the closing </ref> tag, which will cause
            # the entire article to be eaten up until the next <ref>. So we bail out early instead. The fancy regex
            # above first tries chopping out anything that looks like a comment or SGML tag, which is a crude way to
            # avoid false alarms for <nowiki>, <pre>, etc.
            return [("cite_error_included_ref",)]
        return []

    def _validate_ref_in_references(self, parser, text: Optional[str], group: str,
                                    name: Optional[str]) -> list[Error]:
        config = parser.config
        if group != self.in_references_group:
            # <ref> and <references> have conflicting group attributes.
            return [("cite_error_references_group_mismatch", safe_encode_attribute(group, config=config))]

        if not _truthy(name):
            # <ref> calls inside <references> must be named
            return [("cite_error_references_no_key",)]

        if text is None or _php_trim(text) == "":
            # <ref> called in <references> has no content.
            return [("cite_error_empty_references_define", safe_encode_attribute(name, config=config),
                     safe_encode_attribute(group, config=config))]

        # Section previews are exempt from some rules.
        if not self.is_section_preview:
            if not self.reference_stack.has_group(group):
                # Called with group attribute not defined in text.
                return [("cite_error_references_missing_group", safe_encode_attribute(group, config=config),
                         safe_encode_attribute(name, config=config))]
            group_refs = self.reference_stack.get_group_refs(group)
            if name not in group_refs:
                # No such named ref exists in this group.
                return [("cite_error_references_missing_key", safe_encode_attribute(name, config=config))]
        return []

    def _guarded_ref(self, parser, text: Optional[str], argv: dict) -> str:
        # Tag every page where Book Referencing has been used, whether or not the ref tag is valid. This code and the
        # page property will be removed once the feature is stable. See T237531.
        if BOOK_REF_ATTRIBUTE in argv:
            parser.get_output().page_properties[BOOK_REF_PROPERTY] = ""

        arguments, errors = self._parse_arguments(argv, ["group", "name", BOOK_REF_ATTRIBUTE, "follow", "dir"])
        # Use the default group, or the references group when inside one.
        if arguments["group"] is None:
            arguments["group"] = self.in_references_group if self.in_references_group is not None else DEFAULT_GROUP

        errors += self._validate_ref(parser, text, *arguments.values())

        if errors and self.in_references_group is not None:
            for error in errors:
                self.references_errors.append(self.error_reporter.half_parsed(parser, *error))
            return ""

        # Validation cares about the difference between null and empty, but from here on we don't
        if text is not None and _php_trim(text) == "":
            text = None
        group, name = arguments["group"], arguments["name"]

        if self.in_references_group is not None:
            group_refs = self.reference_stack.get_group_refs(group)
            if text is None:
                return ""
            if group_refs.get(name, {}).get("text") is None:
                self.reference_stack.append_text(group, name, text)
            elif group_refs[name]["text"] != text:
                # two refs with same key and different content; adds error message to the original ref
                # TODO: report these errors the same way as the others, rather than a special case to append to the
                #  second one's content.
                self.reference_stack.append_text(group, name, " " + self.error_reporter.plain(
                    parser, "cite_error_references_duplicate_key", name))
            return ""

        if errors:
            self.reference_stack.push_invalid_ref()
            # FIXME: If we ever have multiple errors, these must all be presented to the user, so they know what to
            #  correct.
            # TODO: Make this nicer, see T238061
            return self.error_reporter.half_parsed(parser, *errors[0])

        ref = self.reference_stack.push_ref(parser, parser.get_strip_state(), text, argv, *arguments.values())
        return self.footnote_mark_formatter.link_ref(parser, group, ref) if ref else ""

    @staticmethod
    def _parse_arguments(argv: dict, allowed_attributes: list[str]) -> tuple[dict, list[Error]]:
        """The dictionary of field names and parsed or default values (missing attributes are None), and an error if
        there are other attributes."""
        all_values = {**dict.fromkeys(allowed_attributes), **argv}
        values = dict(list(all_values.items())[:len(allowed_attributes)])
        errors: list[Error] = []
        if len(all_values) > len(allowed_attributes):
            # A <ref> must have a name (can be null), but <references> can't have one
            errors.append(("cite_error_ref_too_many_keys" if "name" in allowed_attributes
                           else "cite_error_references_invalid_parameters",))
        return values, errors

    def references(self, parser, text: Optional[str], argv: dict) -> Union[str, bool]:
        """Callback function for <references>. False in case a <references> tag is not allowed in the current
        context."""
        if self.in_cite or self.in_references_group is not None:
            return False
        try:
            return self._guarded_references(parser, text, argv)
        finally:
            self.in_references_group = None

    def _guarded_references(self, parser, text: Optional[str], argv: dict) -> str:
        """Must only be called from references(). Use that to prevent recursion."""
        values, errors = self._parse_arguments(argv, ["group", "responsive"])
        group, responsive = values["group"], values["responsive"]
        self.in_references_group = group if group is not None else DEFAULT_GROUP

        if text is not None and _php_trim(text) != "":
            if text.count(MARKER_PREFIX + "-references-"):
                return self.error_reporter.half_parsed(parser, "cite_error_included_references")

            # Detect whether we were sent already rendered <ref>s. Mostly a side effect of using
            # {{#tag:references}}. The following assumes that the parsed <ref>s sent within the <references> block
            # were the most recent calls to <ref>. This assumption is true for all known use cases, but not strictly
            # enforced by the parser. It is possible that some unusual combination of #tag, <references> and
            # conditional parser functions could be created that would lead to malformed references here.
            count = text.count(MARKER_PREFIX + "-ref-")

            # Undo effects of calling <ref> while unaware of being contained in <references>
            for call in self.reference_stack.rollback_refs(count):
                # Rerun <ref> call with the <references> context now being known
                self._guarded_ref(parser, *call)

            # Parse the <references> content to process any unparsed <ref> tags
            parser.recursive_tag_parse(text)

        if errors:
            # Bail out with an error.
            return self.error_reporter.half_parsed(parser, *errors[0])

        s = self._format_references(parser, self.in_references_group, responsive)

        # Append errors generated while processing <references>
        if self.references_errors:
            s += "\n" + "<br />\n".join(self.references_errors)
            self.references_errors = []
        return s

    def _format_references(self, parser, group: str, responsive: Optional[str] = None) -> str:
        """``responsive``: defaults to $wgCiteResponsiveReferences when not set"""
        default_responsive = getattr(parser.config, "cite_responsive_references", True)
        return self.references_formatter.format_references(
            parser,
            self.reference_stack.pop_group(group),
            responsive != "0" if responsive is not None else default_responsive,
            self.is_section_preview,
        )

    def check_refs_no_references(self, parser, is_section_preview: bool) -> str:
        """Called at the end of page processing to append a default references section, if refs were used without a
        main references tag. If there are references in a custom group, and there is no references tag for it, show
        an error message for that group. If we are processing a section preview, this adds the missing references
        tags and does not add the errors."""
        s = ""
        for group in self.reference_stack.get_groups():
            if group == DEFAULT_GROUP or is_section_preview:
                s += self._format_references(parser, group)
            else:
                s += "<br />" + self.error_reporter.half_parsed(
                    parser, "cite_error_group_refs_without_references",
                    safe_encode_attribute(group, config=parser.config))
        if is_section_preview and s != "":
            header_msg = "cite_section_preview_references"
            if not self.message_localizer.is_disabled(header_msg):
                s = element("h2", {"id": "mw-ext-cite-cite_section_preview_references_header"},
                            self.message_localizer.text(header_msg)) + s
            # provide a preview of references in its own section
            s = raw_element("div", {"class": "mw-ext-cite-cite_section_preview_references"}, s)
        return "\n" + s if s != "" else ""


# ======================================================================================================================
# Hooks (CiteParserTagHooks, CiteParserHooks)
# ======================================================================================================================

def cite_for_parser(parser) -> Cite:
    """Get or create Cite state for this parser. ($parser->extCite, unset by the ParserClearState hook: here the
    state belongs to the parse's ParserOutput, which the parser replaces at the start of each parse.)"""
    state = getattr(parser, "_ext_cite", None)
    output = parser.get_output()
    if state is None or state[0] is not output:
        state = (output, Cite(parser))
        parser._ext_cite = state
    return state[1]


def ref_hook(text: Optional[str], argv: dict, parser, frame) -> str:
    """Parser hook for the <ref> tag."""
    cite = cite_for_parser(parser)
    result = cite.ref(parser, text, argv)
    if result is False:
        return htmlspecialchars(f"<ref>{text or ''}</ref>")
    frame.set_volatile()
    return result


def references_hook(text: Optional[str], argv: dict, parser, frame) -> str:
    """Parser hook for the <references> tag."""
    cite = cite_for_parser(parser)
    result = cite.references(parser, text, argv)
    if result is False:
        return htmlspecialchars("<references/>" if text is None else f"<references>{text}</references>")
    frame.set_volatile()
    return result


def after_parse(parser, text: str) -> str:
    """ParserAfterParse: add the references of groups without <references />."""
    state = getattr(parser, "_ext_cite", None)
    if state is not None and state[0] is parser.get_output():
        text += state[1].check_refs_no_references(parser, False)
    return text


def register(parser) -> None:
    """ParserFirstCallInit: the <ref> and <references> tags, and the ParserAfterParse hook.

    The parser's after-parse hook point is ``parser.after_parse_hooks`` (a list of ``callback(parser, text) -> text``
    run between internal_parse() and internal_parse_half_parsed() of the main parse) if the parser has one;
    otherwise this parser instance's internal_parse() is wrapped to call it after a main (is_main) parse."""
    parser.set_hook("ref", ref_hook)
    parser.set_hook("references", references_hook)

    hooks = getattr(parser, "after_parse_hooks", None)
    if isinstance(hooks, list):
        if after_parse not in hooks:
            hooks.append(after_parse)
        return
    if getattr(parser, "_ext_cite_wrapped", False):
        return
    original: Callable = parser.internal_parse

    def internal_parse(text: str, is_main: bool = True, frame=None) -> str:
        text = original(text, is_main, frame)
        return after_parse(parser, text) if is_main else text

    parser.internal_parse = internal_parse
    parser._ext_cite_wrapped = True

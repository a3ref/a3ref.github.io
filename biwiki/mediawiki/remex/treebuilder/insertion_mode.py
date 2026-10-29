# Ported from RemexHtml 3.0.2 src/TreeBuilder/InsertionMode.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The base class of the insertion modes."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .._php import strcspn, strspn
from ..tokenizer.attributes import Attributes

if TYPE_CHECKING:
    from .dispatcher import Dispatcher
    from .tree_builder import TreeBuilder

_WHITESPACE = "\t\n\f\r "


class InsertionMode:
    def __init__(self, builder: TreeBuilder, dispatcher: Dispatcher):
        self.builder = builder
        self.dispatcher = dispatcher

    def doctype(self, name, public, system, quirks, source_start: int, source_length: int) -> None:
        self.builder.error("unexpected doctype", source_start)

    def comment(self, text: str, source_start: int, source_length: int) -> None:
        self.builder.comment(None, text, source_start, source_length)

    def error(self, text: str, pos: int) -> None:
        self.builder.error(text, pos)

    def split_initial_match(self, is_start_of_token: bool, mask: str, text: str, start: int, length: int,
                            source_start: int, source_length: int) -> tuple[tuple[int, int, int, int],
                                                                            tuple[int, int, int, int]]:
        match_length = strspn(text, mask, start, length)
        if is_start_of_token and match_length:
            # Do some extra work to figure out a plausible start position if
            # the text node started with <![CDATA[
            # FIXME: make this optional?
            source_text = self.builder.tokenizer.get_preprocessed_text()
            # substr_compare( $sourceText, '<![CDATA[', $sourceStart, $sourceLength ) === 0
            is_cdata = (source_start < len(source_text) and source_length > 0
                        and source_text[source_start:source_start + source_length] == "<![CDATA["[:source_length])
            cdata_length = len("<![CDATA[") if is_cdata else 0
        else:
            cdata_length = 0
        return (
            (start, match_length, source_start, match_length + cdata_length),
            (start + match_length, length - match_length, source_start + match_length + cdata_length,
             source_length - match_length - cdata_length),
        )

    def handle_frameset_whitespace(self, in_body: bool, text: str, start: int, length: int, source_start: int,
                                   source_length: int) -> None:
        is_start_of_token = True
        builder = self.builder
        while True:
            part1, part2 = self.split_initial_match(is_start_of_token, _WHITESPACE, text, start, length,
                                                    source_start, source_length)
            is_start_of_token = False
            start, length, source_start, source_length = part1
            if length:
                if in_body:
                    self.dispatcher.in_body.characters(text, start, length, source_start, source_length)
                else:
                    builder.insert_characters(text, start, length, source_start, source_length)
            start, length, source_start, source_length = part2
            if length:
                builder.error("unexpected non-whitespace character", source_start)
                start += 1
                length -= 1
                source_start += 1
                source_length -= 1
            if not length > 0:
                break

    def strip_nulls(self, callback: Callable[[str, int, int, int, int], None], text: str, start: int, length: int,
                    source_start: int, source_length: int) -> None:
        error_offset = source_start - start
        while length > 0:
            valid_length = strcspn(text, "\0", start, length)
            if valid_length:
                callback(text, start, valid_length, source_start, source_length)
                start += valid_length
                length -= valid_length
            if length <= 0:
                break
            self.error("unexpected null character", start + error_offset)
            start += 1
            length -= 1

    def characters(self, text: str, start: int, length: int, source_start: int, source_length: int) -> None:
        raise NotImplementedError

    def start_tag(self, name: str, attrs: Attributes, self_close: bool, source_start: int,
                  source_length: int) -> None:
        raise NotImplementedError

    def end_tag(self, name: str, source_start: int, source_length: int) -> None:
        raise NotImplementedError

    def end_document(self, pos: int) -> None:
        raise NotImplementedError

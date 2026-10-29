# Ported from RemexHtml 3.0.2 src/TreeBuilder/TraceFormatter.php, TreeMutationTracer.php and DispatchTracer.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the PHP func_get_args() forwarding became
# explicit methods.
"""Debugging helpers which describe tree mutation and dispatch events."""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from ..tokenizer.token_handler import TokenHandler
from .tree_handler import TreeHandler


class TraceFormatter:
    @staticmethod
    def get_debug_tag(element: Any) -> str:
        """Get a debug tag for an element or null"""
        if not element:
            return ""
        elif hasattr(element, "get_debug_tag"):
            return element.get_debug_tag()
        else:
            return type(element).__name__ + "#" + hashlib.md5(str(id(element)).encode()).hexdigest()[:8]

    @staticmethod
    def excerpt(text: str) -> str:
        """Get a short excerpt of some text"""
        if len(text) > 20:
            text = text[:20] + "..."
        return text.replace("\n", "\\n")

    @staticmethod
    def get_preposition_name(prep: int) -> str:
        """Get a readable version of the TreeBuilder preposition constants"""
        return {0: "before", 1: "under", 2: "under root"}.get(prep, "???")

    @staticmethod
    def start_document(fns, fn) -> str:
        return "startDocument"

    @staticmethod
    def end_document(pos) -> str:
        return f"endDocument pos={pos}"

    @classmethod
    def characters(cls, preposition, ref_node, text, start, length, source_start, source_length) -> str:
        excerpt = cls.excerpt(text[start:start + length])
        prep_name = cls.get_preposition_name(preposition)
        ref_tag = cls.get_debug_tag(ref_node)
        return f'characters "{excerpt}", {prep_name} {ref_tag}, pos={source_start}, len={source_length}'

    @classmethod
    def insert_element(cls, preposition, ref_node, element, void, source_start, source_length) -> str:
        prep_name = cls.get_preposition_name(preposition)
        ref_tag = cls.get_debug_tag(ref_node)
        element_tag = cls.get_debug_tag(element)
        void_msg = "void" if void else ""
        return f"insert {element_tag} {void_msg}, {prep_name} {ref_tag}, pos={source_start}, len={source_length}"

    @classmethod
    def end_tag(cls, element, source_start, source_length) -> str:
        element_tag = cls.get_debug_tag(element)
        return f"end {element_tag}, pos={source_start}, len={source_length}"

    @staticmethod
    def doctype(name, public, system, quirks, source_start, source_length) -> str:
        quirks_msg = {2: "quirks", 0: "no-quirks", 1: "limited-quirks"}[quirks]
        return (f'doctype {name}, public="{public}", system="{system}", {quirks_msg}, pos={source_start}, '
                f"len={source_length}")

    @classmethod
    def comment(cls, preposition, ref_node, text, source_start, source_length) -> str:
        prep_name = cls.get_preposition_name(preposition)
        ref_tag = cls.get_debug_tag(ref_node)
        excerpt = cls.excerpt(text)
        return f'comment "{excerpt}", {prep_name} {ref_tag}, pos={source_start}, len={source_length}'

    @staticmethod
    def error(text, pos) -> str:
        return f'error "{text}", pos={pos}'

    @classmethod
    def merge_attributes(cls, element, attrs, source_start) -> str:
        return f"merge {cls.get_debug_tag(element)}, pos={source_start}"

    @classmethod
    def remove_node(cls, element, source_start) -> str:
        return f"remove {cls.get_debug_tag(element)}, pos={source_start}"

    @classmethod
    def reparent_children(cls, element, new_parent, source_start) -> str:
        element_tag = cls.get_debug_tag(element)
        new_parent_tag = cls.get_debug_tag(new_parent)
        return f"reparent children of {element_tag} under {new_parent_tag}, pos={source_start}"


class TreeMutationTracer(TreeHandler):
    """This is a debugging helper class which calls the supplied callback function each time there is a TreeHandler
    event, giving a descriptive message. It then forwards the event through to the supplied handler."""

    def __init__(self, handler: TreeHandler, callback: Callable[[str], Any], verbosity: int = 0):
        """``handler``: the next pipeline stage; ``callback``: the message output function; ``verbosity``: set to
        non-zero to call dump() on the handler before and after each event."""
        self.handler = handler
        self.callback = callback
        self.verbosity = verbosity

    def _trace(self, msg: str) -> None:
        self.callback(f"[Tree] {msg}")

    def _handle_mutation(self, func_name: str, *args) -> None:
        self._trace(getattr(TraceFormatter, func_name)(*args))
        self._before()
        getattr(self.handler, func_name)(*args)
        self._after()

    def _handle_simple(self, func_name: str, *args) -> None:
        self._trace(getattr(TraceFormatter, func_name)(*args))
        getattr(self.handler, func_name)(*args)

    def _before(self) -> None:
        if self.verbosity > 0:
            self._trace("Before: " + self.handler.dump() + "\n")

    def _after(self) -> None:
        if self.verbosity > 0:
            self._trace("After:  " + self.handler.dump() + "\n")

    def start_document(self, fragment_namespace, fragment_name):
        self._handle_simple("start_document", fragment_namespace, fragment_name)

    def end_document(self, pos):
        self._handle_simple("end_document", pos)

    def characters(self, preposition, ref, text, start, length, source_start, source_length):
        self._handle_mutation("characters", preposition, ref, text, start, length, source_start, source_length)

    def insert_element(self, preposition, ref, element, void, source_start, source_length):
        self._handle_mutation("insert_element", preposition, ref, element, void, source_start, source_length)

    def end_tag(self, element, source_start, source_length):
        self._handle_mutation("end_tag", element, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self._handle_mutation("doctype", name, public, system, quirks, source_start, source_length)

    def comment(self, preposition, ref, text, source_start, source_length):
        self._handle_mutation("comment", preposition, ref, text, source_start, source_length)

    def error(self, text, pos):
        self._handle_simple("error", text, pos)

    def merge_attributes(self, element, attrs, source_start):
        self._handle_mutation("merge_attributes", element, attrs, source_start)

    def remove_node(self, element, source_start):
        self._handle_mutation("remove_node", element, source_start)

    def reparent_children(self, element, new_parent, source_start):
        self._handle_mutation("reparent_children", element, new_parent, source_start)


class DispatchTracer(TokenHandler):
    def __init__(self, input_: str, dispatcher, callback: Callable[[str], Any]):
        self.input = input_
        self.dispatcher = dispatcher
        self.callback = callback

    def _trace(self, msg: str) -> None:
        self.callback(f"[Dispatch] {msg}")

    @staticmethod
    def _excerpt(text: str) -> str:
        if len(text) > 20:
            text = text[:20] + "..."
        return text.replace("\n", "\\n")

    def _wrap(self, func_name: str, source_start: int, source_length: int, *args) -> None:
        prev_handler = self._get_handler_name()
        excerpt = self._excerpt(self.input[source_start:source_start + source_length])
        self._trace(f'{func_name} {prev_handler} "{excerpt}"')
        getattr(self.dispatcher, func_name)(*args)
        handler = self._get_handler_name()
        if prev_handler != handler:
            self._trace(f"{prev_handler} -> {handler}")

    def _get_handler_name(self) -> str:
        handler = self.dispatcher.get_handler()
        return type(handler).__name__ if handler else "NULL"

    def start_document(self, tokenizer, fragment_namespace, fragment_name):
        prev_handler = self._get_handler_name()
        ns_msg = "NULL" if fragment_namespace is None else fragment_namespace
        name_msg = "NULL" if fragment_name is None else fragment_name
        self._trace(f"startDocument {prev_handler} {ns_msg} {name_msg}")
        self.dispatcher.start_document(tokenizer, fragment_namespace, fragment_name)
        handler = self._get_handler_name()
        if prev_handler != handler:
            self._trace(f"{prev_handler} -> {handler}")

    def end_document(self, pos):
        self._wrap("end_document", pos, 0, pos)

    def error(self, text, pos):
        self._trace(f'error {self._get_handler_name()} "{text}"')
        self.dispatcher.error(text, pos)

    def characters(self, text, start, length, source_start, source_length):
        self._wrap("characters", source_start, source_length, text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        self._wrap("start_tag", source_start, source_length, name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        self._wrap("end_tag", source_start, source_length, name, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self._wrap("doctype", source_start, source_length, name, public, system, quirks, source_start,
                   source_length)

    def comment(self, text, source_start, source_length):
        self._wrap("comment", source_start, source_length, text, source_start, source_length)

# Ported from RemexHtml 3.0.2 src/TreeBuilder/TreeHandler.php, NullTreeHandler.php and RelayTreeHandler.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""Receivers of tree mutation events."""
from __future__ import annotations

from typing import Any, Optional

from ..tokenizer.attributes import Attributes
from .element import Element


class TreeHandler:
    """The interface for receivers of tree mutation events from the TreeBuilder.

    ``preposition`` arguments give the placement of the new node with respect to ``ref``. May be TreeBuilder::
     - BEFORE: insert as a sibling before the reference element
     - UNDER: append as the last child of the reference element
     - ROOT: append as the last child of the document node
    ``ref`` is the element to insert before/below, or null if ``preposition`` is ROOT.
    """

    def start_document(self, fragment_namespace: Optional[str], fragment_name: Optional[str]) -> None:
        """Called when parsing starts. The fragment namespace and tag name are None to run in document mode."""
        raise NotImplementedError

    def end_document(self, pos: int) -> None:
        """Called when parsing stops. ``pos``: the input string length, i.e. the past-the-end position."""
        raise NotImplementedError

    def characters(self, preposition: int, ref: Any, text: str, start: int, length: int, source_start: int,
                   source_length: int) -> None:
        """Insert characters.

        ``text``: the text to insert is a substring of this string, with the start and length of the substring
        given by ``start`` and ``length``. We do it this way to avoid unnecessary copying. ``source_start``: the
        input position. This is not necessarily accurate, particularly when the tokenizer is run without
        ignoreEntities, or in CDATA sections. ``source_length``: the length of the input which is consumed. The same
        caveats apply as for ``source_start``.
        """
        raise NotImplementedError

    def insert_element(self, preposition: int, ref: Any, element: Element, void: bool, source_start: int,
                       source_length: int) -> None:
        """Insert an element. The element name and attributes are given in the supplied Element object. Handlers
        for this event typically attach an identifier to the userData property of the Element object, to identify
        the element when it is used again in subsequent tree mutations.

        ``element``: an object containing information about the new element. The same object will be used for
        $parent and $refNode in other calls as appropriate. The handler can set $element->userData to attach a
        suitable DOM object to identify the mutation target in subsequent calls.
        ``void``: true if this is a void element which cannot have any children appended to it. This is usually
        true if the element is closed by the same token that opened it. No endTag() event will be sent for such an
        element. This is only true if self-closing tags are acknowledged for this tag name, so it is a hint to the
        serializer that a self-closing tag is acceptable.
        """
        raise NotImplementedError

    def end_tag(self, element: Element, source_start: int, source_length: int) -> None:
        """A hint that an element was closed and was removed from the stack of open elements. It probably won't be
        mutated again."""
        raise NotImplementedError

    def doctype(self, name: str, public: str, system: str, quirks: int, source_start: int,
                source_length: int) -> None:
        """A valid DOCTYPE token was found. ``quirks``: the quirks mode implied from the doctype. One of:
        TreeBuilder::NO_QUIRKS, LIMITED_QUIRKS, QUIRKS."""
        raise NotImplementedError

    def comment(self, preposition: int, ref: Any, text: str, source_start: int, source_length: int) -> None:
        """Insert a comment"""
        raise NotImplementedError

    def error(self, text: str, pos: int) -> None:
        """A parse error. ``text``: an error message explaining in English what the author did wrong, and what the
        parser intends to do about the situation."""
        raise NotImplementedError

    def merge_attributes(self, element: Element, attrs: Attributes, source_start: int) -> None:
        """Add attributes to an existing element. This is used to update the attributes of the <html> or <body>
        elements. The event receiver should add only those attributes which the original element does not already
        have. It should not overwrite existing attributes."""
        raise NotImplementedError

    def remove_node(self, element: Element, source_start: int) -> None:
        """Remove a node from the tree, and all its children. This is only done when a <frameset> element is found,
        which triggers removal of the partially-constructed body element."""
        raise NotImplementedError

    def reparent_children(self, element: Element, new_parent: Element, source_start: int) -> None:
        """Take all children of a given parent $element, and insert them as children of $newParent, removing them
        from their original parent in the process. Insert $newParent as now the only child of $element."""
        raise NotImplementedError


class NullTreeHandler(TreeHandler):
    def start_document(self, fragment_namespace, fragment_name):
        pass

    def end_document(self, pos):
        pass

    def characters(self, preposition, ref, text, start, length, source_start, source_length):
        pass

    def insert_element(self, preposition, ref, element, void, source_start, source_length):
        pass

    def end_tag(self, element, source_start, source_length):
        pass

    def doctype(self, name, public, system, quirks, source_start, source_length):
        pass

    def comment(self, preposition, ref, text, source_start, source_length):
        pass

    def error(self, text, pos):
        pass

    def merge_attributes(self, element, attrs, source_start):
        pass

    def remove_node(self, element, source_start):
        pass

    def reparent_children(self, element, new_parent, source_start):
        pass


class RelayTreeHandler(TreeHandler):
    """A TreeHandler which simply passes all events through to another handler. Applications can subclass this in
    order to modify only a few event types as they pass through."""

    def __init__(self, next_handler: TreeHandler):
        self.next_handler = next_handler

    def start_document(self, fragment_namespace, fragment_name):
        self.next_handler.start_document(fragment_namespace, fragment_name)

    def end_document(self, pos):
        self.next_handler.end_document(pos)

    def characters(self, preposition, ref, text, start, length, source_start, source_length):
        self.next_handler.characters(preposition, ref, text, start, length, source_start, source_length)

    def insert_element(self, preposition, ref, element, void, source_start, source_length):
        self.next_handler.insert_element(preposition, ref, element, void, source_start, source_length)

    def end_tag(self, element, source_start, source_length):
        self.next_handler.end_tag(element, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.next_handler.doctype(name, public, system, quirks, source_start, source_length)

    def comment(self, preposition, ref, text, source_start, source_length):
        self.next_handler.comment(preposition, ref, text, source_start, source_length)

    def error(self, text, pos):
        self.next_handler.error(text, pos)

    def merge_attributes(self, element, attrs, source_start):
        self.next_handler.merge_attributes(element, attrs, source_start)

    def remove_node(self, element, source_start):
        self.next_handler.remove_node(element, source_start)

    def reparent_children(self, element, new_parent, source_start):
        self.next_handler.reparent_children(element, new_parent, source_start)

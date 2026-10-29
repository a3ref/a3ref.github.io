# Ported from RemexHtml 3.0.2 src/TreeBuilder/ActiveFormattingElements.php and TemplateModeStack.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the destructor that breaks reference cycles
# is not needed.
"""The list of active formatting elements, and the stack of template insertion modes."""
from __future__ import annotations

from typing import Optional

from .element import Element, FormattingElement, Marker
from .stack import TreeBuilderError


class ActiveFormattingElements:
    """The list of active formatting elements"""

    def __init__(self) -> None:
        # The last (most recent) element in the list
        self.tail: Optional[FormattingElement] = None
        # The first (least recent) element in the list
        self.head: Optional[FormattingElement] = None
        # An array of arrays representing the population of elements in each bucket according to the Noah's Ark
        # clause. The outer array is stack-like, with each integer-indexed element representing a segment of the
        # list, bounded by markers. The first element represents the segment of the list before the first marker.
        #
        # The inner arrays are indexed by "Noah key", which is a string which uniquely identifies each bucket
        # according to the rules in the spec. The value in the inner array is the first (least recently inserted)
        # element in the bucket, and subsequent members of the bucket can be found by iterating through the
        # singly-linked list via $node->nextNoah.
        #
        # This is optimised for the most common case of inserting into a bucket with zero members, and deleting a
        # bucket containing one member. In the worst case, iteration through the list is still O(1) in the document
        # size, since each bucket can have at most 3 members.
        self.noah_table_stack: list[dict[tuple, Element]] = [{}]

    def insert_marker(self) -> None:
        """Insert a marker"""
        elt = Marker("marker")
        if self.tail:
            self.tail.next_afe = elt
            elt.prev_afe = self.tail
        else:
            self.head = elt
        self.tail = elt
        self.noah_table_stack.append({})

    def push(self, elt: Element) -> None:
        """Follow the steps required when the spec requires us to "push onto the list of active formatting
        elements"."""
        # Must not be in the list already
        if elt.prev_afe is not None or self.head is elt:
            raise Exception("Cannot insert a node into the AFE list twice")
        # "Noah's Ark clause" -- if there are already three copies of
        # this element before we encounter a marker, then drop the last
        # one.
        noah_key = elt.get_noah_key()
        table = self.noah_table_stack[-1]
        if noah_key not in table:
            table[noah_key] = elt
        else:
            count = 1
            head = tail = table[noah_key]
            while tail.next_noah:
                tail = tail.next_noah
                count += 1
            if count >= 3:
                self.remove(head)
            tail.next_noah = elt
        # Add to the main AFE list
        if self.tail:
            self.tail.next_afe = elt
            elt.prev_afe = self.tail
        else:
            self.head = elt
        self.tail = elt

    def clear_to_marker(self) -> None:
        """Follow the steps required when the spec asks us to "clear the list of active formatting elements up to
        the last marker"."""
        # Iterate back through the list starting from the tail
        tail = self.tail
        while tail and not isinstance(tail, Marker):
            # Unlink the element
            prev = tail.prev_afe
            tail.prev_afe = None
            if prev:
                prev.next_afe = None
            tail.next_noah = None
            tail = prev
        # If we finished on a marker, unlink it and pop it off the Noah table stack
        if tail:
            prev = tail.prev_afe
            if prev:
                prev.next_afe = None
            tail = prev
            self.noah_table_stack.pop()
        else:
            # No marker: wipe the top-level Noah table (which is the only one)
            self.noah_table_stack[0] = {}
        # If we removed all the elements, clear the head pointer
        if not tail:
            self.head = None
        self.tail = tail

    def find_element_by_name(self, name: str) -> Optional[Element]:
        """Find and return the last element with the specified name between the end of the list and the last
        marker on the list. Used when parsing <a> "in body mode"."""
        elt = self.tail
        while elt and not isinstance(elt, Marker):
            if elt.html_name == name:
                return elt
            elt = elt.prev_afe
        return None

    def is_in_list(self, elt: Element) -> bool:
        """Determine whether an element is in the list of formatting elements."""
        return self.head is elt or bool(elt.prev_afe)

    def remove(self, elt: FormattingElement) -> None:
        """Find the element $elt in the list and remove it. Used when parsing <a> in body mode."""
        if self.head is not elt and not elt.prev_afe:
            raise TreeBuilderError("Attempted to remove an element which is not in the AFE list")
        # Update head and tail pointers
        if self.head is elt:
            self.head = elt.next_afe
        if self.tail is elt:
            self.tail = elt.prev_afe
        # Update previous element
        if elt.prev_afe:
            elt.prev_afe.next_afe = elt.next_afe
        # Update next element
        if elt.next_afe:
            elt.next_afe.prev_afe = elt.prev_afe
        # Clear pointers so that isInList() etc. will work
        elt.prev_afe = elt.next_afe = None
        # Update Noah list
        if isinstance(elt, Element):
            self._remove_from_noah_list(elt)

    def _add_to_noah_list(self, elt: Element) -> None:
        """Add an element to a bucket of elements which are alike for the purposes of the Noah's Ark clause."""
        noah_key = elt.get_noah_key()
        table = self.noah_table_stack[-1]
        if noah_key not in table:
            table[noah_key] = elt
        else:
            tail = table[noah_key]
            while tail.next_noah:
                tail = tail.next_noah
            tail.next_noah = elt

    def _remove_from_noah_list(self, elt: Element) -> None:
        """Remove an element from its Noah's Ark bucket."""
        table = self.noah_table_stack[-1]
        key = elt.get_noah_key()
        noah_elt = table.get(key)
        if noah_elt is elt:
            if noah_elt.next_noah:
                table[key] = noah_elt.next_noah
                noah_elt.next_noah = None
            else:
                del table[key]
        else:
            while noah_elt:
                prev_noah_elt = noah_elt
                noah_elt = prev_noah_elt.next_noah
                if noah_elt is elt:
                    # Found it, unlink
                    prev_noah_elt.next_noah = elt.next_noah
                    elt.next_noah = None
                    break

    def replace(self, a: FormattingElement, b: FormattingElement) -> None:
        """Find element $a in the list and replace it with element $b"""
        if self.head is not a and not a.prev_afe:
            raise TreeBuilderError("Attempted to replace an element which is not in the AFE list")
        # Update head and tail pointers
        if self.head is a:
            self.head = b
        if self.tail is a:
            self.tail = b
        # Update previous element
        if a.prev_afe:
            a.prev_afe.next_afe = b
        # Update next element
        if a.next_afe:
            a.next_afe.prev_afe = b
        b.prev_afe = a.prev_afe
        b.next_afe = a.next_afe
        a.next_afe = a.prev_afe = None
        # Update Noah list
        if isinstance(a, Element):
            self._remove_from_noah_list(a)
        if isinstance(b, Element):
            self._add_to_noah_list(b)

    def insert_after(self, a: FormattingElement, b: FormattingElement) -> None:
        """Find $a in the list and insert $b after it."""
        if self.head is not a and not a.prev_afe:
            raise TreeBuilderError("Attempted to insert after an element which is not in the AFE list")
        if self.tail is a:
            self.tail = b
        if a.next_afe:
            a.next_afe.prev_afe = b
        b.next_afe = a.next_afe
        b.prev_afe = a
        a.next_afe = b
        if isinstance(b, Element):
            self._add_to_noah_list(b)

    def dump(self) -> str:
        """Get a string representation of the AFE list, for debugging"""
        prev = None
        s = ""
        node = self.head
        while node:
            if isinstance(node, Marker):
                s += "MARKER\n"
            else:
                s += node.get_debug_tag()
                if node.next_noah:
                    s += " (noah sibling: " + node.next_noah.get_debug_tag() + ")"
                if node.next_afe and node.next_afe.prev_afe is not node:
                    s += " (reverse link is wrong!)"
                s += "\n"
            prev = node
            node = node.next_afe
        if prev is not self.tail:
            s += "(tail pointer is wrong!)\n"
        return s

    def get_tail(self) -> Optional[FormattingElement]:
        """Get the most recently inserted element in the list"""
        return self.tail


class TemplateModeStack:
    """The stack of template insertion modes. We use a storage model optimised for access to the element at the
    top of the stack, which is stored separately from the rest of the stack."""

    def __init__(self) -> None:
        # The insertion mode at the top of the stack. This is public for performance reasons but should be treated
        # as read-only.
        self.current: Optional[int] = None
        # The remainder of the stack
        self.non_current_modes: list[Optional[int]] = []

    def push(self, mode: int) -> None:
        """Push a mode on to the stack"""
        self.non_current_modes.append(self.current)
        self.current = mode

    def pop(self) -> None:
        """Pop a mode from the stack"""
        self.current = self.non_current_modes.pop() if self.non_current_modes else None

    def is_empty(self) -> bool:
        """Return true if the stack is empty, false otherwise"""
        return self.current is None

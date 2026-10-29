# Ported from RemexHtml 3.0.2 src/TreeBuilder/TreeBuilder.php and TreeBuilderError.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The tree builder state and its helpers."""
from __future__ import annotations

from typing import Any, Mapping, Optional

from ..htmldata import HTMLData
from ..tokenizer.attributes import Attributes, PlainAttributes
from ..tokenizer.tokenizer import Tokenizer
from .active_formatting_elements import ActiveFormattingElements
from .element import Element, Marker
from .stack import CachingStack, SimpleStack, Stack, TreeBuilderError
from .tree_handler import TreeHandler

_FOSTER_TRIGGERS = frozenset(["table", "tbody", "tfoot", "thead", "tr"])

_IMPLIED_END_TAGS = frozenset(["dd", "dt", "li", "option", "optgroup", "p", "rb", "rp", "rt", "rtc"])

_THOROUGHLY_IMPLIED_END_TAGS = frozenset([
    "caption", "colgroup", "dd", "dt", "li", "optgroup", "option", "p", "rb", "rp", "rt", "rtc", "tbody", "td",
    "tfoot", "th", "thead", "tr",
])


class TreeBuilder:
    """TreeBuilder is the receiver of events from the InsertionMode subclasses, and is responsible for forwarding
    events on to the TreeHandler, which is responsible for constructing a DOM.

    TreeBuilder contains most of the state referred to by the "tree construction" part of the HTML spec which is
    not handled elsewhere, such as the stack of open elements and the list of active formatting elements.

    Miscellaneous helpers for InsertionMode subclasses are also in this class.

    https://www.w3.org/TR/2016/REC-html51-20161101/syntax.html
    """

    # Quirks
    NO_QUIRKS = 0
    LIMITED_QUIRKS = 1
    QUIRKS = 2

    # Insertion placement
    BEFORE = 0
    UNDER = 1
    ROOT = 2

    def __init__(self, handler: TreeHandler, options: Optional[Mapping[str, Any]] = None):
        """``handler``: the handler which receives tree mutation events; ``options``:
        - isIframeSrcdoc: True if the document is an iframe srcdoc document. Default false.
        - scriptingFlag: True if the scripting flag is enabled. Default true. Setting this to false cause the
          contents of <noscript> elements to be processed as normal content. The scriptingFlag option in the
          Tokenizer should be set to the same value.
        - ignoreErrors: True to ignore errors. This improves performance. Default false.
        - ignoreNulls: True to ignore null characters in the input, instead of following the specified behaviour.
          Default false.
        - scopeCache: True to use an implementation of the stack of open elements which caches "in scope"
          predicates. False to use a simpler implementation. Default true. Setting this to false may improve
          performance for simple documents, although at the expense of O(N^2) instead of O(N) worst case time
          order.
        """
        self.handler = handler
        self.afe = ActiveFormattingElements()
        options = {
            "isIframeSrcdoc": False,
            "scriptingFlag": True,
            "ignoreErrors": False,
            "ignoreNulls": False,
            "scopeCache": True,
            **(options or {}),
        }

        self.is_iframe_srcdoc = options["isIframeSrcdoc"]
        self.scripting_flag = options["scriptingFlag"]
        self.ignore_errors = options["ignoreErrors"]
        self.ignore_nulls = options["ignoreNulls"]

        self.stack: Stack = CachingStack() if options["scopeCache"] else SimpleStack()

        self.tokenizer: Optional[Tokenizer] = None

        # State
        self.is_fragment = False
        self.fragment_context: Optional[Element] = None
        self.head_element: Optional[Element] = None
        self.form_element: Optional[Element] = None
        self.frameset_ok = True
        self.quirks = self.NO_QUIRKS
        self.foster_parenting = False
        self.pending_table_characters: list[tuple[str, int, int, int, int]] = []

    def start_document(self, tokenizer: Tokenizer, namespace: Optional[str], name: Optional[str]) -> None:
        """Notify TreeBuilder and later pipeline stages of the start of a document. This is called by the Dispatcher
        when a startDocument event is received."""

        def enable_cdata() -> bool:
            acn = self.adjusted_current_node()
            return bool(acn) and acn.namespace != HTMLData.NS_HTML

        tokenizer.set_enable_cdata_callback(enable_cdata)
        self.tokenizer = tokenizer

        self.handler.start_document(namespace, name)
        if namespace is not None:
            self.is_fragment = True
            self.fragment_context = Element(namespace, name, PlainAttributes())
            self.fragment_context.is_virtual = True
            html = Element(HTMLData.NS_HTML, "html", PlainAttributes())
            html.is_virtual = True
            self.stack.push(html)
            self.handler.insert_element(self.ROOT, None, html, False, 0, 0)

    def adjusted_current_node(self) -> Optional[Element]:
        """Get the adjusted current node"""
        current = self.stack.current
        if self.is_fragment and (not current or current.stack_index == 0):
            return self.fragment_context
        else:
            return current

    def _appropriate_place(self, target: Optional[Element] = None) -> tuple[int, Optional[Element]]:
        """Find the appropriate place for inserting a node. ``target``: the override target. Returns a list with
        the preposition in the first element, and the reference node in the second element."""
        stack = self.stack
        if target is None:
            target = stack.current
        if target is None:
            return self.ROOT, None
        if not self.foster_parenting:
            return self.UNDER, target
        if target.html_name not in _FOSTER_TRIGGERS:
            return self.UNDER, target
        node = None
        for idx in range(stack.length() - 1, -1, -1):
            node = stack.item(idx)
            if node.html_name == "table" and idx >= 1:
                return self.BEFORE, node
            if node.html_name == "template":
                return self.UNDER, node
        return self.UNDER, node

    def insert_characters(self, text: str, start: int, length: int, source_start: int, source_length: int) -> None:
        """Insert characters at the appropriate place for inserting a node."""
        prep, ref = self._appropriate_place()
        self.handler.characters(prep, ref, text, start, length, source_start, source_length)

    def insert_element(self, name: str, attrs: Attributes, void: bool, source_start: int,
                       source_length: int) -> Element:
        """Insert an element in the HTML namespace, at the appropriate place for inserting a node. ``void``: the
        void (self-closing) element hint"""
        return self.insert_foreign(HTMLData.NS_HTML, name, attrs, void, source_start, source_length)

    def insert_foreign(self, ns: str, name: str, attrs: Attributes, void: bool, source_start: int,
                       source_length: int) -> Element:
        """Insert an element in any namespace, at the appropriate place for inserting a node."""
        prep, ref = self._appropriate_place()
        element = Element(ns, name, attrs)
        self.handler.insert_element(prep, ref, element, void, source_start, source_length)
        if not void:
            self.stack.push(element)
        return element

    def pop(self, source_start: int, source_length: int) -> Element:
        """Pop the current node from the stack of open elements, and notify the handler that we are done with that
        node."""
        element = self.stack.pop()
        self.handler.end_tag(element, source_start, source_length)
        return element

    def doctype(self, name: str, public: str, system: str, quirks: int, source_start: int,
                source_length: int) -> None:
        """Insert a doctype node. ``quirks``: the quirks mode. May be either self::NO_QUIRKS, self::LIMITED_QUIRKS
        or self::QUIRKS to indicate no-quirks mode, limited-quirks mode or quirks mode respectively."""
        self.handler.doctype(name, public, system, quirks, source_start, source_length)
        self.quirks = quirks

    def comment(self, place: Optional[tuple[int, Optional[Element]]], text: str, source_start: int,
                source_length: int) -> None:
        """Insert a comment. ``place``: the place where the node is to be inserted. May be either a
        preposition/refNode pair or null. If it is null, the node will be inserted at the "appropriate place"."""
        prep, ref = place if place is not None else self._appropriate_place()
        self.handler.comment(prep, ref, text, source_start, source_length)

    def error(self, text: str, pos: int) -> None:
        """Notify the handler of an error (if ignoreErrors is not set)."""
        if not self.ignore_errors:
            self.handler.error(text, pos)

    def merge_attributes(self, elt: Element, attrs: Attributes, source_start: int, source_length: int) -> None:
        """Add attributes to an existing element."""
        if attrs.count() and not elt.is_virtual:
            self.handler.merge_attributes(elt, attrs, source_start)

    def close_p_in_button_scope(self, pos: int) -> None:
        """If the stack of open elements has a p element in button scope, then close a p element.

        The above phrase appears many times in the spec.
        """
        if self.stack.is_in_button_scope("p"):
            self.generate_implied_end_tags_and_pop("p", pos, 0)

    def check_unclosed(self, allowed, pos: int) -> None:
        """Check the stack to see if there is any element which is not on the list of allowed elements. Raise an
        error if any are found. ``allowed``: the allowed HTML element names"""
        if self.ignore_errors:
            return

        stack = self.stack
        unclosed_errors: dict[str, bool] = {}
        for i in range(stack.length() - 1, -1, -1):
            unclosed_name = stack.item(i).html_name
            if unclosed_name not in allowed:
                unclosed_errors[unclosed_name] = True
        if unclosed_errors:
            names = ", ".join(unclosed_errors)
            self.error(f"closing unclosed {names}", pos)

    def reconstruct_afe(self, source_start: int) -> None:
        """Reconstruct the active formatting elements.
        @author C. Scott Ananian, Tim Starling
        """
        entry = self.afe.get_tail()
        # If there are no entries in the list of active formatting elements,
        # then there is nothing to reconstruct
        if not entry:
            return
        # If the last is a marker, do nothing.
        if isinstance(entry, Marker):
            return
        # Or if it is an open element, do nothing.
        if entry.stack_index is not None:
            return

        # Loop backward through the list until we find a marker or an
        # open element
        found_it = False
        while entry.prev_afe:
            entry = entry.prev_afe
            if isinstance(entry, Marker) or entry.stack_index is not None:
                found_it = True
                break

        # Now loop forward, starting from the element after the current one (or
        # the first element if we didn't find a marker or open element),
        # recreating formatting elements and pushing them back onto the list
        # of open elements.
        if found_it:
            entry = entry.next_afe
        while True:
            new_element = self.insert_foreign(HTMLData.NS_HTML, entry.name, entry.attrs.clone(), False,
                                              source_start, 0)
            self.afe.replace(entry, new_element)
            entry = new_element.next_afe
            if not entry:
                break

    def adoption_agency(self, subject: str, source_start: int, source_length: int) -> None:
        """Run the "adoption agency algorithm" (AAA) for the given subject tag name.
        @author C. Scott Ananian, Tim Starling
        """
        afe = self.afe
        stack = self.stack
        handler = self.handler

        # If the current node is an HTML element whose tag name is subject,
        # and the current node is not in the list of active formatting
        # elements, then pop the current node off the stack of open
        # elements and abort these steps. [1]
        if stack.current.html_name == subject and not afe.is_in_list(stack.current):
            self.pop(source_start, source_length)
            return

        # Outer loop: If outer loop counter is greater than or
        # equal to eight, then abort these steps. [2-4]
        for _outer in range(8):

            # Let the formatting element be the last element in the list
            # of active formatting elements that: is between the end of
            # the list and the last scope marker in the list, if any, or
            # the start of the list otherwise, and has the same tag name
            # as the token. [5]
            fmt_elt = afe.find_element_by_name(subject)

            # If there is no such node, then abort these steps and instead
            # act as described in the "any other end tag" entry above.
            if not fmt_elt:
                self.any_other_end_tag(subject, source_start, source_length)
                return

            # Otherwise, if there is such a node, but that node is not in
            # the stack of open elements, then this is a parse error;
            # remove the element from the list, and abort these steps. [6]
            fmt_elt_index = fmt_elt.stack_index
            if fmt_elt_index is None:
                self.error("closing tag matched an active formatting element which is not in the stack",
                           source_start)
                afe.remove(fmt_elt)
                return

            # Otherwise, if there is such a node, and that node is also in
            # the stack of open elements, but the element is not in scope,
            # then this is a parse error; ignore the token, and abort
            # these steps. [7]
            if not stack.is_element_in_scope(fmt_elt):
                self.error("end tag matched a start tag which is not in scope", source_start)
                return

            # If formatting element is not the current node, this is a parse
            # error. (But do not abort these steps.) [8]
            if fmt_elt is not stack.current:
                self.error("end tag matched a formatting element which was not the current node", source_start)

            # Let the furthest block be the topmost node in the stack of
            # open elements that is lower in the stack than the formatting
            # element, and is an element in the special category. There
            # might not be one. [9]
            furthest_block = None
            furthest_block_index = -1
            stack_length = stack.length()

            for i in range(fmt_elt_index + 1, stack_length):
                item = stack.item(i)
                if item.name in HTMLData.special.get(item.namespace, ()):
                    furthest_block = item
                    furthest_block_index = i
                    break

            # If there is no furthest block, then the UA must skip the
            # subsequent steps and instead just pop all the nodes from the
            # bottom of the stack of open elements, from the current node up
            # to and including the formatting element, and remove the
            # formatting element from the list of active formatting
            # elements. [10]
            if not furthest_block:
                self.pop_all_up_to_element(fmt_elt, source_start, source_length)
                afe.remove(fmt_elt)
                return

            # Let the common ancestor be the element immediately above the
            # formatting element in the stack of open elements. [11]
            ancestor = stack.item(fmt_elt_index - 1)

            # Let a bookmark note the position of the formatting element in
            # the list of active formatting elements relative to the elements
            # on either side of it in the list. [12]
            bookmark = Marker("bookmark")
            afe.insert_after(fmt_elt, bookmark)

            # Let node and last node be the furthest block. [13]
            last_node = furthest_block
            node_index = furthest_block_index
            stack_removals: dict[int, bool] = {}
            insertions: list[tuple[int, Optional[Element], Element]] = []

            # Inner loop
            inner = 0
            while True:
                inner += 1
                # Let node be the element immediately above node in the stack
                # of open elements, or if node is no longer in the stack of
                # open elements (e.g. because it got removed by this
                # algorithm), the element that was immediately above node in
                # the stack of open elements before node was removed. [13.3]
                node_index -= 1
                node = stack.item(node_index)

                # If node is the formatting element, then go to the next step
                # in the overall algorithm. [13.4]
                if node is fmt_elt:
                    break

                # If the inner loop counter is greater than three and node
                # is in the list of active formatting elements, then remove
                # node from the list of active formatting elements. [13.5]
                is_afe = afe.is_in_list(node)
                if inner > 3 and is_afe:
                    afe.remove(node)
                    is_afe = False

                # If node is not in the list of active formatting elements,
                # then remove node from the stack of open elements and then
                # go back to the step labeled inner loop. [13.6]
                if not is_afe:
                    stack_removals[node_index] = True
                    continue

                # Create an element for the token for which the element node
                # was created with common ancestor as the intended parent,
                # replace the entry for node in the list of active formatting
                # elements with an entry for the new element, replace the
                # entry for node in the stack of open elements with an entry
                # for the new element, and let node be the new element. [13.7]
                new_elt = Element(node.namespace, node.name, node.attrs.clone())
                afe.replace(node, new_elt)
                stack.replace(node, new_elt)
                node = new_elt

                # If last node is the furthest block, then move the
                # aforementioned bookmark to be immediately after the new node
                # in the list of active formatting elements. [13.8]
                if last_node is furthest_block:
                    afe.remove(bookmark)
                    afe.insert_after(new_elt, bookmark)

                # Insert last node into node, first removing it from its
                # previous parent node if any. [13.9]
                insertions.append((self.UNDER, node, last_node))

                # Let last node be node. [13.10]
                last_node = node

            # Insert whatever last node ended up being in the previous step at
            # the appropriate place for inserting a node, but using common
            # ancestor as the override target. [14]
            prep, ref = self._appropriate_place(ancestor)
            insertions.append((prep, ref, last_node))

            # Execute queued insertions in reverse order.
            # This has the same effect but allows the handler to assume that
            # elements are always in the tree.
            for ins in reversed(insertions):
                handler.insert_element(ins[0], ins[1], ins[2], False, source_start, 0)

            # Create an element for the token for which the formatting element
            # was created, with furthest block as the intended parent. [15]
            new_elt2 = Element(fmt_elt.namespace, fmt_elt.name, fmt_elt.attrs.clone())

            # Take all of the child nodes of the furthest block and append
            # them to the element created in the last step. [16]
            # Append the new element to the furthest block. [17]
            handler.reparent_children(furthest_block, new_elt2, source_start)

            # Remove the formatting element from the list of active formatting
            # elements, and insert the new element into the list of active
            # formatting elements at the position of the aforementioned
            # bookmark. [18]
            afe.remove(fmt_elt)
            afe.replace(bookmark, new_elt2)

            # Remove the formatting element from the stack of open elements,
            # and insert the new element into the stack of open elements
            # immediately below the position of the furthest block in that
            # stack. [19]

            # Make a temporary stack with the elements we are going to push back in
            temp_stack = []

            # Stash the elements up to the furthest block
            index = stack.length() - 1
            while index > furthest_block_index:
                temp_stack.append(stack.pop())
                index -= 1
            # Add the new element
            temp_stack.append(new_elt2)
            # Stash the elements up to the formatting element
            while index > fmt_elt_index:
                elt = stack.pop()
                # Drop elements previously marked for removal
                if index in stack_removals:
                    handler.end_tag(elt, source_start, 0)
                else:
                    temp_stack.append(elt)
                index -= 1
            # Remove the formatting element
            elt = stack.pop()
            handler.end_tag(elt, source_start, 0)
            # Reinsert
            for elt in reversed(temp_stack):
                stack.push(elt)

    def any_other_end_tag(self, name: str, source_start: int, source_length: int) -> None:
        """Perform the steps required when "any other end tag" is encountered in the "in body" insertion mode."""
        stack = self.stack
        for index in range(stack.length() - 1, -1, -1):
            node = stack.item(index)
            if node.html_name == name:
                self.generate_implied_end_tags(name, source_start)
                # If node is not the current node, then this is a parse error
                if node is not stack.current:
                    self.error("end tag matched an element which was not the current node", source_start)
                # Pop all the nodes from the current node up to node, including
                # node, then stop these steps.
                for _ in range(stack.length() - 1, index, -1):
                    elt = stack.pop()
                    self.handler.end_tag(elt, source_start, 0)
                elt = stack.pop()
                self.handler.end_tag(elt, source_start, source_length)
                return

            # If node is in the special category, then this is a parse error;
            # ignore the token, and abort these steps
            if node.name in HTMLData.special.get(node.namespace, ()):
                self.error(f"cannot implicitly close a special element <{node.html_name}>", source_start)
                return

    def generate_implied_end_tags(self, name: Optional[str], pos: int) -> None:
        """Generate implied end tags, optionally with an element to exclude. ``name``: the name to exclude, or None
        (false in PHP)"""
        stack = self.stack
        current = stack.current
        while current and current.html_name != name and current.html_name in _IMPLIED_END_TAGS:
            popped = stack.pop()
            self.handler.end_tag(popped, pos, 0)
            current = stack.current

    def generate_implied_end_tags_thoroughly(self, pos: int) -> None:
        """Generate all implied end tags thoroughly. This was introduced in HTML 5.1 in order to expand the set of
        elements which can be implicitly closed by a </template>."""
        stack = self.stack
        current = stack.current
        while current and current.html_name in _THOROUGHLY_IMPLIED_END_TAGS:
            popped = stack.pop()
            self.handler.end_tag(popped, pos, 0)
            current = stack.current

    def generate_implied_end_tags_and_pop(self, name: str, source_start: int, source_length: int) -> None:
        """Generate implied end tags, with an element to exclude, and if the current element is not now the named
        excluded element, raise an error. Then, pop all elements until an element with the name is popped from the
        list."""
        self.generate_implied_end_tags(name, source_start)
        if self.stack.current.html_name != name:
            self.error(f"found </{name}> but elements are open that cannot have implied end tags, closing them",
                       source_start)
        self.pop_all_up_to_name(name, source_start, source_length)

    def pop_all_up_to_element(self, elt: Element, source_start: int, source_length: int) -> None:
        """Pop elements from the stack until the specified element is popped."""
        while True:
            popped = self.stack.pop()
            if not popped:
                break
            elif popped is elt:
                self.handler.end_tag(popped, source_start, source_length)
                break
            else:
                self.handler.end_tag(popped, source_start, 0)

    def pop_all_up_to_name(self, name: str, source_start: int, source_length: int) -> None:
        """Pop elements from the stack until an element in the HTML namespace with the specified name is popped."""
        while True:
            popped = self.stack.pop()
            if not popped:
                break
            elif popped.html_name == name:
                self.handler.end_tag(popped, source_start, source_length)
                break
            else:
                self.handler.end_tag(popped, source_start, 0)

    def pop_all_up_to_names(self, names, source_start: int, source_length: int) -> None:
        """Pop elements from the stack until an element with one of the specified names is popped. ``names``: the
        allowed names"""
        while True:
            popped = self.stack.pop()
            if not popped:
                break
            elif popped.html_name in names:
                self.handler.end_tag(popped, source_start, source_length)
                break
            else:
                self.handler.end_tag(popped, source_start, 0)

    def clear_stack_back(self, names, pos: int) -> None:
        """The "clear stack back to" algorithm used by several template insertion modes. Similar to
        popAllUpToName(), except that the named element is not popped, and a set of names is used instead of a
        single name."""
        stack = self.stack
        while stack.current and stack.current.html_name not in names:
            self.pop(pos, 0)
        if not stack.current:
            raise TreeBuilderError("clearStackBack: stack is unexpectedly empty")

    def stop_parsing(self, pos: int) -> None:
        """Take the steps required when the spec says to "stop parsing". This occurs when an end-of-file token is
        received, and is equivalent to the endDocument() methods elsewhere."""
        stack = self.stack
        while stack.current:
            popped = stack.pop()
            if not self.is_fragment or popped.html_name != "html":
                self.handler.end_tag(popped, pos, 0)
        self.handler.end_document(pos)

        self.afe = ActiveFormattingElements()
        self.head_element = None
        self.form_element = None
        self.tokenizer.set_enable_cdata_callback(None)
        self.tokenizer = None

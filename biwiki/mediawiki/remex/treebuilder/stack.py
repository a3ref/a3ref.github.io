# Ported from RemexHtml 3.0.2 src/TreeBuilder/Stack.php, SimpleStack.php and CachingStack.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The stack of open elements."""
from __future__ import annotations

from typing import Mapping, Optional

from ..htmldata import HTMLData
from .element import Element


class TreeBuilderError(Exception):
    pass


class Stack:
    """The parent class for the "stack of open elements".
    @see CachingStack
    @see SimpleStack
    """

    def __init__(self) -> None:
        self.current: Optional[Element] = None

    def push(self, elt: Element) -> None:
        """Push an element"""
        raise NotImplementedError

    def pop(self) -> Optional[Element]:
        """Pop an element from the stack"""
        raise NotImplementedError

    def replace(self, old: Element, new: Element) -> None:
        """Replace an element which is on the stack with another element of the same type (i.e. with the same tag
        name)."""
        raise NotImplementedError

    def remove(self, elt: Element) -> None:
        """Remove an element, potentially from the middle of the stack."""
        raise NotImplementedError

    def is_in_scope(self, name: str) -> bool:
        """Is there an element in (default) scope which is in the HTML namespace and has the given tag name?"""
        raise NotImplementedError

    def is_element_in_scope(self, elt: Element) -> bool:
        """Is the given element in (default) scope?"""
        raise NotImplementedError

    def is_one_of_set_in_scope(self, names: Mapping[str, object]) -> bool:
        """Is there any element in the (default) scope which is in the HTML namespace and has one of the given tag
        names? ``names``: the tag names in the keys (any collection of names works)"""
        raise NotImplementedError

    def is_in_list_scope(self, name: str) -> bool:
        """Is there an element in list scope which is an HTML element with the given name?"""
        raise NotImplementedError

    def is_in_button_scope(self, name: str) -> bool:
        """Is there an element in button scope which is an HTML element with the given name?"""
        raise NotImplementedError

    def is_in_table_scope(self, name: str) -> bool:
        """Is there an element in table scope which is an HTML element with the given name?"""
        raise NotImplementedError

    def is_in_select_scope(self, name: str) -> bool:
        """Is there an element in select scope which is an HTML element with the given name?"""
        raise NotImplementedError

    def item(self, idx: int) -> Optional[Element]:
        """Get an element from the stack, where 0 is the first element inserted, and $this->length() - 1 is the most
        recently inserted element. (PHP raises a notice and gives null if the index is out of range; so does this,
        without the notice.)"""
        raise NotImplementedError

    def length(self) -> int:
        """Get the number of elements in the stack."""
        raise NotImplementedError

    def has_template(self) -> bool:
        """Is there a template element in the stack of open elements?"""
        raise NotImplementedError

    def dump(self) -> str:
        """Get a string representation of the stack for debugging purposes."""
        s = ""
        for i in range(self.length()):
            item = self.item(i)
            s += f"{i}. " + item.get_debug_tag()
            if i == self.length() - 1 and item is not self.current:
                s += " CURRENT POINTER INCORRECT"
            s += "\n"
        return s


_DEFAULT_SCOPE: dict[str, frozenset[str]] = {
    HTMLData.NS_HTML: frozenset(["applet", "caption", "html", "table", "td", "th", "marquee", "object",
                                 "template"]),
    HTMLData.NS_MATHML: frozenset(["mi", "mo", "mn", "ms", "mtext", "annotation-xml"]),
    HTMLData.NS_SVG: frozenset(["foreignObject", "desc", "title"]),
}
_TABLE_SCOPE: dict[str, frozenset[str]] = {
    HTMLData.NS_HTML: frozenset(["html", "table", "template"]),
}
_LIST_SCOPE = dict(_DEFAULT_SCOPE)
_LIST_SCOPE[HTMLData.NS_HTML] = _DEFAULT_SCOPE[HTMLData.NS_HTML] | {"ol", "li"}
_BUTTON_SCOPE = dict(_DEFAULT_SCOPE)
_BUTTON_SCOPE[HTMLData.NS_HTML] = _DEFAULT_SCOPE[HTMLData.NS_HTML] | {"button"}
_EMPTY: frozenset[str] = frozenset()


class SimpleStack(Stack):
    """An implementation of the "stack of open elements" which, unlike CachingStack, iterates through the stack in
    order to answer queries about which elements are in scope. This is presumably faster for best case input."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[Element] = []

    def push(self, elt: Element) -> None:
        n = len(self.elements)
        self.elements.append(elt)
        self.current = elt
        elt.stack_index = n

    def pop(self) -> Optional[Element]:
        elt = self.elements.pop() if self.elements else None
        if elt is not None:
            elt.stack_index = None
        n = len(self.elements)
        self.current = self.elements[n - 1] if n else None
        return elt

    def replace(self, old_elt: Element, elt: Element) -> None:
        idx = old_elt.stack_index
        self.elements[idx] = elt
        old_elt.stack_index = None
        elt.stack_index = idx
        if idx == len(self.elements) - 1:
            self.current = elt

    def remove(self, elt: Element) -> None:
        # (sic: RemexHtml renumbers the elements above but leaves $elt in the array)
        elt_index = elt.stack_index
        n = len(self.elements)
        for i in range(elt_index + 1, n):
            self.elements[i].stack_index -= 1
        elt.stack_index = None

    def is_in_scope(self, name: str) -> bool:
        return self._is_in_specific_scope(name, _DEFAULT_SCOPE)

    def is_element_in_scope(self, elt: Element) -> bool:
        for node in reversed(self.elements):
            if node is elt:
                return True
            if node.name in _DEFAULT_SCOPE.get(node.namespace, _EMPTY):
                return False
        return False

    def is_one_of_set_in_scope(self, names) -> bool:
        for node in reversed(self.elements):
            if node.namespace == HTMLData.NS_HTML and node.name in names:
                return True
            if node.name in _DEFAULT_SCOPE.get(node.namespace, _EMPTY):
                return False
        return False

    def is_in_list_scope(self, name: str) -> bool:
        return self._is_in_specific_scope(name, _LIST_SCOPE)

    def is_in_button_scope(self, name: str) -> bool:
        return self._is_in_specific_scope(name, _BUTTON_SCOPE)

    def is_in_table_scope(self, name: str) -> bool:
        return self._is_in_specific_scope(name, _TABLE_SCOPE)

    def is_in_select_scope(self, name: str) -> bool:
        for node in reversed(self.elements):
            if node.namespace == HTMLData.NS_HTML and node.name == name:
                return True
            if node.namespace != HTMLData.NS_HTML:
                return False
            if node.name != "optgroup" and node.name != "option":
                return False
        return False

    def _is_in_specific_scope(self, name: str, set_: Mapping[str, frozenset[str]]) -> bool:
        for node in reversed(self.elements):
            if node.namespace == HTMLData.NS_HTML and node.name == name:
                return True
            if node.name in set_.get(node.namespace, _EMPTY):
                return False
        return False

    def item(self, idx: int) -> Optional[Element]:
        return self.elements[idx] if 0 <= idx < len(self.elements) else None

    def length(self) -> int:
        return len(self.elements)

    def has_template(self) -> bool:
        for elt in self.elements:
            if elt.namespace == HTMLData.NS_HTML and elt.name == "template":
                return True
        return False


SCOPE_DEFAULT = 0
SCOPE_LIST = 1
SCOPE_BUTTON = 2
SCOPE_TABLE = 3
SCOPE_SELECT = 4

_ALL_SCOPES = (SCOPE_DEFAULT, SCOPE_LIST, SCOPE_BUTTON, SCOPE_TABLE, SCOPE_SELECT)
_NON_TABLE_SCOPES = (SCOPE_DEFAULT, SCOPE_LIST, SCOPE_BUTTON, SCOPE_SELECT)
_LIST_SCOPES = (SCOPE_LIST, SCOPE_SELECT)
_BUTTON_SCOPES = (SCOPE_BUTTON, SCOPE_SELECT)
_SELECT_ONLY = (SCOPE_SELECT,)

_MATH_BREAKERS = frozenset(["mi", "mo", "mn", "ms", "mtext", "annotation-xml"])
_SVG_BREAKERS = frozenset(["foreignObject", "desc", "title"])

# If you compile every predicate of the form "an X element in Y scope" in the HTML 5 spec, you discover that every
# element name X corresponds to at most one such scope Y. This is useful because it means when we see a new
# element, we need to add it to at most one scope cache.
#
# This is a list of such statements in the spec, and the scope they relate to. All formatting elements are
# included as SCOPE_DEFAULT since the AAA involves pulling an item out of the AFE list and checking if it is in
# scope.
_PREDICATE_MAP = {
    "a": SCOPE_DEFAULT,
    "address": SCOPE_DEFAULT,
    "applet": SCOPE_DEFAULT,
    "article": SCOPE_DEFAULT,
    "aside": SCOPE_DEFAULT,
    "b": SCOPE_DEFAULT,
    "big": SCOPE_DEFAULT,
    "blockquote": SCOPE_DEFAULT,
    "body": SCOPE_DEFAULT,
    "button": SCOPE_DEFAULT,
    "caption": SCOPE_TABLE,
    "center": SCOPE_DEFAULT,
    "code": SCOPE_DEFAULT,
    "dd": SCOPE_DEFAULT,
    "details": SCOPE_DEFAULT,
    "dialog": SCOPE_DEFAULT,
    "dir": SCOPE_DEFAULT,
    "div": SCOPE_DEFAULT,
    "dl": SCOPE_DEFAULT,
    "dt": SCOPE_DEFAULT,
    "em": SCOPE_DEFAULT,
    "fieldset": SCOPE_DEFAULT,
    "figcaption": SCOPE_DEFAULT,
    "figure": SCOPE_DEFAULT,
    "font": SCOPE_DEFAULT,
    "footer": SCOPE_DEFAULT,
    "form": SCOPE_DEFAULT,
    "h1": SCOPE_DEFAULT,
    "h2": SCOPE_DEFAULT,
    "h3": SCOPE_DEFAULT,
    "h4": SCOPE_DEFAULT,
    "h5": SCOPE_DEFAULT,
    "h6": SCOPE_DEFAULT,
    "header": SCOPE_DEFAULT,
    "hgroup": SCOPE_DEFAULT,
    "i": SCOPE_DEFAULT,
    "li": SCOPE_LIST,
    "listing": SCOPE_DEFAULT,
    "main": SCOPE_DEFAULT,
    "marquee": SCOPE_DEFAULT,
    "menu": SCOPE_DEFAULT,
    "nav": SCOPE_DEFAULT,
    "nobr": SCOPE_DEFAULT,
    "object": SCOPE_DEFAULT,
    "ol": SCOPE_DEFAULT,
    "p": SCOPE_BUTTON,
    "pre": SCOPE_DEFAULT,
    "ruby": SCOPE_DEFAULT,
    "s": SCOPE_DEFAULT,
    "section": SCOPE_DEFAULT,
    "select": SCOPE_SELECT,
    "small": SCOPE_DEFAULT,
    "strike": SCOPE_DEFAULT,
    "strong": SCOPE_DEFAULT,
    "summary": SCOPE_DEFAULT,
    "table": SCOPE_TABLE,
    "tbody": SCOPE_TABLE,
    "td": SCOPE_TABLE,
    "tfoot": SCOPE_TABLE,
    "th": SCOPE_TABLE,
    "thead": SCOPE_TABLE,
    "tr": SCOPE_TABLE,
    "tt": SCOPE_DEFAULT,
    "u": SCOPE_DEFAULT,
    "ul": SCOPE_DEFAULT,
}


def _get_scope_types_to_stack(ns: str, name: str) -> tuple[int, ...]:
    """For a given namespace and element name, get the list of scopes for which a new scope should be created and
    the old one needs to be pushed onto the scope stack."""
    if ns == HTMLData.NS_HTML:
        if name in ("html", "table", "template"):
            return _ALL_SCOPES
        if name in ("applet", "caption", "td", "th", "marquee", "object"):
            return _NON_TABLE_SCOPES
        if name in ("ol", "ul"):
            return _LIST_SCOPES
        if name == "button":
            return _BUTTON_SCOPES
        if name in ("option", "optgroup"):
            return ()
        return _SELECT_ONLY
    elif ns == HTMLData.NS_MATHML:
        if name in _MATH_BREAKERS:
            return _NON_TABLE_SCOPES
        else:
            return _SELECT_ONLY
    elif ns == HTMLData.NS_SVG:
        if name in _SVG_BREAKERS:
            return _NON_TABLE_SCOPES
        else:
            return _SELECT_ONLY
    else:
        return _SELECT_ONLY


class CachingStack(Stack):
    """An implementation of the "stack of open elements" which includes a cache of elements currently in the
    various kinds of scope. It presumably has good worst-case performance at the expense of somewhat slower
    updates."""

    def __init__(self) -> None:
        super().__init__()
        # The stack of open elements
        self.elements: list[Element] = []
        # A cache of the elements which are currently in a given scope. The first key is the scope ID, the second
        # key is the element name, and the value is the first Element in a singly-linked list of Element objects,
        # linked by $element->nextEltInScope.
        self.scopes: list[dict[str, Optional[Element]]] = [{}, {}, {}, {}, {}]
        # This is the part of the scope cache which stores scope lists for objects which are not currently in
        # scope. The first key is the scope ID, the second key is the stack index, the third key is the element
        # name, and the value is the Element object.
        self.scope_stacks: list[list[dict[str, Optional[Element]]]] = [[], [], [], [], []]
        # The number of <template> elements in the stack of open elements. This speeds up the hot function
        # hasTemplate().
        self.template_count = 0

    def push(self, elt: Element) -> None:
        # Update the stack store
        n = len(self.elements)
        self.elements.append(elt)
        # Update the current node and index cache
        self.current = elt
        elt.stack_index = n
        # Update the scope cache
        ns = elt.namespace
        name = elt.name
        for type_ in _get_scope_types_to_stack(ns, name):
            self.scope_stacks[type_].append(self.scopes[type_])
            self.scopes[type_] = {}
        if ns == HTMLData.NS_HTML and name in _PREDICATE_MAP:
            scope = self.scopes[_PREDICATE_MAP[name]]
            elt.next_elt_in_scope = scope.get(name)
            scope[name] = elt
        # Update the template count
        if ns == HTMLData.NS_HTML and name == "template":
            self.template_count += 1

    def pop(self) -> Element:
        n = len(self.elements)
        if not n:
            raise TreeBuilderError("CachingStack::pop: stack empty")
        # Update the stack store, index cache and current node
        elt = self.elements.pop()
        n -= 1
        elt.stack_index = None
        ns = elt.namespace
        name = elt.name
        self.current = self.elements[n - 1] if n else None
        # Update the scope cache
        if ns == HTMLData.NS_HTML and name in _PREDICATE_MAP:
            self.scopes[_PREDICATE_MAP[name]][name] = elt.next_elt_in_scope
            elt.next_elt_in_scope = None
        for scope in _get_scope_types_to_stack(ns, name):
            self.scopes[scope] = self.scope_stacks[scope].pop()
        # Update the template count
        if ns == HTMLData.NS_HTML and name == "template":
            self.template_count -= 1
        return elt

    def replace(self, old_elt: Element, elt: Element) -> None:
        idx = old_elt.stack_index
        # AAA calls this function only for elements with the same name, which
        # simplifies the scope cache update, and eliminates the template count
        # update
        if old_elt.name != elt.name or old_elt.namespace != elt.namespace:
            raise TreeBuilderError("CachingStack::replace can only be called for elements of the same name")
        ns = elt.namespace
        name = elt.name
        # Find the old element in its scope list and replace it
        if ns == HTMLData.NS_HTML and name in _PREDICATE_MAP:
            type_ = _PREDICATE_MAP[name]
            scope_elt = self.scopes[type_].get(name)
            if scope_elt is old_elt:
                self.scopes[type_][name] = elt
                elt.next_elt_in_scope = scope_elt.next_elt_in_scope
                scope_elt.next_elt_in_scope = None
            else:
                next_elt = scope_elt.next_elt_in_scope if scope_elt is not None else None
                while next_elt:
                    if next_elt is old_elt:
                        scope_elt.next_elt_in_scope = elt
                        elt.next_elt_in_scope = next_elt.next_elt_in_scope
                        next_elt.next_elt_in_scope = None
                        break
                    scope_elt = scope_elt.next_elt_in_scope
                    next_elt = scope_elt.next_elt_in_scope
                if not next_elt:
                    raise TreeBuilderError("CachingStack::replace: cannot find old element in scope cache")
        # Replace the stack element
        self.elements[idx] = elt
        if idx == len(self.elements) - 1:
            self.current = elt
        old_elt.stack_index = None
        elt.stack_index = idx

    def remove(self, elt: Element) -> None:
        temp_stack = []
        elt_index = elt.stack_index
        if elt_index is None:
            raise TreeBuilderError("CachingStack::remove: element not in stack")
        n = len(self.elements)
        for _ in range(n - 1, elt_index, -1):
            temp_stack.append(self.pop())
        self.pop()
        for temp in reversed(temp_stack):
            self.push(temp)

    def is_in_scope(self, name: str) -> bool:
        if _PREDICATE_MAP.get(name) != SCOPE_DEFAULT:
            raise TreeBuilderError(f'Unexpected predicate: "{name} is in scope"')
        return bool(self.scopes[SCOPE_DEFAULT].get(name))

    def is_element_in_scope(self, elt: Element) -> bool:
        name = elt.name
        if _PREDICATE_MAP.get(name) != SCOPE_DEFAULT:
            raise TreeBuilderError(f'Unexpected predicate: "{name} is in scope"')
        scope_member = self.scopes[SCOPE_DEFAULT].get(name)
        while scope_member:
            if scope_member is elt:
                return True
            scope_member = scope_member.next_elt_in_scope
        return False

    def is_one_of_set_in_scope(self, names) -> bool:
        for name in names:
            if self.is_in_scope(name):
                return True
        return False

    def is_in_list_scope(self, name: str) -> bool:
        if _PREDICATE_MAP.get(name) != SCOPE_LIST:
            raise TreeBuilderError(f'Unexpected predicate: "{name} is in list scope"')
        return bool(self.scopes[SCOPE_LIST].get(name))

    def is_in_button_scope(self, name: str) -> bool:
        if _PREDICATE_MAP.get(name) != SCOPE_BUTTON:
            raise TreeBuilderError(f'Unexpected predicate: "{name} is in button scope"')
        return bool(self.scopes[SCOPE_BUTTON].get(name))

    def is_in_table_scope(self, name: str) -> bool:
        if _PREDICATE_MAP.get(name) != SCOPE_TABLE:
            raise TreeBuilderError(f'Unexpected predicate: "{name} is in table scope"')
        return bool(self.scopes[SCOPE_TABLE].get(name))

    def is_in_select_scope(self, name: str) -> bool:
        if _PREDICATE_MAP.get(name) != SCOPE_SELECT:
            raise TreeBuilderError(f'Unexpected predicate: "{name} is in select scope"')
        return bool(self.scopes[SCOPE_SELECT].get(name))

    def item(self, idx: int) -> Optional[Element]:
        return self.elements[idx] if 0 <= idx < len(self.elements) else None

    def length(self) -> int:
        return len(self.elements)

    def has_template(self) -> bool:
        return bool(self.template_count)

    def dump(self) -> str:
        return (super().dump() + self._scope_dump(SCOPE_DEFAULT, "In scope")
                + self._scope_dump(SCOPE_LIST, "In list scope") + self._scope_dump(SCOPE_BUTTON, "In button scope")
                + self._scope_dump(SCOPE_TABLE, "In table scope")
                + self._scope_dump(SCOPE_SELECT, "In select scope") + "\n")

    def _scope_dump(self, type_: int, scope_name: str) -> str:
        if self.scopes[type_]:
            return f"{scope_name}: " + ", ".join(self.scopes[type_]) + "\n"
        else:
            return ""

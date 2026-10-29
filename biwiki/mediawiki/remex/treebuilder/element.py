# Ported from RemexHtml 3.0.2 src/TreeBuilder/Element.php, FormattingElement.php and Marker.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the Noah's Ark key is a tuple instead of
# PHP's serialize() output.
"""Elements of the tree builder, and markers in the list of active formatting elements."""
from __future__ import annotations

import itertools
from typing import Any, Optional

from .._php import strtolower
from ..htmldata import HTMLData
from ..tokenizer.attributes import Attributes


class FormattingElement:
    """An interface for things that can go in the ActiveFormattingElements list"""

    __slots__ = ()


# The element types in the MathML namespace which are MathML text integration points.
_MATHML_INTEGRATION = frozenset(["mi", "mo", "mn", "ms", "mtext"])

# The element types in the SVG namespace which are SVG text integration points.
_SVG_HTML_INTEGRATION = frozenset(["foreignObject", "desc", "title"])

# The next unique ID to be used
_next_uid = itertools.count(1)


class Element(FormattingElement):
    """Storage for all the state that TreeBuilder needs to associate with each element. These objects should be
    freed once they fall out of TreeBuilder's data structures (the stack etc.).

    These objects are also used to communicate information about elements with downstream clients.

    Attributes:
    - namespace: The namespace. This will be the HTML namespace for elements that are not in foreign content, even
      if there is a prefix.
    - name: The tag name, usually exactly as it appeared in the source document. This is not strictly a local
      name, since it still contains a colon for prefixed elements. In foreign content, it is effectively a local
      name. It is suitable for use as a serialized tag name.
    - html_name: This is an internal designation of the type of the element, which is equal to the tag name when
      the element is in the HTML namespace, and is some other string when the element is not in the HTML
      namespace.
    - is_virtual: This is true if the element was created by the TreeBuilder either as a fragment context node, or
      as a synthetic <html> element to be used as the top-level element in fragment parsing.
    - next_elt_in_scope: Internal to CachingStack. A link in the scope list.
    - stack_index: Internal to CachingStack and SimpleStack. The current stack index, or null if the element is
      not in the stack.
    - prev_afe, next_afe, next_noah: Internal to ActiveFormattingElements.
    - user_data: This member variable can be written to by the TreeHandler, to store any state associated with the
      element (such as a DOM node). It is not used by TreeBuilder.
    - uid: A unique ID which identifies the element
    """

    __slots__ = ("namespace", "name", "html_name", "attrs", "is_virtual", "next_elt_in_scope", "stack_index",
                 "prev_afe", "next_afe", "next_noah", "_noah_key", "user_data", "uid")

    def __init__(self, namespace: str, name: str, attrs: Attributes):
        self.namespace = namespace
        self.name = name
        if namespace == HTMLData.NS_HTML:
            self.html_name = name
        elif namespace == HTMLData.NS_MATHML:
            self.html_name = f"mathml {name}"
        elif namespace == HTMLData.NS_SVG:
            self.html_name = f"svg {name}"
        else:
            self.html_name = f"{namespace} {name}"
        self.attrs = attrs
        self.uid = next(_next_uid)
        self.is_virtual = False
        self.next_elt_in_scope: Optional[Element] = None
        self.stack_index: Optional[int] = None
        self.prev_afe: Optional[FormattingElement] = None
        self.next_afe: Optional[FormattingElement] = None
        self.next_noah: Optional[Element] = None
        self._noah_key: Optional[tuple] = None
        self.user_data: Any = None

    def is_mathml_text_integration(self) -> bool:
        """Is the element a MathML text integration point?"""
        return self.namespace == HTMLData.NS_MATHML and self.name in _MATHML_INTEGRATION

    def is_html_integration(self) -> bool:
        """Is the element an HTML integration point?"""
        if self.namespace == HTMLData.NS_MATHML:
            if "encoding" in self.attrs:
                encoding = strtolower(self.attrs["encoding"])
                return encoding == "text/html" or encoding == "application/xhtml+xml"
            else:
                return False
        elif self.namespace == HTMLData.NS_SVG:
            return self.name in _SVG_HTML_INTEGRATION
        else:
            return False

    def get_noah_key(self) -> tuple:
        """Get a key for the Noah's Ark algorithm"""
        if self._noah_key is None:
            attrs = self.attrs.get_values()
            self._noah_key = (self.html_name, tuple(sorted(attrs.items())))
        return self._noah_key

    def get_debug_tag(self) -> str:
        """Get a string identifying the element, for use in debugging."""
        return f"{self.html_name}#{self.uid}"


class Marker(FormattingElement):
    """A pseudo-element used as a marker or bookmark in the list of active formatting elements"""

    __slots__ = ("next_afe", "prev_afe", "next_noah", "type")

    def __init__(self, type_: str):
        self.type = type_
        self.next_afe: Optional[FormattingElement] = None
        self.prev_afe: Optional[FormattingElement] = None
        self.next_noah = None

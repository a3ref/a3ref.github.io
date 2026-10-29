# Ported from MediaWiki 1.39 includes/parser/PPNode.php, PPNode_Hash_Tree.php, PPNode_Hash_Text.php,
# PPNode_Hash_Attr.php and PPNode_Hash_Array.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the PPNode interface is not a separate class;
# "false" results are None; MWException is a local exception class.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The nodes of the preprocessor's tree (the "Hash" implementation).

A node store is a list where each element is either a string (a text node) or a "descriptor": a two-element list
``[name, children]`` where ``children`` is again a node store. Attributes are descriptors whose name starts with
"@" and whose single child is a scalar (str or int). The PPNode_Hash_* objects are temporary proxies over a store
and an index into it.
"""
from __future__ import annotations

from typing import Optional, Union


class MWException(Exception):
    """MediaWiki's generic exception, raised for malformed node trees."""


def _htmlspecialchars(value) -> str:
    """htmlspecialchars( $value, ENT_COMPAT ): & < > and the double quote, not the single quote."""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


Node = Union["PPNode_Hash_Tree", "PPNode_Hash_Text", "PPNode_Hash_Attr"]


class PPNode_Hash_Tree:  # noqa: N801 - MediaWiki's class name
    # The offset of the name within descriptors, used in some places for readability.
    NAME = 0
    # The offset of the child list within descriptors, used in some places for readability.
    CHILDREN = 1

    def __init__(self, store: list, index: int):
        """Construct an object using the data from ``store[index]``. The rest of the store array can be accessed
        via get_next_sibling()."""
        # The store array for the siblings of this node, including this node itself.
        self.store = store
        # The index into self.store which contains the descriptor of this node.
        self.index = index
        # rawChildren: the store array for children of this node. It is "raw" in the sense that nodes are
        # two-element lists ("descriptors") rather than PPNode_Hash_* objects.
        self.name, self.raw_children = store[index]

    @staticmethod
    def factory(store: list, index: int) -> Optional[Node]:
        """Construct an appropriate PPNode_Hash_* object with a class that depends on what is at the relevant store
        index; None if there is nothing there."""
        if not (0 <= index < len(store)) or store[index] is None:
            return None

        descriptor = store[index]
        if isinstance(descriptor, str):
            cls = PPNode_Hash_Text
        elif isinstance(descriptor, list):
            if descriptor[PPNode_Hash_Tree.NAME][0] == "@":
                cls = PPNode_Hash_Attr
            else:
                cls = PPNode_Hash_Tree
        else:
            raise MWException("PPNode_Hash_Tree::factory: invalid node descriptor")
        return cls(store, index)

    def __str__(self) -> str:
        """Convert a node to XML, for debugging"""
        inner = ""
        attribs = ""
        node = self.get_first_child()
        while node:
            if isinstance(node, PPNode_Hash_Attr):
                attribs += " " + node.name + '="' + _htmlspecialchars(node.value) + '"'
            else:
                inner += str(node)
            node = node.get_next_sibling()
        if inner == "":
            return f"<{self.name}{attribs}/>"
        return f"<{self.name}{attribs}>{inner}</{self.name}>"

    def get_children(self) -> PPNode_Hash_Array:
        return PPNode_Hash_Array([self.factory(self.raw_children, i) for i in range(len(self.raw_children))])

    def get_first_child(self) -> Optional[Node]:
        """Get the first child, or None if there is none. Note that this will return a temporary proxy object:
        different instances will be returned if this is called more than once on the same node."""
        if not self.raw_children or self.raw_children[0] is None:
            return None
        return self.factory(self.raw_children, 0)

    def get_next_sibling(self) -> Optional[Node]:
        """Get the next sibling, or None if there is none. Note that this will return a temporary proxy object:
        different instances will be returned if this is called more than once on the same node."""
        return self.factory(self.store, self.index + 1)

    def get_children_of_type(self, name: str) -> PPNode_Hash_Array:
        """Get an array of the children with a given node name"""
        children = []
        for i, child in enumerate(self.raw_children):
            if isinstance(child, list) and child[self.NAME] == name:
                children.append(self.factory(self.raw_children, i))
        return PPNode_Hash_Array(children)

    def get_raw_children(self) -> list:
        """Get the raw child array. For internal use."""
        return self.raw_children

    def get_length(self) -> bool:
        return False

    def item(self, i: int) -> bool:
        return False

    def get_name(self) -> str:
        return self.name

    def split_arg(self) -> dict:
        """Split a "<part>" node into a dict containing:
         - name          PPNode name
         - index         String index
         - value         PPNode value
        """
        return self.split_raw_arg(self.raw_children)

    @staticmethod
    def split_raw_arg(children: list) -> dict:
        """Like split_arg() but for a raw child array. For internal use only."""
        bits = {}
        for i, child in enumerate(children):
            if not isinstance(child, list):
                continue
            if child[PPNode_Hash_Tree.NAME] == "name":
                bits["name"] = PPNode_Hash_Tree(children, i)
                grandchildren = child[PPNode_Hash_Tree.CHILDREN]
                if (grandchildren and isinstance(grandchildren[0], list)
                        and grandchildren[0][PPNode_Hash_Tree.NAME] == "@index"):
                    bits["index"] = grandchildren[0][PPNode_Hash_Tree.CHILDREN][0]
            elif child[PPNode_Hash_Tree.NAME] == "value":
                bits["value"] = PPNode_Hash_Tree(children, i)

        if "name" not in bits:
            raise MWException("Invalid brace node passed to PPNode_Hash_Tree::splitRawArg")
        if "index" not in bits:
            bits["index"] = ""
        return bits

    def split_ext(self) -> dict:
        """Split an "<ext>" node into a dict containing name, attr, inner and close. All values in the resulting
        dict are PPNodes. Inner and close are optional."""
        return self.split_raw_ext(self.raw_children)

    @staticmethod
    def split_raw_ext(children: list) -> dict:
        """Like split_ext() but for a raw child array. For internal use only."""
        bits = {}
        for i, child in enumerate(children):
            if not isinstance(child, list):
                continue
            if child[PPNode_Hash_Tree.NAME] in ("name", "attr", "inner", "close"):
                bits[child[PPNode_Hash_Tree.NAME]] = PPNode_Hash_Tree(children, i)
        if "name" not in bits:
            raise MWException("Invalid ext node passed to PPNode_Hash_Tree::splitRawExt")
        return bits

    def split_heading(self) -> dict:
        """Split an "<h>" node"""
        if self.name != "h":
            raise MWException("Invalid h node passed to PPNode_Hash_Tree::splitHeading")
        return self.split_raw_heading(self.raw_children)

    @staticmethod
    def split_raw_heading(children: list) -> dict:
        """Like split_heading() but for a raw child array. For internal use only."""
        bits = {}
        for child in children:
            if not isinstance(child, list):
                continue
            if child[PPNode_Hash_Tree.NAME] == "@i":
                bits["i"] = child[PPNode_Hash_Tree.CHILDREN][0]
            elif child[PPNode_Hash_Tree.NAME] == "@level":
                bits["level"] = child[PPNode_Hash_Tree.CHILDREN][0]
        if "i" not in bits:
            raise MWException("Invalid h node passed to PPNode_Hash_Tree::splitRawHeading")
        return bits

    def split_template(self) -> dict:
        """Split a "<template>" or "<tplarg>" node"""
        return self.split_raw_template(self.raw_children)

    @staticmethod
    def split_raw_template(children: list) -> dict:
        """Like split_template() but for a raw child array. For internal use only."""
        parts = []
        bits = {"lineStart": ""}
        for i, child in enumerate(children):
            if not isinstance(child, list):
                continue
            name = child[PPNode_Hash_Tree.NAME]
            if name == "title":
                bits["title"] = PPNode_Hash_Tree(children, i)
            elif name == "part":
                parts.append(PPNode_Hash_Tree(children, i))
            elif name == "@lineStart":
                bits["lineStart"] = "1"
        if "title" not in bits:
            raise MWException("Invalid node passed to PPNode_Hash_Tree::splitRawTemplate")
        bits["parts"] = PPNode_Hash_Array(parts)
        return bits


class PPNode_Hash_Text:  # noqa: N801 - MediaWiki's class name
    def __init__(self, store: list, index: int):
        """Construct an object using the data from ``store[index]``. The rest of the store array can be accessed
        via get_next_sibling()."""
        self.value = store[index]
        if not isinstance(self.value, (str, int, float, bool)):
            raise MWException("PPNode_Hash_Text given object instead of string")
        self.store = store
        self.index = index

    def __str__(self) -> str:
        return _htmlspecialchars(self.value)

    def get_next_sibling(self) -> Optional[Node]:
        return PPNode_Hash_Tree.factory(self.store, self.index + 1)

    def get_children(self) -> bool:
        return False

    def get_first_child(self) -> None:
        return None

    def get_children_of_type(self, name: str) -> bool:
        return False

    def get_length(self) -> bool:
        return False

    def item(self, i: int) -> bool:
        return False

    def get_name(self) -> str:
        return "#text"

    def split_arg(self):
        raise MWException("PPNode_Hash_Text::splitArg: not supported")

    def split_ext(self):
        raise MWException("PPNode_Hash_Text::splitExt: not supported")

    def split_heading(self):
        raise MWException("PPNode_Hash_Text::splitHeading: not supported")


class PPNode_Hash_Attr:  # noqa: N801 - MediaWiki's class name
    def __init__(self, store: list, index: int):
        """Construct an object using the data from ``store[index]``. The rest of the store array can be accessed
        via get_next_sibling()."""
        descriptor = store[index]
        if descriptor[PPNode_Hash_Tree.NAME][0] != "@":
            raise MWException("PPNode_Hash_Attr::__construct: invalid name in attribute descriptor")
        self.name: str = descriptor[PPNode_Hash_Tree.NAME][1:]
        self.value = descriptor[PPNode_Hash_Tree.CHILDREN][0]
        self.store = store
        self.index = index

    def __str__(self) -> str:
        return f"<@{self.name}>" + _htmlspecialchars(self.value) + f"</@{self.name}>"

    def get_name(self) -> str:
        return self.name

    def get_next_sibling(self) -> Optional[Node]:
        return PPNode_Hash_Tree.factory(self.store, self.index + 1)

    def get_children(self) -> bool:
        return False

    def get_first_child(self) -> None:
        return None

    def get_children_of_type(self, name: str) -> bool:
        return False

    def get_length(self) -> bool:
        return False

    def item(self, i: int) -> bool:
        return False

    def split_arg(self):
        raise MWException("PPNode_Hash_Attr::splitArg: not supported")

    def split_ext(self):
        raise MWException("PPNode_Hash_Attr::splitExt: not supported")

    def split_heading(self):
        raise MWException("PPNode_Hash_Attr::splitHeading: not supported")


class PPNode_Hash_Array:  # noqa: N801 - MediaWiki's class name
    """A list of nodes. Deliberately without __len__: like a PHP object it is true even when empty."""

    def __init__(self, value: list):
        self.value = value

    def __str__(self) -> str:
        # PHP: var_export( $this, true )
        return f"PPNode_Hash_Array({self.value!r})"

    def get_length(self) -> int:
        return len(self.value)

    def item(self, i: int):
        return self.value[i]

    def get_name(self) -> str:
        return "#nodelist"

    def get_next_sibling(self) -> None:
        return None

    def get_children(self) -> bool:
        return False

    def get_first_child(self) -> None:
        return None

    def get_children_of_type(self, name: str) -> bool:
        return False

    def split_arg(self):
        raise MWException("PPNode_Hash_Array::splitArg: not supported")

    def split_ext(self):
        raise MWException("PPNode_Hash_Array::splitExt: not supported")

    def split_heading(self):
        raise MWException("PPNode_Hash_Array::splitHeading: not supported")

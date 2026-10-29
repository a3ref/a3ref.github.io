# Ported from RemexHtml 3.0.2 src/Tokenizer/Attribute.php, Attributes.php, PlainAttributes.php and
# LazyAttributes.php (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; PHP's ArrayAccess and IteratorAggregate
# became the mapping methods (``in``, ``[]``, ``del``; iteration gives the names, items() the pairs).
"""Attributes emitted by the tokenizer."""
from __future__ import annotations

from typing import Any, Callable, Iterator, Optional


class Attribute:
    """A namespaced attribute, as returned by Attributes::getObjects()"""

    __slots__ = ("qualified_name", "namespace_uri", "prefix", "local_name", "value")

    def __init__(self, qualified_name: str, namespace_uri: Optional[str], prefix: Optional[str], local_name: str,
                 value: str):
        self.qualified_name = qualified_name
        self.namespace_uri = namespace_uri
        self.prefix = prefix
        self.local_name = local_name
        self.value = value


class Attributes:
    """Interface for attributes emitted by the tokenizer"""

    def get_values(self) -> dict[str, str]:
        """Get the attributes as a key/value array"""
        raise NotImplementedError

    def get_objects(self) -> dict[str, Attribute]:
        """Get the attributes as an array of Attribute objects"""
        raise NotImplementedError

    def count(self) -> int:
        """Get the number of attributes. This may include duplicates, and so may be larger than
        count( $this->getValues() ). Including duplicates gives us an efficient way to distinguish zero attributes
        from non-zero but is not compliant with the spec, which states that duplicate attributes must be removed.
        """
        raise NotImplementedError

    def merge(self, other: Attributes) -> None:
        """Add any attributes in the argument to $this, but if an attribute of the same name already exists, do not
        overwrite it."""
        raise NotImplementedError

    def clone(self) -> Attributes:
        """It's efficient to assume that attributes are immutable when cloning nodes due to AFE reconstruction or
        AAA. So by default, this returns $this. But users can override it if attribute cloning needs special
        handling."""
        raise NotImplementedError

    def __contains__(self, key: object) -> bool:
        raise NotImplementedError

    def __getitem__(self, key: str) -> str:
        raise NotImplementedError

    def __setitem__(self, key: str, value: str) -> None:
        raise NotImplementedError

    def __delitem__(self, key: str) -> None:
        raise NotImplementedError

    def __iter__(self) -> Iterator[str]:
        return iter(self.get_values())

    def items(self):
        return self.get_values().items()


class PlainAttributes(Attributes):
    """An Attributes implementation which is a simple array proxy."""

    def __init__(self, data: Optional[dict[str, str]] = None):
        self.data: dict[str, str] = dict(data) if data else {}
        self.attr_objects: Optional[dict[str, Attribute]] = None

    def merge(self, other: Attributes) -> None:
        for name, value in other.items():
            if name not in self:
                self[name] = value

    def __contains__(self, key: object) -> bool:
        return key in self.data

    def __getitem__(self, key: str) -> str:
        return self.data[key]

    def __setitem__(self, key: str, value: str) -> None:
        self.data[key] = value
        if self.attr_objects is not None:
            self.attr_objects[key] = Attribute(key, None, None, key, value)

    def __delitem__(self, key: str) -> None:
        self.data.pop(key, None)
        if self.attr_objects is not None:
            self.attr_objects.pop(key, None)

    def get_values(self) -> dict[str, str]:
        return self.data

    def get_objects(self) -> dict[str, Attribute]:
        if self.attr_objects is None:
            self.attr_objects = {name: Attribute(name, None, None, name, value) for name, value in self.data.items()}
        return self.attr_objects

    def count(self) -> int:
        return len(self.data)

    def clone(self) -> Attributes:
        return self


class LazyAttributes(Attributes):
    """An Attributes implementation which defers interpretation of regex match results until the caller requires
    them.

    This should not be directly instantiated outside of Tokenizer.
    """

    def __init__(self, data: Any, interpreter: Callable[[Any], dict[str, str]]):
        self.interpreter: Optional[Callable[[Any], dict[str, str]]] = interpreter
        self.data = data
        self.attributes: Optional[dict[str, str]] = None
        self.attr_objects: Optional[dict[str, Attribute]] = None

    def init(self) -> None:
        """Initialize the attributes array"""
        if self.attributes is None:
            func = self.interpreter
            self.attributes = func(self.data)
            self.interpreter = None
            self.data = None

    def __contains__(self, offset: object) -> bool:
        if self.attributes is None:
            self.init()
        return offset in self.attributes

    def __getitem__(self, offset: str) -> str:
        if self.attributes is None:
            self.init()
        return self.attributes[offset]

    def __setitem__(self, offset: str, value: str) -> None:
        if self.attributes is None:
            self.init()
        self.attributes[offset] = value
        if self.attr_objects is not None:
            self.attr_objects[offset] = Attribute(offset, None, None, offset, value)

    def __delitem__(self, offset: str) -> None:
        if self.attributes is None:
            self.init()
        self.attributes.pop(offset, None)
        if self.attr_objects is not None:
            self.attr_objects.pop(offset, None)

    def get_values(self) -> dict[str, str]:
        if self.attributes is None:
            self.init()
        return self.attributes

    def get_objects(self) -> dict[str, Attribute]:
        if self.attr_objects is None:
            if self.attributes is None:
                self.init()
            self.attr_objects = {name: Attribute(name, None, None, name, value)
                                 for name, value in self.attributes.items()}
        return self.attr_objects

    def count(self) -> int:
        if self.attributes is None:
            return len(self.data)
        return len(self.attributes)

    def merge(self, other: Attributes) -> None:
        if self.attributes is None:
            self.init()
        for name, value in other.items():
            if name not in self.attributes:
                self.attributes[name] = value

    def clone(self) -> Attributes:
        return self

# Ported from RemexHtml 3.0.2 src/Serializer/AbstractSerializer.php, Serializer.php, SerializerNode.php,
# SerializerError.php and SerializerWithTracer.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""A TreeHandler which serializes the document as it is built."""
from __future__ import annotations

from typing import Any, Callable, Optional, Union

from ..tokenizer.attributes import Attributes, PlainAttributes
from ..treebuilder.element import Element
from ..treebuilder.tracer import TraceFormatter
from ..treebuilder.tree_builder import TreeBuilder
from ..treebuilder.tree_handler import TreeHandler
from .formatters import Formatter


class SerializerError(Exception):
    pass


class SerializerNode:
    """A node in the serializer's tree.

    Attributes: id (the integer index into Serializer::$nodes of this node), parent_id (the integer index into
    Serializer::$nodes of the parent node), namespace, name, attrs, void (the void flag as in
    TreeHandler::insertElement), children (encoded strings and SerializerNodes), sn_data (arbitrary user data can be
    placed here).
    """

    __slots__ = ("id", "parent_id", "namespace", "name", "attrs", "void", "children", "sn_data")

    def __init__(self, id_: int, parent_id: int, namespace: str, name: str, attrs: Attributes, void: bool):
        self.id = id_
        self.parent_id = parent_id
        self.namespace = namespace
        self.name = name
        self.attrs = attrs
        self.void = void
        self.children: list[Union[str, SerializerNode]] = []
        self.sn_data: Any = None

    def get_debug_tag(self) -> str:
        """Get a string identifying the node, for use in debugging."""
        return f"{self.name}#{self.id}"


class AbstractSerializer(TreeHandler):
    def get_result(self) -> str:
        """Get the serialized result of tree construction"""
        raise NotImplementedError


def _index_of(children: list, node: Any) -> int:
    """array_search( $node, $children, true ): the index of ``node`` by identity, or -1 (false in PHP)"""
    for i, child in enumerate(children):
        if child is node:
            return i
    return -1


class Serializer(AbstractSerializer):
    """A TreeHandler which builds a serialized representation of a document, by encoding elements when the end tags
    are seen. This is faster than building a DOM and then serializing it, even if you use
    DOMDocument::saveHTML()."""

    def __init__(self, formatter: Formatter, error_callback: Optional[Callable[[str, int], Any]] = None):
        """``error_callback``: a function which is called with the details of each parse error"""
        self.formatter = formatter
        self.error_callback = error_callback
        # A node corresponding to the Document
        self.root: Optional[SerializerNode] = None
        # All active SerializerNode objects in an array, so that they can be referred to by integer indexes. This
        # is a way to emulate weak references, to avoid circular references, allowing nodes to be freed.
        self.nodes: dict[int, SerializerNode] = {}
        # True if we are parsing a fragment. The children of the <html> element will be serialized, instead of the
        # whole document.
        self.is_fragment = False
        # The result string
        self.result = ""

    def get_result(self) -> str:
        """Get the final string. This can only be called after endDocument() is received."""
        return self.result

    def get_root_node(self) -> SerializerNode:
        """Get the root SerializerNode."""
        return self.root

    def get_parent_node(self, node: SerializerNode) -> SerializerNode:
        """Get the parent SerializerNode of a given SerializerNode"""
        return self.nodes[node.parent_id]

    def get_last_child(self, node: SerializerNode) -> Union[SerializerNode, str, None]:
        """Get the last child of a given SerializerNode"""
        children = node.children
        return children[-1] if children else None

    def start_document(self, fragment_namespace, fragment_name):
        self.root = SerializerNode(0, 0, "", "", PlainAttributes(), False)
        self.nodes = {0: self.root}
        self.is_fragment = fragment_namespace is not None
        self.result = self.formatter.start_document(fragment_namespace, fragment_name)

    def end_document(self, pos):
        if self.is_fragment:
            root = self.root.children[0]
        else:
            root = self.root
        parts = [self.result]
        for child in root.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                parts.append(self._serialize_node(root, child, False))
        self.result = "".join(parts)
        self.root = None
        self.nodes = {}

    def interpret_placement(self, preposition: int,
                            ref_element: Any) -> tuple[SerializerNode, Optional[SerializerNode]]:
        if preposition == TreeBuilder.ROOT:
            return self.root, None
        if isinstance(ref_element, Element):
            ref_node = ref_element.user_data
        elif isinstance(ref_element, SerializerNode):
            ref_node = ref_element
        else:
            raise SerializerError("Invalid type of ref element")
        if preposition == TreeBuilder.BEFORE:
            return self.nodes[ref_node.parent_id], ref_node
        else:
            return ref_node, ref_node

    def characters(self, preposition, ref_element, text, start, length, source_start, source_length):
        parent, ref_node = self.interpret_placement(preposition, ref_element)
        encoded = str(self.formatter.characters(parent, text, start, length))
        children = parent.children
        last_child_index = len(children) - 1
        last_child = children[last_child_index] if last_child_index >= 0 else None
        if preposition == TreeBuilder.BEFORE:
            # Insert before element
            if last_child is not ref_node:
                ref_index = _index_of(children, ref_node)
                raise SerializerError(f"invalid insert position {ref_index}/{last_child_index}")
            children[last_child_index] = encoded
            children.append(ref_node)
        else:
            # Append to the list of children
            if isinstance(last_child, str):
                children[last_child_index] += encoded
            else:
                children.append(encoded)

    def insert_element(self, preposition, ref_element, element, void, source_start, source_length):
        parent, ref_node = self.interpret_placement(preposition, ref_element)
        children = parent.children
        last_child_index = len(children) - 1
        last_child = children[last_child_index] if last_child_index >= 0 else None
        if element.user_data:
            # This element has already been inserted, this is a reparenting operation
            self_ = element.user_data
            old_parent = self.nodes[self_.parent_id]
            old_children = old_parent.children
            old_child_index = _index_of(old_children, self_)
            if old_child_index == -1:
                raise SerializerError("cannot find node to reparent: " + element.get_debug_tag())
            # Remove from the old parent, update parent pointer
            old_children[old_child_index] = ""
            self_.parent_id = parent.id
        else:
            # Inserting an element which has not been seen before
            id_ = element.uid
            self_ = SerializerNode(id_, parent.id, element.namespace, element.name, element.attrs, void)
            self.nodes[id_] = element.user_data = self_
        if preposition == TreeBuilder.BEFORE:
            # Insert before element
            if last_child is not ref_node:
                ref_index = _index_of(children, ref_node)
                raise SerializerError(f"invalid insert position {ref_index}/{last_child_index}")
            children[last_child_index] = self_
            children.append(ref_node)
        else:
            # Append to the list of children
            children.append(self_)

    def end_tag(self, element, source_start, source_length):
        if element.html_name == "head" or element.is_virtual:
            # <head> elements are immortal
            return
        self_ = element.user_data
        parent = self.nodes[self_.parent_id]
        children = parent.children
        for index in range(len(children) - 1, -1, -1):
            if children[index] is self_:
                children[index] = self._serialize_node(parent, self_, True)
                return
        # Ignore requests to end non-existent elements (this happens sometimes)

    def _serialize_node(self, parent: SerializerNode, node: SerializerNode, destroy: bool) -> str:
        """Serialize a specific node. ``destroy``: if true, the node and its descendants will be removed from
        $this->nodes"""
        if node.void:
            contents = None
        else:
            parts = []
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    parts.append(self._serialize_node(node, child, destroy))
            contents = "".join(parts)
        if destroy:
            self.nodes.pop(node.id, None)
        return self.formatter.element(parent, node, contents)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.result += self.formatter.doctype(name, public, system)

    def comment(self, preposition, ref_element, text, source_start, source_length):
        parent, ref_node = self.interpret_placement(preposition, ref_element)
        encoded = self.formatter.comment(parent, text)
        children = parent.children
        last_child_index = len(children) - 1
        last_child = children[last_child_index] if last_child_index >= 0 else None
        if preposition == TreeBuilder.BEFORE:
            # Insert before element
            if last_child is not ref_node:
                raise SerializerError("invalid insert position")
            children[last_child_index] = encoded
            children.append(ref_node)
        else:
            # Append to the list of children
            if isinstance(last_child, str):
                children[last_child_index] += encoded
            else:
                children.append(encoded)

    def error(self, text, pos):
        if self.error_callback:
            self.error_callback(text, pos)

    def merge_attributes(self, element, attrs, source_start):
        element.attrs.merge(attrs)
        if isinstance(element.user_data, SerializerNode):
            element.user_data.attrs = element.attrs

    def remove_node(self, element, source_start):
        self_ = element.user_data
        parent = self.nodes[self_.parent_id]
        children = parent.children
        for index in range(len(children) - 1, -1, -1):
            if children[index] is self_:
                children[index] = ""
                return
        raise SerializerError("cannot find element to remove")

    def reparent_children(self, element, new_parent, source_start):
        self_ = element.user_data
        children = self_.children
        self_.children = []
        self.insert_element(TreeBuilder.UNDER, element, new_parent, False, source_start, 0)
        new_parent_node = new_parent.user_data
        new_parent_id = new_parent_node.id
        for child in children:
            if not isinstance(child, str):
                child.parent_id = new_parent_id
        new_parent_node.children = children

    def dump(self) -> str:
        """Get a text representation of the current state of the serializer, for debugging."""
        s = self._serialize_node(self.root, self.root, False)
        return s[2:-3] + "\n"


class SerializerWithTracer(Serializer):
    def __init__(self, formatter: Formatter, error_callback: Optional[Callable[[str, int], Any]] = None,
                 trace_callback: Optional[Callable[[str], Any]] = None, verbosity: int = 0):
        self.trace_callback = trace_callback
        self.verbosity = verbosity
        super().__init__(formatter, error_callback)

    def _handle(self, func_name: str, *args) -> None:
        self._trace(getattr(TraceFormatter, func_name)(*args))
        getattr(super(), func_name)(*args)
        if self.verbosity > 0 and func_name != "end_document":
            self._trace(f"Dump after {func_name}: " + self.dump())

    def _trace(self, msg: str) -> None:
        self.trace_callback(f"[Serializer] {msg}")

    def start_document(self, fragment_namespace, fragment_name):
        self._handle("start_document", fragment_namespace, fragment_name)

    def end_document(self, pos):
        if self.nodes:
            node_tags = ", ".join(node.get_debug_tag() for node in self.nodes.values())
            self._trace(f"endDocument: unclosed elements: {node_tags}")
        else:
            self._trace("endDocument: no unclosed elements")
        self._handle("end_document", pos)

    def characters(self, preposition, ref_element, text, start, length, source_start, source_length):
        self._handle("characters", preposition, ref_element, text, start, length, source_start, source_length)

    def insert_element(self, preposition, ref_element, element, void, source_start, source_length):
        self._handle("insert_element", preposition, ref_element, element, void, source_start, source_length)

    def end_tag(self, element, source_start, source_length):
        self._handle("end_tag", element, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self._handle("doctype", name, public, system, quirks, source_start, source_length)

    def comment(self, preposition, ref_element, text, source_start, source_length):
        self._handle("comment", preposition, ref_element, text, source_start, source_length)

    def error(self, text, pos):
        self._handle("error", text, pos)

    def merge_attributes(self, element, attrs, source_start):
        self._handle("merge_attributes", element, attrs, source_start)

    def remove_node(self, element, source_start):
        self._handle("remove_node", element, source_start)

    def reparent_children(self, element, new_parent, source_start):
        self._handle("reparent_children", element, new_parent, source_start)

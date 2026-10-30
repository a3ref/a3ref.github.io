# Ported from MediaWiki 1.39 includes/tidy/RemexDriver.php, includes/tidy/RemexCompatFormatter.php,
# includes/tidy/RemexCompatMunger.php, includes/tidy/RemexMungerData.php, includes/tidy/RemexCompatBuilder.php and
# includes/tidy/TidyDriverBase.php (https://www.mediawiki.org/), (C) MediaWiki contributors; these files as in
# MediaWiki 1.39.0, the release the wiki runs (they do not differ from REL1_39 commit 19ddcf0 except that
# RemexCompatFormatter there also escapes U+0338 and normalizes character references only outside raw text elements,
# later fixes for T387130 and T406391).
# Changed by a3ref contributors on 2026-10-30: translated to Python, on top of the Python port of RemexHtml 3.0.2
# (biwiki/mediawiki/remex/, MIT); the configuration ($wgTidyConfig, $wgParserEnableLegacyMediaDOM) is passed as
# arguments with MediaWiki 1.39's defaults; tracing goes to the logging module instead of wfDebug().
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tidy: the HTML cleanup MediaWiki runs on the parser output (RemexHtml with p-wrapping and its own formatter)."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Mapping, Optional

from .remex.htmldata import HTMLData
from .remex.serializer import HtmlFormatter, Serializer, SerializerNode, SerializerWithTracer
from .remex.tokenizer import PlainAttributes, Tokenizer
from .remex.treebuilder import Dispatcher, Element, Marker, TreeBuilder, TreeHandler, TreeMutationTracer
from .remex.serializer.formatters import strtr
from .sanitizer import normalize_char_references

logger = logging.getLogger(__name__)


def _wf_debug(msg: str) -> None:
    logger.debug("%s", msg)


def _strspn_blank(text: str) -> int:
    """strspn( $text, "\\t\\n\\f\\r " )"""
    return len(text) - len(text.lstrip("\t\n\f\r "))


class TidyDriverBase:
    """Base class for HTML cleanup utilities"""

    def __init__(self, config: Mapping[str, Any]):
        self.config = config

    def tidy(self, text: str, text_processor: Optional[Callable[[str], str]] = None) -> str:
        """Clean up HTML

        ``text``: HTML document fragment to clean up. ``text_processor``: a callback to run on the contents of text
        nodes (not elements or attribute values). This can be used to apply text modifications like french spacing
        or smart quotes, without affecting element or attribute markup. Returns the corrected HTML output
        """
        raise NotImplementedError


class RemexMungerData:
    """@internal"""

    __slots__ = ("child_p_element", "ancestor_p_node", "wrap_base_node", "current_clone_element", "is_p_wrapper",
                 "is_splittable", "needs_p_wrapping", "nonblank_node_count")

    def __init__(self) -> None:
        # The Element for the mw:p-wrap which is a child of the current node. If this is set, inline insertions
        # into this node will be diverted so that they insert into the p-wrap.
        self.child_p_element: Optional[Element] = None
        # This tracks the mw:p-wrap node in the Serializer stack which is an ancestor of this node. If there is no
        # mw:p-wrap ancestor, it is null.
        self.ancestor_p_node: Optional[SerializerNode] = None
        # The wrap base node is the body or blockquote node which is the parent of active p-wrappers. This is set
        # if there is an ancestor p-wrapper, or if a p-wrapper was closed due to a block element being encountered
        # inside it.
        self.wrap_base_node: Optional[SerializerNode] = None
        # Stack splitting (essentially our idea of AFE reconstruction) can clone formatting elements which are
        # split over multiple paragraphs. TreeBuilder is not aware of the cloning, and continues to insert into the
        # original element. This is set to the newer clone if this node was cloned, i.e. if there is an active
        # diversion of the insertion location.
        self.current_clone_element: Optional[Element] = None
        # Is the node a p-wrapper, with name mw:p-wrap?
        self.is_p_wrapper = False
        # Is the node splittable, i.e. a formatting element or a node with a formatting element ancestor which is
        # under an active or deactivated p-wrapper.
        self.is_splittable = False
        # This is true if the node is a body or blockquote, which activates p-wrapping of child nodes.
        self.needs_p_wrapping = False
        # The number of child nodes, not counting whitespace-only text nodes or comments.
        self.nonblank_node_count = 0

    def dump(self) -> str:
        """Get a text representation of the current state of the serializer, for debugging."""
        parts = []
        if self.child_p_element:
            parts.append("childPElement=" + self.child_p_element.get_debug_tag())
        if self.ancestor_p_node:
            parts.append(f"ancestorPNode=<{self.ancestor_p_node.name}>")
        if self.wrap_base_node:
            parts.append(f"wrapBaseNode=<{self.wrap_base_node.name}>")
        if self.current_clone_element:
            parts.append("currentCloneElement=" + self.current_clone_element.get_debug_tag())
        if self.is_p_wrapper:
            parts.append("isPWrapper")
        if self.is_splittable:
            parts.append("isSplittable")
        if self.needs_p_wrapping:
            parts.append("needsPWrapping")
        if self.nonblank_node_count:
            parts.append(f"nonblankNodeCount={self.nonblank_node_count}")
        s = "RemexMungerData {\n"
        for part in parts:
            s += f"  {part}\n"
        s += "}\n"
        return s


_ONLY_INLINE_ELEMENTS = frozenset([
    "a", "abbr", "acronym", "applet", "b", "basefont", "bdo", "big", "br", "button", "cite", "code", "del", "dfn",
    "em", "font", "i", "iframe", "img", "input", "ins", "kbd", "label", "legend", "map", "object", "param", "q",
    "rb", "rbc", "rp", "rt", "rtc", "ruby", "s", "samp", "select", "small", "span", "strike", "strong", "sub",
    "sup", "textarea", "tt", "u", "var",
    # Those defined in tidy.conf
    "video", "audio", "bdi", "data", "time", "mark",
])

# For the purposes of this class, "metadata" elements are those that should neither trigger p-wrapping nor stop an
# outer p-wrapping, typically those that are themselves invisible in a browser's rendering. This isn't a complete
# list, it's just the tags that we're likely to encounter in practice.
_METADATA_ELEMENTS = frozenset(["style", "script", "link", "meta"])

_FORMATTING_ELEMENTS = frozenset(["a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike",
                                  "strong", "tt", "u"])


class RemexCompatMunger(TreeHandler):
    """@internal"""

    def __init__(self, serializer: Serializer, trace: bool = False):
        self.serializer = serializer
        self._trace_enabled = trace

    def start_document(self, fragment_namespace, fragment_name):
        self.serializer.start_document(fragment_namespace, fragment_name)
        root = self.serializer.get_root_node()
        root.sn_data = RemexMungerData()
        root.sn_data.needs_p_wrapping = True

    def end_document(self, pos):
        self.serializer.end_document(pos)

    def _get_parent_for_insert(self, preposition: int, ref_element: Any):
        if preposition == TreeBuilder.ROOT:
            return self.serializer.get_root_node(), None
        elif preposition == TreeBuilder.BEFORE:
            ref_node = ref_element.user_data
            return self.serializer.get_parent_node(ref_node), ref_node
        else:
            ref_node = ref_element.user_data
            ref_data = ref_node.sn_data
            if ref_data.current_clone_element:
                # Follow a chain of clone links if necessary
                orig_ref_data = ref_data
                while ref_data.current_clone_element:
                    ref_element = ref_data.current_clone_element
                    ref_node = ref_element.user_data
                    ref_data = ref_node.sn_data
                # Cache the end of the chain in the requested element
                orig_ref_data.current_clone_element = ref_element
            elif ref_data.child_p_element:
                ref_element = ref_data.child_p_element
                ref_node = ref_element.user_data
            return ref_node, ref_node

    def _insert_p_wrapper(self, parent: SerializerNode, source_start: int) -> SerializerNode:
        """Insert a p-wrapper"""
        p_wrap = Element(HTMLData.NS_HTML, "mw:p-wrap", PlainAttributes())
        self.serializer.insert_element(TreeBuilder.UNDER, parent, p_wrap, False, source_start, 0)
        data = RemexMungerData()
        data.is_p_wrapper = True
        data.wrap_base_node = parent
        p_wrap.user_data.sn_data = data
        parent.sn_data.child_p_element = p_wrap
        return p_wrap.user_data

    def characters(self, preposition, ref_element, text, start, length, source_start, source_length):
        is_blank = _strspn_blank(text[start:start + length]) == length

        parent, ref_node = self._get_parent_for_insert(preposition, ref_element)
        parent_data = parent.sn_data

        if preposition == TreeBuilder.UNDER:
            if parent_data.needs_p_wrapping and not is_blank:
                # Add a p-wrapper for bare text under body/blockquote
                ref_node = self._insert_p_wrapper(ref_node, source_start)
                parent = ref_node
                parent_data = parent.sn_data
            elif parent_data.is_splittable and not parent_data.ancestor_p_node:
                # The parent is splittable and in block mode, so split the tag stack
                ref_node = self._split_tag_stack(ref_node, True, source_start)
                parent = ref_node
                parent_data = parent.sn_data

        if not is_blank:
            # Non-whitespace characters detected
            parent_data.nonblank_node_count += 1
        self.serializer.characters(preposition, ref_node, text, start, length, source_start, source_length)

    def _trace(self, msg: str) -> None:
        if self._trace_enabled:
            _wf_debug(f"[RCM] {msg}")

    def insert_element(self, preposition, ref_element, element, void, source_start, source_length):
        """Insert or reparent an element. Create p-wrappers or split the tag stack as necessary.

        Consider the following insertion locations. The parent may be:

          - A: A body or blockquote (!!needsPWrapping)
          - B: A p-wrapper (!!isPWrapper)
          - C: A descendant of a p-wrapper (!!ancestorPNode)
            - CS: With splittable formatting elements in the stack region up to
              the p-wrapper
            - CU: With one or more unsplittable elements in the stack region up
              to the p-wrapper
          - D: Not a descendant of a p-wrapper (!ancestorNode)
            - DS: With splittable formatting elements in the stack region up to
              the body or blockquote
            - DU: With one or more unsplittable elements in the stack region up
              to the body or blockquote

        And consider that we may insert two types of element:
          - b: block
          - i: inline

        We handle the insertion as follows:

          - A/i: Create a p-wrapper, insert under it
          - A/b: Insert as normal
          - B/i: Insert as normal
          - B/b: Close the p-wrapper, insert under the body/blockquote (wrap
            base) instead)
          - C/i: Insert as normal
          - CS/b: Split the tag stack, insert the block under cloned formatting
            elements which have the wrap base (the parent of the p-wrap) as
            their ultimate parent.
          - CU/b: Disable the p-wrap, by reparenting the currently open child
            of the p-wrap under the p-wrap's parent. Then insert the block as
            normal.
          - D/b: Insert as normal
          - DS/i: Split the tag stack, creating a new p-wrapper as the ultimate
            parent of the formatting elements thus cloned. The parent of the
            p-wrapper is the body or blockquote.
          - DU/i: Insert as normal

        FIXME: fostering ($preposition == BEFORE) is mostly done by inserting as normal, the full algorithm is not
        followed.
        """
        parent, new_ref = self._get_parent_for_insert(preposition, ref_element)
        parent_data = parent.sn_data
        element_name = element.html_name

        inline = element_name in _ONLY_INLINE_ELEMENTS
        under = preposition == TreeBuilder.UNDER

        if element_name in _METADATA_ELEMENTS:
            # The element is a metadata element, that we allow to appear in
            # both inline and block contexts.
            self._trace("insert metadata")
        elif under and parent_data.is_p_wrapper and not inline:
            # [B/b] The element is non-inline and the parent is a p-wrapper,
            # close the parent and insert into its parent instead
            self._trace("insert B/b")
            new_parent = self.serializer.get_parent_node(parent)
            parent = new_parent
            parent_data = parent.sn_data
            parent_data.child_p_element = None
            new_ref = ref_element.user_data
        elif under and parent_data.is_splittable and bool(parent_data.ancestor_p_node) != inline:
            # [CS/b, DS/i] The parent is splittable and the current element is
            # inline in block context, or if the current element is a block
            # under a p-wrapper, split the tag stack.
            self._trace("insert DS/i" if inline else "insert CS/b")
            new_ref = self._split_tag_stack(new_ref, inline, source_start)
            parent = new_ref
            parent_data = parent.sn_data
        elif under and parent_data.needs_p_wrapping and inline:
            # [A/i] If the element is inline and we are in body/blockquote,
            # we need to create a p-wrapper
            self._trace("insert A/i")
            new_ref = self._insert_p_wrapper(new_ref, source_start)
            parent = new_ref
            parent_data = parent.sn_data
        elif parent_data.ancestor_p_node and not inline:
            # [CU/b] If the element is non-inline and (despite attempting to
            # split above) there is still an ancestor p-wrap, disable that
            # p-wrap
            self._trace("insert CU/b")
            self._disable_p_wrapper(parent, source_start)
        else:
            # [A/b, B/i, C/i, D/b, DU/i] insert as normal
            self._trace("insert normal")

        # An element with element children is a non-blank element
        parent_data.nonblank_node_count += 1

        # Insert the element downstream and so initialise its userData
        self.serializer.insert_element(preposition, new_ref, element, void, source_start, source_length)

        # Initialise snData
        if not element.user_data.sn_data:
            element_data = element.user_data.sn_data = RemexMungerData()
        else:
            element_data = element.user_data.sn_data
        if (parent_data.is_p_wrapper or parent_data.is_splittable) and element_name in _FORMATTING_ELEMENTS:
            element_data.is_splittable = True
        if parent_data.is_p_wrapper:
            element_data.ancestor_p_node = parent
        elif parent_data.ancestor_p_node:
            element_data.ancestor_p_node = parent_data.ancestor_p_node
        if parent_data.wrap_base_node:
            element_data.wrap_base_node = parent_data.wrap_base_node
        elif parent_data.needs_p_wrapping:
            element_data.wrap_base_node = parent
        if element_name in ("body", "blockquote", "html"):
            element_data.needs_p_wrapping = True

    def _split_tag_stack(self, parent_node: SerializerNode, inline: bool, pos: int) -> SerializerNode:
        """Clone nodes in a stack range and return the new parent"""
        parent_data = parent_node.sn_data
        wrap_base = parent_data.wrap_base_node
        p_wrap = parent_data.ancestor_p_node
        if not p_wrap:
            clone_end = wrap_base
        else:
            clone_end = parent_data.ancestor_p_node

        serializer = self.serializer
        node = parent_node
        root = serializer.get_root_node()
        nodes = []
        removable_nodes = []
        while node is not clone_end:
            next_parent = serializer.get_parent_node(node)
            if next_parent is root:
                raise Exception("Did not find end of clone range")
            nodes.append(node)
            if node.sn_data.nonblank_node_count == 0:
                removable_nodes.append(node)
                next_parent.sn_data.nonblank_node_count -= 1
            node = next_parent

        if inline:
            p_wrap = self._insert_p_wrapper(wrap_base, pos)
            node = p_wrap
        else:
            if p_wrap:
                # End the p-wrap which was open, cancel the diversion
                wrap_base.sn_data.child_p_element = None
            p_wrap = None
            node = wrap_base

        for old_node in reversed(nodes):
            old_data = old_node.sn_data
            node_parent = node
            element = Element(old_node.namespace, old_node.name, old_node.attrs)
            self.serializer.insert_element(TreeBuilder.UNDER, node_parent, element, False, pos, 0)
            old_data.current_clone_element = element

            new_node = element.user_data
            new_data = new_node.sn_data = RemexMungerData()
            if p_wrap:
                new_data.ancestor_p_node = p_wrap
            new_data.is_splittable = True
            new_data.wrap_base_node = wrap_base
            new_data.is_p_wrapper = old_data.is_p_wrapper

            node_parent.sn_data.nonblank_node_count += 1

            node = new_node
        for r_node in removable_nodes:
            fake_element = Element(r_node.namespace, r_node.name, r_node.attrs)
            fake_element.user_data = r_node
            self.serializer.remove_node(fake_element, pos)
        return node

    def _disable_p_wrapper(self, node: SerializerNode, source_start: int) -> None:
        """Find the ancestor of $node which is a child of a p-wrapper, and reparent that node so that it is placed
        after the end of the p-wrapper"""
        node_data = node.sn_data
        p_wrap_node = node_data.ancestor_p_node
        new_parent = self.serializer.get_parent_node(p_wrap_node)
        if p_wrap_node is not self.serializer.get_last_child(new_parent):
            # Fostering or something? Abort!
            return

        next_parent = node
        while True:
            victim = next_parent
            victim.sn_data.ancestor_p_node = None
            next_parent = self.serializer.get_parent_node(victim)
            if next_parent is p_wrap_node:
                break

        # Make a fake Element to use in a reparenting operation
        victim_element = Element(victim.namespace, victim.name, victim.attrs)
        victim_element.user_data = victim

        # Reparent
        self.serializer.insert_element(TreeBuilder.UNDER, new_parent, victim_element, False, source_start, 0)

        # Decrement nonblank node count
        p_wrap_node.sn_data.nonblank_node_count -= 1

        # Cancel the diversion so that no more elements are inserted under this p-wrap
        new_parent.sn_data.child_p_element = None

    def end_tag(self, element, source_start, source_length):
        data = element.user_data.sn_data
        if data.child_p_element:
            self.end_tag(data.child_p_element, source_start, 0)
        self.serializer.end_tag(element, source_start, source_length)
        element.user_data.sn_data = None
        element.user_data = None

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.serializer.doctype(name, public, system, quirks, source_start, source_length)

    def comment(self, preposition, ref_element, text, source_start, source_length):
        _, ref_node = self._get_parent_for_insert(preposition, ref_element)
        self.serializer.comment(preposition, ref_node, text, source_start, source_length)

    def error(self, text, pos):
        self.serializer.error(text, pos)

    def merge_attributes(self, element, attrs, source_start):
        self.serializer.merge_attributes(element, attrs, source_start)

    def remove_node(self, element, source_start):
        self.serializer.remove_node(element, source_start)

    def reparent_children(self, element, new_parent, source_start):
        self_ = element.user_data
        if self_.sn_data.child_p_element:
            # Reparent under the p-wrapper instead, so that e.g.
            #   <blockquote><mw:p-wrap>...</mw:p-wrap></blockquote>
            # becomes
            #   <blockquote><mw:p-wrap><i>...</i></mw:p-wrap></blockquote>

            # The formatting element should not be the parent of the p-wrap.
            # Without this special case, the insertElement() of the <i> below
            # would be diverted into the p-wrapper, causing infinite recursion
            # (T178632)
            self.reparent_children(self_.sn_data.child_p_element, new_parent, source_start)
            return

        children = self_.children
        self_.children = []
        self.insert_element(TreeBuilder.UNDER, element, new_parent, False, source_start, 0)
        new_parent_node = new_parent.user_data
        new_parent_id = new_parent_node.id
        for child in children:
            if not isinstance(child, str):
                self._trace(f"reparent <{child.name}>")
                child.parent_id = new_parent_id
        new_parent_node.children = children


_MARKED_EMPTY_ELEMENTS = frozenset(["li", "p", "tr"])


class RemexCompatFormatter(HtmlFormatter):
    """@internal"""

    def __init__(self, options: Optional[Mapping[str, Any]] = None):
        options = options or {}
        super().__init__(options)
        self.attribute_escapes[" "] = "&#160;"
        del self.attribute_escapes["&"]
        self.text_escapes[" "] = "&#160;"
        del self.text_escapes["&"]
        self.text_processor: Optional[Callable[[str], str]] = options.get("textProcessor")

    def start_document(self, fragment_namespace, fragment_name):
        return ""

    def characters(self, parent, text, start, length):
        text = super().characters(parent, text, start, length)

        if parent.namespace != HTMLData.NS_HTML or parent.name not in self.raw_text_elements:
            if self.text_processor is not None:
                text = self.text_processor(text)

        # Ensure a consistent representation for all entities
        text = normalize_char_references(text)
        return text

    def element(self, parent, node, contents):
        data = node.sn_data
        if data and data.is_p_wrapper:
            if data.nonblank_node_count:
                return f"<p>{contents}</p>"
            else:
                return contents

        name = node.name
        attrs = node.attrs
        if (name in _MARKED_EMPTY_ELEMENTS and attrs.count() == 0
                and _strspn_blank(contents or "") == len(contents or "")):
            return f'<{name} class="mw-empty-elt">{contents or ""}</{name}>'

        s = f"<{name}"
        for attr_name, attr_value in attrs.get_values().items():
            enc_value = strtr(attr_value, self.attribute_escapes)
            enc_value = normalize_char_references(enc_value)
            s += f' {attr_name}="{enc_value}"'
        if node.namespace == HTMLData.NS_HTML and name in self.void_elements:
            s += " />"
            return s

        s += ">"
        if (node.namespace == HTMLData.NS_HTML and contents and contents[0] == "\n"
                and name in self.prefix_lf_elements):
            s += f"\n{contents}</{name}>"
        else:
            s += f"{contents or ''}</{name}>"
        return s


class RemexCompatBuilder(TreeBuilder):
    """@internal"""

    _MW_FILE = re.compile(r"\bmw:File\b")

    def reconstruct_afe(self, source_start):
        # These checks are redundant with the parent, but here for performance
        entry = self.afe.get_tail()
        if not entry:
            return
        if isinstance(entry, Marker):
            return
        if entry.stack_index is not None:
            return

        # Don't reconstruct AFE in file figures to respect the spec,
        # https://www.mediawiki.org/wiki/Specs/HTML#Media
        length = self.stack.length()
        while length > 0:
            i = self.stack.item(length - 1)
            if i.html_name == "figcaption":
                break
            if i.html_name == "figure":
                for k, v in i.attrs.get_values().items():
                    if k == "typeof" and self._MW_FILE.search(v):
                        return
                break
            length -= 1
        super().reconstruct_afe(source_start)


class RemexDriver(TidyDriverBase):
    def __init__(self, config: Optional[Mapping[str, Any]] = None, enable_legacy_media_dom: bool = True):
        """``config``: $wgTidyConfig (default: an empty array); ``enable_legacy_media_dom``:
        $wgParserEnableLegacyMediaDOM (default true in MediaWiki 1.39)."""
        config = {
            "treeMutationTrace": False,
            "serializerTrace": False,
            "mungerTrace": False,
            "pwrap": True,
            **(config or {}),
        }
        self.tree_mutation_trace = config["treeMutationTrace"]
        self.serializer_trace = config["serializerTrace"]
        self.munger_trace = config["mungerTrace"]
        self.pwrap = config["pwrap"]
        self.enable_legacy_media_dom = enable_legacy_media_dom
        super().__init__(config)

    def tidy(self, text: str, text_processor: Optional[Callable[[str], str]] = None) -> str:
        def trace_callback(msg: str) -> None:
            _wf_debug(f"RemexHtml: {msg}")

        formatter = RemexCompatFormatter({"textProcessor": text_processor})
        if self.serializer_trace:
            serializer: Serializer = SerializerWithTracer(formatter, None, trace_callback)
        else:
            serializer = Serializer(formatter)
        if self.pwrap:
            munger: TreeHandler = RemexCompatMunger(serializer, self.munger_trace)
        else:
            munger = serializer
        if self.tree_mutation_trace:
            tracer: TreeHandler = TreeMutationTracer(munger, trace_callback)
        else:
            tracer = munger
        tree_builder_class = TreeBuilder if self.enable_legacy_media_dom else RemexCompatBuilder
        tree_builder = tree_builder_class(tracer, {
            "ignoreErrors": True,
            "ignoreNulls": True,
        })
        dispatcher = Dispatcher(tree_builder)
        tokenizer = Tokenizer(dispatcher, text, {
            "ignoreErrors": True,
            "ignoreCharRefs": True,
            "ignoreNulls": True,
            "skipPreprocess": True,
        })

        tokenizer.execute({
            "fragmentNamespace": HTMLData.NS_HTML,
            "fragmentName": "body",
        })
        return serializer.get_result()


_DEFAULT_DRIVER: Optional[RemexDriver] = None


def tidy(text: str, text_processor: Optional[Callable[[str], str]] = None) -> str:
    """MediaWikiServices::getTidy()->tidy( $text, $textProcessor ) with MediaWiki 1.39's default configuration
    ($wgTidyConfig = [], so RemexHtml with p-wrapping; $wgParserEnableLegacyMediaDOM = true, so the plain
    TreeBuilder). The parser passes ``sanitizer.armor_french_spaces`` as ``text_processor``, which then runs on the
    contents of text nodes outside raw text elements."""
    global _DEFAULT_DRIVER
    if _DEFAULT_DRIVER is None:
        _DEFAULT_DRIVER = RemexDriver()
    return _DEFAULT_DRIVER.tidy(text, text_processor)

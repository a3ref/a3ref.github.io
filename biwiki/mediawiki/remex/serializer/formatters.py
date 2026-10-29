# Ported from RemexHtml 3.0.2 src/Serializer/Formatter.php, HtmlFormatter.php, DepurateFormatter.php,
# FastFormatter.php, TestFormatter.php and DOM/DOMUtils.php (uncoerceName)
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the DOMFormatter methods (formatDOMNode,
# formatDOMElement) are left out with the DOM builder.
"""Formatters: how the Serializer turns nodes into strings."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping, Optional

from ..htmldata import HTMLData

if TYPE_CHECKING:
    from .serializer import SerializerNode

_STRTR_CACHE: dict[tuple, Any] = {}


def strtr(text: str, pairs: Mapping[str, str]) -> str:
    """PHP strtr( $text, $pairs ): replace the keys by their values, longest key first, without rescanning."""
    key = tuple(pairs.items())
    table = _STRTR_CACHE.get(key)
    if table is None:
        if all(len(k) == 1 for k in pairs):
            table = str.maketrans(dict(pairs))
        else:
            table = re.compile("|".join(re.escape(k) for k in sorted(pairs, key=len, reverse=True) if k))
        _STRTR_CACHE[key] = table
    if isinstance(table, dict):
        return text.translate(table)
    return table.sub(lambda m: pairs[m.group(0)], text)


class Formatter:
    """The interface for classes that help Serializer to convert nodes to strings. Serializer assumes that the
    return values of these functions can be concatenated to make a document.

    It is not safe to assume that the methods will be called in any particular order, or that the return values
    will actually be retained in the final Serializer result.
    """

    def start_document(self, fragment_namespace: Optional[str], fragment_name: Optional[str]) -> str:
        """Get a string which starts the document"""
        raise NotImplementedError

    def characters(self, parent: SerializerNode, text: str, start: int, length: int) -> str:
        """Encode the given character substring. ``parent``: the parent of the text node (at creation time)"""
        raise NotImplementedError

    def element(self, parent: SerializerNode, node: SerializerNode, contents: Optional[str]) -> str:
        """Encode the given element. ``parent``: the parent of the node (when it is closed); ``contents``: the
        previously-encoded contents, or null for a void element. Void elements can be serialized as self-closing
        tags."""
        raise NotImplementedError

    def comment(self, parent: SerializerNode, text: str) -> str:
        """Encode a comment. ``text``: the inner text of the comment"""
        raise NotImplementedError

    def doctype(self, name: str, public: str, system: str) -> str:
        """Encode a doctype. This event occurs when the source document has a doctype, it can return an empty
        string if the formatter wants to use its own doctype."""
        raise NotImplementedError


class HtmlFormatter(Formatter):
    """A formatter which follows the HTML 5 fragment serialization algorithm."""

    def __init__(self, options: Optional[Mapping[str, Any]] = None):
        """``options``: an associative array of options:
        - scriptingFlag : Set this to false to disable scripting. True by default.
        - useSourceDoctype : Emit the doctype used in the source. If this is false or absent, an HTML doctype will be
          used.
        - reverseCoercion : When formatting a DOM node, reverse the encoding of invalid names. False by default.
        """
        options = {"scriptingFlag": True, "useSourceDoctype": False, "reverseCoercion": False, **(options or {})}
        # The elements for which a closing tag is omitted.
        self.void_elements = {
            "area": True, "base": True, "basefont": True, "bgsound": True, "br": True, "col": True, "embed": True,
            "frame": True, "hr": True, "img": True, "input": True, "keygen": True, "link": True, "menuitem": True,
            "meta": True, "param": True, "source": True, "track": True, "wbr": True,
        }
        # The elements which need a leading newline in their contents to be duplicated, since the parser strips a
        # leading newline.
        self.prefix_lf_elements = {"pre": True, "textarea": True, "listing": True}
        # The elements which have unescaped contents.
        self.raw_text_elements = {
            "style": True, "script": True, "xmp": True, "iframe": True, "noembed": True, "noframes": True,
            "plaintext": True,
        }
        # The escape table for attribute values
        self.attribute_escapes = {"&": "&amp;", " ": "&nbsp;", '"': "&quot;"}
        # The escape table for text nodes
        self.text_escapes = {"&": "&amp;", " ": "&nbsp;", "<": "&lt;", ">": "&gt;"}
        # Attribute namespaces which have unqualified local names
        self.unqualified_namespaces = {HTMLData.NS_HTML: True, HTMLData.NS_MATHML: True, HTMLData.NS_SVG: True}
        if options["scriptingFlag"]:
            self.raw_text_elements["noscript"] = True
        self.use_source_doctype = options["useSourceDoctype"]
        self.reverse_coercion = options["reverseCoercion"]

    def start_document(self, fragment_namespace, fragment_name):
        return "<!DOCTYPE html>"

    def characters(self, parent, text, start, length):
        text = text[start:start + length]
        if parent.namespace != HTMLData.NS_HTML or parent.name not in self.raw_text_elements:
            text = strtr(text, self.text_escapes)
        return text

    def element(self, parent, node, contents):
        name = node.name
        s = f"<{name}"
        for attr_name, attr_value in node.attrs.get_values().items():
            enc_value = strtr(attr_value, self.attribute_escapes)
            s += f' {attr_name}="{enc_value}"'
        s += ">"
        if node.namespace == HTMLData.NS_HTML:
            if contents and contents[0] == "\n" and name in self.prefix_lf_elements:
                s += f"\n{contents}</{name}>"
            elif name not in self.void_elements:
                s += f"{contents or ''}</{name}>"
        else:
            s += f"{contents or ''}</{name}>"
        return s

    def comment(self, parent, text):
        return f"<!--{text}-->"

    def doctype(self, name, public, system):
        return ""


class DepurateFormatter(HtmlFormatter):
    """A formatter which produces a serialization extremely similar to the Html5Depurate service, which uses the
    validator.nu library for tree construction.

    For use in comparative testing.

    https://www.mediawiki.org/wiki/Html5Depurate
    """

    def __init__(self, options: Optional[Mapping[str, Any]] = None):
        super().__init__(options)
        self.text_escapes[" "] = "&#160;"

    def element(self, parent, node, contents):
        name = node.name
        s = f"<{name}"
        for attr_name, attr_value in node.attrs.get_values().items():
            enc_value = strtr(attr_value, self.attribute_escapes)
            s += f' {attr_name}="{enc_value}"'
        if node.namespace == HTMLData.NS_HTML:
            if name in self.prefix_lf_elements:
                s += f">\n{contents or ''}</{name}>"
            elif name not in self.void_elements:
                s += f">{contents or ''}</{name}>"
            else:
                s += " />"
        else:
            s += f">{contents or ''}</{name}>"
        return s


class FastFormatter(Formatter):
    """A formatter suitable for pre-sanitized input with ignoreEntities enabled in the Tokenizer."""

    def __init__(self, options: Optional[Mapping[str, Any]] = None):
        pass

    def start_document(self, fragment_namespace, fragment_name):
        if fragment_namespace is None:
            return "<!DOCTYPE html>\n"
        else:
            return ""

    def doctype(self, name, public, system):
        return ""

    def characters(self, parent, text, start, length):
        return text[start:start + length]

    def element(self, parent, node, contents):
        name = node.name
        ret = f"<{name}"
        for attr_name, value in node.attrs.get_values().items():
            ret += f' {attr_name}="{value}"'
        if contents is None:
            ret += "/>"
        elif contents and contents[0] == "\n" and name in ("pre", "textarea", "listing"):
            ret += f">\n{contents}</{name}>"
        else:
            ret += f">{contents}</{name}>"
        return ret

    def comment(self, parent, text):
        return f"<!--{text}-->"


_UNCOERCE_RE = re.compile(r"U([0-9A-F]{6})")
# PCRE's /^/m: the start of the string and after every newline except a final one (Python's also matches there)
_LINE_START = re.compile(r"\A|(?<=\n)(?!\Z)")
_NUMERIC_ENTITY_RE = re.compile(r"&#(?:([0-9]+)|[xX]([0-9a-fA-F]+));")


def uncoerce_name(name: str) -> str:
    """DOMUtils::uncoerceName(): invert the encoding produced by coerceName() (characters that are not allowed in
    XML names written as U followed by six hex digits). PHP's mb_decode_numericentity() also decodes the numeric
    character references which were in the name before."""
    name = _UNCOERCE_RE.sub(lambda m: f"&#x{m.group(1)};", name)

    def decode(m: re.Match[str]) -> str:
        codepoint = int(m.group(1)) if m.group(1) is not None else int(m.group(2), 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return m.group(0)
        return chr(codepoint)

    return _NUMERIC_ENTITY_RE.sub(decode, name)


class TestFormatter(Formatter):
    """A Formatter which is used to format documents in (almost) the way they appear in the html5lib tests. A little
    bit of post-processing is required in the tests."""

    __test__ = False  # not a unittest/pytest test class

    _attr_namespaces = {
        HTMLData.NS_XML: "xml",
        HTMLData.NS_XLINK: "xlink",
        HTMLData.NS_XMLNS: "xmlns",
    }

    def start_document(self, fragment_namespace, fragment_name):
        return ""

    def doctype(self, name, public, system):
        ret = f"<!DOCTYPE {name}"
        if public != "" or system != "":
            ret += f' "{public}" "{system}"'
        ret += ">\n"
        return ret

    def characters(self, parent, text, start, length):
        return self._format_characters(text[start:start + length])

    @staticmethod
    def _format_characters(text: str) -> str:
        return '"' + text.replace("\n", "<EOL>") + '"\n'

    def element(self, parent, node, contents):
        return self._format_element(node.namespace, node.name, node.attrs.get_objects(), contents)

    def _format_element(self, namespace: str, name: str, attrs: Mapping[str, Any], contents: Optional[str]) -> str:
        name = uncoerce_name(name)
        if namespace == HTMLData.NS_HTML:
            tag_name = name
        elif namespace == HTMLData.NS_SVG:
            tag_name = f"svg {name}"
        elif namespace == HTMLData.NS_MATHML:
            tag_name = f"math {name}"
        else:
            tag_name = name
        ret = f"<{tag_name}>\n"
        # ksort( $sortedAttrs, SORT_STRING ) compares bytes: sort by the UTF-8 encoding
        for attr_name in sorted(attrs, key=lambda k: str(k).encode("utf-8")):
            attr = attrs[attr_name]
            local_name = uncoerce_name(attr.local_name)
            if attr.namespace_uri is None:
                prefix = ""
            elif attr.namespace_uri in self._attr_namespaces:
                prefix = self._attr_namespaces[attr.namespace_uri] + " "
            else:
                prefix = ""
            ret += f'  {prefix}{local_name}="{attr.value}"\n'
        if contents is not None and contents != "":
            contents = _LINE_START.sub("  ", contents)
        else:
            contents = ""
        if namespace == HTMLData.NS_HTML and name == "template":
            if contents == "":
                contents = "  content\n"
            else:
                contents = "  content\n" + _LINE_START.sub("  ", contents)
        ret += contents
        return ret

    def comment(self, parent, text):
        return self._format_comment(text)

    @staticmethod
    def _format_comment(text: str) -> str:
        return f"<!-- {text} -->\n"

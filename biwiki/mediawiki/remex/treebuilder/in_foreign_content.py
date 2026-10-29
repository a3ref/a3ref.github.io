# Ported from RemexHtml 3.0.2 src/TreeBuilder/InForeignContent.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The rules for parsing tokens in foreign content."""
from __future__ import annotations

from .._php import strcasecmp, strcspn, strspn
from ..htmldata import HTMLData
from .element import Element
from .foreign_attributes import ForeignAttributes
from .insertion_mode import InsertionMode
from .stack import TreeBuilderError

# The list of tag names which unconditionally generate a parse error when seen in foreign content.
_NOT_ALLOWED = frozenset([
    "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em", "embed", "h1", "h2",
    "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing", "menu", "meta", "nobr", "ol", "p", "pre",
    "ruby", "s", "small", "span", "strong", "strike", "sub", "sup", "table", "tt", "u", "ul", "var",
])

# The table for correcting the tag names of SVG elements, given in the "Any other start tag" section of the spec.
_SVG_ELEMENT_CASE = {
    "altglyph": "altGlyph",
    "altglyphdef": "altGlyphDef",
    "altglyphitem": "altGlyphItem",
    "animatecolor": "animateColor",
    "animatemotion": "animateMotion",
    "animatetransform": "animateTransform",
    "clippath": "clipPath",
    "feblend": "feBlend",
    "fecolormatrix": "feColorMatrix",
    "fecomponenttransfer": "feComponentTransfer",
    "fecomposite": "feComposite",
    "feconvolvematrix": "feConvolveMatrix",
    "fediffuselighting": "feDiffuseLighting",
    "fedisplacementmap": "feDisplacementMap",
    "fedistantlight": "feDistantLight",
    "fedropshadow": "feDropShadow",
    "feflood": "feFlood",
    "fefunca": "feFuncA",
    "fefuncb": "feFuncB",
    "fefuncg": "feFuncG",
    "fefuncr": "feFuncR",
    "fegaussianblur": "feGaussianBlur",
    "feimage": "feImage",
    "femerge": "feMerge",
    "femergenode": "feMergeNode",
    "femorphology": "feMorphology",
    "feoffset": "feOffset",
    "fepointlight": "fePointLight",
    "fespecularlighting": "feSpecularLighting",
    "fespotlight": "feSpotLight",
    "fetile": "feTile",
    "feturbulence": "feTurbulence",
    "foreignobject": "foreignObject",
    "glyphref": "glyphRef",
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "textpath": "textPath",
}

_WHITESPACE = "\t\n\f\r "


class InForeignContent(InsertionMode):
    """The rules for parsing tokens in foreign content.

    This is not referred to as an insertion mode in the spec, but is sufficiently similar to one that we can
    inherit from InsertionMode here.
    """

    def characters(self, text, start, length, source_start, source_length):
        builder = self.builder
        while length:
            normal_length = strcspn(text, "\0" + _WHITESPACE, start, length)
            if normal_length:
                builder.frameset_ok = False
                builder.insert_characters(text, start, normal_length, source_start, source_length)
            start += normal_length
            length -= normal_length
            source_start += normal_length
            source_length -= normal_length
            if not length:
                break
            char = text[start]
            if char == "\0":
                builder.error("replaced null character", source_start)
                builder.insert_characters("�", 0, 1, source_start, source_length)
                start += 1
                length -= 1
                source_start += 1
                source_length -= 1
            else:
                # Whitespace
                ws_length = strspn(text, _WHITESPACE, start, length)
                builder.insert_characters(text, start, ws_length, source_start, ws_length)
                start += ws_length
                length -= ws_length
                source_start += ws_length
                source_length -= ws_length

    @staticmethod
    def _is_integration_point(element: Element) -> bool:
        return (element.namespace == HTMLData.NS_HTML or element.is_mathml_text_integration()
                or element.is_html_integration())

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name in _NOT_ALLOWED:
            allowed = False
        elif name == "font" and ("color" in attrs or "face" in attrs or "size" in attrs):
            allowed = False
        else:
            allowed = True

        if not allowed:
            builder.error(f"unexpected <{name}> tag in foreign content", source_start)
            if not builder.is_fragment:
                while True:
                    builder.pop(source_start, 0)
                    if not (stack.current and not self._is_integration_point(stack.current)):
                        break
                dispatcher.start_tag(name, attrs, self_close, source_start, source_length)
                return

        acn_ns = builder.adjusted_current_node().namespace
        if acn_ns == HTMLData.NS_MATHML:
            attrs = ForeignAttributes(attrs, "math")
        elif acn_ns == HTMLData.NS_SVG:
            attrs = ForeignAttributes(attrs, "svg")
            name = _SVG_ELEMENT_CASE.get(name, name)
        else:
            attrs = ForeignAttributes(attrs, "other")
        dispatcher.ack = True
        builder.insert_foreign(acn_ns, name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        node = stack.current
        if strcasecmp(node.name, name) != 0:
            builder.error("mismatched end tag in foreign content", source_start)
        for idx in range(stack.length() - 1, 0, -1):
            if strcasecmp(node.name, name) == 0:
                builder.pop_all_up_to_element(node, source_start, source_length)
                break
            node = stack.item(idx - 1)
            if node.namespace == HTMLData.NS_HTML:
                dispatcher.get_handler().end_tag(name, source_start, source_length)
                break

    def end_document(self, pos):
        raise TreeBuilderError("unspecified, presumed unreachable")

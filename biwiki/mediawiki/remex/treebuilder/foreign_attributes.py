# Ported from RemexHtml 3.0.2 src/TreeBuilder/ForeignAttributes.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""Attributes of foreign (MathML, SVG) elements."""
from __future__ import annotations

from typing import Optional

from ..htmldata import HTMLData
from ..tokenizer.attributes import Attribute, Attributes
from .stack import TreeBuilderError

# Adjustment tables for the case of attributes on MathML and SVG elements
_ADJUSTMENT_TABLES: dict[str, dict[str, str]] = {
    "math": {
        "definitionurl": "definitionURL",
    },
    "svg": {
        "attributename": "attributeName",
        "attributetype": "attributeType",
        "basefrequency": "baseFrequency",
        "baseprofile": "baseProfile",
        "calcmode": "calcMode",
        "clippathunits": "clipPathUnits",
        "diffuseconstant": "diffuseConstant",
        "edgemode": "edgeMode",
        "filterunits": "filterUnits",
        "glyphref": "glyphRef",
        "gradienttransform": "gradientTransform",
        "gradientunits": "gradientUnits",
        "kernelmatrix": "kernelMatrix",
        "kernelunitlength": "kernelUnitLength",
        "keypoints": "keyPoints",
        "keysplines": "keySplines",
        "keytimes": "keyTimes",
        "lengthadjust": "lengthAdjust",
        "limitingconeangle": "limitingConeAngle",
        "markerheight": "markerHeight",
        "markerunits": "markerUnits",
        "markerwidth": "markerWidth",
        "maskcontentunits": "maskContentUnits",
        "maskunits": "maskUnits",
        "numoctaves": "numOctaves",
        "pathlength": "pathLength",
        "patterncontentunits": "patternContentUnits",
        "patterntransform": "patternTransform",
        "patternunits": "patternUnits",
        "pointsatx": "pointsAtX",
        "pointsaty": "pointsAtY",
        "pointsatz": "pointsAtZ",
        "preservealpha": "preserveAlpha",
        "preserveaspectratio": "preserveAspectRatio",
        "primitiveunits": "primitiveUnits",
        "refx": "refX",
        "refy": "refY",
        "repeatcount": "repeatCount",
        "repeatdur": "repeatDur",
        "requiredextensions": "requiredExtensions",
        "requiredfeatures": "requiredFeatures",
        "specularconstant": "specularConstant",
        "specularexponent": "specularExponent",
        "spreadmethod": "spreadMethod",
        "startoffset": "startOffset",
        "stddeviation": "stdDeviation",
        "stitchtiles": "stitchTiles",
        "surfacescale": "surfaceScale",
        "systemlanguage": "systemLanguage",
        "tablevalues": "tableValues",
        "targetx": "targetX",
        "targety": "targetY",
        "textlength": "textLength",
        "viewbox": "viewBox",
        "viewtarget": "viewTarget",
        "xchannelselector": "xChannelSelector",
        "ychannelselector": "yChannelSelector",
        "zoomandpan": "zoomAndPan",
    },
    "other": {},
}

# The potentially namespaced attributes, and the namespaces they belong to. Excepting xmlns since it is very
# special.
_NAMESPACE_MAP = {
    "xlink:actuate": HTMLData.NS_XLINK,
    "xlink:arcrole": HTMLData.NS_XLINK,
    "xlink:href": HTMLData.NS_XLINK,
    "xlink:role": HTMLData.NS_XLINK,
    "xlink:show": HTMLData.NS_XLINK,
    "xlink:title": HTMLData.NS_XLINK,
    "xlink:type": HTMLData.NS_XLINK,
    "xml:lang": HTMLData.NS_XML,
    "xml:space": HTMLData.NS_XML,
    "xmlns:xlink": HTMLData.NS_XMLNS,
}


class ForeignAttributes(Attributes):
    """An Attributes class for storing attributes on foreign elements, which may have namespaces. Features lazy
    adjustment of attribute name case."""

    def __init__(self, unadjusted: Attributes, type_: str):
        """``unadjusted``: the unadjusted attributes from the Tokenizer; ``type_``: the element type, which may be
        "math", "svg" or "other"."""
        self.unadjusted = unadjusted
        # The map of lowercase attribute name to correct attribute name
        self.table = _ADJUSTMENT_TABLES[type_]
        self.attr_objects: Optional[dict[str, Attribute]] = None

    # (sic: these look the adjusted name up in the unadjusted, lower-case attributes)
    def __contains__(self, offset: object) -> bool:
        offset = self.table.get(offset, offset)
        return offset in self.unadjusted

    def __getitem__(self, offset: str) -> str:
        offset = self.table.get(offset, offset)
        return self.unadjusted[offset]

    def __setitem__(self, offset: str, value: str) -> None:
        raise TreeBuilderError("Setting foreign attributes is not supported")

    def __delitem__(self, offset: str) -> None:
        raise TreeBuilderError("Setting foreign attributes is not supported")

    def get_values(self) -> dict[str, str]:
        result = {}
        for name, value in self.unadjusted.get_values().items():
            name = self.table.get(name, name)
            result[name] = value
        return result

    def count(self) -> int:
        return self.unadjusted.count()

    def get_objects(self) -> dict[str, Attribute]:
        if self.attr_objects is None:
            result = {}
            for name, value in self.unadjusted.get_values().items():
                if name in self.table:
                    name = self.table[name]
                if name == "xmlns":
                    prefix = None
                    namespace = HTMLData.NS_XMLNS
                    local_name = name
                elif name in _NAMESPACE_MAP:
                    namespace = _NAMESPACE_MAP[name]
                    prefix, local_name = name.split(":", 1)
                else:
                    prefix = None
                    namespace = None
                    local_name = name
                result[name] = Attribute(name, namespace, prefix, local_name, value)
            self.attr_objects = result
        return self.attr_objects

    def merge(self, other: Attributes) -> None:
        raise TreeBuilderError("ForeignAttributes::merge: unimplemented")

    def clone(self) -> Attributes:
        return self

# Ported from RemexHtml 3.0.2 src/Serializer/ (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""Serialization of the tree as it is built (namespace Wikimedia\\RemexHtml\\Serializer)."""
from .formatters import DepurateFormatter, FastFormatter, Formatter, HtmlFormatter, TestFormatter, uncoerce_name
from .serializer import AbstractSerializer, Serializer, SerializerError, SerializerNode, SerializerWithTracer

__all__ = ["AbstractSerializer", "DepurateFormatter", "FastFormatter", "Formatter", "HtmlFormatter", "Serializer",
           "SerializerError", "SerializerNode", "SerializerWithTracer", "TestFormatter", "uncoerce_name"]

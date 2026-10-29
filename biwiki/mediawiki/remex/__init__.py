# Ported from RemexHtml 3.0.2 (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation.
# MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""RemexHtml, an HTML 5 parser (tokenizer, tree builder, serializer), translated to Python.

See README.md in this directory. The subpackages follow RemexHtml's namespaces: ``tokenizer``
(Wikimedia\\RemexHtml\\Tokenizer), ``treebuilder`` (Wikimedia\\RemexHtml\\TreeBuilder) and ``serializer``
(Wikimedia\\RemexHtml\\Serializer); ``htmldata`` is Wikimedia\\RemexHtml\\HTMLData.
"""
from .htmldata import HTMLData

__all__ = ["HTMLData"]

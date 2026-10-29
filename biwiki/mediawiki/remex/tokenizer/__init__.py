# Ported from RemexHtml 3.0.2 src/Tokenizer/ (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The tokenizer: a token event stream from HTML text (namespace Wikimedia\\RemexHtml\\Tokenizer)."""
from .attributes import Attribute, Attributes, LazyAttributes, PlainAttributes
from .token_handler import NullTokenHandler, RelayTokenHandler, TestTokenHandler, TokenHandler, TokenSerializer
from .tokenizer import Tokenizer, TokenizerError

__all__ = ["Attribute", "Attributes", "LazyAttributes", "NullTokenHandler", "PlainAttributes", "RelayTokenHandler",
           "TestTokenHandler", "TokenHandler", "TokenSerializer", "Tokenizer", "TokenizerError"]

# Ported from RemexHtml 3.0.2 src/Tokenizer/TokenHandler.php, NullTokenHandler.php, RelayTokenHandler.php,
# TestTokenHandler.php and TokenSerializer.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""Receivers of tokenizer events."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .attributes import Attributes

if TYPE_CHECKING:
    from .tokenizer import Tokenizer


class TokenHandler:
    """This is the interface for handlers receiving events from the Tokenizer. All events which consume characters
    give a source offset and length, allowing for input stream patching. The offset and length are relative to the
    preprocessed input, see Tokenizer::getPreprocessedText()
    """

    def start_document(self, tokenizer: Tokenizer, fragment_namespace: Optional[str],
                       fragment_name: Optional[str]) -> None:
        """Called once at the start of the document (STATE_START). ``fragment_namespace``/``fragment_name``: the
        fragment namespace and tag name, or None to run in document mode."""
        raise NotImplementedError

    def end_document(self, pos: int) -> None:
        """Called when the end of the input string is consumed. ``pos``: the input position (past the end)"""
        raise NotImplementedError

    def error(self, text: str, pos: int) -> None:
        """This is called for "parse errors" (as defined by the spec). The spec does not define names for error
        messages, so we just use some English text for now. The imagined audience is a developer reading validator
        output."""
        raise NotImplementedError

    def characters(self, text: str, start: int, length: int, source_start: int, source_length: int) -> None:
        """A merged sequence of character tokens. We use the SAX-like convention of requiring the handler to do the
        substring operation, i.e. the actual text is substr( $text, $start, $length ), since this allows us to
        avoid some copying, at least if ignoreCharRefs and ignoreNulls are enabled."""
        raise NotImplementedError

    def start_tag(self, name: str, attrs: Attributes, self_close: bool, source_start: int,
                  source_length: int) -> None:
        """A start tag event. We call it a tag rather than an element since the start/end events are not balanced,
        so the relationship between tags and elements is complex. Errors emitted by attribute parsing will be not
        be received until $attrs is accessed by the handler."""
        raise NotImplementedError

    def end_tag(self, name: str, source_start: int, source_length: int) -> None:
        """An end tag event."""
        raise NotImplementedError

    def doctype(self, name: Optional[str], public: Optional[str], system: Optional[str], quirks: bool,
                source_start: int, source_length: int) -> None:
        """A DOCTYPE declaration. ``quirks``: what the spec calls the "force-quirks flag"."""
        raise NotImplementedError

    def comment(self, text: str, source_start: int, source_length: int) -> None:
        """A comment. ``text``: the inner text of the comment."""
        raise NotImplementedError


class NullTokenHandler(TokenHandler):
    """A TokenHandler which does nothing"""

    def start_document(self, tokenizer, fragment_namespace, fragment_name):
        pass

    def end_document(self, pos):
        pass

    def error(self, text, pos):
        pass

    def characters(self, text, start, length, source_start, source_length):
        pass

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        pass

    def end_tag(self, name, source_start, source_length):
        pass

    def doctype(self, name, public, system, quirks, source_start, source_length):
        pass

    def comment(self, text, source_start, source_length):
        pass


class RelayTokenHandler(TokenHandler):
    """A TokenHandler which simply passes all tokens through to another token handler, specified in the
    constructor.

    Applications can subclass this in order to modify only a few token types as they pass through.
    """

    def __init__(self, next_handler: TokenHandler):
        self.next_handler = next_handler

    def start_document(self, tokenizer, fragment_namespace, fragment_name):
        self.next_handler.start_document(tokenizer, fragment_namespace, fragment_name)

    def end_document(self, pos):
        self.next_handler.end_document(pos)

    def error(self, text, pos):
        self.next_handler.error(text, pos)

    def characters(self, text, start, length, source_start, source_length):
        self.next_handler.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        # (sic: RemexHtml passes $sourceLength as the start position too)
        self.next_handler.start_tag(name, attrs, self_close, source_length, source_length)

    def end_tag(self, name, source_start, source_length):
        self.next_handler.end_tag(name, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.next_handler.doctype(name, public, system, quirks, source_start, source_length)

    def comment(self, text, source_start, source_length):
        self.next_handler.comment(text, source_start, source_length)


class TestTokenHandler(TokenHandler):
    """A TokenHandler which collects events from the Tokenizer and generates an array compatible with the html5lib
    tokenizer tests."""

    __test__ = False  # not a unittest/pytest test class

    def __init__(self) -> None:
        self.tokens: list[Any] = []

    def get_tokens(self) -> list[Any]:
        return self.tokens

    def start_document(self, tokenizer, fragment_namespace, fragment_name):
        pass

    def end_document(self, pos):
        pass

    def error(self, text, pos):
        self.tokens.append("ParseError")

    def characters(self, text, start, length, source_start, source_length):
        self.tokens.append(["Character", text[start:start + length]])

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        attr_array = dict(attrs.get_values())
        if self_close:
            self.tokens.append(["StartTag", name, attr_array, self_close])
        else:
            self.tokens.append(["StartTag", name, attr_array])

    def end_tag(self, name, source_start, source_length):
        self.tokens.append(["EndTag", name])

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.tokens.append(["DOCTYPE", name, public, system, not quirks])

    def comment(self, text, source_start, source_length):
        self.tokens.append(["Comment", text])


def _htmlspecialchars(s: str) -> str:
    return (s.replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#039;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class TokenSerializer(TokenHandler):
    """A simple serializer for the token stream, mostly meant for debugging.

    The main reason this shouldn't be used in production for modification of HTML documents is that element names
    are only determined by TreeBuilder and are not known here. The correct serialization for a text node depends on
    its parent element, including its namespace.
    """

    def __init__(self) -> None:
        self.output = ""
        self.errors: list[tuple[str, int]] = []

    def get_output(self) -> str:
        return self.output

    def get_errors(self) -> list[tuple[str, int]]:
        return self.errors

    def start_document(self, tokenizer, fragment_namespace, fragment_name):
        self.output = ""

    def end_document(self, pos):
        pass

    def error(self, text, pos):
        self.errors.append((text, pos))

    def characters(self, text, start, length, source_start, source_length):
        self.output += _htmlspecialchars(text[start:start + length])

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        self.output += f"<{name}"
        for attr_name, value in attrs.get_values().items():
            self.output += f" {attr_name}=\"" + value.replace('"', "&quot;") + '"'
        if self_close:
            self.output += " /"
        self.output += ">"

    def end_tag(self, name, source_start, source_length):
        self.output += f"</{name}>"

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.output += f"<!DOCTYPE {name or ''}"
        if public:
            self.output += f' PUBLIC "{public}"'
            if system:
                self.output += f' "{system}"'
        elif system:
            self.output += f' SYSTEM "{system}"'
        self.output += ">"
        if quirks:
            self.output += "<!--quirks-->"

    def comment(self, text, source_start, source_length):
        self.output += "<!--" + text + "-->"

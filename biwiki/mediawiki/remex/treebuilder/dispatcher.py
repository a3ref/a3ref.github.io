# Ported from RemexHtml 3.0.2 src/TreeBuilder/Dispatcher.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The tree construction dispatcher."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..htmldata import HTMLData
from ..tokenizer.attributes import Attributes
from ..tokenizer.token_handler import TokenHandler
from .active_formatting_elements import TemplateModeStack
from .stack import TreeBuilderError

if TYPE_CHECKING:
    from ..tokenizer.tokenizer import Tokenizer
    from .element import Element
    from .insertion_mode import InsertionMode
    from .tree_builder import TreeBuilder


class Dispatcher(TokenHandler):
    """This is the approximate equivalent of the "tree construction dispatcher" in the spec. It receives token
    events and distributes them to the appropriate insertion mode class. It also implements some things specific to
    the dispatcher state:
      - "Reset the insertion mode appropriately"
      - The stack of template insertion modes
      - The "original insertion mode"
    """

    # The insertion mode indexes
    INITIAL = 1
    BEFORE_HTML = 2
    BEFORE_HEAD = 3
    IN_HEAD = 4
    IN_HEAD_NOSCRIPT = 5
    AFTER_HEAD = 6
    IN_BODY = 7
    TEXT = 8
    IN_TABLE = 9
    IN_TABLE_TEXT = 10
    IN_CAPTION = 11
    IN_COLUMN_GROUP = 12
    IN_TABLE_BODY = 13
    IN_ROW = 14
    IN_CELL = 15
    IN_SELECT = 16
    IN_SELECT_IN_TABLE = 17
    IN_TEMPLATE = 18
    AFTER_BODY = 19
    IN_FRAMESET = 20
    AFTER_FRAMESET = 21
    AFTER_AFTER_BODY = 22
    AFTER_AFTER_FRAMESET = 23
    IN_FOREIGN_CONTENT = 24
    IN_PRE = 25
    IN_TEXTAREA = 26

    # The handler class for each insertion mode (filled in at the end of this module)
    handler_classes: dict[int, type] = {}

    _TABLE_MODES = frozenset([IN_TABLE, IN_CAPTION, IN_TABLE_BODY, IN_ROW, IN_CELL])

    def __init__(self, builder: TreeBuilder):
        self.builder = builder
        self.template_mode_stack = TemplateModeStack()
        # Public shortcuts for "using the rules for" actions
        self.in_head = None
        self.in_body = None
        self.in_table = None
        self.in_select = None
        self.in_template = None
        self.in_foreign = None
        # The InsertionMode object for the current insertion mode in HTML content
        self.handler: Optional[InsertionMode] = None
        # An array mapping insertion mode indexes to InsertionMode objects
        self.dispatch_table: Optional[dict[int, InsertionMode]] = None
        # The insertion mode index
        self.mode: Optional[int] = None
        # The "original insertion mode" index
        self.original_mode: Optional[int] = None
        # The insertion mode sets this to true to acknowledge the tag's self-closing flag.
        self.ack: Optional[bool] = None

    def switch_mode(self, mode: int) -> InsertionMode:
        """Switch the insertion mode, and return the new handler"""
        self.mode = mode
        self.handler = self.dispatch_table[mode]
        return self.handler

    def switch_and_save(self, mode: int) -> InsertionMode:
        """Let the original insertion mode be the current insertion mode, and switch the insertion mode to some new
        value. Return the new handler."""
        self.original_mode = self.mode
        self.mode = mode
        self.handler = self.dispatch_table[mode]
        return self.handler

    def restore_mode(self) -> InsertionMode:
        """Switch the insertion mode to the original insertion mode and return the new handler."""
        if self.original_mode is None:
            raise TreeBuilderError("original insertion mode is not set")
        mode = self.mode = self.original_mode
        self.original_mode = None
        self.handler = self.dispatch_table[mode]
        return self.handler

    def get_handler(self) -> Optional[InsertionMode]:
        """Get the handler for the current insertion mode in HTML content. This is used by the "in foreign" handler
        to execute the HTML insertion mode. It does not necessarily correspond to the handler currently being
        executed."""
        return self.handler

    def is_in_table_mode(self) -> bool:
        """True if we are in a table mode, for the purposes of switching to IN_SELECT_IN_TABLE as opposed to
        IN_SELECT."""
        return self.mode in self._TABLE_MODES

    def flush_table_text(self) -> None:
        """If the insertion mode is "in table text", flush the pending table text. This is a facility allowing users
        to insert into the DOM more cleanly."""
        from .table_modes import InTableText
        if self.mode == self.IN_TABLE_TEXT and isinstance(self.handler, InTableText):
            self.handler.flush()

    def reset(self) -> InsertionMode:
        """Reset the insertion mode appropriately, and return the new handler."""
        return self.switch_mode(self.get_appropriate_mode())

    def get_appropriate_mode(self) -> int:
        """Get the insertion mode index which is switched to when we reset the insertion mode appropriately."""
        builder = self.builder
        stack = builder.stack
        last = False
        for idx in range(stack.length() - 1, -1, -1):
            node = stack.item(idx)
            if idx == 0:
                last = True
                if builder.is_fragment:
                    node = builder.fragment_context
            name = node.html_name
            if name == "select":
                if last:
                    return self.IN_SELECT
                for ancestor_idx in range(idx - 1, 0, -1):
                    ancestor = stack.item(ancestor_idx)
                    if ancestor.html_name == "template":
                        return self.IN_SELECT
                    elif ancestor.html_name == "table":
                        return self.IN_SELECT_IN_TABLE
                return self.IN_SELECT
            elif name in ("td", "th"):
                if not last:
                    return self.IN_CELL
            elif name == "tr":
                return self.IN_ROW
            elif name in ("tbody", "thead", "tfoot"):
                return self.IN_TABLE_BODY
            elif name == "caption":
                return self.IN_CAPTION
            elif name == "colgroup":
                return self.IN_COLUMN_GROUP
            elif name == "table":
                return self.IN_TABLE
            elif name == "template":
                return self.template_mode_stack.current
            elif name == "head":
                if last:
                    return self.IN_BODY
                else:
                    return self.IN_HEAD
            elif name == "body":
                return self.IN_BODY
            elif name == "frameset":
                return self.IN_FRAMESET
            elif name == "html":
                if builder.head_element is None:
                    return self.BEFORE_HEAD
                else:
                    return self.AFTER_HEAD
        return self.IN_BODY

    def dispatcher_current_node(self) -> Optional[Element]:
        """If the stack of open elements is empty, return null, otherwise return the adjusted current node."""
        current = self.builder.stack.current
        if current and current.stack_index == 0 and self.builder.is_fragment:
            return self.builder.fragment_context
        else:
            return current

    def start_document(self, tokenizer: Tokenizer, namespace: Optional[str], name: Optional[str]) -> None:
        self.dispatch_table = {}
        for mode, class_ in self.handler_classes.items():
            self.dispatch_table[mode] = class_(self.builder, self)
        self.in_head = self.dispatch_table[self.IN_HEAD]
        self.in_body = self.dispatch_table[self.IN_BODY]
        self.in_table = self.dispatch_table[self.IN_TABLE]
        self.in_select = self.dispatch_table[self.IN_SELECT]
        self.in_template = self.dispatch_table[self.IN_TEMPLATE]
        self.in_foreign = self.dispatch_table[self.IN_FOREIGN_CONTENT]
        self.switch_mode(self.INITIAL)
        self.builder.start_document(tokenizer, namespace, name)
        if namespace is not None:
            if namespace == HTMLData.NS_HTML and name == "template":
                self.template_mode_stack.push(self.IN_TEMPLATE)
            self.reset()

    def end_document(self, pos: int) -> None:
        self.handler.end_document(pos)
        # All references to insertion modes must be explicitly released, since
        # they have a circular reference back to $this
        self.dispatch_table = None
        self.handler = None
        self.in_head = None
        self.in_body = None
        self.in_table = None
        self.in_select = None
        self.in_template = None
        self.in_foreign = None

    def error(self, text: str, pos: int) -> None:
        self.builder.error(text, pos)

    def characters(self, text: str, start: int, length: int, source_start: int, source_length: int) -> None:
        current = self.dispatcher_current_node()
        if (not current or current.namespace == HTMLData.NS_HTML or current.is_mathml_text_integration()
                or current.is_html_integration()):
            self.handler.characters(text, start, length, source_start, source_length)
        else:
            self.in_foreign.characters(text, start, length, source_start, source_length)

    def start_tag(self, name: str, attrs: Attributes, self_close: bool, source_start: int,
                  source_length: int) -> None:
        self.ack = False
        current = self.dispatcher_current_node()
        if (not current
                or current.namespace == HTMLData.NS_HTML
                or (current.is_mathml_text_integration() and name != "mglyph" and name != "malignmark")
                or (name == "svg" and current.namespace == HTMLData.NS_MATHML and current.name == "annotation-xml")
                or current.is_html_integration()):
            self.handler.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            self.in_foreign.start_tag(name, attrs, self_close, source_start, source_length)
        if self_close and not self.ack:
            self.builder.error("unacknowledged self-closing tag", source_start)

    def end_tag(self, name: str, source_start: int, source_length: int) -> None:
        current = self.dispatcher_current_node()
        if not current or current.namespace == HTMLData.NS_HTML:
            self.handler.end_tag(name, source_start, source_length)
        else:
            self.in_foreign.end_tag(name, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start: int, source_length: int) -> None:
        current = self.dispatcher_current_node()
        if not current or current.namespace == HTMLData.NS_HTML:
            self.handler.doctype(name, public, system, quirks, source_start, source_length)
        else:
            self.in_foreign.doctype(name, public, system, quirks, source_start, source_length)

    def comment(self, text: str, source_start: int, source_length: int) -> None:
        current = self.dispatcher_current_node()
        if not current or current.namespace == HTMLData.NS_HTML:
            self.handler.comment(text, source_start, source_length)
        else:
            self.in_foreign.comment(text, source_start, source_length)


# The insertion modes import Dispatcher for its mode constants, so they are imported after the class is defined.
from .body_modes import InBody, InPre, InTextarea, Text  # noqa: E402
from .document_modes import (AfterAfterBody, AfterAfterFrameset, AfterBody, AfterFrameset, AfterHead,  # noqa: E402
                             BeforeHead, BeforeHtml, InFrameset, InHead, InHeadNoscript, Initial)
from .in_foreign_content import InForeignContent  # noqa: E402
from .select_template_modes import InSelect, InSelectInTable, InTemplate  # noqa: E402
from .table_modes import InCaption, InCell, InColumnGroup, InRow, InTable, InTableBody, InTableText  # noqa: E402

Dispatcher.handler_classes = {
    Dispatcher.INITIAL: Initial,
    Dispatcher.BEFORE_HTML: BeforeHtml,
    Dispatcher.BEFORE_HEAD: BeforeHead,
    Dispatcher.IN_HEAD: InHead,
    Dispatcher.IN_HEAD_NOSCRIPT: InHeadNoscript,
    Dispatcher.AFTER_HEAD: AfterHead,
    Dispatcher.IN_BODY: InBody,
    Dispatcher.TEXT: Text,
    Dispatcher.IN_TABLE: InTable,
    Dispatcher.IN_TABLE_TEXT: InTableText,
    Dispatcher.IN_CAPTION: InCaption,
    Dispatcher.IN_COLUMN_GROUP: InColumnGroup,
    Dispatcher.IN_TABLE_BODY: InTableBody,
    Dispatcher.IN_ROW: InRow,
    Dispatcher.IN_CELL: InCell,
    Dispatcher.IN_SELECT: InSelect,
    Dispatcher.IN_SELECT_IN_TABLE: InSelectInTable,
    Dispatcher.IN_TEMPLATE: InTemplate,
    Dispatcher.AFTER_BODY: AfterBody,
    Dispatcher.IN_FRAMESET: InFrameset,
    Dispatcher.AFTER_FRAMESET: AfterFrameset,
    Dispatcher.AFTER_AFTER_BODY: AfterAfterBody,
    Dispatcher.AFTER_AFTER_FRAMESET: AfterAfterFrameset,
    Dispatcher.IN_FOREIGN_CONTENT: InForeignContent,
    Dispatcher.IN_PRE: InPre,
    Dispatcher.IN_TEXTAREA: InTextarea,
}

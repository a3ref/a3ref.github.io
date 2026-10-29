# Ported from RemexHtml 3.0.2 src/TreeBuilder/InTable.php, InTableText.php, InCaption.php, InColumnGroup.php,
# InTableBody.php, InRow.php and InCell.php (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The table insertion modes."""
from __future__ import annotations

from .._php import strcasecmp, strspn
from ..tokenizer.attributes import PlainAttributes
from .dispatcher import Dispatcher
from .insertion_mode import InsertionMode

_WHITESPACE = "\t\n\f\r "

# The tag names that are cleared when we "clear the stack back to a table context"
_TABLE_CONTEXT = frozenset(["table", "template", "html"])
_TABLE_BODY_CONTEXT = frozenset(["tbody", "tfoot", "thead", "template", "html"])
_TABLE_ROW_CONTEXT = frozenset(["tr", "template", "html"])

_TABLE_TEXT_PARENTS = frozenset(["table", "tbody", "tfoot", "thead", "tr"])


class InTable(InsertionMode):
    """The "in table" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        if self.builder.stack.current.html_name in _TABLE_TEXT_PARENTS:
            self.builder.pending_table_characters = []
            self.dispatcher.switch_and_save(Dispatcher.IN_TABLE_TEXT).characters(text, start, length, source_start,
                                                                                 source_length)
        else:
            self.builder.error("unexpected text in table, fostering", source_start)
            self.builder.foster_parenting = True
            self.dispatcher.in_body.characters(text, start, length, source_start, source_length)
            self.builder.foster_parenting = False

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        stack = builder.stack
        if name == "caption":
            builder.clear_stack_back(_TABLE_CONTEXT, source_start)
            builder.afe.insert_marker()
            dispatcher.switch_mode(Dispatcher.IN_CAPTION)
            builder.insert_element(name, attrs, False, source_start, source_length)
        elif name == "colgroup":
            builder.clear_stack_back(_TABLE_CONTEXT, source_start)
            dispatcher.switch_mode(Dispatcher.IN_COLUMN_GROUP)
            builder.insert_element(name, attrs, False, source_start, source_length)
        elif name == "col":
            builder.clear_stack_back(_TABLE_CONTEXT, source_start)
            builder.insert_element("colgroup", PlainAttributes(), False, source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_COLUMN_GROUP).start_tag(name, attrs, self_close, source_start,
                                                                         source_length)
        elif name in ("tbody", "tfoot", "thead"):
            builder.clear_stack_back(_TABLE_CONTEXT, source_start)
            builder.insert_element(name, attrs, False, source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_TABLE_BODY)
        elif name in ("td", "th", "tr"):
            builder.clear_stack_back(_TABLE_CONTEXT, source_start)
            builder.insert_element("tbody", PlainAttributes(), False, source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_TABLE_BODY).start_tag(name, attrs, self_close, source_start,
                                                                       source_length)
        elif name == "table":
            builder.error("unexpected <table> in table", source_start)
            if not stack.is_in_table_scope("table"):
                # Ignore
                return
            builder.pop_all_up_to_name("table", source_start, 0)
            dispatcher.reset().start_tag(name, attrs, self_close, source_start, source_length)
        elif name in ("style", "script", "template"):
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "form":
            if stack.has_template() or builder.form_element is not None:
                builder.error("invalid form in table, ignoring", source_start)
                # Ignore
                return
            builder.error("invalid form in table, inserting void element", source_start)
            elt = builder.insert_element("form", attrs, True, source_start, source_length)
            builder.form_element = elt
        elif name == "input" and "type" in attrs and strcasecmp(attrs["type"], "hidden") == 0:
            builder.error("begrudgingly accepting a hidden input in table mode", source_start)
            dispatcher.ack = True
            builder.insert_element(name, attrs, True, source_start, source_length)
        else:
            builder.error("invalid start tag in table, fostering", source_start)
            builder.foster_parenting = True
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
            builder.foster_parenting = False

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "table":
            if not stack.is_in_table_scope("table"):
                builder.error("</table> found but no table element in scope, ignoring", source_start)
                # Ignore
                return
            builder.pop_all_up_to_name("table", source_start, source_length)
            dispatcher.reset()
        elif name in ("body", "caption", "col", "colgroup", "html", "tbody", "td", "tfoot", "th", "thead", "tr"):
            builder.error("ignoring invalid end tag inside table", source_start)
        elif name == "template":
            dispatcher.in_head.end_tag(name, source_start, source_length)
        else:
            builder.error("unexpected end tag in table, fostering", source_start)
            builder.foster_parenting = True
            dispatcher.in_body.end_tag(name, source_start, source_length)
            builder.foster_parenting = False

    def end_document(self, pos):
        self.dispatcher.in_body.end_document(pos)


class InTableText(InsertionMode):
    """The "in table text" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        def handle_non_null(text, start, length, source_start, source_length):
            self.builder.pending_table_characters.append((text, start, length, source_start, source_length))

        if not self.builder.ignore_nulls:
            self.strip_nulls(handle_non_null, text, start, length, source_start, source_length)
        else:
            handle_non_null(text, start, length, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.process_pending_characters()
        self.dispatcher.restore_mode().doctype(name, public, system, quirks, source_start, source_length)

    def comment(self, text, source_start, source_length):
        self.process_pending_characters()
        self.dispatcher.restore_mode().comment(text, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        self.process_pending_characters()
        self.dispatcher.restore_mode().start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        self.process_pending_characters()
        self.dispatcher.restore_mode().end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.process_pending_characters()
        self.dispatcher.restore_mode().end_document(pos)

    def flush(self) -> None:
        """Flush the pending table text and restore the mode"""
        self.process_pending_characters()
        self.dispatcher.restore_mode()

    def process_pending_characters(self) -> None:
        """Common code for the "anything else" case. Process the pending table character tokens."""
        builder = self.builder
        all_space = True
        for text, start, length, source_start, source_length in builder.pending_table_characters:
            if strspn(text, _WHITESPACE, start, length) != length:
                all_space = False
        if all_space:
            for text, start, length, source_start, source_length in builder.pending_table_characters:
                builder.insert_characters(text, start, length, source_start, source_length)
        else:
            builder.foster_parenting = True
            for text, start, length, source_start, source_length in builder.pending_table_characters:
                builder.error("invalid characters in table text, fostering", source_start)
                self.dispatcher.in_body.characters(text, start, length, source_start, source_length)
            builder.foster_parenting = False


class InCaption(InsertionMode):
    """The "in caption" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.dispatcher.in_body.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        if name in ("caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"):
            builder.error(f"start tag <{name}> not allowed in caption", source_start)
            if not stack.is_in_table_scope("caption"):
                # Ignore
                return
            builder.pop_all_up_to_name("caption", source_start, 0)
            builder.afe.clear_to_marker()
            self.dispatcher.switch_mode(Dispatcher.IN_TABLE).start_tag(name, attrs, self_close, source_start,
                                                                       source_length)
        else:
            self.dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        dispatcher = self.dispatcher
        builder = self.builder
        stack = builder.stack
        if name == "caption":
            if not stack.is_in_table_scope("caption"):
                builder.error("</caption> matches a start tag which is not in scope, ignoring", source_start)
                return
            builder.generate_implied_end_tags(None, source_start)
            if stack.current.html_name != "caption":
                builder.error("</caption> found but another element is open", source_start)
            builder.pop_all_up_to_name("caption", source_start, source_length)
            builder.afe.clear_to_marker()
            dispatcher.switch_mode(Dispatcher.IN_TABLE)
        elif name == "table":
            if not stack.is_in_table_scope("caption"):
                builder.error("</table> found in caption, but there is no caption in scope, ignoring",
                              source_start)
                return
            builder.generate_implied_end_tags(None, source_start)
            if stack.current.html_name != "caption":
                builder.error("</table> found in caption, closing caption", source_start)
            builder.pop_all_up_to_name("caption", source_start, 0)
            builder.afe.clear_to_marker()
            dispatcher.switch_mode(Dispatcher.IN_TABLE).end_tag(name, source_start, source_length)
        elif name in ("body", "col", "colgroup", "html", "tbody", "td", "tfoot", "th", "thead", "tr"):
            self.builder.error(f"end tag </{name}> ignored in caption mode", source_start)
        else:
            self.dispatcher.in_body.end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.in_body.end_document(pos)


class InColumnGroup(InsertionMode):
    """The "in column group" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part1
        if length != 0:
            self.builder.insert_characters(text, start, length, source_start, source_length)
        start, length, source_start, source_length = part2
        if length == 0:
            # All done with this sequence
            return

        # Handle non-whitespace as "anything else"
        builder = self.builder
        stack = builder.stack
        if stack.current.html_name != "colgroup":
            builder.error("text should close the colgroup but another element is open", source_start)
            # Ignore
            return
        else:
            builder.pop(source_start, 0)
        self.dispatcher.switch_mode(Dispatcher.IN_TABLE).characters(text, start, length, source_start,
                                                                    source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        dispatcher = self.dispatcher
        builder = self.builder
        stack = builder.stack
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "col":
            dispatcher.ack = True
            builder.insert_element(name, attrs, True, source_start, source_length)
        elif name == "template":
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            if stack.current.html_name != "colgroup":
                builder.error("start tag should close the colgroup but another element is open", source_start)
                # Ignore
                return
            else:
                builder.pop(source_start, 0)
            self.dispatcher.switch_mode(Dispatcher.IN_TABLE).start_tag(name, attrs, self_close, source_start,
                                                                       source_length)

    def end_tag(self, name, source_start, source_length):
        dispatcher = self.dispatcher
        builder = self.builder
        stack = builder.stack
        if name == "colgroup":
            if stack.current.html_name != "colgroup":
                builder.error("</colgroup> found but another element is open, ignoring", source_start)
                return
            builder.pop(source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_TABLE)
        elif name == "col":
            builder.error("</col> found in column group mode, ignoring", source_start)
        elif name == "template":
            dispatcher.in_head.end_tag(name, source_start, source_length)
        else:
            if stack.current.html_name != "colgroup":
                builder.error("non-matching end tag should close the colgroup  but another element is open",
                              source_start)
                # Ignore
                return
            else:
                builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_TABLE).end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.in_body.end_document(pos)


class InTableBody(InsertionMode):
    """The "in table body" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.dispatcher.in_table.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "tr":
            builder.clear_stack_back(_TABLE_BODY_CONTEXT, source_start)
            builder.insert_element(name, attrs, False, source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_ROW)
        elif name in ("th", "td"):
            builder.error(f"<{name}> encountered in table body (not row) mode", source_start)
            builder.clear_stack_back(_TABLE_BODY_CONTEXT, source_start)
            builder.insert_element("tr", PlainAttributes(), False, source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_ROW).start_tag(name, attrs, self_close, source_start,
                                                                source_length)
        elif name in ("caption", "col", "colgroup", "tbody", "tfoot", "thead"):
            if (not stack.is_in_table_scope("tbody") and not stack.is_in_table_scope("thead")
                    and not stack.is_in_table_scope("tfoot")):
                builder.error(f"<{name}> encountered in table body mode when there is no tbody/thead/tfoot in scope",
                              source_start)
                return
            builder.clear_stack_back(_TABLE_BODY_CONTEXT, source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_TABLE).start_tag(name, attrs, self_close, source_start,
                                                                  source_length)
        else:
            dispatcher.in_table.start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name in ("tbody", "tfoot", "thead"):
            if not stack.is_in_table_scope(name):
                builder.error(f"</{name}> found but no {name} in scope", source_start)
                return
            builder.clear_stack_back(_TABLE_BODY_CONTEXT, source_start)
            builder.pop(source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_TABLE)
        elif name in ("body", "caption", "col", "colgroup", "html", "td", "th", "tr"):
            builder.error(f"</{name}> found in table body mode, ignoring", source_start)
            return
        else:
            dispatcher.in_table.end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.in_table.end_document(pos)


class InRow(InsertionMode):
    """The "in row" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.dispatcher.in_table.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name in ("th", "td"):
            builder.clear_stack_back(_TABLE_ROW_CONTEXT, source_start)
            builder.insert_element(name, attrs, False, source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_CELL)
            builder.afe.insert_marker()
        elif name in ("caption", "col", "colgroup", "tbody", "tfoot", "thead", "tr"):
            if not stack.is_in_table_scope("tr"):
                builder.error(f"<{name}> should close the tr but it is not in scope", source_start)
                # Ignore
                return
            builder.clear_stack_back(_TABLE_ROW_CONTEXT, source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_TABLE_BODY).start_tag(name, attrs, self_close, source_start,
                                                                       source_length)
        else:
            dispatcher.in_table.start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "tr":
            if not stack.is_in_table_scope("tr"):
                builder.error("</tr> found but no tr element in scope", source_start)
                # Ignore
                return
            builder.clear_stack_back(_TABLE_ROW_CONTEXT, source_start)
            builder.pop(source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_TABLE_BODY)
        elif name == "table":
            if not stack.is_in_table_scope("tr"):
                builder.error("</table> should close the tr but it is not in scope", source_start)
                # Ignore
                return
            builder.clear_stack_back(_TABLE_ROW_CONTEXT, source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_TABLE_BODY).end_tag(name, source_start, source_length)
        elif name in ("tbody", "tfoot", "thead"):
            if not stack.is_in_table_scope(name):
                builder.error(f"</{name}> encountered but there is no {name} element in scope", source_start)
                return
            if not stack.is_in_table_scope("tr"):
                return
            builder.clear_stack_back(_TABLE_ROW_CONTEXT, source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_TABLE_BODY).end_tag(name, source_start, source_length)
        elif name in ("body", "caption", "col", "colgroup", "html", "td", "th"):
            builder.error(f"</{name}> encountered in row mode, ignoring", source_start)
            return
        else:
            dispatcher.in_table.end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.in_table.end_document(pos)


class InCell(InsertionMode):
    """The "in cell" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.dispatcher.in_body.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        if name in ("caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"):
            if not self.builder.stack.is_in_table_scope("td") and not self.builder.stack.is_in_table_scope("th"):
                self.builder.error(f"<{name}> tag should close the cell but none is in scope", source_start)
                return
            self._close_the_cell(source_start).start_tag(name, attrs, self_close, source_start, source_length)
        else:
            self.dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name in ("td", "th"):
            if not stack.is_in_table_scope(name):
                builder.error(f"</{name}> encountered but there is no {name} in scope, ignoring", source_start)
                return
            builder.generate_implied_end_tags(None, source_start)
            if stack.current.html_name != name:
                builder.error(f"</{name}> encountered when there are tags open which can't be closed automatically",
                              source_start)
            builder.pop_all_up_to_name(name, source_start, source_length)
            builder.afe.clear_to_marker()
            dispatcher.switch_mode(Dispatcher.IN_ROW)
        elif name in ("body", "caption", "col", "colgroup", "html"):
            builder.error(f"unexpected </{name}> in cell, ignoring", source_start)
            return
        elif name in ("table", "tbody", "tfoot", "thead", "tr"):
            if not stack.is_in_table_scope(name):
                builder.error(f"</{name}> encountered but there is no {name} in scope, ignoring", source_start)
                return
            self._close_the_cell(source_start).end_tag(name, source_start, source_length)
        else:
            dispatcher.in_body.end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.in_body.end_document(pos)

    def _close_the_cell(self, source_start: int) -> InsertionMode:
        builder = self.builder
        stack = builder.stack
        builder.generate_implied_end_tags(None, source_start)
        if stack.current.html_name not in ("td", "th"):
            builder.error("closing the cell but there are tags open which can't be closed automatically",
                          source_start)
        builder.afe.clear_to_marker()
        return self.dispatcher.switch_mode(Dispatcher.IN_ROW)

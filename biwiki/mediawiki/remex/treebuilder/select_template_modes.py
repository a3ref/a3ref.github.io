# Ported from RemexHtml 3.0.2 src/TreeBuilder/InSelect.php, InSelectInTable.php and InTemplate.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The select and template insertion modes."""
from __future__ import annotations

from .dispatcher import Dispatcher
from .insertion_mode import InsertionMode


class InSelect(InsertionMode):
    """The "in select" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        def insert(text, start, length, source_start, source_length):
            self.builder.insert_characters(text, start, length, source_start, source_length)

        self.strip_nulls(insert, text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "option":
            if stack.current.html_name == "option":
                builder.pop(source_start, 0)
            builder.insert_element("option", attrs, False, source_start, source_length)
        elif name == "optgroup":
            if stack.current.html_name == "option":
                builder.pop(source_start, 0)
            if stack.current.html_name == "optgroup":
                builder.pop(source_start, 0)
            builder.insert_element("optgroup", attrs, False, source_start, source_length)
        elif name == "select":
            if not stack.is_in_select_scope("select"):
                builder.error("<select> found in select mode but no select element is in scope, ignoring",
                              source_start)
                return
            builder.error("<select> found inside a select element", source_start)
            builder.pop_all_up_to_name("select", source_start, source_length)
            dispatcher.reset()
        elif name in ("input", "keygen", "textarea"):
            builder.error(f"<{name}> found inside a select element", source_start)
            if not stack.is_in_select_scope("select"):
                # Ignore
                return
            builder.pop_all_up_to_name("select", source_start, 0)
            dispatcher.reset().start_tag(name, attrs, self_close, source_start, source_length)
        elif name in ("script", "template"):
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            builder.error(f"<{name}> found inside a select element, ignoring", source_start)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "optgroup":
            if stack.current.html_name == "option":
                penultimate = stack.item(stack.length() - 2)
                if penultimate and penultimate.html_name == "optgroup":
                    builder.pop(source_start, 0)
            if stack.current.html_name != "optgroup":
                builder.error("unexpected </optgroup>, ignoring", source_start)
                return
            builder.pop(source_start, source_length)
        elif name == "option":
            if stack.current.html_name != "option":
                builder.error("unexpected </option>, ignoring", source_start)
                return
            builder.pop(source_start, source_length)
        elif name == "select":
            if not stack.is_in_select_scope("select"):
                builder.error("</select> found but the select element is not in scope", source_start)
                return
            builder.pop_all_up_to_name("select", source_start, source_length)
            dispatcher.reset()
        elif name == "template":
            dispatcher.in_head.end_tag(name, source_start, source_length)
        else:
            builder.error(f"unexpected </{name}> in select, ignoring", source_start)

    def end_document(self, pos):
        self.dispatcher.in_body.end_document(pos)


_TABLE_TAGS = frozenset(["caption", "table", "tbody", "tfoot", "thead", "tr", "td", "th"])


class InSelectInTable(InsertionMode):
    """The "in select in table" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.dispatcher.in_select.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name in _TABLE_TAGS:
            builder.error(f"unexpected <{name}> in select in table, closing select", source_start)
            builder.pop_all_up_to_name("select", source_start, 0)
            dispatcher.reset().start_tag(name, attrs, self_close, source_start, source_length)
        else:
            dispatcher.in_select.start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name in _TABLE_TAGS:
            if not stack.is_in_table_scope(name):
                builder.error(f"unexpected </{name}> in select in table, ignoring", source_start)
                return
            builder.error(f"unexpected </{name}> in select in table, closing select", source_start)
            builder.pop_all_up_to_name("select", source_start, 0)
            dispatcher.reset().end_tag(name, source_start, source_length)
        else:
            dispatcher.in_select.end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.in_select.end_document(pos)


class InTemplate(InsertionMode):
    """The "in template" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.dispatcher.in_body.characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        dispatcher = self.dispatcher
        if name in ("base", "basefont", "bgsound", "link", "meta", "noframes", "script", "style", "template",
                    "title"):
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
            return
        elif name in ("caption", "colgroup", "tbody", "tfoot", "thead"):
            mode = Dispatcher.IN_TABLE
        elif name == "col":
            mode = Dispatcher.IN_COLUMN_GROUP
        elif name == "tr":
            mode = Dispatcher.IN_TABLE_BODY
        elif name in ("td", "th"):
            mode = Dispatcher.IN_ROW
        else:
            mode = Dispatcher.IN_BODY
        dispatcher.template_mode_stack.pop()
        dispatcher.template_mode_stack.push(mode)
        dispatcher.switch_mode(mode).start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        dispatcher = self.dispatcher
        if name == "template":
            dispatcher.in_head.end_tag(name, source_start, source_length)
        else:
            self.builder.error(f"unexpected </{name}> in template, ignoring", source_start)
            return

    def end_document(self, pos):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if not stack.has_template():
            builder.stop_parsing(pos)
            return
        builder.error("unexpected end of file in template", pos)
        builder.pop_all_up_to_name("template", pos, 0)
        builder.afe.clear_to_marker()
        dispatcher.template_mode_stack.pop()
        dispatcher.reset().end_document(pos)

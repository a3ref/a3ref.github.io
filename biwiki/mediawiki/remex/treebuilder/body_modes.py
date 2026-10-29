# Ported from RemexHtml 3.0.2 src/TreeBuilder/InBody.php, Text.php, InPre.php and InTextarea.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The "in body" insertion mode, and the text modes entered from it."""
from __future__ import annotations

from .._php import strcasecmp, strspn
from ..htmldata import HTMLData
from ..tokenizer.attributes import PlainAttributes
from ..tokenizer.tokenizer import Tokenizer
from .dispatcher import Dispatcher
from .foreign_attributes import ForeignAttributes
from .insertion_mode import InsertionMode
from .stack import TreeBuilderError
from .tree_builder import TreeBuilder

# The tag names h1-h6, which are referred to at a couple of points.
_HEADING_NAMES = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])

# The tag names which can be closed by </body> or </html> without causing an error.
_IMPLICIT_CLOSE = frozenset(["dd", "dt", "li", "optgroup", "option", "p", "rb", "rp", "rt", "rtc", "tbody", "td",
                             "tfoot", "th", "thead", "tr", "body", "html"])

_END_DOCUMENT_ALLOWED = frozenset(["dd", "dt", "li", "p", "tbody", "td", "tfoot", "th", "thead", "tr", "body",
                                   "html"])

_CLOSE_P_START_TAGS = frozenset([
    "address", "article", "aside", "blockquote", "center", "details", "dir", "div", "dl", "fieldset", "figcaption",
    "figure", "footer", "header", "main", "menu", "nav", "ol", "p", "section", "summary", "ul",
])
_FORMATTING_START_TAGS = frozenset(["b", "big", "code", "em", "font", "i", "s", "small", "strike", "strong", "tt",
                                    "u"])
_BLOCK_END_TAGS = frozenset([
    "address", "article", "aside", "blockquote", "button", "center", "details", "dir", "div", "dl", "fieldset",
    "figcaption", "figure", "footer", "header", "listing", "main", "menu", "nav", "ol", "pre", "section", "summary",
    "ul",
])
_FORMATTING_END_TAGS = frozenset(["a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike",
                                  "strong", "tt", "u"])
_IN_HEAD_START_TAGS = frozenset(["base", "basefont", "bgsound", "link", "meta", "noframes", "script", "style",
                                 "template", "title"])
_INVALID_IN_BODY_START_TAGS = frozenset(["caption", "col", "colgroup", "frame", "head", "tbody", "td", "tfoot",
                                         "th", "thead", "tr"])


class InBody(InsertionMode):
    """The "in body" insertion mode."""

    def characters(self, text, start, length, source_start, source_length):
        def handle_non_null(text, start, length, source_start, source_length):
            if strspn(text, "\t\n\f\r ", start, length) != length:
                self.builder.frameset_ok = False
            self.builder.reconstruct_afe(source_start)
            self.builder.insert_characters(text, start, length, source_start, source_length)

        if not self.builder.ignore_nulls:
            self.strip_nulls(handle_non_null, text, start, length, source_start, source_length)
        else:
            handle_non_null(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        mode = None
        text_mode = None
        tokenizer_state = None
        is_new_afe = False
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        void = False
        if name == "html":
            builder.error("merging unexpected html tag", source_start)
            if stack.has_template():
                return
            if stack.length() < 1:
                return
            builder.merge_attributes(stack.item(0), attrs, source_start, source_length)
            return
        elif name in _IN_HEAD_START_TAGS:
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
            return
        elif name == "body":
            if stack.length() < 2 or stack.has_template():
                builder.error("ignored unexpected body tag", source_start)
                return
            body = stack.item(1)
            if body.html_name != "body":
                builder.error("ignored unexpected body tag", source_start)
                return
            builder.error("merged unexpected body tag", source_start)
            self.builder.frameset_ok = False
            self.builder.merge_attributes(body, attrs, source_start, source_length)
            return
        elif name == "frameset":
            if not builder.frameset_ok or stack.length() < 2 or stack.has_template():
                builder.error("ignored unexpected frameset tag", source_start)
                return
            body = stack.item(1)
            if body.html_name != "body":
                builder.error("ignored unexpected frameset tag", source_start)
                return
            builder.error("unexpected frameset tag erases body contents", source_start)
            builder.handler.remove_node(body, source_start)
            # Pop all the nodes from the bottom of the stack of open elements,
            # from the current node up to, but not including, the root html element.
            n = stack.length()
            for _ in range(n - 1):
                stack.pop()
            mode = Dispatcher.IN_FRAMESET
            # Insert as normal
        elif name in _CLOSE_P_START_TAGS:
            builder.close_p_in_button_scope(source_start)
        elif name in _HEADING_NAMES:
            builder.close_p_in_button_scope(source_start)
            if stack.current.html_name in _HEADING_NAMES:
                builder.error("invalid nested heading, closing previous", source_start)
                builder.pop(source_start, 0)
        elif name in ("pre", "listing"):
            builder.close_p_in_button_scope(source_start)
            builder.frameset_ok = False
            text_mode = Dispatcher.IN_PRE
        elif name == "form":
            if builder.form_element is not None and not stack.has_template():
                builder.error("ignoring nested form tag", source_start)
                return
            builder.close_p_in_button_scope(source_start)
            elt = builder.insert_element("form", attrs, False, source_start, source_length)
            if not stack.has_template():
                builder.form_element = elt
            return
        elif name == "li":
            builder.frameset_ok = False
            for idx in range(stack.length() - 1, -1, -1):
                node = stack.item(idx)
                html_name = node.html_name
                if html_name == "li":
                    builder.generate_implied_end_tags_and_pop("li", source_start, 0)
                    break
                if (node.name in HTMLData.special.get(node.namespace, ())
                        and html_name != "address" and html_name != "div" and html_name != "p"):
                    break
            builder.close_p_in_button_scope(source_start)
        elif name in ("dd", "dt"):
            builder.frameset_ok = False
            for idx in range(stack.length() - 1, -1, -1):
                node = stack.item(idx)
                html_name = node.html_name
                if html_name == "dd" or html_name == "dt":
                    builder.generate_implied_end_tags_and_pop(html_name, source_start, 0)
                    break
                if (node.name in HTMLData.special.get(node.namespace, ())
                        and html_name != "address" and html_name != "div" and html_name != "p"):
                    break
            builder.close_p_in_button_scope(source_start)
        elif name == "plaintext":
            builder.close_p_in_button_scope(source_start)
            tokenizer_state = Tokenizer.STATE_PLAINTEXT
        elif name == "button":
            if stack.is_in_scope("button"):
                builder.error("invalid nested button tag, closing previous", source_start)
                builder.generate_implied_end_tags(None, source_start)
                builder.pop_all_up_to_name("button", source_start, 0)
            builder.reconstruct_afe(source_start)
            builder.frameset_ok = False
        elif name == "a":
            elt = builder.afe.find_element_by_name("a")
            if elt is not None:
                builder.error("invalid nested a tag, closing previous", source_start)
                builder.adoption_agency("a", source_start, 0)
                if builder.afe.is_in_list(elt):
                    builder.afe.remove(elt)
                if elt.stack_index is not None:
                    stack.remove(elt)
            builder.reconstruct_afe(source_start)
            is_new_afe = True
        elif name in _FORMATTING_START_TAGS:
            builder.reconstruct_afe(source_start)
            is_new_afe = True
        elif name == "nobr":
            builder.reconstruct_afe(source_start)
            if stack.is_in_scope("nobr"):
                builder.error("invalid nested nobr tag, closing previous", source_start)
                builder.adoption_agency("nobr", source_start, 0)
                builder.reconstruct_afe(source_start)
            is_new_afe = True
        elif name in ("applet", "marquee", "object"):
            builder.reconstruct_afe(source_start)
            builder.afe.insert_marker()
            builder.frameset_ok = False
        elif name == "table":
            if builder.quirks != TreeBuilder.QUIRKS:
                builder.close_p_in_button_scope(source_start)
            builder.frameset_ok = False
            mode = Dispatcher.IN_TABLE
        elif name in ("area", "br", "embed", "img", "keygen", "wbr"):
            builder.reconstruct_afe(source_start)
            dispatcher.ack = True
            void = True
            builder.frameset_ok = False
        elif name == "input":
            builder.reconstruct_afe(source_start)
            dispatcher.ack = True
            void = True
            if "type" not in attrs or strcasecmp(attrs["type"], "hidden") != 0:
                builder.frameset_ok = False
        elif name in ("menuitem", "param", "source", "track"):
            dispatcher.ack = True
            void = True
        elif name == "hr":
            builder.close_p_in_button_scope(source_start)
            dispatcher.ack = True
            void = True
            builder.frameset_ok = False
        elif name == "image":
            builder.error('invalid "image" tag, assuming "img"', source_start)
            self.start_tag("img", attrs, self_close, source_start, source_length)
            return
        elif name == "textarea":
            tokenizer_state = Tokenizer.STATE_RCDATA
            text_mode = Dispatcher.IN_TEXTAREA
            builder.frameset_ok = False
        elif name == "xmp":
            builder.close_p_in_button_scope(source_start)
            builder.reconstruct_afe(source_start)
            builder.frameset_ok = False
            tokenizer_state = Tokenizer.STATE_RAWTEXT
            text_mode = Dispatcher.TEXT
        elif name == "iframe":
            builder.frameset_ok = False
            tokenizer_state = Tokenizer.STATE_RAWTEXT
            text_mode = Dispatcher.TEXT
        elif name == "noscript" and not builder.scripting_flag:
            builder.reconstruct_afe(source_start)
        elif name in ("noscript", "noembed"):
            tokenizer_state = Tokenizer.STATE_RAWTEXT
            text_mode = Dispatcher.TEXT
        elif name == "select":
            builder.reconstruct_afe(source_start)
            builder.frameset_ok = False
            if dispatcher.is_in_table_mode():
                mode = Dispatcher.IN_SELECT_IN_TABLE
            else:
                mode = Dispatcher.IN_SELECT
        elif name in ("optgroup", "option"):
            if stack.current.html_name == "option":
                builder.pop(source_start, 0)
            builder.reconstruct_afe(source_start)
        elif name in ("rb", "rtc"):
            if stack.is_in_scope("ruby"):
                builder.generate_implied_end_tags(None, source_start)
                if stack.current.html_name != "ruby":
                    builder.error(f"<{name}> is not a child of <ruby>", source_start)
        elif name in ("rp", "rt"):
            if stack.is_in_scope("ruby"):
                builder.generate_implied_end_tags("rtc", source_start)
                if stack.current.html_name not in ("ruby", "rtc"):
                    builder.error(f"<{name}> is not a child of <ruby> or <rtc>", source_start)
        elif name == "math":
            builder.reconstruct_afe(source_start)
            attrs = ForeignAttributes(attrs, "math")
            dispatcher.ack = True
            builder.insert_foreign(HTMLData.NS_MATHML, "math", attrs, self_close, source_start, source_length)
            return
        elif name == "svg":
            builder.reconstruct_afe(source_start)
            attrs = ForeignAttributes(attrs, "svg")
            dispatcher.ack = True
            builder.insert_foreign(HTMLData.NS_SVG, "svg", attrs, self_close, source_start, source_length)
            return
        elif name in _INVALID_IN_BODY_START_TAGS:
            builder.error(f"{name} is invalid in body mode", source_start)
            return
        else:
            builder.reconstruct_afe(source_start)

        # Generic element insertion, for all cases that didn't return above
        element = builder.insert_element(name, attrs, void, source_start, source_length)
        if is_new_afe:
            builder.afe.push(element)
        if tokenizer_state is not None:
            builder.tokenizer.switch_state(tokenizer_state, name)
        if mode is not None:
            dispatcher.switch_mode(mode)
        elif text_mode is not None:
            dispatcher.switch_and_save(text_mode)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "template":
            dispatcher.in_head.end_tag(name, source_start, source_length)
        elif name == "body":
            if not stack.is_in_scope("body"):
                builder.error("</body> has no matching start tag in scope", source_start)
                return
            builder.check_unclosed(_IMPLICIT_CLOSE, source_start)
            dispatcher.switch_mode(Dispatcher.AFTER_BODY)
        elif name == "html":
            if not stack.is_in_scope("body"):
                builder.error("</html> found in body mode but the body is not in scope", source_start)
                return
            builder.check_unclosed(_IMPLICIT_CLOSE, source_start)
            dispatcher.switch_mode(Dispatcher.AFTER_BODY).end_tag(name, source_start, source_length)
        elif name in _BLOCK_END_TAGS:
            if not stack.is_in_scope(name):
                builder.error(f"unmatched </{name}>, ignoring", source_start)
                return
            builder.generate_implied_end_tags_and_pop(name, source_start, source_length)
        elif name == "form":
            if not stack.has_template():
                node = builder.form_element
                builder.form_element = None
                if node is None:
                    builder.error("found </form> when there is no open form element", source_start)
                    return
                if not stack.is_element_in_scope(node):
                    builder.error("found </form> when there is no form in scope", source_start)
                    return
                builder.generate_implied_end_tags(None, source_start)
                if stack.current is node:
                    builder.pop(source_start, source_length)
                else:
                    builder.error("found </form> when there are tags open which cannot be closed automatically",
                                  source_start)
                    stack.remove(node)
                    # FIXME cannot garbage collect in Serializer since children
                    # of the form are still in the stack
                    # $builder->handler->endTag( $node, $sourceStart, $sourceLength );
            else:
                if not stack.is_in_scope("form"):
                    builder.error("found </form> when there is no form in scope", source_start)
                    return
                builder.generate_implied_end_tags_and_pop("form", source_start, source_length)
        elif name == "p":
            if not stack.is_in_button_scope("p"):
                builder.error("found </p> when there is no p in scope", source_start)
                builder.insert_element("p", PlainAttributes(), False, source_start, 0)
                builder.pop(source_start, source_length)
                return
            builder.generate_implied_end_tags_and_pop("p", source_start, source_length)
        elif name == "li":
            if not stack.is_in_list_scope("li"):
                builder.error("found </li> when there is no li in scope, ignoring", source_start)
                return
            builder.generate_implied_end_tags_and_pop("li", source_start, source_length)
        elif name in ("dd", "dt"):
            if not stack.is_in_scope(name):
                builder.error(f"found </{name}> when there is no {name} in scope, ignoring", source_start)
                return
            builder.generate_implied_end_tags_and_pop(name, source_start, source_length)
        elif name in _HEADING_NAMES:
            if not stack.is_one_of_set_in_scope(_HEADING_NAMES_ORDERED):
                builder.error(f"found </{name}> when there is no heading tag in scope, ignoring", source_start)
                return
            builder.generate_implied_end_tags(None, source_start)
            if stack.current.html_name != name:
                builder.error(f"end tag </{name}> assumed to close non-matching heading tag", source_start)
            builder.pop_all_up_to_names(_HEADING_NAMES, source_start, source_length)
        elif name in _FORMATTING_END_TAGS:
            builder.adoption_agency(name, source_start, source_length)
        elif name in ("applet", "marquee", "object"):
            if not stack.is_in_scope(name):
                builder.error(f"found </{name}> when there is no {name} in scope", source_start)
                return
            builder.generate_implied_end_tags(None, source_start)
            if stack.current.html_name != name:
                builder.error(f"found </{name}> when there are tags open which cannot be implicitly closed, "
                              "closing them anyway", source_start)
            builder.pop_all_up_to_name(name, source_start, source_length)
            builder.afe.clear_to_marker()
        elif name == "br":
            builder.error("end tag </br> is invalid, assuming start tag", source_start)
            self.start_tag(name, PlainAttributes(), False, source_start, source_length)
        else:
            builder.any_other_end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.builder.check_unclosed(_END_DOCUMENT_ALLOWED, pos)
        if not self.dispatcher.template_mode_stack.is_empty():
            self.dispatcher.in_template.end_document(pos)
        else:
            self.builder.stop_parsing(pos)


# (The heading names in PHP's array order, for isOneOfSetInScope())
_HEADING_NAMES_ORDERED = ("h1", "h2", "h3", "h4", "h5", "h6")


class Text(InsertionMode):
    """The "text" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.builder.insert_characters(text, start, length, source_start, source_length)

    def end_document(self, pos):
        self.builder.error("unexpected end of input in text mode", pos)
        self.builder.pop(pos, 0)
        self.dispatcher.restore_mode().end_document(pos)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        raise TreeBuilderError("unexpected token")

    def end_tag(self, name, source_start, source_length):
        # I think this is complete if we have no support for executing scripts
        self.builder.pop(source_start, source_length)
        self.dispatcher.restore_mode()


class InPre(InsertionMode):
    """This is not a tree builder state in the spec. I added it to handle the "next token" references in
    pre/listing. The specified mode for parsing the pre/listing is saved before entering this mode. This mode checks
    if the first token is a newline, and then switches to the correct mode regardless."""

    def characters(self, text, start, length, source_start, source_length):
        if length > 0 and text[start] == "\n":
            start += 1
            length -= 1
            source_start += 1
            source_length -= 1
        mode = self.dispatcher.restore_mode()
        if length:
            mode.characters(text, start, length, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.restore_mode().end_document(pos)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        self.dispatcher.restore_mode().start_tag(name, attrs, self_close, source_start, source_length)

    def end_tag(self, name, source_start, source_length):
        self.dispatcher.restore_mode().end_tag(name, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.dispatcher.restore_mode().doctype(name, public, system, quirks, source_start, source_length)

    def comment(self, text, source_start, source_length):
        self.dispatcher.restore_mode().comment(text, source_start, source_length)


class InTextarea(InsertionMode):
    """This is not a tree builder state in the spec. I added it to handle the "next token" references in textarea.
    If the first token is a newline, it is ignored. Then we switch the dispatcher to the "text" mode regardless,
    which is the correct mode for parsing textarea elements."""

    def characters(self, text, start, length, source_start, source_length):
        if length > 0 and text[start] == "\n":
            # Ignore initial line break
            start += 1
            length -= 1
            source_start += 1
            source_length -= 1
        mode = self.dispatcher.switch_mode(Dispatcher.TEXT)
        if length:
            mode.characters(text, start, length, source_start, source_length)

    def end_document(self, pos):
        self.dispatcher.switch_mode(Dispatcher.TEXT).end_document(pos)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        self.dispatcher.switch_mode(Dispatcher.TEXT).start_tag(name, attrs, self_close, source_start,
                                                               source_length)

    def end_tag(self, name, source_start, source_length):
        self.dispatcher.switch_mode(Dispatcher.TEXT).end_tag(name, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        self.dispatcher.switch_mode(Dispatcher.TEXT).doctype(name, public, system, quirks, source_start,
                                                             source_length)

    def comment(self, text, source_start, source_length):
        self.dispatcher.switch_mode(Dispatcher.TEXT).comment(text, source_start, source_length)

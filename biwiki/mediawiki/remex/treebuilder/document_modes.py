# Ported from RemexHtml 3.0.2 src/TreeBuilder/Initial.php, BeforeHtml.php, BeforeHead.php, InHead.php,
# InHeadNoscript.php, AfterHead.php, AfterBody.php, AfterAfterBody.php, InFrameset.php, AfterFrameset.php and
# AfterAfterFrameset.php (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license:
# see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
"""The insertion modes around the body: before it, in the head, after it, and the frameset modes."""
from __future__ import annotations

import re

from ..htmldata import HTMLData
from ..tokenizer.attributes import PlainAttributes
from ..tokenizer.tokenizer import Tokenizer
from .dispatcher import Dispatcher
from .insertion_mode import InsertionMode
from .tree_builder import TreeBuilder

_WHITESPACE = "\t\n\f\r "


class Initial(InsertionMode):
    """The "initial" insertion mode"""

    # The doctypes listed in the spec which are allowed without generating a parse error. A 2-d array where each
    # row gives the doctype name, the public identifier and the system identifier.
    _allowed_doctypes = [
        ("html", "-//W3C//DTD HTML 4.0//EN", None),
        ("html", "-//W3C//DTD HTML 4.0//EN", "http://www.w3.org/TR/REC-html40/strict.dtd"),
        ("html", "-//W3C//DTD HTML 4.01//EN", None),
        ("html", "-//W3C//DTD HTML 4.01//EN", "http://www.w3.org/TR/html4/strict.dtd"),
        ("html", "-//W3C//DTD XHTML 1.0 Strict//EN", "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd"),
        ("html", "-//W3C//DTD XHTML 1.1//EN", "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"),
    ]

    _quirks_if_no_system = re.compile(r"-//W3C//DTD HTML 4\.01 Frameset//|-//W3C//DTD HTML 4\.01 Transitional//",
                                      re.I | re.A)
    _limited_quirks = re.compile(r"-//W3C//DTD XHTML 1\.0 Frameset//|-//W3C//DTD XHTML 1\.0 Transitional//",
                                 re.I | re.A)

    def characters(self, text, start, length, source_start, source_length):
        # Ignore whitespace
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part2
        if not length:
            return
        if not self.builder.is_iframe_srcdoc:
            self.error("missing doctype", source_start)
            self.builder.quirks = TreeBuilder.QUIRKS
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HTML).characters(text, start, length, source_start,
                                                                       source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        if not self.builder.is_iframe_srcdoc:
            self.error("missing doctype", source_start)
            self.builder.quirks = TreeBuilder.QUIRKS
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HTML).start_tag(name, attrs, self_close, source_start,
                                                                      source_length)

    def end_tag(self, name, source_start, source_length):
        if not self.builder.is_iframe_srcdoc:
            self.error("missing doctype", source_start)
            self.builder.quirks = TreeBuilder.QUIRKS
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HTML).end_tag(name, source_start, source_length)

    def doctype(self, name, public, system, quirks, source_start, source_length):
        if ((name != "html" or public is not None or (system is not None and system != "about:legacy-compat"))
                and (name, public, system) not in self._allowed_doctypes):
            self.error("invalid doctype", source_start)

        quirks = TreeBuilder.QUIRKS if quirks else TreeBuilder.NO_QUIRKS

        if (name != "html"
                or public == "-//W3O//DTD W3 HTML Strict 3.0//EN//"
                or public == "-/W3C/DTD HTML 4.0 Transitional/EN"
                or public == "HTML"
                or system == "http://www.ibm.com/data/dtd/v11/ibmxhtml1-transitional.dtd"
                or (system is None and self._quirks_if_no_system.match(public or ""))
                or HTMLData.quirkyPrefixRegex.match(public or "")):
            quirks = TreeBuilder.QUIRKS
        elif (not self.builder.is_iframe_srcdoc
              and (self._limited_quirks.match(public or "")
                   or (system is not None and self._quirks_if_no_system.match(public or "")))):
            quirks = TreeBuilder.LIMITED_QUIRKS

        name = name if name is not None else ""
        public = public if public is not None else ""
        system = system if system is not None else ""
        self.builder.doctype(name, public, system, quirks, source_start, source_length)
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HTML)

    def end_document(self, pos):
        if not self.builder.is_iframe_srcdoc:
            self.error("missing doctype", pos)
            self.builder.quirks = TreeBuilder.QUIRKS
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HTML).end_document(pos)


class BeforeHtml(InsertionMode):
    """The "before html" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        # Ignore whitespace
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part2
        if not length:
            return
        # Generate missing <html> tag
        self.builder.insert_element("html", PlainAttributes(), False, source_start, 0)
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HEAD).characters(text, start, length, source_start,
                                                                       source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        if name == "html":
            self.builder.insert_element(name, attrs, False, source_start, source_length)
            self.dispatcher.switch_mode(Dispatcher.BEFORE_HEAD)
        else:
            self.builder.insert_element("html", PlainAttributes(), False, source_start, 0)
            self.dispatcher.switch_mode(Dispatcher.BEFORE_HEAD).start_tag(name, attrs, self_close, source_start,
                                                                          source_length)

    def end_tag(self, name, source_start, source_length):
        if name not in ("head", "body", "html", "br"):
            self.builder.error("end tag not allowed before html", source_start)
            return
        self.builder.insert_element("html", PlainAttributes(), False, source_start, 0)
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HEAD).end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.builder.insert_element("html", PlainAttributes(), False, pos, 0)
        self.dispatcher.switch_mode(Dispatcher.BEFORE_HEAD).end_document(pos)


class BeforeHead(InsertionMode):
    """The "before head" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        # Ignore whitespace
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part2
        if not length:
            return
        # Handle non-whitespace
        self.builder.head_element = self.builder.insert_element("head", PlainAttributes(), False, source_start, 0)
        self.dispatcher.switch_mode(Dispatcher.IN_HEAD).characters(text, start, length, source_start,
                                                                   source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        if name == "html":
            self.dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "head":
            self.builder.head_element = self.builder.insert_element(name, attrs, False, source_start,
                                                                    source_length)
            self.dispatcher.switch_mode(Dispatcher.IN_HEAD)
        else:
            self.builder.head_element = self.builder.insert_element("head", PlainAttributes(), False,
                                                                    source_start, 0)
            self.dispatcher.switch_mode(Dispatcher.IN_HEAD).start_tag(name, attrs, self_close, source_start,
                                                                      source_length)

    def end_tag(self, name, source_start, source_length):
        if name not in ("head", "body", "html", "br"):
            self.builder.error("end tag not allowed before head", source_start)
            return
        self.builder.head_element = self.builder.insert_element("head", PlainAttributes(), False, source_start, 0)
        self.dispatcher.switch_mode(Dispatcher.IN_HEAD).end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.builder.head_element = self.builder.insert_element("head", PlainAttributes(), False, pos, 0)
        self.dispatcher.switch_mode(Dispatcher.IN_HEAD).end_document(pos)


class InHead(InsertionMode):
    """The "in head" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        # Split and insert whitespace
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part1
        if length:
            self.builder.insert_characters(text, start, length, source_start, source_length)
        # Handle non-whitespace specially
        start, length, source_start, source_length = part2
        if not length:
            return
        elt = self.builder.pop(source_start, 0)
        if elt.html_name != "head":
            raise Exception("In head mode but current element is not <head>")
        self.dispatcher.switch_mode(Dispatcher.AFTER_HEAD).characters(text, start, length, source_start,
                                                                      source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        void = False
        tokenizer_state = None
        text_mode = None
        mode = None
        dispatcher = self.dispatcher
        if name == "html":
            self.dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
            return
        elif name in ("base", "basefont", "bgsound", "link"):
            void = True
            dispatcher.ack = True
        elif name == "meta":
            void = True
            dispatcher.ack = True
            # charset handling omitted
        elif name == "title":
            tokenizer_state = Tokenizer.STATE_RCDATA
            text_mode = Dispatcher.TEXT
        elif name in ("noscript", "noframes", "style"):
            if name == "noscript" and not self.builder.scripting_flag:
                mode = Dispatcher.IN_HEAD_NOSCRIPT
            else:
                tokenizer_state = Tokenizer.STATE_RAWTEXT
                text_mode = Dispatcher.TEXT
        elif name == "script":
            tokenizer_state = Tokenizer.STATE_SCRIPT_DATA
            text_mode = Dispatcher.TEXT
        elif name == "template":
            self.builder.afe.insert_marker()
            self.builder.frameset_ok = False
            mode = Dispatcher.IN_TEMPLATE
            self.dispatcher.template_mode_stack.push(Dispatcher.IN_TEMPLATE)
        elif name == "head":
            self.builder.error("unexpected head tag in head, ignoring", source_start)
            return
        else:
            elt = self.builder.pop(source_start, 0)
            if elt.html_name != "head":
                raise Exception("In head mode but current element is not <head>")
            self.dispatcher.switch_mode(Dispatcher.AFTER_HEAD).start_tag(name, attrs, self_close, source_start,
                                                                         source_length)
            return

        # Generic element insertion, for all cases that didn't return above
        self.builder.insert_element(name, attrs, void, source_start, source_length)
        if tokenizer_state is not None:
            self.builder.tokenizer.switch_state(tokenizer_state, name)
        if text_mode is not None:
            self.dispatcher.switch_and_save(text_mode)
        elif mode is not None:
            self.dispatcher.switch_mode(mode)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        if name == "head":
            builder.pop(source_start, source_length)
            self.dispatcher.switch_mode(Dispatcher.AFTER_HEAD)
        elif name in ("body", "html", "br"):
            builder.pop(source_start, 0)
            self.dispatcher.switch_mode(Dispatcher.AFTER_HEAD).end_tag(name, source_start, source_length)
        elif name == "template":
            if not stack.has_template():
                builder.error("found </template> but there is no open template, ignoring", source_start)
                return
            builder.generate_implied_end_tags_thoroughly(source_start)
            if stack.current.html_name != "template":
                builder.error("found </template> when other tags are still open", source_start)
            builder.pop_all_up_to_name("template", source_start, source_length)
            builder.afe.clear_to_marker()
            self.dispatcher.template_mode_stack.pop()
            self.dispatcher.reset()
        else:
            builder.error(f"ignoring </{name}> in head", source_start)

    def end_document(self, pos):
        self.builder.pop(pos, 0)
        self.dispatcher.switch_mode(Dispatcher.AFTER_HEAD).end_document(pos)


class InHeadNoscript(InsertionMode):
    """The "in head noscript" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        # Insert whitespace
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part1
        if length:
            dispatcher.in_head.characters(text, start, length, source_start, source_length)
        # Switch mode on non-whitespace
        start, length, source_start, source_length = part2
        if length:
            builder.error("unexpected non-whitespace character in head in noscript, closing noscript",
                          source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_HEAD).characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name in ("basefont", "bgsound", "link", "meta", "noframes", "style"):
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        elif name in ("head", "noscript"):
            builder.error(f"unexpected <{name}> in head in noscript, ignoring", source_start)
            return
        else:
            builder.error(f"unexpected <{name}> in head in noscript, closing noscript", source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_HEAD).start_tag(name, attrs, self_close, source_start,
                                                                 source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "noscript":
            builder.pop(source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_HEAD)
        elif name == "br":
            builder.error("unexpected </br> in head in noscript, closing noscript", source_start)
            builder.pop(source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_HEAD).end_tag(name, source_start, source_length)
        else:
            builder.error(f"unexpected </{name}> in head in noscript, ignoring", source_start)
            return

    def end_document(self, pos):
        self.builder.error("unexpected end-of-file in head in noscript", pos)
        self.builder.pop(pos, 0)
        self.dispatcher.switch_mode(Dispatcher.IN_HEAD).end_document(pos)


class AfterHead(InsertionMode):
    """The "after head" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        # Insert whitespace
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part1
        if length:
            builder.insert_characters(text, start, length, source_start, source_length)
        # Switch mode on non-whitespace
        start, length, source_start, source_length = part2
        if length:
            builder.insert_element("body", PlainAttributes(), False, source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_BODY).characters(text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "body":
            builder.insert_element(name, attrs, False, source_start, source_length)
            builder.frameset_ok = False
            dispatcher.switch_mode(Dispatcher.IN_BODY)
        elif name == "frameset":
            builder.insert_element(name, attrs, False, source_start, source_length)
            dispatcher.switch_mode(Dispatcher.IN_FRAMESET)
        elif name in ("base", "basefont", "bgsound", "link", "meta", "noframes", "script", "style", "template",
                      "title"):
            builder.error(f"unexpected <{name}> after </head>, accepting", source_start)
            stack.push(builder.head_element)
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
            stack.remove(builder.head_element)
        elif name == "head":
            builder.error("unexpected <head> after </head>, ignoring", source_start)
            return
        else:
            builder.insert_element("body", PlainAttributes(), False, source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_BODY).start_tag(name, attrs, self_close, source_start,
                                                                 source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "template":
            dispatcher.in_head.end_tag(name, source_start, source_length)
        elif name in ("body", "html", "br"):
            builder.insert_element("body", PlainAttributes(), False, source_start, 0)
            dispatcher.switch_mode(Dispatcher.IN_BODY).end_tag(name, source_start, source_length)
        else:
            builder.error(f"unexpected </{name}> after head, ignoring", source_start)
            return

    def end_document(self, pos):
        self.builder.insert_element("body", PlainAttributes(), False, pos, 0)
        self.dispatcher.switch_mode(Dispatcher.IN_BODY).end_document(pos)


class AfterBody(InsertionMode):
    """The "after body" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part1
        if length:
            self.dispatcher.in_body.characters(text, start, length, source_start, source_length)
        start, length, source_start, source_length = part2
        self.builder.error("unexpected non-whitespace character after body", source_start)
        self.dispatcher.switch_mode(Dispatcher.IN_BODY).characters(text, start, length, source_start,
                                                                   source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            builder.error("unexpected start tag after body", source_start)
            dispatcher.switch_mode(Dispatcher.IN_BODY).start_tag(name, attrs, self_close, source_start,
                                                                 source_length)

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            if builder.is_fragment:
                builder.error("unexpected </html> in fragment", source_start)
                return
            dispatcher.switch_mode(Dispatcher.AFTER_AFTER_BODY)
        else:
            builder.error("unexpected end tag after body", source_start)
            dispatcher.switch_mode(Dispatcher.IN_BODY).end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.builder.stop_parsing(pos)

    def comment(self, text, source_start, source_length):
        self.builder.comment((TreeBuilder.UNDER, self.builder.stack.item(0)), text, source_start, source_length)


class AfterAfterBody(InsertionMode):
    """The "after after body" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        part1, part2 = self.split_initial_match(True, _WHITESPACE, text, start, length, source_start, source_length)
        start, length, source_start, source_length = part1
        if length:
            self.builder.insert_characters(text, start, length, source_start, source_length)
        start, length, source_start, source_length = part2
        if not length:
            return
        self.builder.error("unexpected non-whitespace characters after after body", source_start)
        self.dispatcher.switch_mode(Dispatcher.IN_BODY).characters(text, start, length, source_start,
                                                                   source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            builder.error("unexpected start tag after after body", source_start)
            dispatcher.switch_mode(Dispatcher.IN_BODY).start_tag(name, attrs, self_close, source_start,
                                                                 source_length)

    def end_tag(self, name, source_start, source_length):
        self.builder.error("unexpected end tag after after body", source_start)
        self.dispatcher.switch_mode(Dispatcher.IN_BODY).end_tag(name, source_start, source_length)

    def end_document(self, pos):
        self.builder.stop_parsing(pos)

    def comment(self, text, source_start, source_length):
        self.builder.comment((TreeBuilder.ROOT, None), text, source_start, source_length)


class InFrameset(InsertionMode):
    """The "in frameset" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.handle_frameset_whitespace(False, text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "frameset":
            builder.insert_element(name, attrs, False, source_start, source_length)
        elif name == "frame":
            dispatcher.ack = True
            builder.insert_element(name, attrs, True, source_start, source_length)
        elif name == "noframes":
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            builder.error("unexpected start tag in frameset, ignoring", source_start)
            return

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        stack = builder.stack
        dispatcher = self.dispatcher
        if name == "frameset":
            if stack.current.html_name == "html":
                builder.error("unexpected </frameset> in fragment context", source_start)
                return
            builder.pop(source_start, source_length)
            # (sic: RemexHtml compares the current Element object with the string 'frameset', which is always
            # unequal)
            if not builder.is_fragment:
                dispatcher.switch_mode(Dispatcher.AFTER_FRAMESET)
        else:
            builder.error(f"unexpected </{name}> in frameset", source_start)
            return

    def end_document(self, pos):
        builder = self.builder
        stack = builder.stack
        if stack.current.html_name != "html":
            builder.error("unexpected end of file in frameset mode", pos)
        builder.stop_parsing(pos)


class AfterFrameset(InsertionMode):
    """The "after frameset" insertion mode"""

    def characters(self, text, start, length, source_start, source_length):
        self.handle_frameset_whitespace(False, text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "noframes":
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            builder.error("unexpected start tag after frameset, ignoring", source_start)
            return

    def end_tag(self, name, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.switch_mode(Dispatcher.AFTER_AFTER_FRAMESET)
        else:
            builder.error("unexpected end tag after frameset, ignoring", source_start)

    def end_document(self, pos):
        self.builder.stop_parsing(pos)


class AfterAfterFrameset(InsertionMode):
    """The "after after frameset" insertion mode."""

    def characters(self, text, start, length, source_start, source_length):
        self.handle_frameset_whitespace(True, text, start, length, source_start, source_length)

    def start_tag(self, name, attrs, self_close, source_start, source_length):
        builder = self.builder
        dispatcher = self.dispatcher
        if name == "html":
            dispatcher.in_body.start_tag(name, attrs, self_close, source_start, source_length)
        elif name == "noframes":
            dispatcher.in_head.start_tag(name, attrs, self_close, source_start, source_length)
        else:
            builder.error("unexpected start tag after after frameset", source_start)

    def end_tag(self, name, source_start, source_length):
        self.builder.error("unexpected end tag after after frameset", source_start)

    def end_document(self, pos):
        self.builder.stop_parsing(pos)

    def comment(self, text, source_start, source_length):
        self.builder.comment((TreeBuilder.ROOT, None), text, source_start, source_length)

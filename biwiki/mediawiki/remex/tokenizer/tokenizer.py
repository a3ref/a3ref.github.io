# Ported from RemexHtml 3.0.2 src/Tokenizer/Tokenizer.php and TokenizerError.php
# (https://github.com/wikimedia/remex-html), (C) 2016 Wikimedia Foundation. MIT license: see
# biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python. The PCRE patterns are kept, with these
# translations: possessive quantifiers are written as plain greedy ones where nothing after them can fail (so the
# first, greedy attempt is the match either way; Python before 3.11 has no possessive quantifiers), "(?i)" inside
# the DOCTYPE group became a scoped "(?i:...)", "\z" is "\Z", and re.ASCII keeps case-insensitive matching to
# ASCII letters as PCRE without /u does. The named entity alternation of the character reference regex is
# htmldata.named_entity_match(). Offsets count code points instead of bytes.
"""HTML 5 tokenizer"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from .._php import strcspn, strspn, strtolower
from ..htmldata import HTMLData, named_entity_match
from .attributes import Attributes, LazyAttributes, PlainAttributes
from .token_handler import TokenHandler


class TokenizerError(Exception):
    pass


# Match indices for the data state regex
MD_END_TAG_OPEN = 1
MD_TAG_NAME = 2
MD_TAG_AFTER_LOWERCASE = 3
MD_COMMENT = 4
MD_COMMENT_INNER = 5
MD_COMMENT_END = 6
MD_DOCTYPE = 7
MD_DT_NAME_WS = 8
MD_DT_NAME = 9
MD_DT_PUBLIC_WS = 10
MD_DT_PUBLIC_DQ = 11
MD_DT_PUBLIC_SQ = 12
MD_DT_PUBSYS_WS = 13
MD_DT_PUBSYS_DQ = 14
MD_DT_PUBSYS_SQ = 15
MD_DT_SYSTEM_WS = 16
MD_DT_SYSTEM_DQ = 17
MD_DT_SYSTEM_SQ = 18
MD_DT_BOGUS = 19
MD_DT_END = 20
MD_CDATA = 21
MD_BOGUS_COMMENT = 22

# Match indices for the attribute regex
MA_SLASH = 1
MA_NAME = 2
MA_SIMPLE_NAME = 3
MA_DQUOTED = 4
MA_DQUOTED_CHARREF = 5
MA_DQUOTED_UNSIMPLE = 6
MA_SQUOTED = 7
MA_SQUOTED_CHARREF = 8
MA_SQUOTED_UNSIMPLE = 9
MA_UNQUOTED = 10
MA_UNQUOTED_UNSIMPLE = 11

# Characters
REPLACEMENT_CHAR = "�"
BYTE_ORDER_MARK = "﻿"

# A list of "common well-behaved entities", used to optimize fast paths
_COMMON_ENTITIES = {
    "&amp;": "&",
    "&apos;": "'",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&nbsp;": " ",
}
_COMMON_ENTITY_RE = re.compile(r"&(?:amp|apos|lt|gt|quot|nbsp);")


def _strtr_common_entities(text: str) -> str:
    """strtr( $text, self::$commonEntities )"""
    return _COMMON_ENTITY_RE.sub(lambda m: _COMMON_ENTITIES[m.group(0)], text)


# Raise parse errors for any control characters: "C0 controls" (u0000 - u001F) but not "ASCII whitespace"
# (u0009, u000A, u000C, u000D, u0020) or NULL (u0000), "Controls" other than C0 controls (u007F - u009F), and what
# the HTML spec calls "noncharacters"
_CONTROL_CHAR_RE = re.compile("[\x01-\x08\x0b\x0e-\x1f\x7f-\x9f﷐-﷯￾￿"
                              + "".join(chr(plane * 0x10000 + 0xfffe) + chr(plane * 0x10000 + 0xffff)
                                        for plane in range(1, 17))
                              + "]")

_DATA_STATE_RE = re.compile(r"""
    <
    (?:
        ( /? )                        # 1. End tag open

        (                             # 2. Tag name
            # Try to match the ASCII letter required for the start of a start
            # or end tag. If this fails, a slash matched above can be
            # backtracked and then fed into the bogus comment alternative below.
            # As an optimization, notice if the tag is all-lowercase;
            # we can skip strtolower and null handling in that case.
            (?:
                [a-z]+
                # Portion after initial all-lowercase prefix
                ( [^\t\n\f />]* ) |

                # Capture initial uppercase letter
                [A-Z]
                # Then capture the rest of the tag name
                [^\t\n\f />]*
            )
        )

        |

        # Comment
        !--
        (                             # 4. Comment match detector
            > | -> | # Invalid short close
            (                         # 5. Comment contents
                (?:
                    (?! --> )
                    (?! --!> )
                    (?! --! \Z )
                    (?! -- \Z )
                    (?! - \Z )
                    .
                )*
            )
            (                         # 6. Comment close
                --> |   # Normal close
                --!> |  # Comment end bang
                --! |   # EOF in comment end bang state
                -- |    # EOF in comment end state
                -  |    # EOF in comment end dash state
                        # EOF in comment state
            )
        ) |
        ( (?i:                        # 7. Doctype
            ! DOCTYPE

            # There must be at least one whitespace character to suppress
            # a parse error, but if there isn't one, this is still a
            # DOCTYPE. There is no way for the DOCTYPE string to end up
            # as a character node, the DOCTYPE subexpression must always
            # wholly match if we matched up to this point.

            ( [\t\n\f ]* )            # 8. Required whitespace
            ( [^\t\n\f >]* )          # 9. DOCTYPE name
            [\t\n\f ]*
            (?:
                # After DOCTYPE name state
                PUBLIC
                ( [\t\n\f ]* )            # 10. Required whitespace
                (?:
                    " ( [^">]* ) "? |     # 11. Double-quoted identifier
                    ' ( [^'>]* ) '? |     # 12. Single-quoted identifier
                    # Non-match: bogus
                )
                (?:
                    # After DOCTYPE public identifier state
                    # Assert quoted identifier before here
                    (?<= " | ' )
                    ( [\t\n\f ]* )            # 13. Required whitespace
                    (?:
                        " ( [^">]* ) "? |     # 14. Double-quoted identifier
                        ' ( [^'>]* ) '? |     # 15. Single-quoted identifier
                        # Non-match: no system ID
                    )
                )?
                |
                SYSTEM
                ( [\t\n\f ]* )            # 16. Required whitespace
                (?:
                    " ( [^">]* ) "? |     # 17. Double-quoted identifier
                    ' ( [^'>]* ) '? |     # 18. Single-quoted identifier
                    # Non-match: bogus
                )
                |  # No keyword is OK
            )
            [\t\n\f ]*
            ( [^>]* )                 # 19. Bogus DOCTYPE
            ( >? )                    # 20. End of DOCTYPE
        ) ) |
        ( ! \[CDATA\[ ) |             # 21. CDATA section
        ( [!?/] [^>]* ) >?            # 22. Bogus comment

        # Anything else: parse error and emit literal less-than sign.
        # We will let the match fail at this position and later check
        # for less-than signs in the resulting text node.
    )
    """, re.X | re.S | re.A)

_DIFFICULT_RE = re.compile("[<&\0]")

_CHARREF_NUMERIC_RE = re.compile(r"""
    \# (?:
        0*([0-9]+)           |  # 2. decimal
        [xX]0*([0-9A-Fa-f]+)    # 3. hexadecimal
    )
    ( ; ) ?                     # 4. semicolon
    """, re.X)
_CHARREF_INVALID_RE = re.compile(r"[a-zA-Z0-9]+;")
_ATTRIBUTE_SUFFIX = frozenset("=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

_DISALLOWED_CODEPOINTS = frozenset([0x000B, 0xFFFE, 0xFFFF] + [plane * 0x10000 + low for plane in range(1, 17)
                                                                for low in (0xFFFE, 0xFFFF)])

_ATTRIB_RE = re.compile(r"""
    [\t\n\f ]*   # Ignored whitespace before attribute name
    (?! /> )     # Do not consume self-closing end of tag
    (?! > )      # Do not consume normal closing bracket

    (?:
        # Before attribute name state
        # A bare slash at this point, not part of a self-closing end tag, is
        # consumed and ignored (with a parse error), returning to the before
        # attribute name state.
        ( / ) |    # 1. Bare slash

        # Attribute name state
        # Note that the first character can be an equals sign, this is a parse error
        # but still generates an attribute called "=". Thus the only way the match
        # could fail here is due to EOF.

        (                       # 2. Attribute name
            (?:
                ( [-a-z]+ ) |   # 3. Optional "simple" prefix
                [^\t\n\f />]
            )
            [^\t\n\f =/>]*
        )

        # After attribute name state
        [\t\n\f ]*

        (?:
            =
            # Before attribute value state
            # Ignore whitespace
            [\t\n\f ]*
            (?:
                # If an end-quote is omitted, the attribute will run to the end of the
                # string, leaving no closing bracket. So the caller will detect the
                # unexpected EOF and will not emit the tag, which is correct.
                " (                     # 4. Double-quoted attribute values
                    [^"&\r\0]*          #    Simple prefix
                    (                   # 5. Perhaps some simple entities
                        (?: &(?:amp|apos|lt|gt|quot|nbsp); | [^"&\r\0] )*
                    )
                    ( [^"]* )           # 6. Unsimple suffix
                ) "? |
                ' (                     # 7. Single-quoted attribute value
                    [^'&\r\0]*          #    Simple prefix
                    (                   # 8. Perhaps some simple entities
                        (?: &(?:amp|apos|lt|gt|quot|nbsp); | [^'&\r\0] )*
                    )
                    ( [^']* )           # 9. Unsimple suffix
                ) '? |
                (                       # 10. Unquoted attribute value
                    [^\t\n\f >\r"&'\0=<`]* #  Simple prefix
                    ( [^\t\n\f >]* )    # 11. Unsimple suffix
                )
            )
            # Or nothing: an attribute with an empty value. The attribute name was
            # terminated by a slash, closing bracket or EOF
            |
        )
    )
    # The /A modifier causes preg_match_all to give contiguous chunks
    """, re.X)

_AFTER_ATTRIBUTE_VALUE = frozenset("\t\n\f />")


class Tokenizer:
    """HTML 5 tokenizer

    Based on the W3C recommendation as published 01 November 2016:
    https://www.w3.org/TR/2016/REC-html51-20161101/
    """

    # States
    STATE_START = 1
    STATE_DATA = 2
    STATE_RCDATA = 3
    STATE_RAWTEXT = 4
    STATE_SCRIPT_DATA = 5
    STATE_PLAINTEXT = 6
    STATE_EOF = 7
    STATE_CURRENT = 8

    REPLACEMENT_CHAR = REPLACEMENT_CHAR
    BYTE_ORDER_MARK = BYTE_ORDER_MARK

    def __init__(self, listener: TokenHandler, text: str, options: Optional[dict[str, Any]] = None):
        """``listener``: the object which receives token events; ``text``: the text to tokenize; ``options``:
        - ignoreErrors: True to improve performance by ignoring errors. The token stream should still be the same,
          except that error() won't be called.
        - ignoreCharRefs: True to ignore character references. Character tokens will contain the unexpanded
          character references, and no errors related to invalid character references will be raised. Performance
          will be improved. This is not compliant behaviour.
        - ignoreNulls: True to ignore NULL bytes in the input stream, instead of raising errors and converting them
          to U+FFFD as is usually required by the spec.
        - skipPreprocess: True to skip the "preprocessing the input stream" stage, which normalizes line endings
          and raises errors on certain control characters. Advisable if the input stream is already appropriately
          normalized.
        - scriptingFlag: True if the scripting flag is enabled. Default true. Setting this to false cause the
          contents of <noscript> elements to be processed as normal content. The scriptingFlag option in the
          TreeBuilder should be set to the same value.
        """
        options = options or {}
        self.listener = listener
        self.text = text
        self.pos = 0
        self.preprocessed = False
        self.length = len(text)
        self.ignore_errors = bool(options.get("ignoreErrors"))
        self.ignore_char_refs = bool(options.get("ignoreCharRefs"))
        self.ignore_nulls = bool(options.get("ignoreNulls"))
        self.skip_preprocess = bool(options.get("skipPreprocess"))
        scripting_flag = options.get("scriptingFlag")
        self.scripting_flag = True if scripting_flag is None else scripting_flag
        self.appropriate_end_tag: Optional[str] = None
        self.state: Optional[int] = None
        self.enable_cdata_callback: Optional[Callable[[], bool]] = None
        self.fragment_namespace: Optional[str] = None
        self.fragment_name: Optional[str] = None

    def set_enable_cdata_callback(self, cb: Optional[Callable[[], bool]]) -> None:
        self.enable_cdata_callback = cb

    def execute(self, options: Optional[dict[str, Any]] = None) -> None:
        """Run the tokenizer on the whole input stream. This is the normal entry point.

        ``options``: an associative array of options:
        - state : One of the STATE_* constants, a state in which to start.
        - appropriateEndTag : The "appropriate end tag", which needs to be set if entering one of the raw text
          states.
        - fragmentNamespace : The fragment namespace
        - fragmentName : The fragment tag name
        """
        options = options or {}
        if options.get("state") is not None:
            self.state = options["state"]
        else:
            self.state = self.STATE_START

        if options.get("fragmentNamespace") is not None:
            self.set_fragment_context(options["fragmentNamespace"], options["fragmentName"])
        else:
            self.fragment_namespace = None
            self.fragment_name = None
        self.appropriate_end_tag = options.get("appropriateEndTag")
        self.preprocess()
        self.listener.start_document(self, self.fragment_namespace, self.fragment_name)

        self.execute_internal(True)

    def get_preprocessed_text(self) -> str:
        """Get the preprocessed input text. Source offsets in event parameters are relative to this string. If
        skipPreprocess was specified, this will be the same as the input string."""
        self.preprocess()
        return self.text

    def switch_state(self, state: int, appropriate_end_tag: Optional[str]) -> None:
        """Change the state of the tokenizer during parsing. This for use by the tree builder to switch the
        tokenizer into one of the raw text states."""
        self.state = state
        self.appropriate_end_tag = appropriate_end_tag

    def set_fragment_context(self, namespace: Optional[str], tag_name: str) -> None:
        """Initialize the tokenizer for fragment parsing"""
        self.fragment_namespace = namespace
        self.fragment_name = tag_name

        if (namespace or "") != "" and namespace != HTMLData.NS_HTML:
            return

        if tag_name in ("title", "textarea"):
            self.state = self.STATE_RCDATA
        elif tag_name in ("style", "xmp", "iframe", "noembed", "noframes"):
            self.state = self.STATE_RAWTEXT
        elif tag_name == "script":
            self.state = self.STATE_SCRIPT_DATA
        elif tag_name == "noscript":
            if self.scripting_flag:
                self.state = self.STATE_RAWTEXT
        elif tag_name == "plaintext":
            self.state = self.STATE_PLAINTEXT

    def begin_stepping(self) -> None:
        """Notify the tokenizer that the document will be tokenized by repeated step() calls. This must be called
        once only, before the first call to step()."""
        self.state = self.STATE_START
        self.preprocess()
        self.listener.start_document(self, None, None)

    def step(self) -> bool:
        """Tokenize a minimum amount of text from the input stream, and emit the resulting events. Returns True if
        the input continues and step() should be called again, false on EOF"""
        if self.state is None:
            self.fatal("beginStepping() must be called before step()")
        return self.execute_internal(False)

    def preprocess(self) -> None:
        """Preprocess the input text, if it hasn't been done already. (sic: RemexHtml never sets $this->preprocessed,
        so the errors are raised again on each call of getPreprocessedText().)"""
        if self.preprocessed or self.skip_preprocess:
            return

        # Normalize line endings
        if "\r" in self.text:
            self.text = re.sub(r"\r\n?", "\n", self.text)
            self.length = len(self.text)

        # Raise parse errors for any control characters
        if not self.ignore_errors:
            for m in _CONTROL_CHAR_RE.finditer(self.text):
                self.error("disallowed control character", m.start())

    def execute_internal(self, loop: bool) -> bool:
        """The main state machine, the common implementation of step() and execute(). ``loop``: set to true to loop
        until finished, false to step once. Returns True if the input continues, false on EOF"""
        eof = False

        while True:
            state = self.state
            if state == self.STATE_DATA:
                self.state = self.data_state(loop)
            elif state == self.STATE_RCDATA:
                self.state = self.text_element_state(False)
            elif state == self.STATE_RAWTEXT:
                self.state = self.text_element_state(True)
            elif state == self.STATE_SCRIPT_DATA:
                self.state = self.script_data_state()
            elif state == self.STATE_PLAINTEXT:
                self.state = self.plaintext_state()
            elif state == self.STATE_START:
                self.state = self.STATE_DATA
            elif state == self.STATE_EOF:
                self.listener.end_document(self.length)
                eof = True
                break
            else:
                self.fatal("invalid state")
            if not loop:
                break

        return not eof

    def data_state(self, loop: bool) -> int:
        """Consume input text starting from the "data state". ``loop``: true to loop while still in the data
        state, false to process a single less-than sign. Returns the next state index"""
        text = self.text
        next_state = self.STATE_DATA
        while True:
            # As an optimization, quick scan ahead to the first "difficult"
            # character
            m = _DIFFICULT_RE.search(text, self.pos)
            npos = m.start() if m else self.length
            # While the "difficult" section is in fact a simple entity, keep
            # skipping ahead.
            mpos = npos
            while True:
                m = _COMMON_ENTITY_RE.match(text, mpos)
                if not m:
                    break
                mpos = m.end()
                m = _DIFFICULT_RE.search(text, mpos)
                mpos = m.start() if m else self.length
            m = _DATA_STATE_RE.search(text, mpos)
            if not m:
                # Text runs to end
                data_is_simple = npos == self.length
                data_has_simple_refs = mpos == self.length
                self.emit_data_range(self.pos, self.length - self.pos, data_is_simple, data_has_simple_refs)
                self.pos = self.length
                next_state = self.STATE_EOF
                break

            start_pos = m.start()
            data_is_simple = npos == start_pos
            data_has_simple_refs = mpos == start_pos
            tag_name = m.group(MD_TAG_NAME) or ""

            self.emit_data_range(self.pos, start_pos - self.pos, data_is_simple, data_has_simple_refs)
            self.pos = start_pos
            next_pos = m.end()

            is_cdata_match = m.start(MD_CDATA) >= 0

            if tag_name:
                # Tag
                is_end_tag = bool(m.group(MD_END_TAG_OPEN))
                is_all_lower = m.group(MD_TAG_AFTER_LOWERCASE) == ""
                if not is_all_lower:
                    # As an optimization, we skip these steps for the common
                    # case of an all-lowercase tag name
                    if not self.ignore_nulls:
                        tag_name = self.handle_nulls(tag_name, m.start(MD_TAG_NAME))
                    tag_name = strtolower(tag_name)
                self.pos = next_pos
                if next_pos < self.length and text[next_pos] == ">":
                    # "Simple tag" optimization; skip attribute parsing and
                    # stay in this state
                    next_pos += 1
                    self.pos = next_pos
                    if is_end_tag:
                        self.listener.end_tag(tag_name, start_pos, next_pos - start_pos)
                    else:
                        self.listener.start_tag(tag_name, PlainAttributes(), False, start_pos, next_pos - start_pos)
                    # Respect any state switch imposed by the parser
                    next_state = self.state
                    if loop and next_state == self.STATE_DATA:
                        continue
                    break
                next_state = self.handle_attribs_and_close(self.STATE_DATA, tag_name, is_end_tag, start_pos)
                next_pos = self.pos
                if next_state == self.STATE_EOF:
                    break

                # Respect any state switch imposed by the parser
                next_state = self.state

            elif m.start(MD_COMMENT) >= 0:
                # Comment
                self.interpret_comment_matches(m)
            elif m.start(MD_DOCTYPE) >= 0:
                # DOCTYPE
                self.interpret_doctype_matches(m)
            elif is_cdata_match:
                # CDATA
                if self.enable_cdata_callback and self.enable_cdata_callback():
                    self.pos += len(m.group(MD_CDATA)) + 1
                    end_pos = text.find("]]>", self.pos)
                    if end_pos == -1:
                        self.emit_cdata_range(self.pos, self.length - self.pos, start_pos, self.length - start_pos)
                        self.pos = self.length
                        next_state = self.STATE_EOF
                        break
                    else:
                        outer_end_pos = end_pos + len("]]>")
                        self.emit_cdata_range(self.pos, end_pos - self.pos, start_pos, outer_end_pos - start_pos)
                        next_pos = outer_end_pos
                else:
                    # Bogus comment
                    self.error("unexpected CDATA interpreted as bogus comment")
                    end_pos = text.find(">", self.pos)
                    bogus_pos = self.pos + 2
                    if end_pos == -1:
                        next_pos = self.length
                        contents = text[bogus_pos:]
                    else:
                        next_pos = end_pos + 1
                        contents = text[bogus_pos:end_pos]
                    contents = self.handle_nulls(contents, bogus_pos)
                    # (PHP: strpos() === false gives $endPos - $this->pos = -$this->pos)
                    self.listener.comment(contents, self.pos, (end_pos if end_pos != -1 else 0) - self.pos)
            elif m.start(MD_BOGUS_COMMENT) >= 0:
                # Bogus comment
                contents = m.group(MD_BOGUS_COMMENT)
                bogus_pos = m.start(MD_BOGUS_COMMENT)
                if m.group(0) == "</>":
                    self.error("empty end tag")
                    # No token emitted
                elif m.group(0) == "</":
                    self.error("EOF in end tag")
                    source_start = m.start()
                    self.listener.characters("</", 0, 2, source_start, 2)
                else:
                    self.error(f"unexpected <{contents[0]} interpreted as bogus comment")
                    if contents[0] != "?":
                        # For starting types other than <?, the initial character is
                        # not in the tag contents
                        contents = contents[1:]
                        bogus_pos += 1

                    contents = self.handle_nulls(contents, bogus_pos)
                    self.listener.comment(contents, start_pos, next_pos - start_pos)
            else:
                self.fatal("unexpected data state match")
            self.pos = next_pos
            if not (loop and next_state == self.STATE_DATA):
                break

        return next_state

    def interpret_comment_matches(self, m: re.Match[str]) -> None:
        """Interpret the data state match results for a detected comment, and emit events as appropriate."""
        outer_start = m.start()
        outer_length = len(m.group(0))
        inner_start = outer_start + len("<!--")
        contents = m.group(MD_COMMENT_INNER) or ""
        inner_length = len(contents)

        if m.group(0) == "<!-->" or m.group(0) == "<!--->":
            # These are special cases in the comment start state
            self.error("not enough dashes in empty comment", outer_start)
            self.listener.comment("", outer_start, outer_length)
            return

        if not self.ignore_nulls:
            contents = self.handle_nulls(contents, inner_start)
        close = m.group(MD_COMMENT_END)
        close_pos = m.start(MD_COMMENT_END)

        if not self.ignore_errors:
            if close == "--!>":
                self.error("invalid comment end bang", close_pos)
            elif close in ("-", "--", "--!"):
                self.error("EOF part way through comment close", close_pos)
            elif close == "":
                self.error("EOF in comment", close_pos)

            dash_search_length = inner_length
            while dash_search_length > 0 and contents[dash_search_length - 1] == "-":
                self.error("invalid extra dash at comment end", inner_start + dash_search_length - 1)
                dash_search_length -= 1

            offset = 0
            while offset != -1 and offset < dash_search_length:
                offset = contents.find("--", offset)
                if offset != -1:
                    self.error('bare "--" found in comment', inner_start + offset)
                    offset += 2

        self.listener.comment(contents, outer_start, outer_length)

    def interpret_doctype_matches(self, m: re.Match[str]) -> None:
        """Interpret the data state match results for a detected DOCTYPE token, and emit events as appropriate."""
        igerr = self.ignore_errors
        name = None
        public = None
        system = None
        quirks = False

        # Missing ">" can only be caused by EOF
        eof = not m.group(MD_DT_END)

        if m.group(MD_DT_BOGUS):
            # Bogus DOCTYPE state
            if not igerr:
                self.error("invalid DOCTYPE contents", m.start(MD_DT_BOGUS))
            # Set quirks mode unless there was a properly quoted SYSTEM identifier
            have_dq = m.start(MD_DT_SYSTEM_DQ) >= 0
            have_sq = m.start(MD_DT_SYSTEM_SQ) >= 0
            if not have_dq and not have_sq:
                quirks = True
            # EOF in the bogus state does not set quirks mode (but it is a parse error)
            if eof and not igerr:
                self.error("unterminated DOCTYPE")
        elif eof:
            if not igerr:
                self.error("unterminated DOCTYPE")
            quirks = True

        if not igerr and not eof and not m.group(MD_DT_NAME_WS):
            self.error("missing whitespace", m.start(MD_DT_NAME_WS))

        if m.group(MD_DT_NAME):
            # DOCTYPE name
            name = self.handle_nulls(strtolower(m.group(MD_DT_NAME)), m.start(MD_DT_NAME))
        else:
            if not eof and not igerr:
                self.error("missing DOCTYPE name", m.start(MD_DOCTYPE) + len("!DOCTYPE"))
            quirks = True

        if m.start(MD_DT_PUBLIC_WS) >= 0:
            # PUBLIC keyword found
            public, quirks = self.interpret_doctype_quoted(m, MD_DT_PUBLIC_DQ, MD_DT_PUBLIC_SQ, quirks)
            if public is None:
                quirks = True
                if not eof and not igerr:
                    self.error("missing public identifier", m.start(MD_DT_PUBLIC_WS))
            elif not igerr and not eof and not m.group(MD_DT_PUBLIC_WS):
                self.error("missing whitespace", m.start(MD_DT_PUBLIC_WS))

            # Check for a system ID after the public ID
            have_dq = m.start(MD_DT_PUBSYS_DQ) >= 0
            have_sq = m.start(MD_DT_PUBSYS_SQ) >= 0
            if have_dq or have_sq:
                if not igerr and not m.group(MD_DT_PUBSYS_WS):
                    self.error("missing whitespace", m.start(MD_DT_PUBSYS_WS))
                system, quirks = self.interpret_doctype_quoted(m, MD_DT_PUBSYS_DQ, MD_DT_PUBSYS_SQ, quirks)
        elif m.start(MD_DT_SYSTEM_WS) >= 0:
            # SYSTEM keyword found
            system, quirks = self.interpret_doctype_quoted(m, MD_DT_SYSTEM_DQ, MD_DT_SYSTEM_SQ, quirks)
            if system is None:
                quirks = True
                self.error("missing system identifier", m.start(MD_DT_SYSTEM_WS))
            elif not igerr and not m.group(MD_DT_SYSTEM_WS):
                self.error("missing whitespace", m.start(MD_DT_SYSTEM_WS))

        self.listener.doctype(name, public, system, quirks, m.start(), len(m.group(0)))

    def interpret_doctype_quoted(self, m: re.Match[str], dq: int, sq: int,
                                 quirks: bool) -> tuple[Optional[str], bool]:
        """DOCTYPE helper which interprets a quoted string (or lack thereof). Returns the quoted value, with nulls
        replaced, or None, and the updated quirks flag (a reference parameter in PHP)."""
        if m.start(dq) >= 0:
            value = m.group(dq)
            start_pos = m.start(dq)
        elif m.start(sq) >= 0:
            value = m.group(sq)
            start_pos = m.start(sq)
        else:
            return None, quirks
        end_pos = start_pos + len(value)
        if end_pos >= self.length:
            # This is a parse error, but we already emitted a generic EOF error
            quirks = True
        elif self.text[end_pos] == ">":
            self.error('DOCTYPE identifier terminated by ">"', end_pos)
            quirks = True
        value = self.handle_nulls(value, start_pos)
        return value, quirks

    def handle_nulls(self, text: str, source_pos: int) -> str:
        """Generic helper for all those points in the spec where U+0000 needs to be replaced with U+FFFD with a
        parse error issued. ``source_pos``: the input offset from which ``text`` was extracted, for error position
        reporting. Returns the converted text"""
        if self.ignore_nulls:
            return text
        if not self.ignore_errors:
            offset = 0
            while True:
                null_pos = text.find("\0", offset)
                if null_pos == -1:
                    break
                self.error("replaced null character", source_pos + null_pos)
                if null_pos < len(text) - 1:
                    offset = null_pos + 1
                else:
                    break
        return text.replace("\0", REPLACEMENT_CHAR)

    def handle_ascii_errors(self, mask: str, text: str, offset: int, length: int, source_pos: int) -> None:
        """Generic helper for points in the spec which say that an error should be issued when certain ASCII
        characters are seen, with no other action taken."""
        while length > 0:
            valid_length = strcspn(text, mask, offset, length)
            offset += valid_length
            length -= valid_length
            if length <= 0:
                break
            char = text[offset]
            codepoint = ord(char)
            if codepoint < 0x20 or codepoint >= 0x7f:
                self.error("unexpected U+00%02X" % codepoint, offset + source_pos)
            else:
                self.error(f'unexpected "{char}"', offset + source_pos)
            offset += 1
            length -= 1

    def handle_char_refs(self, text: str, source_pos: int, in_attr: bool = False,
                         additional_allowed_char: str = "") -> str:
        """Expand character references in some text, and emit errors as appropriate.

        ``source_pos``: the input position of ``text``; ``in_attr``: true if the text is within an attribute value;
        ``additional_allowed_char``: an unused string which the spec inexplicably spends a lot of space telling you
        how to derive. It suppresses errors in a place where no errors are emitted anyway. Returns the expanded
        text.

        RemexHtml matches HTMLData::$charRefRegex repeatedly, anchored, against the text:
        ``( .*? ) & (?: \\# (?: 0*(\\d+) | [xX]0*([0-9A-Fa-f]+) ) (;)? | (\\#) | ({{NAMED_ENTITY_REGEX}})
        (?: (?<!;) ([=a-zA-Z0-9]) )? | ( [a-zA-Z0-9]+ ; ) )``. The loop below finds the same matches: the first
        "&" from the current position at which one of the alternatives matches, tried in that order.
        """
        if self.ignore_char_refs:
            return text

        out = []
        pos = 0
        length = len(text)
        search = 0
        while True:
            amp = text.find("&", search)
            if amp == -1:
                break
            decimal = hexdec = semicolon = hash_ = invalid = None
            known_named = ""
            attribute_suffix = ""
            nm = _CHARREF_NUMERIC_RE.match(text, amp + 1)
            if nm:
                decimal, hexdec, semicolon = nm.group(1), nm.group(2), nm.group(3)
                end = nm.end()
            elif text.startswith("#", amp + 1):
                hash_ = "#"
                end = amp + 2
            else:
                named = named_entity_match(text, amp + 1)
                if named is not None:
                    known_named = named
                    end = amp + 1 + len(named)
                    if not named.endswith(";") and end < length and text[end] in _ATTRIBUTE_SUFFIX:
                        attribute_suffix = text[end]
                        end += 1
                else:
                    im = _CHARREF_INVALID_RE.match(text, amp + 1)
                    if im:
                        invalid = im.group(0)
                        end = im.end()
                    else:
                        # No alternative matches at this "&": the lazy prefix moves on
                        search = amp + 1
                        continue

            prefix = text[pos:amp]
            out.append(prefix)
            error_pos = source_pos + pos + len(prefix)
            pos = end
            search = end

            if hash_:
                # Bare &#
                self.error("Expected digits after &#", error_pos)
                out.append("&#")
                continue

            have_semicolon = bool(semicolon) or (known_named != "" and known_named[-1] == ";") or bool(invalid)

            if in_attr and not have_semicolon:
                if attribute_suffix:
                    if not self.ignore_errors and attribute_suffix == "=":
                        self.error("invalid equals sign after named character reference")
                    out.append("&" + known_named + attribute_suffix)
                    continue

            if not self.ignore_errors and not have_semicolon:
                self.error("character reference missing semicolon", error_pos)

            if decimal:
                # Decimal
                if len(decimal) > 7:
                    self.error("invalid numeric reference", error_pos)
                    out.append(REPLACEMENT_CHAR)
                    continue
                codepoint = int(decimal)
            elif hexdec:
                # Hexadecimal
                if len(hexdec) > 6:
                    self.error("invalid numeric reference", error_pos)
                    out.append(REPLACEMENT_CHAR)
                    continue
                codepoint = int(hexdec, 16)
            elif known_named != "":
                out.append(HTMLData.namedEntityTranslations[known_named] + attribute_suffix)
                continue
            elif invalid:
                if not self.ignore_errors:
                    self.error("invalid named reference", error_pos)
                out.append("&" + invalid)
                continue
            else:
                self.fatal("unable to identify char ref submatch")

            # Interpret $codepoint
            if codepoint == 0 or 0xD800 <= codepoint <= 0xDFFF or codepoint > 0x10FFFF:
                if not self.ignore_errors:
                    self.error("invalid numeric reference", error_pos)
                out.append(REPLACEMENT_CHAR)
            elif codepoint in HTMLData.legacyNumericEntities:
                if not self.ignore_errors:
                    self.error("invalid reference to non-ASCII control character", error_pos)
                out.append(HTMLData.legacyNumericEntities[codepoint])
            else:
                if not self.ignore_errors:
                    if (1 <= codepoint <= 8 or 0x0d <= codepoint <= 0x1f or 0x7f <= codepoint <= 0x9f
                            or 0xfdd0 <= codepoint <= 0xfdef or codepoint in _DISALLOWED_CODEPOINTS):
                        self.error("invalid numeric reference to control character", error_pos)

                out.append(chr(codepoint))
        if pos < length:
            out.append(text[pos:])
        return "".join(out)

    def emit_data_range(self, pos: int, length: int, is_simple: bool = False, has_simple_refs: bool = False) -> None:
        """Emit a range of the input text as a character token, and emit related errors, with validity rules as per
        the data state.

        ``is_simple``: true if you know that the data range does not contain < \\0 or &; false is safe if you're
        not sure. ``has_simple_refs``: true if you know that any character references are semicolon terminated and
        in the list of $commonEntities; false is safe if you're not sure
        """
        if length == 0:
            return
        if self.ignore_char_refs and self.ignore_nulls and self.ignore_errors:
            # Pretend this data range doesn't contain < \0 or &
            is_simple = True
        if is_simple:
            self.listener.characters(self.text, pos, length, pos, length)
        else:
            if not self.ignore_errors:
                # Any bare "<" in a data state text node is a parse error.
                # Uniquely to the data state, nulls are just flagged as errors
                # and passed through, they are not replaced.
                self.handle_ascii_errors("<\0", self.text, pos, length, 0)

            text = self.text[pos:pos + length]
            if has_simple_refs:
                text = _strtr_common_entities(text)
            else:
                text = self.handle_char_refs(text, pos)
            self.listener.characters(text, 0, len(text), pos, length)

    def emit_cdata_range(self, inner_pos: int, inner_length: int, outer_pos: int, outer_length: int) -> None:
        """Emit a range of characters from the input text, with validity rules as per the CDATA section state."""
        self.listener.characters(self.text, inner_pos, inner_length, outer_pos, outer_length)

    def emit_raw_text_range(self, ignore_char_refs: bool, pos: int, length: int) -> None:
        """Emit a range of characters from the input text, either from RCDATA, RAWTEXT, script data or PLAINTEXT.
        The only difference between these states is whether or not character references are expanded, so we take
        that as a parameter."""
        if length == 0:
            return
        ignore_char_refs = ignore_char_refs or self.ignore_char_refs
        if ignore_char_refs and self.ignore_nulls:
            self.listener.characters(self.text, pos, length, pos, length)
        else:
            text = self.text[pos:pos + length]
            if not ignore_char_refs:
                text = self.handle_char_refs(text, pos)
            text = self.handle_nulls(text, pos)
            self.listener.characters(text, 0, len(text), pos, length)

    def text_element_state(self, ignore_char_refs: bool) -> int:
        """The entry point for the RCDATA and RAWTEXT states. ``ignore_char_refs``: true to ignore character
        references regardless of configuration, false to respect the configuration. Returns the next state index"""
        if self.appropriate_end_tag is None:
            self.emit_raw_text_range(ignore_char_refs, self.pos, self.length - self.pos)
            self.pos = self.length
            return self.STATE_EOF

        # Assert that the end tag name state is exited appropriately,
        # since the anything else case leads to the tag being treated as
        # a literal
        regex = re.compile("</" + re.escape(self.appropriate_end_tag) + r"(?=[\t\n\f />])", re.I | re.A)

        while True:
            m = regex.search(self.text, self.pos)
            if not m:
                # Text runs to end
                self.emit_raw_text_range(ignore_char_refs, self.pos, self.length - self.pos)
                self.pos = self.length
                return self.STATE_EOF
            start_pos = m.start()

            # Emit text before tag
            self.emit_raw_text_range(ignore_char_refs, self.pos, start_pos - self.pos)

            match_length = len(m.group(0))
            self.pos = start_pos + match_length
            next_state = self.handle_attribs_and_close(self.STATE_RCDATA, self.appropriate_end_tag, True, start_pos)
            if next_state != self.STATE_RCDATA:
                return next_state

    def consume_attribs(self) -> Attributes:
        """Advance $this->pos, consuming all tag attributes found at the current position. The new position will be
        at the end of the tag or at the end of the input string.

        To improve performance of consumers which don't need to read the attribute array, interpretation of the
        PCRE match results is deferred.
        """
        matches = []
        pos = self.pos
        while True:
            m = _ATTRIB_RE.match(self.text, pos)
            if not m:
                break
            matches.append(m)
            pos = m.end()
        if matches:
            self.pos = pos
            attribs: Attributes = LazyAttributes(matches, self.interpret_attrib_matches)
        else:
            attribs = PlainAttributes()

        # Consume trailing whitespace. This is strictly part of the before attribute
        # name state, but we didn't consume it in the regex since we used a principle
        # of one match equals one attribute.
        self.pos += strspn(self.text, "\t\n\f ", self.pos)
        return attribs

    def interpret_attrib_matches(self, matches: list[re.Match[str]]) -> dict[str, str]:
        """Interpret the results of the attribute preg_match_all(). Emit errors as appropriate and return an
        associative array."""
        attributes: dict[str, str] = {}
        for m in matches:
            if m.group(MA_SLASH):
                self.error("unexpected bare slash", m.start(MA_SLASH))
                continue
            name = m.group(MA_NAME)
            simple_name = m.group(MA_SIMPLE_NAME)
            is_simple = simple_name is not None and len(name) == len(simple_name)
            if not is_simple:
                # We can skip these steps if we already know the name is simple
                if not self.ignore_errors:
                    self.handle_ascii_errors("\"'<=", name, 0, len(name), m.start(MA_NAME))
                if not self.ignore_nulls:
                    name = self.handle_nulls(m.group(MA_NAME), m.start(MA_NAME))
                name = strtolower(name)
            additional_allowed_char = ""
            is_simple = True
            if m.start(MA_DQUOTED) >= 0:
                # Double-quoted attribute value
                additional_allowed_char = '"'
                value = m.group(MA_DQUOTED)
                pos = m.start(MA_DQUOTED)
                is_simple = not m.group(MA_DQUOTED_UNSIMPLE)
                if is_simple and m.group(MA_DQUOTED_CHARREF) and not self.ignore_char_refs:
                    # Efficiently handle well-behaved character references
                    value = _strtr_common_entities(value)
            elif m.start(MA_SQUOTED) >= 0:
                # Single-quoted attribute value
                additional_allowed_char = "'"
                value = m.group(MA_SQUOTED)
                pos = m.start(MA_SQUOTED)
                is_simple = not m.group(MA_SQUOTED_UNSIMPLE)
                if is_simple and m.group(MA_SQUOTED_CHARREF) and not self.ignore_char_refs:
                    # Efficiently handle well-behaved character references
                    value = _strtr_common_entities(value)
            elif m.start(MA_UNQUOTED) >= 0:
                # Unquoted attribute value
                value = m.group(MA_UNQUOTED)
                pos = m.start(MA_UNQUOTED)
                is_simple = not m.group(MA_UNQUOTED_UNSIMPLE)
                # Search for parse errors
                if not self.ignore_errors:
                    if value == "":
                        # ">" in the before attribute value state is a parse error
                        self.error("empty unquoted attribute", pos)
                    if not is_simple:
                        self.handle_ascii_errors("\"'<=`", value, 0, len(value), pos)
            else:
                value = ""
                # reassure phan
                pos = -1
            if additional_allowed_char and not self.ignore_errors:
                # After attribute value (quoted) state
                # Quoted attributes must be followed by a space, "/" or ">"
                aav_pos = m.end()
                if aav_pos < self.length:
                    aav_char = self.text[aav_pos]
                    if aav_char not in _AFTER_ATTRIBUTE_VALUE:
                        self.error("missing space between attributes", aav_pos)
            if not is_simple and value != "":
                if not self.ignore_nulls:
                    value = self.handle_nulls(value, pos)
                if not self.ignore_char_refs:
                    value = self.handle_char_refs(value, pos, True, additional_allowed_char)
            if name in attributes:
                self.error("duplicate attribute", m.start())
            else:
                attributes[name] = value
        return attributes

    def handle_attribs_and_close(self, state: int, tag_name: str, is_end_tag: bool, start_pos: int) -> int:
        """Consume attributes, and the closing bracket which follows attributes. Emit the appropriate tag event, or
        in the case of broken attributes in text states, emit characters.

        ``state``: the current state; ``tag_name``: the normalized tag name; ``start_pos``: the input position of
        the start of the current tag. Returns the next state
        """
        attrib_start_pos = self.pos
        attribs = self.consume_attribs()
        pos = self.pos

        # Literal characters are emitted on EOF or "anything else" from the
        # end tag substates of the text states.
        # (spec ref 8.2.4 sections 11-19, 25-27)
        is_data_state = state == self.STATE_DATA
        is_literal = attrib_start_pos == pos and not is_data_state

        if pos >= self.length:
            self.error("unexpected end of file inside tag")
            if is_literal:
                self.listener.characters(self.text, start_pos, self.length - start_pos, start_pos,
                                         self.length - start_pos)
            return self.STATE_EOF
        if is_end_tag and not self.ignore_errors and attribs.count():
            self.error("end tag has an attribute")

        if self.text[pos:pos + 2] == "/>":
            pos += 2
            self_close = True
        elif self.text[pos] == ">":
            pos += 1
            self_close = False
        elif is_literal:
            self.listener.characters(self.text, start_pos, attrib_start_pos - start_pos, start_pos,
                                     attrib_start_pos - start_pos)
            return state
        else:
            self.fatal('failed to find an already-matched ">"')
        self.pos = pos
        if is_end_tag:
            if self_close:
                self.error("self-closing end tag")
            self.listener.end_tag(tag_name, start_pos, pos - start_pos)
        else:
            self.listener.start_tag(tag_name, attribs, self_close, start_pos, pos - start_pos)
        return self.STATE_DATA

    def plaintext_state(self) -> int:
        """Process input text in the PLAINTEXT state"""
        self.emit_raw_text_range(True, self.pos, self.length - self.pos)
        return self.STATE_EOF

    def script_data_state(self) -> int:
        """Process input text in the script data state"""
        if self.appropriate_end_tag is None:
            self.pos = self.length
            return self.STATE_EOF

        tag = re.escape(self.appropriate_end_tag)
        regex = re.compile(r"""
            (?: # Outer loop start
                # Script data state
                # Stop iteration if we previously matched an appropriate end tag.
                # This is a conditional subpattern: if capture 1 previously
                # matched, then run the pattern /$./ which always fails.
                (?(1) $. )
                .*?
                (?:
                    $ |
                    (
                        </ """ + tag + r"""
                        # If we hit the "anything else" case in the script data
                        # end tag name state, don't exit
                        (?= [\t\n\f />] )
                    ) | # 1. Appropriate end tag
                    <!--
                    # Script data escaped dash dash state
                    # Hyphens at this point are consumed without a state transition
                    # and so are not part of a comment-end.
                    -*

                    (?: # Inner loop start
                        # Script data escaped state
                        .*?
                        (?:
                            $ |
                            # Stop at, but do not consume, comment-close or end tag.
                            # This causes the inner loop to exit, since restarting the
                            # inner loop at this input position will cause the loop
                            # body to match zero characters. Repeating a zero-character
                            # match causes the repeat to terminate.
                            (?= --> ) |
                            (?= </ """ + tag + r""" [\t\n\f />] ) |
                            <script [\t\n\f />]
                            # Script data double escaped state
                            .*?
                            (?:
                                $ |
                                # Stop at, but do not consume, comment-close
                                (?= --> ) |
                                </script [\t\n\f />]
                            )
                        )
                    )*


                    # Consume the comment close which exited the inner loop, if any
                    (?: --> )?
                )
            )*
            """, re.X | re.S | re.I | re.A)

        while True:
            m = regex.match(self.text, self.pos)
            if not m:
                self.fatal("unexpected regex failure: this pattern can match zero characters")

            start_pos = self.pos
            match_length = len(m.group(0))
            end_tag_length = len(m.group(1)) if m.group(1) is not None else 0
            text_length = match_length - end_tag_length
            self.emit_raw_text_range(True, start_pos, text_length)
            self.pos = start_pos + match_length
            tag_start_pos = start_pos + text_length

            if end_tag_length:
                next_state = self.handle_attribs_and_close(self.STATE_SCRIPT_DATA, self.appropriate_end_tag, True,
                                                           tag_start_pos)
            else:
                next_state = self.STATE_EOF
            if next_state != self.STATE_SCRIPT_DATA:
                return next_state

    def error(self, text: str, pos: Optional[int] = None) -> None:
        """Emit a parse error event. ``pos``: the error position, or None to use the current position"""
        if not self.ignore_errors:
            if pos is None:
                pos = self.pos
            self.listener.error(text, pos)

    def fatal(self, text: str):
        """Throw an exception for a specified reason. This is used for API errors and assertion-like checks."""
        raise TokenizerError("Tokenizer: " + text)

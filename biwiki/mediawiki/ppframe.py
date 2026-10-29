# Ported from MediaWiki 1.39 includes/parser/PPFrame.php, PPFrame_Hash.php, PPTemplateFrame_Hash.php and
# PPCustomFrame_Hash.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; PPFrame_Hash is Frame, PPTemplateFrame_Hash is
# TemplateFrame, PPCustomFrame_Hash is CustomFrame (the PHP names are aliases); titles may be plain strings; PHP's
# array key normalisation ("1" and 1 are the same key) is done by _php_key(); the expansion depth is restored even
# when an expansion raises.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Expansion frames: the context (template arguments, loop check, limits) in which a preprocessor tree is expanded
to text, calling back into the parser for templates, arguments and extension tags."""
from __future__ import annotations

import re
from typing import Optional, Union

from .ppnode import MWException, PPNode_Hash_Array, PPNode_Hash_Attr, PPNode_Hash_Text, PPNode_Hash_Tree
from .stripstate import MARKER_PREFIX, MARKER_SUFFIX

# PPFrame flags
NO_ARGS = 1
NO_TEMPLATES = 2
STRIP_COMMENTS = 4
NO_IGNORE = 8
RECOVER_COMMENTS = 16
NO_TAGS = 32
PROCESS_NOWIKI = 64

# Recover original text, as far as possible
RECOVER_ORIG = NO_ARGS | NO_TEMPLATES | NO_IGNORE | RECOVER_COMMENTS | NO_TAGS

_INT_KEY = re.compile(r"-?[1-9][0-9]*|0")
_PHP_INT_MAX = 2 ** 63 - 1


def _php_key(key):
    """The key PHP stores for an array key: decimal integer strings ("1", not "01" or " 1") become integers."""
    if isinstance(key, bool):
        return int(key)
    if isinstance(key, str) and _INT_KEY.fullmatch(key) and -_PHP_INT_MAX - 1 <= int(key) <= _PHP_INT_MAX:
        return int(key)
    return key


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


def _pdbk(title) -> Union[str, bool]:
    """$title->getPrefixedDBkey(), or false for no title. A plain string title is taken as the prefixed text."""
    if title is None or title is False or (isinstance(title, str) and title == ""):
        return False
    if hasattr(title, "prefixed_db_key"):  # title.Title
        return title.prefixed_db_key
    return str(title).replace(" ", "_")


def _php_strval(value) -> str:
    """$out .= $value: null and false append nothing"""
    if value is None or value is False:
        return ""
    if value is True:
        return "1"
    return str(value)


def _title_text(title) -> str:
    """(string)$title: the prefixed text, '' for no title."""
    if title is None or title is False:
        return ""
    return str(title)


class Frame:
    """An expansion frame, used as a context to expand the result of preprocess_to_obj() (PPFrame_Hash)"""

    NO_ARGS = NO_ARGS
    NO_TEMPLATES = NO_TEMPLATES
    STRIP_COMMENTS = STRIP_COMMENTS
    NO_IGNORE = NO_IGNORE
    RECOVER_COMMENTS = RECOVER_COMMENTS
    NO_TAGS = NO_TAGS
    PROCESS_NOWIKI = PROCESS_NOWIKI
    RECOVER_ORIG = RECOVER_ORIG

    # static $expansionDepth of PPFrame_Hash::expand(), shared by all frames
    _expansion_depth = 0

    # Only template frames have a parent
    parent: Optional["Frame"] = None

    def __init__(self, preprocessor):
        """``preprocessor``: the parent preprocessor"""
        self.preprocessor = preprocessor
        self.parser = preprocessor.parser
        self.title = self.parser.get_title()
        # $parser->getOptions()->getMaxPPNodeCount() / getMaxPPExpandDepth(): $wgMaxPPNodeCount, $wgMaxPPExpandDepth
        self._max_pp_node_count: int = self.parser.config.max_pp_node_count
        self._max_pp_expand_depth: int = self.parser.config.max_pp_expand_depth
        self.title_cache: list = [_pdbk(self.title) if self.title else False]
        # Hashtable listing templates which are disallowed for expansion in this frame, having been encountered
        # previously in parent frames.
        self.loop_check_hash: dict[str, bool] = {}
        # Recursion depth of this frame, top = 0. Note that this is NOT the same as expansion depth in expand()
        self.depth = 0
        self._volatile = False
        self._ttl: Optional[int] = None
        self.child_expansion_cache: dict = {}

    def new_child(self, args=None, title=None, index_offset: int = 0) -> "TemplateFrame":
        """Create a new child frame. ``args`` is optionally a multi-root PPNode or list containing the template
        arguments."""
        named_args: dict = {}
        numbered_args: dict = {}
        if title is None or title is False:
            title = self.title
        if args is not None and args is not False:
            if isinstance(args, PPNode_Hash_Array):
                args = args.value
            elif not isinstance(args, list):
                raise MWException("PPFrame_Hash::newChild: $args must be array or PPNode_Hash_Array")
            for arg in args:
                bits = arg.split_arg()
                if bits["index"] != "":
                    # Numbered parameter
                    index = int(bits["index"]) - index_offset
                    if index in named_args or index in numbered_args:
                        self.parser.get_output().add_warning_msg(
                            "duplicate-args-warning", _title_text(self.title), _title_text(title), index)
                        self.parser.add_tracking_category("duplicate-args-category")
                    numbered_args[index] = bits["value"]
                    named_args.pop(index, None)
                else:
                    # Named parameter
                    name = _php_key(_php_trim(self.expand(bits["name"], STRIP_COMMENTS)))
                    if name in named_args or name in numbered_args:
                        self.parser.get_output().add_warning_msg(
                            "duplicate-args-warning", _title_text(self.title), _title_text(title), name)
                        self.parser.add_tracking_category("duplicate-args-category")
                    named_args[name] = bits["value"]
                    numbered_args.pop(name, None)
        return TemplateFrame(self.preprocessor, self, numbered_args, named_args, title)

    def cached_expand(self, key, root, flags: int = 0) -> str:
        # we don't have a parent, so we don't have a cache
        return self.expand(root, flags)

    def expand(self, root, flags: int = 0) -> str:
        if isinstance(root, str):
            return root

        parser = self.parser
        parser.pp_node_count += 1
        if parser.pp_node_count > self._max_pp_node_count:
            parser.limitation_warn("node-count-exceeded", parser.pp_node_count, self._max_pp_node_count)
            return '<span class="error">Node-count limit exceeded</span>'
        if Frame._expansion_depth > self._max_pp_expand_depth:
            parser.limitation_warn("expansion-depth-exceeded", Frame._expansion_depth, self._max_pp_expand_depth)
            return '<span class="error">Expansion depth limit exceeded</span>'
        Frame._expansion_depth += 1
        try:
            if Frame._expansion_depth > parser.highest_expansion_depth:
                parser.highest_expansion_depth = Frame._expansion_depth
            return self._expand(root, flags)
        finally:
            Frame._expansion_depth -= 1

    def _expand(self, root, flags: int) -> str:
        """The loop of PPFrame_Hash::expand(), which walks the tree with explicit stacks instead of recursion."""
        parser = self.parser
        out_stack = ["", ""]
        iterator_stack: list = [None, root]
        index_stack = [0, 0]

        while len(iterator_stack) > 1:
            level = len(out_stack) - 1
            iterator_node = iterator_stack[level]

            if isinstance(iterator_node, list):
                if index_stack[level] >= len(iterator_node):
                    # All done with this iterator
                    iterator_stack[level] = None
                    context_node = None
                else:
                    context_node = iterator_node[index_stack[level]]
                    index_stack[level] += 1
            elif isinstance(iterator_node, PPNode_Hash_Array):
                if index_stack[level] >= iterator_node.get_length():
                    # All done with this iterator
                    iterator_stack[level] = None
                    context_node = None
                else:
                    context_node = iterator_node.item(index_stack[level])
                    index_stack[level] += 1
            else:
                # Copy to context_node and then delete from iterator stack, because this is not an iterator but we
                # do have to execute it once
                context_node = iterator_stack[level]
                iterator_stack[level] = None

            new_iterator = None
            context_name = None
            context_children = None

            if context_node is None:
                pass  # nothing to do
            elif isinstance(context_node, str):
                out_stack[level] += context_node
            elif isinstance(context_node, PPNode_Hash_Array):
                new_iterator = context_node
            elif isinstance(context_node, PPNode_Hash_Attr):
                pass  # No output
            elif isinstance(context_node, PPNode_Hash_Text):
                out_stack[level] += str(context_node.value)
            elif isinstance(context_node, PPNode_Hash_Tree):
                context_name = context_node.name
                context_children = context_node.get_raw_children()
            elif isinstance(context_node, list):
                # Node descriptor array
                if len(context_node) != 2:
                    raise MWException("PPFrame_Hash::expand: found an array where a node descriptor should be")
                context_name, context_children = context_node
            else:
                raise MWException("PPFrame_Hash::expand: Invalid parameter type")

            # Handle node descriptor array or tree object
            if context_name is None:
                pass  # Not a node, already handled above
            elif context_name[0] == "@":
                pass  # Attribute: no output
            elif context_name == "template":
                # Double-brace expansion
                bits = PPNode_Hash_Tree.split_raw_template(context_children)
                if flags & NO_TEMPLATES:
                    new_iterator = self.virtual_bracketed_implode("{{", "|", "}}", bits["title"], bits["parts"])
                else:
                    ret = parser.brace_substitution(bits, self)
                    if ret.get("object") is not None:
                        new_iterator = ret["object"]
                    else:
                        out_stack[level] += _php_strval(ret.get("text"))
            elif context_name == "tplarg":
                # Triple-brace expansion
                bits = PPNode_Hash_Tree.split_raw_template(context_children)
                if flags & NO_ARGS:
                    new_iterator = self.virtual_bracketed_implode("{{{", "|", "}}}", bits["title"], bits["parts"])
                else:
                    ret = parser.arg_substitution(bits, self)
                    if ret.get("object") is not None:
                        new_iterator = ret["object"]
                    else:
                        out_stack[level] += _php_strval(ret.get("text"))
            elif context_name == "comment":
                # HTML-style comment
                # Remove it in HTML, pre+remove and STRIP_COMMENTS modes
                # Not in RECOVER_COMMENTS mode (msgnw) though.
                # ParserOptions::getRemoveComments() (default true) is read from the config as remove_comments
                if ((parser.ot["html"] or (parser.ot["pre"] and parser.config.remove_comments)
                        or flags & STRIP_COMMENTS) and not flags & RECOVER_COMMENTS):
                    out_stack[level] += ""
                elif parser.ot["wiki"] and not flags & RECOVER_COMMENTS:
                    # Add a strip marker in PST mode so that pstPass2() can run some old-fashioned regexes on the
                    # result. Not in RECOVER_COMMENTS mode (extractSections) though.
                    out_stack[level] += parser.insert_strip_item(context_children[0])
                else:
                    # Recover the literal comment in RECOVER_COMMENTS and pre+no-remove
                    out_stack[level] += context_children[0]
            elif context_name == "ignore":
                # Output suppression used by <includeonly> etc.
                # OT_WIKI will only respect <ignore> in substed templates.
                # The other output types respect it unless NO_IGNORE is set.
                # extractSections() sets NO_IGNORE and so never respects it.
                if (self.parent is None and parser.ot["wiki"]) or flags & NO_IGNORE:
                    out_stack[level] += context_children[0]
                # else: out .= ''
            elif context_name == "ext":
                # Extension tag
                bits = PPNode_Hash_Tree.split_raw_ext(context_children)
                for key in ("attr", "inner", "close"):
                    bits.setdefault(key, None)
                if flags & NO_TAGS:
                    s = "<" + bits["name"].get_first_child().value
                    if bits["attr"]:
                        s += bits["attr"].get_first_child().value
                    if bits["inner"]:
                        s += ">" + bits["inner"].get_first_child().value
                        if bits["close"]:
                            s += bits["close"].get_first_child().value
                    else:
                        s += "/>"
                    out_stack[level] += s
                else:
                    out_stack[level] += parser.extension_substitution(bits, self, bool(flags & PROCESS_NOWIKI))
            elif context_name == "h":
                # Heading
                if parser.ot["html"]:
                    # Expand immediately and insert heading index marker
                    s = self.expand(context_children, flags)
                    bits = PPNode_Hash_Tree.split_raw_heading(context_children)
                    title_text = _pdbk(self.title)
                    parser.headings.append([title_text, bits["i"]])
                    serial = len(parser.headings) - 1
                    marker = f"{MARKER_PREFIX}-h-{serial}-{MARKER_SUFFIX}"
                    level_ = int(bits["level"])
                    s = s[:level_] + marker + s[level_:]
                    parser.strip_state.add_general(marker, "")
                    out_stack[level] += s
                else:
                    # Expand in virtual stack
                    new_iterator = context_children
            else:
                # Generic recursive expansion
                new_iterator = context_children

            if new_iterator is not None:
                out_stack.append("")
                iterator_stack.append(new_iterator)
                index_stack.append(0)
            elif iterator_stack[level] is None:
                # Return accumulated value to parent
                # With tail recursion
                while iterator_stack[level] is None and level > 0:
                    out_stack[level - 1] += out_stack[level]
                    out_stack.pop()
                    iterator_stack.pop()
                    index_stack.pop()
                    level -= 1
        return out_stack[0]

    def implode_with_flags(self, sep: str, flags: int, *args) -> str:
        first = True
        s = ""
        for root in args:
            if isinstance(root, PPNode_Hash_Array):
                root = root.value
            if not isinstance(root, list):
                root = [root]
            for node in root:
                if first:
                    first = False
                else:
                    s += sep
                s += self.expand(node, flags)
        return s

    def implode(self, sep: str, *args) -> str:
        """Implode with no flags specified"""
        return self.implode_with_flags(sep, 0, *args)

    def virtual_implode(self, sep: str, *args) -> PPNode_Hash_Array:
        """Makes an object that, when expand()ed, will be the same as one obtained with implode()"""
        out = []
        first = True
        for root in args:
            if isinstance(root, PPNode_Hash_Array):
                root = root.value
            if not isinstance(root, list):
                root = [root]
            for node in root:
                if first:
                    first = False
                else:
                    out.append(sep)
                out.append(node)
        return PPNode_Hash_Array(out)

    def virtual_bracketed_implode(self, start: str, sep: str, end: str, *args) -> PPNode_Hash_Array:
        """Virtual implode with brackets"""
        out = [start]
        first = True
        for root in args:
            if isinstance(root, PPNode_Hash_Array):
                root = root.value
            if not isinstance(root, list):
                root = [root]
            for node in root:
                if first:
                    first = False
                else:
                    out.append(sep)
                out.append(node)
        out.append(end)
        return PPNode_Hash_Array(out)

    def __str__(self) -> str:
        return "frame{}"

    def get_pdbk(self, level=None):
        if level is None or level is False:
            return _pdbk(self.title)
        return self.title_cache[level] if 0 <= level < len(self.title_cache) else False

    def get_arguments(self) -> dict:
        return {}

    def get_numbered_arguments(self) -> dict:
        return {}

    def get_named_arguments(self) -> dict:
        return {}

    def is_empty(self) -> bool:
        """Returns true if there are no arguments in this frame"""
        return True

    def get_argument(self, name) -> Union[str, bool]:
        """Always False in this implementation."""
        return False

    def loop_check(self, title) -> bool:
        """Returns true if the infinite loop check is OK, false if a loop is detected"""
        return _pdbk(title) not in self.loop_check_hash

    def is_template(self) -> bool:
        """Return true if the frame is a template frame"""
        return False

    def get_title(self):
        """Get a title of frame"""
        return self.title

    def set_volatile(self, flag: bool = True) -> None:
        """Set the volatile flag"""
        self._volatile = flag

    def is_volatile(self) -> bool:
        """Get the volatile flag"""
        return self._volatile

    def set_ttl(self, ttl: Optional[int]) -> None:
        if ttl is not None and (self._ttl is None or ttl < self._ttl):
            self._ttl = ttl

    def get_ttl(self) -> Optional[int]:
        return self._ttl


class TemplateFrame(Frame):
    """Expansion frame with template arguments (PPTemplateFrame_Hash)"""

    def __init__(self, preprocessor, parent: Optional[Frame] = None, numbered_args: Optional[dict] = None,
                 named_args: Optional[dict] = None, title=None):
        super().__init__(preprocessor)
        self.parent = parent
        self.numbered_args: dict = numbered_args if numbered_args is not None else {}
        self.named_args: dict = named_args if named_args is not None else {}
        self.title = title
        pdbk = _pdbk(title) if title else False
        self.title_cache = list(parent.title_cache)
        self.title_cache.append(pdbk)
        self.loop_check_hash = dict(parent.loop_check_hash)
        if pdbk is not False:
            self.loop_check_hash[pdbk] = True
        self.depth = parent.depth + 1
        self.numbered_expansion_cache: dict = {}
        self.named_expansion_cache: dict = {}

    def __str__(self) -> str:
        s = "tplframe{"
        first = True
        args = dict(self.numbered_args)
        for name, value in self.named_args.items():
            args.setdefault(name, value)
        for name, value in args.items():
            if first:
                first = False
            else:
                s += ", "
            s += f'"{name}":"' + str(value).replace('"', '\\"') + '"'
        s += "}"
        return s

    def cached_expand(self, key, root, flags: int = 0) -> str:
        if self.parent.child_expansion_cache.get(key) is not None:
            return self.parent.child_expansion_cache[key]
        retval = self.expand(root, flags)
        if not self.is_volatile():
            self.parent.child_expansion_cache[key] = retval
        return retval

    def is_empty(self) -> bool:
        """Returns true if there are no arguments in this frame"""
        return not self.numbered_args and not self.named_args

    def get_arguments(self) -> dict:
        arguments = {}
        for key in list(self.numbered_args) + list(self.named_args):
            arguments[key] = self.get_argument(key)
        return arguments

    def get_numbered_arguments(self) -> dict:
        return {key: self.get_argument(key) for key in self.numbered_args}

    def get_named_arguments(self) -> dict:
        return {key: self.get_argument(key) for key in self.named_args}

    def get_numbered_argument(self, index) -> Union[str, bool]:
        index = _php_key(index)
        if self.numbered_args.get(index) is None:
            return False
        if self.numbered_expansion_cache.get(index) is None:
            # No trimming for unnamed arguments
            self.numbered_expansion_cache[index] = self.parent.expand(self.numbered_args[index], STRIP_COMMENTS)
        return self.numbered_expansion_cache[index]

    def get_named_argument(self, name) -> Union[str, bool]:
        name = _php_key(name)
        if self.named_args.get(name) is None:
            return False
        if self.named_expansion_cache.get(name) is None:
            # Trim named arguments post-expand, for backwards compatibility
            self.named_expansion_cache[name] = _php_trim(
                self.parent.expand(self.named_args[name], STRIP_COMMENTS))
        return self.named_expansion_cache[name]

    def get_argument(self, name) -> Union[str, bool]:
        text = self.get_numbered_argument(name)
        if text is False:
            text = self.get_named_argument(name)
        return text

    def is_template(self) -> bool:
        """Return true if the frame is a template frame"""
        return True

    def set_volatile(self, flag: bool = True) -> None:
        super().set_volatile(flag)
        self.parent.set_volatile(flag)

    def set_ttl(self, ttl: Optional[int]) -> None:
        super().set_ttl(ttl)
        self.parent.set_ttl(ttl)


class CustomFrame(Frame):
    """Expansion frame with custom arguments (PPCustomFrame_Hash)"""

    def __init__(self, preprocessor, args: dict):
        super().__init__(preprocessor)
        self.args = {_php_key(key): value for key, value in args.items()}

    def __str__(self) -> str:
        s = "cstmframe{"
        first = True
        for name, value in self.args.items():
            if first:
                first = False
            else:
                s += ", "
            s += f'"{name}":"' + str(value).replace('"', '\\"') + '"'
        s += "}"
        return s

    def is_empty(self) -> bool:
        return not self.args

    def get_argument(self, index) -> Union[str, bool]:
        value = self.args.get(_php_key(index))
        return False if value is None else value

    def get_arguments(self) -> dict:
        return self.args


# MediaWiki's class names
PPFrame_Hash = Frame
PPTemplateFrame_Hash = TemplateFrame
PPCustomFrame_Hash = CustomFrame

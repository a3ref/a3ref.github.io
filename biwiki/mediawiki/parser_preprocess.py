# Ported from MediaWiki 1.39 includes/parser/Parser.php (the template and preprocessing half: clearState() and
# the constructor's hook setup, getOutputType()/setOutputType(), recursiveTagParse(), recursiveTagParseFully(),
# recursivePreprocess(), getTitle(), getPreprocessor(), extractTagsAndParams(), getStripList(), insertStripItem(),
# expandMagicVariable(), initializeVariables(), preprocessToDom(), replaceVariables(), limitationWarn(),
# braceSubstitution(), callParserFunction(), getTemplateDom(), fetchCurrentRevisionRecordOfTitle(),
# fetchTemplateAndTitle(), statelessFetchTemplate(), interwikiTransclude(), argSubstitution(),
# extensionSubstitution(), incrementIncludeSize(), incrementExpensiveFunctionCount(), addTrackingCategory(),
# setHook(), clearTagHooks(), setFunctionHook(), getFunctionHooks(), attributeStripCallback(), getTags(),
# getFunctionSynonyms(), markerSkipCallback(), killMarkers(), stripOuterParagraph()), includes/parser/CoreTagHooks.php,
# and the helpers they call: Linker::normalizeSubpageLink() (includes/Linker.php), wfEscapeWikiText()
# (includes/GlobalFunctions.php), WikitextContent::getRedirectTargetAndText() (includes/content/WikitextContent.php)
# and Title::isValidRedirectTarget() (includes/Title.php) (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python as a mixin of the Parser class; templates come
# from the parser's ``pages`` mapping instead of the database; no hooks of other extensions, profiling, caches
# beyond one parse, language variants, special page or interwiki transclusion; the English text of the messages.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Templates, template arguments, parser functions and extension tags: the preprocessing half of the Parser.

PreprocessingMixin is mixed into Parser (parser.py), which provides ``config``, ``magic_words``, ``pages``,
``title``, ``strip_state``, ``output``, ``internal_parse(text, is_main, frame)`` and
``internal_parse_half_parsed(text, is_main, linestart)``; ``site`` (a site.Site) is used when present, otherwise one
is built from ``config``.
"""
from __future__ import annotations

import functools
import importlib.util
import inspect
import re
import urllib.parse
from typing import Callable, Optional, Union

from .html import htmlspecialchars, raw_element
from .ppframe import NO_TEMPLATES, RECOVER_ORIG, STRIP_COMMENTS, Frame, _php_key  # noqa: F401
from .ppnode import MWException, PPNode_Hash_Array, PPNode_Hash_Attr, PPNode_Hash_Text, PPNode_Hash_Tree
from .preprocessor import DOM_FOR_INCLUSION, Preprocessor
from .site import NS_MEDIAWIKI, NS_SPECIAL, NS_TEMPLATE, Site
from .stripstate import MARKER_PREFIX, MARKER_SUFFIX
from .title import Title

# Allowed values for output_type (Parser::OT_*)
OT_HTML = 1  # like parse()
OT_WIKI = 2  # like preSaveTransform()
OT_PREPROCESS = 3  # like preprocess()
OT_MSG = 3
OT_PLAIN = 4  # like extractSections() - portions of the original are returned unchanged.

# Flags for Parser::setFunctionHook
SFH_NO_HASH = 1
SFH_OBJECT_ARGS = 2

# Preprocess wikitext in transclusion mode
PTD_FOR_INCLUSION = DOM_FOR_INCLUSION

# $wgInvalidRedirectTargets (MainConfigSchema default)
INVALID_REDIRECT_TARGETS = ("Filepath", "Mypage", "Mytalk", "Redirect")

# English text of the messages used here (languages/i18n/en.json)
_MESSAGES = {
    "parser-template-recursion-depth-warning": "Template recursion depth limit exceeded ($1)",
    "parser-template-loop-warning": "Template loop detected: [[$1]]",
    "scarytranscludedisabled": "[Interwiki transcluding is disabled]",
    "invalid-indicator-name": "<strong>Error:</strong> Page status indicators' <code>name</code> attribute must "
                              "not be empty.",
    "invalid-langconvert-attrs": "<strong>Error:</strong> Langconvert tag's <code>from</code> and <code>to</code> "
                                 "attributes must not be empty and must contain BCP 47 codes for convertible "
                                 "variants of the same language.",
}

_PPNODE = (PPNode_Hash_Tree, PPNode_Hash_Text, PPNode_Hash_Attr, PPNode_Hash_Array)
_ERROR_STR = '<span class="error">'
_WS = "[\t\n\x0b\f\r ]"  # PCRE's \s without the u modifier
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _msg(key: str, *params) -> str:
    """wfMessage( $key, ...$params )->inContentLanguage()->text()"""
    text = _MESSAGES[key]
    for i, p in enumerate(params, 1):
        text = text.replace(f"${i}", str(p))
    return text


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


@functools.lru_cache(maxsize=None)
def _max_positional(callback: Callable) -> Optional[int]:
    """How many positional arguments ``callback`` takes, the parser included; None if it takes any number."""
    params = inspect.signature(callback).parameters.values()
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return None
    return sum(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params)


def _strlen(s) -> int:
    """PHP strlen(): bytes of the UTF-8 form; 0 for false/null"""
    if s is None or s is False:
        return 0
    return len(str(s).encode("utf-8"))


def _isset(d: dict, key) -> bool:
    return d.get(key) is not None


def wf_escape_wiki_text(text: str, config) -> str:
    """wfEscapeWikiText(): escapes the given text so that it may be output using addWikiText() without any linking,
    formatting, etc. making its way through. This is achieved by substituting certain characters with HTML
    entities. As required by the callers, "<nowiki>" is not used."""
    from .stringutils import php_strtr

    repl = {
        '"': "&#34;", "&": "&#38;", "'": "&#39;", "<": "&#60;",
        "=": "&#61;", ">": "&#62;", "[": "&#91;", "]": "&#93;",
        "{": "&#123;", "|": "&#124;", "}": "&#125;", ";": "&#59;",
        "\n#": "\n&#35;", "\r#": "\r&#35;",
        "\n*": "\n&#42;", "\r*": "\r&#42;",
        "\n:": "\n&#58;", "\r:": "\r&#58;",
        "\n ": "\n&#32;", "\r ": "\r&#32;",
        "\n\n": "\n&#10;", "\r\n": "&#13;\n",
        "\n\r": "\n&#13;", "\r\r": "\r&#13;",
        "\n\t": "\n&#9;", "\r\t": "\r&#9;",  # "\n\t\n" is treated like "\n\n"
        "\n----": "\n&#45;---", "\r----": "\r&#45;---",
        "__": "_&#95;", "://": "&#58;//",
    }
    magic_links = [magic for magic, enabled in config.enable_magic_links.items() if enabled]
    # We have to catch everything "\s" matches in PCRE
    for magic in magic_links:
        repl[f"{magic} "] = f"{magic}&#32;"
        repl[f"{magic}\t"] = f"{magic}&#9;"
        repl[f"{magic}\r"] = f"{magic}&#13;"
        repl[f"{magic}\n"] = f"{magic}&#10;"
        repl[f"{magic}\f"] = f"{magic}&#12;"

    # And handle protocols that don't use "://"
    repl2 = [re.escape(prot[:-1]) for prot in config.url_protocols if prot.endswith(":")]
    text = php_strtr("\n" + text, repl)[1:]
    if repl2:
        text = re.sub(r"\b(" + "|".join(repl2) + "):", r"\1&#58;", text, flags=re.I | re.A)
    return text


def normalize_subpage_link(context_title: Optional[Title], target: str, text: str, site: Site) -> tuple[str, str]:
    """Linker::normalizeSubpageLink(): the target of a link that may be relative to the page ``context_title``,
    and the link text (``text`` is the PHP by-reference argument)."""
    # Valid link forms:
    # Foobar -- normal
    # :Foobar -- override special treatment of prefix (images, language links)
    # /Foobar -- convert to CurrentPage/Foobar
    # /Foobar/ -- convert to CurrentPage/Foobar, strip the initial and final / from text
    # ../ -- convert to CurrentPage, from CurrentPage/CurrentSubPage
    # ../Foobar -- convert to CurrentPage/Foobar, (from CurrentPage/CurrentSubPage)
    # ../Foobar/ -- convert to CurrentPage/Foobar, use 'Foobar' as text (from CurrentPage/CurrentSubPage)
    ret = target  # default return value is no change

    # Some namespaces don't allow subpages, so only perform processing if subpages are allowed
    if context_title and site.has_subpages(context_title.namespace):
        hash_ = target.find("#")
        if hash_ != -1:
            suffix = target[hash_:]
            target = target[:hash_]
        else:
            suffix = ""
        # T9425
        target = _php_trim(target)
        context_prefixed_text = context_title.prefixed_text
        # Look at the first character
        if target != "" and target[0] == "/":
            # / at end means we don't want the slash to be shown
            m = re.search(r"(/+)$", target)
            if m:
                noslash = target = target[1:-len(m.group(0))]
            else:
                noslash = target[1:]

            ret = context_prefixed_text + "/" + _php_trim(noslash) + suffix
            if text == "":
                text = target + suffix
            # this might be changed for ugliness reasons
        else:
            # check for .. subpage backlinks
            dotdotcount = 0
            nodotdot = target
            while nodotdot.startswith("../"):
                dotdotcount += 1
                nodotdot = nodotdot[3:]
            if dotdotcount > 0:
                exploded = context_prefixed_text.split("/")
                if len(exploded) > dotdotcount:  # not allowed to go below top level page
                    ret = "/".join(exploded[:-dotdotcount])
                    # / at the end means don't show full path
                    if nodotdot[-1:] == "/":
                        nodotdot = nodotdot.rstrip("/")
                        if text == "":
                            text = nodotdot + suffix
                    nodotdot = _php_trim(nodotdot)
                    if nodotdot != "":
                        ret += "/" + nodotdot
                    ret += suffix
    return ret, text


def strip_outer_paragraph(html: str) -> str:
    """Parser::stripOuterParagraph(): strip outer <p></p> tag from the HTML source of a single paragraph. Returns
    original HTML if the <p/> tag has any attributes, if there's no wrapping <p/> tag, or if there is more than one
    <p/> tag in the input HTML."""
    m = re.match(r"<p>(.*?)\n??</p>\n??$", html, re.S)
    if m and "</p>" not in m.group(1):
        html = m.group(1)
    return html


_extract_counter = 1  # static $n of Parser::extractTagsAndParams()


def extract_tags_and_params(elements: list[str], text: str) -> tuple[str, dict]:
    """Parser::extractTagsAndParams(): replaces all occurrences of HTML-style comments and the given tags in the
    text with a random marker and returns the next text, and the extracted tags: marker => [element, tag content,
    {param: value}, '<element param="x">tag content</element>']. Comments are always extracted."""
    from .sanitizer import decode_tag_attributes

    global _extract_counter
    stripped = ""
    matches: dict[str, list] = {}

    taglist = "|".join(elements)
    start = re.compile(rf"<({taglist})({_WS}+[^>]*?|{_WS}*?)(/?>)|<(!--)", re.I | re.A)

    while text != "":
        m = start.search(text)
        if not m:
            stripped += text
            break
        stripped += text[:m.start()]
        inside = text[m.end():]
        if m.group(4) is not None:
            # comment
            element = m.group(4)
            attributes = ""
            close = ""
        else:
            # tag
            element, attributes, close = m.group(1), m.group(2), m.group(3)

        marker = f"{MARKER_PREFIX}-{element}-{_extract_counter:08X}{MARKER_SUFFIX}"
        _extract_counter += 1
        stripped += marker

        if close == "/>":
            # Empty element tag, <tag />
            content = None
            text = inside
            tail = None
        else:
            if element == "!--":
                end = re.compile("(-->)")
            else:
                end = re.compile(rf"(</{element}{_WS}*>)", re.I | re.A)
            q = end.search(inside)
            if not q:
                # No end tag -- let it run out to the end of the text.
                content = inside
                tail = ""
                text = ""
            else:
                content = inside[:q.start()]
                tail = q.group(1)
                text = inside[q.end():]

        matches[marker] = [element, content, decode_tag_attributes(attributes),
                           f"<{element}{attributes}{close}{content or ''}{tail or ''}"]
    return stripped, matches


def is_valid_redirect_target(title: Title) -> bool:
    """Title::isValidRedirectTarget(): check if this title is a valid redirect target. Special page aliases are not
    resolved: the canonical names are compared."""
    if title.is_special_page():
        # invalid redirect targets are stored in a global array, but explicitly disallow Userlogout here
        name = title.db_key.split("/", 1)[0].lower()
        return name not in [t.lower() for t in ("Userlogout",) + INVALID_REDIRECT_TARGETS]
    elif title.db_key == "":
        # relative section links are not valid redirect targets (T278367)
        return False
    return title.is_valid()


class CoreTagHooks:
    """Various tag hooks, registered in every Parser (CoreTagHooks.php). A tag hook is called as
    ``hook(content, attributes, parser, frame)`` and returns HTML, or a dict ``{0: html, "markerType": ...}``."""

    @staticmethod
    def register(parser) -> None:
        raw_html = parser.config.raw_html
        parser.set_hook("pre", CoreTagHooks.pre)
        parser.set_hook("nowiki", CoreTagHooks.nowiki)
        parser.set_hook("gallery", CoreTagHooks.gallery)
        parser.set_hook("indicator", CoreTagHooks.indicator)
        parser.set_hook("langconvert", CoreTagHooks.langconvert)
        if raw_html:
            parser.set_hook("html", CoreTagHooks.html)

    @staticmethod
    def pre(content: Optional[str], attribs: dict, parser, frame=None) -> str:
        """Core parser tag hook function for 'pre'. Text is treated roughly as 'nowiki' wrapped in an HTML 'pre'
        tag; valid HTML attributes are passed on."""
        from .sanitizer import validate_tag_attributes
        from .stringutils import delimiter_replace

        # Backwards-compatibility hack
        content = delimiter_replace("<nowiki>", "</nowiki>", "$1", content or "", "i")

        attribs = validate_tag_attributes(attribs, "pre", config=parser.config)
        # We need to let both '"' and '&' through, for strip markers and entities respectively.
        content = content.replace(">", "&gt;").replace("<", "&lt;")
        return raw_element("pre", attribs, content)

    @staticmethod
    def html(content: Optional[str], attributes: dict, parser, frame=None) -> Union[dict, str]:
        """Core parser tag hook function for 'html', used only when $wgRawHtml is enabled. This is potentially
        unsafe and should be used only in very careful circumstances, as the contents are emitted as raw HTML."""
        if parser.config.raw_html:
            # ParserOptions::getAllowUnsafeRawHtml() is true by default (it is false only for system messages)
            return {0: content or "", "markerType": "nowiki"}
        raise MWException("<html> extension tag encountered unexpectedly")

    @staticmethod
    def nowiki(content: Optional[str], attributes: dict, parser, frame=None) -> dict:
        """Core parser tag hook function for 'nowiki'. Text within this section gets interpreted as a string of
        text with HTML-compatible character references, and wiki markup within it will not be expanded."""
        from .stringutils import php_strtr

        content = php_strtr(content or "", {
            # lang converter
            "-{": "-&#123;",
            "}-": "&#125;-",
            # html tags
            "<": "&lt;",
            ">": "&gt;",
            # Note: Both '"' and '&' are not converted. This allows strip markers and entities through.
        })
        return {0: content, "markerType": "nowiki"}

    @staticmethod
    def gallery(content: Optional[str], attributes: dict, parser, frame=None) -> str:
        """Core parser tag hook function for 'gallery'. Renders a thumbnail list of the given images, with optional
        captions."""
        return parser.render_image_gallery(content or "", attributes)

    @staticmethod
    def indicator(content: Optional[str], attributes: dict, parser, frame=None) -> str:
        """XML-style tag for page status indicators: icons (or short text snippets) usually displayed in the
        top-right corner of the page, outside of the main content."""
        if attributes.get("name") is None or _php_trim(attributes["name"]) == "":
            return '<span class="error">' + _msg("invalid-indicator-name") + "</span>"

        parser.get_output().indicators[_php_trim(attributes["name"])] = strip_outer_paragraph(
            parser.recursive_tag_parse_fully(content or "", frame))
        return ""

    @staticmethod
    def langconvert(content: Optional[str], attributes: dict, parser, frame=None) -> str:
        """Returns content converted into the requested language variant, using LanguageConverter. No language
        converter is ported (English has no variants), so every language counts as having none: always the error
        message."""
        return raw_element("span", {"class": "error"}, _msg("invalid-langconvert-attrs"))


class PreprocessingMixin:
    """The template, argument, parser function and extension tag half of MediaWiki's Parser."""

    # ---- state ------------------------------------------------------------------------------------------------

    def _register_preprocessing(self) -> None:
        """What Parser::__construct() sets up once: the hook registries, the preprocessor, the magic word arrays
        (initializeVariables()), CoreParserFunctions (a module coreparserfunctions.py with register(parser), if
        present) and CoreTagHooks."""
        self._preprocessing_registered = True
        self.tag_hooks: dict[str, Callable] = {}
        self.function_hooks: dict[str, tuple[Callable, int]] = {}
        self.function_synonyms: dict[int, dict[str, str]] = {0: {}, 1: {}}
        self.strip_list: list[str] = []
        self.var_cache: dict[str, object] = {}
        self.marker_index = 0
        self._current_revision_cache: dict[str, Optional[str]] = {}
        self.preprocessor = Preprocessor(self)
        # initializeVariables(): the magic variables (like CURRENTMONTHNAME) and substitution modifiers
        self.variables = self.magic_words.new_array(self.magic_words.get_variable_ids())
        self.subst_words = self.magic_words.new_array(self.magic_words.get_subst_ids())
        if importlib.util.find_spec(__package__ + ".coreparserfunctions") is not None:
            from . import coreparserfunctions

            coreparserfunctions.register(self)
        CoreTagHooks.register(self)

    def _ensure_preprocessing_registered(self) -> None:
        if not getattr(self, "_preprocessing_registered", False):
            self._register_preprocessing()

    def _init_preprocessing(self, output_type: int = OT_HTML, text: Optional[str] = None) -> None:
        """The preprocessing part of Parser::startParse() and clearState(), at the start of each parse: the output
        type and the per-parse state. ``text``: the input, for mInputSize ({{PAGESIZE}} of the current page)."""
        self._ensure_preprocessing_registered()
        self.set_output_type(output_type)
        self.var_cache = {}
        self._current_revision_cache = {}
        # Clear these on every parse, T6549
        self.tpl_redir_cache: dict[str, tuple[int, str]] = {}
        self.tpl_dom_cache: dict[str, object] = {}
        self.include_sizes = {"post-expand": 0, "arg": 0}
        self.pp_node_count = 0
        self.highest_expansion_depth = 0
        self.headings: list = []
        self.expensive_function_count = 0
        self.input_size = _strlen(text) if text is not None else False

    def finish_preprocessing(self) -> None:
        """The end of Parser::parse() that concerns preprocessing: warn if too many heavyweight parser functions
        were used."""
        limit = self.config.expensive_parser_function_limit
        if self.expensive_function_count > limit:
            self.limitation_warn("expensive-parserfunction", self.expensive_function_count, limit)

    def get_output_type(self) -> int:
        return self.output_type

    def set_output_type(self, ot: int) -> None:
        """Mutator for the output type (one of the OT_* constants)"""
        self.output_type = ot
        # Shortcut alias
        self.ot = {
            "html": ot == OT_HTML,
            "wiki": ot == OT_WIKI,
            "pre": ot == OT_PREPROCESS,
            "plain": ot == OT_PLAIN,
        }

    def _preprocessing_site(self) -> Site:
        site = getattr(self, "site", None)
        if site is None:
            site = getattr(self, "_default_site", None)
            if site is None or site.config is not self.config:
                site = self._default_site = Site(self.config)
        return site

    def get_title(self) -> Title:
        """The page being parsed, as a Title (``self.title`` may be a Title or its text); Special:Badtitle/Parser if
        there is none. The fragment is stripped."""
        title = self.title
        if isinstance(title, Title):
            t = title
        else:
            cached = getattr(self, "_title_cache", None)
            if cached is not None and cached[0] == title and cached[1] is self._preprocessing_site():
                return cached[2]
            site = self._preprocessing_site()
            t = Title.new_from_text(title, site=site) if title else None
            if t is None:
                t = Title.make_title(NS_SPECIAL, "Badtitle/Parser", site=site)
        if t.has_fragment():
            # Strip the fragment to avoid various odd effects
            t = t.create_fragment_target("")
        if not isinstance(title, Title):
            self._title_cache = (title, self._preprocessing_site(), t)
        return t

    def get_output(self):
        return self.output

    def get_preprocessor(self) -> Preprocessor:
        """Get a preprocessor object"""
        self._ensure_preprocessing_registered()
        return self.preprocessor

    def get_strip_list(self) -> list[str]:
        """Get a list of strippable XML-like elements"""
        self._ensure_preprocessing_registered()
        return self.strip_list

    def get_strip_state(self):
        return self.strip_state

    def insert_strip_item(self, text: str) -> str:
        """Add an item to the strip state. Returns the unique tag which must be inserted into the stripped text.
        The tag will be replaced with the original text in unstrip()"""
        marker = f"{MARKER_PREFIX}-item-{self.marker_index}-{MARKER_SUFFIX}"
        self.marker_index += 1
        self.strip_state.add_general(marker, text)
        return marker

    def limitation_warn(self, limitation_type: str, current="", max_="") -> None:
        """Warn the user when a parser limitation is reached. ``limitation_type``: 'expensive-parserfunction',
        'post-expand-template-argument', 'post-expand-template-inclusion', 'node-count-exceeded' or
        'expansion-depth-exceeded'."""
        # does no harm if current and max are present but are unnecessary for the message
        self.output.add_warning_msg(f"{limitation_type}-warning", current, max_)
        self.add_tracking_category(f"{limitation_type}-category")

    def add_tracking_category(self, msg: str) -> bool:
        """Add a tracking category, by the message key of its name (TrackingCategories::addTrackingCategory())"""
        self.output.add_tracking_category(msg)
        return True

    def _increment_include_size(self, type_: str, size: int) -> bool:
        """Increment an include size counter. False if this inclusion would take it over the maximum
        (ParserOptions::getMaxIncludeSize(): $wgMaxArticleSize kibibytes), true otherwise."""
        if self.include_sizes[type_] + size > self.config.get_max_include_size():
            return False
        self.include_sizes[type_] += size
        return True

    def increment_expensive_function_count(self) -> bool:
        """False if the limit has been exceeded"""
        self.expensive_function_count += 1
        return self.expensive_function_count <= self.config.expensive_parser_function_limit

    # ---- hooks ------------------------------------------------------------------------------------------------

    def set_hook(self, tag: str, callback: Callable) -> Optional[Callable]:
        """Create an HTML-style tag, e.g. "<yourtag>special text</yourtag>". The callback is called as
        ``callback(text, params, parser, frame)``; it returns HTML, or a dict whose key 0 is the HTML and whose
        "markerType" ('nowiki', 'general' or 'none') overrides which strip array the result is placed in. Returns
        the previous callback of the tag."""
        self._ensure_preprocessing_registered()
        tag = tag.translate(_ASCII_LOWER)
        m = re.search(r"[<>\r\n]", tag)
        if m:
            raise MWException(f"Invalid character {m.group(0)} in setHook('{tag}', ...) call")
        old_val = self.tag_hooks.get(tag)
        self.tag_hooks[tag] = callback
        if tag not in self.strip_list:
            self.strip_list.append(tag)
        return old_val

    def clear_tag_hooks(self) -> None:
        """Remove all tag hooks"""
        self._ensure_preprocessing_registered()
        self.tag_hooks = {}
        self.strip_list = []

    def set_function_hook(self, id_: str, callback: Callable, flags: int = 0) -> Optional[Callable]:
        """Create a function, e.g. {{sum:1|2|3}}, for the magic word ``id_``. The callback is called as
        ``callback(parser, arg1, arg2, ...)`` with the expanded, trimmed arguments, or with SFH_OBJECT_ARGS as
        ``callback(parser, frame, args)`` where args[0] is the expanded text before the first pipe and the others
        are PPNodes. It returns the text, or a dict with the text in key 0 (or "text") and flags: found, nowiki,
        isHTML, noparse (default true), preprocessFlags, isChildObj, isLocalObj, title, forceRawInterwiki.
        ``flags``: SFH_NO_HASH (no leading hash, i.e. {{plural:...}} instead of {{#if:...}}) and SFH_OBJECT_ARGS.
        Returns the previous callback."""
        self._ensure_preprocessing_registered()
        old = self.function_hooks.get(id_)
        old_val = old[0] if old else None
        self.function_hooks[id_] = (callback, flags)

        # Add to function cache
        try:
            mw = self.magic_words.get(id_)
        except KeyError:
            raise MWException("Parser::setFunctionHook() expecting a magic word identifier.") from None

        synonyms = mw.synonyms
        sensitive = int(bool(mw.case_sensitive))

        for syn in synonyms:
            # Case
            if not sensitive:
                syn = syn.lower()  # Language::lc()
            # Add leading hash
            if not flags & SFH_NO_HASH:
                syn = "#" + syn
            # Remove trailing colon
            if syn[-1:] == ":":
                syn = syn[:-1]
            self.function_synonyms[sensitive][syn] = id_
        return old_val

    def get_function_hooks(self) -> list[str]:
        """Get all registered function hook identifiers"""
        self._ensure_preprocessing_registered()
        return list(self.function_hooks)

    def get_tags(self) -> list[str]:
        self._ensure_preprocessing_registered()
        return list(self.tag_hooks)

    def get_function_synonyms(self) -> dict[int, dict[str, str]]:
        self._ensure_preprocessing_registered()
        return self.function_synonyms

    # ---- hook points filled by other modules -------------------------------------------------------------------

    def get_variable_value(self, index: str, frame=None):
        """The value of the magic variable ``index`` (CoreMagicVariables::expand(), ported elsewhere); None means
        it is not a known variable, and braceSubstitution() then goes on as for a template."""
        return None

    def render_image_gallery(self, text: str, params: dict) -> str:
        """Parser::renderImageGallery(): render an image gallery from a text with one line per image (ported in
        gallery.py)."""
        from .gallery import render_image_gallery

        return render_image_gallery(self, text, params)

    # ---- entry points -----------------------------------------------------------------------------------------

    def recursive_tag_parse(self, text: str, frame=None) -> str:
        """Half-parse wikitext to half-parsed HTML. This recursive parser entry point can be called from an
        extension tag hook. If ``frame`` is not provided, then template variables (e.g., {{{1}}}) within text are
        not expanded."""
        return self.internal_parse(text, False, frame)

    def recursive_tag_parse_fully(self, text: str, frame=None) -> str:
        """Fully parse wikitext to fully parsed HTML. This recursive parser entry point can be called from an
        extension tag hook."""
        text = self.recursive_tag_parse(text, frame)
        return self.internal_parse_half_parsed(text, False)

    def recursive_preprocess(self, text: str, frame=None) -> str:
        """Recursive parser entry point that can be called from an extension tag hook."""
        text = self.replace_variables(text, frame)
        return self.strip_state.unstrip_both(text)

    def replace_variables_for_internal_parse(self, text: str, frame=None) -> str:
        """The start of Parser::internalParse(): with a frame, expand the text in it (as an included document if
        the frame is a template's), else replace_variables()."""
        # if frame is provided, then use frame for replacing any variables
        if frame:
            # use frame depth to infer how include/noinclude tags should be handled
            # depth=0 means this is the top-level document; otherwise it's an included document
            flag = 0 if not frame.depth else DOM_FOR_INCLUSION
            dom = self.preprocess_to_dom(text, flag)
            return frame.expand(dom)
        # if frame is not provided, then use old-style replaceVariables
        return self.replace_variables(text)

    def attribute_strip_callback(self, text: str, frame=None) -> str:
        """Callback from the Sanitizer for expanding items found in HTML attribute values, so they can be safely
        tested and escaped."""
        text = self.replace_variables(text, frame)
        return self.strip_state.unstrip_both(text)

    def preprocess_to_dom(self, text: str, flags: int = 0) -> PPNode_Hash_Tree:
        """Get the document object model for the given wikitext. The generated DOM tree must depend only on the
        input text and the flags."""
        return self.get_preprocessor().preprocess_to_obj(text, flags)

    def replace_variables(self, text: str, frame=None, args_only: bool = False) -> str:
        """Replace magic variables, templates, and template arguments with the appropriate text. Templates are
        substituted recursively, taking care to avoid infinite loops.

        Note that the substitution depends on value of output_type:
          OT_WIKI: only {{subst:}} templates
          OT_PREPROCESS: templates but not extension tags
          OT_HTML: all templates and extension tags

        ``frame``: a Frame, or a dict of the arguments (a custom frame); ``args_only``: only do argument
        (triple-brace) expansion, not double-brace expansion."""
        # Is there any text? Also, Prevent too big inclusions!
        text_size = _strlen(text)
        if text_size < 1 or text_size > self.config.get_max_include_size():
            return text

        if frame is None or frame is False:
            frame = self.get_preprocessor().new_frame()
        elif not isinstance(frame, Frame):
            frame = self.get_preprocessor().new_custom_frame(frame)

        dom = self.preprocess_to_dom(text)
        flags = NO_TEMPLATES if args_only else 0
        return frame.expand(dom, flags)

    # ---- templates --------------------------------------------------------------------------------------------

    def expand_magic_variable(self, index: str, frame=None):
        """Return value of a magic variable (like PAGENAME). Some of these require message or data lookups and can
        be expensive to check many times."""
        if self.var_cache.get(index) is not None:
            return self.var_cache[index]
        value = self.get_variable_value(index, frame)
        if value is not None:
            self.var_cache[index] = value
        return value

    def brace_substitution(self, piece: dict, frame: Frame) -> dict:
        """Return the text of a template, after recursively replacing any variables or templates within the
        template. ``piece``: the parts of the template: 'title', the title, i.e. the part before the |; 'parts',
        the parameter array; 'lineStart', whether the brace was at the start of a line. Returns {'text': ...} or
        {'object': node to expand in the current frame}."""
        site = self._preprocessing_site()
        # Flags

        # text has been filled
        found = False
        text: object = ""
        # wiki markup in text should be escaped
        nowiki = False
        # text is HTML, armour it against wikitext transformation
        is_html = False
        # Force interwiki transclusion to be done in raw mode not rendered
        force_raw_interwiki = False
        # text is a DOM node needing expansion in a child frame
        is_child_obj = False
        # text is a DOM node needing expansion in the current frame
        is_local_obj = False

        # Title object, where text came from
        title = None

        # part1 is the bit before the first |, and must contain only title characters.
        # Various prefixes will be stripped from it later.
        title_with_spaces = frame.expand(piece["title"])
        part1 = _php_trim(title_with_spaces)
        title_text: Union[str, bool] = False

        # Original title text preserved for various purposes
        original_title = part1

        # args is a list of argument nodes, starting from index 0, not including part1
        args = piece["parts"] if piece.get("parts") is not None else PPNode_Hash_Array([])

        saw_deprecated_template_equals = False  # T91154

        # SUBST
        if not found:
            subst_match, part1 = self.subst_words.match_start_and_remove(part1)

            # Possibilities for subst_match: "subst", "safesubst" or False
            # Decide whether to expand template or keep wikitext as-is.
            if self.ot["wiki"]:
                literal = subst_match is False  # literal when in PST with no prefix; expand with subst: or safesubst:
            else:
                literal = subst_match == "subst"  # literal when not in PST with plain subst:
            if literal:
                text = frame.virtual_bracketed_implode("{{", "|", "}}", title_with_spaces, args)
                is_local_obj = True
                found = True

        # Variables
        if not found and args.get_length() == 0:
            id_ = self.variables.match_start_to_end(part1)
            if id_ is not False:
                value = self.expand_magic_variable(id_, frame)
                # (No cache expiry: there is no parser cache.) None: get_variable_value() does not know the variable
                if value is not None:
                    text = value
                    found = True

        # MSG, MSGNW and RAW
        if not found:
            # Check for MSGNW:
            matched, part1 = self.magic_words.get("msgnw").match_start_and_remove(part1)
            if matched:
                nowiki = True
            else:
                # Remove obsolete MSG:
                _, part1 = self.magic_words.get("msg").match_start_and_remove(part1)

            # Check for RAW:
            matched, part1 = self.magic_words.get("raw").match_start_and_remove(part1)
            if matched:
                force_raw_interwiki = True

        # Parser functions
        if not found:
            colon_pos = part1.find(":")
            if colon_pos != -1:
                func = part1[:colon_pos]
                func_args: list = [_php_trim(part1[colon_pos + 1:])]
                for i in range(args.get_length()):
                    func_args.append(args.item(i))

                result = self.call_parser_function(frame, func, func_args)

                # Extract any forwarded flags
                if _isset(result, "title"):
                    title = result["title"]
                if _isset(result, "found"):
                    found = result["found"]
                if "text" in result:
                    # a string or null
                    text = result["text"]
                if _isset(result, "nowiki"):
                    nowiki = result["nowiki"]
                if _isset(result, "isHTML"):
                    is_html = result["isHTML"]
                if _isset(result, "forceRawInterwiki"):
                    force_raw_interwiki = result["forceRawInterwiki"]
                if _isset(result, "isChildObj"):
                    is_child_obj = result["isChildObj"]
                if _isset(result, "isLocalObj"):
                    is_local_obj = result["isLocalObj"]

        # Finish mangling title and then check for loops.
        # Set title to a Title object and title_text to the PDBK
        if not found:
            ns = NS_TEMPLATE
            # Split the title into page and subpage
            relative, _ = normalize_subpage_link(self.get_title(), part1, "", site)
            if part1 != relative:
                part1 = relative
                ns = self.get_title().namespace
            title = Title.new_from_text(part1, ns, site=site)
            if title:
                title_text = title.prefixed_text
                # (Language variants: English has none.)
                # Do recursion depth check
                limit = self.config.max_template_depth
                if frame.depth >= limit:
                    found = True
                    text = ('<span class="error">'
                            + _msg("parser-template-recursion-depth-warning", f"{limit:,}") + "</span>")

        # Load from database
        if not found and title:
            if not title.is_external():
                if title.is_special_page() and self.ot["html"]:
                    # $wgAllowSpecialInclusion is true, but special pages are not ported: the page is not found,
                    # as for a special page that cannot be included
                    pass
                # NamespaceInfo::isNonincludable(): $wgNonincludableNamespaces is empty
                else:
                    text, title = self.get_template_dom(title)
                    if text is not False:
                        found = True
                        is_child_obj = True
                        if title.namespace == NS_TEMPLATE and title.db_key == "=" and original_title == "=":
                            # Note that we won't get here if `=` is evaluated (in the future) as a parser function,
                            # nor if the Template namespace is given explicitly, ie `{{Template:=}}`. Only `{{=}}`
                            # triggers.
                            saw_deprecated_template_equals = True  # T91154

                # If the title is valid but undisplayable, make a link to it
                if not found and (self.ot["html"] or self.ot["pre"]):
                    text = f"[[:{title_text}]]"
                    found = True
            elif title.is_trans():
                # Interwiki transclusion
                if self.ot["html"] and not force_raw_interwiki:
                    text = self.interwiki_transclude(title, "render")
                    is_html = True
                else:
                    text = self.interwiki_transclude(title, "raw")
                    # Preprocess it like a template
                    text = self.preprocess_to_dom(text, DOM_FOR_INCLUSION)
                    is_child_obj = True
                found = True

            # Do infinite loop check
            # This has to be done after redirect resolution to avoid infinite loops via redirects
            if not frame.loop_check(title):
                found = True
                text = '<span class="error">' + _msg("parser-template-loop-warning", title_text) + "</span>"
                self.add_tracking_category("template-loop-category")
                self.output.add_warning_msg("template-loop-warning", title_text)

        # If we haven't found text to substitute by now, we're done
        # Recover the source wikitext and return it
        if not found:
            return {"object": frame.virtual_bracketed_implode("{{", "|", "}}", title_with_spaces, args)}

        # Expand DOM-style return values in a child frame
        if is_child_obj:
            # Clean up argument array
            new_frame = frame.new_child(args, title if title else None)

            if nowiki:
                text = new_frame.expand(text, RECOVER_ORIG)
            elif title_text is not False and new_frame.is_empty():
                # Expansion is eligible for the empty-frame cache
                text = new_frame.cached_expand(title_text, text)
            else:
                # Uncached expansion
                text = new_frame.expand(text)
        if is_local_obj and nowiki:
            text = frame.expand(text, RECOVER_ORIG)
            is_local_obj = False

        if saw_deprecated_template_equals and self.strip_state.unstrip_both(text) != "=":
            # T91154: {{=}} is deprecated when it doesn't expand to `=`; use {{Template:=}} if you must.
            self.add_tracking_category("template-equals-category")
            self.output.add_warning_msg("template-equals-warning")

        # Replace raw HTML by a placeholder
        if is_html:
            text = self.insert_strip_item(text)
        elif nowiki and (self.ot["html"] or self.ot["pre"]):
            # Escape nowiki-style return values
            text = wf_escape_wiki_text(text, self.config)
        elif isinstance(text, str) and not piece.get("lineStart") and re.match(r"(?:\{\||:|;|#|\*)", text):
            # T2529: if the template begins with a table or block-level element, it should be treated as beginning
            # a new line. This behavior is somewhat controversial.
            text = "\n" + text

        if isinstance(text, str) and not self._increment_include_size("post-expand", _strlen(text)):
            # Error, oversize inclusion
            if title_text is not False:
                # Make a working, properly escaped link if possible (T25588)
                text = f"[[:{title_text}]]"
            else:
                # This will probably not be a working link, but at least it may provide some hint of where the
                # problem is
                original_title = re.sub(r"^:", "", original_title)
                text = f"[[:{original_title}]]"
            text += self.insert_strip_item("<!-- WARNING: template omitted, post-expand include size too large -->")
            self.limitation_warn("post-expand-template-inclusion")

        if is_local_obj:
            return {"object": text}
        return {"text": text}

    def call_parser_function(self, frame: Frame, function: str, args=()) -> dict:
        """Call a parser function and return a dict with text and flags.

        The returned dict will always contain a boolean 'found', indicating whether the parser function was found
        or not. It may also contain the following:
          text: str|object, resulting wikitext or PP DOM object
          isHTML: bool, text is HTML, armour it against wikitext transformation
          isChildObj: bool, text is a DOM node needing expansion in a child frame
          isLocalObj: bool, text is a DOM node needing expansion in the current frame
          nowiki: bool, wiki markup in text should be escaped

        ``args``: the arguments to the function, a list or a dict (keys as in PHP)."""
        self._ensure_preprocessing_registered()
        # Case sensitive functions
        if function in self.function_synonyms[1]:
            function = self.function_synonyms[1][function]
        else:
            # Case insensitive functions
            function = function.lower()  # Language::lc()
            if function in self.function_synonyms[0]:
                function = self.function_synonyms[0][function]
            else:
                return {"found": False}

        callback, flags = self.function_hooks[function]

        items = [(_php_key(k), v) for k, v in args.items()] if isinstance(args, dict) else list(enumerate(args))
        if flags & SFH_OBJECT_ARGS:
            # Convert arguments to PPNodes and collect for appending to all_args
            func_args = []
            for k, v in items:
                if isinstance(v, _PPNODE) or (isinstance(k, int) and k == 0):
                    func_args.append(v)
                else:
                    func_args.append(self.preprocessor.new_part_node_array({k: v}).item(0))

            # Add a frame parameter, and pass the arguments as an array
            result = callback(self, frame, func_args)
        else:
            # Convert arguments to plain text and append to all_args
            all_args = []
            for k, v in items:
                if isinstance(v, _PPNODE):
                    all_args.append(_php_trim(frame.expand(v)))
                elif isinstance(k, int) and k >= 0:
                    all_args.append(_php_trim(v))
                else:
                    all_args.append(_php_trim(f"{k}={v}"))
            # PHP drops the arguments a userland function does not declare ({{#explode:a|b|0|0|extra}})
            limit = _max_positional(callback)
            if limit is not None:
                all_args = all_args[:limit - 1]
            result = callback(self, *all_args)

        # The interface for function hooks allows them to return a wikitext string or a dict containing the string
        # and any flags. This mungs things around to match what this method should return.
        if not isinstance(result, dict):
            result = {"found": True, "text": result}
        else:
            result = dict(result)
            if _isset(result, 0) and not _isset(result, "text"):
                result["text"] = result[0]
            result.pop(0, None)
            result.setdefault("found", True)

        noparse = True
        preprocess_flags = 0
        if _isset(result, "noparse"):
            noparse = result["noparse"]
        if _isset(result, "preprocessFlags"):
            preprocess_flags = result["preprocessFlags"]

        if not noparse:
            result["text"] = self.preprocess_to_dom(result["text"], preprocess_flags)
            result["isChildObj"] = True
        return result

    @staticmethod
    def _page_key(title: Title) -> str:
        """CacheKeyHelper::getKeyForPage()"""
        return f"{title.namespace}:{title.db_key}"

    def get_template_dom(self, title: Title) -> tuple[object, Title]:
        """Get the semi-parsed DOM representation of a template with a given title, and its redirect destination
        title. Cached."""
        cache_title = title
        title_key = self._page_key(title)

        if title_key in self.tpl_redir_cache:
            ns, dbk = self.tpl_redir_cache[title_key]
            title = Title.make_title(ns, dbk, site=self._preprocessing_site())
            title_key = self._page_key(title)
        if title_key in self.tpl_dom_cache:
            return self.tpl_dom_cache[title_key], title

        # Cache miss, go to the database
        text, title = self.fetch_template_and_title(title)

        if text is False:
            self.tpl_dom_cache[title_key] = False
            return False, title

        dom = self.preprocess_to_dom(text, DOM_FOR_INCLUSION)
        self.tpl_dom_cache[title_key] = dom

        if not (title.namespace == cache_title.namespace and title.db_key == cache_title.db_key):
            self.tpl_redir_cache[self._page_key(cache_title)] = (title.namespace, title.db_key)

        return dom, title

    def _page_index(self) -> dict[str, str]:
        """``pages`` by normalised prefixed title (built once per mapping), for keys not written as Title does."""
        pages = self.pages
        cached = getattr(self, "_page_index_cache", None)
        if cached is not None and cached[0] is pages and cached[1] == len(pages):
            return cached[2]
        site = self._preprocessing_site()
        index: dict[str, str] = {}
        for key, text in pages.items():
            t = Title.new_from_text(key, site=site)
            if t is not None:
                index.setdefault(t.prefixed_text, text)
        self._page_index_cache = (pages, len(pages), index)
        return index

    def fetch_current_revision_text(self, title: Title) -> Optional[str]:
        """fetchCurrentRevisionRecordOfTitle(): the current text of a page, None if there is no such page. Pages
        come from ``self.pages`` (prefixed title with spaces -> wikitext)."""
        key = title.prefixed_text
        if key not in self._current_revision_cache:
            text = self.pages.get(key)
            if text is None and not title.is_external() and title.namespace >= 0:
                text = self._page_index().get(key)
            self._current_revision_cache[key] = text
        return self._current_revision_cache[key]

    def fetch_template_and_title(self, title: Title) -> tuple[Union[str, bool], Title]:
        """Fetch the unparsed text of a template and register a reference to it. Returns (text or False, Title)."""
        stuff = self.stateless_fetch_template(title)
        text = stuff["text"]
        if isinstance(text, str):
            # We use U+007F DELETE to distinguish strip markers from regular text
            text = text.replace("\x7f", "?")
        final_title = stuff.get("finalTitle") or title
        for dep in stuff.get("deps", []):
            self.output.add_template(dep["title"].prefixed_text)
        return text, final_title

    def stateless_fetch_template(self, title: Title) -> dict:
        """Parser::statelessFetchTemplate(): get a template, following up to two redirects. Returns {'text': str or
        False, 'finalTitle': Title, 'deps': [{'title': Title}, ...]}."""
        text = False
        final_title = title
        deps = []

        # Loop to fetch the article, with up to 2 redirects
        for _ in range(3):
            if title is None:
                break
            # Get the revision
            content = self.fetch_current_revision_text(title)
            deps.append({"title": title})
            if content is not None:
                text = content  # Content::getWikitextForTransclusion()
            elif title.namespace == NS_MEDIAWIKI:
                from .messages import MESSAGES

                key = title.text.replace(" ", "_")
                message = MESSAGES.get(key[:1].lower() + key[1:])
                if message is None:
                    text = False
                    break
                text = message
                break
            else:
                break
            # Redirect?
            final_title = title
            title = self.get_redirect_target(content)

        return {"text": text, "finalTitle": final_title, "deps": deps}

    def get_redirect_target(self, text: str) -> Optional[Title]:
        """WikitextContent::getRedirectTarget(): the target of a "#REDIRECT [[...]]" page, None if it is not a
        redirect."""
        redir = self.magic_words.get("redirect")
        text = text.lstrip(" \t\n\r\0\x0b")
        matched, text = redir.match_start_and_remove(text)
        if matched:
            # Extract the first link and see if it's usable
            # Ensure that it really does come directly after #REDIRECT
            # Some older redirects included a colon, so don't freak about that!
            m = re.match(rf"{_WS}*:?{_WS}*\[{{2}}(.*?)(?:\|.*?)?\]{{2}}{_WS}*", text)
            if m:
                target = m.group(1)
                # Strip preceding colon used to "escape" categories, etc. and URL-decode links
                if "%" in target:
                    # Match behavior of inline link parsing here;
                    target = urllib.parse.unquote(target.lstrip(":"))
                title = Title.new_from_text(target, site=self._preprocessing_site())
                # If the title is a redirect to bad special pages or is invalid, return None
                if title is None or not is_valid_redirect_target(title):
                    return None
                return title
        return None

    def interwiki_transclude(self, title: Title, action: str) -> str:
        """Transclude an interwiki link: disabled, as $wgEnableScaryTranscluding is false by default."""
        return _msg("scarytranscludedisabled")

    def arg_substitution(self, piece: dict, frame: Frame) -> dict:
        """Triple brace replacement -- used for template arguments"""
        error = False
        parts = piece["parts"]
        name_with_spaces = frame.expand(piece["title"])
        arg_name = _php_trim(name_with_spaces)
        obj = None
        text = frame.get_argument(arg_name)
        if (text is False and parts.get_length() > 0
                and (self.ot["html"] or self.ot["pre"] or (self.ot["wiki"] and frame.is_template()))):
            # No match in frame, use the supplied default
            obj = parts.item(0).get_children()
        if not self._increment_include_size("arg", _strlen(text)):
            error = "<!-- WARNING: argument omitted, expansion size too large -->"
            self.limitation_warn("post-expand-template-argument")

        if text is False and obj is None:
            # No match anywhere
            obj = frame.virtual_bracketed_implode("{{{", "|", "}}}", name_with_spaces, parts)
        if error is not False:
            text = ("" if text is False else text) + error
        if obj is not None:
            return {"object": obj}
        return {"text": text}

    def extension_substitution(self, params: dict, frame: Frame, process_nowiki: bool = False) -> str:
        """Return the text to be used for a given extension tag. This is the ghost of strip().

        ``params``: name (PPNode for the tag name), attr (PPNode for unparsed text where tag attributes are thought
        to be), attributes (optional dict of parsed attributes), inner (contents of extension element), noClose
        (original text did not have a close tag). ``process_nowiki``: process nowiki tags by running the nowiki tag
        handler. Normally, nowikis are only processed for the HTML output type. With this arg set to true, they are
        processed (and converted to a nowiki strip marker) for all output types."""
        self._ensure_preprocessing_registered()
        name = frame.expand(params["name"])
        if name.startswith(_ERROR_STR):
            # Probably expansion depth or node count exceeded. Just punt the error up.
            return name

        attr_text = "" if params.get("attr") is None else frame.expand(params["attr"])
        if attr_text.startswith(_ERROR_STR):
            # See above
            return attr_text

        # We can't safely check if the expansion for content resulted in an error, because the content could
        # happen to be the error string (T149622).
        content = None if params.get("inner") is None else frame.expand(params["inner"])

        marker = f"{MARKER_PREFIX}-{name}-{self.marker_index:08X}{MARKER_SUFFIX}"
        self.marker_index += 1

        normalized_name = name.translate(_ASCII_LOWER)
        is_nowiki = normalized_name == "nowiki"
        marker_type = "nowiki" if is_nowiki else "general"
        if self.ot["html"] or (process_nowiki and is_nowiki):
            from .sanitizer import decode_tag_attributes

            name = normalized_name
            attributes = decode_tag_attributes(attr_text)
            if params.get("attributes") is not None:
                for key, value in params["attributes"].items():
                    attributes.setdefault(key, value)

            if name in self.tag_hooks:
                # Note that content may be None here, for example if the tag is self-closed.
                output = self.tag_hooks[name](content, attributes, self, frame)
            else:
                output = '<span class="error">Invalid tag extension name: ' + htmlspecialchars(name) + "</span>"

            if isinstance(output, dict):
                # Extract flags
                flags = output
                output = flags[0]
                if flags.get("markerType") is not None:
                    marker_type = flags["markerType"]
        else:
            if params.get("attributes") is not None:
                for attr_name, attr_value in params["attributes"].items():
                    attr_text += " " + htmlspecialchars(attr_name) + '="' + htmlspecialchars(attr_value, False) + '"'
            if content is None:
                output = f"<{name}{attr_text}/>"
            else:
                close = "" if params.get("close") is None else frame.expand(params["close"])
                if close.startswith(_ERROR_STR):
                    # See above
                    return close
                output = f"<{name}{attr_text}>{content}{close}"

        if marker_type == "none":
            return output
        elif marker_type == "nowiki":
            self.strip_state.add_no_wiki(marker, output)
        elif marker_type == "general":
            self.strip_state.add_general(marker, output)
        else:
            raise MWException("Parser::extensionSubstitution: invalid marker type")
        return marker

    # ---- strip markers ----------------------------------------------------------------------------------------

    @staticmethod
    def marker_skip_callback(s: str, callback: Callable[[str], str]) -> str:
        """Call a callback function on all regions of the given text that are not inside strip markers, and
        replace those regions with the return value of the callback. For example, with input:

          aaa<MARKER>bbb

        This will call the callback function twice, with 'aaa' and 'bbb'. Those two strings will be replaced with
        the value returned by the callback in each case."""
        i = 0
        out = ""
        while i < len(s):
            marker_start = s.find(MARKER_PREFIX, i)
            if marker_start == -1:
                out += callback(s[i:])
                break
            out += callback(s[i:marker_start])
            marker_end = s.find(MARKER_SUFFIX, marker_start)
            if marker_end == -1:
                out += s[marker_start:]
                break
            marker_end += len(MARKER_SUFFIX)
            out += s[marker_start:marker_end]
            i = marker_end
        return out

    def kill_markers(self, text: str) -> str:
        """Remove any strip markers found in the given text."""
        return self.strip_state.kill_markers(text)

    # extractTagsAndParams() and stripOuterParagraph() are static in PHP
    extract_tags_and_params = staticmethod(extract_tags_and_params)
    strip_outer_paragraph = staticmethod(strip_outer_paragraph)

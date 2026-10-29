# Ported from MediaWiki 1.39 includes/parser/CoreMagicVariables.php and Parser::expandMagicVariable() of
# includes/parser/Parser.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; English only; the time comes from
# ``parser.timestamp`` (the parser tests' ParserGetVariableValueTs hook fixes it), settings from the parser's Config;
# no hooks, logger or SpecialVersion (CURRENTVERSION is MediaWiki's version string).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Expansions of core magic variables ({{CURRENTYEAR}}, {{PAGENAME}}, {{SITENAME}}, ...), used by the parser.

The parser's hook point is ``get_variable_value(index, frame)``; connect it with::

    def get_variable_value(self, index, frame=None):
        return core_magic_variables.get_variable_value(self, index, frame)

Parser attributes used are described in coreparserfunctions.py.
"""
from __future__ import annotations

import time as time_
from datetime import datetime
from typing import Optional

from . import coreparserfunctions as cpf
from .parser_preprocess import wf_escape_wiki_text
from .site import wf_urlencode

# MW_VERSION (includes/Defines.php at the ported commit), for {{CURRENTVERSION}} (SpecialVersion::getVersion())
MW_VERSION = "1.39.17"

# Assume that no output will later be saved this many seconds after parsing
MAX_TTS = 900


def get_variable_value(parser, id_: str, frame=None) -> Optional[str]:
    """Parser::expandMagicVariable() without its cache (PreprocessingMixin keeps var_cache): the value of the magic
    variable ``id_``, or None if it is not a core magic variable."""
    ts = cpf.to_datetime(getattr(parser, "timestamp", None))
    return expand(parser, id_, ts)


def expand(parser, id_: str, ts: datetime) -> Optional[str]:
    """CoreMagicVariables::expand(): expand the magic variable given by ``id_`` (the magic word ID which was used to
    match the variable) at the time ``ts`` (UTC). Returns None to indicate the given index wasn't a known magic
    variable."""
    page_lang = cpf.get_function_lang(parser)
    title = parser.get_title()
    config = parser.config
    site = title.site

    def date(fmt: str) -> str:
        return cpf.php_date(ts, fmt)

    def local(fmt: str) -> str:
        return cpf.php_date(_make_ts_local(parser, ts), fmt)

    def escape(text: str) -> str:
        return wf_escape_wiki_text(text, config)

    if id_ == "!":
        return "|"
    if id_ == "=":
        return "="
    if id_ == "currentmonth":
        return page_lang.format_num_no_separators(date("m"))
    if id_ == "currentmonth1":
        return page_lang.format_num_no_separators(date("n"))
    if id_ == "currentmonthname":
        return page_lang.get_month_name(int(date("n")))
    if id_ == "currentmonthnamegen":
        return page_lang.get_month_name_gen(int(date("n")))
    if id_ == "currentmonthabbrev":
        return page_lang.get_month_abbreviation(int(date("n")))
    if id_ == "currentday":
        return page_lang.format_num_no_separators(date("j"))
    if id_ == "currentday2":
        return page_lang.format_num_no_separators(date("d"))
    if id_ == "localmonth":
        return page_lang.format_num_no_separators(local("m"))
    if id_ == "localmonth1":
        return page_lang.format_num_no_separators(local("n"))
    if id_ == "localmonthname":
        return page_lang.get_month_name(int(local("n")))
    if id_ == "localmonthnamegen":
        return page_lang.get_month_name_gen(int(local("n")))
    if id_ == "localmonthabbrev":
        return page_lang.get_month_abbreviation(int(local("n")))
    if id_ == "localday":
        return page_lang.format_num_no_separators(local("j"))
    if id_ == "localday2":
        return page_lang.format_num_no_separators(local("d"))
    if id_ == "pagename":
        return escape(title.text)
    if id_ == "pagenamee":
        return escape(title.partial_url)
    if id_ == "fullpagename":
        return escape(title.prefixed_text)
    if id_ == "fullpagenamee":
        return escape(title.prefixed_url)
    if id_ == "subpagename":
        return escape(title.subpage_text)
    if id_ == "subpagenamee":
        return escape(title.subpage_url_form)
    if id_ == "rootpagename":
        return escape(title.root_text)
    if id_ == "rootpagenamee":
        return escape(wf_urlencode(title.root_text.replace(" ", "_")))
    if id_ == "basepagename":
        return escape(title.base_text)
    if id_ == "basepagenamee":
        return escape(wf_urlencode(title.base_text.replace(" ", "_")))
    if id_ == "talkpagename":
        if title.can_have_talk_page():
            return escape(title.get_talk_page().prefixed_text)
        return ""
    if id_ == "talkpagenamee":
        if title.can_have_talk_page():
            return escape(title.get_talk_page().prefixed_url)
        return ""
    if id_ == "subjectpagename":
        return escape(title.get_subject_page().prefixed_text)
    if id_ == "subjectpagenamee":
        return escape(title.get_subject_page().prefixed_url)
    if id_ == "pageid":  # requested in T25427
        # Inform the edit saving system that getting the canonical output after page insertion requires a parse that
        # used that exact page ID
        cpf._set_output_flag(parser, "vary-page-id")
        value = cpf._article_id(parser, title)
        if not value:
            value = getattr(parser, "speculative_page_id", None) or value
        return str(value)
    if id_ == "revisionid":
        if (getattr(config, "miser_mode", False) and not getattr(parser, "interface_message", False)
                # @TODO: disallow this variable on all namespaces
                and site.is_subject(title.namespace)):
            # Use a stub result instead of the actual revision ID in order to avoid double parses on page save but
            # still allow preview detection (T137900)
            if cpf.get_revision_id(parser) or getattr(parser, "speculative_rev_id", None):
                return "-"
            cpf._set_output_flag(parser, "vary-revision-exists")
            return ""
        # Inform the edit saving system that getting the canonical output after revision insertion requires a parse
        # that used that exact revision ID
        cpf._set_output_flag(parser, "vary-revision-id")
        value = cpf.get_revision_id(parser)
        if value == 0:
            rev = cpf.get_revision_record_object(parser)
            value = rev.id if rev else value
        if not value:
            value = getattr(parser, "speculative_rev_id", None) or value
        return cpf._php_strval(value)
    if id_ == "revisionday":
        return str(cpf._php_intval(_get_revision_timestamp_substring(parser, 6, 2, MAX_TTS, id_)))
    if id_ == "revisionday2":
        return _get_revision_timestamp_substring(parser, 6, 2, MAX_TTS, id_)
    if id_ == "revisionmonth":
        return _get_revision_timestamp_substring(parser, 4, 2, MAX_TTS, id_)
    if id_ == "revisionmonth1":
        return str(cpf._php_intval(_get_revision_timestamp_substring(parser, 4, 2, MAX_TTS, id_)))
    if id_ == "revisionyear":
        return _get_revision_timestamp_substring(parser, 0, 4, MAX_TTS, id_)
    if id_ == "revisiontimestamp":
        return _get_revision_timestamp_substring(parser, 0, 14, MAX_TTS, id_)
    if id_ == "revisionuser":
        # Inform the edit saving system that getting the canonical output after revision insertion requires a parse
        # that used the actual user ID
        cpf._set_output_flag(parser, "vary-user")
        # Note that getRevisionUser() can return null; we need to be sure to cast this to (an empty) string, since
        # 'null' means "magic variable not handled here".
        return cpf._php_strval(cpf.get_revision_user(parser))
    if id_ == "revisionsize":
        return cpf._php_strval(cpf.get_revision_size(parser))
    if id_ == "namespace":
        return (site.get_ns_text(title.namespace) or "").replace("_", " ")
    if id_ == "namespacee":
        return wf_urlencode(site.get_ns_text(title.namespace) or "")
    if id_ == "namespacenumber":
        return str(title.namespace)
    if id_ == "talkspace":
        return (title.talk_ns_text or "").replace("_", " ") if title.can_have_talk_page() else ""
    if id_ == "talkspacee":
        return wf_urlencode(title.talk_ns_text or "") if title.can_have_talk_page() else ""
    if id_ == "subjectspace":
        return (title.subject_ns_text or "").replace("_", " ")
    if id_ == "subjectspacee":
        return wf_urlencode(title.subject_ns_text or "")
    if id_ == "currentdayname":
        return page_lang.get_weekday_name(int(date("w")) + 1)
    if id_ == "currentyear":
        return page_lang.format_num_no_separators(date("Y"))
    if id_ == "currenttime":
        return page_lang.time(date("YmdHis"), False, False)
    if id_ == "currenthour":
        return page_lang.format_num_no_separators(date("H"))
    if id_ == "currentweek":
        # @bug T6594 PHP5 has it zero padded, PHP4 does not, cast to int to remove the padding
        return page_lang.format_num(int(date("W")))
    if id_ == "currentdow":
        return page_lang.format_num(date("w"))
    if id_ == "localdayname":
        return page_lang.get_weekday_name(int(local("w")) + 1)
    if id_ == "localyear":
        return page_lang.format_num_no_separators(local("Y"))
    if id_ == "localtime":
        return page_lang.time(local("YmdHis"), False, False)
    if id_ == "localhour":
        return page_lang.format_num_no_separators(local("H"))
    if id_ == "localweek":
        # @bug T6594 PHP5 has it zero padded, PHP4 does not, cast to int to remove the padding
        return page_lang.format_num(int(local("W")))
    if id_ == "localdow":
        return page_lang.format_num(local("w"))
    stats = cpf._site_stats(parser)
    if id_ == "numberofarticles":
        return page_lang.format_num(stats.articles)
    if id_ == "numberoffiles":
        return page_lang.format_num(stats.images)
    if id_ == "numberofusers":
        return page_lang.format_num(stats.users)
    if id_ == "numberofactiveusers":
        return page_lang.format_num(stats.active_users)
    if id_ == "numberofpages":
        return page_lang.format_num(stats.pages)
    if id_ == "numberofadmins":
        return page_lang.format_num(stats.numberingroup("sysop"))
    if id_ == "numberofedits":
        return page_lang.format_num(stats.edits)
    if id_ == "currenttimestamp":
        return date("YmdHis")
    if id_ == "localtimestamp":
        return local("YmdHis")
    if id_ == "currentversion":
        return MW_VERSION
    if id_ == "articlepath":
        return str(config.article_path)
    if id_ == "sitename":
        return str(config.sitename)
    if id_ == "server":
        return str(config.server)
    if id_ == "servername":
        return str(config.server_name)
    if id_ == "scriptpath":
        return str(config.script_path)
    if id_ == "stylepath":
        # $wgStylePath defaults to "$wgResourceBasePath/skins", $wgResourceBasePath to $wgScriptPath
        return str(getattr(config, "style_path", None) or f"{config.script_path}/skins")
    if id_ == "directionmark":
        return page_lang.get_dir_mark()
    if id_ == "contentlanguage":
        return str(config.language_code)
    if id_ == "pagelanguage":
        return str(getattr(parser, "page_language_code", None) or config.language_code)
    if id_ == "cascadingsources":
        return cpf.cascadingsources(parser)
    # This is not one of the core magic variables
    return None


def _make_ts_local(parser, ts: datetime) -> datetime:
    """Helper to convert a timestamp instance to local time ($wgLocaltimezone). @see
    MWTimestamp::getLocalInstance()"""
    return ts.astimezone(cpf.local_zone(parser))


def _get_revision_timestamp_substring(parser, start: int, length: int, mtts: int, variable: str) -> str:
    """``mtts``: max time-till-save; sets vary-revision-timestamp if result changes by then"""
    # Get the timezone-adjusted timestamp to be used for this revision
    res_now = cpf.get_revision_timestamp(parser)[start:start + length]
    # Possibly set vary-revision if there is not yet an associated revision
    if not cpf.get_revision_record_object(parser):
        # Get the timezone-adjusted timestamp $mtts seconds in the future. This future is relative to the current
        # time and not that of the parser options. The rendered timestamp can be compared to that of the timestamp
        # specified by the parser options.
        then = cpf.php_date(cpf.to_datetime(int(time_.time()) + mtts), "YmdHis")
        res_then = cpf.ENGLISH.user_adjust(then, "", cpf.local_tz_offset(parser))[start:start + length]
        if res_now != res_then:
            # Inform the edit saving system that getting the canonical output after revision insertion requires a
            # parse that used an actual revision timestamp
            cpf._set_output_flag(parser, "vary-revision-timestamp")
    return res_now

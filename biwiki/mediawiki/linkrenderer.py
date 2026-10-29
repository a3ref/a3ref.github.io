# Ported from MediaWiki 1.39 includes/linker/LinkRenderer.php, includes/libs/HtmlArmor.php, the alias handling of
# includes/specialpage/SpecialPageFactory.php (CORE_LIST names, resolveAlias(), exists(), getLocalNameFor()) with
# the English aliases of languages/messages/MessagesEn.php ($specialPageAliases), and the existence checks of
# includes/Title.php (exists(), isAlwaysKnown(), isKnown(), hasSourceText()) and includes/cache/LinkCache.php
# (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; a page exists if the caller's ``pages`` mapping
# holds it (no database, no LinkCache rows); redirects are pages whose text starts with #REDIRECT [[...]]; no
# files yet (every file is missing); MediaWiki: messages exist only for a short list of keys; no hooks.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Links to wiki pages: blue, red (new), redirect and interwiki links, and which pages exist."""
from __future__ import annotations

import re
from typing import Mapping, Optional, Union

from .html import htmlspecialchars, raw_element
from .magicword import FACTORY, MagicWordFactory
from .site import NS_FILE, NS_MAIN, NS_MEDIA, NS_MEDIAWIKI, NS_SPECIAL, Site
from .title import Title, wf_append_query


class HtmlArmor:
    """Marks HTML that shouldn't be escaped"""

    def __init__(self, value: Optional[str]):
        self.value = value

    @staticmethod
    def get_html(input_: Union["HtmlArmor", str]) -> str:
        """The HTML of the armored value, or the input string escaped (ENT_QUOTES)."""
        if isinstance(input_, HtmlArmor):
            return input_.value or ""
        return htmlspecialchars(input_)

    def __repr__(self) -> str:
        return f"HtmlArmor({self.value!r})"


# --- special pages ---

# SpecialPageFactory::CORE_LIST, plus the pages getPageList() adds with the default settings: Search
# ($wgDisableInternalSearch false), Confirmemail and Invalidateemail ($wgEmailAuthentication true), ChangeEmail
# ($wgEnableEmail true). Not added by default: JavaScriptTest, Mute, PageLanguage.
CORE_SPECIAL_PAGES = (
    "BrokenRedirects", "Deadendpages", "DoubleRedirects", "Longpages", "Ancientpages", "Lonelypages",
    "Fewestrevisions", "Withoutinterwiki", "Protectedpages", "Protectedtitles", "Shortpages",
    "Uncategorizedcategories", "Uncategorizedimages", "Uncategorizedpages", "Uncategorizedtemplates",
    "Unusedcategories", "Unusedimages", "Unusedtemplates", "Unwatchedpages", "Wantedcategories", "Wantedfiles",
    "Wantedpages", "Wantedtemplates", "Allpages", "Prefixindex", "Categories", "Listredirects", "PagesWithProp",
    "TrackingCategories", "Userlogin", "Userlogout", "CreateAccount", "LinkAccounts", "UnlinkAccounts",
    "ChangeCredentials", "RemoveCredentials", "Activeusers", "Block", "Unblock", "BlockList", "AutoblockList",
    "ChangePassword", "BotPasswords", "PasswordReset", "DeletedContributions", "Preferences", "ResetTokens",
    "Contributions", "Listgrouprights", "Listgrants", "Listusers", "Listadmins", "Listbots", "Userrights",
    "EditWatchlist", "PasswordPolicies", "Newimages", "Log", "Watchlist", "Newpages", "Recentchanges",
    "Recentchangeslinked", "Tags", "Listfiles", "Filepath", "MediaStatistics", "MIMEsearch", "FileDuplicateSearch",
    "Upload", "UploadStash", "ListDuplicatedFiles", "ApiSandbox", "Statistics", "Allmessages", "Version", "Lockdb",
    "Unlockdb", "LinkSearch", "Randompage", "RandomInCategory", "Randomredirect", "Randomrootpage", "GoToInterwiki",
    "Mostlinkedcategories", "Mostimages", "Mostinterwikis", "Mostlinked", "Mostlinkedtemplates", "Mostcategories",
    "Mostrevisions", "ComparePages", "Export", "Import", "Undelete", "Whatlinkshere", "MergeHistory",
    "ExpandTemplates", "ChangeContentModel", "Booksources", "ApiHelp", "Blankpage", "DeletePage", "Diff", "EditPage",
    "EditTags", "Emailuser", "Movepage", "Mycontributions", "MyLanguage", "Mypage", "Mytalk", "PageHistory",
    "PageInfo", "ProtectPage", "Purge", "Myuploads", "AllMyUploads", "NewSection", "PermanentLink", "Redirect",
    "Revisiondelete", "RunJobs", "Specialpages", "PageData",
    "Search", "Confirmemail", "Invalidateemail", "ChangeEmail",
)

# MessagesEn.php $specialPageAliases
SPECIAL_PAGE_ALIASES_EN: dict[str, tuple[str, ...]] = {
    "Activeusers": ("ActiveUsers",),
    "Allmessages": ("AllMessages",),
    "AllMyUploads": ("AllMyUploads", "AllMyFiles"),
    "Allpages": ("AllPages",),
    "Ancientpages": ("AncientPages",),
    "ApiHelp": ("ApiHelp",),
    "ApiSandbox": ("ApiSandbox",),
    "AutoblockList": ("AutoblockList", "ListAutoblocks"),
    "Badtitle": ("Badtitle",),
    "Blankpage": ("BlankPage",),
    "Block": ("Block", "BlockIP", "BlockUser"),
    "BlockList": ("BlockList", "ListBlocks", "IPBlockList"),
    "Booksources": ("BookSources",),
    "BotPasswords": ("BotPasswords",),
    "BrokenRedirects": ("BrokenRedirects",),
    "Categories": ("Categories",),
    "ChangeContentModel": ("ChangeContentModel",),
    "ChangeCredentials": ("ChangeCredentials",),
    "ChangeEmail": ("ChangeEmail",),
    "ChangePassword": ("ChangePassword", "ResetPass", "ResetPassword"),
    "ComparePages": ("ComparePages",),
    "Confirmemail": ("ConfirmEmail",),
    "Contributions": ("Contributions", "Contribs"),
    "CreateAccount": ("CreateAccount",),
    "Deadendpages": ("DeadendPages",),
    "DeletedContributions": ("DeletedContributions",),
    "DeletePage": ("DeletePage", "Delete"),
    "Diff": ("Diff",),
    "DoubleRedirects": ("DoubleRedirects",),
    "EditPage": ("EditPage", "Edit"),
    "EditTags": ("EditTags",),
    "EditWatchlist": ("EditWatchlist",),
    "Emailuser": ("EmailUser", "Email"),
    "ExpandTemplates": ("ExpandTemplates",),
    "Export": ("Export",),
    "Fewestrevisions": ("FewestRevisions",),
    "FileDuplicateSearch": ("FileDuplicateSearch",),
    "Filepath": ("FilePath",),
    "GoToInterwiki": ("GoToInterwiki",),
    "Import": ("Import",),
    "Invalidateemail": ("InvalidateEmail",),
    "JavaScriptTest": ("JavaScriptTest",),
    "LinkAccounts": ("LinkAccounts",),
    "LinkSearch": ("LinkSearch",),
    "Listadmins": ("ListAdmins",),
    "Listbots": ("ListBots",),
    "ListDuplicatedFiles": ("ListDuplicatedFiles", "ListFileDuplicates"),
    "Listfiles": ("ListFiles", "FileList", "ImageList"),
    "Listgrants": ("ListGrants",),
    "Listgrouprights": ("ListGroupRights", "UserGroupRights"),
    "Listredirects": ("ListRedirects",),
    "Listusers": ("ListUsers", "UserList", "Users"),
    "Lockdb": ("LockDB",),
    "Log": ("Log", "Logs"),
    "Lonelypages": ("LonelyPages", "OrphanedPages"),
    "Longpages": ("LongPages",),
    "MediaStatistics": ("MediaStatistics",),
    "MergeHistory": ("MergeHistory",),
    "MIMEsearch": ("MIMESearch",),
    "Mostcategories": ("MostCategories",),
    "Mostimages": ("MostLinkedFiles", "MostFiles", "MostImages"),
    "Mostinterwikis": ("MostInterwikis",),
    "Mostlinked": ("MostLinkedPages", "MostLinked"),
    "Mostlinkedcategories": ("MostLinkedCategories", "MostUsedCategories"),
    "Mostlinkedtemplates": ("MostTranscludedPages", "MostLinkedTemplates", "MostUsedTemplates"),
    "Mostrevisions": ("MostRevisions",),
    "Movepage": ("MovePage",),
    "Mute": ("Mute",),
    "Mycontributions": ("MyContributions", "MyContribs"),
    "MyLanguage": ("MyLanguage",),
    "Mypage": ("MyPage",),
    "Mytalk": ("MyTalk",),
    "Myuploads": ("MyUploads", "MyFiles"),
    "Newimages": ("NewFiles", "NewImages"),
    "Newpages": ("NewPages",),
    "NewSection": ("NewSection", "Newsection"),
    "PageData": ("PageData",),
    "PageHistory": ("PageHistory", "History"),
    "PageInfo": ("PageInfo", "Info"),
    "PageLanguage": ("PageLanguage",),
    "PagesWithProp": ("PagesWithProp", "Pageswithprop", "PagesByProp", "Pagesbyprop"),
    "PasswordPolicies": ("PasswordPolicies",),
    "PasswordReset": ("PasswordReset",),
    "PermanentLink": ("PermanentLink", "PermaLink"),
    "Preferences": ("Preferences",),
    "Prefixindex": ("PrefixIndex",),
    "Protectedpages": ("ProtectedPages",),
    "Protectedtitles": ("ProtectedTitles",),
    "ProtectPage": ("ProtectPage", "Protect"),
    "Purge": ("Purge",),
    "RandomInCategory": ("RandomInCategory",),
    "Randompage": ("Random", "RandomPage"),
    "Randomredirect": ("RandomRedirect",),
    "Randomrootpage": ("RandomRootpage",),
    "Recentchanges": ("RecentChanges",),
    "Recentchangeslinked": ("RecentChangesLinked", "RelatedChanges"),
    "Redirect": ("Redirect",),
    "RemoveCredentials": ("RemoveCredentials",),
    "ResetTokens": ("ResetTokens",),
    "Revisiondelete": ("RevisionDelete",),
    "RunJobs": ("RunJobs",),
    "Search": ("Search",),
    "Shortpages": ("ShortPages",),
    "Specialpages": ("SpecialPages",),
    "Statistics": ("Statistics", "Stats"),
    "Tags": ("Tags",),
    "TrackingCategories": ("TrackingCategories",),
    "Unblock": ("Unblock",),
    "Uncategorizedcategories": ("UncategorizedCategories",),
    "Uncategorizedimages": ("UncategorizedFiles", "UncategorizedImages"),
    "Uncategorizedpages": ("UncategorizedPages",),
    "Uncategorizedtemplates": ("UncategorizedTemplates",),
    "Undelete": ("Undelete",),
    "UnlinkAccounts": ("UnlinkAccounts",),
    "Unlockdb": ("UnlockDB",),
    "Unusedcategories": ("UnusedCategories",),
    "Unusedimages": ("UnusedFiles", "UnusedImages"),
    "Unusedtemplates": ("UnusedTemplates",),
    "Unwatchedpages": ("UnwatchedPages",),
    "Upload": ("Upload",),
    "UploadStash": ("UploadStash",),
    "Userlogin": ("UserLogin", "Login"),
    "Userlogout": ("UserLogout", "Logout"),
    "Userrights": ("UserRights", "MakeSysop", "MakeBot"),
    "Version": ("Version",),
    "Wantedcategories": ("WantedCategories",),
    "Wantedfiles": ("WantedFiles",),
    "Wantedpages": ("WantedPages", "BrokenLinks"),
    "Wantedtemplates": ("WantedTemplates",),
    "Watchlist": ("Watchlist",),
    "Whatlinkshere": ("WhatLinksHere",),
    "Withoutinterwiki": ("WithoutInterwiki",),
}


def _case_fold(s: str) -> str:
    """Language::caseFold() (uc())"""
    return s.upper()


class SpecialPageFactory:
    """The special pages of the wiki and their English aliases (SpecialPageFactory, without the page objects)."""

    def __init__(self, page_list: tuple[str, ...] = CORE_SPECIAL_PAGES,
                 aliases: Mapping[str, tuple[str, ...]] = SPECIAL_PAGE_ALIASES_EN):
        self.page_list = set(page_list)
        self.aliases_by_name = dict(aliases)
        self._alias_list: Optional[dict[str, str]] = None

    def get_alias_list(self) -> dict[str, str]:
        """Case-folded alias -> canonical name"""
        if self._alias_list is None:
            alias_list: dict[str, str] = {}
            keep_alias: dict[str, str] = {}
            # Force every canonical name to be an alias for itself.
            for name in self.page_list:
                case_folded_alias = _case_fold(name)
                alias_list[case_folded_alias] = name
                keep_alias[case_folded_alias] = "canonical"
            for real_name, aliases in self.aliases_by_name.items():
                for i, alias in enumerate(aliases):
                    case_folded_alias = _case_fold(alias)
                    if alias_list.get(case_folded_alias) == real_name:
                        # Ignore same-realName conflicts
                        continue
                    if case_folded_alias not in keep_alias:
                        alias_list[case_folded_alias] = real_name
                        if not i:
                            keep_alias[case_folded_alias] = "first"
            self._alias_list = alias_list
        return self._alias_list

    def resolve_alias(self, alias: str) -> tuple[Optional[str], Optional[str]]:
        """Given a special page name with a possible subpage, return a (canonical name, subpage) pair; (None,
        None) if the name is not an alias."""
        bits = alias.split("/", 1)
        case_folded_alias = _case_fold(bits[0]).replace(" ", "_")
        aliases = self.get_alias_list()
        if case_folded_alias not in aliases:
            return None, None
        name = aliases[case_folded_alias]
        par = bits[1] if len(bits) > 1 else None  # T4087
        return name, par

    def exists(self, name: str) -> bool:
        """Check if a given name exist as a special page or as a special page alias"""
        title, _ = self.resolve_alias(name)
        return title in self.page_list

    def get_local_name_for(self, name: str, subpage: Union[str, bool, None] = False) -> str:
        """The local name for a specified canonical name"""
        aliases = self.aliases_by_name
        alias_list = self.get_alias_list()
        # Find the first alias that maps back to name
        if name in aliases:
            for alias in aliases[name]:
                case_folded_alias = _case_fold(alias).replace(" ", "_")
                if alias_list.get(case_folded_alias) == name:
                    name = alias
                    break
        else:
            # Check if someone misspelled the correct casing
            for n in aliases:
                if n.lower() == name.lower():
                    return self.get_local_name_for(n, subpage)
        if subpage is not False and subpage is not None:
            # Make sure it's in dbkey form
            subpage = subpage.replace(" ", "_")
            name = f"{name}/{subpage}"
        return Site.ucfirst(name)


# --- MediaWiki: messages ---

# Keys of English messages (languages/i18n/en.json) whose MediaWiki: pages count as existing. MediaWiki knows
# every message; only a few that wiki pages link to are listed here.
KNOWN_MESSAGES = frozenset({
    "mainpage", "sidebar", "common.css", "common.js", "print.css", "filepage.css", "noscript.css", "edit",
    "red-link-title", "toc", "showtoc", "hidetoc", "editsection", "sitenotice", "anonnotice", "copyright",
    "copyrightwarning", "edittools", "pagetitle", "noarticletext", "aboutsite", "aboutpage", "disclaimers",
    "disclaimerpage", "privacy", "privacypage", "helppage", "mainpage-description", "portal", "portal-url",
    "currentevents", "currentevents-url", "recentchanges", "randompage", "help", "search", "tagline",
    "bad_image_list", "external_image_whitelist", "licenses", "uploadtext", "rfcurl", "pubmedurl",
    "booksources-text",
})


class LinkCache:
    """Which pages exist, from the caller's ``pages`` mapping (title -> wikitext): what LinkCache and the page table
    answer in MediaWiki. Keys are page titles with spaces; they are normalised like titles when first needed."""

    def __init__(self, pages: Optional[Mapping[str, str]], site: Site, magic_words: MagicWordFactory = FACTORY,
                 special_pages: Optional[SpecialPageFactory] = None, files=None):
        self.pages = pages or {}
        self.site = site
        self.magic_words = magic_words
        self.special_pages = special_pages or SpecialPageFactory()
        self.files = files  # a files.FileRepo, or None for no files
        self._index: Optional[dict[str, str]] = None
        self._redirects: dict[str, Optional[Title]] = {}

    def _normalised_index(self) -> dict[str, str]:
        if self._index is None:
            index: dict[str, str] = {}
            for key, text in self.pages.items():
                t = Title.new_from_text(key, site=self.site)
                if t is not None and not t.is_external():
                    index.setdefault(t.prefixed_text, text)
            self._index = index
        return self._index

    def get_page_text(self, title: Title) -> Optional[str]:
        """The wikitext of the page, None if it does not exist."""
        if title.is_external() or title.namespace < 0 or title.db_key == "":
            return None
        key = title.prefixed_text
        if key in self.pages:
            return self.pages[key]
        return self._normalised_index().get(key)

    def exists(self, title: Title) -> bool:
        """Title::exists(): does the page exist (has an article ID)?"""
        return self.get_page_text(title) is not None

    def get_redirect_target(self, title: Title) -> Optional[Title]:
        """WikitextContent::getRedirectTarget() of the page's text: the target of #REDIRECT [[...]], or None."""
        key = title.prefixed_db_key
        if key in self._redirects:
            return self._redirects[key]
        target = None
        text = self.get_page_text(title)
        if text is not None:
            text = text.lstrip()
            matched, text = self.magic_words.get("redirect").match_start_and_remove(text)
            if matched:
                # Extract the first link and see if it's usable
                # Ensure that it really does come directly after #REDIRECT
                # Some older redirects included a colon, so don't freak about that!
                m = re.match(r"^\s*:?\s*\[{2}(.*?)(?:\|.*?)?\]{2}\s*", text, re.S)
                if m:
                    link = m.group(1)
                    # Strip preceding colon used to "escape" categories, etc. and URL-decode links
                    if "%" in link:
                        from urllib.parse import unquote
                        link = unquote(link.lstrip(":"), errors="surrogateescape")
                    target = Title.new_from_text(link, site=self.site)
        self._redirects[key] = target
        return target

    def is_redirect(self, title: Title) -> bool:
        """The 'redirect' field of the page row."""
        return self.get_redirect_target(title) is not None

    def find_file(self, title: Title):
        """RepoGroup::findFile(): the file a File: or Media: title names, following a redirect of its file page
        (FileRepo::checkRedirect()); None if there is none."""
        if self.files is None or title is None:
            return None
        file = self.files.get(title)
        if file is not None:
            return file
        # Now try redirects
        redirect = self.check_redirect(title)
        if redirect is not None:
            file = self.files.get(redirect)
            if file is not None:
                file.redirected_from = title.db_key
            return file
        return None

    def check_redirect(self, title: Title) -> Optional[Title]:
        """LocalRepo::checkRedirect(): the target of the file page if it is a redirect to a File: page."""
        if title.namespace not in (NS_FILE, NS_MEDIA):
            return None
        file_title = Title.make_title(NS_FILE, title.db_key, site=title.site)
        target = self.get_redirect_target(file_title)
        if target is not None and target.namespace == NS_FILE:
            return target
        return None

    def file_exists(self, title: Title) -> bool:
        """Does RepoGroup::findFile() find the file?"""
        return self.find_file(title) is not None

    def message_exists(self, title: Title) -> bool:
        """Is the text of a MediaWiki: title a known system message? (MessageCache::figureMessage() strips a
        language subpage; keys are lcfirst with underscores.)"""
        from .parser_links import LANGUAGE_CODES

        text = title.text
        key = text[:1].lower() + text[1:]  # Language::lcfirst()
        pieces = key.split("/")
        if len(pieces) >= 2 and pieces[-1] in LANGUAGE_CODES:
            key = "/".join(pieces[:-1])
        return key.replace(" ", "_") in KNOWN_MESSAGES  # MessageCache::normalizeKey()

    def has_source_text(self, title: Title) -> bool:
        """Title::hasSourceText()"""
        if self.exists(title):
            return True
        if title.namespace == NS_MEDIAWIKI:
            return self.message_exists(title)
        return False

    def is_always_known(self, title: Title) -> bool:
        """Title::isAlwaysKnown(): should links to this title be shown as potentially viewable even if there's no
        page in the wiki?"""
        if title.is_external():
            return True  # any interwiki link might be viewable, for all we know
        ns = title.namespace
        if ns in (NS_MEDIA, NS_FILE):
            # file exists, possibly in a foreign repo
            return self.file_exists(title)
        if ns == NS_SPECIAL:
            # valid special page
            return self.special_pages.exists(title.db_key)
        if ns == NS_MAIN:
            # selflink, possibly with fragment
            return title.db_key == ""
        if ns == NS_MEDIAWIKI:
            # known system message
            return self.has_source_text(title)
        return False

    def is_known(self, title: Title) -> bool:
        """Title::isKnown(): does this title refer to a page that can (or might) be meaningfully viewed?"""
        return self.is_always_known(title) or self.exists(title)


class LinkRenderer:
    """Class that generates HTML <a> links for pages."""

    def __init__(self, link_cache: LinkCache, *, force_article_path: bool = False,
                 expand_urls: Union[bool, str, int] = False):
        self.link_cache = link_cache
        self.site = link_cache.site
        self.special_page_factory = link_cache.special_pages
        self.force_article_path = force_article_path
        self.expand_urls = expand_urls

    def make_link(self, target: Title, text: Union[HtmlArmor, str, None] = None,
                  extra_attribs: Optional[dict] = None, query: Optional[dict] = None) -> str:
        """A known or broken link, depending on whether the target is known."""
        if self.link_cache.is_known(target):
            return self.make_known_link(target, text, extra_attribs, query)
        return self.make_broken_link(target, text, extra_attribs, query)

    def make_preloaded_link(self, target: Title, text: Union[HtmlArmor, str, None] = None, classes: str = "",
                            extra_attribs: Optional[dict] = None, query: Optional[dict] = None) -> str:
        """A link whose CSS classes (link colour) are already known."""
        target = self.normalize_target(target)
        url = self.get_link_url(target, query or {})
        attribs: dict = {"class": classes}
        prefixed_text = target.prefixed_text
        if prefixed_text != "":
            attribs["title"] = prefixed_text
        attribs = {"href": url, **self._merge_attribs(attribs, extra_attribs or {})}
        if text is None:
            text = self._get_link_text(target)
        return self._build_a_element(target, text, attribs, True)

    def make_known_link(self, target: Title, text: Union[HtmlArmor, str, None] = None,
                        extra_attribs: Optional[dict] = None, query: Optional[dict] = None) -> str:
        classes = []
        if target.is_external():
            classes.append("extiw")
        colour = self.get_link_classes(target)
        if colour != "":
            classes.append(colour)
        return self.make_preloaded_link(target, text, " ".join(classes), extra_attribs, query)

    def make_broken_link(self, target: Title, text: Union[HtmlArmor, str, None] = None,
                         extra_attribs: Optional[dict] = None, query: Optional[dict] = None) -> str:
        query = dict(query or {})
        # We don't want to include fragments for broken links, because they generally make no sense.
        if target.has_fragment():
            target = target.create_fragment_target("")
        target = self.normalize_target(target)
        if "action" not in query and target.namespace != NS_SPECIAL:
            query["action"] = "edit"
            query["redlink"] = "1"
        url = self.get_link_url(target, query)
        attribs: dict = {"class": "new"}
        prefixed_text = target.prefixed_text
        if prefixed_text != "":
            # This ends up in parser cache!
            attribs["title"] = f"{prefixed_text} (page does not exist)"  # red-link-title
        attribs = {"href": url, **self._merge_attribs(attribs, extra_attribs or {})}
        if text is None:
            text = self._get_link_text(target)
        return self._build_a_element(target, text, attribs, False)

    @staticmethod
    def _build_a_element(target: Title, text: Union[HtmlArmor, str], attribs: dict, is_known: bool) -> str:
        return raw_element("a", attribs, HtmlArmor.get_html(text))

    @staticmethod
    def _get_link_text(target: Title) -> str:
        prefixed_text = target.prefixed_text
        # If the target is just a fragment, with no title, we return the fragment text. Otherwise, we return the
        # title text itself.
        if prefixed_text == "" and target.has_fragment():
            return target.fragment
        return prefixed_text

    def get_link_url(self, target: Title, query: Optional[dict] = None) -> str:
        query = dict(query or {})
        if self.force_article_path:
            real_query, query = query, {}
        else:
            real_query = {}
        url = target.get_link_url(query, self.expand_urls)
        if self.force_article_path and real_query:
            url = wf_append_query(url, real_query)
        return url

    def normalize_target(self, target: Title) -> Title:
        """Normalize a special page title to its local (first alias) name."""
        if target.namespace == NS_SPECIAL and not target.is_external():
            name, subpage = self.special_page_factory.resolve_alias(target.db_key)
            if name:
                return Title.make_title(NS_SPECIAL, self.special_page_factory.get_local_name_for(name, subpage),
                                        target.fragment, site=target.site)
        return target

    @staticmethod
    def _merge_attribs(defaults: dict, attribs: dict) -> dict:
        if not attribs:
            return defaults
        from .sanitizer import merge_attributes

        # Merge the custom attribs with the default ones, and iterate over that, deleting all "false" attributes.
        return {k: v for k, v in merge_attributes(defaults, attribs).items() if v is not False}

    def get_link_classes(self, target: Title) -> str:
        """The CSS classes of a link to an existing page: 'mw-redirect' for redirects, '' otherwise (no stub
        threshold)."""
        # Don't call LinkCache if the target is "non-proper"
        if target.is_external() or target.text == "" or target.namespace < 0:
            return ""
        if not self.link_cache.exists(target):
            # Doesn't exist
            return ""
        if self.link_cache.is_redirect(target):
            # Page is a redirect
            return "mw-redirect"
        return ""

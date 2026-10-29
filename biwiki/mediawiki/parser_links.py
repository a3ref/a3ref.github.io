# Ported from MediaWiki 1.39 includes/parser/Parser.php (https://www.mediawiki.org/), (C) MediaWiki contributors:
# Parser::handleInternalLinks(), handleInternalLinks2(), makeKnownLinkHolder(), armorLinks(), replaceLinkHolders(),
# replaceLinkHoldersPrivate(), replaceLinkHoldersText(), getLinkRenderer(), nextLinkID(), fetchFileAndTitle(),
# normalizeLinkUrl(), normalizeUrlComponent(); the ParserOutput methods they call (addLink(), addInterwikiLink(),
# addLanguageLink(), addImage()); the language codes of includes/languages/data/Names.php (for
# LanguageNameUtils::getLanguageName()).
# Changed by a3ref contributors on 2026-10-30: translated to Python as a mixin of Parser; the content language is
# English (no link prefixes, no variants); page existence comes from the parser's pages (linkrenderer.LinkCache);
# images are a stub (make_image) until the image code is ported; no hooks.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Internal links [[...]]: link holders, categories, interlanguage links, self-links, media and file links."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote

from .html import htmlspecialchars
from .linker import make_media_link_file, make_self_link_obj, normalize_subpage_link, split_trail, valid_protocols
from .linkholders import LinkHolderArray
from .linkrenderer import HtmlArmor, LinkCache, LinkRenderer
from .site import NS_CATEGORY, NS_FILE, NS_MEDIA, NS_SPECIAL
from .stripstate import MARKER_PREFIX
from .title import Title, _is_ipv4, _is_ipv6_add, _legal_chars_to_python

# The language codes of includes/languages/data/Names.php: LanguageNameUtils::getLanguageName( $code, AUTONYMS,
# DEFINED ) is not '' for these ($wgExtraLanguageNames is empty by default)
LANGUAGE_CODES = frozenset("""
aa ab abs ace ady ady-cyrl aeb aeb-arab aeb-latn af ak aln als alt am ami an ang anp ar arc arn arq ary arz as
ase ast atj av avk awa ay az azb ba ban ban-bali bar bat-smg bbc bbc-latn bcc bci bcl be be-tarask be-x-old bg
bgn bh bho bi bjn blk bm bn bo bpy bqi br brh bs btm bto bug bxr ca cbk-zam cdo ce ceb ch cho chr chy ckb co cps
cr crh crh-cyrl crh-latn cs csb cu cv cy da dag de de-at de-ch de-formal din diq dsb dtp dty dv dz ee egl el eml
en en-ca en-gb eo es es-419 es-formal et eu ext fa fat ff fi fit fiu-vro fj fo fon fr frc frp frr fur fy ga gaa
gag gan gan-hans gan-hant gcr gd gl gld glk gn gom gom-deva gom-latn gor got gpe grc gsw gu guc gur guw gv ha
hak haw he hi hif hif-latn hil ho hr hrx hsb hsn ht hu hu-formal hy hyw hz ia id ie ig ii ik ike-cans ike-latn
ilo inh io is it iu ja jam jbo jut jv ka kaa kab kbd kbd-cyrl kbp kcg kea kg khw ki kiu kj kjp kk kk-arab kk-cn
kk-cyrl kk-kz kk-latn kk-tr kl km kn ko ko-kp koi kr krc kri krj krl ks ks-arab ks-deva ksh ksw ku ku-arab
ku-latn kum kv kw ky la lad lb lbe lez lfn lg li lij liv lki lld lmo ln lo loz lrc lt ltg lus luz lv lzh lzz mad
mai map-bms mdf mg mh mhr mi min mk ml mn mni mnw mo mos mr mrh mrj ms ms-arab mt mus mwl my myv mzn na nah nan
nap nb nds nds-nl ne new ng nia niu nl nl-informal nmz nn no nod nov nqo nrm nso nv ny nyn nys oc ojb olo om or
os pa pag pam pap pcd pcm pdc pdt pfl pi pih pl pms pnb pnt prg ps pt pt-br pwn qu qug rgn rif rm rmc rmy rn ro
roa-rup roa-tara rsk ru rue rup ruq ruq-cyrl ruq-latn rw ryu sa sah sat sc scn sco sd sdc sdh se se-fi se-no
se-se sei ses sg sgs sh shi shi-latn shi-tfng shn shy shy-latn si simple sjd sje sk skr skr-arab sl sli sm sma
smn sms sn so sq sr sr-ec sr-el srn sro ss st stq sty su sv sw syl szl szy ta tay tcy tdd te tet tg tg-cyrl
tg-latn th ti tk tl tly tly-cyrl tn to tpi tr tru trv ts tt tt-cyrl tt-latn tum tw ty tyv tzm udm ug ug-arab
ug-latn uk ur uz uz-cyrl uz-latn ve vec vep vi vls vmf vmw vo vot vro wa war wls wo wuu xal xh xmf xsy yi yo yrl
yue za zea zgh zh zh-classical zh-cn zh-hans zh-hant zh-hk zh-min-nan zh-mo zh-my zh-sg zh-tw zh-yue zu
""".split())


class TargetLanguage:
    """The target language of the parse: English (Parser::getTargetLanguage())."""
    code = "en"

    @staticmethod
    def link_prefix_extension() -> bool:
        """Language::linkPrefixExtension(): $linkPrefixExtension of MessagesEn is false."""
        return False

    @staticmethod
    def link_trail() -> str:
        """Language::linkTrail(): MessagesEn $linkTrail"""
        return "/^([a-z]+)(.*)$/sD"


ENGLISH = TargetLanguage()


def _rawurlencode_char(c: str) -> str:
    return "".join(f"%{b:02X}" for b in c.encode("utf-8", "surrogatepass"))


def _normalize_url_component(component: str, unsafe: str) -> str:
    def callback(m: re.Match) -> str:
        char = chr(int(m.group(0)[1:], 16))  # urldecode() of one %XX
        ord_ = ord(char)
        if 32 < ord_ < 127 and char not in unsafe:
            # Unescape it
            return char
        # Leave it escaped, but use uppercase for a-f
        return m.group(0).upper()

    return re.sub(r"%[0-9A-Fa-f]{2}", callback, component)


_UNSAFE_URL_CHARS = re.compile('[\x00-\x20"<>\\[\\\\\\]^`{|}\x7f-\U0010ffff]')


def normalize_link_url(url: str) -> str:
    """Parser::normalizeLinkUrl(): replace unusual escape codes in a URL with their equivalent characters. This
    generally follows the syntax defined in RFC 3986, with special consideration for HTTP query strings."""
    # Test for RFC 3986 IPv6 syntax
    scheme = r"[a-z][a-z0-9+.-]*:"
    userinfo = r"(?:[a-z0-9\-._~!$&'()*+,;=:]|%[0-9a-f]{2})*"
    ipv6_host = r"\[((?:[0-9a-f:]|%3[0-A]|%[46][1-6])+)\]"
    m = re.match(rf"^(?:{scheme})?//(?:{userinfo}@)?{ipv6_host}(?:[:/?#].*|)$", url, re.I)
    is_ipv6: Optional[str] = None
    if m:
        decoded = unquote(m.group(1), errors="surrogateescape")
        if _is_ipv4(decoded) and "/" not in decoded or _is_ipv6_add(decoded):  # IPUtils::isValid()
            is_ipv6 = decoded

    # Make sure unsafe characters are encoded
    url = _UNSAFE_URL_CHARS.sub(lambda mm: _rawurlencode_char(mm.group(0)), url)

    ret = ""
    end = len(url)

    # Fragment part - 'fragment'
    start = url.find("#")
    if start != -1 and start < end:
        ret = _normalize_url_component(url[start:end], '"#%<>[\\]^`{|}') + ret
        end = start

    # Query part - 'query' minus &=+;
    start = url.find("?")
    if start != -1 and start < end:
        ret = _normalize_url_component(url[start:end], '"#%<>[\\]^`{|}&=+;') + ret
        end = start

    # Scheme and path part - 'pchar'
    # (we assume no userinfo or encoded colons in the host)
    ret = _normalize_url_component(url[:end], '"#%<>[\\]^`{|}/?') + ret

    # Fix IPv6 syntax
    if is_ipv6 is not None:
        ipv6_host = f"%5B({re.escape(is_ipv6)})%5D"
        ret = re.sub(rf"^((?:{scheme})?//(?:{userinfo}@)?){ipv6_host}(?=[:/?#]|$)", r"\1[\2]", ret, flags=re.I)
    return ret


class LinksMixin:
    """The internal-link part of Parser. The class using it provides: ``site`` (Site), ``config`` (Config),
    ``pages`` (title -> wikitext), ``title`` (the page title, a string), ``output`` (ParserOutput, with
    ``categories`` and ``page_properties``), ``strip_state``, ``magic_words`` and ``handle_external_links()``."""

    # ---- state ------------------------------------------------------------------------------------------------

    def clear_link_state(self) -> None:
        """What Parser::clearState() resets for links: the link holders, the link ID counter and the languages of
        the interlanguage links found so far. Call it at the start of every parse."""
        self.link_holders = LinkHolderArray(self)
        self.link_id = 0
        self.lang_link_languages: dict[str, bool] = {}
        self._title_object: Optional[tuple[str, Title]] = None

    def _ensure_link_state(self) -> None:
        if "link_holders" not in self.__dict__:
            self.clear_link_state()

    def next_link_id(self) -> int:
        self._ensure_link_state()
        link_id = self.link_id
        self.link_id += 1
        return link_id

    def get_title_object(self) -> Title:
        """Parser::getTitle(): the Title of the page being parsed (``self.title`` holds its text)."""
        self._ensure_link_state()
        cached = self._title_object
        if cached is not None and cached[0] == self.title:
            return cached[1]
        title = Title.new_from_text(self.title, site=self.site)
        if title is None:
            title = Title.make_title(NS_SPECIAL, "Badtitle/Parser", site=self.site)
        self._title_object = (self.title, title)
        return title

    def get_target_language(self) -> TargetLanguage:
        """The target language for the content being parsed: English."""
        return ENGLISH

    def get_link_cache(self) -> LinkCache:
        """Which pages exist: the parser's pages, for its site."""
        cache = self.__dict__.get("_link_cache")
        key = self.__dict__.get("_link_cache_key")
        if cache is None or key is None or key[0] is not self.pages or key[1] is not self.site:
            cache = self._link_cache = LinkCache(self.pages, self.site, self.magic_words)
            self._link_cache_key = (self.pages, self.site)
            self._link_renderer = None
        return cache

    def get_link_renderer(self) -> LinkRenderer:
        """A LinkRenderer instance to make links with"""
        cache = self.get_link_cache()
        renderer = self.__dict__.get("_link_renderer")
        if renderer is None:
            renderer = self._link_renderer = LinkRenderer(cache)
        return renderer

    # ---- ParserOutput -----------------------------------------------------------------------------------------

    def _output_field(self, name: str, factory):
        """A ParserOutput field the link code fills, created on first use if ParserOutput does not declare it."""
        fields = self.output.__dict__
        if name not in fields:
            fields[name] = factory()
        return fields[name]

    def output_add_link(self, title: Title, id_: Optional[int] = None) -> None:
        """ParserOutput::addLink(): record a local or interwiki inline link for saving in future link tables.
        ``links``: namespace -> DB key -> page ID (0 for missing pages)."""
        if title.is_external():
            # Don't record interwikis in pagelinks
            self.output_add_interwiki_link(title)
            return
        ns = title.namespace
        dbk = title.db_key
        if ns == NS_MEDIA:
            # Normalize this pseudo-alias if it makes it down here...
            ns = NS_FILE
        elif ns == NS_SPECIAL:
            # We don't want to record Special: links in the database, so put them in a separate place.
            self._output_field("links_special", dict)[dbk] = 1
            return
        elif dbk == "":
            # Don't record self links - [[#Foo]]
            return
        if id_ is None:
            id_ = 1 if self.get_link_cache().exists(title) else 0
        self._output_field("links", dict).setdefault(ns, {})[dbk] = id_

    def output_add_interwiki_link(self, title: Title) -> None:
        """ParserOutput::addInterwikiLink(): ``interwiki_links``: prefix -> DB key -> 1"""
        if not title.is_external():
            raise ValueError("Non-interwiki link passed, internal parser error.")
        self._output_field("interwiki_links", dict).setdefault(title.interwiki, {})[title.db_key] = 1

    def output_add_language_link(self, text: str) -> None:
        """ParserOutput::addLanguageLink(): ``language_links``, full texts such as 'de:Seite'"""
        self._output_field("language_links", list).append(text)

    def output_add_image(self, name: str) -> None:
        """ParserOutput::addImage(): ``images``: file DB key -> 1"""
        self._output_field("images", dict)[name] = 1

    # ---- [[...]] ----------------------------------------------------------------------------------------------

    def handle_internal_links(self, text: str) -> str:
        """Process [[ ]] wikilinks"""
        self._ensure_link_state()
        text, holders = self.handle_internal_links2(text)
        self.link_holders.merge(holders)
        return text

    def _internal_link_regexes(self) -> tuple[re.Pattern, re.Pattern]:
        regexes = self.__dict__.get("_e1_regexes")
        if regexes is None or regexes[0] is not self.site:
            # the % is needed to support urlencoded titles as well
            tc = _legal_chars_to_python(self.site.legal_title_chars) + "#%"
            # Match a link having the form [[namespace:link|alternate]]trail
            e1 = re.compile(rf"^([{tc}]+)(?:\|(.+?))?\]\](.*)\Z", re.S)
            # Match cases where there is no "]]", which might still be images
            e1_img = re.compile(rf"^([{tc}]+)\|(.*)\Z", re.S)
            regexes = self._e1_regexes = (self.site, e1, e1_img)
        return regexes[1], regexes[2]

    def handle_internal_links2(self, s: str) -> tuple[str, LinkHolderArray]:
        """Process [[ ]] wikilinks (RIL). Returns the text and the link holders it now holds (MediaWiki changes the
        text by reference)."""
        from .quotes import do_quotes

        e1, e1_img = self._internal_link_regexes()
        holders = LinkHolderArray(self)

        # split the entire text string on occurrences of [[
        a = (" " + s).split("[[")
        # get the first element (all text up to first [[), and remove the space we added
        s = a[0][1:]

        page_title = self.get_title_object()
        nottalk = not page_title.is_talk_page()

        # English has no link prefixes (Language::linkPrefixExtension() is false)
        prefix = ""

        # Some namespaces don't allow subpages
        use_subpages = self.site.has_subpages(page_title.namespace)
        protocols = re.compile(r"^(?i:" + valid_protocols(self.config) + ")")

        # Loop for each link
        i = 1
        while i < len(a):
            line = a[i]
            # Check for excessive memory usage
            if holders.is_big():
                # Too big. Do the existence check, replace the link holders and clear the array
                s = holders.replace(s)
                holders.clear()

            might_be_img = False

            m = e1.match(line)
            if m:  # page with normal text or alt
                target = m.group(1)
                text = m.group(2) or ""
                trail = m.group(3)
                # If we get a ] at the beginning of trail that means we have a link that's something like:
                # [[Image:Foo.jpg|[http://example.com desc]]] <- having three ] in a row fucks up, the real problem
                # is with the e1 regex. See T1500.
                # Still some problems for cases where the ] is meant to be outside punctuation, and no image is in
                # sight. See T4095.
                if text != "" and trail[:1] == "]" and "[" in text:
                    text += "]"  # so that handleExternalLinks($text) works later
                    trail = trail[1:]
                # fix up urlencoded title texts
                if "%" in target:
                    # Should anchors '#' also be rejected?
                    target = unquote(target, errors="surrogateescape").replace("<", "&lt;").replace(">", "&gt;")
            else:
                m = e1_img.match(line)
                if m:
                    # Invalid, but might be an image with a link in its caption
                    might_be_img = True
                    target = m.group(1)
                    text = m.group(2)
                    if "%" in target:
                        target = unquote(target, errors="surrogateescape").replace("<", "&lt;").replace(">", "&gt;")
                    trail = ""
                else:  # Invalid form; output directly
                    s += prefix + "[[" + line
                    i += 1
                    continue

            orig_link = target.lstrip(" ")

            # Don't allow internal links to pages containing PROTO: where PROTO is a valid URL protocol; these
            # should be external links.
            if protocols.match(orig_link):
                s += prefix + "[[" + line
                i += 1
                continue

            # Make subpage if necessary
            if use_subpages:
                link, text = normalize_subpage_link(page_title, orig_link, text)
            else:
                link = orig_link

            # \x7f isn't a default legal title char, so most likely strip markers will force us into the "invalid
            # form" path above. But, just in case, let's assert that xmlish tags aren't valid in the title position.
            unstrip = self.strip_state.kill_markers(link)
            no_markers = unstrip == link

            nt = Title.new_from_text(link, site=self.site) if no_markers else None
            if nt is None:
                s += prefix + "[[" + line
                i += 1
                continue

            ns = nt.namespace
            iw = nt.interwiki

            noforce = orig_link[:1] != ":"

            if might_be_img:  # if this is actually an invalid link
                if ns == NS_FILE and noforce:  # but might be an image
                    found = False
                    while True:
                        # look at the next 'line' to see if we can close it there
                        i += 1
                        if i >= len(a):
                            break
                        next_line = a[i]
                        parts = next_line.split("]]", 2)
                        if len(parts) == 3:
                            # the first ]] closes the inner link, the second the image
                            found = True
                            text += f"[[{parts[0]}]]{parts[1]}"
                            trail = parts[2]
                            break
                        elif len(parts) == 2:
                            # if there's exactly one ]] that's fine, we'll keep looking
                            text += f"[[{parts[0]}]]{parts[1]}"
                        else:
                            # if next_line is invalid too, we need look no further
                            text += "[[" + next_line
                            break
                    if not found:
                        # we couldn't find the end of this imageLink, so output it raw but don't ignore what might be
                        # perfectly normal links in the text we've examined
                        text, inner = self.handle_internal_links2(text)
                        holders.merge(inner)
                        s += f"{prefix}[[{link}|{text}"
                        # note: no trail, because without an end, there *is* no trail
                        i += 1
                        continue
                else:  # it's not an image, so output it raw
                    s += f"{prefix}[[{link}|{text}"
                    # note: no trail, because without an end, there *is* no trail
                    i += 1
                    continue

            wasblank = text == ""
            if wasblank:
                text = link
                if not noforce:
                    # Strip off leading ':'
                    text = text[1:]
            else:
                # T6598 madness. Handle the quotes only if they come from the alternate part
                # [[Lista d''e paise d''o munno]] -> <a href="...">Lista d''e paise d''o munno</a>
                # [[Criticism of Harry Potter|Criticism of ''Harry Potter'']]
                #    -> <a href="Criticism of Harry Potter">Criticism of <i>Harry Potter</i></a>
                text = do_quotes(text)

            # Link not escaped by : , create the various objects
            if noforce and not nt.was_local_interwiki():
                # Interwikis
                if iw and self.config_interwiki_magic() and nottalk and (
                        iw.lower() in LANGUAGE_CODES or iw in self.extra_interlanguage_link_prefixes()):
                    # T26502: filter duplicates
                    if iw not in self.lang_link_languages:
                        self.lang_link_languages[iw] = True
                        self.output_add_language_link(nt.full_text)
                    # Strip the whitespace interwiki links produce, see T10897
                    s = (s + prefix).rstrip(" \t\n\r\0\x0b") + trail  # T175416
                    i += 1
                    continue

                if ns == NS_FILE:
                    if wasblank:
                        # if no parameters were passed, text becomes something like "File:Foo.png", which we don't
                        # want to pass on to the image generator
                        text = ""
                    else:
                        # recursively parse links inside the image caption actually, this will parse them in any
                        # other parameters, too, but it might be hard to fix that, and it doesn't matter ATM
                        text = self.handle_external_links(text)
                        text, inner = self.handle_internal_links2(text)
                        holders.merge(inner)
                    # cloak any absolute URLs inside the image markup, so handleExternalLinks() won't touch them
                    s += prefix + self.armor_links(self.make_image(nt, text, holders)) + trail
                    i += 1
                    continue
                elif ns == NS_CATEGORY:
                    # Strip the whitespace Category links produce, see T2087
                    s = (s + prefix).rstrip(" \t\n\r\0\x0b") + trail  # T2087, T87753
                    if wasblank:
                        sortkey = self.output.page_properties.get("defaultsort") or ""
                    else:
                        sortkey = text
                    from .sanitizer import decode_char_references

                    sortkey = decode_char_references(sortkey)
                    sortkey = sortkey.replace("\n", "")
                    # convertCategoryKey(): English has no variants
                    self.output.categories[nt.db_key] = sortkey
                    i += 1
                    continue

            # Self-link checking. For some languages, variants of the title are checked in
            # LinkHolderArray::doVariants() to allow batching the existence checks necessary for linking to a
            # different variant.
            if ns != NS_SPECIAL and nt.equals(page_title) and not nt.has_fragment():
                s += prefix + make_self_link_obj(nt, text, "", trail)
                i += 1
                continue

            # NS_MEDIA is a pseudo-namespace for linking directly to a file
            if ns == NS_MEDIA:
                # Fetch and register the file (file title may be different via hooks)
                file, nt = self.fetch_file_and_title(nt, {})
                # Cloak with NOPARSE to avoid replacement in handleExternalLinks
                s += prefix + self.armor_links(make_media_link_file(nt, file, text)) + trail
                i += 1
                continue

            # Some titles, such as valid special pages or files in foreign repos, should be shown as bluelinks even
            # though they're not included in the page table
            if iw == "" and self.get_link_cache().is_always_known(nt):
                self.output_add_link(nt)
                s += self.make_known_link_holder(nt, text, trail, prefix)
            else:
                # Links will be added to the output link list after checking
                s += holders.make_holder(nt, text, trail, prefix)
            i += 1
        return s, holders

    def config_interwiki_magic(self) -> bool:
        """ParserOptions::getInterwikiMagic(): interpret interlanguage links (default true)."""
        return getattr(self.config, "interwiki_magic", True)

    def extra_interlanguage_link_prefixes(self) -> tuple[str, ...]:
        """$wgExtraInterlanguageLinkPrefixes (default empty; the parser tests use ['mul'])."""
        return tuple(getattr(self.config, "extra_interlanguage_link_prefixes", ()))

    def make_known_link_holder(self, nt: Title, text: str = "", trail: str = "", prefix: str = "") -> str:
        """Render a forced-blue link inline; protect against double expansion of URLs if we're in a mode that
        prepends full URL prefixes to internal links. Since this little disaster has to split off the trail text to
        avoid breaking URLs in the following text without breaking trails on the wiki links, it's been made into a
        horrible function."""
        inside, trail = split_trail(trail)
        if text == "":
            text = htmlspecialchars(nt.prefixed_text)
        link = self.get_link_renderer().make_known_link(nt, HtmlArmor(f"{prefix}{text}{inside}"))
        return self.armor_links(link) + trail

    def armor_links(self, text: str) -> str:
        """Insert a NOPARSE hacky thing into any inline links in a chunk that's going to go through further parsing
        steps before inline URL expansion.

        Not needed quite as much as it used to be since free links are a bit more sensible these days. But
        bracketed links are still an issue."""
        return re.sub(r"\b((?i:" + valid_protocols(self.config) + "))", MARKER_PREFIX + r"NOPARSE\1", text,
                      flags=re.A)

    # ---- link holders -----------------------------------------------------------------------------------------

    def replace_link_holders(self, text: str) -> str:
        """Replace <!--LINK--> link placeholders with actual links, in the buffer (deprecated public name)."""
        return self.replace_link_holders_private(text)

    def replace_link_holders_private(self, text: str) -> str:
        """Replace <!--LINK--> link placeholders with actual links, in the buffer; returns the new text."""
        self._ensure_link_state()
        return self.link_holders.replace(text)

    def replace_link_holders_text(self, text: str) -> str:
        """Replace <!--LINK--> link placeholders with plain text of links (not HTML-formatted)."""
        self._ensure_link_state()
        return self.link_holders.replace_text(text)

    # ---- files ------------------------------------------------------------------------------------------------

    def fetch_file_and_title(self, link: Title, options: Optional[dict] = None) -> tuple[None, Title]:
        """Fetch a file and its title and register a reference to it. (TODO: files, with the image port; every file
        is missing for now, so the file is None.)"""
        file = None
        # Register the file as a dependency...
        self.output_add_image(link.db_key)
        return file, link

    def make_image(self, title: Title, options: str, holders: Optional[LinkHolderArray] = None) -> str:
        """Parse image options text and use it to make an image. (TODO: a later step ports Parser::makeImage() and
        Linker::makeImageLink(); until then the link text, escaped.)"""
        return htmlspecialchars(title.prefixed_text)

    # ---- external link URLs -----------------------------------------------------------------------------------

    normalize_link_url = staticmethod(normalize_link_url)

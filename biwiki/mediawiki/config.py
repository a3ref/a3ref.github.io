# Settings of MediaWiki 1.39 that the parser reads (includes/MainConfigSchema.php defaults, and the values
# tests/parser/ParserTestRunner.php sets for the parser tests) (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: the settings the port needs, as a Python dataclass; BIKI holds the
# values of the Bohemia Interactive Community wiki (from its API, meta=siteinfo).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The wiki configuration the parser depends on ($wg... settings)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# $wgUrlProtocols (MainConfigSchema default)
URL_PROTOCOLS = (
    "bitcoin:", "ftp://", "ftps://", "geo:", "git://", "gopher://", "http://", "https://", "irc://", "ircs://",
    "magnet:", "mailto:", "matrix:", "mms://", "news:", "nntp://", "redis://", "sftp://", "sip:", "sips:", "sms:",
    "ssh://", "svn://", "tel:", "telnet://", "urn:", "worldwind://", "xmpp:", "//",
)


@dataclass(frozen=True)
class Config:
    sitename: str = "MediaWiki"
    meta_namespace: str = "Project"
    server: str = "http://localhost"
    server_name: str = "localhost"
    script_path: str = ""
    script: str = "/index.php"
    article_path: str = "/wiki/$1"
    language_code: str = "en"
    capital_links: bool = True
    url_protocols: tuple[str, ...] = URL_PROTOCOLS
    no_follow_links: bool = True
    no_follow_ns_exceptions: tuple[int, ...] = ()
    no_follow_domain_exceptions: tuple[str, ...] = ("mediawiki.org",)
    external_link_target: object = False
    fragment_mode: tuple[str, ...] = ("html5", "legacy")
    external_interwiki_fragment_mode: str = "legacy"
    allow_external_images: bool = False
    allow_external_images_from: object = ""
    enable_image_whitelist: bool = False
    allow_image_tag: bool = False
    raw_html: bool = False
    max_toc_level: int = 999
    enable_magic_links: dict = field(default_factory=lambda: {"ISBN": False, "PMID": False, "RFC": False})
    enable_uploads: bool = False
    thumb_limits: tuple[int, ...] = (120, 150, 180, 200, 250, 300)
    max_pp_node_count: int = 1000000
    max_pp_expand_depth: int = 100
    max_template_depth: int = 100
    expensive_parser_function_limit: int = 100
    max_article_size: int = 2048  # kibibytes
    link_holder_batch_size: int = 1000
    localtimezone: str = "UTC"

    def with_(self, **changes) -> "Config":
        return replace(self, **changes)


DEFAULT = Config()

# ParserTestRunner::staticSetup() and perTestSetup()
TEST = Config(
    sitename="MediaWiki",
    meta_namespace="TestWiki",
    server="http://example.org",
    server_name="example.org",
    script_path="",
    script="/index.php",
    article_path="/wiki/$1",
    capital_links=True,
    no_follow_links=True,
    no_follow_domain_exceptions=("no-nofollow.org",),
    external_link_target=False,
    fragment_mode=("legacy",),  # "Test with legacy encoding by default until HTML5 is very stable and default"
    allow_external_images=True,
    enable_uploads=True,
    enable_magic_links={"ISBN": True, "PMID": True, "RFC": True},
    thumb_limits=(0, 0, 0, 0, 0, 180),
    max_toc_level=999,
)

# The Bohemia Interactive Community wiki (meta=siteinfo, 2026-10-29/30, saved in biki_siteinfo.json): titles are case
# sensitive ($wgCapitalLinks false), magic links are off, and only these URL protocols are links
BIKI = Config(
    url_protocols=("http://", "https://", "ftp://", "ftps://", "sftp://", "steam://", "armareforger://", "enfusion://",
                   "mailto:"),
    sitename="Bohemia Interactive Community",
    meta_namespace="Bohemia Interactive Community",
    server="https://community.bistudio.com",
    server_name="community.bistudio.com",
    script_path="/wikidata",
    script="/wiki",
    article_path="/wiki/$1",
    capital_links=False,
    localtimezone="Europe/Prague",
    max_article_size=20000,
)

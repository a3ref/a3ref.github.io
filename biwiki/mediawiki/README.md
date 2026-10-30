# biwiki.mediawiki: a Python port of the MediaWiki parser

A port of the wikitext parser of [MediaWiki](https://www.mediawiki.org/) **1.39**, the version the
Bohemia Interactive Community Wiki runs, so that a3ref renders wiki pages the way the wiki itself does.

## Origin

- Source: MediaWiki, tag `1.39.0` (commit `c95fc4786beba034fa643062b98a60ccbde831fd`), the release the wiki runs
  (<https://github.com/wikimedia/mediawiki/tree/1.39.0>), mainly `includes/parser/` and `tests/parser/`. The port
  was begun from branch `REL1_39` at commit `19ddcf0` (1.39.17); the fixes backported there after 1.39.0 were taken
  out again on 2026-10-30.
- Copyright (C) MediaWiki contributors; see <https://www.mediawiki.org/wiki/Special:Version/Credits>.
- Port: Copyright (C) 2026 a3ref contributors.

## License

GNU General Public License, version 2 or (at your option) any later version, the license of MediaWiki.
The full text is in [COPYING](COPYING). This applies to everything in this directory and in
`tests/mediawiki/` (MediaWiki's parser test cases, `parserTests.txt`, copied unchanged).

## Changes from the original

The code is translated from PHP to Python and is therefore changed throughout; every file says which MediaWiki
file it comes from and when it was ported. Beyond the translation:

- only what renders wikitext is ported: no database, caches, hooks of other extensions, user preferences or
  page editing;
- pages, templates and their existence come from an object the caller passes (in a3ref, the synced wiki pages),
  not from a database;
- the extensions the wiki runs are ported or reimplemented here as far as they shape page content
  (ParserFunctions, Cite, SyntaxHighlight and Bohemia Interactive's own tags such as `<sqf>`); the latter are not
  public, so they follow the HTML the wiki produces.

## File header

Every file in this directory starts with:

```python
# Ported from MediaWiki 1.39 <path of the PHP file> (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on <date>: translated to Python <and what else>.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
```

## Status and plan

Ported (with tests): doQuotes, BlockLevelPass, StripState, magic words, Sanitizer, StringUtils, the preprocessor
(Preprocessor_Hash, nodes, frames), tables, headings, double-underscore words, external and magic links, Html,
Title/MediaWikiTitleCodec, namespaces and interwikis (Site, with the BI wiki's own settings in `biki_siteinfo.json`).

In progress: the template half of Parser.php and CoreTagHooks; CoreParserFunctions and CoreMagicVariables; internal
links, LinkHolderArray and LinkRenderer; RemexHtml 3.0.2 (MIT, `remex/`) and MediaWiki's tidy layer.

Still to do: finalizeHeadings/formatHeadings (TOC, edit-section links, ParserOutput::getText), images and galleries
(Parser::makeImage, Linker::makeImageLink, File), then the wiki's extensions: ParserFunctions (incl. string
functions), RegexFunctions, LabeledSectionTransclusion, Cite, SyntaxHighlight, TemplateData, CharInsert, YouTube,
FontAwesome, Math, CategoryTree, DynamicPageList; and Bohemia Interactive's own, which are not public and follow
the HTML the wiki produces (`action=parse`): SQF Highlighter (`<sqf>`, `<sqs>`), Enforce Script Highlighter
(`<enforce>`), BIKI Spoiler (`<spoiler>`), BIKI Helper (`#biki-date`).

a3ref's build renders every page through the port (wikitext -> HTML -> Markdown/JSON/site, see
`biwiki/portrender.py` and `biwiki/htmlmd.py`); it replaced a direct wikitext -> Markdown renderer, which was
removed once the output had been compared page by page.

## Tests

`python -m biwiki.mediawiki.parsertests` runs MediaWiki's own parser tests (`tests/mediawiki/parserTests.txt` and the
other core files) and those of the ported extensions (`tests/mediawiki/ext/`, with the extension registered through
`ext.register_all`) and reports how many pass, per extension file; `--accept` stores the passing ones in `tests/mediawiki/passing.txt`, which
`python -m unittest` keeps from regressing.

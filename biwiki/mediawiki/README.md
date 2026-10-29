# biwiki.mediawiki: a Python port of the MediaWiki parser

A port of the wikitext parser of [MediaWiki](https://www.mediawiki.org/) **1.39**, the version the
Bohemia Interactive Community Wiki runs, so that a3ref renders wiki pages the way the wiki itself does.

## Origin

- Source: MediaWiki, branch `REL1_39`, commit `19ddcf09181a8b7d2837b4c99e11184c53047697`
  (<https://github.com/wikimedia/mediawiki/tree/REL1_39>), mainly `includes/parser/` and `tests/parser/`.
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

## Tests

`python -m biwiki.mediawiki.parsertests` runs MediaWiki's own parser tests (`tests/mediawiki/parserTests.txt`) and
reports how many pass; `--accept` stores the passing ones in `tests/mediawiki/passing.txt`, which
`python -m unittest` keeps from regressing.

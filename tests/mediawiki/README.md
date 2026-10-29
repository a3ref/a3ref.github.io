# MediaWiki parser tests

`parserTests.txt` is MediaWiki's parser test suite, copied unchanged from MediaWiki branch `REL1_39`, commit
`19ddcf09181a8b7d2837b4c99e11184c53047697` (`tests/parser/parserTests.txt`). Its test cases are "(C) their
respective authors and released under the GPL" (see the file's header): GNU General Public License, version 2 or
later, as all of this directory and `biwiki/mediawiki/` (full text: `biwiki/mediawiki/COPYING`).

`mediaParserTests.txt`, `legacyMediaParserTests.txt`, `extraParserTests.txt` and `pfeqParserTests.txt` are the other
core test files of MediaWiki 1.39 (`tests/parser/`, same commit, unchanged, same license). The runner reads all five;
a test name that an earlier file already has gets the suffix ` [media]`, ` [legacyMedia]`, ` [extra]` or ` [pfeq]`.

`passing.txt` lists the tests the port passes (written by `python -m biwiki.mediawiki.parsertests --accept`).

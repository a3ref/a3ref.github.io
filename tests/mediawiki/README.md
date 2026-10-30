# MediaWiki parser tests

`parserTests.txt` is MediaWiki's parser test suite, copied unchanged from MediaWiki tag `1.39.0`, commit
`c95fc4786beba034fa643062b98a60ccbde831fd` (`tests/parser/parserTests.txt`), the release the wiki runs. Its test cases are "(C) their
respective authors and released under the GPL" (see the file's header): GNU General Public License, version 2 or
later, as all of this directory and `biwiki/mediawiki/` (full text: `biwiki/mediawiki/COPYING`).

`mediaParserTests.txt`, `legacyMediaParserTests.txt`, `extraParserTests.txt` and `pfeqParserTests.txt` are the other
core test files of MediaWiki 1.39 (`tests/parser/`, same commit, unchanged, same license). The runner reads all five;
a test name that an earlier file already has gets the suffix ` [media]`, ` [legacyMedia]`, ` [extra]` or ` [pfeq]`.

`ext/<extension>/` holds the parser test files of the ported extensions (their `tests/parser/`, unchanged, GPL as
the extensions): `ext/ParserFunctions/` those of ParserFunctions 1.6.0 (REL1_39 as released with MediaWiki 1.39.0,
commit `4b0abc7f9fdc4593dc9b2db0b3fd5a4e76fc8e7a`), `ext/Cite/` those of Cite (commit
`951ea9c64b72b0bd1ed8119f8d4c8ca4e2948454`, MediaWiki 1.39.0). The runner reads them after the core files, each
with its extension registered (`EXT_TEST_FILES` in `biwiki/mediawiki/parsertests.py`); duplicate names get the same
kind of suffix (` [funcs]`, ` [cite]`, ...).

`passing.txt` lists the tests the port passes (written by `python -m biwiki.mediawiki.parsertests --accept`).

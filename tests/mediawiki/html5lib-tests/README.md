# html5lib tests

Test data for the RemexHtml port (`biwiki/mediawiki/remex/`), run by `tests/test_mediawiki_remex.py`.

- `tokenizer/`, `tree-construction/`, `LICENSE`, `AUTHORS.rst`: from [html5lib-tests](https://github.com/html5lib/html5lib-tests),
  commit `b2f4f5844192ed097bd7993dfb0bcbd4c7a4aeb0` (2016-05-14), copied unchanged. This is the revision RemexHtml
  3.0.2 bundles in its `tests/html5lib/` (the directory trees are identical). Copyright (c) 2006-2013 James Graham,
  Geoffrey Sneddon, and other contributors; MIT license, see [LICENSE](LICENSE). Only the files RemexHtml's tests
  run are kept: not `tokenizer/pendingSpecChanges.test`, `tokenizer/unicodeCharsProblematic.test` and
  `tree-construction/menuitem-element.dat` (which RemexHtml skips), nor the `encoding/`, `serializer/` and
  `tree-construction/scripted/` tests (which it does not run).
- `remex-local/remex01.dat`: RemexHtml's own tree construction tests, `tests/local/tree-construction/remex01.dat` at
  tag 3.0.2 (<https://github.com/wikimedia/remex-html>), copied unchanged. Copyright (c) 2016 Wikimedia Foundation;
  MIT license, see `biwiki/mediawiki/remex/LICENSE`.

The MIT licenses above apply to these files instead of the GPL that covers the rest of `tests/mediawiki/`.
`.gitattributes` keeps git from converting the line endings, as in html5lib-tests: some tests contain carriage
returns.

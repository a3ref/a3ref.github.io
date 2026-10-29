# biwiki.mediawiki.remex: RemexHtml in Python

A translation to Python of [RemexHtml](https://github.com/wikimedia/remex-html), the HTML 5 parser MediaWiki uses
for tidying its output (`biwiki/mediawiki/tidy.py`) and in its Sanitizer.

## Origin

- Source: wikimedia/remex-html, tag **3.0.2** (commit `a471c8d472a6e80fc4f7a5a77c10758c24325d43`), the version
  MediaWiki 1.39.0 requires; `src/` except the DOM builder (`src/DOM/`), the token generator, the PropGuard trait and
  the destructor tracer, which MediaWiki's parser does not use.
- Copyright (c) 2016 Wikimedia Foundation; credits: Tim Starling, C. Scott Ananian (see [LICENSE](LICENSE)).
- Translated to Python by a3ref contributors on 2026-10-30.

## License

MIT, the license of RemexHtml: see [LICENSE](LICENSE), which holds RemexHtml's license text and credits. This
directory is the exception to the GPL of the rest of `biwiki/mediawiki/`.

## Layout

The subpackages follow RemexHtml's namespaces, with RemexHtml's class names and snake_case method names:
`htmldata.py` (HTMLData), `tokenizer/` (Tokenizer, the attribute classes, the token handlers), `treebuilder/`
(TreeBuilder, Dispatcher, the stacks, the insertion modes grouped into a few modules), `serializer/` (Serializer,
HtmlFormatter and the other formatters). Every file names the PHP files it comes from.

## Changes from the original

Beyond the translation: strings are Python strings, so offsets count code points instead of bytes; the named
character references come from `html.entities.html5` (the same table) and are matched by a longest-prefix lookup
that gives the same result as RemexHtml's regex alternation; PCRE patterns are rewritten where Python's `re` differs
(see the comments in `tokenizer/tokenizer.py`). The tests (`tests/test_mediawiki_remex.py`) run the html5lib tests
RemexHtml runs, with the same skip list.

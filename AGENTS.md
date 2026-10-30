# AGENTS.md

Instructions for AI coding agents working on this repository. What the project publishes and how people use it
is in [README.md](README.md); read it only when the task touches the public output. This file is how to work on
the code.

**a3ref** mirrors the Arma 3 scripting pages of the BI Community Wiki (commands, functions, concept topics) and
publishes them as Markdown, JSON and HTML at https://a3ref.github.io/. This repository holds the Python code
(package `biwiki`) and deploys the site; it holds no data.

## Repositories

| Repository | Contents |
|---|---|
| a3ref/a3ref.github.io (this) | parser, site generator, deploy workflow |
| [a3ref/data](https://github.com/a3ref/data) | raw wikitext cache and generated JSON; syncs from the wiki twice a day using this repo's code |
| [a3ref/mcp](https://github.com/a3ref/mcp) | MCP server + Claude Code plugin; reads the live site, has its own [AGENTS.md](https://github.com/a3ref/mcp/blob/main/AGENTS.md) |

`build`, `sync` and `feed` need a clone of a3ref/data. By default they read it from `data/` in this repository
(gitignored; the deploy workflow checks it out there too). For a clone elsewhere pass `--raw <clone>/raw`,
`--dataset <clone>` and `feed --data <clone>`.

## Setup

```sh
pip install -r requirements.txt               # Python 3.10+; CI uses 3.12
git clone https://github.com/a3ref/data data  # needed by build and feed
```

## Commands

| Command | Time | What it does |
|---|---|---|
| `python -m unittest` | ~6 s | parser and end-to-end build tests on `tests/fixtures/raw/` (no data clone needed) |
| `python -m biwiki build` | ~2.5 min | full mirror from `data/raw/` into `out/` (gitignored), rendered through the MediaWiki parser port with the templates in `data/raw/templates.json` (`--templates <file>` for others); without that file it warns and uses the legacy renderer |
| `python -m biwiki build --renderer legacy` | ~20 s | the same with the legacy renderer (`biwiki/wikitext.py`), kept for comparison |
| `python -m biwiki report` | 1 s | new parser problems in `out/report.json` compared with `known-problems.json` |
| `python -m biwiki --dataset data build` | ~2.5 min | also rewrite the JSON bundles in the data clone |
| `python -m biwiki feed` | ~5 s | `changes.*` and `feed.xml` from the git history of the data clone |
| `python -m biwiki serve --port 8000` | — | serve `out/` |
| `python -m biwiki sync` | ~10 s | download changed wiki pages: opens a real Chrome window and contacts the wiki. Reads the wiki's recent changes since the newest edit in the cache; `--walk` lists every member page instead (~2 min, also the fallback when the cache is empty or older than ~90 days). Either also updates `raw/templates.json`, the templates the pages transclude. Do not run it unless the task needs fresh pages; `build` works from the cache |

## Verify a change

1. `python -m unittest` passes. In Claude Code a hook runs it after every edit to `biwiki/` or `tests/`.
2. `python -m biwiki build` then `python -m biwiki report`: no new problems. If a change fixes problems or
   knowingly accepts new ones, run `python -m biwiki report --accept` and commit `known-problems.json`.
3. Check the real output of what you changed, e.g. `out/commands/setPos.md`, `out/commands/setPos.json`,
   `out/index.json`. To compare with the published version: `curl -s https://a3ref.github.io/commands/setPos.md`.
4. HTML, CSS or JS changes: open the page via `python -m biwiki serve`. Pages must stay valid for html-validate,
   the W3C HTML/CSS validators, axe (WCAG 2.2 AA, light and dark) and Lighthouse; see the constraints below.
5. A new parser case: add the page title to `PAGES` in `tests/fixtures/refresh.py`, run it, add a test.

## Where to change what

| Task | Place |
|---|---|
| wiki markup or template rendered wrong | the wiki's HTML → Markdown/plain text: `biwiki/htmlmd.py` (`HtmlMarkdown`); wikitext → the wiki's HTML: the parser port in `biwiki/mediawiki/` (its README; the wiki's setup in `biki.py`, extensions in `ext/`); the glue (fragment cache, revision times): `biwiki/portrender.py`. The legacy renderer (`--renderer legacy`) is `biwiki/wikitext.py` |
| templates the port renders with | `raw/templates.json` in the data clone, written by `fetch.sync_templates` |
| fields of a record (syntax, params, types, status, locality) | `biwiki/parse.py` (`parse_page`, `split_param`, `syntax_form`, `_status`) |
| placeholder function pages, header comments | `biwiki/docblock.py`, `parse._fill_from_docblock` |
| file layout, `index.json`, `syntax.json`, `llms.txt`, `names.txt`, sitemap | `biwiki/render.py` (`build` and the `_*` writers) |
| HTML pages, CSP, SEO metadata, structured data | `biwiki/site.py`; styles and scripts in `biwiki/assets/` |
| which pages are mirrored | `biwiki/fetch.py`: `CATEGORIES`, `TOPIC_TITLES`, `TOPIC_CATEGORIES`, `TOPIC_ROOT` with `TOPIC_SKIP_CATEGORY` / `TOPIC_SKIP_TITLE` (takes effect for existing pages only after a walk, which runs weekly: once pushed, start one with `gh workflow run sync.yml -R a3ref/data -f walk=true`; the site follows within the hour); the incremental sync is `fetch.sync_recent` |
| topic groups | `biwiki/render.py`: `TOPIC_GROUPS`, `topic_group` |
| JSON format documentation | `biwiki/schema.json` (copied to `out/` and the data clone) and "JSON record" in README.md |
| parser health report, GitHub issue | `biwiki/report.py`, baseline `known-problems.json` |
| change feed | `biwiki/feed.py` |
| deployment, schedule, watchdog | `.github/workflows/site.yml`; the data sync is `.github/workflows/sync.yml` in a3ref/data |
| icons, preview image | `scripts/make_brand_assets.py` |

Data flow: `fetch.sync` → `data/raw/{commands,functions,topics}.json` (wikitext by page id) and
`data/raw/templates.json` (the templates they transclude) → `render.build` (`parse.parse_page` / `parse_topic` cut a
page into fragments; `portrender.PortRenderer` parses each fragment once with the MediaWiki parser port into the
wiki's HTML and `htmlmd` converts it three times: plain text for JSON, mirror-only links for Markdown, wiki links
for HTML) → `out/` and, with `--dataset`, `data/*.json`. With `--renderer legacy`, or before the first template
sync, `wikitext.Renderer` renders the wikitext directly instead.

## Rules

- **English only** in everything committed: code, comments, docs, commit messages, generated text.
- **Never edit generated files**: `out/`, the data clone's `*.json` and `raw/`, `dist/` in a3ref/mcp. Change the code
  and rebuild.
  A Claude Code hook blocks these edits.
- **Deterministic output.** No build times, random order or absolute paths in the data: bundles are sorted, one
  record per line, and `updated` is the newest wiki edit, so the daily sync commits only real changes.
- **Contracts other code relies on**: `index.json` fields `name`, `type`, `syntax`, `summary`, `groups`, `status`,
  `operator`, `aliases`, `md`, `json`; `syntax.json` `commands`/`functions` keyed by lower-case name with `forms`,
  `status`, `replaced_by`, `branch`, `syntax`; topic records' `sections`. The MCP server (a3ref/mcp) and
  external users read them. Changing them means updating `biwiki/schema.json`, README.md and a3ref/mcp.
- **Stable URLs.** Page paths come from `render.slug` / `page_slug`; changing them breaks links agents already use.
- **Markdown links only to mirrored pages** (agents cannot open the wiki behind its bot check); HTML may link to
  the wiki.
- **Site constraints**: no inline scripts or styles (strict CSP; JSON-LD hashes are computed in `site.py`), no
  external requests or JS libraries, headings never skip a level, content inside landmarks, colors meet WCAG AA in
  both themes, CSS/JS minified by `site.py` at build time.
- **Dependencies**: three runtime packages (`requirements.txt`). Do not add more without a strong reason.
- **Local Windows, CI Linux.** Write files as UTF-8 with `\n`. Windows and macOS file systems are case-insensitive, so
  the lower-case alias pages (`commands/setpos.md`) are only produced on Linux.
- **Outward actions need the maintainer's consent**: pushing to `main` deploys the site; `report --issue` writes
  to GitHub; `sync` contacts the wiki.

## MediaWiki parser port (`biwiki/mediawiki/`)

A Python port of the MediaWiki 1.39 parser renders the pages as the wiki renders them (the default renderer); see
`biwiki/mediawiki/README.md`. Its rules:

- **License: GPL-2.0-or-later**, as MediaWiki; the rest of the repository is MIT (see `LICENSE`). Code translated
  or adapted from MediaWiki goes into `biwiki/mediawiki/` only, never into MIT files, with the header given in
  its README (origin file, "(C) MediaWiki contributors", what was changed and when).
- Port from MediaWiki tag `1.39.0` (commit `c95fc47`), the release the wiki runs, not from later `REL1_39`
  commits, file by file, keeping names and comments so it can be
  compared with the PHP.
- `python -m biwiki.mediawiki.parsertests` runs MediaWiki's parser tests (`tests/mediawiki/parserTests.txt`);
  after a step that makes more of them pass, `--accept` and commit `tests/mediawiki/passing.txt`.

## Conventions

- Style: as in the surrounding code; type hints, `from __future__ import annotations`, docstrings that explain why.
- Commit messages: one plain sentence saying what changed and why, no prefixes (see `git log`).
- No `--no-verify`, no force pushes, no rewriting history.

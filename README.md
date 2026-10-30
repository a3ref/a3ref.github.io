# a3ref — Arma 3 scripting reference for AI agents

**Every Arma 3 scripting command and function, built first for AI agents, bots and programs.**

A daily-updated mirror of every page in
[Category:Arma 3: Scripting Commands](https://community.bistudio.com/wiki/Category:Arma_3:_Scripting_Commands),
[Category:Arma 3: Functions](https://community.bistudio.com/wiki/Category:Arma_3:_Functions)
and the concept pages they rely on (data types, `Position`, locality, scheduler, event handlers, `Description.ext`, ...),
plus every other Arma 3 page of
[Category:Arma 3](https://community.bistudio.com/wiki/Category:Arma_3) (mission editing, configs, GUI controls,
multiplayer and server, tools, file formats, reference lists, ...)
from the Bohemia Interactive Community Wiki. The original wiki sits behind a bot challenge that blocks scripts and
agents; this mirror serves the same content as **Markdown** and **JSON** at stable, predictable URLs, with no API key,
no rate limit and open CORS. A readable **HTML** version is there for people too.

Site: **https://a3ref.github.io/** · Data: **[a3ref/data](https://github.com/a3ref/data)** ·
MCP server: **[a3ref/mcp](https://github.com/a3ref/mcp)** · Agent guide: **https://a3ref.github.io/llms.txt** ·
Working on the code: **[AGENTS.md](AGENTS.md)**

## For AI agents and programs

The easiest way for an agent is the **[MCP server](https://github.com/a3ref/mcp)**: search, read pages and lint SQF
(catches made-up commands, missing operands, unknown `BIS_fnc_*` functions, deprecated commands). In Claude Code:
`/plugin marketplace add a3ref/mcp`, then `/plugin install a3ref@a3ref`.

Without MCP, everything is a plain GET:

| You need | Fetch |
|---|---|
| where to start | [`llms.txt`](https://a3ref.github.io/llms.txt): how to use the mirror, topics, groups (a few thousand tokens) |
| one command | `https://a3ref.github.io/commands/<name>.md` or `.json`, e.g. [`commands/setPos.md`](https://a3ref.github.io/commands/setPos.md) |
| one function | `https://a3ref.github.io/functions/<name>.md` or `.json`, e.g. [`functions/BIS_fnc_spawnGroup.json`](https://a3ref.github.io/functions/BIS_fnc_spawnGroup.json) |
| a concept | `https://a3ref.github.io/topics/<name>.md`, e.g. [`topics/Multiplayer_Scripting.md`](https://a3ref.github.io/topics/Multiplayer_Scripting.md), [`topics/Event_Handlers.md`](https://a3ref.github.io/topics/Event_Handlers.md) |
| every name | [`names.txt`](https://a3ref.github.io/names.txt), one per line |
| one group | `groups/commands/<group>.md`, `groups/functions/<group>.md`, listed in `llms.txt` |
| to search | [`index.json`](https://a3ref.github.io/index.json) (2 MB): every entry with syntax, summary, groups, locality, status, operator symbol, paths |
| everything | [`commands.json`](https://a3ref.github.io/commands.json) (7 MB), [`functions.json`](https://a3ref.github.io/functions.json) (4 MB), [`topics.json`](https://a3ref.github.io/topics.json) (27 MB): for programs; a model should read single pages instead |
| a linter's data | [`syntax.json`](https://a3ref.github.io/syntax.json) (0.5 MB): forms (nullary/unary/binary), status, replacements and syntax of every name |
| the record format | [`schema.json`](https://a3ref.github.io/schema.json) (JSON Schema 2020-12) |
| what changed | [`changes.md`](https://a3ref.github.io/changes.md), [`changes.json`](https://a3ref.github.io/changes.json), Atom [`feed.xml`](https://a3ref.github.io/feed.xml) |
| version history | the [a3ref/data](https://github.com/a3ref/data) repository, one commit per day with changes |

Paths use the name as written in scripts (`setPos`, `diag_fps`, `BIS_fnc_spawnGroup`), and **lower-case paths work
too** (`commands/setpos.md`). Spaces become `_`; other characters outside `A-Za-z0-9.-` become `~XX` per UTF-8 byte
(the operator page `a != b` is `commands/a_~21~3D_b.md`; `index.json` also lists operators by symbol). A missing page
returns a 404 that explains how to find the right path.

What the records add on top of the wiki text:

- `status` (`ok`, `deprecated`, `broken`) and `replaced_by`, so agents avoid outdated commands;
- the type of every parameter and return value normalised for programs (`type_expr`: `Array<String>`,
  `Object | Group`), whose names are the data type topics;
- for commands, the syntax `form` (`nullary`, `unary`, `binary`) with typed `left`/`right` operands, and the
  `operator` symbol of operator pages;
- for the ~400 placeholder function pages, the description, parameters, return value and examples parsed from the
  function's header comment in the game files (`docblock`, `filled_from_docblock`).

Markdown pages are the best fit for a model's context: description, every syntax with typed parameters and return
value, locality, examples and community notes in one file. Links in Markdown point only to other mirrored pages
(agents cannot open the wiki); HTML pages also link to the wiki.

### Add it to your agent

Paste this into `AGENTS.md`, `CLAUDE.md`, `.cursorrules` or your system prompt:

```markdown
## Arma 3 / SQF reference
When writing or reviewing SQF for Arma 3, check commands and BIS_fnc_* functions against
https://a3ref.github.io/ instead of relying on memory:
- https://a3ref.github.io/commands/<command>.md (e.g. commands/setPos.md)
- https://a3ref.github.io/functions/<BIS_fnc_name>.md (e.g. functions/BIS_fnc_spawnGroup.md)
- https://a3ref.github.io/topics/<topic>.md (e.g. topics/Multiplayer_Scripting.md)
- https://a3ref.github.io/names.txt lists every name; https://a3ref.github.io/llms.txt explains the rest
Check syntax, parameter types, return value, locality (local/global argument and effect),
status (deprecated commands name a replacement) and the Arma 3 version that introduced the command.
```

### From code

```sh
curl -s https://a3ref.github.io/commands/setPos.md
curl -s https://a3ref.github.io/index.json | jq -r '.items[] | select(.name | test("^setPos")) | .syntax[]'
```

```python
import json, urllib.request

index = json.load(urllib.request.urlopen("https://a3ref.github.io/index.json"))
entry = next(e for e in index["items"] if e["name"].lower() == "createvehicle")
page = json.load(urllib.request.urlopen("https://a3ref.github.io/" + entry["json"]))
for s in page["syntaxes"]:
    print(s["syntax"], "->", s["returns"]["type"] if s["returns"] else None)
```

```js
const index = await (await fetch("https://a3ref.github.io/index.json")).json();
const fns = index.items.filter((e) => e.type === "function" && e.groups.includes("Multiplayer"));
```

The same files are also served by `raw.githubusercontent.com/a3ref/data/main/…` and
`cdn.jsdelivr.net/gh/a3ref/data@main/…`.

## How it works

The wiki sits behind a Cloudflare managed challenge, so plain HTTP clients get a 403.
`sync` starts the locally installed Google Chrome through [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright),
lets it pass the check, then calls the MediaWiki API (`/wikidata/api.php`) with `fetch()` from inside the page:
50 pages of wikitext per request, about 110 requests in total. Raw wikitext is cached in `raw/*.json` of the data clone.
Later runs read the wiki's recent changes from the newest edit in the cache (minus a day of overlap) and download
only the pages edited, created, moved or deleted since, deciding whether a new page belongs by its categories: a few
requests, a few seconds. `sync --walk` lists every member page instead and downloads those whose `revid` changed; it
also catches pages that join or leave a category through a template, and it is used automatically when the cache is
empty or older than the wiki's 90 days of recent changes.

`sync` also keeps the wiki templates the mirrored pages transclude, recursively, in `raw/templates.json`: the walk
asks the wiki for the templates of every page (50 pages per request, about 220 requests) and downloads those whose
`revid` changed; later runs read the template namespace's recent changes in the same request as the pages', refetch
the edited templates and add the new templates of the pages they download.

`build` then parses each page's `{{RV}}` template with `mwparserfromhell` into structured fields, renders the wikitext
of each field and concept page with a Python port of the wiki's MediaWiki 1.39 parser (`biwiki/mediawiki/`) and those
templates into the HTML the wiki shows, converts that to Markdown and plain text (`biwiki/htmlmd.py`), and writes the
mirror to `out/`. Without `raw/templates.json` it stops and says how to get the file (`sync --walk`).

## Deployment

Three repositories, no secrets:

- **[a3ref/data](https://github.com/a3ref/data)** holds the data: raw wikitext of the pages and their templates (`raw/*.json`) and the parsed
  `commands.json`, `functions.json`, `topics.json`, `index.json`, `syntax.json`. Its workflow runs **twice a day, at 04:17 and 16:17 UTC**: it checks out this
  repository for the code, runs `sync` (real Chrome inside `xvfb`) and `build --dataset`, and commits only if
  something changed. A third run, on Sundays at 10:17 UTC, uses `sync --walk`.
- **this repository** holds only the code. `.github/workflows/site.yml` builds the site from the latest
  `a3ref/data` and deploys it to GitHub Pages:
  - on every push to `main` (parser or design changes);
  - **every hour**, but only if the data commit differs from `data-version.txt` on the live site, so the site
    follows every data sync, scheduled or run by hand, within the hour;
  - every 6 hours a watchdog run fails (and GitHub emails) if the data sync has not succeeded for 26 hours, since
    GitHub may drop scheduled runs;
  - manually (Actions → Deploy site → Run workflow).
- **[a3ref/mcp](https://github.com/a3ref/mcp)** is the MCP server and Claude Code plugin; it reads the live site.

Everything in `out/` is generated during deployment and never committed.

If Cloudflare ever blocks the GitHub runner, sync locally
(`python -m biwiki sync && python -m biwiki --dataset data build`, then commit and push in the data clone).

## Parser problems

Every build writes `report.json` (also published at https://a3ref.github.io/report.json) and never stops on a single
broken page: the page is left out, reported, and the rest of the site is built.

After each deploy, `python -m biwiki report --issue` compares the report with `known-problems.json`, the accepted baseline.
Problems are compared by their key (kind, page, detail); where it can be found, each one also says where it is:
`"md": "line:column"` in the page's `.md`, `"wiki": "line:column"` in the wikitext, and the text around it.

- **new problems** open (or update, with a comment) the issue labelled `parser-report`, listing each page with links to
  the site and the wiki; GitHub notifies watchers of the repository;
- **a page the parser crashed on** additionally fails the workflow run, which sends the usual failure email;
- when the new problems are gone, the issue is closed automatically;
- the run page in Actions shows the same summary.

After fixing the parser or deciding a problem is acceptable, refresh the baseline locally and commit it:

```sh
python -m biwiki build
python -m biwiki report            # what is new compared to the baseline
python -m biwiki report --accept   # accept the current state as the baseline
```

## Development

Requires Python 3.10+ and Google Chrome (for `sync` only). Agents: read [AGENTS.md](AGENTS.md) first; it lists the
commands, where to change what, the rules and how to verify a change.

```sh
pip install -r requirements.txt
git clone https://github.com/a3ref/data data      # the data lives in its own repository; elsewhere: --raw/--dataset/--data

python -m unittest                 # tests on tests/fixtures (under a second, no data clone needed)
python -m biwiki build             # regenerate out/ from the cache only (about 20 s)
python -m biwiki report            # new parser problems compared with known-problems.json
python -m biwiki serve --port 8000 # serve out/ over HTTP
python -m biwiki update            # sync + build (opens a Chrome window for a few seconds)
python -m biwiki sync --walk       # list every member page instead of reading recent changes (about a minute)
python -m biwiki update --hidden   # same, with the Chrome window moved off-screen
python -m biwiki sync --full       # re-download everything, ignoring the cache
python -m biwiki --dataset data build  # also refresh the parsed JSON in the data repository
```

`--only commands` / `--only functions` limits the work to one category.
Cloudflare rejects real headless Chrome; if a checkbox appears, run without `--hidden` and click it.

## Output (`out/`)

| File | Purpose |
|---|---|
| `index.html` | **the site**: home page with search, groups, topics, recent edits |
| `commands/`, `functions/`, `topics/` | one page per entry as `<name>.md` (YAML front matter + Markdown), `.json` and `.html`, plus lower-case aliases and an `index.md`/`index.html` by group; `<name>.og.png` is the page's 1200×630 preview image for link previews |
| `commands.json`, `functions.json`, `topics.json` | every record of one kind in a single file |
| `index.json` | lightweight index: name, type, syntaxes, summary, groups, locality, status, operator, aliases, paths |
| `names.txt` | every name, one per line, with paths where they do not follow the simple rule |
| `groups/<kind>/<group>.md` | per-group lists with summaries |
| `syntax.json` | forms, status, replacements and syntax lines of every name, for linters (used by the MCP server) |
| `llms.txt`, `llms-full.txt` | short guide for language models, and the full list of every page |
| `changes.md`, `changes.json`, `feed.xml` | wiki edits, from the git history of a3ref/data (written by `python -m biwiki feed`) |
| `robots.txt`, `sitemap.xml`, `404.html` | crawlers and search engines; the 404 page redirects people and explains paths to agents |
| `schema.json` | JSON Schema of every file above |
| `report.json` | parser health report: crashes, skipped pages, unknown templates, leftover markup, untyped parameters |
| `assets/` | stylesheet, script and search index of the HTML version |

### JSON record

A command or function record (format 2, `"version": 2` in [`schema.json`](https://a3ref.github.io/schema.json)),
shortened:

```jsonc
{
  "name": "createVehicle",            // as written in code (BIS_fnc_... for functions)
  "title": "createVehicle",           // wiki page title
  "type": "command",                  // or "function"
  "url": "https://community.bistudio.com/wiki/createVehicle",
  "revid": 377509, "updated": "2026-01-02T06:50:13Z",
  "groups": ["Object Manipulation"],
  "status": "ok",                     // or "deprecated" / "broken", then also "replaced_by": [...]
  "games": {"ofp": "1.34", "ofpe": "1.00", "arma1": "1.00", ..., "arma3": "0.50"},  // oldest first
  "since": "ofp 1.34",                // first game it appeared in, as the syntax and parameter "since"
  "arma3_since": "0.50",
  "locality": {"effect": "global"},   // argument locality unknown, no server execution needed
  "description": "markdown",
  "syntaxes": [{
    "syntax": "type createVehicle position",
    "params": [
      {"name": "type", "type": "String", "description": "vehicle/object className", "type_expr": "String"},
      {"name": "position", "type": "Position", "description": "desired placement position. ...", "type_expr": "Position"}
    ],
    "returns": {"type": "Object", "type_expr": "Object"},
    "form": "binary", "left": {"text": "type"}, "right": {"text": "position"}
  }, {
    "syntax": "createVehicle [type, position, markers, placement, special]",
    "params": [..., {"name": "markers", "type": "Array of Strings", "optional": true, "default": "`[]`",
                     "description": "if the markers array ...", "type_expr": "Array<String>",
                     "text": "markers: Array of Strings - (Optional, default `[]`) if the markers array ..."}, ...],
    "returns": {"type": "Object", "type_expr": "Object", "description": "created vehicle or objNull if failed"},
    "form": "unary", "right": {"text": "[type, position, markers, placement, special]"}
  }],
  "examples": [{"code": ["raw SQF"]}, {"text": "markdown", "code": ["raw SQF"]}],
  "see_also": ["createVehicleLocal", ...],
  "notes": [{"user": "MrSanchez", "date": "2015-08-22T13:04:00Z", "text": "markdown"}]
}
```

| Field | Present | Meaning |
|---|---|---|
| `name`, `title`, `type`, `url`, `revid`, `updated`, `groups`, `status`, `description`, `syntaxes` | always | `updated` may be null, `description` empty |
| `operator` | operator pages | the symbol (`!=`, `>>`) |
| `replaced_by`, `aliases`, `see_also` | when not empty | names |
| `games`, `since`, `arma3_since` | when known | game code → version that added it (null if the wiki gives none); `since` is `"<game> <version>"` |
| `branch` | dev/diag/prof-only commands | list: `["diag", "prof"]` |
| `locality` | when anything is known | `argument`, `effect` (`local`/`global`), `server_exec: true`; each key only when known |
| `exec` | functions | `spawn` / `call` |
| `syntaxes[]` | always | `syntax`, `params` and `returns` (null when the wiki gives none) always; `note`, `since`, `effect`, `server_exec: true` (this syntax runs on the server), commands' `form`, `left`, `right`, functions' `inferred` when set |
| `params[]` | | `name` always; `type`, `type_expr`, `types`, `optional: true`, `default`, `description`, `since`, `optional_since`, `text`, `source` when set |
| `examples[]`, `notes[]`, `multiplayer`, `problems` | when not empty | Markdown; examples also have their SQF `code` |
| `categories_extra` | when not empty | wiki categories that do not follow from the other fields (`WIP`, `Stubs`, `AI`, `Easter Eggs`, `Arma 3: Remote Execution`, ...) |
| `docblock`, `filled_from_docblock` | functions with a header comment | the header's `text`, `author` and `meta`; which fields were filled from it |

Every optional field is left out when it is empty (null, `[]`, `{}`, `false`, `""`): read a missing field as that
empty value. Also left out is what follows from other fields, so it can be rebuilt exactly:

- a parameter's `text` when it is `name`, then `: type` if there is a type, then ` - description` if there is a
  description; a return value's `text` when it is `type`, then ` - description` the same way;
- an example's `text` when it is only its `code`: each snippet as a ```` ```sqf ```` block, one blank line apart;
- `types` (parameters, return values, operands) when it lists the names in `type_expr` (split at `<`, `>`, `|`);
  an operand's types are those of the parameter of the same name, or `["Array"]` for an array literal;
- `categories`: the kind, the games, the groups, locality, server execution and branch categories
  (rules in `schema.json`); `syntaxes[].operator`, which repeated the record's.

Topic records (`topics/*.json`) have every field, `categories` included.

**Changed in format 2** (the files had no version before): `categories` became `categories_extra`; `games` is a map
and `since` a string; `branch` is a list (also in `syntax.json`); a syntax's `exec: "server"` is `server_exec: true`
(the record's `exec` stays spawn/call); `syntaxes[].operator` is gone; `docblock` keeps `text`, `author` and `meta`;
empty, derivable and default values are left out; a return type `-` is written as `Nothing`, game codes in `since`
are lower case (`Arma3 2.08` → `arma3 2.08`), an unknown note date is left out instead of `""`. The command and
function bundles are about 40% smaller.

`name`, `type`, `optional` and `default` of parameters are extracted heuristically from the wiki text
(`name: Type - (Optional, default x) description`); `text` holds the original, losslessly (left out only when the
rule above rebuilds it).
A parameter's `since` is the version that added it; a parameter that became optional later
("(Optional since 2.20, ...)") also has `optional_since` (`"arma3 2.20"`), present only then.
`type` is the type as the wiki writes it ("Object or Array of Objects"); `type_expr` is the same type
normalised for programs: alternatives joined with ` | `, element types as `Array<...>`
(`Object | Array<Object>`, `Array<Array<Number>>`), qualifiers such as "in range 0..1" dropped. When the
wiki lists the alternatives below the parameter (`* [[Number]]: ...` / `* [[Boolean]]: ...`), `type` is
missing and `type_expr` collects them. `type_expr` is missing when the type is free text.
In JSON, links are plain text (fewer tokens); in `.md` and `.html` they are real links.

## HTML version

A static documentation site with no build tooling and no JS dependencies: serve it with `python -m biwiki serve`
or open `out/index.html` directly from disk.

- the other pages of the current group on the left, the table of contents on the right; one page per group
  (`groups/<kind>/<group>.html`, next to the Markdown list for agents)
- search across every command, function and topic (`/` to focus, arrow keys, Enter)
- SQF highlighting where every command and function in code links to its page; Copy button on code blocks
- Note / Important / Warning boxes, locality badges (filled = global, dashed = local), status, versions
- light and dark theme following the system; mobile layout

Built to pass the checkers search engines and browsers use, tested on every page: html-validate (all pages),
the W3C HTML and CSS validators, axe (WCAG 2.2 AA, light and dark), and Lighthouse (100 for performance,
accessibility, best practices, SEO and agentic browsing on the main page types). In practice that means:

- one self-hosted font (JetBrains Mono, OFL) preloaded with `font-display: optional`; text uses the system font,
  so nothing shifts while loading; CSS and JS are minified at build time
- a strict Content-Security-Policy (no inline scripts; JSON-LD blocks listed by hash)
- canonical URLs, Open Graph and Twitter cards with a preview image drawn for each page, `TechArticle` and `BreadcrumbList` structured
  data, `sitemap.xml`, `robots.txt`, favicon, icons and a web manifest
- headings never skip a level, every piece of content sits in a landmark, scrollable code is keyboard-focusable

`scripts/make_brand_assets.py` regenerates the icons and the site-wide preview image; `biwiki/ogimage.py` draws
the per-page ones during the build (`build --no-og-images` skips them).

## Code layout

- `biwiki/fetch.py`: browser session, MediaWiki API, incremental cache of pages and templates
- `biwiki/portrender.py`, `biwiki/htmlmd.py`: render wikitext with the MediaWiki parser port, then the wiki's HTML →
  Markdown and plain text (links, lists, tables, code, notes)
- `biwiki/markdown.py`: small Markdown writers (quotes, code spans, tables without spans)
- `biwiki/parse.py`: `{{RV}}` template → record (status, types, syntax forms); concept pages → topic records;
  `biwiki/wikitext.py` has its helpers for cutting a page with `mwparserfromhell`, game names and wiki anchors
- `biwiki/docblock.py`: function header comments on placeholder pages → description, parameters, returns, examples
- `biwiki/render.py`: writes the mirror files and indexes
- `biwiki/report.py`: parser health report, baseline comparison and the GitHub issue
- `biwiki/feed.py`: change feed from the data repository's history
- `biwiki/site.py`, `biwiki/assets/`: HTML version (markdown-it-py, SQF highlighting, page templates)
- `biwiki/ogimage.py`: the per-page preview images (Pillow, JetBrains Mono), drawn in worker processes
- `biwiki/mediawiki/`: a Python port of the MediaWiki 1.39 parser, set up as the BI wiki (see its README);
  `python -m biwiki.mediawiki.parsertests` runs MediaWiki's own parser tests against it
- `tests/`: unit and end-to-end build tests on a few real pages in `tests/fixtures/raw/`; `tests/mediawiki/`:
  MediaWiki's parser test cases
- `AGENTS.md`, `CLAUDE.md`, `.claude/`: instructions and Claude Code hooks for AI agents working on the code

## License

The code is MIT-licensed ([LICENSE](LICENSE)), except `biwiki/mediawiki/` and `tests/mediawiki/`, which are derived
from MediaWiki and licensed GPL-2.0-or-later ([COPYING](biwiki/mediawiki/COPYING)); the program as a whole is
therefore distributed under the GPL. Neither license covers the content: it is the intellectual property of Bohemia
Interactive and the BI Community Wiki's contributors, used under the wiki's
[terms](https://community.bistudio.com/wiki/Meta:General_disclaimer), which allow personal, non-commercial use and
require works derived from it to stay non-commercial (it is not Creative Commons). Every generated page links to its
source and revision and says so in its footer.

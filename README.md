# a3ref — Arma 3 scripting reference for AI agents

**Every Arma 3 scripting command and function, built first for AI agents, bots and programs.**

A daily-updated mirror of every page in
[Category:Arma 3: Scripting Commands](https://community.bistudio.com/wiki/Category:Arma_3:_Scripting_Commands),
[Category:Arma 3: Functions](https://community.bistudio.com/wiki/Category:Arma_3:_Functions)
and the concept pages they rely on (data types, `Position`, locality, scheduler, event handlers, `Description.ext`, ...)
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
| everything | [`commands.json`](https://a3ref.github.io/commands.json) (7 MB), [`functions.json`](https://a3ref.github.io/functions.json) (4 MB), [`topics.json`](https://a3ref.github.io/topics.json) (1 MB): for programs; a model should read single pages instead |
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
- `types` lists for every parameter and return value (`["Array", "String"]`), linked to the data type topics;
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
50 pages of wikitext per request, about 110 requests in total. Raw wikitext is cached in `data/raw/*.json`;
later runs only download pages whose `revid` changed.

`build` then parses each page's `{{RV}}` template with `mwparserfromhell` into structured fields
and writes the mirror to `out/`.

## Deployment

Three repositories, no secrets:

- **[a3ref/data](https://github.com/a3ref/data)** holds the data: raw wikitext (`raw/*.json`) and the parsed
  `commands.json`, `functions.json`, `topics.json`, `index.json`, `syntax.json`. Its workflow runs **twice a day, at 04:17 and 16:17 UTC**: it checks out this
  repository for the code, runs `sync` (real Chrome inside `xvfb`) and `build --dataset`, and commits only if
  something changed.
- **this repository** holds only the code. `.github/workflows/site.yml` builds the site from the latest
  `a3ref/data` and deploys it to GitHub Pages:
  - on every push to `main` (parser or design changes);
  - **every 6 hours**, but only if the data commit differs from `data-version.txt` on the live site; the same run
    fails (and GitHub emails) if the data sync has not succeeded for 26 hours, since GitHub may drop scheduled runs;
  - manually (Actions → Deploy site → Run workflow).
- **[a3ref/mcp](https://github.com/a3ref/mcp)** is the MCP server and Claude Code plugin; it reads the live site.

Everything in `out/` is generated during deployment and never committed.

If Cloudflare ever blocks the GitHub runner, sync locally inside the data clone
(`python -m biwiki sync && python -m biwiki --dataset data build`, then commit and push in `data/`).

## Parser problems

Every build writes `report.json` (also published at https://a3ref.github.io/report.json) and never stops on a single
broken page: the page is left out, reported, and the rest of the site is built.

After each deploy, `python -m biwiki report --issue` compares the report with `known-problems.json`, the accepted baseline:

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
git clone https://github.com/a3ref/data data   # the data lives in its own repository

python -m unittest                 # tests on tests/fixtures (under a second, no data/ needed)
python -m biwiki build             # regenerate out/ from the cache only (about 20 s)
python -m biwiki report            # new parser problems compared with known-problems.json
python -m biwiki serve --port 8000 # serve out/ over HTTP
python -m biwiki update            # sync + build (opens a Chrome window for about a minute)
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
| `commands/`, `functions/`, `topics/` | one page per entry as `<name>.md` (YAML front matter + Markdown), `.json` and `.html`, plus lower-case aliases and an `index.md`/`index.html` by group |
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

```jsonc
{
  "name": "createVehicle",            // as written in code (BIS_fnc_... for functions)
  "title": "createVehicle",           // wiki page title
  "type": "command",                  // or "function"
  "url": "https://community.bistudio.com/wiki/createVehicle",
  "revid": 377509, "updated": "2026-01-02T06:50:13Z",
  "groups": ["Object Manipulation"],
  "games": [{"game": "ofp", "name": "Operation Flashpoint", "version": "1.34"}, ...],
  "since": {...},                      // first game it appeared in
  "arma3_since": "0.50",
  "branch": null,                      // "dev" / "diag" for commands only in dev/diag builds
  "locality": {"argument": "global", "effect": "global", "server_exec": false},
  "exec": null,                        // functions: "spawn" / "call"
  "description": "markdown",
  "syntaxes": [{
    "syntax": "type createVehicle position",
    "since": null, "effect": null, "exec": null,
    "params": [{
      "name": "type", "type": "String", "optional": false, "default": null,
      "description": "vehicle/object className", "since": null,
      "text": "full parameter text (markdown)"
    }],
    "returns": {"type": "Object", "description": null, "text": "markdown"}
  }],
  "examples": [{"text": "markdown", "code": ["raw SQF"]}],
  "multiplayer": null, "problems": null,
  "aliases": [], "see_also": ["createVehicleLocal", ...],
  "notes": [{"user": "MrSanchez", "date": "2015-08-22T13:04:00Z", "text": "markdown"}],
  "categories": [...]
}
```

`name`, `type`, `optional` and `default` of parameters are extracted heuristically from the wiki text
(`name: Type - (Optional, default x) description`); `text` always holds the original, losslessly.
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
- canonical URLs, Open Graph and Twitter cards with a preview image, `TechArticle` and `BreadcrumbList` structured
  data, `sitemap.xml`, `robots.txt`, favicon, icons and a web manifest
- headings never skip a level, every piece of content sits in a landmark, scrollable code is keyboard-focusable

`scripts/make_brand_assets.py` regenerates the icons and the preview image.

## Code layout

- `biwiki/fetch.py`: browser session, MediaWiki API, incremental cache
- `biwiki/wikitext.py`: wikitext → Markdown (links, lists, tables, `<sqf>`, `{{Feature}}`, `{{GVI}}`, `{{hl}}`, …)
- `biwiki/parse.py`: `{{RV}}` template → record (status, types, syntax forms); concept pages → topic records
- `biwiki/docblock.py`: function header comments on placeholder pages → description, parameters, returns, examples
- `biwiki/render.py`: writes the mirror files and indexes
- `biwiki/report.py`: parser health report, baseline comparison and the GitHub issue
- `biwiki/feed.py`: change feed from the data repository's history
- `biwiki/site.py`, `biwiki/assets/`: HTML version (markdown-it-py, SQF highlighting, page templates)
- `tests/`: unit and end-to-end build tests on a few real pages in `tests/fixtures/raw/`
- `AGENTS.md`, `CLAUDE.md`, `.claude/`: instructions and Claude Code hooks for AI agents working on the code

Content belongs to the authors of the BI Community Wiki; every generated page links to its source and revision.

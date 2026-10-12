# a3ref — Arma 3 scripting reference for AI agents

**Every Arma 3 scripting command and function, built first for AI agents, bots and programs.**

A daily-updated mirror of every page in
[Category:Arma 3: Scripting Commands](https://community.bistudio.com/wiki/Category:Arma_3:_Scripting_Commands) and
[Category:Arma 3: Functions](https://community.bistudio.com/wiki/Category:Arma_3:_Functions)
from the Bohemia Interactive Community Wiki. The original wiki sits behind a bot challenge that blocks
scripts and agents; this mirror serves the same content as **Markdown** and **JSON** at stable, predictable URLs,
with no API key, no rate limit and open CORS. A readable **HTML** version is there for people too.

Site: **https://a3ref.github.io/** · Data: **[a3ref/data](https://github.com/a3ref/data)** · Agent index: **https://a3ref.github.io/llms.txt**

## For AI agents and programs

| You need | Fetch |
|---|---|
| one command | `https://a3ref.github.io/commands/<name>.md` or `.json`, e.g. [`commands/setPos.md`](https://a3ref.github.io/commands/setPos.md) |
| one function | `https://a3ref.github.io/functions/<name>.md` or `.json`, e.g. [`functions/BIS_fnc_spawnGroup.json`](https://a3ref.github.io/functions/BIS_fnc_spawnGroup.json) |
| to find the right name | [`index.json`](https://a3ref.github.io/index.json): every entry with syntax, one-line summary, groups, locality and page paths |
| everything | [`commands.json`](https://a3ref.github.io/commands.json), [`functions.json`](https://a3ref.github.io/functions.json) |
| the record format | [`schema.json`](https://a3ref.github.io/schema.json) (JSON Schema 2020-12) |
| an LLM-oriented overview | [`llms.txt`](https://a3ref.github.io/llms.txt) ([llms.txt](https://llmstxt.org/) format) |
| version history | the [a3ref/data](https://github.com/a3ref/data) repository, one commit per day with changes |

URLs are case-sensitive and use the wiki spelling (`setPos`, not `setpos`). Spaces become `_`, and characters
outside `A-Za-z0-9.-` become `~XX` per UTF-8 byte (`a != b` → `a_~21~3D_b`). When unsure, look the path up in `index.json`.

Markdown pages are the best fit for a model's context: description, every syntax with typed parameters and return
value, locality, examples and community notes in one file. JSON pages hold the same as structured fields.

### Add it to your agent

Paste this into `AGENTS.md`, `CLAUDE.md`, `.cursorrules` or your system prompt:

```markdown
## Arma 3 / SQF reference
When writing or reviewing SQF for Arma 3, check commands and BIS_fnc_* functions against
https://a3ref.github.io/ instead of relying on memory:
- https://a3ref.github.io/commands/<command>.md (e.g. commands/setPos.md)
- https://a3ref.github.io/functions/<BIS_fnc_name>.md (e.g. functions/BIS_fnc_spawnGroup.md)
- https://a3ref.github.io/index.json lists every name with its syntax and a one-line summary
Names are case-sensitive and use the wiki spelling. Check syntax, parameter types, return value,
locality (local/global argument and effect) and the Arma 3 version that introduced the command.
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

Two repositories, no secrets:

- **[a3ref/data](https://github.com/a3ref/data)** holds the data: raw wikitext (`raw/*.json`) and the parsed
  `commands.json`, `functions.json`, `index.json`. Its workflow runs **daily at 04:17 UTC**: it checks out this
  repository for the code, runs `sync` (real Chrome inside `xvfb`) and `build --dataset`, and commits only if
  something changed.
- **this repository** holds only the code. `.github/workflows/site.yml` builds the site from the latest
  `a3ref/data` and deploys it to GitHub Pages:
  - on every push to `main` (parser or design changes);
  - **daily at 05:17 UTC**, but only if the data commit differs from `data-version.txt` on the live site;
  - manually (Actions → Deploy site → Run workflow).

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

## Installation

Requires Python 3.10+ and Google Chrome.

```sh
pip install -r requirements.txt
git clone https://github.com/a3ref/data data   # the data lives in its own repository
```

## Usage

```sh
python -m biwiki update            # sync + build (opens a Chrome window for about a minute)
python -m biwiki update --hidden   # same, with the Chrome window moved off-screen
python -m biwiki sync --full       # re-download everything, ignoring the cache
python -m biwiki build             # regenerate out/ from the cache only (about 20 s)
python -m biwiki --dataset data build  # also refresh the parsed JSON in the data repository
python -m biwiki serve --port 8000 # serve out/ over HTTP
```

`--only commands` / `--only functions` limits the work to one category.
Cloudflare rejects real headless Chrome; if a checkbox appears, run without `--hidden` and click it.

## Output (`out/`)

| File | Purpose |
|---|---|
| `index.html` | **the site**: home page with search, groups, command and function pages |
| `index.md` | mirror home page in Markdown |
| `commands/index.md`, `functions/index.md` | lists grouped by command group |
| `commands/<name>.md`, `functions/<name>.md` | page with YAML front matter, description, syntaxes, parameters, examples and community notes; links between commands and functions point to local files |
| `commands/<name>.json`, `functions/<name>.json` | the same page as structured data |
| `commands/<name>.html`, `functions/<name>.html` | the same page as HTML |
| `commands.json`, `functions.json` | every record of one category in a single file |
| `index.json` | lightweight index for agents: name, syntaxes, summary, groups, locality, file paths |
| `assets/` | stylesheet, script and search index of the HTML version |
| `llms.txt`, `robots.txt`, `sitemap.xml` | discovery for language models, crawlers and search engines |
| `schema.json` | JSON Schema of a record, of `commands.json`/`functions.json` and of `index.json` |
| `report.json` | parser health report: crashes, skipped pages, unknown templates, leftover markup, untyped parameters |

File names: spaces become `_`, other unsafe characters become `~XX` (hex), e.g. `a != b` → `a_~21~3D_b.md`.
Functions are named as in scripts: `BIS_fnc_spawnGroup.md`. Exact paths are listed in `index.json`.

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

A static site with no build tooling and no JS dependencies: serve it with `python -m biwiki serve`
or open `out/index.html` directly from disk.

- search across every command and function (`/` to focus, arrow keys, Enter)
- SQF highlighting where every command and function in code links to its page
- Note / Important / Warning boxes, locality badges (filled = global, outlined = local), versions
- table of contents, Copy button on code blocks, light/dark theme following the system, mobile layout
- each page's header is a contour map generated from the command name

Fonts (Barlow, JetBrains Mono) load from Google Fonts; offline, system fonts are used.

## Code layout

- `biwiki/fetch.py`: browser session, MediaWiki API, incremental cache
- `biwiki/wikitext.py`: wikitext → Markdown (links, lists, tables, `<sqf>`, `{{Feature}}`, `{{GVI}}`, `{{hl}}`, …)
- `biwiki/parse.py`: `{{RV}}` template → record
- `biwiki/render.py`: writes the mirror files and indexes
- `biwiki/report.py`: parser health report, baseline comparison and the GitHub issue
- `biwiki/site.py`, `biwiki/assets/`: HTML version (markdown-it-py, SQF highlighting, page templates)

Content belongs to the authors of the BI Community Wiki; every generated page links to its source and revision.

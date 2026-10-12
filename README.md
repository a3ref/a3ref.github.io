# a3ref — Arma 3 scripting reference

A mirror of every page in
[Category:Arma 3: Scripting Commands](https://community.bistudio.com/wiki/Category:Arma_3:_Scripting_Commands) and
[Category:Arma 3: Functions](https://community.bistudio.com/wiki/Category:Arma_3:_Functions)
from the Bohemia Interactive Community Wiki, converted to **HTML** (for people), **Markdown** (for people and LLMs)
and **JSON** (for tools and AI agents).

Site: **https://a3ref.github.io/**

## How it works

The wiki sits behind a Cloudflare managed challenge, so plain HTTP clients get a 403.
`sync` starts the locally installed Google Chrome through [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright),
lets it pass the check, then calls the MediaWiki API (`/wikidata/api.php`) with `fetch()` from inside the page:
50 pages of wikitext per request, about 110 requests in total. Raw wikitext is cached in `data/raw/*.json`;
later runs only download pages whose `revid` changed.

`build` then parses each page's `{{RV}}` template with `mwparserfromhell` into structured fields
and writes the mirror to `out/`.

## Deployment

The repository holds only the code and the raw wikitext (`data/raw/*.json`, about 6 MB).
Everything in `out/` is generated during deployment and never committed.

The workflow in `.github/workflows/site.yml` runs:

- **daily at 04:17 UTC**: `sync` (real Chrome inside `xvfb`), commit the changed `data/raw`, build and deploy to GitHub Pages.
  If nothing changed on the wiki, the deploy is skipped.
- **on push to `main`**: build and deploy only (for example after parser or design changes).
- **manually** (Actions → Sync and deploy → Run workflow), with a `full` option to re-download everything.

If Cloudflare blocks the GitHub runner, sync locally instead
(`python -m biwiki sync`, then `git commit data/raw && git push`); the push triggers the deploy.

## Installation

Requires Python 3.10+ and Google Chrome.

```sh
pip install -r requirements.txt
```

## Usage

```sh
python -m biwiki update            # sync + build (opens a Chrome window for about a minute)
python -m biwiki update --hidden   # same, with the Chrome window moved off-screen
python -m biwiki sync --full       # re-download everything, ignoring the cache
python -m biwiki build             # regenerate out/ from the cache only (about 20 s)
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
| `llms.txt` | index in the [llms.txt](https://llmstxt.org/) format |
| `assets/` | stylesheet, script and search index of the HTML version |

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
- `biwiki/site.py`, `biwiki/assets/`: HTML version (markdown-it-py, SQF highlighting, page templates)

Content belongs to the authors of the BI Community Wiki; every generated page links to its source and revision.

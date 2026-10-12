"""Human-readable HTML version of the mirror (static, works from file:// too)."""
from __future__ import annotations

import html
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from markdown_it import MarkdownIt

ASSETS = Path(__file__).parent / "assets"

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:ital,wght@0,400;0,500;0,600;1,400'
    '&family=Barlow+Semi+Condensed:wght@500;600;700&family=JetBrains+Mono:wght@400;600&display=swap">'
)

LOCALITY_HELP = {
    ("argument", "local"): ("Local argument", "Arguments must be local to the machine running the command."),
    ("argument", "global"): ("Global argument", "Arguments can be local or remote."),
    ("effect", "local"): ("Local effect", "The effect is only visible on the machine running the command."),
    ("effect", "global"): ("Global effect", "The effect is broadcast to every machine."),
}

ALERT_TITLES = {"NOTE": "Note", "IMPORTANT": "Important", "WARNING": "Warning", "CAUTION": "Caution", "TIP": "Tip"}

# Sentinels for the few HTML tags our Markdown deliberately contains; everything else stays escaped.
_KEEP = {"<br>": "", "<kbd>": "", "</kbd>": ""}


class CodeLinker:
    """Syntax-highlights SQF and links every known command/function to its page."""

    TOKEN = re.compile(
        r"""
        (?P<comment>//[^\n]*|/\*.*?\*/)
        |(?P<string>"(?:[^"]|"")*"|'(?:[^']|'')*')
        |(?P<pp>^[ \t]*\#[a-z]+)
        |(?P<number>\$[0-9a-fA-F]+|0x[0-9a-fA-F]+|\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b|\.\d+)
        |(?P<local>\b_[A-Za-z0-9_]+)
        |(?P<word>\b[A-Za-z][A-Za-z0-9_]*)
        """,
        re.S | re.M | re.X,
    )

    def __init__(self, pages: dict[str, tuple[str, str]]):
        # lower-case script name -> (kind, slug); SQF is case-insensitive
        self.pages = pages
        self.root = "../"

    def __call__(self, code: str, lang: str, attrs) -> str:
        lang = (lang or "").lower()
        if lang in ("sqf", "sqs"):
            body = self.sqf(code)
        elif lang in ("cpp", "hpp", "ext", "c", "enforce"):
            body = self.config(code)
        else:
            body = html.escape(code)
        cls = f' class="language-{lang}"' if lang else ""
        return f'<pre class="code"><code{cls}>{body}</code></pre>\n'

    def sqf(self, code: str) -> str:
        out, pos = [], 0
        for m in self.TOKEN.finditer(code):
            out.append(html.escape(code[pos : m.start()]))
            kind, text = m.lastgroup, m.group(0)
            esc = html.escape(text)
            if kind == "word":
                hit = self.pages.get(text.lower())
                if hit:
                    css = "t-cmd" if hit[0] == "commands" else "t-fn"
                    out.append(f'<a class="{css}" href="{self.root}{hit[0]}/{hit[1]}.html">{esc}</a>')
                else:
                    out.append(esc)
            else:
                out.append(f'<span class="t-{kind}">{esc}</span>')
            pos = m.end()
        out.append(html.escape(code[pos:]))
        return "".join(out)

    def config(self, code: str) -> str:
        out, pos = [], 0
        for m in self.TOKEN.finditer(code):
            out.append(html.escape(code[pos : m.start()]))
            kind, esc = m.lastgroup, html.escape(m.group(0))
            out.append(esc if kind in ("word", "local") else f'<span class="t-{kind}">{esc}</span>')
            pos = m.end()
        out.append(html.escape(code[pos:]))
        return "".join(out)


class Site:
    def __init__(self, out_dir: Path, pages: dict[str, tuple[str, str]], kind_labels: dict[str, str]):
        self.out = out_dir
        self.linker = CodeLinker(pages)
        self.kind_labels = kind_labels
        self.md = MarkdownIt("commonmark", {"html": False, "highlight": self.linker}).enable(["table", "strikethrough"])

    # ---- markdown -> html -------------------------------------------------------------------

    def html(self, md: str) -> str:
        for tag, mark in _KEEP.items():
            md = md.replace(tag, mark)
        out = self.md.render(md)
        for tag, mark in _KEEP.items():
            out = out.replace(mark, tag)
        out = re.sub(
            r"<blockquote>\s*<p>\[!(\w+)\]\s*",
            lambda m: f'<blockquote class="alert alert-{m.group(1).lower()}">'
            f'<p class="alert-title">{ALERT_TITLES.get(m.group(1), m.group(1).title())}</p><p>',
            out,
        )
        out = out.replace("<p></p>", "")
        out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        return out

    @staticmethod
    def _ids(body: str) -> tuple[str, list[tuple[int, str, str]]]:
        toc, seen = [], set()

        def sub(m):
            level, inner = int(m.group(1)), m.group(2)
            text = re.sub(r"<[^>]+>", "", inner)
            base = re.sub(r"[^\w]+", "-", html.unescape(text).lower()).strip("-") or "section"
            ident, n = base, 2
            while ident in seen:
                ident, n = f"{base}-{n}", n + 1
            seen.add(ident)
            toc.append((level, ident, text))
            return f'<h{level} id="{ident}">{inner}</h{level}>'

        return re.sub(r"<h([23])>(.*?)</h\1>", sub, body), toc

    # ---- page shell ---------------------------------------------------------------------------

    def shell(self, *, root: str, title: str, description: str, masthead: str, main: str, toc: str = "",
              alternates: str = "", footer: str = "", page_class: str = "") -> str:
        layout = "layout" + ("" if toc else " layout-wide")
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
{alternates}{FONTS}
<link rel="stylesheet" href="{root}assets/style.css">
</head>
<body data-root="{root}" class="{page_class}">
<a class="skip" href="#content">Skip to content</a>
<header class="topbar">
  <a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>Arma 3 Scripting</a>
  <nav class="topnav" aria-label="Sections">
    <a href="{root}commands/index.html">Commands</a>
    <a href="{root}functions/index.html">Functions</a>
  </nav>
  <div class="search" role="search">
    <input type="search" placeholder="Search commands and functions" aria-label="Search commands and functions" autocomplete="off" spellcheck="false">
    <kbd class="search-key" aria-hidden="true">/</kbd>
    <ul class="results" role="listbox" hidden></ul>
  </div>
</header>
<div class="masthead"><div class="terrain" aria-hidden="true"></div><div class="masthead-inner">{masthead}</div></div>
<div class="{layout}">
{f'<nav class="toc" aria-label="On this page"><p class="toc-title">On this page</p>{toc}</nav>' if toc else ''}
<main id="content" class="content">
{main}
</main>
</div>
<footer class="footer"><div class="footer-inner">{footer}</div></footer>
<script src="{root}assets/site.js" defer></script>
</body>
</html>
"""

    # ---- pages --------------------------------------------------------------------------------

    def page(self, kind: str, s: str, rec: dict, body_md: str, summary: str) -> None:
        body, heads = self._ids(self.html(body_md))
        notes = ""
        if rec["notes"]:
            items = []
            for n in rec["notes"]:
                when = f'<time datetime="{n["date"]}">{n["date"][:10]}</time>' if n["date"] else ""
                items.append(
                    f'<article class="note"><header><strong>{html.escape(n["user"] or "Anonymous")}</strong>{when}</header>'
                    f'{self.html(n["text"])}</article>'
                )
            notes = '<section class="notes"><h2 id="community-notes">Community notes</h2>' + "".join(items) + "</section>"
            heads.append((2, "community-notes", "Community notes"))

        toc = "<ol>" + "".join(
            f'<li class="toc-{lvl}"><a href="#{i}">{t}</a></li>' for lvl, i, t in heads if lvl == 2 or t.startswith("Syntax")
        ) + "</ol>"

        label = "Command" if rec["type"] == "command" else "Function"
        groups = ", ".join(
            f'<a href="index.html#{_anchor(g)}">{html.escape(g)}</a>' for g in rec["groups"]
        )
        facts = []
        loc = rec["locality"]
        for axis in ("argument", "effect"):
            if loc[axis]:
                text, help_ = LOCALITY_HELP[(axis, loc[axis])]
                facts.append(f'<li class="fact fact-{loc[axis]}" title="{help_}">{text}</li>')
        if loc["server_exec"]:
            facts.append('<li class="fact fact-server" title="Must be executed on the server.">Server only</li>')
        if rec["exec"]:
            facts.append(f'<li class="fact" title="How this function is executed.">Runs with {html.escape(rec["exec"])}</li>')
        if rec["branch"]:
            facts.append(f'<li class="fact fact-branch" title="Only available in this game branch.">{html.escape(rec["branch"])} branch</li>')
        if rec["arma3_since"]:
            facts.append(f'<li class="fact fact-version">Arma 3 v{html.escape(rec["arma3_since"])}</li>')
        if rec["since"] and rec["since"]["game"] != "arma3":
            facts.append(
                f'<li class="fact fact-muted">First in {html.escape(rec["since"]["name"])}'
                f'{" v" + html.escape(rec["since"]["version"]) if rec["since"]["version"] else ""}</li>'
            )
        if rec["aliases"]:
            facts.append('<li class="fact fact-muted">Alias of ' + ", ".join(html.escape(a) for a in rec["aliases"]) + "</li>")

        name_cls = "name name-long" if len(rec["name"]) > 26 else "name"
        masthead = f"""<p class="kind"><a href="index.html">{label}</a>{' in ' + groups if groups else ''}</p>
<h1 class="{name_cls}">{html.escape(rec['name'])}</h1>
<ul class="facts">{''.join(facts)}</ul>
<p class="formats">Also available as <a href="{s}.md">Markdown</a> and <a href="{s}.json">JSON</a>, or read the <a href="{rec['url']}">original wiki page</a>.</p>"""

        updated = (rec["updated"] or "")[:10]
        footer = (f'Content from the <a href="{rec["url"]}">Bohemia Interactive Community Wiki</a>, '
                  f'revision {rec["revid"]}{", edited " + updated if updated else ""}.')
        alternates = (f'<link rel="alternate" type="text/markdown" href="{s}.md">'
                      f'<link rel="alternate" type="application/json" href="{s}.json">\n')
        doc = self.shell(root="../", title=f"{rec['name']} – Arma 3 {label.lower()}", description=summary,
                         masthead=masthead, main=body + notes, toc=toc, alternates=alternates, footer=footer,
                         page_class=f"page-{rec['type']}")
        (self.out / kind / f"{s}.html").write_text(doc, encoding="utf-8")

    def kind_index(self, kind: str, records: list[dict], slugs: dict[str, str], summaries: dict[str, str]) -> None:
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            for g in r["groups"] or ["Uncategorised"]:
                groups[g].append(r)
        label = self.kind_labels[kind]
        jump = "".join(
            f'<li><a href="#{_anchor(g)}">{html.escape(g)}</a> <span class="count">{len(groups[g])}</span></li>'
            for g in sorted(groups, key=str.lower)
        )
        sections = []
        for g in sorted(groups, key=str.lower):
            rows = "".join(
                f'<li><a class="entry-name" href="{slugs[r["title"]]}.html">{html.escape(r["name"])}</a>'
                f'<span class="entry-summary">{html.escape(_short(summaries[r["title"]], 150))}</span></li>'
                for r in sorted(groups[g], key=lambda r: r["name"].lower())
            )
            sections.append(f'<section class="group"><h2 id="{_anchor(g)}">{html.escape(g)}</h2><ul class="entries">{rows}</ul></section>')
        masthead = f"""<p class="kind"><a href="../index.html">Arma 3 scripting reference</a></p>
<h1 class="name">{html.escape(label)}</h1>
<p class="lede">{len(records)} {label.lower()} in {len(groups)} groups. A page can belong to several groups.</p>"""
        main = f'<nav class="group-jump" aria-label="Groups"><ul>{jump}</ul></nav>' + "".join(sections)
        doc = self.shell(root="../", title=f"Arma 3 {label.lower()}", description=f"All Arma 3 {label.lower()} by group.",
                         masthead=masthead, main=main, footer=_site_footer(), page_class="page-index")
        (self.out / kind / "index.html").write_text(doc, encoding="utf-8")

    def home(self, kinds: list[str], all_records: dict[str, list[dict]], slugs: dict[str, str], generated: str) -> None:
        counts = {k: len(v) for k, v in all_records.items()}
        parts = [f"{counts[k]} {self.kind_labels[k].lower()}" for k in kinds]
        masthead = f"""<h1 class="name home-title">Arma 3 scripting reference</h1>
<p class="lede">{' and '.join(parts)} from the Bohemia Interactive Community Wiki, readable offline and available as Markdown and JSON.</p>
<div class="search search-hero" role="search">
  <input type="search" placeholder="Find a command or function, e.g. createVehicle" aria-label="Find a command or function" autocomplete="off" spellcheck="false">
  <ul class="results" role="listbox" hidden></ul>
</div>"""
        columns = []
        for k in kinds:
            groups: dict[str, int] = defaultdict(int)
            for r in all_records[k]:
                for g in r["groups"] or ["Uncategorised"]:
                    groups[g] += 1
            items = "".join(
                f'<li><a href="{k}/index.html#{_anchor(g)}">{html.escape(g)}</a> <span class="count">{n}</span></li>'
                for g, n in sorted(groups.items(), key=lambda x: x[0].lower())
            )
            columns.append(f'<section class="home-col"><h2><a href="{k}/index.html">{html.escape(self.kind_labels[k])}</a></h2><ul class="group-list">{items}</ul></section>')

        recent = sorted((r for k in kinds for r in all_records[k] if r["updated"]), key=lambda r: r["updated"], reverse=True)[:12]
        recent_items = "".join(
            f'<li><a href="{"commands" if r["type"] == "command" else "functions"}/{slugs[r["title"]]}.html">{html.escape(r["name"])}</a>'
            f'<time datetime="{r["updated"]}">{r["updated"][:10]}</time></li>'
            for r in recent
        )
        data_items = "".join(
            f'<li><a href="{href}">{name}</a> {desc}</li>'
            for href, name, desc in [
                ("index.json", "index.json", "lists every entry with its syntax, summary, groups and file paths."),
                *[(f"{k}.json", f"{k}.json", f"holds every {k[:-1]} with full details.") for k in kinds],
                ("llms.txt", "llms.txt", "is an index for language models."),
            ]
        )
        main = f"""<div class="home-grid">{''.join(columns)}
<aside class="home-side">
<section><h2>Recently edited on the wiki</h2><ul class="recent">{recent_items}</ul></section>
<section><h2>For tools and AI agents</h2><p>Every page also exists as <code>.md</code> and <code>.json</code> next to its <code>.html</code>.</p><ul class="data-list">{data_items}</ul></section>
</aside></div>"""
        doc = self.shell(root="", title="Arma 3 scripting reference", description="Arma 3 scripting commands and functions.",
                         masthead=masthead, main=main, footer=_site_footer(generated), page_class="page-home")
        (self.out / "index.html").write_text(doc, encoding="utf-8")

    def assets(self, search_entries: list[list]) -> None:
        target = self.out / "assets"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(ASSETS, target)
        # A script, not JSON, so search also works when the site is opened from disk (file://).
        (target / "search-index.js").write_text(
            "window.BIWIKI_INDEX=" + json.dumps(search_entries, ensure_ascii=False, separators=(",", ":")) + ";",
            encoding="utf-8",
        )


def _anchor(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _site_footer(generated: str = "") -> str:
    when = f" Generated {generated[:10]}." if generated else ""
    return ('Content from the <a href="https://community.bistudio.com/wiki">Bohemia Interactive Community Wiki</a>.'
            f"{when}")

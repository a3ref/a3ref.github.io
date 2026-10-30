"""Human-readable HTML version of the mirror.

Static pages that work from file:// too and are built to pass Lighthouse (performance, accessibility, best
practices, SEO), axe, html-validate and the W3C checkers: self-hosted font, no inline scripts (strict CSP),
canonical URLs, Open Graph, breadcrumbs with structured data, headings without skipped levels.

Documentation layout: the other pages of the current group on the left, the content, the table of contents
on the right.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from markdown_it import MarkdownIt

ASSETS = Path(__file__).parent / "assets"
SITE_NAME = "a3ref"
SITE_TITLE = "Arma 3 scripting reference"

# Delivered as <meta>, so frame-ancestors and report-uri are not available; everything is same-origin.
# The site's origin is listed next to 'self' so the policy also reads right for a validator given the file alone.
CSP = ("default-src 'self' {origin}; script-src 'self' {origin} {hashes}; style-src 'self' {origin}; "
       "img-src 'self' {origin} data:; font-src 'self' {origin}; connect-src 'self' {origin}; "
       "manifest-src 'self' {origin}; object-src 'none'; base-uri 'self'; form-action 'none'")

PRELOAD = ["jetbrains-mono-latin-600-normal", "jetbrains-mono-latin-400-normal"]  # text uses the system font
THEME_COLOR = ("#ffffff", "#16181d")  # light, dark
GOOGLE_SITE_VERIFICATION = "HHNWP8LwEWplPR4MXkhdQW79itoiuehWhhxliCgXj5Y"  # Search Console ownership; checked on the home page only

LOCALITY_HELP = {
    ("argument", "local"): ("Local argument", "Arguments must be local to the machine running the command."),
    ("argument", "global"): ("Global argument", "Arguments can be local or remote."),
    ("effect", "local"): ("Local effect", "The effect is only visible on the machine running the command."),
    ("effect", "global"): ("Global effect", "The effect is broadcast to every machine."),
}

ALERT_TITLES = {"NOTE": "Note", "IMPORTANT": "Important", "WARNING": "Warning", "CAUTION": "Caution", "TIP": "Tip"}
KIND_OF_TYPE = {"command": "commands", "function": "functions", "topic": "topics"}
SIDE_LIMIT = 60  # entries of the current group listed in the side navigation
CURRENT = ' aria-current="page"'

# Sentinels for the few HTML tags our Markdown deliberately contains; everything else stays escaped.
_KEEP = {"<br>": "", "<kbd>": "", "</kbd>": ""}


# An anchor of the wiki ({{Anchor}}'s <span id>, a heading's own id) in the site's Markdown: ANCHOR[0] id ANCHOR[1],
# the id already as heading_id makes it (wikitext.anchor_mark); _place_anchors turns it into an element with that id
ANCHOR = ("", "")
_ANCHOR = re.compile(f"{ANCHOR[0]}([^{ANCHOR[1]}]*){ANCHOR[1]}")

# a code block inside a table cell: ```lang<br>code<br>``` (see Site.html)
_CELL_CODE = re.compile(r"(`{3,})([A-Za-z+-]*)<br>(.*?)(?:<br>)?\1(?!`)")
_NESTED_SEPARATOR = re.compile(r"^\s*\\\|(?:\s*:?-{3,}:?\s*\\\|)+\s*$")


def _fit_title(title: str, limit: int = 70) -> str:
    """Page titles longer than search results show (and html-validate allows): the " – Arma 3 ..." suffix goes
    first, then the name is cut."""
    if len(title) <= limit:
        return title
    name = title.rsplit(" – ", 1)[0]
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def _nested_tables(line: str, render) -> str:
    """A table or a note (blockquote) inside a table cell: Markdown has neither, so the converter writes their lines
    into the cell, separated by <br>, with escaped pipes. ``render`` gets the lines of each one and returns what
    replaces them."""
    cells = re.split(r"(?<!\\)\|", line)
    for k, cell in enumerate(cells):
        if "\\|" not in cell and ">" not in cell:
            continue
        parts, out, i = cell.split("<br>"), [], 0
        while i < len(parts):
            run = 0
            while i + run < len(parts) and parts[i + run].lstrip().startswith(">"):
                run += 1
                if i + run < len(parts) and parts[i + run].lstrip().startswith("> [!"):
                    break  # the next note
            # a note: lines that all start with ">", from "> [!NOTE]" or of more than one line ("> 0 s" is text)
            if run > 1 or (run and parts[i].lstrip().startswith("> [!")):
                out.append(render(parts[i : i + run]))
                i += run
            elif parts[i].strip().startswith("\\|") and i + 1 < len(parts) and _NESTED_SEPARATOR.match(parts[i + 1]):
                rows, i = parts[i : i + 2], i + 2
                while i < len(parts):
                    if parts[i].strip().startswith("\\|"):
                        rows.append(parts[i])
                    elif not rows[-1].rstrip().endswith("\\|"):  # a line break inside a cell of the inner table
                        rows[-1] += "<br>" + parts[i]
                    else:
                        break
                    i += 1
                out.append(render(rows))
            else:
                out.append(parts[i])
                i += 1
        cells[k] = "<br>".join(out)
    return "|".join(cells)


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
        # links the wiki shows inside preformatted lines (see wikitext.CODE_LINK); text and URL are escaped above
        body = re.sub("(.*?)(.*?)", r'<a href="\2">\1</a>', body)
        cls = f' class="language-{lang}"' if lang else ""
        # tabindex: long lines scroll sideways, and keyboard users need to be able to focus the block to scroll it
        return f'<pre class="code" tabindex="0"><code{cls}>{body}</code></pre>\n'

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
    def __init__(self, out_dir: Path, pages: dict[str, tuple[str, str]], kind_labels: dict[str, str],
                 base_url: str = "https://a3ref.github.io/"):
        self.out = out_dir
        self.linker = CodeLinker(pages)
        self.kind_labels = kind_labels
        self.base = base_url
        self.md = MarkdownIt("commonmark", {"html": False, "highlight": self.linker}).enable(["table", "strikethrough"])
        # Only web links: wiki text such as "<timezoneName:string>" would otherwise become a link with that "scheme".
        self.md.validateLink = lambda url: bool(re.match(r"^(https?:|mailto:|[^:]*$)", url.strip(), re.I))

    # ---- markdown -> html -------------------------------------------------------------------

    def html(self, md: str) -> str:
        # A Markdown table cell holds no code block, so the converter writes one as ```lang<br>...<br>``` on the
        # cell's line; markdown-it would make it inline code with "lang" as text. Render those blocks here.
        blocks: list[str] = []

        def cell_code(m: re.Match) -> str:
            code = m.group(3).replace("<br>", "\n").replace("\\|", "|")
            blocks.append(self.linker(code, m.group(2), None).strip())
            return f"{len(blocks) - 1}"

        def cell_table(rows: list[str]) -> str:
            inner = self.html("\n".join(r.strip().replace("\\|", "|") for r in rows)).strip()
            # without its scroll wrapper: the outer pass below wraps every <table>, this one included
            blocks.append(inner.replace('<div class="table-wrap"><table>', "<table>").replace("</table></div>", "</table>"))
            return "%d" % (len(blocks) - 1)

        def table_line(line: str) -> str:
            # tables nested in a cell come first: their own cells may hold code blocks, rendered by the inner call
            return _CELL_CODE.sub(cell_code, _nested_tables(line, cell_table))

        md = re.sub(r"(?m)^[ \t>]*\|.*$", lambda line: table_line(line.group(0)), md)
        # A <br> stands for a Unicode space while Markdown is rendered (U+205F, not used by the wiki), so that
        # emphasis next to it pairs as next to a space: "**???**<br>" in a table cell is bold, not a stray "**".
        md = md.replace("<br>", " ")
        for tag, mark in _KEEP.items():
            md = md.replace(tag, mark)
        out = self.md.render(md).replace(" ", "<br>")
        for tag, mark in _KEEP.items():
            out = out.replace(mark, tag)
        out = re.sub("(\\d+)", lambda m: blocks[int(m.group(1))], out)
        out = re.sub(
            r"<blockquote>\s*<p>\[!(\w+)\]\s*",
            lambda m: f'<blockquote class="alert alert-{m.group(1).lower()}">'
            f'<p class="alert-title">{ALERT_TITLES.get(m.group(1), m.group(1).title())}</p><p>',
            out,
        )
        out = out.replace("<p></p>", "")
        out = re.sub(r"<(hr|br)\s*/>", r"<\1>", out)  # HTML5 void elements, not XHTML
        # wiki tables without a header row get an empty one in Markdown; empty <th> cells confuse screen readers
        out = re.sub(r"<thead>\s*<tr>(?:\s*<th[^>]*>\s*</th>)+\s*</tr>\s*</thead>\s*", "", out)
        out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        # Markdown table headers are column headers; say so, as tables nested in a cell need it (WCAG H63)
        out = re.sub(r"<th(?=[\s>])(?![^>]*\bscope=)", '<th scope="col"', out)
        return out

    @staticmethod
    def _ids(body: str) -> tuple[str, list[tuple[int, str, str]]]:
        """Give headings ids, and never skip a level (h2 followed by h4 becomes h2, h3) for accessibility."""
        toc, seen = [], set()
        last = 1  # the page's h1 is in the header

        def sub(m):
            nonlocal last
            level, inner = min(int(m.group(1)), last + 1), m.group(2)
            last = level
            text = _ANCHOR.sub("", re.sub(r"<[^>]+>", "", inner))
            base = heading_id(html.unescape(text)) or "section"
            ident, n = base, 2
            while ident in seen:
                ident, n = f"{base}-{n}", n + 1
            seen.add(ident)
            toc.append((level, ident, text))
            return f'<h{level} id="{ident}">{inner}</h{level}>'

        return re.sub(r"<h([2-6])>(.*?)</h\1>", sub, body), toc

    # ---- page shell ---------------------------------------------------------------------------

    def _search(self, ident: str, placeholder: str, hero: bool = False) -> str:
        name = "Search the reference" if hero else "Site search"  # two search landmarks need distinct names
        return f"""<div class="search{' search-hero' if hero else ''}" role="search" aria-label="{name}">
  <label class="vh" for="{ident}">Search commands, functions and topics</label>
  <input id="{ident}" type="search" placeholder="{placeholder}" autocomplete="off" spellcheck="false" aria-describedby="{ident}-hint" aria-controls="{ident}-results">{'' if hero else '''
  <kbd class="search-key" aria-hidden="true">/</kbd>'''}
  <p id="{ident}-hint" class="vh">Results appear below as you type; use the arrow keys to move through them.</p>
  <ul id="{ident}-results" class="results" hidden></ul>
  <p id="{ident}-status" class="vh" aria-live="polite"></p>
</div>"""

    def _head(self, root: str, path: str, title: str, description: str, og_type: str, jsonld: list, extra: str) -> str:
        url = self.base + (path if path != "index.html" else "")
        light, dark = THEME_COLOR
        preload = "".join(
            f'<link rel="preload" href="{root}assets/fonts/{f}.woff2" as="font" type="font/woff2" crossorigin>'
            for f in PRELOAD
        )
        blocks = [json.dumps(x, ensure_ascii=False).replace("</", "<\\/") for x in jsonld]
        ld = "".join(f'<script type="application/ld+json">{b}</script>\n' for b in blocks)
        # JSON-LD blocks are data, not scripts, but validators check them against script-src; list their hashes.
        hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(b.encode()).digest()).decode()}'" for b in blocks)
        csp = CSP.format(origin=self.base.rstrip("/"), hashes=hashes)
        desc = html.escape(description)
        return f"""<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{html.escape(title)}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="{light}" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="{dark}" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{root}favicon.ico" sizes="32x32">
<link rel="icon" href="{root}assets/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="{root}assets/icon-180.png">
<link rel="manifest" href="{root}site.webmanifest">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{self.base}assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="a3ref, the Arma 3 scripting reference">
<meta name="twitter:card" content="summary_large_image">
{preload}
<link rel="stylesheet" href="{root}assets/style.css">
{extra}{ld}</head>"""

    def shell(self, *, path: str, title: str, description: str, header: str, main: str, crumbs: list,
              toc: str = "", side: str = "", jsonld: list | None = None, extra_head: str = "", footer: str = "",
              page_class: str = "", og_type: str = "article", root: str | None = None) -> str:
        root = root if root is not None else "../" * path.count("/")
        title = _fit_title(title)
        jsonld = list(jsonld or [])
        if len(crumbs) > 1:
            jsonld.append(_breadcrumb_ld(self.base, crumbs))
        crumb_html = _crumbs(root, crumbs)
        toc_html = (f'<nav class="toc" aria-labelledby="toc-title"><h2 class="toc-title" id="toc-title">'
                    f'{_fold("toc-list", "On this page")}</h2><ol id="toc-list">{toc}</ol></nav>') if toc else ""
        topbar = f"""<header class="topbar">
  <a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>Arma 3 Scripting</a>
  <nav class="topnav" aria-label="Sections">
    <a href="{root}commands/index.html">Commands</a>
    <a href="{root}functions/index.html">Functions</a>
    <a href="{root}topics/index.html">Topics</a>
  </nav>
  {self._search("q-top", "Search")}
</header>"""
        foot = f"""<footer class="footer"><div class="footer-inner">
<p>{footer or _site_footer()}</p>
<nav aria-label="Project"><ul class="footer-links">
<li><a href="{root}llms.txt">For AI agents</a></li>
<li><a href="https://github.com/a3ref/mcp">MCP server</a></li>
<li><a href="https://github.com/a3ref/data">Data</a></li>
<li><a href="{root}feed.xml">Changes feed</a></li>
<li><a href="https://github.com/a3ref/a3ref.github.io">Source</a></li>
</ul></nav>
</div></footer>"""
        # One side column holds both navigations, contents first, as folding sections; without either the
        # content column stands alone. On narrow screens the column becomes folded blocks above the page.
        side_html = f'<nav class="sidenav" aria-labelledby="side-title">{side}</nav>' if side else ""
        column = f'<div class="side">\n{toc_html}\n{side_html}\n</div>\n'.replace("\n\n", "\n") if toc or side else ""
        body = f"""{topbar}
<div class="frame{' frame-one' if column else ''}">
{column}<main id="content" class="content">
<div class="page-head">{crumb_html}{header}</div>
{main}
</main>
</div>"""
        doc = f"""<!DOCTYPE html>
<html lang="en">
{self._head(root, path, title, description, og_type, jsonld, extra_head)}
<body data-root="{root}" class="{page_class}">
<a class="skip" href="#content">Skip to content</a>
{body}
{foot}
<script src="{root}assets/site.js" defer></script>
</body>
</html>
"""
        # code copied from the wiki keeps trailing spaces; they are invisible, and validators flag them
        return re.sub(r"[ \t]+\n", "\n", _place_anchors(doc))

    # ---- pages --------------------------------------------------------------------------------

    def page(self, kind: str, s: str, rec: dict, body_md: str, summary: str, status_note: str = "",
             siblings: list | None = None) -> str:
        body, heads = self._ids(self.html((status_note + "\n\n" if status_note else "") + body_md))
        notes = ""
        if rec["notes"]:
            items = []
            for n in rec["notes"]:
                when = f'<time datetime="{n["date"]}">{n["date"][:10]}</time>' if n["date"] else ""
                items.append(
                    f'<article class="note"><header><h3 class="note-author">{html.escape(n["user"] or "Anonymous")}</h3>{when}</header>'
                    f'{self.html(n["text"])}</article>'
                )
            notes = '<section class="notes"><h2 id="community-notes">Community notes</h2>' + "".join(items) + "</section>"
            heads.append((2, "community-notes", "Community notes"))

        toc = "".join(
            f'<li class="toc-{lvl}"><a href="#{i}">{t}</a></li>' for lvl, i, t in heads if lvl == 2 or t.startswith("Syntax")
        )

        label = "Command" if rec["type"] == "command" else "Function"
        facts = []
        if rec["status"] != "ok":
            facts.append(f'<li class="fact fact-status">{rec["status"].capitalize()}</li>')
        loc = rec["locality"]
        for axis in ("argument", "effect"):
            if loc[axis]:
                text, help_ = LOCALITY_HELP[(axis, loc[axis])]
                facts.append(f'<li class="fact fact-{loc[axis]}" title="{help_}">{text}</li>')
        if loc["server_exec"]:
            facts.append('<li class="fact fact-server" title="Must be executed on the server.">Server only</li>')
        if rec["exec"]:
            facts.append(f'<li class="fact">Runs with {html.escape(rec["exec"])}</li>')
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

        group = rec["groups"][0] if rec["groups"] else None
        others = ", ".join(f'<a href="../{group_path(kind, g)}">{html.escape(g)}</a>' for g in rec["groups"][1:])
        name_cls = "name name-long" if len(rec["name"]) > 26 else "name"
        header = f"""<h1 class="{name_cls}">{html.escape(rec['name'])}</h1>
{('<ul class="facts">' + ''.join(facts) + '</ul>') if facts else ''}
<p class="formats">{label}{' · also in ' + others if others else ''} · <a href="{s}.md">Markdown</a> · <a href="{s}.json">JSON</a> · <a href="{rec['url']}">original wiki page</a></p>"""

        crumbs = [("Home", "index.html"), (self.kind_labels[KIND_OF_TYPE[rec["type"]]], f"{kind}/index.html")]
        if group:
            crumbs.append((group, group_path(kind, group)))
        crumbs.append((rec["name"], f"{kind}/{s}.html"))
        updated = (rec["updated"] or "")[:10]
        footer = (f'Content from the <a href="{rec["url"]}">Bohemia Interactive Community Wiki</a>, '
                  f'revision {rec["revid"]}{", edited " + updated if updated else ""}.')
        return self.shell(path=f"{kind}/{s}.html", title=f"{rec['name']} – Arma 3 {label.lower()}",
                          description=_description(summary, rec["name"], label.lower()), header=header, main=body + notes,
                          crumbs=crumbs, toc=toc, side=self._side(kind, group, siblings, rec["name"]),
                          jsonld=[_article_ld(self.base, f"{kind}/{s}", rec, summary)], extra_head=_alternates(s),
                          footer=footer, page_class=f"page-{rec['type']}")

    def topic(self, s: str, rec: dict, summary: str, siblings: list | None = None) -> str:
        body, heads = self._ids(self.html(rec["markdown"]))
        toc = "".join(f'<li class="toc-{lvl}"><a href="#{i}">{t}</a></li>' for lvl, i, t in heads if lvl <= 3)
        facts = ""
        if rec["aliases"]:
            facts = ('<ul class="facts"><li class="fact fact-muted">Also known as '
                     + ", ".join(html.escape(a) for a in rec["aliases"][:8]) + "</li></ul>")
        group = rec["groups"][0]
        header = f"""<h1 class="name{' name-long' if len(rec['name']) > 26 else ''}">{html.escape(rec['name'])}</h1>
{facts}
<p class="formats">Topic · <a href="{s}.md">Markdown</a> · <a href="{s}.json">JSON</a> · <a href="{rec['url']}">original wiki page</a></p>"""
        crumbs = [("Home", "index.html"), ("Topics", "topics/index.html"),
                  (group, f"topics/index.html#{_anchor(group)}"), (rec["name"], f"topics/{s}.html")]
        updated = (rec["updated"] or "")[:10]
        footer = (f'Content from the <a href="{rec["url"]}">Bohemia Interactive Community Wiki</a>, '
                  f'revision {rec["revid"]}{", edited " + updated if updated else ""}.')
        return self.shell(path=f"topics/{s}.html", title=f"{rec['name']} – Arma 3 scripting",
                          description=_description(summary, rec["name"], "topic"), header=header, main=body, crumbs=crumbs,
                          toc=toc if len(heads) > 1 else "", side=self._side("topics", group, siblings, rec["name"]),
                          jsonld=[_article_ld(self.base, f"topics/{s}", rec, summary)], extra_head=_alternates(s),
                          footer=footer, page_class="page-topic")

    def _side(self, kind: str, group: str | None, siblings: list | None, current: str) -> str:
        """The other pages of the current group, around the current one."""
        if not group or not siblings:
            return ""
        names = [n for n, _ in siblings]
        at = names.index(current) if current in names else 0
        start = max(0, min(at - SIDE_LIMIT // 2, len(siblings) - SIDE_LIMIT))
        shown = siblings[start : start + SIDE_LIMIT]
        items = "".join(
            f'<li><a href="{href}"{CURRENT if n == current else ""}>{html.escape(n)}</a></li>'
            for n, href in shown
        )
        href = f"index.html#{_anchor(group)}" if kind == "topics" else f"../{group_path(kind, group)}"
        # the heading is the section's disclosure button, so the group page is linked below the list
        return (f'<h2 class="side-title" id="side-title">{_fold("side-body", html.escape(group))}</h2>'
                f'<div class="side-body" id="side-body"><ul class="side-list">{items}</ul>'
                f'<p class="side-more"><a href="{href}">All {len(siblings)} in {html.escape(group)}</a></p></div>')

    def not_found(self, base_url: str) -> None:
        """GitHub Pages serves 404.html for any missing path. People are redirected to the page they most likely
        meant (case-insensitive match, assets/404.js); agents, which do not run scripts, get instructions."""
        main = f"""<p>There is no page at this address. Names are case-sensitive and follow the wiki spelling;
lower-case paths such as <code>commands/setpos.md</code> also work.</p>
<p>To find the right path, use <a href="{base_url}names.txt">names.txt</a> (every name) or
<a href="{base_url}index.json">index.json</a> (names with summaries and paths), or read
<a href="{base_url}llms.txt">llms.txt</a>.</p>"""
        header = '<h1 class="name">Page not found</h1>'
        doc = self.shell(path="404.html", root="/", title="Page not found – Arma 3 scripting reference",
                         description="There is no page at this address of the Arma 3 scripting reference.",
                         header=header, main=main, crumbs=[("Home", "index.html")], page_class="page-index",
                         extra_head='<meta name="robots" content="noindex">\n<script src="/assets/404.js" defer></script>\n',
                         og_type="website")
        (self.out / "404.html").write_text(doc, encoding="utf-8")

    def kind_index(self, kind: str, records: list[dict], slugs: dict[str, str], summaries: dict[str, str]) -> None:
        """Commands and functions: an overview of their groups plus one page per group (groups/<kind>/<group>.html,
        next to the Markdown list for agents). Topics are few enough for a single page."""
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            for g in r["groups"] or ["Uncategorised"]:
                groups[g].append(r)
        label = self.kind_labels[kind]
        ordered = sorted(groups, key=str.lower)

        def rows(members: list[dict], prefix: str) -> str:
            return "".join(
                f'<li><a class="entry-name" href="{prefix}{slugs[r["title"]]}.html">{html.escape(r["name"])}</a>'
                f'<span class="entry-summary">{html.escape(_short(summaries[r["title"]], 150))}</span></li>'
                for r in sorted(members, key=lambda r: r["name"].lower())
            )

        if kind == "topics":
            jump = "".join(f'<li><a href="#{_anchor(g)}">{html.escape(g)}</a> <span class="count">{len(groups[g])}</span></li>'
                           for g in ordered)
            main = f'<nav class="group-jump" aria-label="Groups"><ul>{jump}</ul></nav>' + "".join(
                f'<section class="group"><h2 id="{_anchor(g)}">{html.escape(g)}</h2><ul class="entries">{rows(groups[g], "")}</ul></section>'
                for g in ordered)
            lede = (f"{len(records)} pages: data types, locality and multiplayer, event handlers, mission editing, "
                    "configs, GUI, tools and more.")
        else:
            cards = "".join(
                f'<li class="group-card"><h2><a href="../{group_path(kind, g)}">{html.escape(g)}</a></h2>'
                f'<p class="count">{len(groups[g])} {label.lower() if len(groups[g]) != 1 else label.lower().rstrip("s")}</p>'
                f'<p class="group-sample">{", ".join(html.escape(r["name"]) for r in sorted(groups[g], key=lambda r: r["name"].lower())[:4])}'
                f'{", …" if len(groups[g]) > 4 else ""}</p></li>'
                for g in ordered)
            main = f'<ul class="group-cards">{cards}</ul>'
            lede = f"{len(records)} {label.lower()} in {len(groups)} groups. A page can belong to several groups."
            for g in ordered:
                path = group_path(kind, g)
                header = f"""<h1 class="name">{html.escape(g)}</h1>
<p class="lede">{len(groups[g])} {label.lower()}. Also as <a href="{_slug(g)}.md">Markdown</a> for agents.</p>"""
                doc = self.shell(path=path, title=f"{g} – Arma 3 {label.lower()}",
                                 description=_description(f"Arma 3 {label.lower()} in the group {g}: "
                                                          + ", ".join(r["name"] for r in groups[g][:8]) + ".", g, "group"),
                                 header=header, main=f'<ul class="entries">{rows(groups[g], f"../../{kind}/")}</ul>',
                                 crumbs=[("Home", "index.html"), (label, f"{kind}/index.html"), (g, path)],
                                 page_class="page-index", og_type="website")
                (self.out / path).parent.mkdir(parents=True, exist_ok=True)
                (self.out / path).write_text(doc, encoding="utf-8")
        header = f"""<h1 class="name">{html.escape(label)}</h1>
<p class="lede">{lede}</p>"""
        doc = self.shell(path=f"{kind}/index.html", title=f"Arma 3 {label.lower()} by group",
                         description=f"All {len(records)} Arma 3 {label.lower()} from the BI Community Wiki, by group, "
                                     "with one-line summaries.",
                         header=header, main=main, crumbs=[("Home", "index.html"), (label, f"{kind}/index.html")],
                         page_class="page-index", og_type="website")
        (self.out / kind / "index.html").write_text(doc, encoding="utf-8")

    def home(self, kinds: list[str], all_records: dict[str, list[dict]], slugs: dict[str, str], generated: str) -> None:
        counts = {k: len(v) for k, v in all_records.items()}
        parts = [f"{counts[k]} {self.kind_labels[k].lower()}" for k in kinds]
        header = f"""<h1 class="name home-title">Arma 3 scripting reference</h1>
<p class="lede">{', '.join(parts[:-1]) + ' and ' + parts[-1] if len(parts) > 1 else parts[0]} from the Bohemia Interactive Community Wiki, updated daily, for people and for AI agents.</p>
{self._search("q-hero", "Find a command or function, e.g. createVehicle", hero=True)}"""
        columns = []
        for k in [k for k in kinds if k != "topics"]:
            groups: dict[str, int] = defaultdict(int)
            for r in all_records[k]:
                for g in r["groups"] or ["Uncategorised"]:
                    groups[g] += 1
            items = "".join(
                f'<li><a href="{group_path(k, g)}">{html.escape(g)}</a> <span class="count">{n}</span></li>'
                for g, n in sorted(groups.items(), key=lambda x: x[0].lower())
            )
            columns.append(f'<section class="home-col"><h2><a href="{k}/index.html">{html.escape(self.kind_labels[k])}</a></h2><ul class="group-list">{items}</ul></section>')

        recent = sorted((r for k in kinds for r in all_records[k] if r["updated"]), key=lambda r: r["updated"], reverse=True)[:12]
        recent_items = "".join(
            f'<li><a href="{KIND_OF_TYPE[r["type"]]}/{slugs[r["title"]]}.html">{html.escape(r["name"])}</a>'
            f'<time datetime="{r["updated"]}">{r["updated"][:10]}</time></li>'
            for r in recent
        )
        data_items = "".join(
            f'<li><a href="{href}">{name}</a> {desc}</li>'
            for href, name, desc in [
                ("llms.txt", "llms.txt", "explains the mirror to a language model."),
                ("https://github.com/a3ref/mcp", "a3ref/mcp", "is an MCP server and Claude Code plugin: search, pages and an SQF linter."),
                ("index.json", "index.json", "lists every entry with its syntax, summary, groups and paths."),
                ("names.txt", "names.txt", "lists every name, one per line."),
                *[(f"{k}.json", f"{k}.json", f"holds every {k[:-1]} with full details.") for k in kinds],
                ("syntax.json", "syntax.json", "gives the forms and status of every name, for linters."),
                ("feed.xml", "feed.xml", "is an Atom feed of wiki edits (also changes.json)."),
                ("schema.json", "schema.json", "is the JSON Schema of the records."),
                ("https://github.com/a3ref/data", "a3ref/data", "has the same data with daily git history."),
            ]
        )
        topics = "".join(
            f'<li><a href="topics/{slugs[r["title"]]}.html">{html.escape(r["name"])}</a></li>'
            for r in sorted(all_records.get("topics", []), key=lambda r: (r["groups"][0] == "Data Types", r["name"].lower()))
        )
        main = f"""<div class="home-grid">{''.join(columns)}
<aside class="home-side" aria-label="Topics, recent edits and machine-readable data">
<section><h2><a href="topics/index.html">Topics</a></h2><ul class="group-list">{topics}</ul></section>
<section><h2>Recently edited on the wiki</h2><ul class="recent">{recent_items}</ul></section>
<section><h2>For AI agents and tools</h2><p>Every page also exists as <code>.md</code> and <code>.json</code> next to its <code>.html</code>, with no API key, no rate limit and CORS open.</p><ul class="data-list">{data_items}</ul></section>
</aside></div>"""
        website = {
            "@context": "https://schema.org", "@type": "WebSite", "name": SITE_TITLE, "alternateName": SITE_NAME,
            "url": self.base, "inLanguage": "en",
            "description": "Every Arma 3 scripting command and function from the Bohemia Interactive Community Wiki, "
                           "as HTML, Markdown and JSON.",
        }
        doc = self.shell(path="index.html", title=f"{SITE_TITLE} – every SQF command and function",
                         description="Every Arma 3 scripting command, BIS_fnc function and concept page from the Bohemia "
                                     "Interactive Community Wiki, updated daily, as HTML, Markdown and JSON.",
                         header=header, main=main, crumbs=[("Home", "index.html")], jsonld=[website],
                         extra_head=f'<meta name="google-site-verification" content="{GOOGLE_SITE_VERIFICATION}">\n'
                                    '<link rel="alternate" type="application/atom+xml" title="Wiki edits" href="feed.xml">\n',
                         footer=_site_footer(generated), page_class="page-home", og_type="website")
        (self.out / "index.html").write_text(doc, encoding="utf-8")

    def assets(self, search_entries: list[list]) -> None:
        target = self.out / "assets"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(ASSETS, target, ignore=shutil.ignore_patterns("style.css", "site.js", "404.js", "favicon.ico", "site.webmanifest"))
        (target / "style.css").write_text(minify_css((ASSETS / "style.css").read_text(encoding="utf-8")),
                                          encoding="utf-8")
        for js in ("site.js", "404.js"):
            (target / js).write_text(minify_js((ASSETS / js).read_text(encoding="utf-8")), encoding="utf-8")
        # The browser asks for /favicon.ico and /site.webmanifest at the root.
        shutil.copyfile(ASSETS / "favicon.ico", self.out / "favicon.ico")
        shutil.copyfile(ASSETS / "site.webmanifest", self.out / "site.webmanifest")
        # A script, not JSON, so search also works when the site is opened from disk (file://).
        (target / "search-index.js").write_text(
            "window.BIWIKI_INDEX=" + json.dumps(search_entries, ensure_ascii=False, separators=(",", ":")) + ";",
            encoding="utf-8",
        )


def minify_css(css: str) -> str:
    """Comments and layout whitespace out; enough for Lighthouse, safe for our own stylesheets."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};,>])\s*", r"\1", css)
    return css.replace(";}", "}").strip() + "\n"


def minify_js(js: str) -> str:
    """Drop comments and indentation. Our scripts keep // comments on their own lines and have no "/*" inside
    strings or regular expressions, so this needs no parser."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    lines = [l.strip() for l in js.split("\n")]
    return "\n".join(l for l in lines if l and not l.startswith("//")) + "\n"


def _slug(title: str) -> str:
    from .render import slug  # render imports this module

    return slug(title)


def group_path(kind: str, group: str) -> str:
    """Site-relative path of a group page; the Markdown list for agents sits next to it."""
    return f"groups/{kind}/{_slug(group)}.html"


def heading_id(text: str) -> str:
    """Id of a heading in the HTML pages, also used for #anchors in links between mirrored pages."""
    ident = re.sub(r"[^\w]+", "-", text.lower()).strip("-")
    # ids should start with a letter: "_this" (a magic variable) becomes "v-this"
    return ident if not ident or ident[0].isalpha() else "v-" + ident.lstrip("_-")


def _place_anchors(doc: str) -> str:
    """ANCHOR marks -> <span id="...">, so links to the wiki's anchors land. An id the page already has (a
    heading's, the page shell's, an earlier mark's) is dropped: ids must be unique, and the link lands there anyway.
    A paragraph of marks only becomes the marks, as it would otherwise add an empty line."""
    if ANCHOR[0] not in doc:
        return doc
    doc = re.sub(r"<[^>]*>", lambda m: _ANCHOR.sub("", m.group(0)), doc)  # never inside a tag
    doc = re.sub(f"<p>((?:{_ANCHOR.pattern})+)</p>", lambda m: m.group(1), doc)
    seen = set(re.findall(r'\sid="([^"]*)"', doc))

    def span(m: re.Match) -> str:
        ident = html.escape(m.group(1))
        if not ident or ident in seen:
            return ""
        seen.add(ident)
        return f'<span id="{ident}"></span>'

    return _ANCHOR.sub(span, doc)


def _description(summary: str, name: str, what: str) -> str:
    text = summary or f"{name}: Arma 3 scripting {what}."
    return text if len(text) <= 160 else text[:157].rsplit(" ", 1)[0] + "…"


def _alternates(s: str) -> str:
    return (f'<link rel="alternate" type="text/markdown" href="{s}.md">\n'
            f'<link rel="alternate" type="application/json" href="{s}.json">\n')


def _article_ld(base: str, path: str, rec: dict, summary: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": rec["name"],
        "description": summary or rec["name"],
        "url": f"{base}{path}.html",
        "dateModified": rec["updated"],
        "inLanguage": "en",
        "isBasedOn": rec["url"],
        "about": {"@type": "Thing", "name": "Arma 3 scripting (SQF)"},
        "author": {"@type": "Organization", "name": "Bohemia Interactive Community Wiki contributors",
                   "url": "https://community.bistudio.com/wiki"},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": base},
        "encoding": [
            {"@type": "MediaObject", "contentUrl": f"{base}{path}.md", "encodingFormat": "text/markdown"},
            {"@type": "MediaObject", "contentUrl": f"{base}{path}.json", "encodingFormat": "application/json"},
        ],
    }


def _breadcrumb_ld(base: str, crumbs: list) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name,
             "item": base + ("" if href == "index.html" else href)}
            for i, (name, href) in enumerate(crumbs, 1)
        ],
    }


def _crumbs(root: str, crumbs: list) -> str:
    if len(crumbs) < 2:
        return ""
    items = [f'<li><a href="{root}{href}">{html.escape(name)}</a></li>' for name, href in crumbs[:-1]]
    items.append(f'<li aria-current="page">{html.escape(crumbs[-1][0])}</li>')
    return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'


def _fold(controls: str, label: str) -> str:
    """A side column heading's disclosure button. Open in the HTML: site.js folds the sections on narrow screens,
    and without scripts everything stays visible."""
    return f'<button type="button" class="fold" aria-expanded="true" aria-controls="{controls}">{label}</button>'


def _anchor(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _site_footer(generated: str = "") -> str:
    when = f" Generated {generated[:10]}." if generated else ""
    return ('Content from the <a href="https://community.bistudio.com/wiki">Bohemia Interactive Community Wiki</a>.'
            f"{when}")

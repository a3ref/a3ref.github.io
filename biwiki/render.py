"""Write the mirror: per-page Markdown + JSON + HTML, combined JSON dumps, and the entry points for agents."""
from __future__ import annotations

import html
import json
import re
import shutil
from collections import Counter, defaultdict
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path

from .fetch import CATEGORIES, TOPIC_TITLES, load_cache
from .parse import parse_page, parse_topic, script_name, wiki_url
from .report import Report
from .site import Site, _anchor, heading_id
from .wikitext import Renderer

SITE_URL = "https://a3ref.github.io/"
SCHEMA = Path(__file__).parent / "schema.json"
KINDS = ["commands", "functions", "topics"]
KIND_LABEL = {"commands": "Scripting Commands", "functions": "Functions", "topics": "Topics"}
TYPE_OF = {"commands": "command", "functions": "function", "topics": "topic"}
KIND_OF = {v: k for k, v in TYPE_OF.items()}
DATA_TYPE_CATEGORIES = {"Data Types", "Magic Types", "Syntactical Helper Types"}
# Topic groups by words in the wiki categories, first match wins; anything else is "General".
# A group's title pattern catches pages that only have the broad "Arma 3: Editing" category, or none.
TOPIC_GROUPS = [
    ("GUI", ["Control Types", "GUI", "Dialog"], None),
    ("Scripting", ["Scripting", "Syntax", "Arrays", "Example Code"], r"Regular Expressions|SQF|Scripting Tags|Simple Expression|Extensions"),
    ("Multiplayer and Server", ["Multiplayer", "Startup Parameters", "Server", "MP Modes"], None),
    ("Mission Editing", ["Mission Editing", "Eden Editor", "2D Editor", "Briefing", "Editor Modules"], r"\bModules\b"),
    ("Tools and File Formats", ["Official Tools", "File Formats", "File extensions", "Terrain", "Modelling", "Texturing"], r"Viewer|Splendid|Utilities"),
    ("Reference Lists", ["Reference Lists", "CfgWeapons", "CfgVehicles", "Moves"], r"CfgVehicles (?!.*[Cc]onfig)|Airport IDs|inputAction|Input Actions"),
    ("Configuration", ["Configuration", "Config", "Assets", "Sound", "Particle", "AI"], r"\bCfg|[Cc]onfig|Named Properties|UserActions"),
    ("Change Logs", ["Change Logs"], r"Change Log"),
    ("Modding", [], r"Addon|\bMod\b|Mod (Handling|Presentation)|P3D|RVMAT|[Tt]exture|Terrain|Vegetation|Trees|UVAnimations|"
                    r"Firegeometry|Porting|Encoding|Lighting|Lights|Occluders|camo|destroyable|Tutorial|DevelopmentSetup"),
    ("Game and Troubleshooting", ["Troubleshooting", "Hints & Tips", "Easter Eggs", "Points of Interest"],
     r"Getting Started|Cheats|Play on|Steam|Crash|Unusual Process Exit|OneDrive|TrackIR|Performance|Difficulty|"
     r"Main Menu|Loading Screens|Soundtrack|Launcher|Experimental Ports|Main Updates|Alternate Reality|Artwork|"
     r"Invaders|Profile|userconfig|Objects\.sav|DLC"),
]
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def slug(title: str) -> str:
    """Filesystem- and URL-safe file stem: spaces -> '_', other unsafe bytes -> '~XX'."""
    out = []
    for ch in title.strip():
        if ch == " ":
            out.append("_")
        elif re.match(r"[A-Za-z0-9.\-]", ch):
            out.append(ch)
        else:
            out.append("".join(f"~{b:02X}" for b in ch.encode("utf-8")))
    s = "".join(out)
    return s + "_" if s.upper() in _RESERVED else s


def page_slug(title: str, kind: str, topics: Collection[str] = ()) -> str:
    # "Arma 3: Event Handlers" -> topics/Event_Handlers: shorter, and what an agent would guess; unless
    # ``topics`` (all topic titles) has a page with the shorter title too ("Publisher" and "Arma 3: Publisher")
    short = title.removeprefix("Arma 3: ")
    return slug(short) if kind == "topics" and (short == title or short not in topics) else slug(title)


def summary(md: str, limit: int = 220) -> str:
    """First sentence(s) of a Markdown description as plain text."""
    paragraphs = [p for p in md.split("\n\n") if p.strip() and not p.lstrip().startswith(("#", ">", "```", "|", "-"))]
    # without prose, the first block that reads as text (a heading or a list); never a table or code
    rest = [p for p in md.split("\n\n") if p.strip() and not p.lstrip().startswith(("|", "```"))]
    text = paragraphs[0] if paragraphs else (rest[0] if rest else "")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\\?!?\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^>.*$", "", text, flags=re.M)
    text = re.sub(r"(?m)^(#+|[-*]|\d+\.)\s+", "", text)  # heading and list marks
    text = re.sub(r"\s+", " ", text.replace("**", "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "…"


def _indent_continuation(text: str, pad: str = "  ") -> str:
    lines = text.split("\n")
    return "\n".join([lines[0]] + [(pad + l) if l.strip() else "" for l in lines[1:]])


def _yaml_str(v) -> str:
    return json.dumps(v, ensure_ascii=False)


# ---- page Markdown ---------------------------------------------------------------------------------


def page_markdown(rec: dict, resolve) -> str:
    fm = ["---", f"name: {_yaml_str(rec['name'])}", f"type: {rec['type']}"]
    if rec.get("operator"):
        fm.append(f"operator: {_yaml_str(rec['operator'])}")
    fm += [
        f"status: {rec['status']}",
        *([f"replaced_by: {_yaml_str(rec['replaced_by'])}"] if rec["replaced_by"] else []),
        f"groups: {_yaml_str(rec['groups'])}",
        f"arma3_since: {_yaml_str(rec['arma3_since'])}",
        *([f"branch: {_yaml_str(rec['branch'])}"] if rec["branch"] else []),
        f"locality: {_yaml_str(rec['locality'])}",
        f"source: {rec['url']}",
        f"revid: {rec['revid']}",
        f"updated: {rec['updated']}",
        "---",
        "",
        f"# {rec['name']}",
        "",
    ]
    out = fm

    meta = [rec["type"].capitalize()]
    if rec["groups"]:
        meta.append(", ".join(rec["groups"]))
    if rec["arma3_since"]:
        meta.append(f"Arma 3 v{rec['arma3_since']}")
    if rec["since"] and rec["since"]["game"] != "arma3":
        meta.append(f"introduced in {rec['since']['name']} v{rec['since']['version']}")
    if rec["branch"]:
        meta.append(f"branch: {rec['branch']}")
    out.append("*" + " · ".join(meta) + "*")
    warning = status_note(rec, resolve)
    if warning:
        out += ["", warning]
    loc = rec["locality"]
    loc_parts = []
    if loc["argument"]:
        loc_parts.append(f"arguments **{loc['argument']}**")
    if loc["effect"]:
        loc_parts.append(f"effect **{loc['effect']}**")
    if loc["server_exec"]:
        loc_parts.append("**server execution only**")
    if rec["exec"]:
        loc_parts.append(f"executed with **{rec['exec']}**")
    if loc_parts:
        out += ["", "Locality: " + " · ".join(loc_parts)]
    if rec["aliases"]:
        out += ["", "Alias: " + ", ".join(_link(a, resolve) for a in rec["aliases"])]
    out += ["", body_markdown(rec, resolve), ""]

    if rec["notes"]:
        out += ["## Community notes", ""]
        for n in rec["notes"]:
            head = f"**{n['user'] or 'Anonymous'}**" + (f" — {n['date'][:10]}" if n["date"] else "")
            out += [head, "", n["text"], "", "---", ""]
        out.pop(); out.pop()
        out.append("")

    out += ["", f"<sub>Source: [BI Community Wiki — {rec['title']}]({rec['url']}) (revision {rec['revid']}).</sub>", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def status_note(rec: dict, resolve) -> str:
    """A warning box at the top of deprecated and broken pages, so an agent sees it before the syntax."""
    if rec["status"] == "ok":
        return ""
    what = "deprecated" if rec["status"] == "deprecated" else "listed as broken on the wiki"
    text = f"> [!WARNING]\n> This {rec['type']} is {what}."
    if rec["replaced_by"]:
        text += " Use " + " or ".join(_link(n, resolve) for n in rec["replaced_by"]) + " instead."
    return text


def body_markdown(rec: dict, resolve) -> str:
    """Description, syntax, examples, MP notes and see-also: shared by the .md and .html pages."""
    out: list[str] = []
    if rec["description"]:
        out += ["## Description", "", rec["description"], ""]

    if rec["syntaxes"]:
        out += ["## Syntax", ""]
        many = len(rec["syntaxes"]) > 1
        for i, s in enumerate(rec["syntaxes"], 1):
            if many:
                out += [f"### Syntax {i}", ""]
            notes = [x for x in (s["since"] and f"since {s['since']}", s["effect"] and f"effect: {s['effect']}",
                                 s["exec"] and f"execution: {s['exec']}",
                                 s.get("inferred") and "syntax inferred from the function header") if x]
            if notes:
                out += ["*" + " · ".join(notes) + "*", ""]
            if s["syntax"]:
                out += ["```sqf", s["syntax"], "```", ""]
            if s.get("note"):
                out += [s["note"], ""]
            if s["params"]:
                out += ["**Parameters:**", ""]
                for p in s["params"]:
                    text = p["text"]
                    if p.get("source") == "docblock":
                        text = f"`{p['name']}` — {text}" if p["name"] else text
                    elif p["name"] and text.startswith(p["name"]):
                        text = f"`{p['name']}`" + text[len(p["name"]):]
                    if p["since"]:
                        text += f" *(since {p['since']})*"
                    out.append("- " + _indent_continuation(text))
                out.append("")
            if s["returns"]:
                text = s["returns"]["text"]
                if text.startswith((">", "|", "```")):  # a note, table or code block cannot continue the label's line
                    out += ["**Returns:**", "", text, ""]
                else:
                    out += ["**Returns:** " + _indent_continuation(text, ""), ""]

    if rec["examples"]:
        out += ["## Examples", ""]
        for i, x in enumerate(rec["examples"], 1):
            out += [f"### Example {i}", "", x["text"], ""]

    if rec.get("docblock"):
        out += ["## Function header", "",
                "The comment at the top of the function's file in the game"
                + (f"; this page's {', '.join(rec['filled_from_docblock'])} come from it." if rec["filled_from_docblock"] else "."),
                "", "```sqf", "/*", rec["docblock"]["text"], "*/", "```", ""]

    if rec["multiplayer"]:
        out += ["## Multiplayer", "", rec["multiplayer"], ""]
    if rec["problems"]:
        out += ["## Problems", "", rec["problems"], ""]
    if rec["see_also"]:
        out += ["## See also", "", " · ".join(_link(t, resolve) for t in rec["see_also"]), ""]
    return "\n".join(out).strip()


def topic_markdown(rec: dict) -> str:
    fm = ["---", f"name: {_yaml_str(rec['name'])}", "type: topic"]
    if rec["aliases"]:
        fm.append(f"aliases: {_yaml_str(rec['aliases'])}")
    fm += [f"source: {rec['url']}", f"revid: {rec['revid']}", f"updated: {rec['updated']}", "---", "", f"# {rec['name']}", ""]
    out = fm + [rec["markdown"], "",
                f"<sub>Source: [BI Community Wiki — {rec['title']}]({rec['url']}) (revision {rec['revid']}).</sub>", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def _link(name: str, resolve) -> str:
    url = resolve(name.replace("_", " "), "")
    return f"[{name}]({url})" if url else name


# ---- build ------------------------------------------------------------------------------------------


class Pages:
    """Every mirrored page by wiki title, plus the redirects that point at topics."""

    def __init__(self, raws: dict[str, dict[int, dict]]):
        self.where: dict[str, tuple[str, str]] = {}  # title -> (kind, slug)
        self.names: dict[str, str] = {}  # title -> name as written in scripts
        self.topics = {v["title"] for v in raws.get("topics", {}).values()}
        for kind, pages in raws.items():
            for v in pages.values():
                self.where[v["title"]] = (kind, self.slug(v["title"], kind))
                self.names[v["title"]] = script_name(v["title"], kind, v["wikitext"])
        for v in raws.get("topics", {}).values():
            for alias in v.get("redirects", []):
                self.where.setdefault(alias, ("topics", self.slug(v["title"], "topics")))

    def slug(self, title: str, kind: str) -> str:
        return page_slug(title, kind, self.topics)

    def resolver(self, ext: str):
        """Links to mirrored pages stay local; others go to the wiki (HTML) or become plain text (Markdown:
        agents cannot open the wiki, so a link there only costs tokens)."""

        def resolve(title: str, anchor: str):
            hit = self.where.get(title)
            if hit:
                return f"../{hit[0]}/{hit[1]}.{ext}" + (f"#{heading_id(anchor)}" if anchor else "")
            return wiki_url(title, anchor) if ext == "html" else None

        return resolve

    def name(self, title: str) -> str:
        return self.names.get(title.replace("_", " "), title)

    def script_names(self) -> dict[str, tuple[str, str]]:
        """lower-case script name -> page, for linking identifiers in code (SQF is case-insensitive)."""
        out = {}
        for title, (kind, s) in self.where.items():
            name = self.names.get(title)
            if kind != "topics" and name and re.fullmatch(r"[A-Za-z_]\w*", name):
                out.setdefault(name.lower(), (kind, s))
        return out


class Writer:
    """Writes a page file and, where the name has capitals, a lower-case alias next to it, because agents
    often guess `setpos.md` while GitHub Pages is case-sensitive. Skipped on case-insensitive filesystems
    (local Windows/macOS builds), where both names are the same file."""

    def __init__(self, out_dir: Path):
        probe = out_dir / ".CaseProbe"
        out_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("")
        self.aliases = not (out_dir / ".caseprobe").exists()
        probe.unlink()

    def write(self, target: Path, s: str, ext: str, content: str, title: str = "") -> None:
        (target / f"{s}.{ext}").write_text(content, encoding="utf-8")
        if not self.aliases or s.lower() == s:
            return
        if ext == "html":  # people get a redirect, search engines a canonical link
            content = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
                       f'<meta name="robots" content="noindex"><link rel="canonical" href="{s}.html">'
                       f'<meta http-equiv="refresh" content="0; url={s}.html"></head>'
                       f'<body><p>Moved to <a href="{s}.html">{html.escape(title)}</a>.</p></body></html>')
        (target / f"{s.lower()}.{ext}").write_text(content, encoding="utf-8")


def build(raw_dir: Path, out_dir: Path, kinds: list[str] | None = None, dataset: Path | None = None,
          base_url: str = SITE_URL, renderer: str = "legacy", templates: Path | None = None) -> None:
    """Generate the mirror in ``out_dir``; with ``dataset``, also write the parsed JSON bundles there.

    ``renderer``: "legacy" renders wikitext with wikitext.Renderer; "port" with the MediaWiki parser port and
    htmlmd (portrender.PortRenderer), which needs the wiki's templates (``templates``, a JSON file)."""
    kinds = [k for k in (kinds or KINDS) if (raw_dir / f"{k}.json").exists()]
    raws = {k: load_cache(raw_dir / f"{k}.json") for k in kinds}
    make = _renderer_factory(renderer, templates, raw_dir, raws)
    pages = Pages(raws)
    resolve_md, resolve_html = pages.resolver("md"), pages.resolver("html")
    site = Site(out_dir, pages.script_names(), KIND_LABEL, base_url)
    pending: list[tuple] = []  # HTML is rendered once every record is known (the side navigation lists group siblings)
    writer = Writer(out_dir)
    if (out_dir / "groups").exists():
        shutil.rmtree(out_dir / "groups")
    report = Report()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    records: dict[str, list[dict]] = {}
    slugs: dict[str, str] = {}
    summaries: dict[str, str] = {}
    search: list[list] = []
    index: list[dict] = []

    for kind in kinds:
        target = out_dir / kind
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        records[kind] = []
        for raw in sorted(raws[kind].values(), key=lambda v: v["title"].lower()):
            s = pages.slug(raw["title"], kind)
            # One broken page must not take the whole site down: record it and move on.
            try:
                md_r = make(resolve_md)
                if kind == "topics":
                    rec, page_md, render_html, short = _topic(raw, md_r, make, resolve_html, site, s)
                else:
                    rec, page_md, render_html, short = _reference(raw, kind, md_r, make, pages, resolve_md, resolve_html, site, s)
                if rec is None:
                    report.add("skipped", raw["title"], kind)
                    continue
            except Exception as e:  # noqa: BLE001 - reported, the build goes on
                report.add("error", raw["title"], kind, note=f"{type(e).__name__}: {e}"[:300])
                continue
            report.check_page(raw["title"], kind, rec, page_md, md_r.unknown, raw["wikitext"])
            writer.write(target, s, "md", page_md)
            writer.write(target, s, "json", json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            pending.append((target, s, rec, render_html))
            slugs[rec["title"]] = s
            summaries[rec["title"]] = short
            search.append([rec["name"], rec["type"][0], f"{kind}/{s}", _short(short, 110), rec.get("operator") or ""])
            records[kind].append(rec)
            index.append(_index_entry(rec, kind, s, short))

        (target / "index.md").write_text(_kind_index(kind, records[kind], slugs), encoding="utf-8")
        site.kind_index(kind, records[kind], slugs, summaries)
        print(f"{kind}: {len(records[kind])} pages written")

    members: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for kind, recs in records.items():
        for r in sorted(recs, key=lambda r: r["name"].lower()):
            for g in r["groups"]:
                members[(kind, g)].append((r["name"], f"{slugs[r['title']]}.html"))
    for target, s, rec, render_html in pending:
        kind = target.name
        group = rec["groups"][0] if rec["groups"] else None
        writer.write(target, s, "html", render_html(members.get((kind, group))), rec["name"])

    # Stamp the data with its newest wiki edit, not the build time, so unchanged data stays byte-identical.
    updated = max((r["updated"] for recs in records.values() for r in recs if r["updated"]), default=None)
    files = {
        f"{k}.json": {"updated": updated, "source": wiki_url(CATEGORIES[k]) if k != "topics" else wiki_url("Main Page"),
                      "count": len(recs), "items": recs}
        for k, recs in records.items()
    }
    files["index.json"] = {"updated": updated, "count": len(index), "items": index}
    for name, payload in files.items():
        (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if dataset:
            # one record per line keeps git diffs in the data repository readable
            _write_lines(dataset / name, payload)
    lint = _syntax_index(records, updated)
    (out_dir / "syntax.json").write_text(json.dumps(lint, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(SCHEMA, out_dir / "schema.json")
    if dataset:
        (dataset / "syntax.json").write_text(json.dumps(lint, ensure_ascii=False, indent=0) + "\n", encoding="utf-8",
                                             newline="\n")
        shutil.copyfile(SCHEMA, dataset / "schema.json")

    groups = _group_lists(out_dir, records, slugs, summaries)
    (out_dir / "llms.txt").write_text(_llms_txt(base_url, index, groups, records), encoding="utf-8")
    (out_dir / "llms-full.txt").write_text(_llms_full(base_url, index), encoding="utf-8")
    (out_dir / "names.txt").write_text(_names_txt(base_url, index), encoding="utf-8")
    (out_dir / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {base_url}sitemap.xml\n", encoding="utf-8")
    (out_dir / "sitemap.xml").write_text(_sitemap(base_url, records, slugs, groups), encoding="utf-8")
    (out_dir / "index.md").write_text(_root_index(kinds, index, now), encoding="utf-8")
    site.home(kinds, records, slugs, now)
    site.not_found(base_url)
    site.assets(search)
    health = report.to_json(updated)
    (out_dir / "report.json").write_text(json.dumps(health, ensure_ascii=False, indent=1), encoding="utf-8")
    print("problems:", {k: n for k, n in health["counts"].items() if n} or "none")


def _renderer_factory(renderer: str, templates: Path | None, raw_dir: Path, raws: dict):
    """A callable (resolve, **options) -> renderer with wikitext.Renderer's interface."""
    if renderer == "legacy":
        return Renderer
    if renderer != "port":
        raise ValueError(f"unknown renderer {renderer!r}")
    if templates is None or not Path(templates).is_file():
        raise FileNotFoundError(f"the port renderer needs the wiki's templates file; not found: {templates}")
    from .portrender import PortContext

    return PortContext.load(templates, raw_dir, raws).renderer


def _reference(raw, kind, md_r, make, pages: Pages, resolve_md, resolve_html, site: Site, s: str):
    """A command or function page: (JSON record, Markdown, HTML, summary)."""
    rec_md = parse_page(raw, kind, md_r)
    if rec_md is None:
        return None, "", "", ""
    rec = parse_page(raw, kind, make(None, hard_breaks=False))  # JSON: plain newlines
    rec_html = parse_page(raw, kind, make(resolve_html, code_links=True))
    for r in (rec, rec_md, rec_html):
        _fix_references(r, pages)
    short = summary(rec["description"])
    body, note = body_markdown(rec_html, resolve_html), status_note(rec_html, resolve_html)
    render_html = lambda siblings: site.page(kind, s, rec_html, body, short, note, siblings)  # noqa: E731
    return rec, page_markdown(rec_md, resolve_md), render_html, short


def topic_group(raw: dict) -> str:
    """The first group whose words occur in one of the page's wiki categories or whose pattern matches its title;
    the concept pages picked by hand (TOPIC_TITLES) stay under Scripting."""
    categories = raw.get("categories", [])
    if DATA_TYPE_CATEGORIES & set(categories):
        return "Data Types"
    if "Event Handlers" in raw["title"]:
        return "Event Handlers"
    if raw["title"] in TOPIC_TITLES:
        return "Scripting"
    for group, words, title in TOPIC_GROUPS:
        if any(w in c for c in categories for w in words) or (title and re.search(title, raw["title"])):
            return group
    return "General"


def _topic(raw, md_r, make, resolve_html, site: Site, s: str):
    rec_md = parse_topic(raw, md_r)
    rec = parse_topic(raw, make(None, hard_breaks=False))  # JSON: plain newlines
    rec_html = parse_topic(raw, make(resolve_html, code_links=True))
    group = topic_group(raw)
    for r in (rec, rec_md, rec_html):
        r["groups"] = [group]
    short = summary(rec["markdown"])
    return rec, topic_markdown(rec_md), (lambda siblings: site.topic(s, rec_html, short, siblings)), short


def _fix_references(rec: dict, pages: Pages) -> None:
    """Wiki links give page titles ("diag fps"); records should name things as scripts do (diag_fps)."""
    rec["see_also"] = [pages.name(t) for t in rec["see_also"]]
    rec["aliases"] = [pages.name(t) for t in rec["aliases"]]
    rec["replaced_by"] = [pages.name(t) for t in rec["replaced_by"]
                          if pages.where.get(t, ("",))[0] in ("commands", "functions") and t != rec["title"]]


def _index_entry(rec: dict, kind: str, s: str, short: str) -> dict:
    if kind == "topics":
        return {"name": rec["name"], "type": "topic", "md": f"{kind}/{s}.md", "json": f"{kind}/{s}.json",
                "groups": rec["groups"], "syntax": [], "summary": short, "arma3_since": None, "locality": None,
                "status": "ok", "operator": None, "aliases": rec["aliases"]}
    return {
        "name": rec["name"],
        "type": rec["type"],
        "md": f"{kind}/{s}.md",
        "json": f"{kind}/{s}.json",
        "groups": rec["groups"],
        "syntax": [x["syntax"] for x in rec["syntaxes"] if x["syntax"]],
        "summary": short,
        "arma3_since": rec["arma3_since"],
        "locality": rec["locality"],
        "status": rec["status"],
        "operator": rec["operator"],
        "aliases": rec["aliases"],
    }


def _syntax_index(records: dict[str, list[dict]], updated) -> dict:
    """Compact lookup for linters and the MCP server: forms, status and replacements of every name."""
    commands, functions = {}, {}
    for r in records.get("commands", []):
        forms = sorted({s["form"] for s in r["syntaxes"] if s["form"]})
        entry = {"name": r["name"], "forms": forms, "status": r["status"],
                 "syntax": [s["syntax"] for s in r["syntaxes"] if s["syntax"]]}
        if r["replaced_by"]:
            entry["replaced_by"] = r["replaced_by"]
        if r["branch"]:
            entry["branch"] = r["branch"]
        if r["operator"]:
            entry["operator"] = r["operator"]
        commands[(r["operator"] or r["name"]).lower()] = entry
    for r in records.get("functions", []):
        entry = {"name": r["name"], "status": r["status"]}
        if r["replaced_by"]:
            entry["replaced_by"] = r["replaced_by"]
        functions[r["name"].lower()] = entry
    return {"updated": updated, "commands": dict(sorted(commands.items())), "functions": dict(sorted(functions.items()))}


# ---- entry points for agents ---------------------------------------------------------------------------


def _group_lists(out_dir: Path, records, slugs, summaries) -> dict[str, list[tuple[str, str, int]]]:
    """groups/<kind>/<group>.md: small per-group lists an agent can fetch instead of the whole index."""
    root = out_dir / "groups"  # emptied at the start of build(); the HTML group pages live here too
    result: dict[str, list[tuple[str, str, int]]] = {}
    for kind, recs in records.items():
        by_group: dict[str, list[dict]] = defaultdict(list)
        for r in recs:
            for g in r["groups"] or ["Uncategorised"]:
                by_group[g].append(r)
        (root / kind).mkdir(parents=True, exist_ok=True)
        result[kind] = []
        for g in sorted(by_group, key=str.lower):
            gs = slug(g)
            lines = [f"# {g} ({KIND_LABEL[kind].lower()})", ""]
            for r in sorted(by_group[g], key=lambda r: r["name"].lower()):
                flag = "" if r.get("status", "ok") == "ok" else f" **[{r['status']}]**"
                lines.append(f"- [{r['name']}](../../{kind}/{slugs[r['title']]}.md){flag}: {summaries[r['title']]}")
            (root / kind / f"{gs}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            result[kind].append((g, f"groups/{kind}/{gs}.md", len(by_group[g])))
    return result


def _llms_txt(base: str, index: list[dict], groups, records) -> str:
    """https://llmstxt.org/ entry point, kept small enough to read in full (a few thousand tokens)."""
    counts = Counter(e["type"] for e in index)
    out = [
        "# Arma 3 Scripting Reference (a3ref)",
        "",
        f"> Every Arma 3 scripting command ({counts['command']}), function ({counts['function']}) and the core "
        f"topic pages ({counts['topic']}: data types, locality, event handlers, mission editing, configs, GUI, "
        "multiplayer and server, tools, ...) from the Bohemia Interactive "
        "Community Wiki, updated daily and published for AI agents, bots and tools as Markdown and JSON at stable URLs.",
        "",
        "## How to use",
        "",
        f"- One page: `{base}commands/<name>.md`, `{base}functions/<name>.md`, `{base}topics/<name>.md`; "
        "`.json` for structured data. Lower-case paths work too (`commands/setpos.md`).",
        "- Spaces in names become `_`; characters outside `A-Za-z0-9.-` become `~XX` per UTF-8 byte "
        "(the operator page `a != b` is `commands/a_~21~3D_b.md`). Operators are also findable by symbol in index.json.",
        f"- Every name on one line each: {base}names.txt",
        f"- Search by meaning: {base}index.json (name, syntax, one-line summary, groups, locality, status, paths), "
        "or the per-group lists below.",
        "- Check `status` before using a command: `deprecated` and `broken` pages say what to use instead.",
        f"- Everything at once: {base}commands.json, {base}functions.json, {base}topics.json; "
        f"record format {base}schema.json; forms and status of every name for linters: {base}syntax.json",
        f"- Full list of every page with a summary (large): {base}llms-full.txt",
        f"- What changed on the wiki recently: {base}changes.md (also changes.json, Atom feed {base}feed.xml)",
        "- The same data with daily git history: https://github.com/a3ref/data",
        "- MCP server and Claude Code plugin (search, read pages, lint SQF): https://github.com/a3ref/mcp",
        "",
        "## Core topics",
        "",
    ]
    # the scripting concepts in full; the other Arma 3 pages (editing, configs, tools, ...) through their groups
    core = {"Data Types", "Event Handlers"}
    out += [f"- [{e['name']}]({base}{e['md']}): {e['summary']}" for e in index
            if e["type"] == "topic" and (core & set(e["groups"]) or e["name"] in TOPIC_TITLES)]
    for kind in ("topics", "commands", "functions"):
        if kind not in groups:
            continue
        out += ["", f"## {KIND_LABEL[kind]} by group", ""]
        out += [f"- [{g}]({base}{path}) ({n})" for g, path, n in groups[kind]]
    return "\n".join(out) + "\n"


def _llms_full(base: str, index: list[dict]) -> str:
    out = ["# Arma 3 Scripting Reference (a3ref): every page", "",
           f"> The complete list behind {base}llms.txt: every command, function and topic with a one-line summary.", ""]
    for kind in KINDS:
        t = TYPE_OF[kind]
        entries = [e for e in index if e["type"] == t]
        if not entries:
            continue
        out += [f"## {KIND_LABEL[kind]}", ""]
        for e in entries:
            flag = "" if e["status"] == "ok" else f" [{e['status']}]"
            out.append(f"- [{e['name']}]({base}{e['md']}){flag}: {e['summary']}")
        out.append("")
    return "\n".join(out)


def _names_txt(base: str, index: list[dict]) -> str:
    """Every name, one per line; only names whose path does not follow the simple rule carry a path."""
    out = [f"# Arma 3 scripting names. Page: {base}<kind>/<name>.md (or .json). Lines with -> give the exact path.", ""]
    for kind in KINDS:
        t = TYPE_OF[kind]
        out.append(f"## {kind}")
        for e in index:
            if e["type"] != t:
                continue
            simple = e["md"] == f"{kind}/{e['name']}.md"
            label = e["name"] + (f" ({e['operator']})" if e.get("operator") else "")
            out.append(label if simple else f"{label} -> {e['md']}")
        out.append("")
    return "\n".join(out)


def _sitemap(base: str, records: dict[str, list[dict]], slugs: dict[str, str], groups) -> str:
    urls = [f"<url><loc>{base}</loc></url>"]
    for kind, recs in records.items():
        urls.append(f"<url><loc>{base}{kind}/index.html</loc></url>")
        if kind != "topics":  # topics have no group pages
            urls += [f"<url><loc>{base}{path[:-3]}.html</loc></url>" for _, path, _ in groups.get(kind, [])]
        for r in recs:
            lastmod = f"<lastmod>{r['updated'][:10]}</lastmod>" if r["updated"] else ""
            urls.append(f"<url><loc>{base}{kind}/{slugs[r['title']]}.html</loc>{lastmod}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls) + "\n</urlset>\n")


def _write_lines(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in payload.items() if k != "items"}
    lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in payload["items"]]
    text = json.dumps(head, ensure_ascii=False)[:-1] + ', "items": [\n' + ",\n".join(lines) + "\n]}\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _kind_index(kind: str, records: list[dict], slugs: dict[str, str]) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        for g in r["groups"] or ["Uncategorised"]:
            groups[g].append(r)
    out = [f"# Arma 3 {KIND_LABEL[kind]}", "", f"{len(records)} entries in {len(groups)} groups.", ""]
    out += ["## Groups", ""] + [f"- [{g}](#{_anchor(g)}) ({len(groups[g])})" for g in sorted(groups)] + [""]
    for g in sorted(groups):
        out += [f"## {g}", "", "| Name | Summary |", "|---|---|"]
        for r in groups[g]:
            text = summary(r.get("description") or r.get("markdown", ""), 140).replace("|", "\\|")
            out.append(f"| [{r['name'].replace('|', chr(92) + '|')}]({slugs[r['title']]}.md) | {text} |")
        out.append("")
    return "\n".join(out)


def _root_index(kinds: list[str], index: list[dict], now: str) -> str:
    counts = Counter(e["type"] for e in index)
    out = ["# Arma 3 Scripting Reference (mirror)", "",
           "Generated from the [Bohemia Interactive Community Wiki](https://community.bistudio.com/wiki) "
           f"on {now}.", ""]
    for kind in kinds:
        out.append(f"- [{KIND_LABEL[kind]}]({kind}/index.md) — {counts[TYPE_OF[kind]]} pages")
    out += [
        "",
        "## Machine-readable",
        "",
        "- [`llms.txt`](llms.txt) — start here: how to use the mirror",
        "- [`index.json`](index.json) — every entry: name, syntax, summary, groups, locality, status, paths",
        "- [`names.txt`](names.txt) — every name, one per line",
        *[f"- [`{k}.json`]({k}.json) — all {KIND_LABEL[k].lower()} with full details" for k in kinds],
        "- [`syntax.json`](syntax.json) — forms and status of every name, for linters",
        "- [`schema.json`](schema.json) — JSON Schema of the records",
        "- each page: `<kind>/<name>.md` and `<kind>/<name>.json`",
        "",
    ]
    return "\n".join(out)

"""Write the mirror: per-page Markdown + JSON, combined JSON dumps, indexes and llms.txt."""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .fetch import CATEGORIES, load_cache
from .parse import display_name, parse_page, wiki_url
from .report import Report
from .site import Site, _anchor
from .wikitext import Renderer

KIND_LABEL = {"commands": "Scripting Commands", "functions": "Functions"}
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


def summary(md: str, limit: int = 220) -> str:
    """First sentence(s) of a Markdown description as plain text."""
    text = md.split("\n\n")[0]
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^>.*$", "", text, flags=re.M)
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


def page_markdown(rec: dict, resolve) -> str:
    fm = [
        "---",
        f"name: {_yaml_str(rec['name'])}",
        f"type: {rec['type']}",
        f"groups: {_yaml_str(rec['groups'])}",
        f"arma3_since: {_yaml_str(rec['arma3_since'])}",
    ]
    if rec["branch"]:
        fm.append(f"branch: {_yaml_str(rec['branch'])}")
    fm += [
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
                                 s["exec"] and f"execution: {s['exec']}") if x]
            if notes:
                out += ["*" + " · ".join(notes) + "*", ""]
            if s["syntax"]:
                out += ["```sqf", s["syntax"], "```", ""]
            if s["params"]:
                out += ["**Parameters:**", ""]
                for p in s["params"]:
                    text = p["text"]
                    if p["name"] and text.startswith(p["name"]):
                        text = f"`{p['name']}`" + text[len(p["name"]):]
                    if p["since"]:
                        text += f" *(since {p['since']})*"
                    out.append("- " + _indent_continuation(text))
                out.append("")
            if s["returns"]:
                out += ["**Returns:** " + _indent_continuation(s["returns"]["text"], ""), ""]

    if rec["examples"]:
        out += ["## Examples", ""]
        for i, x in enumerate(rec["examples"], 1):
            out += [f"### Example {i}", "", x["text"], ""]

    if rec["multiplayer"]:
        out += ["## Multiplayer", "", rec["multiplayer"], ""]
    if rec["problems"]:
        out += ["## Problems", "", rec["problems"], ""]
    if rec["see_also"]:
        out += ["## See also", "", " · ".join(_link(t, resolve) for t in rec["see_also"]), ""]
    return "\n".join(out).strip()


def _link(title: str, resolve) -> str:
    url = resolve(title.replace("_", " "), "")
    return f"[{title}]({url})" if url else title


def build(raw_dir: Path, out_dir: Path, kinds: list[str] | None = None, dataset: Path | None = None) -> None:
    """Generate the mirror in ``out_dir``; with ``dataset``, also write the parsed JSON bundles there."""
    kinds = kinds or list(CATEGORIES)
    raws = {k: load_cache(raw_dir / f"{k}.json") for k in kinds}
    # title (spaces) -> (kind, slug), so cross-links between mirrored pages stay local
    known = {v["title"]: (k, slug(v["title"])) for k, pages in raws.items() for v in pages.values()}

    def resolve_md(title: str, anchor: str):
        hit = known.get(title)
        if hit:
            return f"../{hit[0]}/{hit[1]}.md"
        return wiki_url(title, anchor)

    def resolve_html(title: str, anchor: str):
        hit = known.get(title)
        if hit:
            return f"../{hit[0]}/{hit[1]}.html"
        return wiki_url(title, anchor)

    # names as written in scripts (lower-case; SQF is case-insensitive) -> page, for linking code
    script_names = {}
    for title, (k, s) in known.items():
        name = display_name(title, k)
        if re.fullmatch(r"[A-Za-z_]\w*", name):
            script_names.setdefault(name.lower(), (k, s))
    site = Site(out_dir, script_names, KIND_LABEL)
    site_records: dict[str, list[dict]] = {}
    slugs: dict[str, str] = {}
    summaries: dict[str, str] = {}
    search: list[list] = []
    bundles: dict[str, dict] = {}

    report = Report()
    now =datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index: list[dict] = []
    llms = [
        "# Arma 3 Scripting Reference",
        "",
        "> Mirror of Arma 3 scripting commands and functions from the Bohemia Interactive Community Wiki "
        "(https://community.bistudio.com/wiki), converted to Markdown and JSON. "
        "Every page is available as `<name>.md` and `<name>.json`; `index.json` lists all entries.",
        "",
    ]

    for kind in kinds:
        target = out_dir / kind
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        records = []
        for raw in sorted(raws[kind].values(), key=lambda v: v["title"].lower()):
            # One broken page must not take the whole site down: record it and move on.
            try:
                md_r = Renderer(resolve_md)
                rec_md = parse_page(raw, kind, md_r)
                rec = parse_page(raw, kind, Renderer(None))
                if rec is None:
                    report.add("skipped", raw["title"], kind)
                    continue
                s = slug(raw["title"])
                page_md = page_markdown(rec_md, resolve_md)
                rec_html = parse_page(raw, kind, Renderer(resolve_html))
                short = summary(rec["description"])
                site.page(kind, s, rec_html, body_markdown(rec_html, resolve_html), short)
            except Exception as e:  # noqa: BLE001 - reported, the build goes on
                report.add("error", raw["title"], kind, note=f"{type(e).__name__}: {e}"[:300])
                continue
            report.check_page(raw["title"], kind, rec, page_md, md_r.unknown)
            (target / f"{s}.md").write_text(page_md, encoding="utf-8")
            (target / f"{s}.json").write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            slugs[rec["title"]] = s
            summaries[rec["title"]] = short
            search.append([rec["name"], rec["type"][0], f"{kind}/{s}", summary(rec["description"], 110)])
            records.append(rec)
            index.append({
                "name": rec["name"],
                "type": rec["type"],
                "md": f"{kind}/{s}.md",
                "json": f"{kind}/{s}.json",
                "groups": rec["groups"],
                "syntax": [x["syntax"] for x in rec["syntaxes"] if x["syntax"]],
                "summary": summary(rec["description"]),
                "arma3_since": rec["arma3_since"],
                "locality": rec["locality"],
            })

        bundles[kind] = {"source": wiki_url(CATEGORIES[kind]), "count": len(records), "items": records}
        (target / "index.md").write_text(_kind_index(kind, records), encoding="utf-8")
        site.kind_index(kind, records, slugs, summaries)
        site_records[kind] = records

        llms += [f"## {KIND_LABEL[kind]}", ""]
        llms += [f"- [{e['name']}]({e['md']}): {e['summary']}" for e in index if e["type"] == records[0]["type"]] if records else []
        llms.append("")
        print(f"{kind}: {len(records)} pages written")

    # Stamp the data with its newest wiki edit, not the build time, so unchanged data stays byte-identical.
    updated = max((r["updated"] for recs in site_records.values() for r in recs if r["updated"]), default=None)
    files = {f"{k}.json": {"updated": updated, **b} for k, b in bundles.items()}
    files["index.json"] = {"updated": updated, "count": len(index), "items": index}
    for name, payload in files.items():
        (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if dataset:
            # one record per line keeps git diffs in the data repository readable
            _write_lines(dataset / name, payload)
    (out_dir / "llms.txt").write_text("\n".join(llms), encoding="utf-8")
    (out_dir / "index.md").write_text(_root_index(kinds, index, now), encoding="utf-8")
    site.home(kinds, site_records, slugs, now)
    site.assets(search)
    health = report.to_json(updated)
    (out_dir / "report.json").write_text(json.dumps(health, ensure_ascii=False, indent=1), encoding="utf-8")
    print("problems:", {k: n for k, n in health["counts"].items() if n} or "none")


def _write_lines(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in payload.items() if k != "items"}
    lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in payload["items"]]
    text = json.dumps(head, ensure_ascii=False)[:-1] + ', "items": [\n' + ",\n".join(lines) + "\n]}\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _kind_index(kind: str, records: list[dict]) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        for g in r["groups"] or ["Uncategorised"]:
            groups[g].append(r)
    out = [f"# Arma 3 {KIND_LABEL[kind]}", "", f"{len(records)} entries in {len(groups)} groups.", ""]
    out += ["## Groups", ""] + [f"- [{g}](#{_anchor(g)}) ({len(groups[g])})" for g in sorted(groups)] + [""]
    for g in sorted(groups):
        out += [f"## {g}", "", "| Name | Summary |", "|---|---|"]
        for r in groups[g]:
            s = summary(r["description"], 140).replace("|", "\\|")
            out.append(f"| [{r['name'].replace('|', chr(92) + '|')}]({slug(r['title'])}.md) | {s} |")
        out.append("")
    return "\n".join(out)


def _root_index(kinds: list[str], index: list[dict], now: str) -> str:
    counts = Counter(e["type"] for e in index)
    out = ["# Arma 3 Scripting Reference (mirror)", "",
           "Generated from the [Bohemia Interactive Community Wiki](https://community.bistudio.com/wiki) "
           f"on {now}.", ""]
    for kind in kinds:
        t = "command" if kind == "commands" else "function"
        out.append(f"- [{KIND_LABEL[kind]}]({kind}/index.md) — {counts[t]} pages")
    out += [
        "",
        "## Machine-readable",
        "",
        "- [`index.json`](index.json) — every entry: name, syntax, summary, groups, locality, paths",
        *[f"- [`{k}.json`]({k}.json) — all {KIND_LABEL[k].lower()} with full details" for k in kinds],
        "- [`llms.txt`](llms.txt) — LLM-friendly index",
        "- each page: `<kind>/<name>.md` and `<kind>/<name>.json`",
        "",
    ]
    return "\n".join(out)

"""What changed on the wiki: built from the git history of the data repository.

Each sync commit in a3ref/data rewrites commands.json / functions.json / topics.json; comparing the
``revid`` of every page between a commit and its parent gives the wiki edits of that day. Changes made
only by the parser (same revid) are not wiki edits and are left out.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from html import escape
from pathlib import Path

FILES = {"commands.json": "commands", "functions.json": "functions", "topics.json": "topics"}
MAX_COMMITS = 90
MAX_FEED_ENTRIES = 150


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def _pages_at(repo: Path, commit: str, file: str) -> dict[str, dict]:
    """{title: record} of one bundle at a commit; {} if the file did not exist yet."""
    try:
        text = _git(repo, "show", f"{commit}:{file}")
    except subprocess.CalledProcessError:
        return {}
    return {r["title"]: r for r in json.loads(text)["items"]}


def history(repo: Path, slug_of) -> list[dict]:
    """Newest first: one entry per data commit that changed any page revision."""
    commits = _git(repo, "log", f"-n{MAX_COMMITS}", "--format=%H %cI", "--", *FILES).split()
    pairs = list(zip(commits[0::2], commits[1::2]))
    out = []
    for commit, date in pairs:
        parents = _git(repo, "log", "-n1", "--format=%P", commit).split()
        if not parents:
            continue  # the initial import is not a change
        since = _when(_git(repo, "log", "-n1", "--format=%cI", parents[0]).strip())
        entry = {"commit": commit, "date": date, "added": [], "changed": [], "removed": []}
        for file, kind in FILES.items():
            new, old = _pages_at(repo, commit, file), _pages_at(repo, parents[0], file)
            if not old:
                continue  # a bundle that appeared for the first time is an import, not a wiki edit
            for title, r in new.items():
                item = {"name": r["name"], "type": r["type"], "path": f"{kind}/{slug_of(title, kind, new)}",
                        "revid": r["revid"], "updated": r["updated"], "url": r["url"]}
                if title not in old:
                    # a page last edited before the previous sync was not new on the wiki: the mirror grew
                    if r["updated"] and _when(r["updated"]) < since:
                        continue
                    entry["added"].append(item)
                elif old[title]["revid"] != r["revid"]:
                    entry["changed"].append(item)
            for title, r in old.items():
                if title not in new:
                    entry["removed"].append({"name": r["name"], "type": r["type"], "url": r["url"]})
        if entry["added"] or entry["changed"] or entry["removed"]:
            out.append(entry)
    return out


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def write(repo: Path, out_dir: Path, base_url: str, slug_of) -> None:
    entries = history(repo, slug_of)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "changes.json").write_text(json.dumps({"changes": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "changes.md").write_text(_markdown(entries, base_url), encoding="utf-8")
    (out_dir / "feed.xml").write_text(_atom(entries, base_url), encoding="utf-8")
    total = sum(len(e["added"]) + len(e["changed"]) + len(e["removed"]) for e in entries)
    print(f"changes: {len(entries)} syncs with {total} page changes")


def _markdown(entries: list[dict], base: str) -> str:
    out = ["# Recent changes on the wiki", "",
           f"Arma 3 scripting pages edited on the BI Community Wiki, newest first. Also as {base}changes.json and "
           f"an Atom feed: {base}feed.xml", ""]
    if not entries:
        out.append("No edits since the mirror started.")
    for e in entries:
        out += [f"## {e['date'][:10]}", ""]
        for label, key in (("Added", "added"), ("Changed", "changed")):
            for i in e[key]:
                out.append(f"- {label}: [{i['name']}]({base}{i['path']}.md) ({i['type']})")
        for i in e["removed"]:
            out.append(f"- Removed: {i['name']} ({i['type']})")
        out.append("")
    return "\n".join(out)


def _atom(entries: list[dict], base: str) -> str:
    items = []
    for e in entries:
        for label, key in (("added", "added"), ("updated", "changed")):
            for i in e[key]:
                items.append((i["updated"] or e["date"], label, i))
    items.sort(key=lambda x: x[0], reverse=True)
    now = items[0][0] if items else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>a3ref: Arma 3 scripting changes</title>",
           f'<link href="{base}"/>', f'<link rel="self" href="{base}feed.xml"/>',
           f"<id>{base}feed.xml</id>", f"<updated>{now}</updated>",
           "<author><name>BI Community Wiki contributors</name></author>"]
    for when, label, i in items[:MAX_FEED_ENTRIES]:
        url = f"{base}{i['path']}.html"
        xml += ["<entry>", f"<title>{escape(i['name'])} ({i['type']}) {label}</title>", f'<link href="{url}"/>',
                f"<id>{url}#rev{i['revid']}</id>", f"<updated>{when}</updated>",
                f'<summary>{escape(i["name"])} was {label} on the wiki (revision {i["revid"]}). Source: {escape(i["url"])}</summary>',
                "</entry>"]
    xml.append("</feed>")
    return "\n".join(xml) + "\n"

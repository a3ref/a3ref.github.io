"""Parser health report: what went wrong while building, and what is new compared to the accepted baseline.

Every problem has a stable ``key`` (kind + page + detail), so reports can be diffed across runs.
``known-problems.json`` lists the keys that are accepted; only problems outside it are reported as new.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from .parse import wiki_url

KIND_TITLES = {
    "error": "Pages the parser crashed on",
    "skipped": "Pages without an {{RV}} template (left out of the site)",
    "no-syntax": "Pages without any syntax",
    "unknown-template": "Templates the converter does not know",
    "unknown-tag": "HTML/wiki tags the converter does not know",
    "markup": "Raw wiki markup left in the output",
    "unnamed-param": "Parameters without a name",
    "untyped-param": "Parameters without a type",
}
# Order of severity; "error" also fails the workflow run.
KIND_ORDER = list(KIND_TITLES)

# Wiki markup that should never survive conversion (checked outside code blocks and inline code).
LEFTOVERS = {
    "{{": re.compile(r"\{\{"),
    "}}": re.compile(r"\}\}"),
    # an unconverted [[Title]] / [[Title|text]]; nested SQF arrays like [[x, y], [z]] in prose are fine
    "[[": re.compile(r"\[\[[A-Za-z:][^\[\]\n,]*(?:\|[^\[\]\n]+)?\]\]"),
    "''": re.compile(r"(?<![\"'])''(?![\"'])"),
    "{|": re.compile(r"^\{\|", re.M),
    "<nowiki": re.compile(r"<nowiki", re.I),
}
_FENCED = re.compile(r"^(`{3,}).*?^\1", re.S | re.M)
_INLINE = re.compile(r"(`+)(?!`).+?(?<!`)\1")

ISSUE_LABEL = "parser-report"
ISSUE_TITLE = "Parser report: new problems"
LIST_LIMIT = 60


class Report:
    def __init__(self):
        self.problems: dict[str, dict] = {}

    def add(self, kind: str, title: str, page_kind: str, detail: str = "", note: str = "") -> None:
        page = f"{page_kind}/{title}"
        key = f"{kind}|{page}" + (f"|{detail}" if detail else "")
        self.problems.setdefault(key, {
            "key": key, "kind": kind, "page": page, "url": wiki_url(title), "detail": detail, "note": note,
        })

    def check_page(self, title: str, page_kind: str, rec: dict, md: str, unknown) -> None:
        for name in unknown:
            what, _, ident = name.partition(":")
            self.add(f"unknown-{what}", title, page_kind, ident)
        for pattern in leftover_markup(md):
            self.add("markup", title, page_kind, pattern)
        if not rec["syntaxes"]:
            self.add("no-syntax", title, page_kind)
        for i, s in enumerate(rec["syntaxes"], 1):
            for p in s["params"]:
                if not p["name"]:
                    self.add("unnamed-param", title, page_kind, f"syntax {i}: {p['text'][:40]}")
                elif not p["type"]:
                    self.add("untyped-param", title, page_kind, f"syntax {i}: {p['name']}")

    def to_json(self, updated) -> dict:
        items = sorted(self.problems.values(), key=lambda p: (KIND_ORDER.index(p["kind"]), p["key"]))
        counts = {k: sum(1 for p in items if p["kind"] == k) for k in KIND_ORDER}
        return {"updated": updated, "counts": counts, "problems": items}


def leftover_markup(md: str) -> list[str]:
    text = _INLINE.sub("", _FENCED.sub("", md))
    return [name for name, rx in LEFTOVERS.items() if rx.search(text)]


# ---- comparing against the accepted baseline and reporting ------------------------------------

def load_known(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def save_known(path: Path, keys) -> None:
    path.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def markdown(report: dict, new: list[dict], resolved: list[str], site: str) -> str:
    from .render import slug  # local import: render imports this module

    counts = report["counts"]
    lines = ["## Parser report", ""]
    lines += ["| Problem | Total | New |", "|---|---|---|"]
    new_counts = {k: sum(1 for p in new if p["kind"] == k) for k in KIND_ORDER}
    for k in KIND_ORDER:
        if counts.get(k) or new_counts[k]:
            lines.append(f"| {KIND_TITLES[k]} | {counts.get(k, 0)} | {new_counts[k] or ''} |")
    lines.append("")
    if not new:
        lines.append("No new problems compared to `known-problems.json`.")
    for k in KIND_ORDER:
        group = [p for p in new if p["kind"] == k]
        if not group:
            continue
        lines += ["", f"### {KIND_TITLES[k]}", ""]
        for p in group[:LIST_LIMIT]:
            kind, _, title = p["page"].partition("/")
            detail = f": `{p['detail']}`" if p["detail"] else ""
            note = f"\n  ```\n  {p['note']}\n  ```" if p["note"] else ""
            if p["kind"] in ("error", "skipped"):  # no page on the site to link to
                lines.append(f"- [{title}]({p['url']}){detail}{note}")
            else:
                lines.append(f"- [{title}]({site}{kind}/{slug(title)}.html) ([wiki]({p['url']})){detail}{note}")
        if len(group) > LIST_LIMIT:
            lines.append(f"- … and {len(group) - LIST_LIMIT} more (see `report.json`)")
    if resolved:
        lines += ["", f"{len(resolved)} known problems are gone; run `python -m biwiki report --accept` to drop them from the baseline."]
    lines += ["", f"Full report: {site}report.json"]
    return "\n".join(lines)


def run(out_dir: Path, known_path: Path, accept: bool, issue: bool, site: str) -> int:
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    current = {p["key"]: p for p in report["problems"]}
    if accept:
        save_known(known_path, current)
        print(f"Accepted {len(current)} problems into {known_path}")
        return 0

    known = load_known(known_path)
    new = [p for k, p in current.items() if k not in known]
    resolved = sorted(known - set(current))
    md = markdown(report, new, resolved, site)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    for p in new:
        if p["kind"] == "error":
            print(f"::error title=Parser crashed::{p['page']}: {p['note']}")

    if issue:
        sync_issue(new, md)
    return 1 if any(p["kind"] == "error" for p in new) else 0


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def sync_issue(new: list[dict], md: str) -> None:
    """Open, update or close the single "parser-report" issue; only changes notify subscribers."""
    digest = hashlib.sha1("\n".join(sorted(p["key"] for p in new)).encode()).hexdigest()[:12]
    marker = f"<!-- problems:{digest} -->"
    body = md + "\n\n" + marker
    if len(body) > 60000:
        body = body[:60000] + "\n\n…truncated, see report.json\n\n" + marker
    _gh("label", "create", ISSUE_LABEL, "--color", "B60205", "--description", "Automatic parser report", "--force")
    issues = json.loads(_gh("issue", "list", "--label", ISSUE_LABEL, "--state", "open", "--json", "number,body"))
    current = issues[0] if issues else None

    if not new:
        if current:
            _gh("issue", "close", str(current["number"]), "--comment", "All new problems are gone.")
            print(f"Closed issue #{current['number']}")
        return
    if current is None:
        url = _gh("issue", "create", "--title", ISSUE_TITLE, "--label", ISSUE_LABEL, "--body", body).strip()
        print(f"Opened {url}")
    elif marker not in current["body"]:
        _gh("issue", "edit", str(current["number"]), "--body", body)
        _gh("issue", "comment", str(current["number"]), "--body",
            f"The set of new problems changed: now {len(new)}. The description above is up to date.")
        print(f"Updated issue #{current['number']}")
    else:
        print(f"Issue #{current['number']} is already up to date")

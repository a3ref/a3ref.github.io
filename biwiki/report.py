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
from typing import Optional

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
    # a template call {{name|...}} / {{name}}; config arrays in prose such as {{0, 1}, {1, 0}} are text on the wiki too
    "{{": re.compile(r"\{\{\s*[^\s{}|\[\]<][^{}|\n]*(?:\||\}\})"),
    # a }} that closes nothing on its line (see _orphan_closes)
    "}}": re.compile(r"\}\}"),
    # an unconverted [[Title]] / [[Title|text]]; nested SQF arrays like [[x, y], [z]] in prose are fine
    "[[": re.compile(r"\[\[[A-Za-z:][^\[\]\n,]*(?:\|[^\[\]\n]+)?\]\]"),
    "''": re.compile(r"(?<![\"'])''(?![\"'])"),
    "{|": re.compile(r"^\{\|", re.M),
    "<nowiki": re.compile(r"<nowiki", re.I),
    "![": re.compile(r"(?<!\\)!\["),  # Markdown image syntax: the converter never means to produce one
}
_FENCED = re.compile(r"^(`{3,}).*?^\1", re.S | re.M)
_INLINE = re.compile(r"(`+)(?!`).+?(?<!`)\1")

ISSUE_LABEL = "parser-report"
ISSUE_TITLE = "Parser report: new problems"
LIST_LIMIT = 60


class Report:
    def __init__(self):
        self.problems: dict[str, dict] = {}

    def add(self, kind: str, title: str, page_kind: str, detail: str = "", note: str = "", where: Optional[dict] = None) -> None:
        page = f"{page_kind}/{title}"
        key = f"{kind}|{page}" + (f"|{detail}" if detail else "")
        # the key stays stable across edits of the page; "where" is only for finding the spot
        self.problems.setdefault(key, {
            "key": key, "kind": kind, "page": page, "url": wiki_url(title), "detail": detail, "note": note,
            **({"where": where} if where else {}),
        })

    def check_page(self, title: str, page_kind: str, rec: dict, md: str, unknown, wikitext: str = "") -> None:
        for name in unknown:
            what, _, ident = name.partition(":")
            needle = re.compile(r"\{\{\s*" + re.escape(ident) if what == "template" else "<" + re.escape(ident), re.I)
            m = needle.search(wikitext)
            where = {"wiki": "%d:%d" % position(wikitext, m.start())} if m else None
            self.add(f"unknown-{what}", title, page_kind, ident, where=where)
        for pattern, offset in leftover_markup(md).items():
            where = {"md": "%d:%d" % position(md, offset), "context": _context(md, offset)}
            src = source_position(wikitext, md, offset)
            if src:
                where["wiki"] = "%d:%d" % src
            self.add("markup", title, page_kind, pattern, where=where)
        if rec["type"] == "topic":  # free-form page: no syntax or parameters to check
            return
        if not rec["syntaxes"]:
            self.add("no-syntax", title, page_kind)
        for i, s in enumerate(rec["syntaxes"], 1):
            for p in s["params"]:
                if not p["name"]:
                    self.add("unnamed-param", title, page_kind, f"syntax {i}: {p['text'][:40]}")
                elif not p["types"] and not p["type"]:
                    name = re.escape(p["name"])
                    # its |pN= line, else the name in the function's header comment
                    m = (re.search(r"(?m)^\|\s*p\d+\s*=\s*(?:\(optional\)\s*)?" + name, wikitext, re.I)
                         or re.search(r"(?<![\w.])" + name + r"(?![\w.])", wikitext))
                    where = {"wiki": "%d:%d" % position(wikitext, m.start())} if m else None
                    self.add("untyped-param", title, page_kind, f"syntax {i}: {p['name']}", where=where)

    def to_json(self, updated) -> dict:
        items = sorted(self.problems.values(), key=lambda p: (KIND_ORDER.index(p["kind"]), p["key"]))
        counts = {k: sum(1 for p in items if p["kind"] == k) for k in KIND_ORDER}
        return {"updated": updated, "counts": counts, "problems": items}


def leftover_markup(md: str) -> dict[str, int]:
    """Leftover markup -> offset of its first occurrence in ``md``."""
    # code is blanked out with spaces, so offsets stay those of the page
    text = _FENCED.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), md)
    text = _INLINE.sub(lambda m: " " * len(m.group(0)), text)
    found = {}
    for name, rx in LEFTOVERS.items():
        for m in rx.finditer(text):
            if name != "}}" or _orphan_close(text, m.start()):
                found[name] = m.start()
                break
    return found


def _orphan_close(text: str, at: int) -> bool:
    """Whether the }} at ``at`` closes fewer than two braces opened earlier on its line."""
    line = text[text.rfind("\n", 0, at) + 1 : at]
    return line.count("{") - line.count("}") < 2


def position(text: str, offset: int) -> tuple[int, int]:
    """1-based line and column of ``offset``."""
    line = text.count("\n", 0, offset) + 1
    return line, offset - (text.rfind("\n", 0, offset) + 1) + 1


def _context(text: str, offset: int) -> str:
    start, end = text.rfind("\n", 0, offset) + 1, text.find("\n", offset)
    line = text[start : end if end != -1 else len(text)]
    col = offset - start
    return (("…" if col > 40 else "") + line[max(0, col - 40) : col + 60] + ("…" if len(line) > col + 60 else "")).strip()


def source_position(wikitext: str, md: str, offset: int) -> Optional[tuple[int, int]]:
    """Where the Markdown at ``offset`` comes from in the wikitext: the first source line that holds the words
    right after it (markup differs between the two, words do not). None if they cannot be found."""
    after = md[offset : offset + 120].split("\n", 1)[0]
    words = re.findall(r"[A-Za-z0-9_]{3,}", after)[:4]
    if not words:
        return None
    rx = re.compile(r"\W+".join(map(re.escape, words)))
    for n, line in enumerate(wikitext.split("\n"), 1):
        m = rx.search(line)
        if m:
            return n, m.start() + 1
    return None


# ---- comparing against the accepted baseline and reporting ------------------------------------

def load_known(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {e["key"] if isinstance(e, dict) else e for e in json.loads(path.read_text(encoding="utf-8"))}


def save_known(path: Path, problems: dict[str, dict]) -> None:
    """One problem per line: its key, and where it was when accepted ("md": line:column in the page's .md,
    "wiki": line:column in the wikitext, "context": the text around it). Only the key is compared."""
    lines = [json.dumps({"key": k, **problems[k].get("where", {})}, ensure_ascii=False) for k in sorted(problems)]
    path.write_text("[\n " + ",\n ".join(lines) + "\n]\n", encoding="utf-8", newline="\n")


def markdown(report: dict, new: list[dict], resolved: list[str], site: str) -> str:
    from .render import page_slug  # local import: render imports this module

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
            where = p.get("where", {})
            spots = [f"{label} {where[k]}" for k, label in (("md", "md"), ("wiki", "wikitext")) if k in where]
            if spots:
                detail += f" at {', '.join(spots)}" + (f" — `{where['context']}`" if where.get("context") else "")
            note = f"\n  ```\n  {p['note']}\n  ```" if p["note"] else ""
            if p["kind"] in ("error", "skipped"):  # no page on the site to link to
                lines.append(f"- [{title}]({p['url']}){detail}{note}")
            else:
                lines.append(f"- [{title}]({site}{kind}/{page_slug(title, kind)}.html) ([wiki]({p['url']})){detail}{note}")
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
    """Keep one permanent "parser-report" issue: reopen it with new problems, close it when they are gone.

    Issue listings lag behind recent changes, so the listing is only used to find the issue's number;
    its state and body are read from the issue itself, which is always current.
    """
    digest = hashlib.sha1("\n".join(sorted(p["key"] for p in new)).encode()).hexdigest()[:12]
    marker = f"<!-- problems:{digest} -->"
    body = md + "\n\n" + marker
    if len(body) > 60000:
        body = body[:60000] + "\n\n…truncated, see report.json\n\n" + marker
    _gh("label", "create", ISSUE_LABEL, "--color", "B60205", "--description", "Automatic parser report", "--force")
    listed = json.loads(_gh("api", f"repos/{{owner}}/{{repo}}/issues?labels={ISSUE_LABEL}&state=all&per_page=100"))
    numbers = [i["number"] for i in listed if "pull_request" not in i]
    issue = json.loads(_gh("api", f"repos/{{owner}}/{{repo}}/issues/{min(numbers)}")) if numbers else None
    is_open = bool(issue) and issue["state"] == "open"

    if not new:
        if is_open:
            _gh("issue", "close", str(issue["number"]), "--comment", "All new problems are gone.")
            print(f"Closed issue #{issue['number']}")
        return
    if issue is None:
        url = _gh("issue", "create", "--title", ISSUE_TITLE, "--label", ISSUE_LABEL, "--body", body).strip()
        print(f"Opened {url}")
        return
    if is_open and marker in (issue["body"] or ""):
        print(f"Issue #{issue['number']} is already up to date")
        return
    _gh("issue", "edit", str(issue["number"]), "--body", body)
    if is_open:
        _gh("issue", "comment", str(issue["number"]), "--body",
            f"The set of new problems changed: now {len(new)}. The description above is up to date.")
        print(f"Updated issue #{issue['number']}")
    else:
        _gh("issue", "reopen", str(issue["number"]), "--comment", f"{len(new)} new problems; see the description.")
        print(f"Reopened issue #{issue['number']}")

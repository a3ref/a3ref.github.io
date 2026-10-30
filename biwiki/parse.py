"""Turn a raw wiki page (``{{RV}}`` template) into a structured record."""
from __future__ import annotations

import html
import re
from datetime import date
from typing import Optional
from urllib.parse import quote

import mwparserfromhell as mw
from mwparserfromhell.nodes import Tag, Template

from . import docblock, typeexpr
from .portrender import PortRenderer
from .wikitext import clean_code, game_name, parse_wikitext, preprocess

WIKI_URL = "https://community.bistudio.com/wiki/"

PARAMS_PER_SYNTAX = 20  # s1 -> p1..p20, s2 -> p21..p40, ...


def wiki_url(title: str, anchor: str = "") -> str:
    url = WIKI_URL + quote(title.replace(" ", "_"), safe="/:()!,'*@$;")
    return url + ("#" + quote(anchor.replace(" ", "_"), safe=":./") if anchor else "")


def display_name(title: str, kind: str) -> str:
    # Function pages are titled "BIS fnc spawnGroup"; scripts call them BIS_fnc_spawnGroup.
    return title.replace(" ", "_") if kind == "functions" else title


def script_name(title: str, kind: str, wikitext: str) -> str:
    """The name as written in scripts. MediaWiki shows "_" in titles as spaces, so the command
    diag_fps is titled "diag fps"; operator pages such as "a != b" keep their spaces."""
    if kind == "functions":
        return title.replace(" ", "_")
    underscored = title.replace(" ", "_")
    visible = re.sub(r"\[\[[^|\]]*\|", "[[", wikitext)  # "[[a_hash_b|#]]" shows "#", not the target
    if " " in title and re.fullmatch(r"\w+", underscored) and re.search(
        rf"^\|\s*s\d+\s*=.*(?<!\w){re.escape(underscored)}(?!\w)", visible, flags=re.M
    ):
        return underscored
    return title


def _name(t: Template) -> str:
    return str(t.name).strip().replace("_", " ")


def _find_rv(code: mw.wikicode.Wikicode) -> Optional[Template]:
    """Pick the Arma 3 ``{{RV}}`` block (pages for older games wrap several in ``{{TabView}}``)."""
    candidates = [t for t in code.filter_templates() if _name(t) == "RV"]
    if not candidates:
        return None
    for t in candidates:
        games = [str(p.value).strip().lower() for p in t.params if re.fullmatch(r"game\d+", str(p.name).strip())]
        if "arma3" in games:
            return t
    return candidates[-1]


def _params(rv: Template) -> dict[str, mw.wikicode.Wikicode]:
    return {str(p.name).strip(): p.value for p in rv.params}


def _numbered(params: dict, prefix: str) -> list[tuple[int, mw.wikicode.Wikicode]]:
    out = []
    for k, v in params.items():
        m = re.fullmatch(prefix + r"(\d+)", k)
        if m and str(v).strip():
            out.append((int(m.group(1)), v))
    return sorted(out, key=lambda x: x[0])


def _text(params: dict, key: str) -> str:
    v = params.get(key)
    return re.sub(r"<!--.*?-->", "", str(v), flags=re.S).strip() if v is not None else ""


def _links(code) -> list[str]:
    out = []
    for link in parse_wikitext(str(code)).filter_wikilinks():
        title = str(link.title).strip().lstrip(":").replace("_", " ")
        if title.lower().startswith(("category:", "file:", "image:")):
            continue
        out.append(title.split("#")[0] or title)
    return list(dict.fromkeys(out))


def _balanced_paren(s: str, start: int) -> int:
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _mask_optional(s: str) -> str:
    """Blank out a "(Optional, default: x)" group, keeping positions, so its ':' is not a separator."""
    m = re.search(r"\((?:O|o)ptional", s)
    if not m:
        return s
    j = _balanced_paren(s, m.start())
    end = j + 1 if j != -1 else len(s)
    return s[: m.start()] + "x" * (end - m.start()) + s[end:]


_SENTENCE_DEFAULT = re.compile(
    r"\s*\(default(?::|\s+is)?\s+([^()\n]+)\)|(?:^|(?<=[.,;])\s+|\s+-\s+)default(?::|\s+is)\s*(?=\S)", re.I)


def _clause_end(s: str, start: int) -> tuple[int, int]:
    """Where the value starting at ``start`` ends: at a ',', ';' or '. ' outside brackets, quotes and code.
    Returns (end of the value, start of the text after it)."""
    depth, quote = 0, ""
    for i in range(start, len(s)):
        c = s[i]
        if quote:
            quote = "" if c == quote else quote
        elif c in "\"'`" and (c != "'" or i == start or not s[i - 1].isalnum()):
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth <= 0 and (c in ",;" or c == "." and (i + 1 == len(s) or s[i + 1].isspace())):
            return i, i + 1
    return len(s), len(s)


def _sentence_default(desc: str) -> tuple[str, Optional[str]]:
    """A default given outside "(Optional, default x)" on the parameter's own line: "... (Default: nil)",
    "... Default: false", "area radius - default: 50". Returns the description without it, and the default.

    Only the default's clause goes: "speed. Default is 150, if you use flares, set it lower" keeps "If you use
    flares, set it lower"."""
    own, nl, more = desc.partition("\n")
    m = _SENTENCE_DEFAULT.search(own)
    if not m:
        return desc, None
    if m.group(1):
        own, value = (own[: m.start()] + own[m.end() :]).strip(), m.group(1)
    else:
        end, after = _clause_end(own, m.end())
        value, before, rest = own[m.end() : end], own[: m.start()].strip(), own[after:].strip()
        if rest and (not before or before.endswith(".")):
            rest = rest[0].upper() + rest[1:]  # the rest starts the sentence the default started
        own = (before + " " + rest).strip()
    return (own + nl + more).strip(), value.strip()


_OPTIONAL_SINCE = re.compile(r"optional\s+(?:since|after|from)\s+(?:Arma\s*3\s+v?)?(\d+\.\d+)\b", re.I)
# a value written alone in "(Optional, x)": number, string, array/code literal, boolean, nil, null or side constant
_VALUE = re.compile(r"-?\d+(?:\.\d+)?|\"[^\"]*\"|'[^']*'|\[[^\[\]]*\]|\{\s*\}|true|false|nil|[a-z]+Null|west|east|"
                    r"independent|resistance|civilian|side(?:Unknown|Logic|Empty|Enemy|Friendly|Ambient)", re.I)


def split_param(plain: str) -> dict:
    """Heuristically split ``name: Type - (Optional, default x) description``."""
    first, _, more = plain.partition("\n")
    name = type_ = desc = ""
    optional, default, optional_since = False, None, None
    lead = re.match(r"^\s*\((?:O|o)ptional\)\s*", first)  # "(optional) defaultValue - anything: ..."
    if lead:
        optional, first = True, first[lead.end():]
    # "expected (Optional, default: nil): ...": the colon inside the parentheses does not end the name
    m = re.match(r"^\s*([^:]{1,60}?)\s*:\s*(.*)$", _mask_optional(first))
    if m and " - " not in m.group(1):
        name, rest = first[m.start(1) : m.end(1)], first[m.start(2) :]
        in_name = re.search(r"\s*(\((?:O|o)ptional.*)$", name)  # "instant (Optional, default false): ..."
        if in_name:
            name, rest = name[: in_name.start()], in_name.group(1) + " " + rest
        type_, sep, desc = rest.partition(" - ")
        opt = re.search(r"\((?:O|o)ptional", rest)
        if opt and (not sep or opt.start() < len(type_)):  # "name: Type (Optional, default x) description"
            type_, desc = rest[: opt.start()], rest[opt.start() :]
        elif not sep:
            type_, desc = "", rest
            # "name: Type" with no description at all
            if len(rest) < 80 and not re.search(r"[(]|\.(\s|$)", rest):
                type_, desc = rest, ""
    else:
        name, _, desc = first.partition(" - ")
    desc = (desc + ("\n" + more if more else "")).strip()

    # Only the parameter's own line: "(Optional, ...)" further down belongs to array elements or modes.
    own = desc.split("\n", 1)[0]
    i = own.find("(Optional")
    if i == -1:
        i = own.find("(optional")
    if i != -1:
        optional = True
        j = _balanced_paren(desc, i)
        inner = desc[i + 1 : j] if j != -1 else desc[i + 1 :]
        # "(Optional since 2.20, default: 0)": the parameter was there before, only optional from then on
        since = _OPTIONAL_SINCE.match(inner)
        if since:
            optional_since = f"arma3 {since.group(1)}"
        dm = re.search(r"default(?:s to|\s+is)?[:\s]+(.*)$", inner, flags=re.S | re.I)
        if dm:
            default = dm.group(1).strip().rstrip(",").strip()
        else:
            # "(Optional, taskNull)": a bare value is the default; words ("current game language") are not
            bare = inner[since.end() if since else len("Optional") :].strip(" ,")
            if _VALUE.fullmatch(bare):
                default = bare
        desc = re.sub(r"^[\s:-]+", "", (desc[:i] + (desc[j + 1 :] if j != -1 else "")).strip(" -\n"))
    if optional and default is None:
        desc, default = _sentence_default(desc)
    return {
        "name": name.strip(),
        "type": type_.strip() or None,
        "optional": optional,
        "default": default,
        "description": desc.strip() or None,
        **({"optional_since": optional_since} if optional_since else {}),
    }


def parse_page(raw: dict, kind: str, r: PortRenderer) -> Optional[dict]:
    title = raw["title"]
    r.page_title = title
    code = parse_wikitext(preprocess(raw["wikitext"]))
    rv = _find_rv(code)
    if rv is None:
        return None
    p = _params(rv)
    name = script_name(title, kind, raw["wikitext"])

    games = [
        {"game": str(v).strip(), "name": game_name(str(v)), "version": _text(p, f"version{n}") or None}
        for n, v in _numbered(p, "game")
    ]

    syntaxes = []
    s_numbers = {n for n, _ in _numbered(p, "s")}
    # Some function pages leave s1 empty but still document the return value.
    rets = {n: v for n, v in _numbered(p, "r") if n in s_numbers or n == 1}
    for n, v in _numbered(p, "r"):
        # an rN without sN is a typo: "|r21=" numbered like the parameters is s2's return value, others are dropped
        # (a stray "|r2=" on a page with one syntax); none makes a syntax of its own
        k = (n - 1) // PARAMS_PER_SYNTAX + 1
        if n not in rets and (n - 1) % PARAMS_PER_SYNTAX == 0 and k in s_numbers and k not in rets:
            rets[k] = v
    indexes = sorted(s_numbers | ({1} if 1 in rets else set()))
    for n in indexes:
        s = p.get(f"s{n}", "")
        params = []
        for pn, pv in _numbered(p, "p"):
            if (n - 1) * PARAMS_PER_SYNTAX < pn <= n * PARAMS_PER_SYNTAX:
                source = re.sub(r"<!--.*?-->|<nowiki\s*/>", "", str(pv), flags=re.S).strip()
                if not source:  # "|p3= <!-- unused -->"
                    continue
                # a table before the parameter's own line (forEach: game versions per argument type) is no part
                # of its name and type; it goes after the description
                table = re.match(r"(?s)(\{\||\{\{\{!\}\}).*?^(\|\}|\{\{!\}\}\})[ \t]*\n?", source, re.M)
                if table:
                    pv = parse_wikitext(source[table.end():])
                    if not str(pv).strip():
                        continue
                md = r.md(pv)  # the text keeps the icons
                # "{{Icon|serverExec|28}} killer: [[Object]]": an icon is no part of the name ("Server execution
                # killer"); records have no field for it per parameter, so it stays only in the text
                pv = parse_wikitext(str(pv))
                for t in [t for t in pv.filter_templates(recursive=False) if _name(t) == "Icon"]:
                    pv.remove(t)
                plain = r.plain_lines(pv)
                if _NO_PARAM.fullmatch(plain):  # "|p1= -" on pages of functions without parameters
                    continue
                item = split_param(plain)
                if item["type"] and _ONE_OF.fullmatch(item["type"]):
                    item["type"] = None  # "group: One of" + a list of types: no type of its own, read the list
                head = type_head(pv, has_name=True)
                item["type_expr"], item["types"] = head_types(head)
                type_md = r.md(head).strip() if _type_after_dash(item, r.plain(head)) else None
                if not item["types"] and not item["type"]:
                    item["type_expr"] = _listed_types(pv) or _table_types(plain) or _trailing_types(pv)
                    item["types"] = typeexpr.names(item["type_expr"])
                item["description"] = _md_desc(md, item, type_md)
                if table:
                    table_md = r.md(source[: table.end()])
                    item["description"] = ((item["description"] or "") + "\n\n" + table_md).strip()
                    md += "\n\n" + table_md
                item["since"] = _text(p, f"p{pn}since") or None
                if "optional_since" in item:  # after since, where a reader looks for it
                    item["optional_since"] = item.pop("optional_since")
                item["text"] = md
                params.append(item)
        ret = rets.get(n, p.get(f"r{n}"))
        # a note placed in the syntax field ({{Feature|obsolete|...}}) is no part of the syntax line
        s_code = parse_wikitext(str(s))
        features = [t for t in s_code.filter_templates(recursive=False) if _name(t) == "Feature"]
        for t in features:
            s_code.remove(t)
        notes = [r.md(str(t)) for t in features]
        # nor are a <span> note ("From Arma 2 v1.00 until Arma 3 v1.54 - see private") and what follows a <br>
        # (version and locality icons per game: addMagazine); they become the note
        for t in [t for t in s_code.filter_tags(recursive=False) if str(t.tag).lower() == "span"]:
            notes.append(r.md(str(t.contents)).strip())
            s_code.remove(t)
        br = next((i for i, n in enumerate(s_code.nodes) if isinstance(n, Tag) and str(n.tag).lower() == "br"), None)
        if br is not None:
            tail = "".join(str(n) for n in s_code.nodes[br + 1 :])
            notes.append(r.md(re.sub(r"\}\}(?=\{\{)", "}} ", tail)).strip())  # icons side by side, not run together
            del s_code.nodes[br:]
        syntax = r.plain(s_code).strip()
        notes = [n for n in notes if n]
        entry = {
            "syntax": syntax,
            **({"note": "\n\n".join(notes)} if notes else {}),
            "since": _text(p, f"s{n}since") or None,
            "effect": _text(p, f"s{n}effect") or None,
            "exec": _text(p, f"s{n}exec") or None,
            "params": params,
            "returns": _returns(ret, r) if ret is not None else None,
        }
        if kind == "commands":
            entry.update(syntax_form(name, syntax, params))
        syntaxes.append(entry)

    examples = []
    for n, x in _numbered(p, "x"):
        xcode = parse_wikitext(str(x))
        snippets = [html.unescape(clean_code(_comment_text(str(t.contents), str(t.tag)))).strip("\n")
                    for t in xcode.filter_tags() if _is_sqf(t) and not t.has("inline") and t.contents]
        text = r.md(x)
        if text.strip():  # placeholder pages have "|x1=" with only a comment
            examples.append({"text": text, "code": snippets})

    notes = _notes(code, r)

    arg = _text(p, "arg").lower() or None
    eff = _text(p, "eff").lower() or None
    server = _text(p, "serverExec").lower()
    a3 = next((g["version"] for g in games if g["game"] == "arma3"), None)
    alias = [l.replace("_", " ") for l in _links(p.get("alias", ""))]
    groups = [r.plain(v) for _, v in _numbered(p, "gr")]
    status, replaced_by = _status(p.get("descr"), groups)

    description, header = _description(p, kind, r)
    filled = _fill_from_docblock(header, name, syntaxes, examples) if header else []
    if header and header["description"] and description:
        prose = [b for b in description.split("\n\n") if b.strip() and not b.lstrip().startswith(">")]
        if not prose:  # only notice boxes besides the header: the header still has the real description
            description = header["description"] + "\n\n" + description
            filled.append("description")

    operators = [s["operator"] for s in syntaxes if s.get("operator")]
    record = {
        "name": name,
        "operator": operators[0] if operators else None,
        "title": title,
        "type": "command" if kind == "commands" else "function",
        "url": wiki_url(title),
        "revid": raw.get("revid"),
        "updated": raw.get("timestamp"),
        "groups": groups,
        "status": status,
        # candidate page titles; render.py keeps those that exist and turns them into names
        "replaced_by": replaced_by,
        "games": games,
        "since": games[0] if games else None,
        "arma3_since": a3,
        "branch": _text(p, "branch") or None,
        "locality": {
            "argument": arg if arg in ("local", "global") else None,
            "effect": eff if eff in ("local", "global") else None,
            "server_exec": server in ("server", "y", "yes", "1", "true"),
        },
        "exec": _text(p, "exec") or None,
        "description": description or ((header or {}).get("description") or ""),
        "syntaxes": syntaxes,
        "examples": examples,
        "multiplayer": r.md(p["mp"]) if _text(p, "mp") else None,
        "problems": r.md(p["pr"]) if _text(p, "pr") else None,
        "aliases": [display_name(a, kind) if a.startswith("BIS ") else a for a in alias],
        "see_also": [display_name(l, "functions") if re.match(r"^\w+ fnc ", l) else l for l in _links(p.get("seealso", ""))],
        "notes": notes,
        "categories": raw.get("categories", []),
    }
    if kind == "functions":
        if header and not description and header["description"]:
            filled.insert(0, "description")
        record["docblock"] = header
        record["filled_from_docblock"] = filled
    return record


_SQF_PARTS = re.compile(r'"(?:[^"]|"")*"?|\'(?:[^\']|\'\')*\'?|//[^\n]*|/\*.*?(?:\*/|$)', re.S)


def _comment_text(code: str, tag: str) -> str:
    """<sqf> code as the wiki shows it: its highlighter parses comments as wikitext, so a ``[[link]]`` or
    ``''emphasis''`` in a comment shows as its text, while the code itself (``[[0]]`` is an array) stays.
    As in MediaWiki, ``[[[`` and ``[<nowiki/>[`` start no link; the raw tag contents go in, before clean_code."""
    if tag.lower() != "sqf":  # <syntaxhighlight> shows its code as written; SQS comments are lines
        return code

    def plain(m: re.Match) -> str:
        part = m.group(0)
        if not part.startswith("/"):  # a string
            return part
        part = re.sub(r"(?<!\[)\[\[(?:[^\[\]|<>{}]*\|)?([^\[\]|<>{}]*)\]\]", r"\1", part)
        return re.sub(r"'''''|'''|''", "", part)

    return _SQF_PARTS.sub(plain, code)


def _is_sqf(tag) -> bool:
    """<sqf>/<sqs> blocks, or <syntaxhighlight lang="sqf">; examples also contain C++ and config code."""
    name = str(tag.tag).lower()
    if name in ("sqf", "sqs"):
        return True
    return name == "syntaxhighlight" and tag.has("lang") and str(tag.get("lang").value).strip().lower() in ("sqf", "sqs")


_LEGACY_NOTES = re.compile(r'(?is)<dl\s+class="?command_description"?\s*>(.*?)(?:</dl>|$)')
_NOTE_TAG = re.compile(r"(?i)<(/?)(dt|dd)\b([^>]*)>")
_MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _notes(code: mw.wikicode.Wikicode, r: PortRenderer) -> list[dict]:
    """Community notes in page order: ``{{Note}}`` templates and the older notes written as raw HTML after
    ``{{RV}}`` (see _legacy_notes). A note given both ways is kept once."""
    text = str(code)
    found: list[tuple[int, dict]] = _legacy_notes(text, r)
    at = 0
    for t in code.filter_templates():
        if _name(t) == "Note" and t.has("text"):
            pos = text.find(str(t), at)
            at = pos + 1 if pos != -1 else at
            found.append((pos if pos != -1 else len(text), _note(t, r)))
    notes: list[dict] = []
    seen: set[str] = set()
    for _, note in sorted(found, key=lambda x: x[0]):
        key = re.sub(r"\s+", " ", note["text"]).strip()
        if key and key not in seen:
            seen.add(key)
            notes.append(note)
    return notes


def _note(t: Template, r: PortRenderer) -> dict:
    """A ``{{Note|user=...|timestamp=...|text=...}}``: user, date (ISO 8601 UTC or "") and the text's Markdown."""
    def get(name: str) -> str:
        return str(t.get(name).value).strip() if t.has(name) else ""

    ts = get("timestamp")
    when = ""
    if re.fullmatch(r"\d{12,14}", ts):
        ts = ts.ljust(14, "0")
        when = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"
    return {"user": get("user"), "date": when, "text": r.md(t.get("text").value) if t.has("text") else ""}


def _legacy_notes(text: str, r: PortRenderer) -> list[tuple[int, dict]]:
    """Notes from before the ``{{Note}}`` template, as the wiki still shows them on about 200 pages::

        <dl class="command_description">
        <dt></dt>
        <dd class="notedate">Posted on 2016-12-03 - 21:35 (UTC)</dd>
        <dt class="note">[[User:Killzone_Kid|Killzone_Kid]]</dt>
        <dd class="note">text ...</dd>
        </dl>

    The tags are often left unclosed (``<dt><dt>`` as a spacer, a ``<dd class="note">`` ended by the next
    ``<dt>``); each element runs to the next tag. Returns (offset in the page, note) pairs; the note has the
    fields of ``_note``."""
    out: list[tuple[int, dict]] = []
    for block in _LEGACY_NOTES.finditer(text):
        body = block.group(1)
        tags = list(_NOTE_TAG.finditer(body))
        posted = ""
        for i, t in enumerate(tags):
            if t.group(1):  # a closing tag ends the element; nothing stands between it and the next tag
                continue
            content = body[t.end() : tags[i + 1].start() if i + 1 < len(tags) else len(body)].strip()
            cls = re.search(r"class\s*=\s*\"?([\w-]+)", t.group(3))
            kind = (t.group(2).lower(), cls.group(1).lower() if cls else "")
            if kind == ("dd", "notedate"):
                posted = _legacy_date(content)
            elif kind == ("dt", "note"):
                user = re.search(r"\[\[\s*User\s*:\s*([^|\]]+)", content, re.I)
                out.append((block.start(1) + t.start(),
                            {"user": user.group(1).strip() if user else r.plain(content).strip(), "date": posted,
                             "text": ""}))
                posted = ""
            elif kind == ("dd", "note") and content:
                if not out or out[-1][1]["text"]:  # a note without an author line
                    out.append((block.start(1) + t.start(), {"user": "", "date": posted, "text": ""}))
                    posted = ""
                out[-1][1]["text"] = r.md(content)
    return [x for x in out if x[1]["text"]]


def _legacy_date(text: str) -> str:
    """The day of "Posted on 2016-12-03 - 21:35 (UTC)", "Posted on 12:07, 20 January 2007 (CET)",
    "Posted: Sep 10 2014" as ISO 8601; with the time only when it is given in UTC, as {{Note}}'s timestamps
    are. Empty if there is no date."""
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        month, year = _MONTH.search(text), re.search(r"(?<!\d)(\d{4})(?!\d)", text)
        day = re.search(r"(?<![\d:])(\d{1,2})(?:st|nd|rd|th)?(?![\d:])", text)
        if not (month and year and day):
            return ""
        y, mo, d = int(year.group(1)), _MONTHS.index(month.group(1).lower()) + 1, int(day.group(1))
    try:
        day_iso = date(y, mo, d).isoformat()
    except ValueError:
        return ""
    tm = re.search(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])", text)
    if tm and re.search(r"\bUTC\b", text):
        return f"{day_iso}T{int(tm.group(1)):02d}:{tm.group(2)}:00Z"
    return day_iso


def _description(p: dict, kind: str, r: PortRenderer) -> tuple[str, Optional[dict]]:
    """The written description, and the function header comment if the page shows one instead.

    Placeholder function pages put the header of the .sqf file in a <pre>/<sqf> block; it is parsed
    separately (see docblock.py) and removed from the description so it is not shown twice.
    """
    descr = p.get("descr")
    if descr is None:
        return "", None
    header = None
    if kind == "functions":
        code = parse_wikitext(str(descr))
        for tag in code.filter_tags():
            if str(tag.tag).lower() in ("pre", "sqf", "syntaxhighlight", "nowiki") and tag.contents:
                body = docblock.find(html.unescape(str(tag.contents)))
                if body is not None:
                    header = docblock.parse(body)
                    code.remove(tag)
                    break
        if header:
            text = re.sub(r"<!--.*?-->", "", str(code), flags=re.S)
            return r.md(text), header
    return r.md(descr), None


def _fill_from_docblock(header: dict, name: str, syntaxes: list[dict], examples: list[dict]) -> list[str]:
    """Fill what the wiki page leaves empty from the function header; returns the names of filled fields."""
    filled = []
    if header["params"] and not any(s["params"] for s in syntaxes):
        if not syntaxes:
            syntaxes.append({"syntax": "", "since": None, "effect": None, "exec": None, "params": [], "returns": None})
        syntaxes[0]["params"] = [_header_param(hp) for hp in header["params"]]
        filled.append("params")
        if not syntaxes[0]["syntax"]:
            syntaxes[0]["syntax"] = header["syntax"] or _infer_syntax(name, header["params"])
            syntaxes[0]["inferred"] = not header["syntax"]
            filled.append("syntax")
    if header["returns"]:
        if not syntaxes:
            syntaxes.append({"syntax": header["syntax"] or f"call {name}", "since": None, "effect": None, "exec": None,
                             "params": [], "returns": None, "inferred": not header["syntax"]})
            filled.append("syntax")
        ret = syntaxes[0]["returns"]
        if not ret or not ret["text"].strip():
            types = header["returns"]["types"]
            # "BOOL - true if added": what follows the type on the first line, and the lines below
            first, nl, more = header["returns"]["text"].partition("\n")
            head, sep, rest = first.partition(" - ")
            desc = (rest + nl + more).strip() if sep and docblock.types_in(head) else ""
            syntaxes[0]["returns"] = {"type": ", ".join(types) or None, "types": types,
                                      "type_expr": header["returns"]["type_expr"], "description": desc or None,
                                      "text": header["returns"]["text"], "source": "docblock"}
            filled.append("returns")
    if header["examples"] and not examples:
        examples.extend({"text": f"```sqf\n{x}\n```", "code": [x]} for x in header["examples"])
        filled.append("examples")
    return filled


def _header_param(hp: dict) -> dict:
    label = f"{hp['index']}: " if hp["index"] is not None else ""
    return {
        "name": hp["name"] or (f"param{hp['index']}" if hp["index"] is not None else "arg"),
        "type": ", ".join(hp["types"]) or None,
        "types": hp["types"],
        "type_expr": hp["type_expr"],
        "optional": hp["optional"],
        "default": hp["default"],
        "description": hp["description"],
        "since": None,
        "text": label + hp["text"],
        "source": "docblock",
    }


def _infer_syntax(name: str, params: list[dict]) -> str:
    names = [p["name"] or (f"param{p['index']}" if p["index"] is not None else "arg") for p in params]
    if len(params) == 1 and params[0]["index"] is None:
        return f"{names[0]} call {name}"
    return f"[{', '.join(names)}] call {name}"


def parse_topic(raw: dict, r: PortRenderer) -> dict:
    """A free-form concept page (data type, event handler list, ...): Markdown plus its sections."""
    title = raw["title"]
    r.page_title = title
    # a string, not Wikicode: the port needs no mwparserfromhell tree, so no parse of the whole page is spent on it
    md = r.md(preprocess(raw["wikitext"]))
    return {
        "name": title,
        "title": title,
        "type": "topic",
        "url": wiki_url(title),
        "revid": raw.get("revid"),
        "updated": raw.get("timestamp"),
        "aliases": raw.get("redirects", []),
        "markdown": md,
        "sections": split_sections(md),
        "categories": raw.get("categories", []),
    }


def split_sections(md: str) -> list[dict]:
    """Split Markdown at headings (outside code fences); text before the first heading is the intro."""
    sections = [{"heading": None, "level": 1, "markdown": []}]
    fence = None
    for line in md.split("\n"):
        m = re.match(r"^(`{3,})", line)
        if m:
            fence = None if fence and m.group(1).startswith(fence) else (fence or m.group(1))
        h = None if fence else re.match(r"^(#{2,6}) (.+)$", line)
        if h:
            sections.append({"heading": h.group(2).strip(), "level": len(h.group(1)), "markdown": []})
        else:
            sections[-1]["markdown"].append(line)
    out = []
    for s in sections:
        text = "\n".join(s["markdown"]).strip()
        if s["heading"] or text:
            out.append({"heading": s["heading"], "level": s["level"], "markdown": text})
    return out


def _md_desc(md: str, item: dict, type_md: Optional[str] = None) -> Optional[str]:
    """The Markdown variant of the description: everything after the ' - ' type separator.

    ``type_md``: the rendered type when the first line is ``name - Type: description`` or
    ``name - Type - description``; the description is what follows it.
    """
    if not item["description"]:
        return None
    first, _, more = md.partition("\n")
    opt = re.search(r"\((?:O|o)ptional", first)
    after_name = first.find(item["name"]) + len(item["name"]) if item["name"] and item["name"] in first else 0
    at = first.find(type_md, after_name) if type_md else -1  # after the name: "databaseArray - Array: ..."
    if at != -1:
        head = re.sub(r"^[\s:-]+", "", first[at + len(type_md) :])
    elif " - " in first:
        head = first.split(" - ", 1)[1]
    elif opt and item["type"]:
        head = first[opt.start() :]
    else:
        head = first.split(":", 1)[1] if item["name"] and ":" in first else first
    desc = (head + ("\n" + more if more else "")).strip()
    if item["optional"]:
        i = desc.lower().find("(optional")
        j = _balanced_paren(desc, i) if i != -1 else -1
        if i != -1 and j != -1:
            desc = re.sub(r"^[\s:-]+", "", (desc[:i] + desc[j + 1 :]).strip(" -\n"))
        desc = _sentence_default(desc)[0]
    return desc or None


def _returns(code, r: PortRenderer) -> dict:
    md = r.md(code)
    plain = r.plain(code)
    # only a " - " on the first line ends the type: "[[Array]] with [a, b]\n* a: [[Number]] - ..." is no type "Array
    # with [a, b] a: Number"
    first, nl, more = plain.partition("\n")
    src_first, _, src_more = str(code).strip().partition("\n")
    if src_more.strip() and all(src_first.count(a) == src_first.count(b) for a, b in (("{{", "}}"), ("[[", "]]"), ("<", ">"))):
        # plain text may join a list to the first line ("where: - visionMode: ..."): split the source instead
        first, nl, more = r.plain(src_first), "\n", r.plain(src_more)
    type_, sep, desc = first.partition(" - ")
    if re.match(r"\s*[-*]\s*\S", first):  # the value starts with a list ("* spawn: [[Script Handle]]"): no type line
        type_, sep, desc = None, "", plain
    elif sep:
        desc += nl + more
    elif len(plain) < 60:
        type_, desc = first, more  # "[[Boolean]]"
    else:
        type_, desc = None, more  # a sentence (still in the text); the type is found below, if it starts it
    head = type_head(code, has_name=False)
    expr, types = head_types(head)  # an unlinked "Nothing" is a type too
    if not expr:
        expr = _listed_types(code, from_first=True)
        types = types or typeexpr.names(expr)
    type_ = type_.strip() if type_ is not None else None
    end = _type_prefix(first, types)
    if not sep and end:
        # "Number in range 0..1, -1 in case of error": the type is the leading run of type names
        type_, desc = first[:end].strip(), (first[end:].lstrip(" ,;:") + nl + more).strip()
    elif sep and end and re.match(r"\s*(?:with|in format)\b", first[end:]):
        # "Array with [a, b] - where ...": the format is description
        type_, desc = first[:end].strip(), first[end:].strip() + nl + more
    return {
        "type": type_,
        "types": types,
        "type_expr": expr,
        "description": desc.strip() or None,
        "text": md,
    }


_TYPE_NAMES = sorted(set(typeexpr.TYPE_WORDS.values()), key=len, reverse=True)
_TYPE_JOINERS = re.compile(r"\s*(?:,|/|(?:and/or|and|or|of|in format|format|an?|the|empty|non-empty)\b)", re.I)


def _type_prefix(line: str, types: list[str]) -> int:
    """Where the type names at the start of a plain-text line end, with the words joining them ("Array of
    Numbers", "Number, String, Boolean or Array", "Color (RGBA)"); 0 if the line does not start with one.
    Known are the linked types, the data type names and the unlinked words the wiki uses as types. When a
    joining word follows ("Array of created Objects", "Array of units in ..."), the type goes on in words that
    are no type name; 0 then too."""
    known = {t for t in types if t[:1].isupper()} | set(_TYPE_NAMES)
    names = "|".join(re.escape(n) + (f"|{re.escape(n[:-1])}ies" if n.endswith("y") else "")
                     for n in sorted(known, key=len, reverse=True))
    words = "|".join(sorted(typeexpr.WIKI_WORDS, key=len, reverse=True))
    name = re.compile(rf"\s*(?:(?:{names})|(?i:{words}))s?(?!\w)(?:\s*\([A-Z0-9]+\))?")
    pos = end = 0
    while True:
        m = name.match(line, pos)
        if m:
            pos = end = m.end()
            continue
        m = _TYPE_JOINERS.match(line, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
    if end and re.match(r"\s*(?:of|or|and)\b", line[end:], re.I):
        return 0
    return end


def _mask_links(s: str) -> str:
    """Blank out [[links]] so ':' and ' - ' inside them are not taken for separators."""
    return re.sub(r"\[\[.*?\]\]", lambda m: "x" * len(m.group(0)), s)


def type_head(code, has_name: bool) -> str:
    """Wikitext of the type part of the first line.

    ``name: [[Array]] of [[String]]s - description`` and ``name - [[Array]]: description`` both give
    ``[[Array]] of [[String]]s`` / ``[[Array]]``; in ``name - description`` the dash form has no type.
    """
    first = str(code).strip().split("\n", 1)[0]
    if has_name:
        skeleton = _mask_optional(first)
        masked = _mask_links(skeleton)
        colon, dash = masked.find(":"), masked.find(" - ")
        rest = first[dash + 3 :] if dash != -1 else ""
        tokens = typeexpr.wiki_tokens(rest) if rest else []
        if (dash != -1 and (colon == -1 or dash < colon) and "[[" not in first[:dash]
                and tokens and tokens[0].kind == "type"):
            first = rest
        elif colon != -1 and ":" in skeleton.split("[[", 1)[0]:
            # "position: - [[Object]] ...", "'''text:''': [[String]] ..."
            first = re.sub(r"^[\s']*:?\s*(?:-\s+)?", "", first[colon + 1 :])
        elif named := re.match(r"^\s*(?:'''|'')?\w+(?:'''|'')?\s+(?=\[\[)", first):
            first = first[named.end() :]  # "oldUnit [[Object]] - old, dead unit"
    head = re.split(r" - |\((?:O|o)ptional", first, maxsplit=1)[0]
    # "name - [[Array]]: description"; a return value's colon is part of the type ("[[Array]]: [[Number]]s")
    colon = _mask_links(head).find(":") if has_name else -1
    return head[:colon] if colon != -1 and typeexpr.of_wikitext(head[:colon]) else head


def head_types(head) -> tuple[Optional[str], list[str]]:
    """The type expression of a type part (see type_head) and the data types in its type position:
    ``[[Array]] of [[String]]s`` -> Array, String; links in notes and prose after it ("([[while]])",
    "[[typeOf]] to get ...") are none. When no type can be read (broken markup such as "[Array]] format
    [[Position]]"), the types are those linked in it."""
    expr, types = typeexpr.wikitext_types(head)
    if not expr:
        links = (typeexpr.link_type(link) for link in parse_wikitext(str(head)).filter_wikilinks())
        types = list(dict.fromkeys(t for t in links if t))
    return expr, types


_ONE_OF = re.compile(r"(?:can be\s+)?one of(?:\s+the following)?\s*:?", re.I)
_NO_PARAM = re.compile(r"\s*(-|none|nothing|n/a)\.?\s*", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:\*(?![*:#])|<br\s*/?>)\s*(.*)$")


def _listed_types(code, from_first: bool = False) -> Optional[str]:
    """Types given as a list below an untyped first line, one alternative per item::

        shadow: (Optional, default 0)
        * [[Number]]: ...
        ** '''0:''' no shadow
        * [[Boolean]]: ...

    Only top-level items that start with a type count; items about values ("* "SET" - ...") do not.
    ``from_first``: the list may start on the first line (return values have no name line).
    """
    exprs = []
    for line in str(code).strip().split("\n")[0 if from_first else 1 :]:
        m = _LIST_ITEM.match(line)
        if m:
            exprs.append(typeexpr.of_wikitext(m.group(1)))
    return typeexpr.union([e for e in exprs if e])


def _table_types(plain: str) -> Optional[str]:
    """Types listed in a "Possible Type" table (operator pages such as ``a == b``): its column or its row."""
    rows = [[c.strip() for c in line.strip().strip("|").split(" | ")] for line in plain.split("\n")
            if line.startswith("|") and not line.startswith("|---")]
    label = re.compile(r"(possible )?types?", re.I)
    cells: list[str] = []
    if rows and any(label.fullmatch(c) for c in rows[0]):
        col = next(i for i, c in enumerate(rows[0]) if label.fullmatch(c))
        cells = [r[col] for r in rows[1:] if col < len(r)]
    else:
        cells = next((r[1:] for r in rows if r and label.fullmatch(r[0])), [])
    return typeexpr.union([c for c in cells if c and re.fullmatch(r"[A-Z][\w ]*", c)])


_TRAILING_TYPES = re.compile(
    r",\s*((?:\[\[[^\[\]|]+(?:\|[^\[\]]+)?\]\])(?:\s*(?:'''or'''|''or''|or|,|/)\s*\[\[[^\[\]|]+(?:\|[^\[\]]+)?\]\])*)\s*\.?\s*$")


def _trailing_types(code) -> Optional[str]:
    """Types after the description: ``param1 - vector starting point, [[Position]] '''or''' [[Object]]``.
    Only when every link there is a data type."""
    first = str(code).strip().split("\n", 1)[0]
    m = _TRAILING_TYPES.search(first)
    if not m:
        return None
    links = parse_wikitext(m.group(1)).filter_wikilinks()
    if not links or not all(typeexpr.link_type(link) for link in links):
        return None
    return typeexpr.of_wikitext(m.group(1).replace("'''", "").replace("''", ""))


def _type_after_dash(item: dict, head_plain: str) -> bool:
    """``name - Type: description``, ``name - Type - description`` and ``name: Color (RGBA)``: split_param read
    the type as the start of the description; move it to ``type``. Returns whether it did, so the Markdown
    description is cut too."""
    desc = item["description"] or ""
    if item["type"] or not item["type_expr"] or not head_plain or not desc.startswith(head_plain):
        return False
    if re.search(r"\.(\s|$)", head_plain):  # "Object the logic. Possible setVariable parameters": prose
        return False
    item["type"] = head_plain
    item["description"] = desc[len(head_plain) :].lstrip(" :-\n") or None
    return True


def syntax_form(title: str, syntax: str, params: list[dict]) -> dict:
    """Shape of a command syntax: nullary ``time``, unary ``alive unit``, binary ``unit setPos pos``.

    Operator pages are titled like "a != b"; the operator itself is what sits between the operands.
    """
    op = title
    m = re.fullmatch(r"(?:a )?(.+?)(?: [ab])?", title)  # "a != b", "! a"
    if m and not re.fullmatch(r"\w+", title):
        op = m.group(1)
    rx = rf"(?<![\w]){re.escape(op)}(?![\w])" if re.fullmatch(r"\w+", op) else re.escape(op)
    hit = re.search(rx, syntax)
    parts = syntax.split()
    if hit:
        left, right = syntax[: hit.start()].strip(), syntax[hit.end() :].strip()
        symbol = op
    elif not re.fullmatch(r"\w+", title) and len(parts) in (2, 3):
        # operators titled in words: "a greater b" is "a > b", "config greater greater name" is "config >> name"
        left, symbol, right = (parts if len(parts) == 3 else ["", *parts])
    else:
        return {"form": None, "operator": None, "left": None, "right": None}
    form = "binary" if left and right else "unary" if right else "nullary" if not left else None
    by_name = {p["name"]: p for p in params if p["name"]}

    def operand(text: str):
        if not text:
            return None
        if text.startswith("["):
            return {"text": text, "types": ["Array"]}
        p = by_name.get(text)
        return {"text": text, "types": p["types"] if p else []}

    operator = None if re.fullmatch(r"\w+", title) else symbol
    return {"form": form, "operator": operator, "left": operand(left), "right": operand(right)}


_DEPRECATION = re.compile(r"\b(deprecated|obsolete)\b", re.I)


def _status(descr, groups: list[str]) -> tuple[str, list[str]]:
    """"broken" (the wiki's Broken Commands/Functions group), "deprecated" (an obsolete/deprecation box), or "ok".

    Free text such as "does not work on vehicles" is deliberately not used: it is about limits, not deprecation.
    Pages linked from the deprecation box are returned as candidate replacements.
    """
    replaced: list[str] = []
    deprecated = False
    if descr is not None:
        for t in parse_wikitext(str(descr)).filter_templates():
            if _name(t) != "Feature" or not t.params:
                continue
            ftype = str(t.params[0].value).strip().lower()
            body = " ".join(str(x.value) for x in t.params[1:])
            if ftype == "obsolete" or _DEPRECATION.search(body):
                deprecated = True
                replaced += [l for l in _links(body) if l not in replaced]
    if any(g.lower().startswith("broken") for g in groups):
        return "broken", replaced
    return ("deprecated" if deprecated else "ok"), replaced

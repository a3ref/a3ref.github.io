"""Turn a raw wiki page (``{{RV}}`` template) into a structured record."""
from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import quote

import mwparserfromhell as mw
from mwparserfromhell.nodes import Template

from .wikitext import Renderer, clean_code, game_name, parse_note, parse_wikitext, preprocess

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


def split_param(plain: str) -> dict:
    """Heuristically split ``name: Type - (Optional, default x) description``."""
    first, _, more = plain.partition("\n")
    name = type_ = desc = ""
    m = re.match(r"^\s*([^:]{1,60}?)\s*:\s*(.*)$", first)
    if m and " - " not in m.group(1):
        name, rest = m.group(1), m.group(2)
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

    optional, default = False, None
    i = desc.find("(Optional")
    if i == -1:
        i = desc.find("(optional")
    if i != -1:
        optional = True
        j = _balanced_paren(desc, i)
        inner = desc[i + 1 : j] if j != -1 else desc[i + 1 :]
        dm = re.search(r"default(?:s to)?[:\s]+(.*)$", inner, flags=re.S | re.I)
        if dm:
            default = dm.group(1).strip().rstrip(",").strip()
        desc = (desc[:i] + (desc[j + 1 :] if j != -1 else "")).strip(" -\n")
    return {
        "name": name.strip(),
        "type": type_.strip() or None,
        "optional": optional,
        "default": default,
        "description": desc.strip() or None,
    }


def parse_page(raw: dict, kind: str, r: Renderer) -> Optional[dict]:
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
    # Some function pages leave s1 empty but still document the return value.
    indexes = sorted({n for n, _ in _numbered(p, "s")} | {n for n, _ in _numbered(p, "r")})
    for n in indexes:
        s = p.get(f"s{n}", "")
        params = []
        for pn, pv in _numbered(p, "p"):
            if (n - 1) * PARAMS_PER_SYNTAX < pn <= n * PARAMS_PER_SYNTAX:
                md = r.md(pv)
                item = split_param(r.plain_lines(pv))
                item["types"] = type_links(pv, has_name=True)
                item["description"] = _md_desc(md, item)
                item["since"] = _text(p, f"p{pn}since") or None
                item["text"] = md
                params.append(item)
        ret = p.get(f"r{n}")
        syntax = r.plain(s)
        entry = {
            "syntax": syntax,
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
        snippets = [html.unescape(clean_code(str(t.contents))).strip("\n") for t in xcode.filter_tags() if str(t.tag).lower() in ("sqf", "sqs", "syntaxhighlight") and not t.has("inline") and t.contents]
        examples.append({"text": r.md(x), "code": snippets})

    notes = []
    for t in code.filter_templates():
        if _name(t) == "Note" and t.has("text"):
            notes.append(parse_note(t, r))

    arg = _text(p, "arg").lower() or None
    eff = _text(p, "eff").lower() or None
    server = _text(p, "serverExec").lower()
    a3 = next((g["version"] for g in games if g["game"] == "arma3"), None)
    alias = [l.replace("_", " ") for l in _links(p.get("alias", ""))]
    groups = [r.plain(v) for _, v in _numbered(p, "gr")]
    status, replaced_by = _status(p.get("descr"), groups)

    operators = [s["operator"] for s in syntaxes if s.get("operator")]
    return {
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
        "description": r.md(p["descr"]) if "descr" in p else "",
        "syntaxes": syntaxes,
        "examples": examples,
        "multiplayer": r.md(p["mp"]) if _text(p, "mp") else None,
        "problems": r.md(p["pr"]) if _text(p, "pr") else None,
        "aliases": [display_name(a, kind) if a.startswith("BIS ") else a for a in alias],
        "see_also": [display_name(l, "functions") if re.match(r"^\w+ fnc ", l) else l for l in _links(p.get("seealso", ""))],
        "notes": notes,
        "categories": raw.get("categories", []),
    }


def parse_topic(raw: dict, r: Renderer) -> dict:
    """A free-form concept page (data type, event handler list, ...): Markdown plus its sections."""
    title = raw["title"]
    r.page_title = title
    md = r.md(parse_wikitext(preprocess(raw["wikitext"])))
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


def _md_desc(md: str, item: dict) -> Optional[str]:
    """The Markdown variant of the description: everything after the ' - ' type separator."""
    if not item["description"]:
        return None
    first, _, more = md.partition("\n")
    opt = re.search(r"\((?:O|o)ptional", first)
    if " - " in first:
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
            desc = (desc[:i] + desc[j + 1 :]).strip(" -\n")
    return desc or None


def _returns(code, r: Renderer) -> dict:
    md = r.md(code)
    plain = r.plain(code)
    type_, sep, desc = plain.partition(" - ")
    return {
        "type": type_.strip() if sep or len(plain) < 60 else None,
        "types": type_links(code, has_name=False),
        "description": desc.strip() or None,
        "text": md,
    }


def type_links(code, has_name: bool) -> list[str]:
    """Data types linked in the type part of ``name: [[Array]] of [[String]]s - description``.

    A link with an anchor is named by its text (``[[Position#PositionAGL|PositionAGL]]`` -> PositionAGL).
    """
    first = str(code).strip().split("\n", 1)[0]
    if has_name:
        first = first.split(":", 1)[1] if ":" in first.split("[[", 1)[0] else first
    head = re.split(r" - |\((?:O|o)ptional", first, maxsplit=1)[0]
    out = []
    for link in parse_wikitext(head).filter_wikilinks():
        target = str(link.title).strip().lstrip(":").replace("_", " ")
        if target.lower().startswith(("category:", "file:", "image:")):
            continue
        name = str(link.text).strip() if link.text is not None and "#" in target else target.split("#")[0]
        if name and name not in out:
            out.append(name)
    return out


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

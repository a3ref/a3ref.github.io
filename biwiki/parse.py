"""Turn a raw wiki page (``{{RV}}`` template) into a structured record."""
from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import quote

import mwparserfromhell as mw
from mwparserfromhell.nodes import Template

from . import docblock, typeexpr
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


def _mask_optional(s: str) -> str:
    """Blank out a "(Optional, default: x)" group, keeping positions, so its ':' is not a separator."""
    m = re.search(r"\((?:O|o)ptional", s)
    if not m:
        return s
    j = _balanced_paren(s, m.start())
    end = j + 1 if j != -1 else len(s)
    return s[: m.start()] + "x" * (end - m.start()) + s[end:]


_SENTENCE_DEFAULT = re.compile(
    r"\s*\(default(?::|\s+is)?\s+([^()\n]+)\)|(?:^|(?<=[.,;])\s+|\s+-\s+)default(?::|\s+is)\s*([^\n]+?)\.?\s*$", re.I)


def _sentence_default(desc: str) -> tuple[str, Optional[str]]:
    """A default given outside "(Optional, default x)" on the parameter's own line: "... (Default: nil)",
    "... Default: false", "area radius - default: 50". Returns the description without it, and the default."""
    own, nl, more = desc.partition("\n")
    m = _SENTENCE_DEFAULT.search(own)
    if not m:
        return desc, None
    own = (own[: m.start()] + own[m.end() :]).strip()
    return (own + nl + more).strip(), (m.group(1) or m.group(2)).strip()


def split_param(plain: str) -> dict:
    """Heuristically split ``name: Type - (Optional, default x) description``."""
    first, _, more = plain.partition("\n")
    name = type_ = desc = ""
    optional, default = False, None
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
        dm = re.search(r"default(?:s to|\s+is)?[:\s]+(.*)$", inner, flags=re.S | re.I)
        if dm:
            default = dm.group(1).strip().rstrip(",").strip()
        desc = re.sub(r"^[\s:-]+", "", (desc[:i] + (desc[j + 1 :] if j != -1 else "")).strip(" -\n"))
    if optional and default is None:
        desc, default = _sentence_default(desc)
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
                plain = r.plain_lines(pv)
                if _NO_PARAM.fullmatch(plain):  # "|p1= -" on pages of functions without parameters
                    continue
                md = r.md(pv)
                item = split_param(plain)
                head = type_head(pv, has_name=True)
                item["types"] = type_links(head)
                item["type_expr"] = typeexpr.of_wikitext(head)
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
                item["text"] = md
                params.append(item)
        ret = p.get(f"r{n}")
        # a note placed in the syntax field ({{Feature|obsolete|...}}) is no part of the syntax line
        s_code = parse_wikitext(str(s))
        features = [t for t in s_code.filter_templates(recursive=False) if _name(t) == "Feature"]
        for t in features:
            s_code.remove(t)
        syntax = r.plain(s_code)
        entry = {
            "syntax": syntax,
            **({"note": "\n\n".join(r.md(str(t)) for t in features)} if features else {}),
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
        snippets = [html.unescape(clean_code(str(t.contents))).strip("\n") for t in xcode.filter_tags()
                    if _is_sqf(t) and not t.has("inline") and t.contents]
        text = r.md(x)
        if text.strip():  # placeholder pages have "|x1=" with only a comment
            examples.append({"text": text, "code": snippets})

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


def _is_sqf(tag) -> bool:
    """<sqf>/<sqs> blocks, or <syntaxhighlight lang="sqf">; examples also contain C++ and config code."""
    name = str(tag.tag).lower()
    if name in ("sqf", "sqs"):
        return True
    return name == "syntaxhighlight" and tag.has("lang") and str(tag.get("lang").value).strip().lower() in ("sqf", "sqs")


def _description(p: dict, kind: str, r: Renderer) -> tuple[str, Optional[dict]]:
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
            syntaxes[0]["returns"] = {"type": ", ".join(types) or None, "types": types,
                                      "type_expr": header["returns"]["type_expr"], "description": None,
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


def _returns(code, r: Renderer) -> dict:
    md = r.md(code)
    plain = r.plain(code)
    type_, sep, desc = plain.partition(" - ")
    head = type_head(code, has_name=False)
    types, expr = type_links(head), typeexpr.of_wikitext(head)
    if not expr:
        expr = _listed_types(code, from_first=True)
        types = types or typeexpr.names(expr)
    return {
        "type": type_.strip() if sep or len(plain) < 60 else None,
        "types": types,
        "type_expr": expr,
        "description": desc.strip() or None,
        "text": md,
    }


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


def type_links(head) -> list[str]:
    """Data types linked in a type part (see type_head): ``[[Array]] of [[String]]s`` -> Array, String.

    A link with an anchor is named by its text (``[[Position#PositionAGL|PositionAGL]]`` -> PositionAGL).
    """
    out = []
    for link in parse_wikitext(str(head)).filter_wikilinks():
        name = typeexpr.link_type(link)
        if name and name not in out:
            out.append(name)
    return out


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

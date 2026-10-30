"""The JSON form of command and function records (format 2, see schema.json and "JSON record" in README.md).

``parse.parse_page`` gives every field every time, which the Markdown and HTML writers rely on. The JSON pages and
bundles leave out what a reader can rebuild from the rest (derivable categories, a parameter text that only joins
name, type and description, type lists that ``type_expr`` already names, ...) and every empty optional value, so a
record costs an agent fewer tokens. Only what is written to ``.json`` passes through here; the Markdown and HTML are
untouched. Topic records are written as they are.
"""
from __future__ import annotations

import re
from typing import Any

from . import typeexpr

# Always present, even when empty or null: the change feed reads name, title, type, url, revid and updated from every
# bundle in the data repository's history, and a record without description or syntaxes would read as broken.
RECORD_CORE = ("name", "title", "type", "url", "revid", "updated", "groups", "status", "description", "syntaxes")
SYNTAX_CORE = ("syntax", "params", "returns")
PARAM_CORE = ("name",)
DOCBLOCK_KEEP = ("text", "author", "meta")
KIND_LABEL = {"command": "Scripting Commands", "function": "Functions"}
# category names that spell a game differently from the game's name in ``games``
CATEGORY_GAME_NAME = {"arma1": "ArmA: Armed Assault"}
BRANCH_CATEGORY = {"diag": "Diagnostic", "prof": "Profiling", "dev": "Development"}
SERVER_VALUES = ("server", "y", "yes", "1", "true")  # as parse.parse_page reads the page's serverExec


def branches(value: str | None) -> list[str]:
    """``"diag prof"`` -> ``["diag", "prof"]``: the wiki writes several builds into one field."""
    return [b for b in re.split(r"[\s,/]+", (value or "").strip().lower()) if b]


def since(value: str | None) -> str | None:
    """Game codes are lower case everywhere else ("Arma3 2.08" -> "arma3 2.08")."""
    if not value:
        return value
    game, sep, rest = value.strip().partition(" ")
    return game.lower() + sep + rest


def param_text(item: dict) -> str:
    """The text a parameter's ``text`` is left out for: ``name: type - description``."""
    out = item["name"] + (f": {item['type']}" if item.get("type") else "")
    return out + (f" - {item['description']}" if item.get("description") else "")


def returns_text(item: dict) -> str:
    """The text a return value's ``text`` is left out for: ``type - description``."""
    return (item.get("type") or "") + (f" - {item['description']}" if item.get("description") else "")


def example_text(code: list[str]) -> str:
    """The text an example's ``text`` is left out for: its code blocks, fenced as SQF, one blank line apart."""
    return "\n\n".join(f"```sqf\n{c}\n```" for c in code)


def operand_types(text: str, params: list[dict]) -> list[str]:
    """The types of a ``left`` / ``right`` operand as parse.syntax_form gives them: Array for an array literal,
    else those of the parameter of that name (the last one if several)."""
    if text.startswith("["):
        return ["Array"]
    by_name = {p["name"]: p for p in params if p["name"]}
    p = by_name.get(text)
    return p["types"] if p else []


def derived_categories(rec: dict) -> set[str]:
    """The wiki categories a reader can rebuild from the record's other fields."""
    kind = KIND_LABEL[rec["type"]]
    out = {kind, f"Arma 3: {kind}"}
    for g in rec["games"]:
        out.add(f"{CATEGORY_GAME_NAME.get(g['game'], g['name'])}: {kind}")
        out.add(f"Introduced with {g['name']} version" + (f" {g['version']}" if g["version"] else ""))
    if rec["since"]:
        out.add(f"{CATEGORY_GAME_NAME.get(rec['since']['game'], rec['since']['name'])}: New {kind}")
    for g in rec["groups"]:
        out |= {f"Command Group: {g}", f"Function Group: {g}"}
    loc = rec["locality"]
    for field, word in (("argument", "Argument"), ("effect", "Effect")):
        if loc[field]:
            out.add(f"{kind}: {loc[field].title()} {word}")
    if loc["server_exec"]:
        out.add(f"{kind}: Server Execution")
    for b in branches(rec["branch"]):
        if b in BRANCH_CATEGORY:
            out.add(f"Arma 3: {kind}: {BRANCH_CATEGORY[b]} Branch")
    return out


def _empty(v: Any) -> bool:
    return v is None or v is False or v == "" or v == [] or v == {}


def _strip(d: dict, keep: tuple[str, ...] = ()) -> dict:
    return {k: v for k, v in d.items() if k in keep or not _empty(v)}


def _typed(item: dict) -> dict:
    """``types`` only where it says more than ``type_expr`` (see schema.json $defs/types)."""
    if item.get("types") == typeexpr.names(item.get("type_expr")):
        item.pop("types", None)
    return item


def _param(p: dict) -> dict:
    p = dict(p, since=since(p.get("since")))
    if "optional_since" in p:
        p["optional_since"] = since(p["optional_since"])
    if p.get("text") == param_text(p):
        del p["text"]
    return _strip(_typed(p), PARAM_CORE)


def _returns(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    if (r.get("type") or "").strip() == "-":  # "|r1= -" on pages of functions that return nothing
        r.update(type="Nothing", type_expr="Nothing", types=["Nothing"])
    if r.get("text") == returns_text(r):
        del r["text"]
    return _strip(_typed(r)) or None  # "|r1=" left empty says no more than no return value at all


def _syntax(s: dict, operator: str | None) -> dict:
    s = dict(s, since=since(s.get("since")))
    exec_ = s.pop("exec", None)  # "|s1exec=server": this syntax must run on the server; "exec" is spawn/call
    if exec_:
        s["server_exec"] = exec_.strip().lower() in SERVER_VALUES
    if s.get("operator") == operator:
        s.pop("operator", None)
    for side in ("left", "right"):
        if s.get(side):
            o = dict(s[side])
            if o.get("types") == operand_types(o["text"], s["params"]):
                del o["types"]
            s[side] = o
    s["params"] = [_param(p) for p in s["params"]]
    s["returns"] = _returns(s["returns"])
    # keep the keys in order; server_exec next to effect, where exec was
    order = [k for k in s if k != "server_exec"]
    if "server_exec" in s:
        order.insert(order.index("effect") + 1 if "effect" in order else len(order), "server_exec")
    return _strip({k: s[k] for k in order}, SYNTAX_CORE)


def _example(x: dict) -> dict:
    x = dict(x)
    if x["code"] and x["text"] == example_text(x["code"]):
        del x["text"]
    return _strip(x)


def compact(rec: dict) -> dict:
    """The JSON record of a command or function (``parse.parse_page`` output); topic records pass unchanged."""
    if rec.get("type") not in KIND_LABEL:
        return rec
    out: dict[str, Any] = {}
    for k, v in rec.items():
        if k == "games":  # oldest first; a game the wiki lists twice (switch: tkoh) keeps its first version
            games: dict[str, str | None] = {}
            for g in v:
                games.setdefault(g["game"], g["version"])
            v = games
        elif k == "since":
            v = f"{v['game']} {v['version']}" if v and v["version"] else v["game"] if v else None
        elif k == "branch":
            v = branches(v)
        elif k == "locality":
            v = _strip(v)
        elif k == "syntaxes":
            v = [_syntax(s, rec["operator"]) for s in v]
        elif k == "examples":
            v = [_example(x) for x in v]
        elif k == "notes":
            v = [_strip(n) for n in v]
        elif k == "categories":
            k, derived = "categories_extra", derived_categories(rec)
            v = [c for c in v if c not in derived]
        elif k == "docblock":
            v = _strip({f: v[f] for f in DOCBLOCK_KEEP if f in v}) if v else None
        out[k] = v
    return _strip(out, RECORD_CORE)

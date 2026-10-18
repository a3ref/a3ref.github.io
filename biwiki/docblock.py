"""Parse the header comment ("docblock") that many function pages show instead of a written description.

About a fifth of the function pages are placeholders whose description is the comment block from the
function's .sqf file, e.g.

    /*
        Author: Karel Moricky

        Description:
        Set which attributes are available for given entity.

        Parameter(s):
            0: OBJECT - curator
            1: ARRAY of STRINGs (Optional) - attributes. Default: []

        Returns:
        BOOL
    */

The format is free-form and varies by author, so parsing is lenient: known labels start sections, the
least-indented numbered lines of the parameter section start parameters, deeper lines belong to the
parameter above. The cleaned original text is always kept as ``text``.
"""
from __future__ import annotations

import re
import textwrap
from typing import Optional

from . import typeexpr
from .typeexpr import TYPE_WORDS

LABELS = {
    "author": "author", "authors": "author", "by": "author",
    "description": "description", "desc": "description", "purpose": "description", "campaign lobby": "description",
    "parameter(s)": "params", "parameters": "params", "parameter": "params", "params": "params", "param(s)": "params",
    "param": "params", "arguments": "params", "argument(s)": "params", "args": "params", "input": "params",
    "returns": "returns", "return": "returns", "return value": "returns", "returned value": "returns",
    "return value(s)": "returns", "result": "returns", "output": "returns",
    "example": "examples", "examples": "examples", "example(s)": "examples", "usage": "examples",
    "syntax": "syntax",
    "execution": "execution", "exucution": "execution", "exec": "execution",
    "note": "notes", "notes": "notes", "remark(s)": "notes", "remarks": "notes", "remark": "notes",
    "required": "requirements", "requirements": "requirements", "requirments": "requirements",
    "project": "meta", "date": "meta", "version": "meta", "name": "meta", "file": "meta",
}
# Labels that may also stand alone on a line without a colon ("Params", "Return").
BARE = {"params", "parameters", "parameter(s)", "returns", "return", "description", "example", "examples"}

_LABEL = re.compile(r"^[ \t]{0,3}(" + "|".join(sorted(map(re.escape, LABELS), key=len, reverse=True)) + r")\s*:\s?(.*)$",
                    re.I)

_TYPE = re.compile(r"\b(" + "|".join(sorted(TYPE_WORDS, key=len, reverse=True)) + r")s?\b", re.I)
_PARAM = re.compile(r"^(?:_this\s+select\s+|#|\(?)(\d+)\s*(?:[:)\.]|\s-)\s*(.*)$", re.I)
_NO_PARAMS = re.compile(r"^\s*(none|nothing|-|n/a|no parameters?)\.?\s*$", re.I)


def find(text: str) -> Optional[str]:
    """The comment block inside a <pre>/<sqf> body, or None if it does not look like a function header."""
    m = re.search(r"/\*(.*?)\*/", text, re.S)
    body = m.group(1) if m else text
    if m or re.search(r"^\s*(author|description|parameters?|params|returns?)\s*:", body, re.I | re.M):
        return body
    return None


def clean(body: str) -> str:
    """Drop banner lines (****) and leading '*' decorations, normalise tabs, dedent."""
    lines = []
    for line in body.replace("\r", "").split("\n"):
        if re.fullmatch(r"\s*[*=/\\-]{5,}\s*", line):
            continue
        line = re.sub(r"^(\s*)\*(?!\*)", r"\1", line)  # " * text" doxygen style
        lines.append(line.replace("\t", "    ").rstrip())
    return textwrap.dedent("\n".join(lines)).strip("\n")


def parse(body: str) -> dict:
    text = clean(body)
    sections: dict[str, list[str]] = {}
    current = "intro"
    sections[current] = []
    meta: dict[str, str] = {}
    for line in text.split("\n"):
        if re.fullmatch(r"\s*[\w\-]+\.sqf\s*", line):  # "fn_EXP_camp_lobby_clearVars.sqf"
            meta["file"] = line.strip()
            continue
        m = _LABEL.match(line.strip())
        bare = line.strip().rstrip(":").lower()
        if m and len(line) - len(line.lstrip()) <= 12:
            key = LABELS[m.group(1).lower()]
            if key == "meta":
                meta[m.group(1).lower()] = m.group(2).strip()
                continue
            current = key
            sections.setdefault(current, [])
            if m.group(2).strip():
                sections[current].append(m.group(2))
        elif bare in BARE and line.strip() and not line.strip().endswith((".", ",")):
            current = LABELS[bare]
            sections.setdefault(current, [])
        else:
            sections[current].append(line)

    def body_of(key: str) -> str:
        return textwrap.dedent("\n".join(sections.get(key, []))).strip()

    description = body_of("description")
    intro = body_of("intro")
    author = body_of("author")
    if not author and description and intro and "\n" not in intro and len(intro) <= 40 and len(intro.split()) <= 4:
        author, intro = intro, ""  # a bare name above "Description:" is the author
    if not description and intro:
        description = intro
    elif intro and not re.fullmatch(r"[\w.\- ]+\.sqf|[A-Z0-9 \-]+", intro):
        description = f"{intro}\n\n{description}"
    returns = body_of("returns")
    ret_head = returns.split(" - ")[0].split("\n")[0]
    boolean = re.match(r"(true|false)\b", returns, re.I) is not None
    examples = [e for e in re.split(r"\n\s*\n", body_of("examples")) if e.strip()]
    # "BIN_fnc_probeDelete" or ", _objects" is not a description
    if not re.search(r"[A-Za-z]{2,}\W+[A-Za-z]{2,}", description) or re.fullmatch(r"\s*\w+\s*", description):
        description = ""
    return {
        "author": re.sub(r"\s+", " ", author.replace("\n-", ",").lstrip("- ")).strip() or None,
        "description": _prose(description) or None,
        "params": parse_params(body_of("params")),
        "returns": {"types": types_in(ret_head) or (["Boolean"] if boolean else []),
                    # "_priority:SCALAR - the priority": a named return value
                    "type_expr": typeexpr.of_text(ret_head) or typeexpr.of_text(ret_head.split(":", 1)[-1])
                    or ("Boolean" if boolean else None), "text": returns}
        if returns and not re.fullmatch(r"(0:)?\s*", returns) else None,
        "examples": [textwrap.dedent(e).strip() for e in examples],
        "syntax": body_of("syntax") or None,
        "execution": _prose(body_of("execution")) or None,
        "notes": _prose(body_of("notes")) or None,
        "requirements": _prose(body_of("requirements")) or None,
        "meta": meta,
        "text": text,
    }


def _prose(text: str) -> str:
    """Join hard-wrapped comment lines into paragraphs, keep list items and indented blocks."""
    out: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        starts_block = not s or s.startswith(("-", "*", "•")) or re.match(r"^\d+[.)]\s", s) or line.startswith("    ")
        if out and out[-1] and not starts_block and not out[-1].startswith("    "):
            out[-1] += " " + s
        else:
            out.append(line.rstrip() if line.startswith("    ") else s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def types_in(head: str) -> list[str]:
    out: list[str] = []
    for m in _TYPE.finditer(head):
        word = m.group(1).lower()
        t = TYPE_WORDS.get(word) or TYPE_WORDS.get(word.rstrip("s"))
        if t and t not in out:
            out.append(t)
    return out


def parse_params(text: str) -> list[dict]:
    if not text.strip() or _NO_PARAMS.match(text):
        return []
    lines = text.split("\n")
    matching = [i for i, l in enumerate(lines) if _PARAM.match(l.strip())]
    # The first parameter may sit on the label line ("Parameters: 0: ..."), whose indentation says nothing
    # about the rest; take the base indentation from the other parameter lines then.
    others = [i for i in matching if i != 0] if matching and matching[0] == 0 else matching
    indents = [len(lines[i]) - len(lines[i].lstrip()) for i in others]
    base = min(indents) if indents else (0 if matching else None)
    params: list[dict] = []
    for i, line in enumerate(lines):
        s = line.strip()
        indent = len(line) - len(line.lstrip())
        m = _PARAM.match(s) if s else None
        if m and (indent == base or (i == 0 and matching and matching[0] == 0)):
            params.append({"index": int(m.group(1)), "lines": [m.group(2)]})
        elif not params and s and base is None:
            params.append({"index": None, "lines": [s]})  # a single unnumbered parameter
        elif params:
            params[-1]["lines"].append(line[base or 0:] if indent >= (base or 0) else s)
    parsed = [_param(p["index"], p["lines"]) for p in params]
    # template leftovers such as a bare "0:" carry no information
    return [p for p in parsed if p["name"] or p["types"] or p["description"]]


def _param(index, lines: list[str]) -> dict:
    head = lines[0].strip()
    more = textwrap.dedent("\n".join(lines[1:])).strip("\n")
    name = None
    m = re.match(r"^(_*[A-Za-z]\w*)\s*(?::|\s-\s|\(|\s+(?=[A-Z]{3,}\b))", head)  # "_matrix ARRAY (...)" too
    if m and m.group(1).lower() not in TYPE_WORDS and m.group(1).lower().rstrip("s") not in TYPE_WORDS:
        name = m.group(1)
        head = head[m.end() - (1 if head[m.end() - 1] == "(" else 0):].strip(" :-")
    type_part, _, desc = head.partition(" - ")
    if not desc and not _TYPE.match(type_part):
        type_part, desc = "", head
    types, expr = types_in(type_part), typeexpr.of_text(type_part)
    if not types:
        # "<object> unit allowed to use ...", "a unit whose tasks will be handled (Array)",
        # "profile unit (Object) [default player]"
        marked = re.match(r"^<([A-Za-z ]+)>", head) or re.search(r"\(([A-Za-z ]+)\)\s*(\[[^\]]*\])?\s*$", head)
        if marked:
            types, expr = types_in(marked.group(1)), typeexpr.of_text(marked.group(1))
            if head.startswith("<"):
                desc = desc or head[marked.end():].strip(" -")
    if not types and not type_part and more:
        # "1:" followed by alternatives on deeper lines: "STRING - ...", "OBJECT - ..."
        alts = [l.split(" - ")[0] for l in more.split("\n") if re.match(r"^\s*[A-Z]{3,}", l)]
        types = list(dict.fromkeys(t for a in alts for t in types_in(a)))
        expr = typeexpr.union([e for e in map(typeexpr.of_text, alts) if e])
    if name and more:
        # the same name again on the next lines: alternatives ("_this: CFG" / "_this: ARRAY of STRINGS - ...")
        alts = [l.split(":", 1)[1].split(" - ")[0] for l in more.split("\n") if re.match(rf"^\s*{re.escape(name)}\s*:", l)]
        if alts:
            types = list(dict.fromkeys(types + [t for a in alts for t in types_in(a)]))
            expr = typeexpr.union([e for e in [expr, *map(typeexpr.of_text, alts)] if e])
    full = (head + ("\n" + more if more else "")).strip()
    optional = bool(re.search(r"\boptional\b", full, re.I))
    default = None
    dm = re.search(r"\bdefault(?:\s+value)?\s*(?:is|:|=)?\s*([^\n)]+?)(?:\)|\.?\s*$|\.\s)", full, re.I | re.M)
    if dm:
        default = dm.group(1).strip().rstrip(".,") or None
        if default and default.endswith("]") and default.count("]") > default.count("["):
            default = default[:-1].strip() or None  # "profile unit (Object) [default player]"
    desc = re.sub(r"^\(?\s*optional\s*\)?\s*[-,:]?\s*", "", desc, flags=re.I).strip()
    return {
        "index": index,
        "name": name,
        "types": types,
        "type_expr": expr,
        "optional": optional,
        "default": default,
        "description": (desc + ("\n" + more if more else "")).strip() or None,
        "text": full,
    }

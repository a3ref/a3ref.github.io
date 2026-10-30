"""The JSON form of command and function records (format 2): what is left out, and that it can be rebuilt."""
from __future__ import annotations

import copy
import unittest

from biwiki.jsonrecord import branches, compact, example_text, param_text, returns_text
from biwiki.render import _syntax_index


def record(**changes) -> dict:
    """A full record as parse.parse_page gives it."""
    rec = {
        "name": "diag_captureFrame", "operator": None, "title": "diag captureFrame", "type": "command",
        "url": "https://community.bistudio.com/wiki/diag_captureFrame", "revid": 1, "updated": "2026-01-01T00:00:00Z",
        "groups": ["Diagnostic"], "status": "ok", "replaced_by": [],
        "games": [{"game": "ofp", "name": "Operation Flashpoint", "version": None},
                  {"game": "arma3", "name": "Arma 3", "version": "0.50"}],
        "since": {"game": "ofp", "name": "Operation Flashpoint", "version": None}, "arma3_since": "0.50",
        "branch": "diag prof",
        "locality": {"argument": None, "effect": None, "server_exec": False}, "exec": None,
        "description": "Opens the profiler.",
        "syntaxes": [{
            "syntax": "diag_captureFrame frame", "since": "Arma3 2.08", "effect": None, "exec": "server",
            "params": [
                {"name": "frame", "type": "Number", "types": ["Number"], "type_expr": "Number", "optional": False,
                 "default": None, "description": "frame to capture", "since": None, "text": "frame: Number - frame to capture"},
                {"name": "pos", "type": "Array format Position", "types": ["Array", "Position"], "type_expr": "Position",
                 "optional": True, "default": "[0,0,0]", "description": None, "since": "Arma3 2.10",
                 "text": "pos: Array format Position (Optional, default [0,0,0])"},
            ],
            "returns": {"type": "-", "types": [], "type_expr": None, "description": None, "text": "-"},
            "form": "unary", "operator": None, "left": None, "right": {"text": "frame", "types": ["Number"]},
        }],
        "examples": [{"text": "```sqf\ndiag_captureFrame 1;\n```", "code": ["diag_captureFrame 1;"]},
                     {"text": "Capture:\n```sqf\ndiag_captureFrame 2;\n```", "code": ["diag_captureFrame 2;"]}],
        "multiplayer": None, "problems": None, "aliases": [], "see_also": [],
        "notes": [{"user": "a", "date": "", "text": "note"}],
        "categories": ["Scripting Commands", "Arma 3: Scripting Commands", "Command Group: Diagnostic",
                       "Introduced with Operation Flashpoint version", "Operation Flashpoint: New Scripting Commands",
                       "Arma 3: Scripting Commands: Diagnostic Branch", "Arma 3: Scripting Commands: Profiling Branch",
                       "WIP"],
    }
    rec.update(changes)
    return rec


class CompactTest(unittest.TestCase):
    def test_record(self):
        full = record()
        before = copy.deepcopy(full)
        rec = compact(full)
        self.assertEqual(full, before, "the full record stays as it is for Markdown and HTML")
        self.assertEqual(list(rec), ["name", "title", "type", "url", "revid", "updated", "groups", "status", "games",
                                     "since", "arma3_since", "branch", "description", "syntaxes", "examples", "notes",
                                     "categories_extra"])
        self.assertEqual(rec["games"], {"ofp": None, "arma3": "0.50"})
        self.assertEqual(rec["since"], "ofp")
        self.assertEqual(rec["branch"], ["diag", "prof"])
        self.assertEqual(rec["categories_extra"], ["WIP"])
        self.assertEqual(rec["notes"], [{"user": "a", "text": "note"}])
        self.assertEqual(rec["examples"], [{"code": ["diag_captureFrame 1;"]},
                                           {"text": "Capture:\n```sqf\ndiag_captureFrame 2;\n```", "code": ["diag_captureFrame 2;"]}])

    def test_syntax(self):
        s = compact(record())["syntaxes"][0]
        self.assertEqual(list(s), ["syntax", "since", "server_exec", "params", "returns", "form", "right"])
        self.assertEqual((s["since"], s["server_exec"], s["right"]), ("arma3 2.08", True, {"text": "frame"}))
        frame, pos = s["params"]
        self.assertEqual(frame, {"name": "frame", "type": "Number", "type_expr": "Number", "description": "frame to capture"})
        # types says more than type_expr, the text more than name: type - description
        self.assertEqual(pos, {"name": "pos", "type": "Array format Position", "types": ["Array", "Position"],
                               "type_expr": "Position", "optional": True, "default": "[0,0,0]", "since": "arma3 2.10",
                               "text": "pos: Array format Position (Optional, default [0,0,0])"})
        self.assertEqual(s["returns"], {"type": "Nothing", "type_expr": "Nothing", "text": "-"})

    def test_rebuild_rules(self):
        self.assertEqual(param_text({"name": "a", "type": "Number", "description": "x"}), "a: Number - x")
        self.assertEqual(param_text({"name": "a"}), "a")
        self.assertEqual(returns_text({"type": "Object", "description": "x"}), "Object - x")
        self.assertEqual(example_text(["a;", "b;"]), "```sqf\na;\n```\n\n```sqf\nb;\n```")

    def test_empty(self):
        rec = compact(record(locality={"argument": "local", "effect": None, "server_exec": False}, branch=None,
                             notes=[], categories=["Scripting Commands"]))
        self.assertEqual(rec["locality"], {"argument": "local"})
        for k in ("branch", "notes", "categories_extra", "categories", "operator", "replaced_by", "exec"):
            self.assertNotIn(k, rec)
        empty = record(syntaxes=[{"syntax": "", "since": None, "effect": None, "exec": None, "params": [],
                                  "returns": {"type": "", "types": [], "type_expr": None, "description": None, "text": ""}}],
                       updated=None, description="")
        rec = compact(empty)
        self.assertEqual(rec["syntaxes"], [{"syntax": "", "params": [], "returns": None}])
        self.assertEqual((rec["updated"], rec["description"]), (None, ""), "the core stays")

    def test_function_docblock(self):
        rec = compact(record(type="function", docblock={"author": "Karel", "description": "d", "params": [{"name": "x"}],
                                                        "returns": None, "meta": {}, "text": "Author: Karel"},
                             filled_from_docblock=["params"], categories=[]))
        self.assertEqual(rec["docblock"], {"author": "Karel", "text": "Author: Karel"})
        self.assertEqual(rec["filled_from_docblock"], ["params"])

    def test_topics_unchanged(self):
        topic = {"name": "Position", "type": "topic", "categories": ["Data Types"], "aliases": []}
        self.assertIs(compact(topic), topic)

    def test_branch_list(self):
        self.assertEqual(branches("diag prof"), ["diag", "prof"])
        self.assertEqual(branches(None), [])
        index = _syntax_index({"commands": [record(), record(name="time", title="time", branch=None)]}, None)
        self.assertEqual(index["commands"]["diag_captureframe"]["branch"], ["diag", "prof"])
        self.assertNotIn("branch", index["commands"]["time"])


if __name__ == "__main__":
    unittest.main()

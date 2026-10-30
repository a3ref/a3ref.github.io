"""fetch.sync_with against an in-memory wiki standing in for WikiSession.api (no network)."""
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from biwiki.fetch import WikiSession, load_cache, save_cache, sync_with

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def run(wiki, raw, kinds, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        asyncio.run(sync_with(wiki, raw, kinds, now=NOW, **kw))


class FakeWiki(WikiSession):
    """A tiny MediaWiki: ``pages`` {pageid: {title, ns, revid, timestamp, text, categories, redirect}}."""

    def __init__(self, pages: dict[int, dict], changes: list[dict]):
        super().__init__(Path("."))
        self.pages, self.changes, self.calls = pages, changes, []

    def _page(self, pid, prop):
        p = self.pages.get(pid)
        if p is None:
            return {"pageid": pid, "missing": True}
        out = {"pageid": pid, "ns": p.get("ns", 0), "title": p["title"]}
        if "info" in prop:
            out.update(lastrevid=p["revid"], touched=p["timestamp"])
            if p.get("redirect"):
                out["redirect"] = True
        if "categories" in prop and p.get("categories"):
            out["categories"] = [{"ns": 14, "title": c} for c in p["categories"]]
        if "revisions" in prop:
            out["revisions"] = [{"revid": p["revid"], "timestamp": p["timestamp"],
                                 "slots": {"main": {"content": p.get("text", "")}}}]
        if "redirects" in prop:
            out["redirects"] = [{"title": q["title"]} for q in self.pages.values() if q.get("redirect") == p["title"]]
        return out

    def _main(self, cond):
        return [pid for pid, p in sorted(self.pages.items()) if p.get("ns", 0) == 0 and cond(p)]

    async def api(self, **params) -> dict:
        self.requests += 1
        self.calls.append(params)
        prop = str(params.get("prop", ""))
        if params.get("list") == "recentchanges":
            return {"query": {"recentchanges": [c for c in self.changes if c["timestamp"] >= params["rcstart"]]}}
        if params.get("generator") == "categorymembers":
            cat = params["gcmtitle"]
            ids = [pid for pid, p in sorted(self.pages.items()) if cat in p.get("categories", [])]
        elif params.get("generator") == "allpages":
            ids = self._main(lambda p: p["title"].startswith(params["gapprefix"]) and not p.get("redirect"))
        elif "titles" in params:
            wanted = str(params["titles"]).split("|")
            ids = self._main(lambda p: p["title"] in wanted and not p.get("redirect"))
        else:
            ids = [int(x) for x in str(params["pageids"]).split("|")]
        if params.get("redirects") and "pageids" in params:
            redirects = [{"from": self.pages[i]["title"], "to": self.pages[i]["redirect"]}
                         for i in ids if self.pages.get(i, {}).get("redirect")]
            return {"query": {"redirects": redirects}}
        return {"query": {"pages": [self._page(pid, prop) for pid in ids]}}


def page(title, revid, ts, categories=(), **kw):
    return {"title": title, "revid": revid, "timestamp": ts, "text": f"{title} r{revid}",
            "categories": list(categories), **kw}


def entry(p, redirects=None):
    out = {"title": p["title"], "categories": [c.removeprefix("Category:") for c in p["categories"]],
           "revid": p["revid"], "timestamp": p["timestamp"], "wikitext": p["text"]}
    if redirects is not None:
        out["redirects"] = redirects
    return out


CMD, FNC, TOPIC = "Category:Arma 3: Scripting Commands", "Category:Arma 3: Functions", "Category:Arma 3: Editing"


def wiki_pages():
    return {
        1: page("setPos", 100, "2026-10-20T10:00:00Z", [CMD]),
        2: page("BIS fnc spawn", 101, "2026-10-01T10:00:00Z", [FNC]),
        3: page("Arma 3: Mission Editing", 102, "2026-10-25T10:00:00Z", [TOPIC]),
        4: page("Mission Editing", 103, "2026-01-01T10:00:00Z", redirect="Arma 3: Mission Editing"),
        50: page(TOPIC, 104, "2020-01-01T10:00:00Z", ["Category:Arma 3"], ns=14),
    }


class SyncRecentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)
        self.pages = wiki_pages()
        save_cache(self.raw / "commands.json", {1: entry(self.pages[1])})
        save_cache(self.raw / "functions.json", {2: entry(self.pages[2])})
        save_cache(self.raw / "topics.json", {3: entry(self.pages[3], ["Mission Editing"])})

    def tearDown(self):
        self.tmp.cleanup()

    def run_sync(self, changes, kinds=("commands", "functions", "topics"), **kw):
        wiki = FakeWiki(self.pages, changes)
        run(wiki, self.raw, list(kinds), **kw)
        return wiki

    def cache(self, kind):
        return load_cache(self.raw / f"{kind}.json")

    def test_start_is_newest_edit_minus_a_day(self):
        wiki = self.run_sync([])
        self.assertEqual(wiki.calls[0]["rcstart"], "2026-10-24T10:00:00Z")
        self.assertEqual(wiki.calls[0]["rctype"], "edit|new|log")

    def test_no_changes_writes_nothing(self):
        before = {k: (self.raw / f"{k}.json").read_bytes() for k in ("commands", "functions", "topics")}
        mtimes = {k: (self.raw / f"{k}.json").stat().st_mtime_ns for k in before}
        wiki = self.run_sync([])
        self.assertEqual(wiki.requests, 1)
        for k in before:
            self.assertEqual((self.raw / f"{k}.json").read_bytes(), before[k])
            self.assertEqual((self.raw / f"{k}.json").stat().st_mtime_ns, mtimes[k])

    def test_edit(self):
        self.pages[1] = page("setPos", 200, "2026-10-29T10:00:00Z", [CMD])
        self.run_sync([{"type": "edit", "title": "setPos", "pageid": 1, "revid": 200,
                        "timestamp": "2026-10-29T10:00:00Z"}])
        self.assertEqual(self.cache("commands")[1]["wikitext"], "setPos r200")
        self.assertEqual(self.cache("topics")[3]["redirects"], ["Mission Editing"])

    def test_new_pages_join_or_not(self):
        self.pages[10] = page("BIS fnc new", 300, "2026-10-29T10:00:00Z", [FNC])
        self.pages[11] = page("Arma 3: Respawn", 301, "2026-10-29T11:00:00Z", ["Category:Arma 3: Editing"])
        self.pages[12] = page("Arma 2: Respawn", 302, "2026-10-29T12:00:00Z", ["Category:Arma 3: Editing"])
        self.pages[13] = page("Cooking", 303, "2026-10-29T13:00:00Z", ["Category:Food"])
        self.pages[14] = page("Old name", 304, "2026-10-29T14:00:00Z", redirect="Arma 3: Respawn")
        self.run_sync([{"type": "new", "title": self.pages[i]["title"], "pageid": i, "revid": self.pages[i]["revid"],
                        "timestamp": self.pages[i]["timestamp"]} for i in (10, 11, 12, 13, 14)])
        self.assertEqual(sorted(self.cache("functions")), [2, 10])
        topics = self.cache("topics")
        self.assertEqual(sorted(topics), [3, 11])
        self.assertEqual(topics[11]["redirects"], ["Old name"])
        self.assertEqual(sorted(self.cache("commands")), [1])

    def test_only_limits_kinds(self):
        self.pages[10] = page("BIS fnc new", 300, "2026-10-29T10:00:00Z", [FNC])
        self.run_sync([{"type": "new", "title": "BIS fnc new", "pageid": 10, "revid": 300,
                        "timestamp": "2026-10-29T10:00:00Z"}], kinds=["commands"])
        self.assertEqual(sorted(self.cache("functions")), [2])

    def test_deletion(self):
        del self.pages[2]
        wiki = self.run_sync([{"type": "log", "title": "BIS fnc spawn", "pageid": 0, "revid": 0,
                               "timestamp": "2026-10-29T10:00:00Z", "logtype": "delete", "logaction": "delete"}])
        self.assertEqual(self.cache("functions"), {})
        self.assertEqual(self.cache("commands")[1]["revid"], 100)
        self.assertFalse(any("revisions" in str(c.get("prop")) for c in wiki.calls))

    def test_deletion_not_confirmed_keeps_page(self):
        self.run_sync([{"type": "log", "title": "BIS fnc spawn", "pageid": 2, "revid": 0,
                        "timestamp": "2026-10-29T10:00:00Z", "logtype": "delete", "logaction": "restore"}])
        self.assertEqual(sorted(self.cache("functions")), [2])

    def test_move(self):
        self.pages[3] = page("Arma 3: Scenario Editing", 400, "2026-10-29T10:00:00Z", [TOPIC])
        self.pages[4]["redirect"] = "Arma 3: Scenario Editing"
        self.pages[20] = page("Arma 3: Mission Editing", 401, "2026-10-29T10:00:00Z",
                              redirect="Arma 3: Scenario Editing")
        self.run_sync([{"type": "log", "title": "Arma 3: Mission Editing", "pageid": 3, "revid": 400,
                        "timestamp": "2026-10-29T10:00:00Z", "logtype": "move", "logaction": "move",
                        "logparams": {"target_ns": 0, "target_title": "Arma 3: Scenario Editing"}}])
        topic = self.cache("topics")[3]
        self.assertEqual(topic["title"], "Arma 3: Scenario Editing")
        self.assertEqual(topic["redirects"], ["Arma 3: Mission Editing", "Mission Editing"])

    def test_move_out_of_main_namespace(self):
        self.pages[2] = page("User:X/BIS fnc spawn", 101, "2026-10-01T10:00:00Z", ns=2)
        self.run_sync([{"type": "log", "title": "BIS fnc spawn", "pageid": 2, "revid": 0,
                        "timestamp": "2026-10-29T10:00:00Z", "logtype": "move", "logaction": "move",
                        "logparams": {"target_ns": 2, "target_title": "User:X/BIS fnc spawn"}}])
        self.assertEqual(self.cache("functions"), {})

    def test_new_redirect(self):
        self.pages[30] = page("Mission editing", 500, "2026-10-29T10:00:00Z", redirect="Arma 3: Mission Editing")
        wiki = self.run_sync([{"type": "new", "title": "Mission editing", "pageid": 30, "revid": 500,
                               "timestamp": "2026-10-29T10:00:00Z"}])
        topics = self.cache("topics")
        self.assertEqual(sorted(topics), [3])
        self.assertEqual(topics[3]["redirects"], ["Mission Editing", "Mission editing"])
        self.assertEqual(topics[3]["revid"], 102)
        self.assertFalse(any("revisions" in str(c.get("prop")) for c in wiki.calls))

    def test_deleted_redirect(self):
        del self.pages[4]
        self.run_sync([{"type": "log", "title": "Mission Editing", "pageid": 0, "revid": 0,
                        "timestamp": "2026-10-29T10:00:00Z", "logtype": "delete", "logaction": "delete"}])
        self.assertEqual(self.cache("topics")[3]["redirects"], [])


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)
        self.pages = wiki_pages()

    def tearDown(self):
        self.tmp.cleanup()

    def walked(self, **kw):
        wiki = FakeWiki(self.pages, [])
        run(wiki, self.raw, ["commands", "functions", "topics"], **kw)
        return not any(c.get("list") == "recentchanges" for c in wiki.calls)

    def test_empty_cache_walks(self):
        self.assertTrue(self.walked())
        self.assertEqual(sorted(load_cache(self.raw / "commands.json")), [1])
        self.assertEqual(sorted(load_cache(self.raw / "functions.json")), [2])
        topics = load_cache(self.raw / "topics.json")
        self.assertEqual(topics, {3: entry(self.pages[3], ["Mission Editing"])})

    def test_old_cache_walks(self):
        old = {1: entry(page("setPos", 1, "2026-07-01T10:00:00Z", [CMD]))}
        for kind in ("commands", "functions", "topics"):
            save_cache(self.raw / f"{kind}.json", old)
        self.assertTrue(self.walked())
        self.assertEqual(load_cache(self.raw / "commands.json")[1]["revid"], 100)

    def test_walk_flag(self):
        self.walked()
        self.assertTrue(self.walked(walk=True))
        self.assertFalse(self.walked())

    def test_walk_and_recent_write_the_same_bytes(self):
        self.walked()
        before = {k: (self.raw / f"{k}.json").read_bytes() for k in ("commands", "functions", "topics")}
        self.walked(walk=True)
        for k, data in before.items():
            self.assertEqual((self.raw / f"{k}.json").read_bytes(), data)
        self.assertEqual(json.loads(before["topics"])["3"]["redirects"], ["Mission Editing"])


if __name__ == "__main__":
    unittest.main()

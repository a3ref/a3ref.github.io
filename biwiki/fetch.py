"""Download page wikitext from the BI Community Wiki.

The wiki is behind a Cloudflare managed challenge, so plain HTTP clients get a 403.
We drive a real Chrome (via patchright) to pass the challenge once, then call the
MediaWiki API with ``fetch()`` from inside the page, where the clearance cookie applies.

A normal sync reads only the wiki's recent changes since the newest edit in the cache (``sync_recent``);
``--walk`` and ``--full`` list every member page instead (``sync_walk``).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://community.bistudio.com"
API = "/wikidata/api.php"

CATEGORIES = {
    "commands": "Category:Arma 3: Scripting Commands",
    "functions": "Category:Arma 3: Functions",
    "topics": "Category:Data Types",
}

# Topics: every Arma 3 page that is not a command or function (editing, multiplayer and server, configs,
# GUI, tools, reference lists, ...), plus the engine-wide concept pages that command pages link to most.
# Agents cannot follow links to the wiki itself, so these are mirrored too.
TOPIC_ROOT = "Category:Arma 3"
TOPIC_PREFIX = "Arma 3:"
# Subcategories not walked: commands and functions are their own kinds; the rest is other games' material
# reached through shared categories (Reference Lists, Tutorials), player or Creator DLC content, and the
# pages of player communities (Multiplayer Squads).
TOPIC_SKIP_CATEGORY = re.compile(
    r"Scripting Commands|Functions|Function Group|Command Group|Introduced with"
    r"|Operation Flashpoint|ArmA:|Arma 2|Take On|CDLC|Field Manual|DLCs & Expansions|Multiplayer Squads"
)
TOPIC_SKIP_TITLE = re.compile(r"^(Operation Flashpoint|ArmA:|Arma: Armed Assault|Arma 2|Take On)|Visitor 3|Field Manual")
TOPIC_CATEGORIES = ["Category:Data Types", "Category:Magic Types", "Category:Syntactical Helper Types"]
TOPIC_TITLES = [
    "SQF Syntax", "Variables", "Operators", "Order of Precedence", "Control Structures", "Magic Variables", "Identifier", "Expression",
    "Position", "Color", "Vector3D", "Arma 3: Tree View Path",
    "Multiplayer Scripting", "Arma 3: Remote Execution", "Scheduler", "Initialisation Order", "Event Scripts",
    "Arma 3: Event Handlers", "Arma 3: Mission Event Handlers", "User Interface Event Handlers",
    "Arma 3: Scripted Event Handlers", "Arma 3: Functions Library", "Arma 3: Writing a Function",
    "PreProcessor Commands", "Description.ext", "Arma 3: Actions", "Arma 3: Curator",
    "Code Best Practices", "Code Optimisation",
]

# Recent changes are read from the newest edit in the cache minus this overlap, so the start time comes from the
# data (a sync without wiki edits writes nothing) and late or slow edits are not missed.
RC_OVERLAP = timedelta(days=1)
# The wiki keeps recent changes for $wgRCMaxAge (MediaWiki's default, 90 days); a start older than this, with a
# day of margin, falls back to the full walk.
RC_MAX_AGE = timedelta(days=89)
_TS = "%Y-%m-%dT%H:%M:%SZ"

_FETCH_JS = """async (params) => {
    for (let attempt = 0; attempt < 5; attempt++) {
        const r = await fetch('%s?' + new URLSearchParams(params));
        if (r.ok && (r.headers.get('content-type') || '').includes('json')) return await r.json();
        await new Promise(res => setTimeout(res, 2000 * (attempt + 1)));
    }
    throw new Error('API request failed: ' + JSON.stringify(params));
}""" % API


class WikiSession:
    def __init__(self, profile_dir: Path, hidden: bool = False, delay: float = 0.3):
        self.profile_dir = profile_dir
        self.hidden = hidden
        self.delay = delay
        self.requests = 0

    async def __aenter__(self):
        from patchright.async_api import async_playwright

        self._pw = await async_playwright().start()
        # Real headless Chrome is rejected by Cloudflare; "hidden" moves a normal window off-screen instead.
        args = ["--window-position=-32000,-32000"] if self.hidden else []
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), channel="chrome", headless=False, no_viewport=True, args=args
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        await self.page.goto(BASE + "/wiki/Main_Page")
        # The challenge page title is localised, so wait for MediaWiki markup instead.
        try:
            await self.page.wait_for_selector("#mw-content-text", timeout=120_000)
        except Exception:
            await self.__aexit__()
            raise RuntimeError(
                "Cloudflare check was not passed within 2 minutes. Run without --hidden and, "
                "if a checkbox appears in the Chrome window, click it."
            ) from None
        return self

    async def __aexit__(self, *exc):
        await self._ctx.close()
        await self._pw.stop()

    async def api(self, **params) -> dict:
        params = {"format": "json", "formatversion": "2", **{k: str(v) for k, v in params.items()}}
        data = await self.page.evaluate(_FETCH_JS, params)
        self.requests += 1
        if "error" in data:
            raise RuntimeError(f"API error: {data['error']}")
        await asyncio.sleep(self.delay)
        return data

    async def query_all(self, **params):
        """Yield every ``query`` block, following ``continue`` tokens."""
        cont: dict = {}
        while True:
            data = await self.api(action="query", **params, **cont)
            if "query" in data:
                yield data["query"]
            if "continue" not in data:
                break
            cont = data["continue"]

    async def list_category(self, category: str) -> dict[int, dict]:
        """Return {pageid: {title, revid, touched}} for all main-namespace members."""
        pages: dict[int, dict] = {}
        async for q in self.query_all(
            generator="categorymembers", gcmtitle=category, gcmnamespace=0, gcmlimit=500, prop="info"
        ):
            for p in q.get("pages", []):
                pages[p["pageid"]] = {"title": p["title"], "revid": p["lastrevid"], "touched": p["touched"]}
        return pages

    async def list_category_tree(self, root: str, skip: re.Pattern, skip_title: re.Pattern) -> dict[int, dict]:
        """Like list_category, for ``root`` and all its subcategories except those matching ``skip``."""
        pages: dict[int, dict] = {}
        seen, queue = {root}, [root]
        while queue:
            category = queue.pop(0)
            async for q in self.query_all(
                generator="categorymembers", gcmtitle=category, gcmnamespace="0|14", gcmlimit=500, prop="info"
            ):
                for p in q.get("pages", []):
                    if p["ns"] == 14:
                        if p["title"] not in seen and not skip.search(p["title"]):
                            seen.add(p["title"])
                            queue.append(p["title"])
                    elif not skip_title.search(p["title"]):
                        pages[p["pageid"]] = {"title": p["title"], "revid": p["lastrevid"], "touched": p["touched"]}
        return pages

    async def list_prefix(self, prefix: str, skip_title: re.Pattern) -> dict[int, dict]:
        """Like list_category, for the main-namespace pages (not redirects) whose title starts with ``prefix``."""
        pages: dict[int, dict] = {}
        async for q in self.query_all(
            generator="allpages", gapprefix=prefix, gapnamespace=0, gapfilterredir="nonredirects", gaplimit=500,
            prop="info",
        ):
            for p in q.get("pages", []):
                if not skip_title.search(p["title"]):
                    pages[p["pageid"]] = {"title": p["title"], "revid": p["lastrevid"], "touched": p["touched"]}
        return pages

    async def list_titles(self, titles: list[str]) -> dict[int, dict]:
        """Like list_category, for explicit titles (redirects followed); missing titles are reported."""
        pages: dict[int, dict] = {}
        for i in range(0, len(titles), 50):
            async for q in self.query_all(titles="|".join(titles[i : i + 50]), redirects=1, prop="info"):
                for p in q.get("pages", []):
                    if p.get("missing"):
                        print(f"  missing on the wiki: {p['title']}")
                    elif p.get("ns") == 0:
                        pages[p["pageid"]] = {"title": p["title"], "revid": p["lastrevid"], "touched": p["touched"]}
        return pages

    async def fetch_redirects(self, pageids: list[int]) -> dict[int, list[str]]:
        """Titles that redirect to each page, so links to old names can stay local."""
        out: dict[int, list[str]] = {pid: [] for pid in pageids}
        for i in range(0, len(pageids), 50):
            async for q in self.query_all(
                pageids="|".join(map(str, pageids[i : i + 50])), prop="redirects", rdprop="title", rdlimit="max",
                rdnamespace=0,
            ):
                for p in q.get("pages", []):
                    out.setdefault(p["pageid"], []).extend(r["title"] for r in p.get("redirects", []))
        return {pid: sorted(set(v)) for pid, v in out.items()}

    async def recent_changes(self, start: str) -> list[dict]:
        """Edits, new pages and log entries (moves, deletions) in the main namespace from ``start`` until now."""
        out: list[dict] = []
        async for q in self.query_all(
            list="recentchanges", rcstart=start, rcdir="newer", rcnamespace=0, rctype="edit|new|log",
            rcprop="title|ids|timestamp|loginfo", rclimit=500,
        ):
            out += q.get("recentchanges", [])
        return out

    async def page_info(self, pageids: list[int]) -> dict[int, dict]:
        """{pageid: {title, ns, redirect, missing, categories}} for the given pages; categories with prefix."""
        out: dict[int, dict] = {}
        for i in range(0, len(pageids), 50):
            async for q in self.query_all(
                pageids="|".join(map(str, pageids[i : i + 50])), prop="categories|info", cllimit="max"
            ):
                for p in q.get("pages", []):
                    entry = out.setdefault(p["pageid"], {
                        "title": p.get("title", ""), "ns": p.get("ns"), "redirect": bool(p.get("redirect")),
                        "missing": bool(p.get("missing")), "categories": [],
                    })
                    entry["categories"] += [c["title"] for c in p.get("categories", [])]
        return out

    async def redirect_targets(self, pageids: list[int]) -> list[str]:
        """Titles the given redirect pages point to."""
        out: list[str] = []
        for i in range(0, len(pageids), 50):
            async for q in self.query_all(pageids="|".join(map(str, pageids[i : i + 50])), redirects=1):
                out += [r["to"] for r in q.get("redirects", [])]
        return out

    async def fetch_content(self, pageids: list[int]) -> dict[int, dict]:
        """Fetch latest wikitext for the given pages, 50 per request (API limit for non-bots)."""
        out: dict[int, dict] = {}
        for i in range(0, len(pageids), 50):
            chunk = pageids[i : i + 50]
            async for q in self.query_all(
                pageids="|".join(map(str, chunk)),
                prop="revisions|categories",
                rvprop="ids|timestamp|content",
                rvslots="main",
                cllimit="max",
                clshow="!hidden",
            ):
                for p in q.get("pages", []):
                    if p.get("missing"):
                        continue
                    # a continued block carries the rest of the categories of pages without their revisions
                    rev = (p.get("revisions") or [{}])[0]
                    entry = out.setdefault(p["pageid"], {"title": p["title"], "categories": []})
                    if "slots" in rev:
                        entry.update(
                            revid=rev["revid"],
                            timestamp=rev["timestamp"],
                            wikitext=rev["slots"]["main"]["content"],
                        )
                    entry["categories"] += [c["title"].removeprefix("Category:") for c in p.get("categories", [])]
            print(f"  fetched {min(i + 50, len(pageids))}/{len(pageids)}", flush=True)
        return {pid: entry for pid, entry in out.items() if "wikitext" in entry}


def load_cache(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def save_cache(path: Path, pages: dict[int, dict]) -> None:
    """Write the cache; a file that would not change is left untouched."""
    text = json.dumps(dict(sorted(pages.items())), ensure_ascii=False, indent=1)
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def recent_start(caches: list[dict[int, dict]], now: datetime) -> str | None:
    """Start of the recent changes to read: the newest edit in the caches minus RC_OVERLAP.

    None (walk every category instead) when a cache is empty or the wiki no longer keeps changes that old.
    """
    stamps = [p["timestamp"] for cache in caches for p in cache.values() if p.get("timestamp")]
    if not stamps or not all(caches):
        return None
    start = datetime.strptime(max(stamps), _TS).replace(tzinfo=timezone.utc) - RC_OVERLAP
    return None if start < now - RC_MAX_AGE else start.strftime(_TS)


def topic_tree(topics: dict[int, dict]) -> set[str]:
    """The categories of the topic tree, approximated by those of the cached topics."""
    cats = {"Category:" + c for p in topics.values() for c in p.get("categories", [])}
    return {TOPIC_ROOT} | {c for c in cats if not TOPIC_SKIP_CATEGORY.search(c)}


def classify(title: str, categories: list[str], tree: set[str]) -> str | None:
    """The kind a main-namespace page that is not a redirect belongs to, by the rules of the walk."""
    cats = set(categories)
    for kind in ("commands", "functions"):
        if CATEGORIES[kind] in cats:
            return kind
    if title in TOPIC_TITLES or cats & set(TOPIC_CATEGORIES):
        return "topics"
    if not TOPIC_SKIP_TITLE.search(title) and (title.startswith(TOPIC_PREFIX) or cats & tree):
        return "topics"
    return None


async def sync(raw_dir: Path, profile_dir: Path, kinds: list[str], hidden: bool = False, full: bool = False,
               walk: bool = False):
    """Bring the raw cache up to date; only changed pages are re-downloaded."""
    async with WikiSession(profile_dir, hidden=hidden) as wiki:
        t0 = time.time()
        await sync_with(wiki, raw_dir, kinds, full=full, walk=walk)
        print(f"{wiki.requests} API requests in {time.time() - t0:.0f}s")


async def sync_with(wiki: WikiSession, raw_dir: Path, kinds: list[str], full: bool = False, walk: bool = False,
                    now: datetime | None = None):
    """Read the recent changes, or walk every category with ``walk``/``full`` or when they do not reach back."""
    caches = {kind: load_cache(raw_dir / f"{kind}.json") for kind in CATEGORIES}
    start = None
    if not (full or walk):
        start = recent_start([caches[k] for k in kinds], now or datetime.now(timezone.utc))
        if start is None:
            print("recent changes do not reach back to the cache: listing every page")
    if start is None:
        await sync_walk(wiki, raw_dir, kinds, caches, full)
    else:
        await sync_recent(wiki, raw_dir, kinds, caches, start)


async def sync_recent(wiki: WikiSession, raw_dir: Path, kinds: list[str], caches: dict[str, dict], start: str):
    """Refetch the cached pages changed since ``start``, add new members, drop deleted pages.

    Left to the weekly walk: pages that leave a category, pages that join one through a template or a category
    page, pages moved into the main namespace, and pages that move from one kind to another.
    """
    t0 = time.time()
    changes = await wiki.recent_changes(start)
    kind_of = {pid: kind for kind, cache in caches.items() for pid in cache}
    by_title = {p["title"]: pid for cache in caches.values() for pid, p in cache.items()}
    topics = caches["topics"]
    redirect_of = {t: pid for pid, p in topics.items() for t in p.get("redirects", [])}
    refetch: set[int] = set()  # cached pages that were edited or moved
    lookup: set[int] = set()  # pages not cached, and cached pages that may be deleted or moved away
    refresh: set[int] = set()  # topics whose redirects may have changed
    for rc in changes:
        pids = {rc.get("pageid") or 0}
        titles = [rc["title"]]
        suspect = rc["type"] == "log"
        if suspect:
            if rc.get("logtype") not in ("delete", "move"):  # protection and the like change no content
                continue
            # the log row's page id may be 0 (deleted) or another page's; the title names the cached one
            pids.add(by_title.get(rc["title"], 0))
            target = (rc.get("logparams") or {}).get("target_title")
            if target:
                titles.append(target)
        for title in titles:
            if title in redirect_of:  # a redirect to a topic was edited, moved or deleted
                refresh.add(redirect_of[title])
        for pid in pids - {0}:
            if pid in kind_of and not suspect:
                refetch.add(pid)
            else:
                lookup.add(pid)
            if suspect and pid in topics:  # a move leaves a redirect behind
                refresh.add(pid)

    removed: dict[str, set[int]] = {kind: set() for kind in CATEGORIES}
    joined: dict[str, set[int]] = {kind: set() for kind in CATEGORIES}
    redirect_pages: list[int] = []
    info = await wiki.page_info(sorted(lookup)) if lookup else {}
    tree = topic_tree(topics)
    for pid in sorted(lookup):
        p = info.get(pid) or {"missing": True}
        gone = p["missing"] or p["ns"] != 0
        if pid in kind_of:
            if gone:
                removed[kind_of[pid]].add(pid)
            else:
                refetch.add(pid)
        elif gone:
            continue
        elif p["redirect"]:
            redirect_pages.append(pid)
        elif kind := classify(p["title"], p["categories"], tree):
            joined[kind].add(pid)
    if redirect_pages and "topics" in kinds:
        topic_by_title = {p["title"]: pid for pid, p in topics.items()}
        refresh.update(topic_by_title[t] for t in await wiki.redirect_targets(redirect_pages) if t in topic_by_title)
    print(f"{len(changes)} recent changes since {start}")

    for kind in kinds:
        path, cache, gone = raw_dir / f"{kind}.json", caches[kind], removed[kind]
        stale = sorted({pid for pid in refetch if kind_of[pid] == kind} | joined[kind])
        fetched = await wiki.fetch_content(stale) if stale else {}
        for pid in stale:
            entry = fetched.get(pid)
            if entry is None:  # deleted meanwhile
                gone.add(pid)
                continue
            if kind == "topics":
                if pid not in cache:
                    refresh.add(pid)
                entry["redirects"] = cache.get(pid, {}).get("redirects", [])
            cache[pid] = entry
        for pid in gone:
            cache.pop(pid, None)
        refreshed = sorted(pid for pid in refresh if pid in cache) if kind == "topics" else []
        if refreshed:
            for pid, titles in (await wiki.fetch_redirects(refreshed)).items():
                if pid in cache:
                    cache[pid]["redirects"] = titles
        new = len(joined[kind] & set(cache))
        print(f"{kind}: {len(stale) - new} refetched, {new} new, {len(gone)} removed, {len(refreshed)} redirect lists")
        save_cache(path, cache)
    print(f"done in {time.time() - t0:.0f}s")


async def sync_walk(wiki: WikiSession, raw_dir: Path, kinds: list[str], caches: dict[str, dict], full: bool):
    """List every member page and fetch those whose revision differs from the cache."""
    for kind in kinds:
        path = raw_dir / f"{kind}.json"
        cache = {} if full else caches[kind]
        t0 = time.time()
        if kind == "topics":
            members = await wiki.list_titles(TOPIC_TITLES)
            for category in TOPIC_CATEGORIES:
                members.update(await wiki.list_category(category))
            members.update(await wiki.list_category_tree(TOPIC_ROOT, TOPIC_SKIP_CATEGORY, TOPIC_SKIP_TITLE))
            members.update(await wiki.list_prefix(TOPIC_PREFIX, TOPIC_SKIP_TITLE))
            # a page in both a topic category and the command or function category is mirrored once
            for other in ("commands", "functions"):
                for pid in caches[other]:
                    members.pop(pid, None)
        else:
            members = await wiki.list_category(CATEGORIES[kind])
        stale = [pid for pid, m in members.items() if cache.get(pid, {}).get("revid") != m["revid"]]
        removed = set(cache) - set(members)
        print(f"{kind}: {len(members)} pages, {len(stale)} to fetch, {len(removed)} removed")
        for pid in removed:
            del cache[pid]
        if stale:
            cache.update(await wiki.fetch_content(stale))
        if kind == "topics":
            # a new redirect does not change the target's revision, so the walk refreshes them all
            for pid, titles in (await wiki.fetch_redirects(sorted(cache))).items():
                if pid in cache:
                    cache[pid]["redirects"] = titles
        caches[kind] = cache
        save_cache(path, cache)
        print(f"{kind}: done in {time.time() - t0:.0f}s")

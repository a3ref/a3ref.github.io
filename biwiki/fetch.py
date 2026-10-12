"""Download page wikitext from the BI Community Wiki.

The wiki is behind a Cloudflare managed challenge, so plain HTTP clients get a 403.
We drive a real Chrome (via patchright) to pass the challenge once, then call the
MediaWiki API with ``fetch()`` from inside the page, where the clearance cookie applies.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

BASE = "https://community.bistudio.com"
API = "/wikidata/api.php"

CATEGORIES = {
    "commands": "Category:Arma 3: Scripting Commands",
    "functions": "Category:Arma 3: Functions",
}

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
                    if p.get("missing") or not p.get("revisions"):
                        continue
                    rev = p["revisions"][0]
                    entry = out.setdefault(p["pageid"], {"title": p["title"], "categories": []})
                    if "slots" in rev:
                        entry.update(
                            revid=rev["revid"],
                            timestamp=rev["timestamp"],
                            wikitext=rev["slots"]["main"]["content"],
                        )
                    entry["categories"] += [c["title"].removeprefix("Category:") for c in p.get("categories", [])]
            print(f"  fetched {min(i + 50, len(pageids))}/{len(pageids)}", flush=True)
        return out


def load_cache(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def save_cache(path: Path, pages: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(pages.items())), ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    tmp.replace(path)


async def sync(raw_dir: Path, profile_dir: Path, kinds: list[str], hidden: bool = False, full: bool = False):
    """Bring the raw cache up to date; only changed pages are re-downloaded."""
    async with WikiSession(profile_dir, hidden=hidden) as wiki:
        for kind in kinds:
            path = raw_dir / f"{kind}.json"
            cache = {} if full else load_cache(path)
            t0 = time.time()
            members = await wiki.list_category(CATEGORIES[kind])
            stale = [pid for pid, m in members.items() if cache.get(pid, {}).get("revid") != m["revid"]]
            removed = set(cache) - set(members)
            print(f"{kind}: {len(members)} pages, {len(stale)} to fetch, {len(removed)} removed")
            for pid in removed:
                del cache[pid]
            if stale:
                cache.update(await wiki.fetch_content(stale))
            save_cache(path, cache)
            print(f"{kind}: done in {time.time() - t0:.0f}s")

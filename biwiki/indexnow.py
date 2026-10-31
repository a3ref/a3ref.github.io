"""IndexNow: after a deploy, tell Bing, Yandex and the other IndexNow search engines which pages changed.

The key is public by design: an engine checks that <site>/<KEY>.txt holds it, which proves the list came from the
site. Google does not take part; it reads sitemap.xml. The changed pages are those of the new sitemap that the
live one, saved before the deploy, lacks or lists with another lastmod (the newest wiki edit of the page).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

KEY = "31d22aa6d5c45af6bd92148698d156c9"
ENDPOINT = "https://api.indexnow.org/indexnow"  # shares every submission with all participating engines
LIMIT = 10_000  # URLs per request

_URL = re.compile(r"<url><loc>([^<]+)</loc>(?:<lastmod>([^<]+)</lastmod>)?</url>")


def entries(sitemap: str) -> dict[str, str]:
    """loc -> lastmod ("" for a page without one)."""
    return {m.group(1): m.group(2) or "" for m in _URL.finditer(sitemap)}


def changed(new: str, old: str) -> list[str]:
    before = entries(old)
    return [url for url, mod in entries(new).items() if before.get(url) != mod]


def submit(urls: list[str], base: str) -> None:
    """Raises urllib.error.HTTPError when the endpoint refuses the list (400, 403 wrong key, 422, 429)."""
    for i in range(0, len(urls), LIMIT):
        body = {"host": urlsplit(base).hostname, "key": KEY, "keyLocation": f"{base}{KEY}.txt",
                "urlList": urls[i:i + LIMIT]}
        req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=60) as r:  # 200 OK, or 202 while the engine checks the key
            print(f"IndexNow: {len(body['urlList'])} URLs sent, HTTP {r.status}")


def run(out: Path, previous: Path, base: str, dry_run: bool = False) -> int:
    old = previous.read_text(encoding="utf-8") if previous.is_file() else ""
    if not entries(old):  # the live sitemap could not be read: sending every page each hour would be spam
        print(f"IndexNow: no previous sitemap in {previous}, nothing sent")
        return 0
    urls = changed((out / "sitemap.xml").read_text(encoding="utf-8"), old)
    if not urls or dry_run:
        print(f"IndexNow: {len(urls)} changed pages{' (dry run, nothing sent)' if urls else ''}")
        print("\n".join(urls[:20]))
        return 0
    try:
        submit(urls, base)
    except urllib.error.HTTPError as e:
        print(f"IndexNow: HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
        return 1
    return 0

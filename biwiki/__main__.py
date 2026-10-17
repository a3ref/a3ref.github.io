"""Command line: python -m biwiki {sync,update,build,feed,report,serve}"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .fetch import CATEGORIES

ROOT = Path(__file__).resolve().parent.parent
# The a3ref/data clone: next to this repository (../data), or inside it (./data, as the deploy workflow checks it out).
DATA = next((p for p in (ROOT / "data", ROOT.parent / "data") if p.is_dir()), ROOT.parent / "data")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="biwiki", description=__doc__)
    ap.add_argument("--raw", type=Path, default=DATA / "raw", help="raw wikitext cache directory (default: ../data/raw)")
    ap.add_argument("--dataset", type=Path, help="also write parsed commands.json/functions.json/index.json here")
    ap.add_argument("--base-url", default="https://a3ref.github.io/", help="public site URL, for llms.txt and sitemap.xml")
    ap.add_argument("--out", type=Path, default=ROOT / "out", help="generated mirror directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def kinds_arg(p):
        p.add_argument("--only", choices=list(CATEGORIES), action="append", help="limit to commands or functions")

    for name, help_ in (("sync", "download/refresh raw wikitext (opens Chrome)"),
                        ("update", "sync + build")):
        p = sub.add_parser(name, help=help_)
        kinds_arg(p)
        p.add_argument("--full", action="store_true", help="ignore cache and re-download everything")
        p.add_argument("--hidden", action="store_true", help="move the Chrome window off-screen")
        p.add_argument("--profile", type=Path, default=ROOT / ".browser-profile", help="Chrome profile directory")
    kinds_arg(sub.add_parser("build", help="generate Markdown/JSON from the raw cache"))
    p = sub.add_parser("feed", help="write changes.json, changes.md and feed.xml from the data repository's git history")
    p.add_argument("--data", type=Path, default=DATA, help="clone of a3ref/data, with history (default: ../data)")
    p = sub.add_parser("report", help="compare the last build's report.json with known-problems.json")
    p.add_argument("--known", type=Path, default=ROOT / "known-problems.json", help="accepted problems baseline")
    p.add_argument("--accept", action="store_true", help="accept all current problems as the new baseline")
    p.add_argument("--issue", action="store_true", help="open/update/close the GitHub issue (needs gh and GH_TOKEN)")
    p.add_argument("--site", default="https://a3ref.github.io/", help="site URL used in links")
    p = sub.add_parser("serve", help="serve the generated mirror over HTTP")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")

    a = ap.parse_args(argv)
    kinds = getattr(a, "only", None) or list(CATEGORIES)

    if a.cmd in ("sync", "update"):
        from .fetch import sync

        asyncio.run(sync(a.raw, a.profile, kinds, hidden=a.hidden, full=a.full))
    if a.cmd in ("build", "update"):
        from .render import build

        build(a.raw, a.out, kinds, dataset=a.dataset, base_url=a.base_url.rstrip("/") + "/")
    if a.cmd == "feed":
        from .feed import write
        from .render import page_slug

        write(a.data, a.out, a.base_url.rstrip("/") + "/", page_slug)
    if a.cmd == "report":
        from .report import run

        sys.exit(run(a.out, a.known, a.accept, a.issue, a.site))
    if a.cmd == "serve":
        serve(a.out, a.host, a.port)


def serve(root: Path, host: str, port: int) -> None:
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {
            **SimpleHTTPRequestHandler.extensions_map,
            ".md": "text/markdown; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }

    httpd = ThreadingHTTPServer((host, port), functools.partial(Handler, directory=str(root)))
    print(f"Serving {root} at http://{host}:{port}/index.md")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

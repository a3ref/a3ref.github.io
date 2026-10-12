"""Command line: python -m biwiki {sync,build,update,serve}"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .fetch import CATEGORIES

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="biwiki", description=__doc__)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw", help="raw wikitext cache directory")
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

        build(a.raw, a.out, kinds)
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

"""IndexNow sends the pages whose sitemap entry is new or has another lastmod, and nothing without the old sitemap."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from biwiki import indexnow

BASE = "https://a3ref.github.io/"
OLD = (f"<url><loc>{BASE}</loc></url>\n<url><loc>{BASE}commands/setPos.html</loc><lastmod>2026-10-01T10:00:00Z</lastmod></url>\n"
       f"<url><loc>{BASE}commands/getPos.html</loc><lastmod>2026-09-01T10:00:00Z</lastmod></url>\n")
NEW = (f"<url><loc>{BASE}</loc></url>\n<url><loc>{BASE}commands/setPos.html</loc><lastmod>2026-10-01T18:30:00Z</lastmod></url>\n"
       f"<url><loc>{BASE}commands/getPos.html</loc><lastmod>2026-09-01T10:00:00Z</lastmod></url>\n"
       f"<url><loc>{BASE}mcp.html</loc></url>\n")


class IndexNowTest(unittest.TestCase):
    def test_changed(self):
        self.assertEqual(indexnow.changed(NEW, OLD), [f"{BASE}commands/setPos.html", f"{BASE}mcp.html"])

    def run_with(self, previous: str | None) -> list:
        sent = []
        with tempfile.TemporaryDirectory() as tmp:
            out, prev = Path(tmp) / "out", Path(tmp) / "previous.xml"
            out.mkdir()
            (out / "sitemap.xml").write_text(NEW, encoding="utf-8")
            if previous is not None:
                prev.write_text(previous, encoding="utf-8")
            with mock.patch.object(indexnow, "submit", lambda urls, base: sent.append(urls)), redirect_stdout(StringIO()):
                self.assertEqual(indexnow.run(out, prev, BASE), 0)
        return sent

    def test_sends_only_changes(self):
        self.assertEqual(self.run_with(OLD), [[f"{BASE}commands/setPos.html", f"{BASE}mcp.html"]])

    def test_nothing_without_the_live_sitemap(self):
        self.assertEqual(self.run_with(None), [])
        self.assertEqual(self.run_with("<html>error page</html>"), [])

    def test_request(self):
        requests = []

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout):
            requests.append(req)
            return Response()

        with mock.patch.object(indexnow.urllib.request, "urlopen", urlopen), redirect_stdout(StringIO()):
            indexnow.submit([f"{BASE}mcp.html"], BASE)
        body = json.loads(requests[0].data)
        self.assertEqual(requests[0].full_url, "https://api.indexnow.org/indexnow")
        self.assertEqual(body["host"], "a3ref.github.io")
        self.assertEqual(body["keyLocation"], f"{BASE}{indexnow.KEY}.txt")
        self.assertEqual(body["urlList"], [f"{BASE}mcp.html"])


if __name__ == "__main__":
    unittest.main()

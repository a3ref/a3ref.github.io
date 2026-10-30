"""Copy a few real wiki pages from the data clone into tests/fixtures/raw/, in the same format as data/raw/, and
the templates a build of them reads into tests/fixtures/raw/templates.json.

    python tests/fixtures/refresh.py            # needs the a3ref/data clone (see biwiki/__main__.py: DATA)

Add a title to PAGES when a parser fix needs a real page to test against; keep the set small.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from biwiki.__main__ import DATA  # noqa: E402
from biwiki.fetch import TEMPLATES, load_cache, save_cache  # noqa: E402

PAGES = {
    "commands": ["setPos", "time", "alive", "a != b", "a == b", "diag fps", "ctrlSetEventHandler", "createVehicle",
                 "drawIcon3D"],
    "functions": ["BIS fnc spawnGroup", "BIS fnc taskHandler", "BIS fnc dbClassCheck", "BIS fnc animateFlag",
                  "BIS fnc typeText2", "BIS fnc getCfgDataPool"],
    "topics": ["Boolean", "Position"],
}

# wikitext the tests render on its own (tests/test_parser.py): the templates it reads go into the fixtures too
TEST_USES = ["{{ArgTitle|4|allowProfileGlasses|{{GVI|arma3|2.04}}}}", "{{cc|done}}"]
FIXTURES = Path(__file__).parent / "raw"


class _Reads(dict):
    """A page mapping that records the titles the parser looks up."""

    def __init__(self, pages):
        super().__init__(pages)
        self.read: set[str] = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __contains__(self, key):
        self.read.add(key)
        return super().__contains__(key)


def write_templates() -> None:
    """raw/templates.json for the fixture pages: the templates of the data clone that a build of them reads."""
    import tempfile
    from contextlib import redirect_stdout
    from io import StringIO

    from biwiki.mediawiki import biki
    from biwiki.portrender import PortContext
    from biwiki.render import build

    source = DATA / "raw" / TEMPLATES
    load_pages, seen = biki.load_pages, []

    def recording(templates, raw):
        pages = _Reads(load_pages(templates, raw))
        seen.append(pages)
        return pages

    biki.load_pages = recording
    try:
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            build(FIXTURES, Path(tmp), templates=source, og_images=False)
        ctx = PortContext.load(source, FIXTURES, {})
        for text in TEST_USES:
            ctx.html("Test", text)
    finally:
        biki.load_pages = load_pages
    read = set().union(*(p.read for p in seen))
    picked = {pid: v for pid, v in load_cache(source).items() if v["title"] in read}
    save_cache(FIXTURES / TEMPLATES, picked)
    print(f"templates: {len(picked)}")


if __name__ == "__main__":
    for kind, titles in PAGES.items():
        cache = load_cache(DATA / "raw" / f"{kind}.json")
        picked = {pid: v for pid, v in cache.items() if v["title"] in titles}
        missing = set(titles) - {v["title"] for v in picked.values()}
        if missing:
            sys.exit(f"{kind}: not in {DATA / 'raw'}: {sorted(missing)}")
        save_cache(FIXTURES / f"{kind}.json", picked)
        print(f"{kind}: {len(picked)} pages")
    write_templates()

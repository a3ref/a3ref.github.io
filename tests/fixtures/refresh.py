"""Copy a few real wiki pages from the data clone into tests/fixtures/raw/, in the same format as data/raw/.

    python tests/fixtures/refresh.py            # needs the a3ref/data clone (see biwiki/__main__.py: DATA)

Add a title to PAGES when a parser fix needs a real page to test against; keep the set small.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from biwiki.__main__ import DATA  # noqa: E402
from biwiki.fetch import load_cache, save_cache  # noqa: E402

PAGES = {
    "commands": ["setPos", "time", "alive", "a != b", "diag fps", "ctrlSetEventHandler", "createVehicle"],
    "functions": ["BIS fnc spawnGroup", "BIS fnc taskHandler"],
    "topics": ["Boolean", "Position"],
}

if __name__ == "__main__":
    for kind, titles in PAGES.items():
        cache = load_cache(DATA / "raw" / f"{kind}.json")
        picked = {pid: v for pid, v in cache.items() if v["title"] in titles}
        missing = set(titles) - {v["title"] for v in picked.values()}
        if missing:
            sys.exit(f"{kind}: not in {DATA / 'raw'}: {sorted(missing)}")
        save_cache(Path(__file__).parent / "raw" / f"{kind}.json", picked)
        print(f"{kind}: {len(picked)} pages")

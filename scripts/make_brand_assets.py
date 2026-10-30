"""Regenerate the icons and the site-wide social preview image in biwiki/assets.

    python scripts/make_brand_assets.py

Drawn with Pillow and the site's own font (JetBrains Mono); the per-page preview images are drawn at build time
by biwiki/ogimage.py, whose palette and mark this shares.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from biwiki.ogimage import DARK, H, MARK_TILE_DARK, MONO, MONO_B, W, font, mark, runs  # noqa: E402

ASSETS = ROOT / "biwiki" / "assets"
MARK, PAPER, INK = "#1b1f24", "#ffffff", "#1b1f24"

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="{MARK}"/>
<rect x="15" y="15" width="34" height="34" fill="none" stroke="{PAPER}" stroke-width="5"/>
<path d="M32 15v34M15 32h34" stroke="{PAPER}" stroke-width="5"/>
</svg>
"""


def icon(size: int) -> Image.Image:
    """The grid-square mark on its dark tile."""
    return mark(size, tile=MARK, line=PAPER)


def og_image() -> Image.Image:
    """The site-wide preview image: a terminal fetching a real page as an agent would. Repository fonts only, in
    the per-page images' palette (biwiki/ogimage.py)."""
    p = DARK
    img = Image.new("RGB", (W, H), p["bg"])
    d = ImageDraw.Draw(img)
    m = mark(72, tile=MARK_TILE_DARK)
    img.paste(m, (80, 56), m)
    d.text((176, 112), "a3ref", font=font(MONO_B, 56), fill=p["ink"], anchor="ls")
    d.text((80, 196), "Arma 3 scripting reference", font=font(MONO_B, 54), fill=p["ink"], anchor="ls")
    d.text((80, 240), "for people and AI agents", font=font(MONO, 34), fill=p["muted"], anchor="ls")
    top = 284
    d.rounded_rectangle([60, top, 1140, 590], radius=14, fill="#0f1115", outline=p["rule"], width=2)
    f, fb = font(MONO, 28), font(MONO_B, 28)
    lines = [
        [("$ ", p["indfor"]), ("curl ", p["ink"]), ("a3ref.github.io/commands/setPos.md", p["accent"])],
        [("# setPos", p["ink"])],
        [("Sets object position to format PositionAGLS", p["muted"])],
        [("object ", p["ink"]), ("setPos", p["accent"]), (" pos", p["ink"])],
        [("$", p["indfor"])],
    ]
    y = top + 56
    for i, parts in enumerate(lines):
        end = runs(d, 92, y, parts, fb if i == 1 else f)
        y += 50
    d.rectangle([end + 17, y - 50 - 24, end + 33, y - 50 + 4], fill=p["ink"])  # the cursor after the prompt
    return img


def main() -> None:
    (ASSETS / "icon.svg").write_text(SVG, encoding="utf-8", newline="\n")
    for size in (180, 192, 512):
        icon(size).save(ASSETS / f"icon-{size}.png", optimize=True)
    icon(64).save(ASSETS / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    manifest = {
        "name": "a3ref – Arma 3 scripting reference",
        "short_name": "a3ref",
        "start_url": "./index.html",
        "display": "browser",
        "background_color": PAPER,
        "theme_color": MARK,
        "icons": [
            {"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "assets/icon.svg", "sizes": "any", "type": "image/svg+xml"},
        ],
    }
    (ASSETS / "site.webmanifest").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                             newline="\n")
    og_image().save(ASSETS / "og.png", optimize=True)
    print("written:", ", ".join(sorted(p.name for p in ASSETS.iterdir() if p.suffix in (".png", ".ico", ".svg", ".webmanifest"))))


if __name__ == "__main__":
    main()

"""Regenerate the icons and the social preview image in biwiki/assets.

    python scripts/make_brand_assets.py

The preview image is rendered by Chrome (patchright) so it uses the site's own fonts.
"""
import asyncio
import json
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "biwiki" / "assets"
MARK, PAPER, INK = "#1b1f24", "#ffffff", "#1b1f24"

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="{MARK}"/>
<rect x="15" y="15" width="34" height="34" fill="none" stroke="{PAPER}" stroke-width="5"/>
<path d="M32 15v34M15 32h34" stroke="{PAPER}" stroke-width="5"/>
</svg>
"""


def icon(size: int) -> Image.Image:
    """The grid-square mark, drawn at 4x and scaled down for clean edges."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = s / 64
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=12 * k, fill=MARK)
    w = round(5 * k)
    d.rectangle([15 * k, 15 * k, 49 * k, 49 * k], outline=PAPER, width=w)
    d.line([32 * k, 15 * k, 32 * k, 49 * k], fill=PAPER, width=w)
    d.line([15 * k, 32 * k, 49 * k, 32 * k], fill=PAPER, width=w)
    return img.resize((size, size), Image.LANCZOS)


OG_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@font-face { font-family: M; src: url(fonts/jetbrains-mono-latin-600-normal.woff2); font-weight: 600; }
html, body { margin: 0; width: 1200px; height: 630px; background: #f5f6f8; color: #1b1f24; overflow: hidden;
  font-family: "Segoe UI", system-ui, sans-serif; }
.grid { position: absolute; inset: 0 0 0 640px; border-left: 1px solid #d9dee5;
  background-image: linear-gradient(#d9dee5 1px, transparent 1px), linear-gradient(90deg, #d9dee5 1px, transparent 1px);
  background-size: 80px 80px; background-position: -1px -1px; }
.cmd { position: absolute; white-space: nowrap; font: 600 27px M; color: #1b1f24; background: #fff; border: 1px solid #d9dee5;
  border-radius: 8px; padding: 14px 20px; }
.cmd b { color: #0b5aa8; font-weight: 600; }
.box { position: absolute; left: 80px; top: 86px; width: 540px; }
.mark { width: 76px; height: 76px; }
h1 { font-size: 66px; line-height: 1.04; font-weight: 700; letter-spacing: -1.5px; margin: 34px 0 20px; }
p { font-size: 27px; line-height: 1.4; margin: 0; color: #545e6a; }
code { font: 600 26px M; color: #0b5aa8; }
</style></head><body>
<div class="grid"></div>
<div class="cmd" style="left:700px;top:150px">_veh <b>setPos</b> [0, 0, 0]</div>
<div class="cmd" style="left:700px;top:290px">[] <b>call</b> BIS_fnc_spawnGroup</div>
<div class="cmd" style="left:720px;top:430px"><b>remoteExec</b> ["hint", 0]</div>
<div class="box">MARK<h1>Arma 3 scripting reference</h1>
<p>Every SQF command, function and concept page, updated daily as HTML, Markdown and JSON.</p>
<p style="margin-top:26px"><code>a3ref.github.io</code></p></div>
</body></html>"""


async def og_image() -> None:
    from patchright.async_api import async_playwright

    page_file = ASSETS / "_og.html"
    page_file.write_text(OG_HTML.replace("MARK", SVG.replace("<svg ", '<svg class="mark" ')),
                         encoding="utf-8")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            page = await browser.new_page(viewport={"width": 1200, "height": 630})
            await page.goto(page_file.as_uri())
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(ASSETS / "og.png"))
            await browser.close()
    finally:
        page_file.unlink()


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
    (ASSETS / "site.webmanifest").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    asyncio.run(og_image())
    print("written:", ", ".join(sorted(p.name for p in ASSETS.iterdir() if p.suffix in (".png", ".ico", ".svg", ".webmanifest"))))


if __name__ == "__main__":
    main()

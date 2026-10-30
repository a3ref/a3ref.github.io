"""Per-page social preview (Open Graph) images: the page drawn as code in a dark editor.

A ``// Scripting command`` style comment, the page name in its type colour (as large as fits, then wrapped),
and its first syntax form or, without one, the first sentence of its summary. 1200x630, a 64-colour PNG of
about 13 KiB, written next to the page as ``<slug>.og.png``.

Only JetBrains Mono from ``assets/fonts`` (Pillow reads WOFF2), so the Linux CI renders what a Windows build
renders. The output is deterministic: no dates, a fixed palette, and Pillow writes no tIME chunk. Each image
carries a key of its inputs in a tEXt chunk; a build skips an image whose file already holds the same key.

Images are rendered in a process pool while the build parses pages (``OgImages.submit``), so on a machine with
spare cores they add little to the build's wall time.
"""
from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import os
import re
from concurrent.futures import Future, ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

import PIL
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

# Bump when the drawing changes, so builds that keep `out/` re-render every image.
VERSION = "t2-editor/1"
SUFFIX = ".og.png"
W, H = 1200, 630

FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
MONO = str(FONTS / "jetbrains-mono-latin-400-normal.woff2")
MONO_B = str(FONTS / "jetbrains-mono-latin-600-normal.woff2")

# The dark side of the site's palette (assets/style.css).
DARK = dict(bg="#16181d", surface="#1e2128", surface2="#262a32", ink="#e5e8ec", muted="#a3acb8", rule="#2e333c",
            rule_strong="#5f6875", accent="#7cb3ff", accent_soft="#1d2a3d", indfor="#74cf8e", opfor="#ff8f86",
            civ="#c9a6ff", sand="#e2b766")
MARK_TILE_DARK = "#2b313b"  # the mark's tile on a dark background
TYPE_LABEL = {"command": "Scripting command", "function": "Function", "topic": "Topic"}
TYPE_COLOR = {"command": "accent", "function": "indfor", "topic": "civ"}
_KEY_CHUNK = "a3ref-og"


@lru_cache(maxsize=None)
def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def mark(size: int, tile: str | None = "#1b1f24", line: str = "#ffffff") -> Image.Image:
    """The grid-square brand mark (assets/icon.svg geometry), drawn at 4x and scaled down for clean edges."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = s / 64
    if tile:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=12 * k, fill=tile)
    w = round(5 * k)
    d.rectangle([15 * k, 15 * k, 49 * k, 49 * k], outline=line, width=w)
    d.line([32 * k, 15 * k, 32 * k, 49 * k], fill=line, width=w)
    d.line([15 * k, 32 * k, 49 * k, 32 * k], fill=line, width=w)
    return img.resize((size, size), Image.LANCZOS)


def runs(d: ImageDraw.ImageDraw, x: float, y: float, parts: list[tuple[str, str]], f) -> float:
    """Draw (text, colour) runs on one baseline; return the end x."""
    for text, color in parts:
        d.text((x, y), text, font=f, fill=color, anchor="ls")
        x += f.getlength(text)
    return x


# ---- layout ---------------------------------------------------------------------------------------------------

def _breaks(name: str) -> list[int]:
    """Break opportunities in a page name: after spaces, '_' and ':', and between camelCase humps."""
    out = set()
    for i in range(1, len(name)):
        a, b = name[i - 1], name[i]
        if a in " _:" and b != " " or (a.islower() and b.isupper()):
            out.add(i)
    return sorted(out)


def wrap_name(name: str, path: str, width: int, sizes1: range, sizes2: range):
    """Largest size that fits on one line, else on two lines (greedy at break points), else the smallest
    two-line size cut hard with an ellipsis."""
    for s in sizes1:
        f = font(path, s)
        if f.getlength(name) <= width:
            return f, [name]
    bks = _breaks(name)
    for s in sizes2:
        f = font(path, s)
        fit = [i for i in bks if f.getlength(name[:i].rstrip()) <= width]
        if fit:
            a, b = name[:fit[-1]].rstrip(), name[fit[-1]:]
            if f.getlength(b) <= width:
                return f, [a, b]
    f = font(path, sizes2[-1])
    lines, rest = [], name
    for _ in range(2):
        n = len(rest)
        while f.getlength(rest[:n]) > width:
            n -= 1
        lines.append(rest[:n])
        rest = rest[n:]
    if rest:
        lines[-1] = lines[-1][:-1] + "…"
    return f, lines


def syntax_runs(name: str, syntax: str, p: dict, name_key: str) -> list[tuple[str, str]]:
    """The syntax line: the page's own name in its type colour, call/spawn in the command colour, punctuation
    muted."""
    out = []
    for m in re.finditer(r"\w+|\s+|[^\w\s]", syntax):
        t = m.group()
        if t == name:
            c = p[name_key]
        elif t in ("call", "spawn"):
            c = p["accent"]
        elif not t.strip() or re.match(r"\w", t):
            c = p["ink"]
        else:
            c = p["muted"]
        out.append((t, c))
    return out


def wrap_runs(parts: list[tuple[str, str]], f, width: int, max_lines: int) -> list[list[tuple[str, str]]]:
    """Greedy word wrap of coloured runs at spaces; a cut last line ends in an ellipsis."""
    lines, cur, cur_w = [], [], 0.0
    for t, c in parts:
        w = f.getlength(t)
        if cur and cur_w + w > width and t.strip():
            lines.append(cur)
            cur, cur_w = [], 0.0
        if not cur and not t.strip():
            continue
        cur.append((t, c))
        cur_w += w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and f.getlength("".join(t for t, _ in last) + " …") > width:
            last.pop()
        while last and not last[-1][0].strip():
            last.pop()
        last.append((" …", last[-1][1] if last else "#000"))
    return lines


def prose_runs(text: str, color: str) -> list[tuple[str, str]]:
    first = re.split(r"(?<=[.!?])\s", text or "", maxsplit=1)[0]
    return [(t, color) for t in re.findall(r"\S+|\s+", first)]


def _name_block(d, name: str, parts: list, name_color: str, top: int, bottom: int, sizes1: range) -> None:
    """The page name (one or two lines) and its syntax or first sentence, centred vertically in [top, bottom]."""
    nf, nlines = wrap_name(name, MONO_B, 1040, sizes1, range(84, 47, -2))
    sf = font(MONO, 34)
    slines = wrap_runs(parts, sf, 1040, 3 if len(nlines) == 1 else 2) if parts else []
    nasc, ndesc = nf.getmetrics()
    lh, slh, gap = round(nf.size * 1.12), 50, 46
    height = nasc + (len(nlines) - 1) * lh + (gap + 26 + (len(slines) - 1) * slh if slines else ndesc)
    y = top + (bottom - top - height) / 2 + nasc
    for line in nlines:
        d.text((76, y), line, font=nf, fill=name_color, anchor="ls")
        y += lh
    y += gap + 26 - lh
    for line in slines:
        runs(d, 80, y, line, sf)
        y += slh


def draw(name: str, kind: str, syntax: str = "", summary: str = "") -> Image.Image:
    """The image of one page. ``kind``: command, function or topic. Without ``syntax`` the first sentence of
    ``summary`` is shown; without either, the name only."""
    p = DARK
    key = TYPE_COLOR[kind]
    img = Image.new("RGB", (W, H), p["bg"])
    d = ImageDraw.Draw(img)
    m = mark(64, tile=MARK_TILE_DARK)
    img.paste(m, (1056, 52), m)
    d.text((80, 100), f"// {TYPE_LABEL[kind]}", font=font(MONO, 36), fill=p["muted"], anchor="ls")
    parts = syntax_runs(name, syntax, p, key) if syntax else prose_runs(summary, p["ink"]) if summary else []
    _name_block(d, name, parts, p[key], 120, 510, range(104, 71, -2))
    d.rectangle([0, 520, W, H], fill=p["surface"])
    d.line([0, 520, W, 520], fill=p["rule"], width=2)
    d.text((80, 586), "a3ref", font=font(MONO_B, 36), fill=p["ink"], anchor="ls")
    d.text((1120, 584), "Arma 3 scripting reference", font=font(MONO, 30), fill=p["muted"], anchor="rs")
    return img


# ---- files ----------------------------------------------------------------------------------------------------

def image_key(name: str, kind: str, syntax: str = "", summary: str = "") -> str:
    """What the image depends on: the inputs it shows, the template version and the Pillow version."""
    shown = [name, kind, syntax, "" if syntax else summary]
    return hashlib.sha256(json.dumps([VERSION, PIL.__version__, *shown]).encode()).hexdigest()[:20]


def png(name: str, kind: str, syntax: str = "", summary: str = "") -> bytes:
    """A 64-colour palette PNG (the text's anti-aliasing survives), its key in a tEXt chunk."""
    img = draw(name, kind, syntax, summary).quantize(colors=64, method=Image.Quantize.MEDIANCUT,
                                                     dither=Image.Dither.NONE)
    info = PngInfo()
    info.add_text(_KEY_CHUNK, image_key(name, kind, syntax, summary))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, pnginfo=info)
    return buf.getvalue()


def _stored_key(path: Path) -> str | None:
    """The key in an existing image, read from its head (Pillow writes tEXt right after IHDR)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(256)
    except OSError:
        return None
    m = re.search(re.escape(_KEY_CHUNK.encode()) + rb"\x00([0-9a-f]{20})", head)
    return m.group(1).decode() if m else None


def write(path: Path, name: str, kind: str, syntax: str = "", summary: str = "") -> bool:
    """Write the image unless ``path`` already holds one with the same key; True if it was rendered."""
    if _stored_key(path) == image_key(name, kind, syntax, summary):
        return False
    path.write_bytes(png(name, kind, syntax, summary))
    return True


class OgImages:
    """Renders the images in worker processes as pages are submitted; ``close`` waits for them and removes the
    images of pages that no longer exist."""

    def __init__(self, workers: int | None = None):
        # Leave a core to the build itself, which keeps parsing pages meanwhile.
        self.workers = workers or max(1, (os.cpu_count() or 2) - 1)
        self._pool: ProcessPoolExecutor | None = None
        self._jobs: list[Future] = []
        self.paths: set[Path] = set()

    def submit(self, path: Path, name: str, kind: str, syntax: str = "", summary: str = "") -> None:
        if self._pool is None:
            # spawn on every platform: no fork of a large, possibly threaded build process
            self._pool = ProcessPoolExecutor(self.workers, mp_context=multiprocessing.get_context("spawn"))
        self.paths.add(path)
        self._jobs.append(self._pool.submit(write, path, name, kind, syntax, summary))

    def close(self, dirs: list[Path]) -> tuple[int, int]:
        """Wait for the images; delete other ``*.og.png`` in ``dirs``. Returns (rendered, kept)."""
        try:
            rendered = sum(f.result() for f in self._jobs)
        finally:
            if self._pool is not None:
                self._pool.shutdown()
        # by lower-case name: on a case-insensitive file system an old file keeps its old spelling when rewritten
        keep = {str(p).lower() for p in self.paths}
        for d in dirs:
            for f in d.glob(f"*{SUFFIX}"):
                if str(f).lower() not in keep:
                    f.unlink()
        return rendered, len(self._jobs) - rendered

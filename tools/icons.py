"""Renders the app icons in icons/ (what a phone shows after the page is installed from the browser).

  python tools/icons.py            # writes icons/*.png next to index.html
  python tools/icons.py --check    # renders to tools/out/ only, writes nothing to the repo

The icon is the page's own dyno chart, drawn as 8-bit pixel art: a torque curve that peaks early and falls, and a power curve
that keeps climbing, crossing where torque and power meet (5,252 RPM). It is drawn on a 32x32 grid of hard pixels and scaled
up with nearest-neighbour (6x for 192, 16x for 512), so every pixel stays a clean square. The palette is the default (green)
theme's own colors, read from index.html (--bg, --halo, --faint, --dim, --fg for power, --s2 for torque, plus a darker --s2
for the shaded underside), so run this again and commit icons/ after changing the palette. Four files, all PNG:

  icon-192.png, icon-512.png   purpose "any": a stepped frame with notched, transparent corners
  icon-maskable-512.png        purpose "maskable": full-bleed, with the chart inside the central 80% that Android may crop to
  apple-touch-icon.png         192x192, full-bleed (iOS rounds the corners itself, turns transparency black, and scales it down)

192 is used for the iPhone icon, not 180, because 192 is a whole multiple of the 32-pixel grid (6x) while 180 is not, and
iOS accepts any size.

Needs Pillow (pip install pillow) as well as Playwright (Playwright only reads the colors from the page).
"""
import asyncio
import sys

from PIL import Image
from playwright.async_api import async_playwright

from common import OUT, REPO, open_page

TOKENS = ("--bg", "--fg", "--dim", "--faint", "--halo", "--s2")
G = 32                       # the pixel grid is G x G
# (file, pixel size, kind): "any" has a frame and notched transparent corners, the others are full-bleed squares
FILES = (("icon-192.png", 192, "any"), ("icon-512.png", 512, "any"),
         ("icon-maskable-512.png", 512, "maskable"), ("apple-touch-icon.png", 192, "apple"))
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def curves():
    """Torque and power as SVG-style point lists in a 100x100 box (y down), on one scale like the page's chart: RPM runs 2,000 to 7,000
    across the box and power = torque x RPM / 5252, so the two curves cross at 5,252 RPM."""
    box = (20, 25, 80, 75)                      # left, top, right, bottom: corner at 39% from the centre, inside the 40% safe zone of a maskable icon
    def torque(x):                              # builds fast to a peak at 0.34, then falls away
        return 0.22 + 0.78 * (1 - (1 - x / 0.34) ** 2) if x < 0.34 else 1 - 0.34 * ((x - 0.34) / 0.66) ** 1.25
    xs = [i / 60 for i in range(61)]
    peak = 0.96 / max(torque(x) for x in xs)    # the torque peak sits just under the top of the box
    ts = [(x, torque(x) * peak) for x in xs]
    ps = [(x, y * (2000 + 5000 * x) / 5252) for x, y in ts]
    def pts(seq):
        l, t, r, b = box
        return [(l + x * (r - l), b - y * (b - t)) for x, y in seq]
    return pts(ts), pts(ps), box


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bresenham(pts):
    """The pixels on the polyline through pts (floats in grid units), one pixel wide."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        x0, y0, x1, y1 = round(x0), round(y0), round(x1), round(y1)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            out.append((x0, y0))
            if (x0, y0) == (x1, y1):
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
    return out


def draw(tok, kind):
    """The icon on its G x G grid, as an RGBA image."""
    P = {k: rgb(v) for k, v in tok.items()}
    amber_dark = tuple(round(a * .6 + b * .4) for a, b in zip(P["--s2"], P["--bg"]))   # the torque line's shaded underside
    img = Image.new("RGBA", (G, G), P["--bg"] + (255,))
    px = img.load()

    def put(x, y, c):
        if 0 <= x < G and 0 <= y < G:
            px[x, y] = (c if isinstance(c, tuple) else P[c]) + (255,)

    # a dithered glow at the top centre (the screen's halo): ordered dither, so only the two palette colors appear
    for y in range(G):
        for x in range(G):
            d = (((x - 15.5) / 16) ** 2 * .8 + ((y + 3) / 14) ** 2) ** .5
            if .75 - d > (BAYER[y % 4][x % 4] + .5) / 16:
                put(x, y, "--halo")

    tpts, ppts, (l, t, r, b) = curves()
    grid = lambda seq: [(x * G / 100, y * G / 100) for x, y in seq]
    L, T, R, B = (round(v * G / 100) for v in (l, t, r, b))
    for x in range(L, R + 1, 2):                                   # dashed grid lines, at the top and the middle of the chart
        put(x, T, "--faint")
        put(x, (T + B) // 2, "--faint")
    for x in range(L, R + 1):                                      # axes
        put(x, B, "--dim")
    for y in range(T - 1, B + 1):
        put(L, y, "--dim")

    def stroke(seq, face, shade):
        """A one-pixel line with a darker pixel under it, which reads as a two-pixel line with a shaded edge."""
        cells = set(bresenham(grid(seq)))
        for (x, y) in cells:
            if (x, y + 1) not in cells:
                put(x, y + 1, shade)
        for (x, y) in cells:
            put(x, y, face)

    stroke(tpts, "--s2", amber_dark)
    stroke(ppts, "--fg", "--dim")

    if kind == "any":                                              # stepped frame, then notch the corners to transparent
        for x in range(3, G - 3):
            put(x, 1, "--dim")
            put(x, G - 2, "--dim")
        for y in range(3, G - 3):
            put(1, y, "--dim")
            put(G - 2, y, "--dim")
        for x, y in ((2, 2), (G - 3, 2), (2, G - 3), (G - 3, G - 3)):
            put(x, y, "--dim")
        for cx, cy, sx, sy in ((0, 0, 1, 1), (G - 1, 0, -1, 1), (0, G - 1, 1, -1), (G - 1, G - 1, -1, -1)):
            for i, j in ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (0, 2)):
                px[cx + sx * i, cy + sy * j] = (0, 0, 0, 0)
    return img


async def read_tokens():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx, pg, errs = await open_page(browser)
        tok = await pg.evaluate("t => Object.fromEntries(t.map(k => [k, getComputedStyle(document.documentElement).getPropertyValue(k).trim()]))",
                                list(TOKENS))
        theme = await pg.evaluate("document.documentElement.dataset.phosphor")
        await ctx.close()
        await browser.close()
    if errs:
        sys.exit("page errors: " + "; ".join(errs))
    return tok, theme


def main():
    check_only = "--check" in sys.argv
    tok, theme = asyncio.run(read_tokens())
    print(f"theme {theme}, tokens {tok}")
    dest = OUT if check_only else REPO / "icons"
    dest.mkdir(exist_ok=True)
    for name, size, kind in FILES:
        assert size % G == 0, f"{size} is not a whole multiple of the {G}-pixel grid"
        img = draw(tok, kind).resize((size, size), Image.NEAREST)
        img.save(dest / name, optimize=True)
        print(f"{dest / name}  {size}x{size}  {kind}  {(dest / name).stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()

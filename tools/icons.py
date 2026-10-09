"""Renders the app icons in icons/ (what a phone shows after the page is installed from the browser).

  python tools/icons.py            # writes icons/*.png next to index.html
  python tools/icons.py --check    # renders to tools/out/ only, writes nothing to the repo

The icon is the page's own dyno chart: a torque curve that peaks early and falls, and a power curve that keeps climbing,
crossing where torque and power meet (5,252 RPM), on the page's screen look in the default (green) theme. The colors are
read from index.html (--bg, --halo, --dim, --faint, --fg for power, --s2 for torque), so run this again and commit icons/
after changing the palette. Four files, all PNG:

  icon-192.png, icon-512.png   purpose "any": a rounded screen with transparent corners
  icon-maskable-512.png        purpose "maskable": full-bleed, with the chart inside the central 80% that Android may crop to
  apple-touch-icon.png         180x180, full-bleed (iOS rounds the corners itself and turns transparency black)

Needs Playwright only (the drawing is an inline SVG screenshotted in Chromium, like og.py).
"""
import asyncio
import sys

from playwright.async_api import async_playwright

from common import OUT, REPO, open_page

TOKENS = ("--desk", "--bg", "--fg", "--dim", "--faint", "--halo", "--rgb", "--s2")
# (file, pixel size, kind): "any" has rounded transparent corners, the others are full-bleed squares
FILES = (("icon-192.png", 192, "any"), ("icon-512.png", 512, "any"),
         ("icon-maskable-512.png", 512, "maskable"), ("apple-touch-icon.png", 180, "apple"))


def curves():
    """Torque and power as SVG point lists in a 100x100 box (y down), on one scale like the page's chart: RPM runs 2,000 to 7,000
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
        return " ".join(f"{l + x * (r - l):.2f},{b - y * (b - t):.2f}" for x, y in seq)
    return pts(ts), pts(ps), box


def page(tok, size, kind, tpts, ppts, box):
    l, t, r, b = box
    frame = (f'<rect x="3" y="3" width="94" height="94" rx="17" fill="none" stroke="{tok["--dim"]}" stroke-width="1.6"/>'
             if kind == "any" else "")
    grid = "".join(f'<line x1="{l}" x2="{r}" y1="{y:.1f}" y2="{y:.1f}" stroke="{tok["--faint"]}" stroke-width=".7" stroke-dasharray="1.6 2.2"/>'
                   for y in (t + (b - t) * f for f in (0.0, 0.5)))
    radius = "22%" if kind == "any" else "0"
    return f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{size}px;height:{size}px;overflow:hidden;background:transparent}}
.s{{width:{size}px;height:{size}px;border-radius:{radius};overflow:hidden;
  background:radial-gradient(75% 60% at 50% -8%,{tok['--halo']},transparent 80%),{tok['--bg']}}}
svg{{display:block}}
</style><div class="s"><svg viewBox="0 0 100 100" width="{size}" height="{size}">
{frame}{grid}
<line x1="{l}" x2="{r}" y1="{b}" y2="{b}" stroke="{tok['--dim']}" stroke-width="1.1"/>
<line x1="{l}" x2="{l}" y1="{t - 4}" y2="{b}" stroke="{tok['--dim']}" stroke-width="1.1"/>
<g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="4">
<polyline points="{tpts}" stroke="{tok['--s2']}" style="filter:drop-shadow(0 0 1.6px rgba(255,255,255,.18))"/>
<polyline points="{ppts}" stroke="{tok['--fg']}" style="filter:drop-shadow(0 0 1.6px rgba({tok['--rgb']},.6))"/>
</g></svg></div>"""


async def main():
    check_only = "--check" in sys.argv
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx, pg, errs = await open_page(browser)
        tok = await pg.evaluate("t => Object.fromEntries(t.map(k => [k, getComputedStyle(document.documentElement).getPropertyValue(k).trim()]))",
                                list(TOKENS))
        theme = await pg.evaluate("document.documentElement.dataset.phosphor")
        await ctx.close()
        if errs:
            sys.exit("page errors: " + "; ".join(errs))
        print(f"theme {theme}, tokens {tok}")
        tpts, ppts, box = curves()
        dest = OUT if check_only else REPO / "icons"
        dest.mkdir(exist_ok=True)
        for name, size, kind in FILES:
            src = OUT / f"icon_source_{kind}_{size}.html"
            src.write_text(page(tok, size, kind, tpts, ppts, box), encoding="utf-8")
            p = await browser.new_page(viewport={"width": size, "height": size})
            await p.goto(src.as_uri())
            await p.screenshot(path=str(dest / name), omit_background=(kind == "any"))
            await p.close()
            print(f"{dest / name}  {size}x{size}  {kind}")
        await browser.close()


asyncio.run(main())

"""Renders og.png, the 1200x630 link-preview image (Open Graph / Twitter card) at the repo root.

  python tools/og.py            # writes og.png next to index.html
  python tools/og.py --check    # only prints the measurements, writes nothing to the repo

It is the page's own VIRTUAL DYNO banner (the stacked variant, which fills a 1.9:1 card better than the one-row
one and stays legible when a chat app shrinks it), set in the self-hosted VT323 on the page's own screen look: the
default (color) theme's colors, the glow, scanlines and vignette. The banner text and colors are read from
index.html, so run this again after changing the art or the palette, then commit og.png. Needs Pillow
(pip install pillow) as well as Playwright.
"""
import asyncio
import sys

from PIL import Image
from playwright.async_api import async_playwright

from common import OUT, REPO, open_page

W, H, MARGIN = 1200, 630, 64
FONT = REPO / "fonts" / "vt323-latin-400-normal.woff2"
TOKENS = ("--desk", "--bg", "--fg", "--hi", "--dim", "--halo", "--rgb")


async def read_page(browser):
    # 400px wide is a phone, where the stacked banner is the one shown
    ctx, pg, errs = await open_page(browser, width=400)
    art = await pg.evaluate("document.querySelector('.art.stack').textContent")
    theme = await pg.evaluate("document.documentElement.dataset.phosphor")
    tok = await pg.evaluate("t => Object.fromEntries(t.map(k => [k, getComputedStyle(document.documentElement).getPropertyValue(k).trim()]))",
                            list(TOKENS))
    await ctx.close()
    if errs:
        sys.exit("page errors: " + "; ".join(errs))
    lines = art.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines, theme, tok


def source(lines, tok, size):
    k = size / 28          # the page's banner glow is defined for 28px
    art = "\n".join(lines).replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:VT323;src:url("{FONT.as_uri()}") format("woff2")}}
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:{tok['--desk']}}}
.scr{{position:absolute;inset:0;background:radial-gradient(900px 520px at 50% -60px,{tok['--halo']},transparent 70%),{tok['--bg']}}}
.frame{{position:absolute;inset:20px;border:2px solid {tok['--dim']};border-radius:12px;
  box-shadow:inset 0 0 90px rgba({tok['--rgb']},.07),0 0 70px rgba({tok['--rgb']},.14)}}
pre{{margin:0;position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);font:400 {size}px/.8 VT323;
  color:{tok['--hi']};white-space:pre;text-shadow:0 0 {6*k:.1f}px {tok['--fg']},0 0 {22*k:.1f}px rgba({tok['--rgb']},.45)}}
.crt{{position:absolute;inset:0;background:repeating-linear-gradient(transparent 0 2px,rgba(0,0,0,.17) 2px 3px),
  radial-gradient(ellipse at 50% 45%,transparent 58%,rgba(0,0,0,.5))}}
</style><div class="scr"></div><div class="frame"></div><pre id="art">{art}</pre><div class="crt"></div>"""


async def main():
    check_only = "--check" in sys.argv
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        lines, theme, tok = await read_page(browser)
        cols, rows = max(len(x) for x in lines), len(lines)
        # a VT323 cell is 0.4em wide and, at line-height .8, 0.8em tall
        size = int(min((W - 2 * MARGIN) / (cols * 0.4), (H - 2 * MARGIN) / (rows * 0.8)))
        print(f"banner {cols} columns x {rows} rows, theme {theme}, font {size}px, tokens {tok}")
        src = OUT / "og_source.html"
        src.write_text(source(lines, tok, size), encoding="utf-8")
        pg = await browser.new_page(viewport={"width": W, "height": H})
        await pg.goto(src.as_uri())
        await pg.evaluate("document.fonts.ready")
        await pg.wait_for_timeout(300)
        loaded = await pg.evaluate(f"document.fonts.check('{size}px VT323')")
        box = await pg.evaluate("(() => { const r = document.getElementById('art').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round) })()")
        print(f"VT323 loaded: {loaded}; banner box {box} inside {W}x{H}")
        if not loaded:
            sys.exit("VT323 did not load, so the image would use a fallback font")
        if box[0] < 20 or box[1] < 20 or box[2] > W - 20 or box[3] > H - 20:
            sys.exit("the banner does not fit inside the frame")
        out = OUT / "og_check.png" if check_only else REPO / "og.png"
        await pg.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": W, "height": H})
        # 256 colors looks the same here and keeps the file under ~300 KB (some chat apps skip bigger previews)
        Image.open(out).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(out, optimize=True)
        print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
        await browser.close()


asyncio.run(main())

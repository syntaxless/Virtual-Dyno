"""Quick visual check: screenshot the page at one or more widths.

  python tools/shot.py                           # 1200 and 375 wide, top of page
  python tools/shot.py --scroll bottom           # footer area
  python tools/shot.py --scroll .notes           # scroll a CSS selector into view
  python tools/shot.py --widths 375              # Car & Conditions is open by default (--expand just makes sure)
  python tools/shot.py --click '#howtg' --full   # with "How It Works" open
  python tools/shot.py --theme green --full      # green theme, whole page (the default is color)
  python tools/shot.py --gpx                     # with the synthetic GPS track loaded
  python tools/shot.py --log /path/to/log.csv    # with a real Accessport log
  python tools/shot.py --nofont --full           # as it looks if the VT323 file fails to load

Images are written to tools/out/ and their paths are printed.
"""
import argparse
import asyncio

from playwright.async_api import async_playwright

from common import COUNTUP_MS, GPX, OUT, open_page


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--widths", default="1200,375")
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--scroll", default="top", help="top | bottom | <css selector>")
    ap.add_argument("--expand", action="store_true", help="make sure Car & Conditions is open (it is open by default)")
    ap.add_argument("--click", action="append", default=[], metavar="SELECTOR",
                    help="click an element before the screenshot, e.g. --click '#howtg' (repeatable)")
    ap.add_argument("--theme", choices=["green", "color"])
    ap.add_argument("--full", action="store_true", help="full-page screenshot")
    ap.add_argument("--gpx", action="store_true", help="load the synthetic GPS track")
    ap.add_argument("--log", help="load an Accessport .csv")
    ap.add_argument("--nofont", action="store_true", help="block the font file (fallback look)")
    ap.add_argument("--name", default="shot")
    a = ap.parse_args()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for w in [int(x) for x in a.widths.split(",")]:
            ctx, pg, errs = await open_page(browser, width=w, height=a.height, expand=a.expand, block_font=a.nofont)
            if a.theme:
                await pg.click(f'#phos button[data-p="{a.theme}"]')
            for sel in a.click:
                await pg.click(sel)
            if a.log:
                await pg.set_input_files("#file", a.log)
            if a.gpx:
                await pg.set_input_files("#gps", GPX)
            if a.log or a.gpx:
                await pg.wait_for_timeout(COUNTUP_MS)
            if a.scroll == "bottom":
                await pg.evaluate("window.scrollTo(0,document.body.scrollHeight)")
            elif a.scroll != "top":
                await pg.evaluate("s=>document.querySelector(s).scrollIntoView()", a.scroll)
            await pg.wait_for_timeout(200)
            path = OUT / f"{a.name}_{w}.png"
            await pg.screenshot(path=str(path), full_page=a.full)
            print(path, "| page errors:", errs or "none")
            await ctx.close()
        await browser.close()


asyncio.run(main())

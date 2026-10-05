"""Shared helpers for the browser checks in this folder.

Run any script from anywhere:  python tools/<script>.py
Requires: pip install playwright && playwright install chromium
"""
import os
import pathlib

TOOLS = pathlib.Path(__file__).resolve().parent
REPO = TOOLS.parent
# DYNO_PAGE lets you point the checks at a candidate file instead of the repo's index.html
URL = pathlib.Path(os.environ.get("DYNO_PAGE") or REPO / "index.html").resolve().as_uri()
OUT = TOOLS / "out"            # screenshots land here (git-ignored)
OUT.mkdir(exist_ok=True)

GPX = str(TOOLS / "data" / "synthetic.gpx")   # synthetic GPS track, safe to commit
LOG = os.environ.get("DYNO_LOG")              # optional: path to a real Cobb Accessport .csv (never commit one)

COUNTUP_MS = 2600   # the big numbers count up for ~1.5 s; wait this long before reading them


def init_script(expand=False):
    """JS injected before the page runs.

    - seeds sessionStorage so the boot-in animation is skipped (it would make screenshots flaky)
    - optionally opens the collapsed "Car & Conditions" section
    """
    js = "try{sessionStorage.setItem('dyno-boot','1')}catch(e){};"
    if expand:
        js += ("document.addEventListener('DOMContentLoaded',()=>{const t=document.getElementById('condtg');"
               "if(t)t.click()});")
    return js


async def open_page(browser, width=1200, height=900, expand=False, reduced_motion=True, seed_boot=True,
                    block_font=False, **ctx_kw):
    """Open index.html in a fresh context. Returns (context, page, errors).

    block_font=True makes the .woff2 request fail, to see the page the way a visitor would if the font could not load.
    """
    ctx = await browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion="reduce" if reduced_motion else "no-preference",
        **ctx_kw)
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and "ERR_" not in m.text and "Failed to load" not in m.text else None)
    if block_font:
        await page.route("**/*.woff2", lambda r: r.abort())
    if seed_boot:
        await page.add_init_script(init_script(expand))
    elif expand:
        raise ValueError("expand requires seed_boot=True")
    await page.goto(URL)
    await page.wait_for_timeout(300)
    return ctx, page, errors

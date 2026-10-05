"""Self-contained smoke test: needs no data files. Exit code 1 if anything fails.

  python tools/smoke.py

Checks layout at phone/tablet/desktop widths (including which banner variant shows, Load Data full width with its two upload boxes side by side or stacked), the collapsible
Car & Conditions and How It Works sections, the one-line SAE checkbox, theme switching/persistence,
the boot-in animation gate, and the self-hosted font (loads from the site, nothing third-party is
requested, and the page degrades to a plain heading when the font file cannot load).
"""
import asyncio
import sys

from playwright.async_api import async_playwright

from common import open_page

WIDTHS = (320, 375, 480, 600, 768, 1024, 1100, 1200)
BANNER = {320: "stack", 375: "stack", 480: "stack", 600: "row", 768: "row", 1024: "row", 1100: "row", 1200: "row"}   # phones: stacked; wider: one row
BESIDE = (1100, 1200)   # from a 1000px-wide header (about a 1084px window) the banner sits to the right of the car; below that it sits under it

# Layout facts measured in the page: horizontal overflow, banner variant and fit, SAE label on one line.
LAYOUT = """(()=>{
  const shown=[...document.querySelectorAll('.art')].filter(a=>a.offsetParent!==null), art=shown[0];
  const l=document.querySelector('label.chk');
  const lh=parseFloat(getComputedStyle(l).lineHeight);
  const lines=Math.round(l.getBoundingClientRect().height/lh);   // label height / line height (ignores the hidden 1px input)
  return {sw:document.documentElement.scrollWidth, vw:innerWidth,
          shown:shown.length, artMode:art&&art.classList.contains('row')?'row':'stack', artOver:art?art.scrollWidth-art.clientWidth:999,
          artL:art?Math.round(art.getBoundingClientRect().left):-999, artT:art?Math.round(art.getBoundingClientRect().top):-999,
          artB:art?Math.round(art.getBoundingClientRect().bottom):-999, artPx:art?parseFloat(getComputedStyle(art).fontSize):0,
          stageL:Math.round(document.querySelector('.stage').getBoundingClientRect().left),
          stageR:Math.round(document.querySelector('.stage').getBoundingClientRect().right),
          stageT:Math.round(document.querySelector('.stage').getBoundingClientRect().top),
          stageB:Math.round(document.querySelector('.stage').getBoundingClientRect().bottom),
          loadW:Math.round(document.querySelector('.load').getBoundingClientRect().width),mainW:Math.round(document.querySelector('.main').getBoundingClientRect().width),
          loadAbove:Math.round(document.querySelector('.main').getBoundingClientRect().top-document.querySelector('.load').getBoundingClientRect().bottom),
          dropRowDiff:Math.round(document.getElementById('gdrop').getBoundingClientRect().top-document.getElementById('drop').getBoundingClientRect().top),
          howGap:Math.round(document.querySelector('.how').getBoundingClientRect().top-document.querySelector('.cond').getBoundingClientRect().bottom),
          saeLines:lines, saeOver:Math.round(l.lastElementChild.getBoundingClientRect().right-l.parentNode.getBoundingClientRect().right)};
})()"""

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


async def layout(browser):
    for w in WIDTHS:
        ctx, pg, errs = await open_page(browser, width=w, expand=True)
        m = await pg.evaluate(LAYOUT)
        check(f"{w}px: no page errors", not errs, "; ".join(errs))
        check(f"{w}px: no horizontal scroll", m["sw"] <= m["vw"], f"scrollWidth {m['sw']} vs {m['vw']}")
        check(f"{w}px: exactly one banner shown, the {BANNER[w]} one", m["shown"] == 1 and m["artMode"] == BANNER[w],
              f"{m['shown']} shown, mode {m['artMode']}")
        check(f"{w}px: ASCII art fits", m["artOver"] <= 1, f"overflow {m['artOver']}px")
        if w in BESIDE:
            check(f"{w}px: the banner sits to the right of the car, side by side, and is still legible",
                  m["artL"] >= m["stageR"] and m["artT"] < m["stageB"] and m["artB"] > m["stageT"] and m["artPx"] >= 13
                  and m["artL"] - m["stageR"] >= 8,
                  f"banner x {m['artL']}..., car right edge {m['stageR']}, banner y {m['artT']}-{m['artB']}, car y {m['stageT']}-{m['stageB']}, {m['artPx']:.1f}px font")
        else:
            check(f"{w}px: car animation sits above the banner and inside the screen",
                  m["artT"] >= m["stageB"] and m["stageR"] <= m["vw"], f"banner top {m['artT']}, car bottom {m['stageB']}, car right edge {m['stageR']}")
        check(f"{w}px: Load Data is full width, above the results", abs(m["loadW"] - m["mainW"]) <= 1 and m["loadAbove"] >= 0,
              f"load {m['loadW']}px vs results {m['mainW']}px, {m['loadAbove']}px above")
        if w >= 768:
            check(f"{w}px: the two upload boxes sit side by side", m["dropRowDiff"] == 0, f"top offset {m['dropRowDiff']}px")
        if w <= 480:
            check(f"{w}px: the two upload boxes stack on a phone", m["dropRowDiff"] > 20, f"top offset {m['dropRowDiff']}px")
        check(f"{w}px: How It Works sits below Car & Conditions", m["howGap"] >= 0, f"{m['howGap']}px below")
        check(f"{w}px: SAE checkbox label on one line", m["saeLines"] == 1 and m["saeOver"] <= 0,
              f"{m['saeLines']} line(s), {m['saeOver']}px past column")
        await ctx.close()


async def collapsible(browser):
    ctx, pg, errs = await open_page(browser)           # not pre-expanded
    for name, tg, body in (("Car & Conditions", "condtg", "condbody"), ("How It Works", "howtg", "howbody")):
        st = lambda: pg.evaluate(f"[document.getElementById('{tg}').getAttribute('aria-expanded'),"
                                 f"document.getElementById('{body}').hidden]")
        check(f"{name} starts collapsed", await st() == ["false", True])
        await pg.click(f"#{tg}")
        check(f"{name} opens", await st() == ["true", False])
        await pg.click(f"#{tg}")
        check(f"{name} closes again", await st() == ["false", True])
    # How It Works text uses the whole width of its section (no narrow column with a gap beside it)
    await pg.click("#howtg")
    wd = await pg.evaluate("[document.querySelector('#howbody p').getBoundingClientRect().width,"
                           "document.getElementById('howbody').getBoundingClientRect().width]")
    check("How It Works text fills the section width", wd[0] >= wd[1] - 2, f"text {wd[0]:.0f}px of {wd[1]:.0f}px")
    await ctx.close()


async def sae_checkbox(browser):
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.click("label.chk span:last-child")
    on_text = await pg.is_checked("#sae")
    await pg.click("label.chk .bx")
    off_box = not await pg.is_checked("#sae")
    await pg.focus("#sae")
    await pg.keyboard.press("Space")
    on_kbd = await pg.is_checked("#sae")
    check("SAE checkbox toggles by label text, [X] box and Space key", on_text and off_box and on_kbd,
          f"text:{on_text} box-off:{off_box} space:{on_kbd}")
    await ctx.close()


async def themes(browser):
    ctx, pg, errs = await open_page(browser)
    ph = lambda: pg.evaluate("document.documentElement.dataset.phosphor||''")
    await pg.click('#phos button[data-p="color"]')
    check("color theme applies", await ph() == "color")
    await pg.reload(); await pg.wait_for_timeout(300)
    check("color theme persists across reload", await ph() == "color")
    await pg.click('#phos button[data-p="green"]')
    check("green theme restores", await ph() != "color")
    await pg.evaluate("localStorage.setItem('dyno-phosphor','red')")   # a theme that no longer exists
    await pg.reload(); await pg.wait_for_timeout(300)
    check("removed theme in storage falls back to green without errors", await ph() != "red" and not errs, "; ".join(errs))
    await ctx.close()


async def boot(browser):
    ctx, pg, errs = await open_page(browser, reduced_motion=False, seed_boot=False)
    has = lambda: pg.evaluate("document.documentElement.classList.contains('bt')")
    check("first visit plays the boot-in animation", await has())
    await pg.wait_for_timeout(2600)
    check("boot-in animation cleans itself up", not await has())
    await ctx.close()
    ctx, pg, errs = await open_page(browser, reduced_motion=True, seed_boot=False)
    check("reduced-motion visitors skip the boot-in", not await has())
    await ctx.close()


async def font(browser):
    # Normal load: VT323 comes from fonts/ next to the page, and nothing leaves the site.
    ctx, pg, errs = await open_page(browser, width=375)
    urls = []
    pg.on("request", lambda r: urls.append(r.url))
    await pg.reload(); await pg.wait_for_timeout(600)
    f = await pg.evaluate("""(async()=>{await document.fonts.ready;
      const face=[...document.fonts].find(x=>x.family.replace(/"/g,'')==='VT323');
      return {status:face&&face.status, check:document.fonts.check('20px VT323','0'),
              nofont:document.documentElement.classList.contains('nofont')}})()""")
    check("VT323 loads from the site's fonts/ folder", f["status"] == "loaded" and f["check"] and not f["nofont"], str(f))
    check("the font file was requested from the site", any(u.endswith(".woff2") and "/fonts/" in u for u in urls),
          "; ".join(u for u in urls if u.endswith(".woff2")) or "no .woff2 request")
    outside = [u for u in urls if u.startswith(("http:", "https:"))]
    check("no third-party requests on load", not outside, "; ".join(outside))
    await ctx.close()

    # Font file blocked: the ASCII banners (which need VT323's width) give way to a plain heading.
    for w in (375, 1200):
        ctx, pg, errs = await open_page(browser, width=w, block_font=True)
        m = await pg.evaluate("""(()=>{const h=document.querySelector('h1.vh').getBoundingClientRect();
          return {nofont:document.documentElement.classList.contains('nofont'),
                  art:[...document.querySelectorAll('.art')].filter(a=>a.offsetParent!==null).length,
                  h:Math.round(h.height), hr:Math.round(h.right),
                  sw:document.documentElement.scrollWidth, vw:innerWidth}})()""")
        check(f"{w}px, font blocked: banners give way to a visible heading, no overflow",
              m["nofont"] and m["art"] == 0 and m["h"] > 10 and m["sw"] <= m["vw"] and m["hr"] <= m["vw"] and not errs,
              f"{m} errors: {errs}")
        await ctx.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for step in (layout, collapsible, sae_checkbox, themes, boot, font):
            await step(browser)
        await browser.close()
    bad = results.count(False)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)


asyncio.run(main())

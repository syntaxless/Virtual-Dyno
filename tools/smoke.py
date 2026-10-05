"""Self-contained smoke test: needs no data files. Exit code 1 if anything fails.

  python tools/smoke.py

Checks layout at phone/tablet/desktop widths (including which banner variant shows), the collapsible
Car & Conditions and How It Works sections, the one-line SAE checkbox, theme switching/persistence,
and the boot-in animation gate.
"""
import asyncio
import sys

from playwright.async_api import async_playwright

from common import open_page

WIDTHS = (320, 375, 480, 600, 768, 1200)
BANNER = {320: "stack", 375: "stack", 480: "stack", 600: "row", 768: "row", 1200: "row"}   # phones: stacked; wide: one row

# Layout facts measured in the page: horizontal overflow, banner variant and fit, SAE label on one line.
LAYOUT = """(()=>{
  const shown=[...document.querySelectorAll('.art')].filter(a=>a.offsetParent!==null), art=shown[0];
  const l=document.querySelector('label.chk');
  const lh=parseFloat(getComputedStyle(l).lineHeight);
  const lines=Math.round(l.getBoundingClientRect().height/lh);   // label height / line height (ignores the hidden 1px input)
  return {sw:document.documentElement.scrollWidth, vw:innerWidth,
          shown:shown.length, artMode:art&&art.classList.contains('row')?'row':'stack', artOver:art?art.scrollWidth-art.clientWidth:999,
          stageGap:art?Math.round(art.getBoundingClientRect().top-document.querySelector('.stage').getBoundingClientRect().bottom):-999,
          stageRight:Math.round(document.querySelector('.stage').getBoundingClientRect().right),
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
        check(f"{w}px: car animation sits above the banner and inside the screen",
              m["stageGap"] >= 0 and m["stageRight"] <= m["vw"], f"gap {m['stageGap']}px, right edge {m['stageRight']}")
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
    check("the estimates-only line stays visible while How It Works is collapsed",
          await pg.evaluate("document.querySelector('.notes .est').offsetParent!==null"))
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


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for step in (layout, collapsible, sae_checkbox, themes, boot):
            await step(browser)
        await browser.close()
    bad = results.count(False)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)


asyncio.run(main())

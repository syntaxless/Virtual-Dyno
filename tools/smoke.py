"""Self-contained smoke test: needs no data files. Exit code 1 if anything fails.

  python tools/smoke.py

Checks layout at phone/tablet/desktop widths, the collapsible Car & Conditions section,
the one-line SAE checkbox, theme switching/persistence, and the boot-in animation gate.
"""
import asyncio
import sys

from playwright.async_api import async_playwright

from common import open_page

WIDTHS = (320, 375, 768, 1200)

# Layout facts measured in the page: horizontal overflow, ASCII art fit, SAE label on one line.
LAYOUT = """(()=>{
  const art=document.querySelector('.art'), l=document.querySelector('label.chk');
  const lh=parseFloat(getComputedStyle(l).lineHeight);
  const lines=Math.round(l.getBoundingClientRect().height/lh);   // label height / line height (ignores the hidden 1px input)
  return {sw:document.documentElement.scrollWidth, vw:innerWidth,
          artOver:art.scrollWidth-art.clientWidth,
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
        check(f"{w}px: ASCII art fits", m["artOver"] <= 1, f"overflow {m['artOver']}px")
        check(f"{w}px: SAE checkbox label on one line", m["saeLines"] == 1 and m["saeOver"] <= 0,
              f"{m['saeLines']} line(s), {m['saeOver']}px past column")
        await ctx.close()


async def collapsible(browser):
    ctx, pg, errs = await open_page(browser)           # not pre-expanded
    st = lambda: pg.evaluate("[document.getElementById('condtg').getAttribute('aria-expanded'),"
                             "document.getElementById('condbody').hidden]")
    check("Car & Conditions starts collapsed", await st() == ["false", True])
    await pg.click("#condtg")
    check("Car & Conditions opens", await st() == ["true", False])
    await pg.click("#condtg")
    check("Car & Conditions closes again", await st() == ["false", True])
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

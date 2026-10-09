"""Self-contained smoke test: needs no data files. Exit code 1 if anything fails.

  python tools/smoke.py [step ...]      (no step names: run everything; e.g. `print_button` runs just that one)

Checks layout at phone/tablet/desktop widths (including which banner variant shows, Load Data full width with its two upload boxes side by side or stacked), the collapsible
Car & Conditions and How It Works sections, the Power Correction dropdown, the one-line place-date-time weather row, tile text colors and layout (four across, two by two, one column), units in capitals, theme switching/persistence,
the boot-in animation gate, and the self-hosted font (loads from the site, nothing third-party is
requested, and the page degrades to a plain heading when the font file cannot load), and real-time Replay
(takes as long as the pull did, live readout, click to skip), and the Print button (a JPEG of the same size on any screen), and the installable web app (manifest, icons, theme color, and a service
worker that, served from a local http server, keeps the page working offline and still shows a new deploy at once).
"""
import asyncio
import functools
import http.server
import json
import pathlib
import re
import sys
import threading
import time

from playwright.async_api import async_playwright

from common import GPX, REPO, init_script, open_page

WIDTHS = (320, 375, 480, 600, 768, 1024, 1100, 1200)
BANNER = {320: "stack", 375: "stack", 480: "stack", 600: "row", 768: "row", 1024: "row", 1100: "row", 1200: "row"}   # phones: stacked; wider: one row
BESIDE = (1100, 1200)   # from a 1000px-wide header (about a 1084px window) the banner sits to the right of the car; below that it sits under it

# Layout facts measured in the page: horizontal overflow, banner variant and fit, Power Correction dropdown inside its column.
LAYOUT = """(()=>{
  const shown=[...document.querySelectorAll('.art')].filter(a=>a.offsetParent!==null), art=shown[0];
  const cs=document.getElementById('corr').getBoundingClientRect(), ss=document.getElementById('spd').getBoundingClientRect();
  const col=document.getElementById('corr').closest('.opts').getBoundingClientRect();
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
          introW:Math.round(document.querySelector('.head p').getBoundingClientRect().width),hgrpW:Math.round(document.querySelector('.hgrp').getBoundingClientRect().width),
          hintW:Math.round(document.querySelector('.load .hint').getBoundingClientRect().width),
          dropsW:Math.round(document.querySelector('.drops').getBoundingClientRect().width),
          dropRowDiff:Math.round(document.getElementById('gdrop').getBoundingClientRect().top-document.getElementById('drop').getBoundingClientRect().top),
          howGap:Math.round(document.querySelector('.how').getBoundingClientRect().top-document.querySelector('.cond').getBoundingClientRect().bottom),
          corrOver:Math.round(cs.right-col.right), corrW:Math.round(cs.width), spdW:Math.round(ss.width)};
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
        check(f"{w}px: Load Data hint lines use the full section width", m["hintW"] >= m["dropsW"] - 2,
              f"hint {m['hintW']}px, upload row {m['dropsW']}px")
        if w > 600:
            check(f"{w}px: the intro line uses the full header width", m["introW"] >= m["hgrpW"] - 2,
                  f"intro {m['introW']}px of {m['hgrpW']}px")
        if w >= 768:
            check(f"{w}px: the two upload boxes sit side by side", m["dropRowDiff"] == 0, f"top offset {m['dropRowDiff']}px")
        if w <= 480:
            check(f"{w}px: the two upload boxes stack on a phone", m["dropRowDiff"] > 20, f"top offset {m['dropRowDiff']}px")
        check(f"{w}px: How It Works sits below Car & Conditions", m["howGap"] >= 0, f"{m['howGap']}px below")
        check(f"{w}px: Power Correction dropdown stays inside its column and matches the Speed Source dropdown",
              m["corrOver"] <= 0 and abs(m["corrW"] - m["spdW"]) <= 1,
              f"{m['corrOver']}px past the column, {m['corrW']}px wide vs {m['spdW']}px")
        await ctx.close()


async def collapsible(browser):
    ctx, pg, errs = await open_page(browser)           # the page as a visitor first sees it
    # Car & Conditions starts open (its fields are there at load); How It Works starts collapsed
    shown = await pg.evaluate("['#fhp', '#curb', '#corr'].map(q => document.querySelector(q).getClientRects().length > 0)")
    check("Car & Conditions fields are visible at load, with no click", all(shown), str(shown))
    for name, tg, body, open0 in (("Car & Conditions", "condtg", "condbody", True), ("How It Works", "howtg", "howbody", False)):
        st = lambda: pg.evaluate(f"[document.getElementById('{tg}').getAttribute('aria-expanded'),"
                                 f"document.getElementById('{body}').hidden]")
        a, b = (["true", False], ["false", True]) if open0 else (["false", True], ["true", False])
        check(f"{name} starts {'open' if open0 else 'collapsed'}", await st() == a)
        await pg.click(f"#{tg}")
        check(f"{name} {'closes' if open0 else 'opens'}", await st() == b)
        await pg.click(f"#{tg}")
        check(f"{name} goes back", await st() == a)
    # How It Works text uses the whole width of its section (no narrow column with a gap beside it)
    await pg.click("#howtg")
    wd = await pg.evaluate("[document.querySelector('#howbody p').getBoundingClientRect().width,"
                           "document.getElementById('howbody').getBoundingClientRect().width]")
    check("How It Works text fills the section width", wd[0] >= wd[1] - 2, f"text {wd[0]:.0f}px of {wd[1]:.0f}px")
    await ctx.close()


async def correction_select(browser):
    ctx, pg, errs = await open_page(browser, expand=True)
    opts = await pg.evaluate("[...document.querySelectorAll('#corr option')].map(o => [o.value, o.textContent])")
    check("Power Correction offers Uncorrected, SAE J1349, SAE J607, DIN 70020 and ISO 1585, in that order",
          [o[0] for o in opts] == ["none", "j1349", "j607", "din", "iso"] and [o[1] for o in opts][0] == "Uncorrected", str(opts))
    check("Power Correction defaults to Uncorrected", await pg.input_value("#corr") == "none")
    # a native select: reachable by keyboard and by value, and each choice sticks
    got = []
    for v in ("j1349", "j607", "din", "iso", "none"):
        await pg.select_option("#corr", v)
        got.append(await pg.input_value("#corr"))
    check("Power Correction takes each of the five choices", got == ["j1349", "j607", "din", "iso", "none"], str(got))
    await pg.focus("#corr")
    await pg.keyboard.press("ArrowDown")
    check("Power Correction can be changed from the keyboard", await pg.input_value("#corr") != "none")
    check("the old SAE checkbox is gone", await pg.evaluate("!document.getElementById('sae') && !document.querySelector('label.chk')"))
    check("no page errors while changing the correction", not errs, "; ".join(errs))
    await ctx.close()


async def no_pulls_message(browser):
    """When no pull is found the page says so in red, once; the line goes away when pulls come back and does not pile up."""
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.click("#demo")
    await pg.wait_for_timeout(800)
    state = lambda: pg.evaluate("""({n: document.querySelectorAll('#nopull').length,
        red: document.querySelector('#nopull') && getComputedStyle(document.querySelector('#nopull')).color,
        err: (() => { const t = document.createElement('i'); t.style.color = getComputedStyle(document.documentElement).getPropertyValue('--err'); document.body.append(t); const c = getComputedStyle(t).color; t.remove(); return c })(),
        plain: getComputedStyle(document.getElementById('msg')).color})""")
    check("with pulls found there is no no-pulls line", (await state())["n"] == 0)
    await pg.fill("#ped", "101")             # nothing reaches a 101% pedal
    await pg.wait_for_timeout(500)
    st = await state()
    check("no pulls found: the message shows once, in the error red (not the plain message color)",
          st["n"] == 1 and st["red"] == st["err"] and st["red"] != st["plain"], str(st))
    await pg.fill("#ped", "102")
    await pg.wait_for_timeout(500)
    check("changing the setting again does not repeat the message", (await state())["n"] == 1, str(await state()))
    await pg.fill("#ped", "90")
    await pg.wait_for_timeout(500)
    check("the message goes away when pulls are found again", (await state())["n"] == 0 and "Pull 1" in await pg.inner_text("#pull"))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def themes(browser):
    ctx, pg, errs = await open_page(browser)
    ph = lambda: pg.evaluate("document.documentElement.dataset.phosphor||''")
    pressed = lambda: pg.evaluate("[...document.querySelectorAll('#phos button')].filter(b=>b.getAttribute('aria-pressed')=='true').map(b=>b.dataset.p)")
    check("the color theme is the default", await ph() == "color" and await pressed() == ["color"], f"{await ph()} {await pressed()}")
    await pg.click('#phos button[data-p="green"]')
    check("green theme applies", await ph() == "green" and await pressed() == ["green"])
    await pg.reload(); await pg.wait_for_timeout(300)
    check("a chosen green theme persists across reload", await ph() == "green" and await pressed() == ["green"])
    await pg.click('#phos button[data-p="color"]')
    check("color theme restores", await ph() == "color" and await pressed() == ["color"])
    await pg.evaluate("localStorage.setItem('dyno-phosphor','red')")   # a theme that no longer exists
    await pg.reload(); await pg.wait_for_timeout(300)
    check("removed theme in storage falls back to color without errors", await ph() == "color" and not errs, "; ".join(errs))
    await ctx.close()
    # storage blocked (private modes, some embeds): still the color default, no errors
    ctx, pg, errs = await open_page(browser)
    await ctx.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked')}})")
    await pg.reload(); await pg.wait_for_timeout(300)
    check("with storage blocked the page still starts in color, without errors", await ph() == "color" and not errs, f"{await ph()} {errs}")
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


async def load_message(browser):
    """The line shown after a file is loaded uses the whole Load Data width (it used to stop at 90ch)."""
    for w in (375, 768, 1200):
        ctx, pg, errs = await open_page(browser, width=w)
        await pg.click("#demo")
        await pg.wait_for_timeout(300)
        m = await pg.evaluate("""({msg:Math.round(document.getElementById('msg').getBoundingClientRect().width),
            drops:Math.round(document.querySelector('.drops').getBoundingClientRect().width),
            chars:document.getElementById('msg').textContent.length})""")
        check(f"{w}px: the message after loading a file uses the full Load Data width",
              m["chars"] > 0 and m["msg"] >= m["drops"] - 2 and not errs, f"{m} {errs}")
        # the weather block under it: its hint and its message run the full width too, but the form controls stay form-sized
        await pg.click("#wxpget")           # no place typed yet, so a short message appears
        await pg.wait_for_timeout(200)
        wx = await pg.evaluate("""({hints:[...document.querySelectorAll('#wxpl .hint')].map(e=>Math.round(e.getBoundingClientRect().width)),
            msg:Math.round(document.getElementById('wxmsg').getBoundingClientRect().width),chars:document.getElementById('wxmsg').textContent.length,
            place:Math.round(document.getElementById('wxplace').getBoundingClientRect().width),
            row:Math.round(document.querySelector('#wxpl .wr').getBoundingClientRect().width)})""")
        check(f"{w}px: the weather hints and message use the full Load Data width",
              wx["chars"] > 0 and wx["hints"] and all(x >= m["drops"] - 2 for x in wx["hints"]) and wx["msg"] >= m["drops"] - 2, f"{wx}, section {m['drops']}px")
        check(f"{w}px: the weather form fields stay form-sized (the place box 560px at most, the place-date-time row 640px)", wx["place"] <= 561 and wx["row"] <= 641, f"{wx}")
        await ctx.close()


async def weather_row(browser):
    """Place, date and local time share one line from 700px up; below that the place box has a line to itself and
    date and time stay together under it. Nothing is cut off at either size (the date and time boxes keep room for their text)."""
    for w in (375, 600, 699, 700, 768, 1200):
        ctx, pg, errs = await open_page(browser, width=w)
        await pg.click("#demo")                  # the demo log has no GPS track, so the place form is the one shown
        await pg.wait_for_timeout(300)
        m = await pg.evaluate("""(() => { const r = q => document.querySelector(q).getBoundingClientRect(), a = r('#wxplace'), d = r('#wxdate'), t = r('#wxtime');
            return {top: [a.top, d.top, t.top].map(Math.round), w: [a.width, d.width, t.width].map(Math.round), right: Math.round(t.right), vw: innerWidth} })()""")
        if w >= 700:
            check(f"{w}px: place, date and time are on one line, with room for the date and time",
                  m["top"][0] == m["top"][1] == m["top"][2] and m["w"][0] >= 200 and m["w"][1] >= 150 and m["w"][2] >= 130 and m["right"] <= m["vw"], str(m))
        else:
            check(f"{w}px: place has its own line, and date and time share the one under it",
                  m["top"][0] < m["top"][1] == m["top"][2] and m["right"] <= m["vw"], str(m))
        check(f"{w}px: no page errors in the weather form", not errs, "; ".join(errs))
        await ctx.close()


async def tile_colors(browser):
    """Every piece of text in the four result tiles (Peak Crank Power, Peak Crank Torque, Peak Wheel Power, Peak Boost Pressure:
    title, number, unit, caption) is the same color, in both themes, and the four tiles keep four different colors."""
    ctx, pg, errs = await open_page(browser)
    await pg.click("#demo")
    await pg.wait_for_timeout(2600)
    for theme in ("color", "green"):
        await pg.click(f'#phos button[data-p="{theme}"]')
        got = await pg.evaluate("""['#s1','#s2','#s3','#s4'].map(id => { const t = document.querySelector(id), c = q => getComputedStyle(t.querySelector(q)).color;
            return {id, caption: t.querySelector('em').textContent.length > 0, colors: [c('legend'), c('b .n'), c('b i'), c('em')]} })""")
        for g in got:
            check(f"{theme} theme: {g['id']} title, number, unit and caption are all one color", g["caption"] and len(set(g["colors"])) == 1, str(g))
        check(f"{theme} theme: the four tiles keep four different colors", len({g["colors"][0] for g in got}) == 4, str([g["colors"][0] for g in got]))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def tile_layout(browser):
    """The four result tiles: four across from 941px up, two by two from 601 to 940, one column on phones (600 and below).
    Nothing pokes out of a tile (the unit after the big number stays inside its padding), the page does not scroll sideways,
    and Peak Boost Pressure is the last tile, on the same row as Peak Crank Power when there are four across."""
    JS = """() => { const q = [...document.querySelectorAll('.stat')], r = q.map(e => e.getBoundingClientRect());
        return {n: q.length, ids: q.map(e => e.id), cols: getComputedStyle(document.querySelector('.stats')).gridTemplateColumns.split(' ').length,
          tops: r.map(b => Math.round(b.top)), over: Math.max(...q.map((e, i) => Math.round(e.querySelector('i').getBoundingClientRect().right - (r[i].right - 14)))),
          hs: document.documentElement.scrollWidth - innerWidth} }"""
    ctx, pg, errs = await open_page(browser, width=1200)
    await pg.click("#demo")
    await pg.wait_for_timeout(500)
    for w, cols in ((1200, 4), (1000, 4), (941, 4), (940, 2), (768, 2), (601, 2), (600, 1), (375, 1)):
        await pg.set_viewport_size({"width": w, "height": 900})
        await pg.wait_for_timeout(120)
        m = await pg.evaluate(JS)
        check(f"{w}px: {cols} tile column{'s' if cols > 1 else ''}, in order, Peak Boost Pressure last",
              m["n"] == 4 and m["ids"] == ["s1", "s2", "s3", "s4"] and m["cols"] == cols and (cols != 4 or m["tops"][0] == m["tops"][3]), str(m))
        check(f"{w}px: nothing pokes out of a tile and the page does not scroll sideways", m["over"] <= 0 and m["hs"] <= 0, str(m))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def unit_case(browser):
    """RPM, MPH, HP and WHP are written in capitals everywhere the visitor reads them: the page text (How It Works open),
    the hover readout, and the labels the graph draws on its canvas. Run with a demo log (RPM axis) and with GPS only (MPH axis)."""
    import re
    bad = re.compile(r"\b(rpm|mph|hp|whp)\b")
    spy = ("(() => { window.__ft = []; const f = CanvasRenderingContext2D.prototype.fillText;"
           " CanvasRenderingContext2D.prototype.fillText = function (t, ...a) { window.__ft.push(String(t)); return f.call(this, t, ...a) } })()")
    for name, axis in (("demo log", "RPM"), ("GPS only", "MPH")):
        ctx, pg, errs = await open_page(browser, expand=True)
        await pg.evaluate(spy)
        if name == "demo log":
            await pg.click("#demo")
        else:
            await pg.set_input_files("#gps", GPX)
        await pg.wait_for_timeout(2600)
        await pg.click("#howtg")
        await pg.hover("#cv")
        await pg.wait_for_timeout(300)
        text = await pg.evaluate("document.body.innerText")
        drawn = await pg.evaluate("window.__ft")
        check(f"{name}: RPM, MPH, HP and WHP are capitals in the page text and the readout", not bad.findall(text), str(sorted(set(bad.findall(text)))))
        check(f"{name}: the graph's own labels are capitals, and its axis says {axis}",
              not any(bad.search(t) for t in drawn) and axis in drawn, str(sorted({t for t in drawn if not t.replace(',', '').replace('K', '').isdigit()})))
        check(f"{name}: no page errors", not errs, "; ".join(errs))
        await ctx.close()


async def link_preview(browser):
    """The link-unfurling image: the meta tags point at a real PNG of the stated size, on the site's own domain."""
    import struct
    ctx, pg, errs = await open_page(browser)
    m = await pg.evaluate("""(() => { const g = s => (document.querySelector(s) || {}).content || ''; return {
        og: g('meta[property="og:image"]'), tw: g('meta[name="twitter:image"]'), card: g('meta[name="twitter:card"]'),
        w: +g('meta[property="og:image:width"]'), h: +g('meta[property="og:image:height"]'),
        alt: g('meta[property="og:image:alt"]'), twalt: g('meta[name="twitter:image:alt"]')} })()""")
    await ctx.close()
    prefix = f"https://{(REPO / 'CNAME').read_text().strip()}/"
    f = REPO / m["og"][len(prefix):] if m["og"].startswith(prefix) and len(m["og"]) > len(prefix) else None
    data = f.read_bytes() if f and f.is_file() else b""
    png = data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24]) if png else (0, 0)
    check("link preview: og:image is an absolute URL on the site's own domain, and the file is in the repo", bool(data), f"{m['og']!r}")
    check("link preview: the file is a PNG whose real size matches og:image:width/height, in the wide-card shape",
          png and (w, h) == (m["w"], m["h"]) and 1.8 <= w / h <= 2.0, f"{w}x{h} vs {m['w']}x{m['h']}")
    check("link preview: small enough for chat apps that skip big previews (300 KB)", 0 < len(data) <= 300 * 1024, f"{len(data) / 1024:.0f} KB")
    check("link preview: the large Twitter card uses the same image and both have alt text",
          m["card"] == "summary_large_image" and m["tw"] == m["og"] and bool(m["alt"]) and bool(m["twalt"]), f"{m}")
    check("link preview: no page errors", not errs, "; ".join(errs))


async def realtime(browser):
    """Replay plays in real time: it takes as long as the pull did, shows a live readout, and a click skips it."""
    ctx, pg, errs = await open_page(browser, reduced_motion=False)
    await pg.click("#demo")
    r = await pg.evaluate("""()=>new Promise(res=>{
        const t0=performance.now(),span=cur[cur.length-1].tm-cur[0].tm,label=document.querySelector('#pull').selectedOptions[0].text;
        let live=false;const iv=setInterval(()=>{live=live||/\\d\\.\\d s ·/.test(document.getElementById('ro').textContent);
          if(grow>=1||performance.now()-t0>30000){clearInterval(iv);res({elapsed:(performance.now()-t0)/1000,span,label,live,
            end:/\\d\\.\\d s ·/.test(document.getElementById('ro').textContent)})}},20)})""")
    pull_s = float(r["label"].rsplit(",", 1)[1].split()[0])      # "Pull 1: 2,404-6,685 RPM, 9.6 s"
    check("Replay takes as long as the pull did (real time)", abs(r["elapsed"] - r["span"]) <= 0.5 and 0.8 * pull_s <= r["span"] <= pull_s + 0.1,
          f"played in {r['elapsed']:.1f} s, plotted span {r['span']:.1f} s, pull {pull_s} s")
    check("a live time/value readout shows while it plays, and goes away at the end", r["live"] and not r["end"], str(r))
    # play again: moving over the graph does not interrupt it, a click skips to the end
    await pg.click("#replay")
    await pg.wait_for_timeout(700)
    box = await pg.locator("#cv").bounding_box()
    await pg.mouse.move(box["x"] + box["width"] * .5, box["y"] + box["height"] * .5)
    await pg.wait_for_timeout(150)
    playing = await pg.evaluate("grow<1")
    await pg.mouse.down(); await pg.mouse.up()
    await pg.wait_for_timeout(150)
    done = await pg.evaluate("[grow, /\\d\\.\\d s ·/.test(document.getElementById('ro').textContent)]")
    await pg.wait_for_timeout(400)
    later = await pg.evaluate("grow")
    check("hovering the graph does not interrupt Replay; a click skips to the end", playing and done[0] == 1 and not done[1] and later == 1,
          f"still playing after hover {playing}, after click {done}, later {later}")
    check("no page errors during playback", not errs, "; ".join(errs))
    await ctx.close()
    # reduced motion: the whole curve at once
    ctx, pg, errs = await open_page(browser, reduced_motion=True)
    await pg.click("#demo")
    await pg.wait_for_timeout(200)
    g = await pg.evaluate("grow")
    check("reduced motion shows the whole curve at once", g == 1 and not errs, f"grow {g} {errs}")
    await ctx.close()


IMG_INK = """async b64 => {
  const im = new Image(); im.src = 'data:image/jpeg;base64,' + b64; await im.decode();
  const c = document.createElement('canvas'); c.width = im.width; c.height = im.height;
  const x = c.getContext('2d'); x.drawImage(im, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data;
  const bg = [d[0], d[1], d[2]]; let ink = 0;
  for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - bg[0]) + Math.abs(d[i + 1] - bg[1]) + Math.abs(d[i + 2] - bg[2]) > 30) ink++;
  const t = document.createElement('i'); t.style.backgroundColor = 'var(--bg)'; document.body.append(t);
  const page = getComputedStyle(t).backgroundColor; t.remove();
  return {bg: 'rgb(' + bg.join(', ') + ')', page, ink: ink / (d.length / 4)} }"""


# Pixels near a color in the top band of the saved image (the result tiles), counted in each quarter of its width.
IMG_TILES = """async ([b64, col]) => {
  const im = new Image(); im.src = 'data:image/jpeg;base64,' + b64; await im.decode();
  const c = document.createElement('canvas'); c.width = im.width; c.height = im.height;
  const x = c.getContext('2d'); x.drawImage(im, 0, 0);
  const t = document.createElement('i'); t.style.color = col; document.body.append(t);
  const m = getComputedStyle(t).color.match(/\\d+/g).map(Number); t.remove();
  const band = Math.round(c.height * 0.14), d = x.getImageData(0, 0, c.width, band).data, q = [0, 0, 0, 0];
  for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - m[0]) + Math.abs(d[i + 1] - m[1]) + Math.abs(d[i + 2] - m[2]) < 60) q[Math.min(3, Math.floor((i / 4 % c.width) / (c.width / 4)))]++;
  return q }"""


async def print_button(browser):
    """The Print button: next to Replay, off until there is a pull, and it saves one JPEG (under 600 KB) of the same size on
    any screen (page at its widest, twice over), in the current theme, with the fields even when Car & Conditions is
    collapsed, without any request to another site."""
    import base64
    import re
    import struct

    def jpeg_size(data):
        """(width, height) from the JPEG's start-of-frame marker, or (0, 0) when it is not a JPEG."""
        if data[:3] != b"\xff\xd8\xff":
            return 0, 0
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return 0, 0
            m, n = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if m in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + n
        return 0, 0

    def same_color(a, b, tol=4):
        """'rgb(r, g, b)' strings equal within a few levels (JPEG is lossy)."""
        x, y = ([int(v) for v in re.findall(r"\d+", c)[:3]] for c in (a, b))
        return all(abs(p - q) <= tol for p, q in zip(x, y))

    async def grab(pg):
        reqs = []
        pg.on("request", lambda r: reqs.append(r.url) if r.url.split(":", 1)[0] not in ("file", "data", "blob", "about") else None)
        async with pg.expect_download() as dl:
            await pg.click("#print")
        d = await dl.value
        data = pathlib.Path(await d.path()).read_bytes()
        w, h = jpeg_size(data)
        return d.suggested_filename, bool(w), w, h, base64.b64encode(data).decode(), reqs, len(data)

    sizes = {}
    for w in (375, 768, 1200):
        ctx, pg, errs = await open_page(browser, width=w, expand=True, accept_downloads=True)
        check(f"{w}px: Print is off until a pull is loaded", await pg.evaluate("document.getElementById('print').disabled"))
        await pg.click("#demo")
        await pg.wait_for_timeout(500)
        g = await pg.evaluate("""(()=>{const r=document.getElementById('replay').getBoundingClientRect(),p=document.getElementById('print').getBoundingClientRect();
            return {off:document.getElementById('print').disabled,gap:Math.round(p.left-r.right),dy:Math.round(p.top-r.top)}})()""")
        check(f"{w}px: Print is on and sits right next to Replay", not g["off"] and g["dy"] == 0 and 0 <= g["gap"] <= 16, str(g))
        name, jpg, iw, ih, b64, reqs, nbytes = await grab(pg)
        sizes[w] = (iw, ih)
        check(f"{w}px: Print saves a JPEG named after the loaded file (the demo has no upload, so it is called Demo)", jpg and name == "Demo_VirtualDyno.jpg", f"{name} jpeg={jpg}")
        check(f"{w}px: the file is small enough to upload anywhere (under 600 KB)", 0 < nbytes <= 600 * 1024, f"{nbytes / 1024:.0f} KB")
        check(f"{w}px: Print makes no request to another site", not reqs, str(reqs))
        check(f"{w}px: no page errors", not errs, "; ".join(errs))
        if w == 1200:
            ink = await pg.evaluate(IMG_INK, b64)
            check("the image is drawn on the page's own background and is not blank", same_color(ink["bg"], ink["page"]) and 0.03 <= ink["ink"] <= 0.6, str(ink))
            col4 = await pg.evaluate("getComputedStyle(document.querySelector('#s4 legend')).color")
            q = await pg.evaluate(IMG_TILES, [b64, col4])
            check("the image has four result tiles, the Peak Boost Pressure one (its own color) in the last quarter", q[3] > 300 and max(q[:3]) < 30, str(q))
            await pg.click("#condtg")      # collapse Car & Conditions: the image still has every field
            collapsed = (await grab(pg))[2:4]
            check("with Car & Conditions collapsed the image is the same size (fields still included)", collapsed == (iw, ih), f"{collapsed} vs {(iw, ih)}")
            await pg.click("[data-p=green]")
            green = await pg.evaluate(IMG_INK, (await grab(pg))[4])
            check("the image follows the theme", same_color(green["bg"], green["page"]) and not same_color(green["bg"], ink["bg"], 2), f"{green['bg']} vs {ink['bg']}")
            await pg.click("#condtg")      # open it again to reach the pedal field
            await pg.fill("#ped", "101")
            await pg.wait_for_timeout(500)
            check("Print is off again when no pull is found", await pg.evaluate("document.getElementById('print').disabled"))
        await ctx.close()
    check("the image is the same size on a phone, a tablet and a desktop", len(set(sizes.values())) == 1 and sizes[375][0] > 2000, str(sizes))

    # The file name comes from what was uploaded: the log (its extension dropped) + "_VirtualDyno", else the GPS file's name.
    def log_csv():
        rows = ["Time (msec),Engine Speed (RPM),Vehicle Speed (MPH),Accel. Pedal Position (%),Ambient Air Temp (F)"]
        rows += [f"{i * 80},{round(2400 + 4300 * i / 119)},{round((2400 + 4300 * i / 119) / 67.1)},100,70" for i in range(120)]
        return "\n".join(rows).encode()

    def upload(name):
        return {"name": name, "mimeType": "text/csv", "buffer": log_csv()}

    ctx, pg, errs = await open_page(browser, width=1200, expand=True, accept_downloads=True)
    await pg.set_input_files("#file", files=[upload("My Test Pull 10.01.2026.csv")])
    await pg.wait_for_timeout(600)
    check("an uploaded log is named after the file, without its extension, plus _VirtualDyno",
          (await grab(pg))[0] == "My Test Pull 10.01.2026_VirtualDyno.jpg")
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(600)
    check("adding a GPS file to a log keeps the log's name", (await grab(pg))[0] == "My Test Pull 10.01.2026_VirtualDyno.jpg")
    await pg.set_input_files("#file", files=[upload("Second Pull.csv")])
    await pg.wait_for_timeout(600)
    check("loading another log changes the name", (await grab(pg))[0] == "Second Pull_VirtualDyno.jpg")
    check("no page errors with uploaded files", not errs, "; ".join(errs))
    await ctx.close()
    ctx, pg, errs = await open_page(browser, width=1200, expand=True, accept_downloads=True)
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(600)
    gps = await grab(pg) if not await pg.evaluate("document.getElementById('print').disabled") else None
    check("with only a GPS file, Print is on and the name comes from that file", gps is not None and gps[0] == "synthetic_VirtualDyno.jpg" and gps[1],
          str(gps[:2]) if gps else "Print is off")
    check("no page errors with a GPS-only print", not errs, "; ".join(errs))
    await ctx.close()


class Site:
    """The repo served over http on localhost (service workers need http, not file://). `late` maps a path to the body to send
    instead of the file, and `delay` maps a path to seconds to wait first: that is how a new deploy and a slow network are staged."""
    def __init__(self):
        self.late, self.delay = {}, {}
        site = self
        class H(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                path = self.path.split("?")[0]
                time.sleep(site.delay.get(path, 0))
                if path in site.late:
                    body = site.late[path].encode()
                    self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                else:
                    super().do_GET()
        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address): pass     # the browser drops the stalled request on purpose: no broken-pipe noise
        self.srv = Quiet(("127.0.0.1", 0), functools.partial(H, directory=str(REPO)))
        self.url = f"http://127.0.0.1:{self.srv.server_port}/"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def close(self):
        self.srv.shutdown(); self.srv.server_close()


async def web_app(browser):
    """Installable and offline: manifest, icons, theme color, and the service worker (sw.js), on a local http server."""
    site = Site()
    ctx = await browser.new_context(viewport={"width": 1200, "height": 900}, reduced_motion="reduce")
    await ctx.add_init_script(init_script())
    pg = await ctx.new_page()
    errs, outside = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "ERR_" not in m.text and "Failed to load" not in m.text else None)
    pg.on("request", lambda r: outside.append(r.url) if not r.url.startswith(site.url) and not r.url.startswith("data:") and not r.url.startswith("blob:") else None)
    await pg.goto(site.url)
    registered = await pg.evaluate("Promise.race([navigator.serviceWorker.ready.then(() => 1), new Promise(r => setTimeout(() => r(0), 8000))])")
    check("web app: the service worker registers and activates on http", registered == 1)
    await pg.reload()                                       # now the worker controls the page
    await pg.wait_for_timeout(500)

    man_url = await pg.evaluate("document.querySelector('link[rel=manifest]') && document.querySelector('link[rel=manifest]').href")
    man = json.loads(await pg.evaluate("u => fetch(u).then(r => r.text())", man_url)) if man_url else {}
    icons = {(i["sizes"], i.get("purpose", "any")): i["src"] for i in man.get("icons", [])}
    check("web app: the page links a manifest that can be fetched and parsed", bool(man), str(man_url))
    check("web app: the manifest names the app, starts at the page, and opens it standalone",
          bool(man.get("name")) and bool(man.get("short_name")) and len(man.get("short_name", "")) <= 12 and man.get("display") == "standalone"
          and man.get("start_url") in (".", "./", "index.html") and man.get("scope") in (".", "./"), f"{ {k: man.get(k) for k in ('name', 'short_name', 'display', 'start_url', 'scope')} }")
    check("web app: icons for 192 and 512 (any) and a 512 maskable are listed", {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= set(icons), str(sorted(icons)))
    probe = """async src => { const im = new Image(); im.src = src; await im.decode();
        const c = document.createElement('canvas'); c.width = im.naturalWidth; c.height = im.naturalHeight; const x = c.getContext('2d'); x.drawImage(im, 0, 0);
        return [im.naturalWidth, im.naturalHeight, x.getImageData(0, 0, 1, 1).data[3], x.getImageData(c.width >> 1, c.height >> 1, 1, 1).data[3]] }"""
    ok_icons, detail = True, []
    for (size, purpose), src in icons.items():
        w, h, corner, middle = await pg.evaluate(probe, site.url + src)
        want = int(size.split("x")[0])
        good = (w, h) == (want, want) and middle == 255 and (corner == 0 if purpose == "any" else corner == 255)
        ok_icons &= good; detail.append(f"{src} {w}x{h} corner alpha {corner}")
    check("web app: each icon is a PNG of its stated size; the 'any' ones have clear corners and the maskable one is full-bleed", ok_icons and bool(icons), "; ".join(detail))
    apple = await pg.evaluate("document.querySelector('link[rel=apple-touch-icon]') && document.querySelector('link[rel=apple-touch-icon]').href")
    w, h, corner, _ = await pg.evaluate(probe, apple) if apple else (0, 0, 0, 0)
    check("web app: the iPhone home-screen icon is 180x180 and has no transparency", (w, h) == (180, 180) and corner == 255, f"{apple} {w}x{h} corner alpha {corner}")
    check("web app: a favicon is linked", bool(await pg.evaluate("document.querySelector('link[rel=icon]') && document.querySelector('link[rel=icon]').href")))
    desk = await pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--desk').trim()")
    tc = lambda: pg.evaluate("document.querySelector('meta[name=theme-color]').content")
    check("web app: the theme color is the page's background, and the manifest agrees", await tc() == desk == man.get("theme_color") == man.get("background_color"), f"{await tc()} {desk}")
    await pg.click("#phos button[data-p=green]")
    desk_g = await pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--desk').trim()")
    check("web app: the theme color follows the green theme and back", await tc() == desk_g != desk, f"{await tc()} vs {desk_g}")
    await pg.click("#phos button[data-p=color]")
    check("web app: back on the default theme the theme color is back", await tc() == desk)

    controlled = await pg.evaluate("!!navigator.serviceWorker.controller")
    cached = await pg.evaluate("caches.keys().then(async ks => { const c = await caches.open(ks[0]); return (await c.keys()).map(r => new URL(r.url).pathname) })")
    need = ["/", "/index.html", "/manifest.webmanifest", "/fonts/vt323-latin-400-normal.woff2"] + ["/" + s for s in icons.values()] + ["/icons/apple-touch-icon.png"]
    missing = [n for n in need if n not in cached]
    check("web app: a service worker controls the page and has kept the page, font, manifest and icons", controlled and not missing, f"missing {missing}")
    core = re.search(r"const CORE = \[(.*?)\];", (REPO / "sw.js").read_text(), re.S)
    listed = re.findall(r"'([^']+)'", core.group(1)) if core else []
    check("web app: every file the worker lists exists in the repo (a missing one would stop it installing)", bool(listed) and all((REPO / x).is_file() or x == "./" for x in listed), str([x for x in listed if x != "./" and not (REPO / x).is_file()]))

    # a new deploy shows at once while online
    html = (REPO / "index.html").read_text(encoding="utf-8")
    site.late["/index.html"] = site.late["/"] = html.replace("</body>", "<!--deploy-2--></body>")
    await pg.reload(); await pg.wait_for_timeout(300)
    check("web app: online, a changed page is shown on the next load (network first)", "<!--deploy-2-->" in await pg.content())
    # offline: the copy kept from the last visit opens, with its font and a working calculation
    await ctx.set_offline(True)
    await pg.reload(); await pg.wait_for_timeout(500)
    title = await pg.title()
    font_ok = await pg.evaluate("document.fonts.ready.then(() => document.fonts.check('20px VT323'))")
    await pg.evaluate("demo()"); await pg.wait_for_timeout(600)
    pulls = await pg.evaluate("cur ? cur.length : 0")
    check("web app: offline, the page opens (the latest copy it kept), with its font", "Virtual Dyno" in title and font_ok and "<!--deploy-2-->" in await pg.content(), f"{title!r} font {font_ok}")
    check("web app: offline, a log still analyzes", pulls > 5, f"{pulls} points")
    await ctx.set_offline(False)
    # a network that is up but too slow: the kept copy opens after the 4 s cutoff instead of hanging
    site.late["/index.html"] = site.late["/"] = html.replace("</body>", "<!--deploy-3--></body>")
    site.delay["/index.html"] = site.delay["/"] = 6
    t0 = time.time()
    await pg.reload(wait_until="commit")
    await pg.wait_for_selector("#fields", timeout=9000)
    took = time.time() - t0
    check("web app: on a network that stalls, the kept copy opens after about 4 s", 3.5 <= took <= 5.5 and "<!--deploy-2-->" in await pg.content(), f"{took:.1f} s")
    check("web app: nothing outside the site's own origin was requested", not outside, "; ".join(outside))
    check("web app: no page errors", not errs, "; ".join(errs))
    await ctx.close()
    site.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        steps = (layout, collapsible, correction_select, no_pulls_message, themes, boot, font, load_message, weather_row, tile_colors, tile_layout, unit_case, link_preview, web_app, realtime, print_button)
        for step in steps:
            if len(sys.argv) < 2 or step.__name__ in sys.argv[1:]:    # `python tools/smoke.py print_button` runs just that step
                await step(browser)
        await browser.close()
    bad = results.count(False)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)


asyncio.run(main())

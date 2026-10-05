"""Functional checks of the dyno calculation and file handling. Exit code 1 if anything fails.

  python tools/functional.py                      # GPS + error-handling checks (bundled synthetic track)
  DYNO_LOG=/path/to/accessport.csv python tools/functional.py   # also exercises a real Accessport log

The reference numbers asserted for the owner's log (GolfR_NewEngine_4thGearPull_10_01_2026.csv, not stored
in this repo) are: 430 hp / 394 lb-ft / 339 whp at 4138 ft density altitude with the SAE J1349 correction, which is
on by default, and 396 hp / 363 lb-ft / 312 whp with the correction switched off.
If the physics is changed on purpose, update the numbers below. Other logs are only printed, not asserted.
"""
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

from common import COUNTUP_MS, GPX, LOG, open_page

OWNER_LOG = "GolfR_NewEngine_4thGearPull_10_01_2026.csv"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


async def nums(pg):
    return [(await pg.inner_text(f"#s{i} .n")).strip() for i in (1, 2, 3)]


async def gps_only(browser):
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(COUNTUP_MS)
    hp, tq, whp = await nums(pg)
    hint = (await pg.inner_text("#s2 em")).strip()
    print(f"     GPS only: hp {hp} | torque {tq} | note: {hint}")
    check("GPS only: horsepower is calculated", hp.isdigit() and int(hp) > 0, hp)
    await pg.fill("#rpmpm", "67")
    await pg.wait_for_timeout(COUNTUP_MS)
    tq = (await pg.inner_text("#s2 .n")).strip()
    check("GPS only: torque appears once RPM per mph is entered (67 -> 351 lb-ft on the synthetic track, SAE on; 330 with it off)",
          tq == "351", tq)
    await pg.set_input_files("#file", {"name": "x.csv", "mimeType": "text/csv", "buffer": b"a,b\n1,2\n"})
    await pg.wait_for_timeout(300)
    msg = (await pg.inner_text("#msg")).strip()
    print(f"     bad file message: {msg!r} (class {await pg.get_attribute('#msg', 'class')!r})")
    check("a file that is not an Accessport log shows an error", bool(msg))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def with_log(browser):
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.set_input_files("#file", LOG)
    await pg.wait_for_timeout(COUNTUP_MS)
    corrected = await nums(pg)          # the SAE J1349 correction is on by default
    da_auto = await pg.input_value("#da")
    print(f"     log: hp/tq/whp {corrected} | density altitude {da_auto} ft | temp {await pg.input_value('#temp')} F"
          f" | loss {await pg.input_value('#loss')}")
    check("log loads and produces numbers", all(n.isdigit() for n in corrected), str(corrected))
    check("SAE correction is on by default", await pg.is_checked("#sae"))
    if os.path.basename(LOG) == OWNER_LOG:
        check("owner's log: 430 hp / 394 lb-ft / 339 whp with SAE correction (the default)", corrected == ["430", "394", "339"], str(corrected))
        check("owner's log: density altitude 4138 ft", da_auto.replace(",", "") == "4138", da_auto)

    # SAE correction is on; unticking lowers the numbers to the uncorrected ones, ticking again restores them
    await pg.click("label.chk")
    await pg.wait_for_timeout(COUNTUP_MS)
    plain = await nums(pg)
    check("unticking SAE lowers horsepower", int(plain[0]) < int(corrected[0]), f"{corrected[0]} -> {plain[0]}")
    if os.path.basename(LOG) == OWNER_LOG:
        check("owner's log: 396 hp / 363 lb-ft / 312 whp without SAE correction", plain == ["396", "363", "312"], str(plain))
    await pg.click("label.chk")
    await pg.wait_for_timeout(COUNTUP_MS)
    check("ticking SAE again restores the corrected numbers", await nums(pg) == corrected)

    # density altitude override sticks until a new log is loaded
    await pg.fill("#da", "1000")
    await pg.wait_for_timeout(1000)
    await pg.fill("#temp", "90")
    await pg.wait_for_timeout(300)
    check("density altitude override survives editing temperature", await pg.input_value("#da") == "1000")
    await pg.set_input_files("#file", LOG)
    await pg.wait_for_timeout(500)
    check("loading a log resets density altitude to automatic", await pg.input_value("#da") == da_auto)

    # GPS attached to a log fills heading/grade/speed and reveals the weather block
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(2500)
    gmsg = (await pg.inner_text("#gmsg")).strip()
    print(f"     GPS attach: {gmsg[:100]!r} | heading {await pg.input_value('#head')} grade {await pg.input_value('#grade')}")
    check("attaching GPS to a log fills heading and shows the weather block",
          bool(await pg.input_value("#head")) and await pg.is_visible("#wx"))

    # pasted Open-Meteo JSON fills humidity/wind
    wx = {"hourly": {"time": ["2026-10-01T17:00", "2026-10-01T18:00", "2026-10-01T19:00"],
                     "relative_humidity_2m": [30, 26, 22], "wind_speed_10m": [6, 10, 14],
                     "wind_direction_10m": [240, 270, 300]}}
    before = await pg.input_value("#humid")
    await pg.evaluate("document.getElementById('wxman').open=true")
    await pg.fill("#wxin", json.dumps(wx))
    await pg.wait_for_timeout(400)
    print(f"     weather paste: {(await pg.inner_text('#wxmsg')).strip()[:100]!r} | humidity {before} -> {await pg.input_value('#humid')}")
    check("pasted weather JSON updates humidity", await pg.input_value("#humid") != before)
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        await gps_only(browser)
        if LOG:
            await with_log(browser)
        else:
            print("SKIP log checks (set DYNO_LOG=/path/to/accessport.csv to run them)")
        await browser.close()
    bad = results.count(False)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)


asyncio.run(main())

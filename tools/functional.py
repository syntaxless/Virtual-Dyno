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
import math
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


async def factory_fields(browser):
    """Factory Horsepower / Torque are the first two Car & Conditions fields and the only reference for the vs-factory captions."""
    import re
    ctx, pg, errs = await open_page(browser, expand=True)
    ids = await pg.eval_on_selector_all("#fields input", "els => els.slice(0, 3).map(e => e.id)")
    labels = await pg.eval_on_selector_all("#fields label", "els => els.slice(0, 2).map(e => e.firstChild.textContent.trim())")
    vals = [await pg.input_value("#fhp"), await pg.input_value("#ftq")]
    print(f"     first fields: {ids} {labels} defaults {vals}")
    check("Factory Horsepower and Factory Torque are the first two fields, defaulting to the Golf R's 292 / 280",
          ids[:2] == ["fhp", "ftq"] and vals == ["292", "280"] and all(labels), f"{ids} {labels} {vals}")

    await pg.set_input_files("#gps", GPX)
    await pg.fill("#rpmpm", "67")
    await pg.wait_for_timeout(COUNTUP_MS)
    hp, tq = [float((await pg.inner_text(f"#s{i} .n")).strip()) for i in (1, 2)]
    cap = lambda i: pg.inner_text(f"#s{i} em")

    async def delta(i, shown):
        m = re.search(r"([+\u2212])(\d+) \S+ \D*?(\d+)\s*$", await cap(i))
        return (m and (int(m.group(2)) * (1 if m.group(1) == "+" else -1), int(m.group(3)))) or None

    d1, d2 = await delta(1, hp), await delta(2, tq)
    check("captions compare to the default factory numbers", bool(d1 and d2 and d1[1] == 292 and d2[1] == 280), f"{d1} {d2}")
    check("the caption difference is the shown number minus factory (within rounding)",
          bool(d1 and d2 and abs(d1[0] - (hp - 292)) <= 1 and abs(d2[0] - (tq - 280)) <= 1), f"{d1} vs {hp - 292}; {d2} vs {tq - 280}")

    await pg.fill("#fhp", "400")
    await pg.fill("#ftq", "500")
    await pg.wait_for_timeout(COUNTUP_MS)
    d1, d2 = await delta(1, hp), await delta(2, tq)
    shown = [float((await pg.inner_text(f"#s{i} .n")).strip()) for i in (1, 2)]
    check("editing the factory fields changes only the captions, to the new reference",
          bool(d1 and d2 and d1[1] == 400 and d2[1] == 500 and abs(d1[0] - (hp - 400)) <= 1 and abs(d2[0] - (tq - 500)) <= 1)
          and shown == [hp, tq], f"{d1} {d2} shown {shown}")

    await pg.fill("#fhp", "")
    await pg.fill("#ftq", "0")
    await pg.wait_for_timeout(COUNTUP_MS)
    c1, c2 = await cap(1), await cap(2)
    check("a blank or zero factory value drops the comparison instead of printing one against 0",
          not re.search(r"[+\u2212]\d", c1 + c2) and bool(c1.strip()) and bool(c2.strip()), f"{c1!r} {c2!r}")
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


def expected_da(msl_hpa, temp_f, rh, alt_ft):
    """Density altitude (ft) the page should show: sea-level pressure reduced to the altitude with the hour's temperature
    (hypsometric), then moist-air density, then the standard-atmosphere altitude with that density.
    msl_hpa=None means no pressure was supplied, so a standard day's pressure at that altitude is used."""
    z = alt_ft * 0.3048
    tc = (temp_f - 32) * 5 / 9
    tk = tc + 273.15
    if msl_hpa is None:
        ps = 101325 * (1 - 2.25577e-5 * z) ** 5.25588
    else:
        ps = msl_hpa * 100 * math.exp(-9.80665 * z / (287.058 * (tk + 0.0065 * z / 2)))
    pv = min(rh, 100) / 100 * 610.78 * 10 ** (7.5 * tc / (tc + 237.3))
    rho = (ps - pv) / (287.058 * tk) + pv / (461.495 * tk)
    return 44330.77 * (1 - (rho / 1.225) ** (1 / 4.25588)) / 0.3048


def wx_json(temp_f=None, msl=None, elevation=None, rh=40):
    """An Open-Meteo-shaped answer for 17:00-19:00 UTC on 2026-10-01 (the synthetic track starts at 18:00).
    temp_f / msl / elevation are left out when None, like an answer from before those variables were requested."""
    h = {"time": ["2026-10-01T17:00", "2026-10-01T18:00", "2026-10-01T19:00"],
         "relative_humidity_2m": [rh] * 3, "wind_speed_10m": [5] * 3, "wind_direction_10m": [270] * 3}
    if temp_f is not None:
        h["temperature_2m"] = [temp_f] * 3
    if msl is not None:
        h["pressure_msl"] = [msl] * 3
    out = {"hourly": h}
    if elevation is not None:
        out["elevation"] = elevation
    return json.dumps(out)


async def paste_wx(pg, text):
    await pg.evaluate("document.getElementById('wxman').open=true")
    await pg.fill("#wxin", "")
    await pg.fill("#wxin", text)
    await pg.wait_for_timeout(500)
    return (await pg.inner_text("#wxmsg")).strip()


async def weather_pressure_temp(browser):
    """Temperature and pressure from the weather answer: used when the log has none, and the log's own sensors win."""
    # GPS only: no log, so the track's altitude and the hour's pressure and temperature set the density altitude
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(1500)
    da0 = await pg.input_value("#da")
    alt = await pg.evaluate("gi.alt")
    await paste_wx(pg, wx_json(temp_f=68, msl=1033))
    da_hi, temp = int(await pg.input_value("#da")), await pg.input_value("#temp")
    await paste_wx(pg, wx_json(temp_f=68, msl=993))
    da_lo = int(await pg.input_value("#da"))
    print(f"     GPS only: density altitude {da0} (standard day) -> {da_hi} (1033 hPa) / {da_lo} (993 hPa), temp {temp}, altitude {alt:.0f} ft")
    check("GPS only: the weather temperature fills the air temp field", float(temp) == 68.0, temp)
    check("GPS only: density altitude follows the hour's sea-level pressure (40 hPa is roughly 1,300 ft)", 1100 < da_lo - da_hi < 1600, f"{da_hi} / {da_lo}")
    check("GPS only: density altitude matches the pressure, temperature and humidity worked out independently (+-4 ft)",
          abs(da_lo - expected_da(993, 68, 40, alt)) <= 4 and abs(da_hi - expected_da(1033, 68, 40, alt)) <= 4,
          f"{da_hi}/{da_lo} vs {expected_da(1033, 68, 40, alt):.0f}/{expected_da(993, 68, 40, alt):.0f}")
    await paste_wx(pg, wx_json())
    da_std = int(await pg.input_value("#da"))
    check("an answer without pressure (the older shape) falls back to a standard day's pressure at the track's altitude, and still fills humidity",
          abs(da_std - expected_da(None, 68, 40, alt)) <= 4 and await pg.input_value("#humid") == "40",
          f"{da_std} vs {expected_da(None, 68, 40, alt):.0f}")
    await pg.fill("#da", "1000")
    await paste_wx(pg, wx_json(temp_f=68, msl=1033))
    check("a hand-entered density altitude is not overwritten by the weather pressure", await pg.input_value("#da") == "1000", await pg.input_value("#da"))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()

    if not LOG:
        return
    raw = open(LOG, "rb").read().decode("utf-8", "ignore")

    # log with its own temperature and pressure + GPS: the log's sensors win; a big disagreement is reported, not applied
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.set_input_files("#file", LOG)
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(2500)
    t0, d0, rh0 = await pg.input_value("#temp"), await pg.input_value("#da"), int(await pg.input_value("#humid"))
    msg = await paste_wx(pg, wx_json(temp_f=55, msl=1033, rh=rh0))     # same humidity, so only temperature and pressure could move it
    t1, d1 = await pg.input_value("#temp"), await pg.input_value("#da")
    print(f"     log + weather: temp {t0} -> {t1}, density altitude {d0} -> {d1} | {msg[-130:]!r}")
    check("log with its own temperature and pressure: both are kept", t0 == t1 and d0 == d1, f"{t0}->{t1} {d0}->{d1}")
    check("a weather temperature far from the log's sensor is reported", "55" in msg and t0.split(".")[0] in msg, msg[-120:])
    await paste_wx(pg, wx_json(temp_f=int(float(t0)), msl=1033, rh=rh0))
    check("a weather temperature close to the log's sensor adds no remark", "Open-Meteo has" not in (await pg.inner_text("#wxmsg")))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()

    # log without temperature or pressure columns + GPS: the weather supplies both
    bare = raw.replace("Ambient Air Temp.", "Zzz Sensor").replace("Ambient Pressure", "Yyy Sensor")
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.set_input_files("#file", {"name": "bare.csv", "mimeType": "text/csv", "buffer": bare.encode()})
    await pg.set_input_files("#gps", GPX)
    await pg.wait_for_timeout(2500)
    alt = await pg.evaluate("gi.alt")
    await paste_wx(pg, wx_json(temp_f=68, msl=1013.25))
    t1, d1 = await pg.input_value("#temp"), int(await pg.input_value("#da"))
    print(f"     log without temp/pressure + weather: temp {t1}, density altitude {d1}, altitude {alt:.0f} ft")
    check("log without temperature or pressure: the weather fills both", float(t1) == 68.0 and abs(d1 - expected_da(1013.25, 68, 40, alt)) <= 4,
          f"{t1} {d1} vs {expected_da(1013.25, 68, 40, alt):.0f}")
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()

    # same log, no GPS track: the answer's own ground elevation is used (Open-Meteo returns one with every answer)
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.route("**/*open-meteo.com/**", lambda r: r.fulfill(
        status=200, headers={"access-control-allow-origin": "*", "content-type": "application/json"},
        body=wx_json(temp_f=68, msl=1013.25, elevation=1600)))
    await pg.set_input_files("#file", {"name": "bare.csv", "mimeType": "text/csv", "buffer": bare.encode()})
    await pg.wait_for_timeout(1500)
    await pg.fill("#wxplace", "39.74, -104.98")
    await pg.fill("#wxdate", "2026-10-01")
    await pg.fill("#wxtime", "18:00")
    await pg.click("#wxpget")
    await pg.wait_for_timeout(900)
    d1 = int(await pg.input_value("#da"))
    print(f"     log without temp/pressure, no GPS: density altitude {d1} (ground elevation 1600 m from the answer)")
    check("with no GPS altitude, the elevation in the weather answer is used", abs(d1 - expected_da(1013.25, 68, 40, 1600 / 0.3048)) <= 4,
          f"{d1} vs {expected_da(1013.25, 68, 40, 1600 / 0.3048):.0f}")
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        await gps_only(browser)
        await factory_fields(browser)
        await weather_pressure_temp(browser)
        if LOG:
            await with_log(browser)
        else:
            print("SKIP log checks (set DYNO_LOG=/path/to/accessport.csv to run them)")
        await browser.close()
    bad = results.count(False)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)


asyncio.run(main())

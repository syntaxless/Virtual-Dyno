"""Functional checks of the dyno calculation and file handling. Exit code 1 if anything fails.

  python tools/functional.py                      # GPS + error-handling checks (bundled synthetic track)
  DYNO_LOG=/path/to/accessport.csv python tools/functional.py   # also exercises a real Accessport log

The reference numbers asserted for the owner's log (GolfR_NewEngine_4thGearPull_10_01_2026.csv, not stored
in this repo) are: 390 hp / 360 lb-ft / 307 whp at 4138 ft density altitude with Power Correction on Uncorrected, which
is the default, and 423 hp / 391 lb-ft / 334 whp with SAE J1349 chosen (they were 396 / 363 / 312 and 430 / 394 / 339 before
whole-MPH speed was rebuilt from RPM; see stepped_speed). The other standards are checked against factors
worked out here from each standard's published formula.
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


# (value, label) of the Power Correction choices that change the numbers
STANDARDS = [("j1349", "SAE J1349"), ("j607", "SAE J607 (STD)"), ("din", "DIN 70020"), ("iso", "ISO 1585")]


def expected_cf(std, temp_f, rh, da_ft):
    """Correction factor the page should apply, from each standard's published formula and the air the fields describe.
    T is the air temperature (K), pd the dry-air pressure and pt the total pressure (Pa). Reference conditions:
    J1349 25 C / 99 kPa dry (the 1990 form of the formula, 298 K), ISO 1585 the same with the power-law form,
    J607 (STD) 60 F / 101.325 kPa total pressure with no humidity term (what a Dynojet's STD does), DIN 70020 20 C / 1013 mbar total pressure."""
    tc = (temp_f - 32) * 5 / 9
    tk = tc + 273.15
    rho = 1.225 * (1 - 2.25577e-5 * da_ft * 0.3048) ** 4.25588
    pv = min(rh, 100) / 100 * 610.78 * 10 ** (7.5 * tc / (tc + 237.3))
    pd = max(5e4, (rho - pv / (461.495 * tk)) * 287.058 * tk)
    pt = pd + pv
    if std == "j1349":
        return 1.18 * (99000 / pd) * math.sqrt(tk / 298) - 0.18
    if std == "j607":
        return (101325 / pt) * math.sqrt(tk / 288.71)
    if std == "din":
        return (101300 / pt) * math.sqrt(tk / 293.15)
    if std == "iso":
        return (99000 / pd) ** 1.2 * (tk / 298.15) ** 0.6
    return 1.0


async def standards_match(pg, where):
    """With Power Correction on Uncorrected, read the numbers; then choose each standard and check the numbers moved by that
    standard's factor for the air in the fields (to within the rounding of the shown integers); then go back."""
    await pg.select_option("#corr", "none")
    await pg.wait_for_timeout(COUNTUP_MS)
    base = [float(x) for x in await nums(pg)]
    snap = "() => ({pts: pulls[sel].pts.map(q => [q.hp, q.tq, q.hw]), cur: cur.map(q => [q.hp, q.tq, q.hw])})"
    pts0 = await pg.evaluate(snap)       # every point of the pull and every bin of the plotted curve, uncorrected
    temp, rh, da = [float((await pg.input_value(i)).replace(",", "")) for i in ("#temp", "#humid", "#da")]
    for std, label in STANDARDS:
        await pg.select_option("#corr", std)
        await pg.wait_for_timeout(COUNTUP_MS)
        got = [float(x) for x in await nums(pg)]
        cf = expected_cf(std, temp, rh, da)
        want = [b * cf for b in base]
        pts1 = await pg.evaluate(snap)
        dev = max((abs(y / x / cf - 1) for k in ("pts", "cur") for a, c in zip(pts0[k], pts1[k]) for x, y in zip(a, c)
                   if x and y and x > 0), default=1)
        check(f"{where}: {label} is the last step: every plotted point and curve bin is its uncorrected value times the factor, applied once",
              dev < 1e-9, f"worst deviation {dev:.1e}")
        cond = await pg.inner_text("#cond")
        others = [l for v, l in STANDARDS if v != std]
        check(f"{where}: {label} scales hp / torque / whp by its own factor ({cf:.3f}) for {temp:.0f} F, {rh:.0f}% humidity, {da:.0f} ft",
              all(abs(g - w) <= 1.1 for g, w in zip(got, want)), f"{got} vs {[round(w, 1) for w in want]}")
        check(f"{where}: the conditions line names {label} and no other standard", label in cond and not any(o in cond for o in others), cond[-70:])
    await pg.select_option("#corr", "none")
    await pg.wait_for_timeout(COUNTUP_MS)
    check(f"{where}: going back to Uncorrected restores the uncorrected numbers", [float(x) for x in await nums(pg)] == base)
    cond = await pg.inner_text("#cond")
    check(f"{where}: the conditions line names no standard when Uncorrected", not any(l in cond for _, l in STANDARDS), cond[-70:])


async def correction_formulas(browser):
    """The page's corrFactor() itself: 1.000 at each standard's own reference conditions, and equal to the published
    formulas worked out independently elsewhere on the map."""
    ctx, pg, errs = await open_page(browser)
    ref = {"j1349": (298, 99000, 99000), "j607": (288.71, 101325, 101325), "din": (293.15, 98000, 101300), "iso": (298.15, 99000, 99000)}
    got = {k: await pg.evaluate("a => corrFactor(...a)", [k, *v]) for k, v in ref.items()}
    check("each standard's factor is 1.000 at its own reference conditions",
          all(abs(g - 1) < 1e-9 for g in got.values()), str(got))
    check("Uncorrected is always 1", await pg.evaluate("[corrFactor('none',250,50000,50500),corrFactor('none',320,105000,106000)]") == [1, 1])
    worst = 0.0
    for tk, pd, pt in ((305.15, 85000, 86200), (278.15, 101000, 101600), (313.15, 70000, 71500), (288.15, 95000, 95900)):
        for std, _ in STANDARDS:
            js = await pg.evaluate("a => corrFactor(...a)", [std, tk, pd, pt])
            py = {"j1349": lambda: 1.18 * (99000 / pd) * math.sqrt(tk / 298) - 0.18,
                  "j607": lambda: (101325 / pt) * math.sqrt(tk / 288.71),
                  "din": lambda: (101300 / pt) * math.sqrt(tk / 293.15),
                  "iso": lambda: (99000 / pd) ** 1.2 * (tk / 298.15) ** 0.6}[std]()
            worst = max(worst, abs(js - py))
    check("corrFactor matches the published formulas at four sets of air conditions", worst < 1e-9, f"worst difference {worst:.2e}")
    # A real Dynojet WinPEP 8 sheet (Golf R, 10/8/2026) lists STD:1.02 for 71.33 F, 29.60 inHg, 48.09% RH and again for
    # 71.47 F, 29.61 inHg, 47.41% RH. STD uses total pressure; a dry-air form would give 1.035 (shown as 1.03).
    for f_, inhg, rh in ((71.33, 29.60, 48.09), (71.47, 29.61, 47.41)):
        tc = (f_ - 32) * 5 / 9
        pt = inhg * 3386.389
        pd = pt - rh / 100 * 610.78 * 10 ** (7.5 * tc / (tc + 237.3))
        js = await pg.evaluate("a => corrFactor(...a)", ["j607", tc + 273.15, pd, pt])
        check(f"SAE J607 (STD) gives the 1.02 a Dynojet sheet shows for {f_} F, {inhg} inHg, {rh}% RH", f"{js:.2f}" == "1.02", f"{js:.4f}")
    hot_high = [await pg.evaluate("a => corrFactor(...a)", [k, 313.15, 80000, 81500]) for k, _ in STANDARDS]
    cold_dense = [await pg.evaluate("a => corrFactor(...a)", [k, 273.15, 102000, 102300]) for k, _ in STANDARDS]
    check("hot thin air raises every standard's factor above 1 and cold dense air lowers it below 1",
          all(f > 1 for f in hot_high) and all(f < 1 for f in cold_dense), f"{hot_high} / {cold_dense}")
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


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
    check("GPS only: torque appears once RPM per mph is entered (67 -> 330 lb-ft on the synthetic track, Uncorrected, the default; 351 with SAE J1349)",
          tq == "330", tq)
    check("Power Correction is Uncorrected by default", await pg.input_value("#corr") == "none")
    await pg.select_option("#corr", "j1349")
    await pg.wait_for_timeout(COUNTUP_MS)
    check("GPS only: choosing SAE J1349 raises the torque to 351", (await pg.inner_text("#s2 .n")).strip() == "351")
    await standards_match(pg, "GPS only")
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
    plain = await nums(pg)              # Power Correction is Uncorrected by default
    da_auto = await pg.input_value("#da")
    print(f"     log: hp/tq/whp {plain} | density altitude {da_auto} ft | temp {await pg.input_value('#temp')} F"
          f" | loss {await pg.input_value('#loss')}")
    check("log loads and produces numbers", all(n.isdigit() for n in plain), str(plain))
    check("Power Correction is Uncorrected by default", await pg.input_value("#corr") == "none")
    if os.path.basename(LOG) == OWNER_LOG:
        check("owner's log: 390 hp / 360 lb-ft / 307 whp Uncorrected (the default)", plain == ["390", "360", "307"], str(plain))
        check("owner's log: density altitude 4138 ft", da_auto.replace(",", "") == "4138", da_auto)

    # Uncorrected to start; choosing SAE J1349 raises the numbers to the corrected ones, and Uncorrected restores them
    await pg.select_option("#corr", "j1349")
    await pg.wait_for_timeout(COUNTUP_MS)
    corrected = await nums(pg)
    check("choosing SAE J1349 raises horsepower", int(corrected[0]) > int(plain[0]), f"{plain[0]} -> {corrected[0]}")
    if os.path.basename(LOG) == OWNER_LOG:
        check("owner's log: 423 hp / 391 lb-ft / 334 whp with SAE J1349", corrected == ["423", "391", "334"], str(corrected))
    await pg.select_option("#corr", "none")
    await pg.wait_for_timeout(COUNTUP_MS)
    check("choosing Uncorrected again restores the uncorrected numbers", await nums(pg) == plain)
    await standards_match(pg, "log")

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


async def tile_captions(browser):
    """The Peak Crank Power, Crank Torque and Wheel Power captions say only where the peak is ("at 116 MPH", "at 6,910 RPM"): the
    owner removed the "+N HP vs stock" comparison, the Factory Horsepower / Factory Torque fields and the "after 20% loss" note."""
    import re
    ctx, pg, errs = await open_page(browser, expand=True)
    first = await pg.eval_on_selector_all("#fields input", "els => els.slice(0, 2).map(e => e.id)")
    gone = await pg.evaluate("!document.getElementById('fhp') && !document.getElementById('ftq') && !/factory/i.test(document.getElementById('fields').textContent)")
    check("the Factory Horsepower and Factory Torque fields are gone (Car & Conditions starts with Curb Weight)", gone and first[:1] == ["curb"], f"{first}")
    await pg.set_input_files("#gps", GPX)
    await pg.fill("#rpmpm", "67")
    await pg.wait_for_timeout(COUNTUP_MS)
    caps = [(await pg.inner_text(f"#s{i} em")).strip() for i in (1, 2, 3)]
    print(f"     captions: {caps}")
    check("the power, torque and wheel power captions only say where the peak is (no comparison to stock, no drivetrain-loss note)",
          all(re.fullmatch(r"at [\d,]+ (RPM|MPH)", c) for c in caps), str(caps))
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
    ap = await pg.evaluate("[...document.querySelectorAll('#wxmsg .ap')].map(e => e.textContent)")
    plain_col, ap_col = await pg.evaluate("[getComputedStyle(document.getElementById('wxmsg')).color, getComputedStyle(document.querySelector('#wxmsg .ap')).color]")
    check("the applied weather (humidity, temperature, wind, and the density altitude it set) is in an accent color, the rest of the message is not",
          len(ap) == 2 and "40% humidity" in ap[0] and "68" in ap[0] and "wind" in ap[0] and "Density altitude set to" in ap[1] and ap_col != plain_col,
          f"{ap} {ap_col} vs {plain_col}")
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
    ap = await pg.evaluate("[...document.querySelectorAll('#wxmsg .ap')].map(e => e.textContent)")
    msg = await pg.inner_text("#wxmsg")
    check("wind that was not applied (no heading) is not in the accent color, and only the applied humidity and temperature are",
          bool(ap) and "humidity" in ap[0] and "wind" not in ap[0] and "not applied" in msg, f"{ap} | {msg[:120]!r}")
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


def synth_pull(speed_of, rpm_wobble=0.0, step=None):
    """A smooth full-throttle pull as Accessport CSV text: RPM 2000 up to about 6100 over 7 s at ~45 Hz.

    speed_of(t, rpm) gives the true speed in MPH; step rounds what is logged to that resolution (1 = whole MPH).
    rpm_wobble adds a 3 Hz ripple (RPM) to the RPM column only, which speed does not have.
    """
    rows = ["Time (sec),Engine Speed (RPM),Vehicle Speed (mph),Accel Pedal Position (%)"]
    for i in range(0, 316):
        t = i * 0.0222
        rpm = 2000 + 800 * t - 30 * t * t
        v = speed_of(t, rpm)
        if step:
            v = round(v / step) * step
        rows.append(f"{t:.3f},{rpm + rpm_wobble * math.sin(2 * math.pi * 3 * t):.0f},{v:.3f},100")
    return "\n".join(rows)


async def pull_curve(browser, text):
    """[(rpm, wheel power)] of the plotted curve for a log given as text, uncorrected, no drag or rolling resistance."""
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.set_input_files("#file", {"name": "synthetic.csv", "mimeType": "text/csv", "buffer": text.encode()})
    await pg.wait_for_timeout(800)
    curve = await pg.evaluate("""() => {for (const [k, v] of Object.entries({cd: 0, crr: 0, grade: 0, wind: 0, loss: 0}))
        document.getElementById(k).value = v; analyze(false); return cur ? cur.map(q => [q.r, q.hw]) : null}""")
    await ctx.close()
    return curve, errs


def curve_gap(a, b, lo=2800, hi=5400):
    """RMS relative difference (percent) of two [(rpm, y)] curves over the same RPM range."""
    def at(c, x):
        for (x0, y0), (x1, y1) in zip(c, c[1:]):
            if x0 <= x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
        return None
    d = [(at(b, x) / at(a, x) - 1) for x in range(lo, hi + 1, 100) if at(a, x) and at(b, x)]
    return 100 * math.sqrt(sum(e * e for e in d) / len(d)), len(d)


async def stepped_speed(browser):
    """A Cobb log's speed moves in whole-MPH steps; the page rebuilds it from RPM inside the pull (see steady() in analyze()).

    Checked against the same pull logged with exact speed, which is left alone. Needs no real log.
    """
    lock = lambda t, rpm: rpm / 59.0
    exact, errs = await pull_curve(browser, synth_pull(lock))
    stepped, errs2 = await pull_curve(browser, synth_pull(lock, step=1))
    check("stepped speed: the synthetic pull is found", bool(exact) and bool(stepped) and not errs and not errs2, "; ".join(errs + errs2))
    gap, n = curve_gap(exact, stepped)
    check("whole-MPH speed gives the same curve as exact speed (0.3% RMS or better; without the rebuild it is 0.7%)", gap < 0.3, f"{gap:.2f}% over {n} points")
    # a ratio that drifts 3% over the pull (clutch slip) must still be followed, not flattened
    slip = lambda t, rpm: rpm / (59.0 + 0.4 * t)
    exact_s, _ = await pull_curve(browser, synth_pull(slip))
    stepped_s, _ = await pull_curve(browser, synth_pull(slip, step=1))
    gap, n = curve_gap(exact_s, stepped_s)
    check("a drifting RPM-per-MPH ratio (slip) is followed with whole-MPH speed (1.5% RMS or better)", gap < 1.5, f"{gap:.2f}% over {n} points")
    # speed that is not stepped is used as logged: a ripple that only the RPM column has must not reach the power
    fine, _ = await pull_curve(browser, synth_pull(lock, step=0.01, rpm_wobble=150))
    gap, n = curve_gap(exact, fine)
    check("speed with fine resolution is used as logged (an RPM-only ripple does not reach the power)", gap < 1.0, f"{gap:.2f}% over {n} points")


def with_cols(text, cols, blank_near=None):
    """Add columns to an Accessport CSV given as text. cols is [(header, fn(rpm_in_this_row) -> value)]; blank_near=(lo, hi) leaves the
    first column empty in rows whose RPM is in that range (a logger that dropped a few samples)."""
    lines = text.split("\n")
    out = [lines[0] + "".join("," + h for h, _ in cols)]
    for ln in lines[1:]:
        rpm = float(ln.split(",")[1])
        cells = []
        for k, (_, fn) in enumerate(cols):
            blank = k == 0 and blank_near and blank_near[0] <= rpm <= blank_near[1]
            cells.append("" if blank else f"{fn(rpm):.2f}")
        out.append(ln + "".join("," + c for c in cells))
    return "\n".join(out)


async def boost_tile(browser):
    """Peak Boost Pressure (the fourth tile) is read from the log's boost column, not calculated. Needs no real log.

    The synthetic pull has boost 22.0 psi at 4,200 RPM, falling away either side (a parabola, so the 100 RPM binning and the
    smoothing take about 0.1 psi off the top)."""
    boost = lambda rpm: 22.0 - 6.0 * ((rpm - 4200) / 1200) ** 2
    base = synth_pull(lambda t, rpm: rpm / 59.0)

    async def tile(text, name="synthetic.csv", gps=False):
        ctx, pg, errs = await open_page(browser, expand=True)
        if gps:
            await pg.set_input_files("#gps", GPX)
            await pg.fill("#rpmpm", "67")
        else:
            await pg.set_input_files("#file", {"name": name, "mimeType": "text/csv", "buffer": text.encode()})
        await pg.wait_for_timeout(800)
        n = (await pg.inner_text("#s4 .n")).strip()
        cap = (await pg.inner_text("#s4 em")).strip()
        others = [(await pg.inner_text(f"#s{i} .n")).strip() for i in (1, 2, 3)]
        await ctx.close()
        return n, cap, others, errs

    n, cap, others, errs = await tile(with_cols(base, [("Boost Press. (psi)", boost)]))
    import re
    rpm_at = re.search(r"([\d,]+) RPM", cap)
    rpm_at = int(rpm_at.group(1).replace(",", "")) if rpm_at else 0
    check("Peak Boost Pressure shows the log's peak to one decimal, at the RPM where it happens (22.0 psi at 4,200 RPM, within 0.3 and 100 RPM)",
          re.fullmatch(r"\d+\.\d", n) is not None and abs(float(n) - 22.0) <= 0.3 and abs(rpm_at - 4200) <= 100, f"{n} | {cap}")
    check("the other three tiles still show numbers", all(re.fullmatch(r"\d+", o) for o in others), str(others))

    # units in the header are converted to psi
    for head, k in (("Boost Press. (kPa)", 6.89476), ("Boost (bar)", 1 / 14.5038), ("Boost Press. (mbar)", 68.9476)):
        n2, cap2, _, _ = await tile(with_cols(base, [(head, lambda r, k=k: boost(r) * k)]))
        check(f"a boost column in {head.split('(')[1][:-1]} is converted to psi", abs(float(n2) - float(n)) <= 0.1 if re.fullmatch(r"\d+\.\d", n2) else False, f"{n2} vs {n}")

    # a target column (listed first) is not the measurement; neither is a duty cycle
    n3, _, _, _ = await tile(with_cols(base, [("Trgt. Boost Press. (psi)", lambda r: boost(r) + 8), ("Wastegate Duty (%)", lambda r: 50),
                                              ("Boost Press. (psi)", boost)]))
    check("a target-boost column listed before the real one is ignored", re.fullmatch(r"\d+\.\d", n3) is not None and abs(float(n3) - float(n)) <= 0.1, f"{n3} vs {n}")

    # no Boost column: a relative manifold pressure column stands in
    n4, _, _, _ = await tile(with_cols(base, [("Relative Manifold Pressure (psi)", boost)]))
    check("with no boost column, Relative Manifold Pressure stands in", re.fullmatch(r"\d+\.\d", n4) is not None and abs(float(n4) - float(n)) <= 0.1, n4)

    # a few empty cells near the peak do not blank the tile
    n5, _, _, _ = await tile(with_cols(base, [("Boost Press. (psi)", boost)], blank_near=(4100, 4300)))
    check("empty boost cells near the peak are skipped, not allowed to blank the tile", re.fullmatch(r"\d+\.\d", n5) is not None and abs(float(n5) - 22.0) <= 0.5, n5)

    # no boost at all (a naturally aspirated car, or a log without the column): N/A, and the rest of the page still works
    n6, cap6, others6, errs6 = await tile(base)
    check("a log with no boost column shows N/A (not a dash: the car may be naturally aspirated), with a caption that says why",
          n6 == "N/A" and "boost" in cap6.lower(), f"{n6!r} | {cap6!r}")
    check("the other tiles still show numbers when there is no boost column", all(re.fullmatch(r"\d+", o) for o in others6[:1] + others6[2:]), str(others6))
    n7, cap7, _, errs7 = await tile("", gps=True)
    check("GPS only shows N/A for boost, with a caption that asks for a log", n7 == "N/A" and "log" in cap7.lower(), f"{n7!r} | {cap7!r}")
    check("no page errors", not (errs or errs6 or errs7), "; ".join(errs + errs6 + errs7))


MPH, G, LB = 0.44704, 9.80665, 0.45359237


def synth_coast(crr=0.0105, grade=0.0, wind=0.0, cda_scale=1.0, v_lift=100, v_stop=30, mode="clutch", brake_after=None, ped=True,
                ambient=None, hz=45):
    """A pull then a coast as Accessport CSV text, from the same force equation the page uses, integrated here with RK4
    (3,500 lb with driver, 36 kg of wheels, Cd .32, 2.2 m2, air density at 0 ft) so the page's fit can be checked against a known answer.

    mode: "clutch" (clutch in: RPM falls away from speed), "gear" (in gear: RPM follows speed and the engine's own braking adds drag),
    "none" (the log stops at the lift). brake_after: seconds after the lift at which hard braking starts. Returns (csv, times, speeds in m/s).
    Speed is logged in whole MPH, like a Cobb log."""
    m, mw = 3500 * LB, 36.0
    kap = 0.5 * 1.225 * 0.32 * cda_scale * 2.2 / (m + mw)
    dt = 1.0 / hz
    hdr = ["Time (sec)", "Engine Speed (RPM)", "Vehicle Speed (mph)"] + (["Accel Pedal Position (%)"] if ped else []) + (["Ambient Air Temp. (F)"] if ambient else [])
    rows, times, speeds = [], [], []

    def emit(t, v, rpm, pedal):
        cells = [f"{t:.3f}", f"{rpm:.0f}", f"{round(v / MPH):g}"] + ([f"{pedal:g}"] if ped else []) + ([f"{ambient}"] if ambient else [])
        rows.append(",".join(cells)); times.append(t); speeds.append(v)

    t, v = 0.0, 30 * MPH
    while v < v_lift * MPH:                          # the pull: 2 m/s2 in a locked gear at 58.6 RPM per MPH
        emit(t, v, 58.6 * v / MPH, 100)
        v += 2.0 * dt; t += dt
    if mode == "none":
        return "\n".join([",".join(hdr)] + rows), times, speeds
    t_lift, rpm0 = t, 58.6 * v / MPH
    force = lambda x, extra: -(kap * (x + wind) * abs(x + wind) + (crr * m * G + m * G * grade) / (m + mw)) - extra
    while v > v_stop * MPH:
        el = t - t_lift
        extra = (0.35 if mode == "gear" else 0.0) + (3.0 if brake_after is not None and el > brake_after else 0.0)
        rpm = 850 + (rpm0 - 850) * math.exp(-max(0.0, el - 0.15) / 0.8) if mode == "clutch" else 58.6 * v / MPH
        emit(t, v, rpm, 0)
        k1 = force(v, extra); k2 = force(v + dt / 2 * k1, extra); k3 = force(v + dt / 2 * k2, extra); k4 = force(v + dt * k3, extra)
        v += dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4); t += dt
        if brake_after is not None and el > brake_after + 3:
            break
    return "\n".join([",".join(hdr)] + rows), times, speeds


def synth_track(times, speeds, grade=0.0, lead=6.0, hz=10):
    """A GPX of the same drive, due east at 39.74 N, elevation 1,600 m + grade x distance, speed in m/s, starting `lead` s before the log
    at 2026-10-01 18:00 UTC. Exact: no GPS noise."""
    import datetime
    base = datetime.datetime(2026, 10, 1, 18, 0, 0)
    T = [-lead] + times + [times[-1] + 4.0]
    V = [speeds[0]] + speeds + [speeds[-1]]
    D = [0.0]
    for i in range(1, len(T)):
        D.append(D[-1] + (T[i] - T[i - 1]) * (V[i] + V[i - 1]) / 2)

    def at(x, arr, j=[0]):
        lo, hi = 0, len(T) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if T[mid] <= x:
                lo = mid
            else:
                hi = mid
        w = (x - T[lo]) / (T[hi] - T[lo])
        return arr[lo] * (1 - w) + arr[hi] * w

    pts, x = [], T[0]
    while x <= T[-1]:
        d, vv = at(x, D), at(x, V)
        ts = (base + datetime.timedelta(seconds=x + lead)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        pts.append(f'<trkpt lat="39.7400000" lon="{-104.98 + d / (111320 * math.cos(math.radians(39.74))):.7f}"><ele>{1600 + grade * d:.2f}</ele>'
                   f'<time>{ts}</time><speed>{vv:.3f}</speed></trkpt>')
        x += 1.0 / hz
    return '<?xml version="1.0"?><gpx version="1.1" creator="synthetic"><trk><trkseg>' + "".join(pts) + "</trkseg></trk></gpx>"


async def coast_state(pg):
    return await pg.evaluate("""() => ({crr: document.getElementById('crr').value, tag: srcOf('crr'),
        status: coast ? coast.status : null, fit: coast && coast.crr != null ? coast.crr : null, sig: coast && coast.sig != null ? coast.sig : null,
        line: document.getElementById('coastmsg') ? document.getElementById('coastmsg').textContent : ''})""")


async def load_coast(browser, text, track=None, fields=None, before=None):
    """Open the page, optionally set fields first, load a log and a GPS track, and put density altitude at 0 ft (what the generator used)."""
    ctx, pg, errs = await open_page(browser, expand=True)
    for k, val in (fields or {}).items():
        await pg.fill("#" + k, str(val))
    await pg.set_input_files("#file", {"name": "coast.csv", "mimeType": "text/csv", "buffer": text.encode()})
    await pg.wait_for_timeout(500)
    if track:
        await pg.set_input_files("#gps", {"name": "coast.gpx", "mimeType": "application/gpx+xml", "buffer": track.encode()})
        await pg.wait_for_timeout(1200)
    await pg.fill("#da", "0")
    await pg.wait_for_timeout(250)
    return ctx, pg, errs


async def coast_fit(browser):
    """Rolling Resistance from a coast-down (pedal at 0, clutch in): the page fits it, with the road grade from GPS elevation, and fills the
    field until the user types in it. Checked against logs generated from the force equation with a known answer. Needs no real log."""
    import re
    TRUE = 0.0105

    # 1. a clean clutch-in coast on a 0.4% downhill, with an exact GPS track: the field gets the true value, tagged as measured
    txt, t, v = synth_coast(crr=TRUE, grade=-0.004, v_lift=100, v_stop=30)
    track = synth_track(t, v, grade=-0.004)
    ctx, pg, errs = await load_coast(browser, txt, track)
    st = await coast_state(pg)
    check("coast with GPS: Rolling Resistance is filled with the true value (0.0105, within 0.001) and tagged coast",
          st["status"] == "ok" and abs(float(st["crr"]) - TRUE) <= 0.001 and st["tag"] == "coast", str(st))
    check("the line under the log message names the value, the coast and its +/-, and says the grade came from GPS",
          "set to" in st["line"] and "+/-" in st["line"] and "MPH" in st["line"] and "GPS" in st["line"], st["line"][:160])
    sig = float(re.search(r"\+/-(\d\.\d+)", st["line"]).group(1)) if "+/-" in st["line"] else 9
    check("the stated uncertainty is realistic for a coast like this (0.0005 to 0.0025)", 0.0005 <= sig <= 0.0025, f"+/-{sig}")
    # the pull uses the fitted value: same numbers as typing that value in by hand, and different from the default
    grab = "() => pulls[sel].pts.map(q => q.hw)"          # wheel horsepower of every point of the pull
    auto = await pg.evaluate(grab)
    await pg.fill("#crr", st["crr"]); await pg.wait_for_timeout(300)
    by_hand = await pg.evaluate(grab)
    await pg.fill("#crr", "0.012"); await pg.wait_for_timeout(300)
    default = await pg.evaluate(grab)
    check("the pull is calculated with the fitted value (identical to typing it in), not the 0.012 default",
          max(abs(a - b) for a, b in zip(auto, by_hand)) < 1e-6 and max(abs(a - b) for a, b in zip(auto, default)) > 0.3, f"{max(abs(a - b) for a, b in zip(auto, default)):.2f} whp apart")
    st2 = await coast_state(pg)
    check("typing a Rolling Resistance keeps it (tag typed), and the line says the typed value was kept",
          st2["crr"] == "0.012" and st2["tag"] == "typed" and "kept" in st2["line"], str(st2))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()

    # 2. the same coast with no GPS: the slope is unknown, so nothing is filled and the line says why (0.1% of grade = 0.001 of Crr)
    ctx, pg, errs = await load_coast(browser, txt)
    st = await coast_state(pg)
    check("coast with no GPS elevation and no grade typed: the field is left at 0.012 and the line explains why",
          st["status"] == "nogps" and st["crr"] == "0.012" and st["tag"] == "" and "GPS" in st["line"], str(st))
    await pg.fill("#grade", "-0.4"); await pg.wait_for_timeout(300)
    st = await coast_state(pg)
    check("typing the road grade (-0.4) is enough: the fit is used and is the true value within 0.001",
          st["status"] == "ok" and abs(float(st["crr"]) - TRUE) <= 0.001 and st["tag"] == "coast", str(st))
    await ctx.close()

    # 3. a coast that is too short or too fast to beat the default is reported but not used
    txt3, t3, v3 = synth_coast(crr=TRUE, v_lift=100, v_stop=65)
    ctx, pg, errs = await load_coast(browser, txt3, synth_track(t3, v3), None)
    st = await coast_state(pg)
    check("a short coast (100 to 65 MPH) is not used: the field stays 0.012 and the line says it is too loose",
          st["status"] == "weak" and st["crr"] == "0.012" and "too loose" in st["line"], str(st))
    await ctx.close()

    # 4. in gear (engine braking): never used, with a line that says to press the clutch in
    txt4, t4, v4 = synth_coast(crr=TRUE, v_lift=100, v_stop=40, mode="gear")
    ctx, pg, errs = await load_coast(browser, txt4, synth_track(t4, v4))
    st = await coast_state(pg)
    check("an off-throttle slow-down in gear is not used (RPM follows speed), and the line says to press the clutch in",
          st["status"] == "gear" and st["crr"] == "0.012" and "clutch" in st["line"], str(st))
    await ctx.close()

    # 5. hard braking at the end of the coast is cut off, not fitted
    txtb, tb, vb = synth_coast(crr=TRUE, grade=-0.004, v_lift=100, v_stop=30, brake_after=75)
    ctx, pg, errs = await load_coast(browser, txtb, synth_track(tb, vb, grade=-0.004))
    st = await coast_state(pg)
    check("braking hard at the end of the coast does not spoil the fit (true value within 0.0015)",
          st["status"] == "ok" and abs(float(st["crr"]) - TRUE) <= 0.0015, str(st))
    await ctx.close()

    # 6. a log with no coast, or no pedal column: nothing happens and nothing is said
    txt6, t6, v6 = synth_coast(mode="none")
    ctx, pg, errs = await load_coast(browser, txt6)
    st = await coast_state(pg)
    check("a log that ends at the lift has no coast: no line, Rolling Resistance stays 0.012", st["status"] is None and st["line"] == "" and st["crr"] == "0.012", str(st))
    await ctx.close()
    txt7, _, _ = synth_coast(crr=TRUE, ped=False)
    ctx, pg, errs = await load_coast(browser, txt7)
    st = await coast_state(pg)
    check("a log with no pedal column is not searched for a coast", st["status"] is None and st["crr"] == "0.012", str(st))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()

    # 7. a new log replaces an earlier fit: a coast, then a log without one puts the default back and clears the tag
    ctx, pg, errs = await load_coast(browser, txt, track)
    first = await coast_state(pg)
    await pg.set_input_files("#file", {"name": "plain.csv", "mimeType": "text/csv", "buffer": synth_coast(mode="none")[0].encode()})
    await pg.wait_for_timeout(600)
    second = await coast_state(pg)
    check("loading a log with no coast after one with a coast puts the 0.012 default back and clears the tag",
          first["tag"] == "coast" and second["crr"] == "0.012" and second["tag"] == "" and second["line"] == "", f"{first['crr']} -> {second}")
    await ctx.close()


async def field_tags(browser):
    """A small tag in a field says where its value came from (log, gps, weather, coast, typed). It is CSS, so it can never reach Print."""
    txt, t, v = synth_coast(crr=0.0105, grade=-0.004, ambient=71.5)
    ctx, pg, errs = await open_page(browser, expand=True)
    await pg.route("**/*open-meteo.com/**", lambda r: r.fulfill(
        status=200, headers={"access-control-allow-origin": "*", "content-type": "application/json"}, body=wx_json(temp_f=68, msl=1013.25, rh=40)))
    tags = lambda: pg.evaluate("Object.fromEntries(FIELDS.map(([id]) => [id, srcOf(id)]))")
    check("before anything is loaded no field has a tag", not any((await tags()).values()))
    await pg.set_input_files("#file", {"name": "coast.csv", "mimeType": "text/csv", "buffer": txt.encode()})
    await pg.wait_for_timeout(600)
    tg = await tags()
    check("the air temperature from the log's sensor is tagged log", tg["temp"] == "log" and tg["head"] == "" and tg["humid"] == "", str(tg))
    await pg.set_input_files("#gps", {"name": "coast.gpx", "mimeType": "application/gpx+xml", "buffer": synth_track(t, v, grade=-0.004).encode()})
    await pg.wait_for_timeout(1500)
    tg = await tags()
    check("heading and grade from the GPS track are tagged gps, density altitude too (its pressure is the GPS altitude)",
          tg["head"] == "gps" and tg["grade"] == "gps" and tg["da"] == "gps", str(tg))
    check("the coast fit is tagged coast", tg["crr"] in ("coast", ""), str(tg))
    await pg.click("#wxget")
    await pg.wait_for_timeout(900)
    tg = await tags()
    check("humidity, wind and wind direction from the weather lookup are tagged weather, and so is density altitude (its sea-level pressure)",
          tg["humid"] == "weather" and tg["wind"] == "weather" and tg["wdir"] == "weather" and tg["da"] == "weather" and tg["temp"] == "log", str(tg))
    await pg.fill("#curb", "3400")
    await pg.fill("#humid", "30")
    tg = await tags()
    check("typing in a field tags it typed, and the others keep theirs", tg["curb"] == "typed" and tg["humid"] == "typed" and tg["wind"] == "weather", str(tg))
    ok = await pg.evaluate("""() => [...document.querySelectorAll('#fields label')].every((l, i) => l.firstChild.nodeType === 3 && l.children.length === 1
        && l.children[0].tagName === 'INPUT' && l.firstChild.textContent === FIELDS[i][1])""")
    check("the tag is not in the label's text or markup (Print reads the label), only in CSS", ok)
    shown = await pg.evaluate("""() => { const l = document.getElementById('humid').closest('label'); return getComputedStyle(l, '::after').content }""")
    check("the tag is drawn by CSS from data-src", shown.strip('"') == "typed", shown)
    await pg.set_input_files("#file", {"name": "plain.csv", "mimeType": "text/csv", "buffer": synth_coast(mode="none")[0].encode()})
    await pg.wait_for_timeout(600)
    tg = await tags()
    check("a new log clears the tags that came from the old data and keeps the typed ones",
          tg["temp"] == "" and tg["humid"] == "typed" and tg["curb"] == "typed" and tg["wind"] != "weather", str(tg))
    check("no page errors", not errs, "; ".join(errs))
    await ctx.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        await correction_formulas(browser)
        await gps_only(browser)
        await tile_captions(browser)
        await stepped_speed(browser)
        await boost_tile(browser)
        await coast_fit(browser)
        await field_tags(browser)
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

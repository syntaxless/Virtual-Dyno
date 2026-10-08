"""Functional checks of the dyno calculation and file handling. Exit code 1 if anything fails.

  python tools/functional.py                      # GPS + error-handling checks (bundled synthetic track)
  DYNO_LOG=/path/to/accessport.csv python tools/functional.py   # also exercises a real Accessport log

The reference numbers asserted for the owner's log (GolfR_NewEngine_4thGearPull_10_01_2026.csv, not stored
in this repo) are: 396 hp / 363 lb-ft / 312 whp at 4138 ft density altitude with Power Correction on Uncorrected, which
is the default, and 430 hp / 394 lb-ft / 339 whp with SAE J1349 chosen. The other standards are checked against factors
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
STANDARDS = [("j1349", "SAE J1349"), ("j607", "SAE J607 (STD/STP)"), ("din", "DIN 70020"), ("iso", "ISO 1585")]


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
        check("owner's log: 396 hp / 363 lb-ft / 312 whp Uncorrected (the default)", plain == ["396", "363", "312"], str(plain))
        check("owner's log: density altitude 4138 ft", da_auto.replace(",", "") == "4138", da_auto)

    # Uncorrected to start; choosing SAE J1349 raises the numbers to the corrected ones, and Uncorrected restores them
    await pg.select_option("#corr", "j1349")
    await pg.wait_for_timeout(COUNTUP_MS)
    corrected = await nums(pg)
    check("choosing SAE J1349 raises horsepower", int(corrected[0]) > int(plain[0]), f"{plain[0]} -> {corrected[0]}")
    if os.path.basename(LOG) == OWNER_LOG:
        check("owner's log: 430 hp / 394 lb-ft / 339 whp with SAE J1349", corrected == ["430", "394", "339"], str(corrected))
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


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        await correction_formulas(browser)
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

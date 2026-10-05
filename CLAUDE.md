# Virtual Dyno

A single-page, retro-terminal web app that estimates horsepower and torque from a Cobb Accessport `.csv` log
and/or GPS data (RaceBox, Dragy, GPX). Defaults are tuned for a 2016 VW Golf R. Live at
https://dyno.turboloser.co (GitHub Pages, served from `main`). The repo is public.

## Layout

- `index.html` is the entire site: inline CSS and JS in one readable file. Edit it directly.
- `CNAME` contains `dyno.turboloser.co`. Pages needs it; do not delete it.
- `tools/` holds the browser checks (see `tools/README.md`). Nothing in it is deployed.
- Only external dependencies: the VT323 Google Fonts link, and Open-Meteo APIs called with `fetch`.

## Workflow

1. `git fetch` and fast-forward first. GitHub itself or the owner may have committed (the `CNAME` file was
   created that way).
2. Edit `index.html`. There is no build or minify step: it was removed because it saved only ~1.5 KB
   gzipped and slowed every edit. Do not add one back.
3. Check in proportion to the change:
   - copy or color tweak: `python tools/shot.py` and look at the screenshot
   - layout or CSS: also `python tools/smoke.py`
   - calculation, parsing, weather or file handling: also `tools/functional.py` and `tools/weather.py`
     (they need `DYNO_LOG`, the owner's log, which is not in the repo)
4. Commit and push to `main` after each finished edit. The owner expects that, and Pages publishes within
   about a minute. Verify with a cache-busted fetch such as `https://dyno.turboloser.co/?cb=123`.
5. Never commit logs or personal data.

## How the page is built (things that are easy to break)

- **Themes** are CSS custom properties on `:root[data-phosphor="..."]`. The default green is the base; `color`
  is a Solarized palette. Tokens: `--desk --bg --screen --fg --hi --mut --dim --faint --s1 --s2 --s3 --err
  --ink --rgb --halo --bezel`. The graph canvas reads `--screen --mut --hi --dim --s1..--s3 --rgb`, and the car
  sprite reads colors through `RB.theme()`. The saved choice lives in `localStorage` key `dyno-phosphor`; its
  allow-list appears twice (the head script and the `setPhos` init). Update both when adding or removing a theme.
  A stored value that is no longer allowed falls back to green.
- **ASCII title**: an `<h1 class="vh">` (visually hidden, for accessibility) followed by `<div class="art">`.
  The font size is `min(28px, calc(100cqw/N))`, where `N = ceil(columns * 0.4 + 1)` because a VT323 character
  advances 0.4em; the art is 70 columns, so N is 29. Change the art, change N (in both declarations), and
  `smoke.py` will confirm it still fits at every width. The two `<!-- htmlmin:ignore -->` comments around it are
  leftovers from the old minifier and can be deleted.
- **Boot-in animation**: `html.bt` is set by a head script on the first visit per session (`sessionStorage`
  key `dyno-boot`); `#boot` in the URL replays it; reduced-motion visitors never get it; a click or key skips it;
  it removes itself after about 2.3 s. Each block's timing is set with `--s/--d/--t` variables in the `html.bt`
  rules, and the art's `--s` equals its row count.
- **Car & Conditions** starts collapsed (`#condtg` button, `#condbody` panel, `aria-expanded`).
- **SAE option** is `label.chk`: a hidden checkbox plus a `[ ]`/`[X]` box drawn by CSS. It is `nowrap` on purpose,
  so the label must stay short enough to fit a 320px screen.
- Text and punctuation in the file are plain ASCII (straight apostrophes), which VT323 renders reliably.
- The `<meta>` and `og:` descriptions still mention the Accessport, RaceBox/Dragy and the Golf R; the visible intro
  line was generalized to "a log file, gps data, or both" and the meta text was not.

## Testing gotchas

- The big numbers count up for ~1.5 s: wait 2.6 s before reading them (`COUNTUP_MS` in `tools/common.py`).
- Tests seed `sessionStorage` to skip the boot-in, click `#condtg` to expand Car & Conditions, and inject a local
  VT323 because the page's Google Fonts request is blocked. Run `tools/setup_font.sh` once per machine.
- Do not assert on wording in `smoke.py`; copy changes are normal. `weather.py` is a snapshot, so a legitimate
  message change means reviewing the diff and running it with `--update`.
- Reference result for the owner's log (`GolfR_NewEngine_4thGearPull_10_01_2026.csv`): 396 hp, 363 lb-ft,
  312 whp at 4138 ft density altitude; 430 hp with SAE correction. On the bundled synthetic GPS track with
  67 RPM per mph, torque is 330. If the physics changes on purpose, update `tools/functional.py`.

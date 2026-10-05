# Virtual Dyno

A single-page, retro-terminal web app that estimates horsepower and torque from a Cobb Accessport `.csv` log
and/or GPS data (RaceBox, Dragy, GPX). Defaults are tuned for a 2016 VW Golf R. Live at
https://dyno.turboloser.co (GitHub Pages, served from `main`). The repo is public.

## Layout

- `index.html` is the entire site: inline CSS and JS in one readable file. Edit it directly.
- `CNAME` contains `dyno.turboloser.co`. Pages needs it; do not delete it.
- `tools/` holds the browser checks and `cargen.py`, the car-sprite authoring aid (see `tools/README.md`). Nothing in
  it is deployed.
- `fonts/` holds the self-hosted VT323 (`vt323-latin-400-normal.woff2`) and its licence, `OFL.txt`. Deployed; keep the
  licence next to the font.
- The only external dependency is the Open-Meteo API, called with `fetch` on user action. The page makes no
  third-party request on load (no Google Fonts), and `smoke.py` checks that.

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
4. Commit and push to `main` after each finished edit. The owner expects that. Pages normally publishes within a
   couple of minutes. To confirm it is live:
   - a WebFetch caches each URL for 15 minutes and a `?cb=` query string did not reliably bypass it, so fetch a URL
     not requested recently, such as `https://dyno.turboloser.co/index.html`; that tool also drops the text of
     collapsed (`hidden`) panels, so check headings and visible text, not paragraphs inside a collapsed section
   - `gh api "repos/syntaxless/virtual-dyno/deployments?per_page=1"`, then `.../deployments/<id>/statuses`, shows
     when the newest deploy reaches `success` (the Pages builds endpoint is not available through the proxy)
5. Never commit logs or personal data.

## How the page is built (things that are easy to break)

- **Themes** are CSS custom properties on `:root[data-phosphor="..."]`. The default green is the base; `color`
  is a Solarized palette. Tokens: `--desk --bg --screen --fg --hi --mut --dim --faint --s1 --s2 --s3 --err
  --ink --rgb --halo --bezel`. The graph canvas reads `--screen --mut --hi --dim --s1..--s3 --rgb`, and the car
  sprite reads colors through `RB.theme()`. The saved choice lives in `localStorage` key `dyno-phosphor`; its
  allow-list appears twice (the head script and the `setPhos` init). Update both when adding or removing a theme.
  A stored value that is no longer allowed falls back to green.
- **ASCII title**: an `<h1 class="vh">` (visually hidden, for accessibility) followed by two banner variants, both
  `aria-hidden`: `.art.stack` (VIRTUAL over DYNO, 16 rows by 70 columns) and `.art.row` (VIRTUAL DYNO on one row,
  8 rows by 115 columns). Both are figlet "banner3-D" output. A container query on `.hgrp`
  (`@container (min-width:520px)`) shows the single row when there is room and the stacked version on phones,
  because the row would be unreadably small below that. Each variant sets its font size as
  `min(28px, calc(100cqw/N))` with `N = ceil(columns * 0.4 + 1)`, because a VT323 character advances 0.4em:
  N is 29 for the stack and 47 for the row. If you change the art, recompute N (the stack's also has a `100vw`
  fallback declaration) and run `smoke.py`, which checks that exactly one variant shows and that it fits at every width.
  The sizing assumes VT323 loaded. A fallback font is wider (measured: VT323 0.40em per character, DejaVu Sans Mono
  0.60, Liberation Mono 0.60) and the banner would overflow its column, so the page checks for it: `noFont()` sets
  `html.nofont` when the `--mono` stack measures wider than 0.45em per character (it runs when the font load settles
  and again after 3.5 s). `html.nofont` hides both banners and shows the `h1` as a plain 32px "Virtual Dyno" heading.
- **Header order**: boot prompt line, then the car (`.stage` with the `#car` canvas: 324px wide, 216px at 430px and
  below), then the banner, then the intro. The car lives inside `.hgrp`, the same container the banner's container
  query measures.
- **Cars**: `CARS` (just above the `RB` engine) is a list of 12 pixel-art cars: VW Mk7 Golf, Mk1 Rabbit and Rabbit
  Truck, Mk3 GTI and Jetta, Mk4 R32, Mk7 Sportwagen, Porsche 964 and 930 Flachbau, Audi RS2, RS6 and 90 IMSA GTO. One is
  picked at random per load, never the same one as last time (`localStorage` key `dyno-car`, which is allowed to be
  missing); `?car=<id>` forces one, which tests and screenshots use. Each entry: `id`, `cap` (the caption on the
  frame), `name` (used in the stage's aria-label), `rows` (one string per pixel row, car facing right; `H` bright,
  `B` body, `S` mid, `D` dim, `G` glass, `O` opaque background, `.` clear), `oy` (empty rows trimmed from the top),
  `wx`/`wy`/`wr` (wheel centre columns, centre row and radius; the engine draws and spins the wheels, so they are not
  in `rows`) and optional `sp` (spokes). The right edge is always drawn at canvas column 94, so a longer car grows
  leftward; keep sprites 40-80 px wide and the tyre bottom (`wy + floor(wr)`) on row 27 so it sits on the road line.
  Colours come from the theme tokens, so a sprite needs no per-theme work. No logos, badges or lettering in a sprite.
  To add or rework a car, describe it in `SPECS` in `tools/cargen.py` (metres, side profile), run it to print the
  entry, paste that into `CARS`, then run `python tools/cargen.py --sheet` and look at `tools/out/cars_*.png` in both
  themes. After pasting, `index.html` is the source of truth; `smoke.py` checks every car in the list.
- **Fonts**: one stack, `--mono` on `:root`, drives both the CSS and the graph canvas (the canvas reads the variable).
  VT323 is the look; the rest is the fallback: `ui-monospace`, SF Mono, Cascadia Mono, Menlo, Consolas, DejaVu Sans
  Mono, Liberation Mono, then `monospace`. Courier New is deliberately not in it (thin and light next to VT323).
  VT323 is self-hosted: an `@font-face` at the top of the `<style>` points at `fonts/vt323-latin-400-normal.woff2`
  (`font-display:block`, so there is no flash of the fallback). It is the `latin` subset from `@fontsource/vt323`
  5.3.0, which covers ASCII plus the symbols the page uses today (° ² ³ · ×, the en dash, curly quotes and the minus sign). Before putting
  a new non-ASCII character in the page, check it is in the font (fontTools `getBestCmap()` on the `.woff`
  from the same package) or take the `latin-ext` file; a missing glyph silently comes from another font.
- **Boot-in animation**: `html.bt` is set by a head script on the first visit per session (`sessionStorage`
  key `dyno-boot`); `#boot` in the URL replays it; reduced-motion visitors never get it; a click or key skips it;
  it removes itself after about 2.3 s. Each block's timing is set with `--s/--d/--t` variables in the `html.bt`
  rules, and the banner's `--s` equals its row count (16 for the stack, 8 for the row).
- **Collapsible sections**: Car & Conditions (`#condtg` button, `#condbody` panel) and How It Works (`#howtg`,
  `#howbody`) both start collapsed and share one click handler that flips `aria-expanded`, the panel's `hidden`
  attribute and the fieldset's `.shut` class. The "Estimates only" line is deliberately outside How It Works, in
  the `.notes` wrapper, so the disclaimer is always visible.
- **SAE option** is `label.chk`: a hidden checkbox plus a `[ ]`/`[X]` box drawn by CSS. It is `nowrap` on purpose,
  so the label must stay short enough to fit a 320px screen.
- Text and punctuation in the file are plain ASCII (straight apostrophes), which VT323 renders reliably.
- The `<meta>` and `og:` descriptions still mention the Accessport, RaceBox/Dragy and the Golf R; the visible intro
  line was generalized to "a log file, gps data, or both" and the meta text was not.

## Testing gotchas

- The big numbers count up for ~1.5 s: wait 2.6 s before reading them (`COUNTUP_MS` in `tools/common.py`).
- The car is random on every load. A test or screenshot that cares which one passes `car=` to `open_page` (or
  `--car` to `shot.py`); the layout checks are indifferent because the canvas size is fixed.
- Tests seed `sessionStorage` to skip the boot-in and click `#condtg` to expand Car & Conditions. The font needs
  no setup: the page loads `fonts/` from the repo like the live site does. `open_page(block_font=True)` and
  `shot.py --nofont` fail the `.woff2` request to show the fallback look.
- Do not assert on wording in `smoke.py`; copy changes are normal. `weather.py` is a snapshot, so a legitimate
  message change means reviewing the diff and running it with `--update`.
- Reference result for the owner's log (`GolfR_NewEngine_4thGearPull_10_01_2026.csv`): 396 hp, 363 lb-ft,
  312 whp at 4138 ft density altitude; 430 hp with SAE correction. On the bundled synthetic GPS track with
  67 RPM per mph, torque is 330. If the physics changes on purpose, update `tools/functional.py`.

# Virtual Dyno

A single-page, retro-terminal web app that estimates horsepower and torque from a Cobb Accessport `.csv` log
and/or GPS data (RaceBox, Dragy, GPX). Defaults are tuned for a 2016 VW Golf R. Live at
https://dyno.turboloser.co (GitHub Pages, served from `main`). The repo is public.

## Layout

- `index.html` is the entire site: inline CSS and JS in one readable file. Edit it directly.
- `CNAME` contains `dyno.turboloser.co`. Pages needs it; do not delete it.
- `tools/` holds the browser checks (see `tools/README.md`). Nothing in it is deployed.
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
  `aria-hidden`: `.art.stack` (VIRTUAL over DYNO, 19 rows by 68 columns) and `.art.row` (VIRTUAL DYNO on one row,
  11 rows by 106 columns). Both are figlet "banner3" lettering (7 rows tall) with the spaces drawn as dots, inside a
  frame of colons (two colon rows above and below, two colon columns at each side). The row is the owner's own art:
  it is `pyfiglet` banner3 `VIRTUAL DYNO` with 3 spaces taken out of the word gap, spaces turned into dots, and each
  row written as `::` + `.` + the row without its last character + a space + `::`. The stack was built with that
  same recipe from banner3 `VIRTUAL` (63 wide) and `DYNO` (38 wide, centred under it, with one dotted row between
  the words), so the two match; redo it the same way if the row art changes. A container query on `.hgrp` (`@container hgrp (min-width:520px)`) shows the single
  row when there is room and the stacked version on phones, because the row is too small to read below that. The art
  keeps `line-height:.8` (one cell is 0.4em wide and 0.8em tall, a 1:2 terminal cell). Each variant sets its font
  size as `min(28px, calc(100cqw/N))` with `N = ceil(columns * 0.4 + 1)`, because a VT323 character advances 0.4em:
  N is 29 for the stack and 44 for the row. If you change the art, recompute N (the stack's also has a `100vw`
  fallback declaration) and run `smoke.py`, which checks that exactly one variant shows and that it fits at every width.
  The sizing assumes VT323 loaded. A fallback font is wider (measured: VT323 0.40em per character, DejaVu Sans Mono
  0.60, Liberation Mono 0.60) and the banner would overflow its column, so the page checks for it: `noFont()` sets
  `html.nofont` when the `--mono` stack measures wider than 0.45em per character (it runs when the font load settles
  and again after 3.5 s). `html.nofont` hides the banners (`.ban`) and the TURBOLOSER sign and shows the `h1` as a
  plain 32px "Virtual Dyno" heading.
- **Header order**: boot prompt line, then `.hero` (the car, `.stage` with the `#car` canvas: 324px wide, 216px at
  430px and below, and the banner wrapper `.ban`), then the intro. There are two named containers: `.hgrp` (the
  header column; the `@container hgrp` queries measure it) and `.ban` (what the banner's `cqw` font size measures).
  When `.hgrp` is at least 1000px wide (a window of about 1084px and up) `.hero` becomes a flex row: the car on the
  left and the one-row banner to its right, centred vertically, with the banner scaled to the width that is left
  (about 14px at 1000, 17px at the 1160px window maximum). Below 1000px the banner sits under the car at full
  width (row from 520px, stack below), as before. `smoke.py` checks both arrangements, and that the beside-the-car
  banner stays at 13px or more; if you change the art or the car's width, recheck that threshold.
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
  rules, and the banner's `--s` equals its row count (19 for the stack, 11 for the row; the sign's is 10). The last
  blocks are timed to finish before the cleanup: sign 1.96 s, footer 2.1 s, prompt 2.16 s.
- **Collapsible sections**: Car & Conditions (`#condtg` button, `#condbody` panel) and How It Works (`#howtg`,
  `#howbody`) both start collapsed and share one click handler that flips `aria-expanded`, the panel's `hidden`
  attribute and the fieldset's `.shut` class. There is no "Estimates only" disclaimer line any more (the owner
  removed it: the intro already says it estimates). The page is one column at every width, in DOM order: header,
  Load Data, results (`.main`), Car & Conditions, How It Works (`.notes`), then the TURBOLOSER sign, the footer
  and the prompt line. There is no desktop/tablet split any more (the old two-column grid and its 900px
  breakpoint are gone). Keep How It Works below Car & Conditions; `smoke.py` checks the order and Load Data's
  full width at every width.
- **TURBOLOSER sign** (`div.sign`, below How It Works, above the footer): the owner's 10-row by 74-column art, a
  dotted frame with the word in `#` letters, in a `<pre>`. The wrapper is `role="img" aria-label="TURBOLOSER"` and
  the `<pre>` is `aria-hidden`. The wrapper is its own container (`container-type:inline-size`) so `cqw` works, and
  the font is `min(9px, calc(100cqw/31))` (9px is half of the 18px it had before the owner asked for it smaller; on phones the width limit (`100cqw/31`) wins, which is about 9px at 375px), with `31 = ceil(74 * 0.4 + 1)` (recompute it if the art changes, and
  keep the `100vw` fallback declaration). The `<pre>` is `width:max-content` with auto margins, so it is centred.
  Hidden by `html.nofont`. The art uses only `#`, `:`, spaces and the middle dot `·` (U+00B7, in the VT323 subset).
- **Load Data**: its two upload boxes sit in `.drops`, an auto-fit grid (`minmax(260px,1fr)`), so they are side by
  side when there is room (tablet and up) and stacked on phones. The weather form (`#wx`) is capped at 560px and the
  hint/message lines at 90ch so they stay readable at full width.
- **SAE option** is `label.chk`: a hidden checkbox plus a `[ ]`/`[X]` box drawn by CSS. It is `nowrap` on purpose,
  so the label must stay short enough to fit a 320px screen.
- Text and punctuation in the file are plain ASCII (straight apostrophes), which VT323 renders reliably.
- The `<meta>` and `og:` descriptions still mention the Accessport, RaceBox/Dragy and the Golf R; the visible intro
  line was generalized to "a log file, gps data, or both" and the meta text was not.

## Testing gotchas

- The big numbers count up for ~1.5 s: wait 2.6 s before reading them (`COUNTUP_MS` in `tools/common.py`).
- Tests seed `sessionStorage` to skip the boot-in and click `#condtg` to expand Car & Conditions. The font needs
  no setup: the page loads `fonts/` from the repo like the live site does. `open_page(block_font=True)` and
  `shot.py --nofont` fail the `.woff2` request to show the fallback look.
- Do not assert on wording in `smoke.py`; copy changes are normal. `weather.py` is a snapshot, so a legitimate
  message change means reviewing the diff and running it with `--update`.
- Reference result for the owner's log (`GolfR_NewEngine_4thGearPull_10_01_2026.csv`): 396 hp, 363 lb-ft,
  312 whp at 4138 ft density altitude; 430 hp with SAE correction. On the bundled synthetic GPS track with
  67 RPM per mph, torque is 330. If the physics changes on purpose, update `tools/functional.py`.

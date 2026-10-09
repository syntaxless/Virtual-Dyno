# tools/

Browser checks for `index.html`, and `og.py` and `icons.py`, which build the link-preview image and the app icons. Nothing here is deployed; Pages only serves the repo root files it needs.

## One-time setup

```bash
pip install playwright && playwright install chromium
pip install pillow          # only for og.py (icons.py needs nothing extra)
```

## Scripts

Run from anywhere, e.g. `python tools/smoke.py` (or `python tools/smoke.py print_button` for just one step).

| Script | What it does | Needs |
|---|---|---|
| `shot.py` | Screenshot at chosen widths/scroll/theme into `tools/out/` (`--click '#howtg'` opens a section first, `--nofont` shows the look when the font cannot load). The quick look after a text or color edit. | nothing |
| `smoke.py` | Layout at eight widths (no JS errors, no horizontal scroll, banner variant and fit, Power Correction dropdown inside its column), both collapsible sections, the Power Correction dropdown, the one-line place-date-time weather row, tile text colors and layout (four tiles across, two by two, one column), themes, boot-in gate, self-hosted font (loads from the site, no third-party requests, fallback heading when blocked), real-time Replay, the Print button (sits next to Replay, saves a JPEG under 600 KB of one fixed size on every screen, named after the uploaded file, in the current theme, with no outside request), and the installable web app (`web_app`: serves the repo on a local http server and checks the manifest, icons, theme color, that the service worker installs and keeps everything, that a changed page shows online, that the page and a log work offline, that a stalled network falls back to the kept copy, and no outside requests). Exit 1 on failure. | nothing |
| `functional.py` | GPS-only calculation, error handling, the factory-number fields and captions, whole-MPH speed rebuilt from RPM and the Peak Boost Pressure tile (both on generated logs), and (with a log) the reference numbers, every Power Correction standard against its published formula, density-altitude override, GPS attach, weather paste, and the weather temperature and pressure rules. | log optional |
| `og.py` | Renders `og.png` at the repo root, the link-preview image (the page's stacked banner on its own screen look, 1200x630, under 300 KB). `--check` writes only to `tools/out/`. Rerun after changing the banner art or palette. | Pillow |
| `icons.py` | Renders the app icons in `icons/` (192 and 512 "any", a 512 maskable, and the 180 iPhone icon): the page's dyno chart, a torque curve and a power curve crossing at 5,252 RPM, in the default theme's colors read from `index.html`. `--check` writes only to `tools/out/`. Rerun after changing the palette, then commit `icons/`. | nothing |
| `weather.py` | About 20 weather-lookup scenarios (humidity, wind, temperature, pressure) against a mocked Open-Meteo, diffed against `data/weather_expected.txt`. `--update` re-saves it. | `DYNO_LOG` |

Environment variables:

- `DYNO_LOG=/path/to/accessport.csv` enables the log-based checks. Never commit a log: the repo is public.
- `DYNO_PAGE=/path/to/candidate.html` tests another file instead of `index.html`.

`data/synthetic.gpx` is a generated track (not a real drive) used for the GPS checks.
The font is the site's own `fonts/vt323-latin-400-normal.woff2`; no test setup is needed for it.

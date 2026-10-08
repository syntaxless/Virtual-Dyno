# tools/

Browser checks for `index.html`, and `og.py`, which builds the link-preview image. Nothing here is deployed; Pages only serves the repo root files it needs.

## One-time setup

```bash
pip install playwright && playwright install chromium
pip install pillow          # only for og.py
```

## Scripts

Run from anywhere, e.g. `python tools/smoke.py`.

| Script | What it does | Needs |
|---|---|---|
| `shot.py` | Screenshot at chosen widths/scroll/theme into `tools/out/` (`--click '#howtg'` opens a section first, `--nofont` shows the look when the font cannot load). The quick look after a text or color edit. | nothing |
| `smoke.py` | Layout at eight widths (no JS errors, no horizontal scroll, banner variant and fit, Power Correction dropdown inside its column), both collapsible sections, the Power Correction dropdown, the one-line place-date-time weather row, tile text colors, themes, boot-in gate, self-hosted font (loads from the site, no third-party requests, fallback heading when blocked), real-time Replay, and the Print button (sits next to Replay, saves a PNG of one fixed size on every screen, in the current theme, with no outside request). Exit 1 on failure. | nothing |
| `functional.py` | GPS-only calculation, error handling, the factory-number fields and captions, and (with a log) the reference numbers, every Power Correction standard against its published formula, density-altitude override, GPS attach, weather paste, and the weather temperature and pressure rules. | log optional |
| `og.py` | Renders `og.png` at the repo root, the link-preview image (the page's stacked banner on its own screen look, 1200x630, under 300 KB). `--check` writes only to `tools/out/`. Rerun after changing the banner art or palette. | Pillow |
| `weather.py` | About 20 weather-lookup scenarios (humidity, wind, temperature, pressure) against a mocked Open-Meteo, diffed against `data/weather_expected.txt`. `--update` re-saves it. | `DYNO_LOG` |

Environment variables:

- `DYNO_LOG=/path/to/accessport.csv` enables the log-based checks. Never commit a log: the repo is public.
- `DYNO_PAGE=/path/to/candidate.html` tests another file instead of `index.html`.

`data/synthetic.gpx` is a generated track (not a real drive) used for the GPS checks.
The font is the site's own `fonts/vt323-latin-400-normal.woff2`; no test setup is needed for it.

# tools/

Browser checks for `index.html`. Nothing here is deployed; Pages only serves the repo root files it needs.

## One-time setup

```bash
pip install playwright && playwright install chromium
```

## Scripts

Run from anywhere, e.g. `python tools/smoke.py`.

| Script | What it does | Needs |
|---|---|---|
| `shot.py` | Screenshot at chosen widths/scroll/theme into `tools/out/` (`--click '#howtg'` opens a section first, `--nofont` shows the look when the font cannot load). The quick look after a text or color edit. | nothing |
| `smoke.py` | Layout at six widths (no JS errors, no horizontal scroll, banner variant and fit, SAE label on one line), both collapsible sections, themes, boot-in gate, self-hosted font (loads from the site, no third-party requests, fallback heading when blocked). Exit 1 on failure. | nothing |
| `functional.py` | GPS-only calculation, error handling, and (with a log) the reference numbers, SAE, density-altitude override, GPS attach, weather paste. | log optional |
| `weather.py` | About 20 weather-lookup scenarios against a mocked Open-Meteo, diffed against `data/weather_expected.txt`. `--update` re-saves it. | `DYNO_LOG` |

Environment variables:

- `DYNO_LOG=/path/to/accessport.csv` enables the log-based checks. Never commit a log: the repo is public.
- `DYNO_PAGE=/path/to/candidate.html` tests another file instead of `index.html`.

`data/synthetic.gpx` is a generated track (not a real drive) used for the GPS checks.
The font is the site's own `fonts/vt323-latin-400-normal.woff2`; no test setup is needed for it.

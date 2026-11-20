# whatshouldifly

A static page that answers one question for a brand-new Star Citizen player during
IAE: **what can I fly for free today, and is any of it worth buying?**

Built because every existing ship tool (erkul, SC-Toolbox, versefiles) is aimed at
veterans with a fleet. A new account has exactly one question on day one, and
nobody answers it on one screen.

## How it works

`build.py` pulls rental, purchase and pledge prices from the public UEX Corp API,
joins them against the published IAE 2956 rotation schedule in `data/iae_2956.json`,
and emits a self-contained static page to `site/`.

The differentiator is the verdict line per hull: try it, skip it, or here's what it
costs in-game. Not a spec table.

## Run

    python3 build.py            # writes site/index.html + site/data.json
    python3 build.py --dry      # prints the current rotation, no write
    python3 build.py --now 2026-11-24T12:00:00Z   # test a specific date

Responses are cached under `cache/` for 6 hours so reruns don't hammer the API.

## Data notes

- UEX is crowdsourced; prices are a guide, not a promise.
- Crew counts arrive as strings, sometimes comma lists (`4,7` = min,max).
- Not affiliated with Cloud Imperium Games.

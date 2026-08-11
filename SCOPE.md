# Project Scope: Cumulative Fatigue Since the 2022 World Cup

## The decision

We're scoping the dataset around **cumulative fatigue going into and since the 2022 FIFA World Cup**
(held Nov-Dec 2022, mid-season for most of the world). That World Cup forced an unprecedented
in-season pause and compressed fixture pile-up for the leagues that stopped for it — which makes it
a natural, meaningful start point for a fatigue/rest study rather than an arbitrary "last N seasons" cutoff.

## The rule

For every league, we pull data starting from the season that was underway when the World Cup happened,
or the first full season after it, depending on the league's calendar type:

- **Cross-year leagues** (season runs across two calendar years, e.g. Aug-May — most of Europe,
  Africa, Middle East): start from the **2022/2023** season, since that's the season the World Cup
  interrupted.
- **Calendar-year leagues** (season runs within one calendar year, e.g. Feb-Nov — most of the Americas,
  much of Asia): start from the **2022** season.

This means "2022" and "2022/2023" are not literally the same months of football for every league —
they're each league's own season that was live around the World Cup, or the one immediately following it.

## Reference file

`league_season_calendars.json` classifies all 66 leagues in `master_leagues.json` by `season_type`
(`cross_year` / `calendar_year`) and gives each a `target_start_season`. Each entry also carries a
`confidence` rating:

- **high** — independently confirmed this pass (major leagues, well-documented calendars)
- **medium** — standard pattern for that region/league type, not individually re-verified
- **low** — genuinely uncertain, flagged for a manual check before you rely on it

**10 leagues are flagged `low` confidence** — mostly smaller Asian, African, and Middle Eastern leagues
where the exact calendar wasn't independently confirmed. Worth a 2-minute spot-check each (their FotMob
league page shows the season list) before treating their `target_start_season` as correct.

## Resolved — Liga MX / Apertura-Clausura leagues

**Liga MX runs Apertura/Clausura but is labeled as a cross-year season** (e.g. "2022–23"), confirmed
against Wikipedia's own season articles — the two tournaments are treated as one continuous season, not
two separate ones. FotMob almost certainly follows the same convention, so `fetch_fixtures("Liga MX",
"2022/2023")` should pull both tournaments in a single call — no special handling needed.

This does NOT necessarily hold for other Apertura/Clausura leagues (Colombia, Costa Rica, Honduras,
Panama) — some countries label these same-calendar-year instead of cross-year (Colombia's Apertura +
Finalización both fall within one year). These are flagged `low` confidence in
`league_season_calendars.json` specifically because of this — worth a 2-minute FotMob check per country
before scraping them.

## Ambiguous league names — real bug, now fixed

10 league names collide across countries in `master_leagues.json` — "Premier League" alone matches 6
different countries (ENG, EGY, RUS, KAZ, GHA, ARM), "Serie A" matches 3 (ITA, BRA, ECU). The original
scripts silently took whichever match came first in the JSON file — harmless while only scraping the
unambiguous top 5, but a real risk of silently scraping the wrong country's league now that scope has
widened.

`fetch_fixtures.py` and `run_pipeline.py` now require a country hint whenever a name is ambiguous —
`fetch_fixtures("Serie A", ...)` raises an error listing the options instead of guessing; use
`"Serie A (BRA)"` / `"Serie A (ITA)"` / `"Serie A (ECU)"` instead. Unambiguous names ("LaLiga", "MLS")
work exactly as before, unchanged. `build_pipeline_config.py` enforces the same rule when generating
`pipeline_config.json`.

## What this changes downstream

- `progress_tracker.json` season keys should follow each league's `target_start_season` forward
  (e.g. LaLiga: 2022/2023, 2023/2024, 2024/2025 ... ; Brazil: 2022, 2023, 2024, 2025 ...)
- `pipeline_config.json` should list the *actual* season strings per league rather than assuming
  every league uses the same season format — a config that says `"seasons": ["2022/2023"]` for every
  league in the cross-product would silently fail or fetch the wrong thing for calendar-year leagues.

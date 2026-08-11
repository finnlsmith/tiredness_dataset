# SincereFC — Weekly Multi-Source Player Stats Pipeline

## 1. Project goal

Build a per-player **rest/fatigue and situational-splits dataset** for the top-5 European
leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1), 2025/26 season, by scraping four
independent data sources on a weekly cadence and computing deltas between snapshots.

Season starts this month (August 2026). Domestic league matches only for now — cup
competitions (Champions League, domestic cups) are explicitly **out of scope for v1**
because Opta and DataMB don't carry cup data at all, so cross-source splits would be
incomplete. Revisit cups later as a FotMob/WhoScored-only enrichment.

## 2. The four sources — what each gives you

| Source | Data shape | What it uniquely offers |
|---|---|---|
| **FotMob** | Match-by-match (one JSON per fixture) | Only source with a real timeline — chronological build-up, not just totals |
| **Opta** (via theanalyst.com) | Season-to-date totals, category-namespaced (attack/carries/defending/goalkeeping/possession) | Broad, well-structured category totals |
| **WhoScored** | Season-to-date, split by *situation/type* (shots by open-play/counter/set-piece/penalty, passes by corner/freekick/cross, etc.) | Situational context no other source has |
| **DataMB** | Season-to-date per-90 rates, position-split files (GK/CB/FB/CM/FW/ST) | Widest stat surface (143 cols), directional/positional detail (crosses by flank, pass length splits) |

Because Opta/WhoScored/DataMB only give **cumulative totals as of scrape time**, the
plan is to scrape them **after every matchweek** and compute `this_week_total -
last_week_total` per player to derive per-round deltas. FotMob doesn't need this trick —
it's already match-level.

**Known limitation to carry forward:** the delta trick only works cleanly if a player's
team plays exactly once in the round being measured. Fine for domestic-only v1;
will need rework once cups are added back in (a club could play twice in a "round").

## 3. Player identity — already solved

A cross-source player identity table already exists: `master_player_table.csv` +
`master_player_table_DATA_DICTIONARY.md` (attached separately). 16,871 rows, one per
real player, `confidence_tier` column (gold/silver/bronze/etc.) indicates how many of
the 4 sources agree on the match. Opta's `player_id`/`date_of_birth`/`canon_team` is
the anchor spine; DataMB has no native ID and was matched via composite
name+team+age fuzzy matching; a 75-entry team-name crosswalk resolves spelling
differences across sources (e.g. "Atlético de Madrid" / "Atletico Madrid" / "Atlético Madrid").

**Open question to resolve during build:** this table's WhoScored columns are
bio/meta only (age, height, weight, position) — no performance stats were folded in.
The situational stat content (the `EPL_dfs_by_metric.pkl`-style data) still needs to be
joined in separately. Decide whether to extend the master table or join WhoScored
stats in as their own step per snapshot.

**Practical use:** treat this master table as the reusable identity crosswalk. Every
weekly snapshot's raw player IDs (per source) get mapped through this table to get
one canonical `player_id` before deltas/joins happen. It does not need to be rebuilt
weekly — only re-run if a large number of new/unmatched players appear (e.g.
transfer window).

## 4. Scrape mechanics per source — what's proven to work

All four sources are accessed via **undocumented public/internal APIs, not paid
programmatic access** — no source requires passing account credentials
programmatically. Where a "login" appears, it's actually anti-bot verification (cookies/
tokens harvested from a real browser session), not authentication to a paid tier.

### FotMob — fully working, fully scriptable already
Existing scripts: `fetch_fixtures.py`, `scrape_match_details.py`
- Headless Playwright loads a real FotMob page, intercepts the `x-mas` header +
  cookies + user-agent off the live request FotMob's own frontend makes
- Those captured values are then reused in plain `requests.get()` calls — no browser
  needed for the actual data pulls, only for the initial token harvest
- `fetch_fixtures.py <league> <season>` → fixtures JSON with every match + `matchId`
- `scrape_match_details.py <fixtures_file> <output_dir> <league>` → loops all
  finished matches, hits `api/data/matchDetails?matchId=`, saves one JSON per match
- Known bug (solved): FotMob's endpoint occasionally returns the *wrong* match's
  data for a given ID — fix was renaming the saved file to the match's *internal* ID
  rather than the requested one, not re-scraping
- **This pipeline just needs a scheduler wrapper — the core mechanics are done.**

### WhoScored — same pattern, needs headless-ification
Existing script: `whoscored_scrape_update_2.py` (Selenium-based)
- Opens a real league page, currently requires a human to accept cookies/close ads
  and press Enter — **this is a consent-banner dismissal, not authentication**, so it's
  automatable (Playwright/Selenium can click the same button)
- Then runs `fetch()` calls *from inside the loaded page's JS context* via
  `execute_async_script`, so requests inherit the page's own session/cookies/origin
- Hits `whoscored.com/statisticsfeed/1/getplayerstatistics` per (category,
  subcategory) pair — 13 collections currently configured (goals/situations,
  shots/situations, passes/type, tackles/success, etc.)
- **To-do:** replace the manual `input()` pause with an automated cookie-banner
  click; otherwise this is close to done.
- Coverage note: WhoScored's overall match rate against Opta is lower (~80% vs
  ~96% for FotMob) — reflects WhoScored simply having fewer total players tracked,
  not a matching-quality issue.

### Opta (via theanalyst.com) — same pattern, already headless
Existing scripts: `grab_data_from_opta_api_2.py`, `opta_json_to_csv.ipynb`
- **This is Stats Perform's public media site (theanalyst.com), not a paywalled Opta
  product** — no login step exists in the script at all
- Headless Playwright loads the public stats page, harvests cookies (the `STYXKEY`
  cookie is almost certainly an anti-bot/bot-management cookie, not a session token)
- Replays those cookies against `theanalyst.com/wp-json/sdapi/v1/soccerdata/tournamentstats`
  per league (tournament ID + post ID pairs hardcoded per league in the script)
- **Known unresolved issue:** EPL currently works, but Bundesliga/LaLiga/Ligue1/SerieA
  were returning HTTP 401 in the last test run. Needs investigation — likely the
  cookie/tournament-ID pairing needs per-league verification, or cookies aren't
  transferring correctly across the loop iterations (each league gets its own
  `page.goto()` + fresh cookie grab in the current script — worth checking whether
  that's actually succeeding for the failing leagues, or silently reusing stale state).
- `opta_json_to_csv.ipynb` parses the raw JSON (nested attack/carries/defending/
  goalkeeping/possession keys, with possession further split into
  chanceCreation/passing) into one merged-per-player CSV per league.

### DataMB — simplest, may need zero browser at all
- Confirmed: `https://datamb.football/database/CURRENT/TOP72526/{POS}/{POS}.xlsx`
  (POS = GK/CB/FB/CM/FW/ST) is **fully public, zero auth, CORS-open** — plain
  `requests.get()` with no cookies works, verified by testing with no session at all
- This covers top-7 European leagues, >1000 minutes played, 143 per-90 columns
- Broader world coverage exists at `PRO2526` and `PRO2026` path variants (same
  `{POS}/{POS}.xlsx` pattern, different folder) — **these were only ever tested from
  within an authenticated browser session; not yet confirmed to work unauthenticated.**
  Test this before assuming the same "fully open" status applies — if they require
  the session cookie, this source moves from "trivially automatable" to "needs the
  same headless-cookie pattern as the other three."
- Not currently needed for v1 scope (top-5 leagues only), but useful to know for
  later expansion.
- Per-90 → totals conversion: `total = per90_stat * (minutes_played / 90)`

## 5. System architecture — the agreed design

**Schedule-first, not poll-first.** Don't discover "did the matchweek end" by
repeatedly checking live `finished` flags. Instead:

1. Pull each league's full fixture list once per season via the existing FotMob
   fixtures pipeline (`fetch_fixtures.py`) — gives dates/times for every round upfront
2. For each round, precompute a **trigger time** = latest scheduled kickoff in that
   round + a buffer (~2 hours) for the match to actually finish
3. Store these trigger times as the schedule that drives everything downstream
4. **Periodically** (weekly is plenty) re-pull the fixture list and diff against the
   stored version — if any match's date/time changed (postponement, reschedule),
   recompute that round's trigger time
5. Whatever's running the automation (GitHub Actions `schedule:` cron, or similar)
   fires the scrape job at each stored trigger time

**What "the scrape job" actually does when triggered, per source:**
- **FotMob**: for each newly-finished match ID in that round, hit `matchDetails`,
  save one JSON per match (already works via `scrape_match_details.py`)
- **WhoScored / Opta / DataMB**: re-run the full-league stat pull, save as a
  **dated snapshot file** (e.g. `whoscored_EPL_2026-08-18.csv`) — never overwrite
  previous snapshots, since deltas are computed by subtracting consecutive
  snapshot files

**Deltas:** once two consecutive dated snapshots exist for a source, per-player
delta = `this_snapshot_value - previous_snapshot_value`. Tag each delta with round
metadata (home/away, day/night, rest days, opponent) to build the "splits" the whole
project is for.

## 6. Status tracker / dashboard — requirements

One row per (league, round, source) combination. Fields needed:
- Expected trigger time (from precomputed schedule)
- Status: `pending` / `success` / `failed` / `needs-retrigger` (e.g. round had a
  postponed match that finished later)
- Last attempt timestamp
- Row/record count from that run, compared against an expected baseline (catches
  silent failures where the request "succeeds" but returns near-empty/garbage data
  — e.g. WhoScored usually returns ~528 EPL players; a run returning 40 is a red
  flag even with HTTP 200)
- Error/notes field for whatever actually went wrong (401, empty payload, schema
  mismatch, wrong-match-ID bug, etc.)

Desired view: at-a-glance grid, leagues down one axis, rounds across the other,
color-coded per source/status, so a full season's health is scannable without
digging through logs.

## 7. Known open items to resolve during build

1. **Opta 401s on 4 of 5 leagues** — needs debugging (see §4)
2. **DataMB `PRO2526`/`PRO2026` auth status** — confirm whether unauthenticated
   requests work (not needed for v1 top-5 scope, but good to resolve)
3. **WhoScored performance stats not yet joined into the master player identity
   table** — currently bio/meta only in that table; the situational stat pkl data
   needs its own join step
4. **Multi-match rounds** (once cups are back in scope) will break the simple
   "one snapshot per round = one match's worth of delta" assumption — needs a
   redesign at that point, not now
5. **Where the actual scrape requests run from** — GitHub Actions is fine for
   *scheduling/triggering*, but a shared runner IP hitting the same anti-bot-
   protected endpoints on a fixed weekly cadence is more fingerprint-able than a
   home/residential IP. Consider whether the token-harvest + request step should
   run somewhere less shared, even if the scheduling logic lives in Actions.

## 8. Existing scripts inventory (all provided separately, to hand to Claude Code)

- `fetch_fixtures.py` — FotMob fixtures puller, headless token harvest included
- `scrape_match_details.py` — FotMob match-by-match scraper, same token pattern
- `whoscored_scrape_update_2.py` — WhoScored scraper, Selenium, currently has a
  manual `input()` pause to remove
- `manipulate_whoscored_jsons.ipynb` — parses raw WhoScored JSON into per-metric
  DataFrames + player meta CSV
- `grab_data_from_opta_api_2.py` — Opta/theanalyst scraper, Playwright cookie
  harvest, currently 401ing on 4/5 leagues
- `opta_json_to_csv.ipynb` — parses raw Opta JSON into merged per-player CSVs
- `master_player_table.csv` + `master_player_table_DATA_DICTIONARY.md` — the
  cross-source player identity crosswalk (see §3)

## 9. Suggested build order

1. Wrap FotMob's existing pipeline in the schedule-trigger logic (§5) — it's the
   most complete, so it validates the scheduling approach fastest
2. Fix WhoScored's manual pause, wire it into the same trigger system
3. Debug and fix Opta's 401 issue, wire it in
4. Build the status tracker/dashboard against real run data from the above
5. DataMB last — lowest complexity, can be added any time
6. GitHub Actions wiring once the individual pieces are proven to run standalone

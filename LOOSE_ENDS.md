# Tiredness Dataset — Open Items & Loose Ends

_Snapshot as of tonight's session. 115 leagues tracked in `progress_tracker.json`, spanning club leagues and domestic cups, both laptops merged and pushed._

## What's genuinely done

- Every club league in `master_leagues.json` attempted, across both laptops.
- Every domestic cup in `master_leagues.json` attempted, across both laptops.
- Two real data-integrity bugs found and fixed at the source (not just patched around):
  - **Missing lineup data**: some leagues/seasons have `coverageLevel: "lower"` and `lineup: null` — real matches, real scores, but no player-level data at all, which is invisible to normal success/failed counts.
  - **Cup sampling bias**: the original lineup preflight only checked a competition's *earliest* matches. For cups, early rounds involve small/reserve clubs with poor coverage while later rounds (semis, finals — the clubs that actually matter) have real data. Fixed by sampling both ends of the fixture list.
- `run_pipeline.py` now has two automatic safety nets before committing to a full scrape:
  1. **Lineup-coverage preflight** (`check_lineup_coverage.py`) — samples matches from both ends, excludes automatically if no real lineup data exists.
  2. **Season-mismatch check** — some leagues silently return the *wrong year* when queried with an unsupported season-string format (FotMob falls back to whatever's currently live instead of erroring). Caught by comparing the API's `selected_season` against what was requested.

## Not started at all

- **Internationals** — World Cup qualifiers, Nations League, continental championships (Euros, Copa América, AFCON, etc.). Not in `master_leagues.json` at all (that catalog is club/continental-club only). Needs its own discovery step to find correct FotMob IDs before any scraping can start. Structurally different per confederation — UEFA's Nations League format looks nothing like CONCACAF's or CAF's qualifying. Treat as its own project, not an extension of tonight's approach.

## Catalog completeness — unverified assumption

- `master_leagues.json` was never systematically cross-checked against `fotmob_world_cup_team_ids.json` to confirm every 2022 World Cup squad player's league is actually represented. It's the catalog we had, not a verified-exhaustive one. Worth a real check before considering "all relevant leagues" done.

## Genuinely excluded — no usable data (leave as-is, don't re-attempt)

**Leagues, whole (all seasons), no lineup data anywhere:**
Iraq, Algeria, Ghana, Slovenia, Wales, Armenia, New Zealand, Kazakhstan, Malaysia, Panama, Paraguay, Uzbekistan, Venezuela.

**Leagues, partial (early seasons excluded, most recent season(s) genuinely have real coverage):**
Iran, Israel, Qatar, Serbia (2022/23–2024/25 excluded, 2025/26 kept), Morocco (2022/23–2023/24 excluded, rest kept), Tunisia (2022/23–2024/25 excluded, 2025/26 kept).

**Cups, whole (rechecked with the fixed both-ends sampling — trust this verdict):**
Svenska Cupen (SWE), Welsh Cup (WAL), Kup Srbije (SRB), FAI Cup (IRL), Slovenia Cup (SVN).

**Cups, partial (some seasons recovered after the sampling fix, others genuinely still bad):**
Egypt Cup (2023/24 excluded, others kept), Nedbank Cup RSA (2022/23–2023/24 excluded, 2024/25 kept), UAE Cup (2022/23–2023/24 excluded, 2024/25 kept), Cyprus Cup (2022/23–2023/24 excluded, rest kept), State Cup ISR (only 2025/26 kept), Magyar Kupa (only 2022/23 excluded), FA Cup SVK (only 2025/26 kept).

## Real loose ends — need action in a future session

1. **Hazfi Cup (IRN) and Cup (KOR) were never rechecked with the fixed sampling.** These were excluded very early (small pilot test batch) using the *old, biased* preflight, before the both-ends fix existed. Given Puchar Polski and 34 other cups flipped from excluded to genuinely good once rechecked, these two are prime candidates to also flip. Nobody re-ran them after the fix — a real gap, not a confirmed dead end. Use `find_excluded_cups.py`-style approach with `arg_9305`-equivalent keys `irn_9487` and `kor_9551` added to the list.

2. **Mexico (Liga MX) — still unresolved, suspiciously low match count.** Only ~27 matches per season scraped, way too few for a real full season. Flagged early, theorized as an Apertura/Clausura season-string issue, but this is likely a *different* failure mode than what the season-mismatch check catches (that check compares `selected_season` to what was requested — Mexico's `selected_season` may have matched fine even though only a fragment of matches came back). Never actually diagnosed. Needs its own investigation, probably similar to the Costa Rica/Colombia/Honduras date-range check done earlier tonight.

3. **Copa de la Liga Profesional (ARG) 2025 — excluded via season-mismatch check, never chased down.** Just one pair; low priority but not investigated at all.

4. **Top 5 leagues' 2023/24 and 2024/25 seasons still carry pre-session "seeded from project history" tags** — `success: null`, `updated_by: "unknown"`, notes say "exact match counts not recorded, verify against raw_json/ folder." These predate tonight's pipeline entirely and were never actually re-run through the real, verified pipeline. Almost certainly fine (top 5 leagues, unlikely to have lineup gaps) but never confirmed with real numbers.

5. **Two permanently unrecoverable Brazil matches** (Internacional vs Botafogo RJ 2022, Flamengo vs Mirassol 2025) — documented as a real, investigated, accepted gap (FotMob reassigned the match IDs to future fixtures). Not actionable, just noted here so it isn't mistaken for an oversight later.

## Tooling reference for next session

- `run_pipeline.py` — main entry point. `--force` re-runs anything already `complete` or `excluded`. Skips by default otherwise.
- `check_lineup_coverage.py` — the preflight module, imported by `run_pipeline.py`. Samples `DEFAULT_SAMPLE_SIZE = 4` matches (2 from each end of the fixture list).
- `build_pipeline_config.py` — only works for leagues in `league_season_calendars.json`. **Does not work for cups** — cups need hand-written `pipeline_config.json` entries with a guessed season format (slash-style `"2022/2023"` or calendar-year `"2022"`), which the season-mismatch check will catch if wrong.
- `find_excluded_cups.py` — pattern for finding everything marked `excluded` and re-running with `--force` after a check-logic fix. Reusable for the Hazfi Cup / Cup (KOR) recheck above.
- Git workflow: both laptops share one `progress_tracker.json`. Always `git fetch && git status` before assuming you're up to date. When both laptops have uncommitted local changes, use `git stash push -m "..." progress_tracker.json pipeline_config.json`, then `git pull`, then compare pulled vs. stashed with a small Python diff script before merging — never trust git's line-based merge on this file, it's semantically a keyed dict, not text.

"""
Scrape match details for all finished matches in a fixture file.

Usage (unchanged):
    python scrape_match_details.py <fixtures_file> <output_dir> <league_name>

Example:
    python scrape_match_details.py esp_87_2024_2025_fixtures.json raw_json/laliga_2024_2025 LaLiga

Can also be imported and called directly:
    from scrape_match_details import scrape_match_details
    result = scrape_match_details("esp_87_2024_2025_fixtures.json", "raw_json/laliga_2024_2025", "LaLiga")
    # result == {"success": n, "failed": n, "skipped": n, "related_competition": n}

NOTE on classification (history, most recent fix 2026-08-11):
    v1: compared FotMob's returned `leagueName` against the short catalog
        name passed in on the command line (e.g. "MLS"). Broke for any
        league whose catalog short-name doesn't match FotMob's own display
        string — e.g. MLS returns "Major League Soccer", so every match
        failed the comparison and got wrongly bucketed as related.

    v2: self-calibrated off the first successfully-fetched match's
        leagueName instead of a fixed string. Fixed the v1 problem, but
        turned out to be fragile in its own way: if fixture order isn't
        guaranteed and an early match happens to carry an alternate/older
        branding name (a mid-scrape rename, e.g. "Saudi Pro League" vs
        "Saudi Professional League"), the baseline locks onto the MINORITY
        name and flips the whole run's classification backwards. Confirmed
        on Saudi Pro League 2023/24: 273 of 306 legitimate matches got
        wrongly marked "related" because the baseline happened to calibrate
        off a rebranded label seen early in the run.

    v3 (current): don't try to match any single "correct" name at all.
        Classify by whether leagueName contains language indicating a
        genuinely different SUB-COMPETITION (playoff, group stage,
        relegation/promotion round, qualifiers) - anything else counts as
        the real season, regardless of which of a league's rebranded names
        it happens to use. This correctly handles same-league renames
        (Saudi, Belgium's Pro League/First Division A) AND genuine
        sub-competitions (MLS Cup Playoffs, Eredivisie ECL Playoff, Belgian
        Championship/Relegation/ECL playoff groups) without depending on
        fixture order or any hardcoded per-league name mapping.

        Caveat: this only distinguishes sub-competitions of the SAME
        league from the main season - it does NOT verify the match is even
        the right league at all (that would need a leagueId/parentLeagueId
        check). If a genuinely wrong-league match ever showed up with a
        bland name containing none of the keywords below, it would be
        wrongly counted as success. Worth an occasional spot-check via
        leagueId on high-related-count seasons rather than trusting this
        blindly forever.
"""

import json
import sys
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

DELAY = 1.5

RELATED_KEYWORDS = ["playoff", "play-off", "relegation", "promotion", "qualif", "group"]


def classify_league_name(league_name: str) -> str:
    """
    Returns "success" if this looks like the main league season, "related"
    if the name indicates a sub-competition (playoff/group/etc), or
    "unknown" if no name was returned at all.
    """
    if league_name is None:
        return "unknown"
    lname = league_name.lower()
    if any(kw in lname for kw in RELATED_KEYWORDS):
        return "related"
    return "success"


def scrape_match_details(fixtures_filename: str, output_dir: str, league_name: str, league_id: int = None) -> dict:
    """
    Scrape match details for every finished match in fixtures_tiredness/<fixtures_filename>,
    saving each to <output_dir>/<match_id>.json. Skips files that already exist.

    Returns {"success": n, "failed": n, "skipped": n, "related_competition": n}.

    `league_name` is used only for display/logging - classification is done
    via classify_league_name() based on sub-competition keywords, not by
    comparing against this string.
    """
    fixtures_file = Path("fixtures_tiredness") / fixtures_filename
    out_dir       = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ─── Step 1: Load fixtures ─────────────────────────────────────────────────
    with open(fixtures_file) as f:
        fixture_data = json.load(f)

    all_matches = fixture_data["data"]["fixtures"]["allMatches"]
    finished    = [m for m in all_matches if m["status"].get("finished")]
    print(f"Loaded {fixtures_file.name}: {len(finished)} finished matches\n")

    if not finished:
        print("No finished matches to scrape.")
        return {"success": 0, "failed": 0, "skipped": 0, "related_competition": 0}

    sample_match    = finished[0]
    sample_page_url = f"https://www.fotmob.com{sample_match['pageUrl'].split('#')[0]}"

    # ─── Step 2: Playwright intercepts token ───────────────────────────────────
    captured = {}

    def handle_request(request):
        if "api/data/matchDetails" in request.url:
            h = request.headers
            if "x-mas" in h and not captured.get("x-mas"):
                print("✓ Intercepted x-mas token")
                captured["x-mas"]      = h["x-mas"]
                captured["cookie"]     = h.get("cookie", "")
                captured["user-agent"] = h.get("user-agent", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()
        page.on("request", handle_request)
        print(f"Opening {sample_page_url} to intercept token ...")
        page.goto(sample_page_url, wait_until="networkidle", timeout=30000)
        browser.close()

    if not captured.get("x-mas"):
        raise RuntimeError("Failed to capture x-mas token — try a different match page URL")

    def build_headers(referer):
        return {
            "accept":             "*/*",
            "accept-language":    "en-US,en;q=0.9",
            "cache-control":      "no-cache",
            "pragma":             "no-cache",
            "user-agent":         captured["user-agent"],
            "cookie":             captured["cookie"],
            "x-mas":              captured["x-mas"],
            "referer":            referer,
            "sec-ch-ua":          '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-mobile":   "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest":     "empty",
            "sec-fetch-mode":     "cors",
            "sec-fetch-site":     "same-origin",
        }

    # ─── Step 3: Scrape match details ──────────────────────────────────────────
    total   = len(finished)
    success = 0
    failed  = 0
    skipped = 0
    related = 0  # matches under a sub-competition (playoffs, groups, etc.) - still saved, tracked separately

    print(f"\nScraping {total} matches into {out_dir} ...\n")

    for i, match in enumerate(finished):
        match_id = match["id"]
        out_path = out_dir / f"{match_id}.json"

        if out_path.exists():
            skipped += 1
            continue

        home           = match["home"]["name"]
        away           = match["away"]["name"]
        url            = f"https://www.fotmob.com/api/data/matchDetails?matchId={match_id}"
        match_page_url = f"https://www.fotmob.com{match['pageUrl'].split('#')[0]}"

        try:
            r = requests.get(url, headers=build_headers(match_page_url), timeout=10)

            if r.status_code != 200:
                print(f"[{i+1}/{total}] ✗ HTTP {r.status_code}: {match_id} — {home} vs {away}")
                failed += 1
                continue

            data          = r.json()
            general       = data.get("general", {})
            league        = general.get("leagueName")
            parent_id     = general.get("parentLeagueId")
            finished_flag = general.get("finished")

            if not finished_flag:
                print(f"[{i+1}/{total}] ✗ Not actually finished: {match_id} — {home} vs {away}")
                failed += 1
                continue

            with open(out_path, "w") as f:
                json.dump({"pageProps": data}, f)

            wrong_league   = (league_id is not None and parent_id is not None and parent_id != league_id)
            classification = classify_league_name(league)

            if wrong_league:
                print(f"[{i+1}/{total}] Wrong league saved (league='{league}', parentLeagueId={parent_id} != {league_id}): {home} vs {away} ({match_id})")
                related += 1
            elif classification == "related":
                print(f"[{i+1}/{total}] ⚑ Related competition saved (league='{league}'): {home} vs {away} ({match_id})")
                related += 1
            elif classification == "unknown":
                print(f"[{i+1}/{total}] ? No league name returned, saved anyway: {home} vs {away} ({match_id})")
                related += 1  # conservative: don't silently call it success with no evidence
            else:
                print(f"[{i+1}/{total}] ✓ {home} vs {away} ({match_id})")
                success += 1

        except Exception as e:
            print(f"[{i+1}/{total}] ✗ Error on {match_id}: {e}")
            failed += 1

        time.sleep(DELAY)

    print(f"\nDone. ✓ {success} saved | ⚑ {related} related-competition | ✗ {failed} failed | ⏭ {skipped} skipped")
    return {"success": success, "failed": failed, "skipped": skipped, "related_competition": related}


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python scrape_match_details.py <fixtures_file> <output_dir> <league_name>")
        sys.exit(1)

    try:
        scrape_match_details(sys.argv[1], sys.argv[2], sys.argv[3])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)

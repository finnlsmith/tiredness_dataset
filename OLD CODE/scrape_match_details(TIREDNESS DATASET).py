"""
Scrape match details for all finished matches in a fixture file.

Usage:
    python scrape_match_details.py <fixtures_file> <output_dir> <league_name>

Example:
    python scrape_match_details.py esp_87_2024_2025_fixtures.json raw_json/laliga_2024_2025 LaLiga
"""

import json
import sys
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

# ─── Args ────────────────────────────────────────────────────────────────────

if len(sys.argv) != 4:
    print("Usage: python scrape_match_details.py <fixtures_file> <output_dir> <league_name>")
    sys.exit(1)

FIXTURES_FILE = Path("fixtures_tiredness") / sys.argv[1]
OUTPUT_DIR    = Path(sys.argv[2])
LEAGUE_NAME   = sys.argv[3]
DELAY         = 1.5

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Step 1: Load fixtures ────────────────────────────────────────────────────

with open(FIXTURES_FILE) as f:
    fixture_data = json.load(f)

all_matches = fixture_data["data"]["fixtures"]["allMatches"]
finished    = [m for m in all_matches if m["status"].get("finished")]
print(f"Loaded {FIXTURES_FILE.name}: {len(finished)} finished matches\n")

# Grab any match page URL to use as the Playwright interception target
sample_match    = finished[0]
sample_page_url = f"https://www.fotmob.com{sample_match['pageUrl'].split('#')[0]}"

# ─── Step 2: Playwright intercepts token ─────────────────────────────────────

captured = {}

def intercept_token():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        def handle_request(request):
            if "api/data/matchDetails" in request.url:
                h = request.headers
                if "x-mas" in h and not captured.get("x-mas"):
                    print("✓ Intercepted x-mas token")
                    captured["x-mas"]      = h["x-mas"]
                    captured["cookie"]     = h.get("cookie", "")
                    captured["user-agent"] = h.get("user-agent", "")

        page.on("request", handle_request)
        print(f"Opening {sample_page_url} to intercept token ...")
        page.goto(sample_page_url, wait_until="networkidle", timeout=30000)
        browser.close()

    if not captured.get("x-mas"):
        raise RuntimeError("Failed to capture x-mas token — try a different match page URL")

intercept_token()

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

# ─── Step 3: Scrape match details ─────────────────────────────────────────────

total   = len(finished)
success = 0
failed  = 0
skipped = 0

print(f"\nScraping {total} matches into {OUTPUT_DIR} ...\n")

for i, match in enumerate(finished):
    match_id       = match["id"]
    out_path       = OUTPUT_DIR / f"{match_id}.json"

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
        league        = data.get("general", {}).get("leagueName")
        finished_flag = data.get("general", {}).get("finished")

        if league != LEAGUE_NAME or not finished_flag:
            print(f"[{i+1}/{total}] ✗ Bad data (league='{league}', finished={finished_flag}): {match_id} — {home} vs {away}")
            failed += 1
            continue

        with open(out_path, "w") as f:
            json.dump({"pageProps": data}, f)

        print(f"[{i+1}/{total}] ✓ {home} vs {away} ({match_id})")
        success += 1

    except Exception as e:
        print(f"[{i+1}/{total}] ✗ Error on {match_id}: {e}")
        failed += 1

    time.sleep(DELAY)

print(f"\nDone. ✓ {success} saved | ✗ {failed} failed | ⏭ {skipped} skipped")

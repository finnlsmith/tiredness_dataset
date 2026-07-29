"""
Step 1 of the pipeline: use Playwright to navigate to the LaLiga 2024/25 page,
intercept the x-mas token and cookie from the network request, then immediately
use them to fetch the fixture list and save it to disk.
"""

import json
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

LEAGUE_ID   = 87
LEAGUE_NAME = "laliga"
LEAGUE_KEY  = "esp_87"
SEASON      = "2024/2025"
SEASON_SLUG = "2024_2025"
CCODE       = "USA_NY"
OUT_DIR     = Path("fixtures_tiredness")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE_URL = f"https://www.fotmob.com/leagues/{LEAGUE_ID}/overview/{LEAGUE_NAME}?season=2024-2025"
API_URL  = f"https://www.fotmob.com/api/data/leagues?id={LEAGUE_ID}&ccode3={CCODE}&season=2024%2F2025"

captured = {}

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        # Intercept the leagues API request to grab headers
        def handle_request(request):
            if f"api/data/leagues?id={LEAGUE_ID}" in request.url and "season=" in request.url:
                headers = request.headers
                if "x-mas" in headers:
                    print(f"✓ Intercepted x-mas token")
                    captured["x-mas"]   = headers["x-mas"]
                    captured["cookie"]  = headers.get("cookie", "")
                    captured["user-agent"] = headers.get("user-agent", "")

        page.on("request", handle_request)

        print(f"Navigating to {PAGE_URL} ...")
        page.goto(PAGE_URL, wait_until="networkidle", timeout=30000)

        browser.close()

    if not captured.get("x-mas"):
        print("✗ Failed to capture x-mas token. Try increasing the timeout or check the URL.")
        return

    # Now immediately use the token to fetch fixtures
    headers = {
        "accept":             "*/*",
        "accept-language":    "en-US,en;q=0.9",
        "user-agent":         captured["user-agent"],
        "cookie":             captured["cookie"],
        "x-mas":              captured["x-mas"],
        "referer":            PAGE_URL,
        "sec-ch-ua":          '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest":     "empty",
        "sec-fetch-mode":     "cors",
        "sec-fetch-site":     "same-origin",
    }

    print(f"Fetching fixtures from API ...")
    r = requests.get(API_URL, headers=headers, timeout=15)

    if r.status_code != 200:
        print(f"✗ API returned HTTP {r.status_code}")
        return

    data        = r.json()
    sel_season  = data.get("details", {}).get("selectedSeason", "")
    all_matches = data.get("fixtures", {}).get("allMatches", [])
    finished    = [m for m in all_matches if m["status"].get("finished")]
    upcoming    = [m for m in all_matches if not m["status"].get("finished")]

    if sel_season != SEASON:
        print(f"⚠️  Season mismatch: requested '{SEASON}' but got '{sel_season}'")
    else:
        print(f"✓ Season confirmed: {sel_season}")

    print(f"✓ {len(finished)} finished | {len(upcoming)} upcoming")

    output = {
        "meta": {
            "league_key":       LEAGUE_KEY,
            "league_id":        LEAGUE_ID,
            "league_name":      "LaLiga",
            "country":          "ESP",
            "requested_season": SEASON,
            "selected_season":  sel_season,
            "finished_count":   len(finished),
            "upcoming_count":   len(upcoming),
        },
        "data": data
    }

    out_path = OUT_DIR / f"{LEAGUE_KEY}_{SEASON_SLUG}_fixtures.json"
    with open(out_path, "w") as f:
        json.dump(output, f)

    print(f"✓ Saved to {out_path}")

if __name__ == "__main__":
    run()

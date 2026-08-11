"""
Fetch fixture list for a given league and season using Playwright to intercept
the x-mas token, then immediately hit the FotMob API.

Looks up league metadata from master_leagues.json automatically.

Usage:
    python fetch_fixtures.py <league_name> <season>

Example:
    python fetch_fixtures.py LaLiga "2023/2024"
    python fetch_fixtures.py "Premier League" "2022/2023"
"""

import json
import sys
import re
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

# ─── Args ─────────────────────────────────────────────────────────────────────

if len(sys.argv) != 3:
    print('Usage: python fetch_fixtures.py <league_name> <season>')
    print('Example: python fetch_fixtures.py LaLiga "2023/2024"')
    sys.exit(1)

LEAGUE_NAME_ARG = sys.argv[1]
SEASON          = sys.argv[2]
CCODE           = "USA_NY"

# ─── Lookup league from master_leagues.json ───────────────────────────────────

MASTER_LEAGUES = Path("master_leagues.json")
if not MASTER_LEAGUES.exists():
    print("✗ master_leagues.json not found in current directory")
    sys.exit(1)

with open(MASTER_LEAGUES) as f:
    leagues = json.load(f)

match = next(
    (l for l in leagues if l["name"].lower() == LEAGUE_NAME_ARG.lower()),
    None
)

if not match:
    print(f"✗ League '{LEAGUE_NAME_ARG}' not found in master_leagues.json")
    print("Available leagues:")
    for l in leagues:
        print(f"  {l['name']}")
    sys.exit(1)

LEAGUE_ID   = match["id"]
LEAGUE_NAME = match["name"]
COUNTRY     = match["country"]
LEAGUE_KEY  = f"{COUNTRY.lower()}_{LEAGUE_ID}"
LEAGUE_SLUG = re.sub(r'[^a-z0-9]+', '-', LEAGUE_NAME.lower()).strip('-')

SEASON_SLUG = SEASON.replace("/", "_")
SEASON_URL  = SEASON.replace("/", "-")
SEASON_ENC  = SEASON.replace("/", "%2F")

OUT_DIR  = Path("fixtures_tiredness")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE_URL = f"https://www.fotmob.com/leagues/{LEAGUE_ID}/overview/{LEAGUE_SLUG}?season={SEASON_URL}"
API_URL  = f"https://www.fotmob.com/api/data/leagues?id={LEAGUE_ID}&ccode3={CCODE}&season={SEASON_ENC}"

print(f"League:  {LEAGUE_NAME} (id={LEAGUE_ID}, key={LEAGUE_KEY}, slug={LEAGUE_SLUG})")
print(f"Season:  {SEASON}")
print(f"Country: {COUNTRY}")

# ─── Step 1: Playwright intercepts token ──────────────────────────────────────

captured = {}

def intercept_token():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        def handle_request(request):
            if f"api/data/leagues?id={LEAGUE_ID}" in request.url and "season=" in request.url:
                h = request.headers
                if "x-mas" in h and not captured.get("x-mas"):
                    print("✓ Intercepted x-mas token")
                    captured["x-mas"]      = h["x-mas"]
                    captured["cookie"]     = h.get("cookie", "")
                    captured["user-agent"] = h.get("user-agent", "")

        page.on("request", handle_request)
        print(f"Navigating to {PAGE_URL} ...")
        page.goto(PAGE_URL, wait_until="networkidle", timeout=30000)
        browser.close()

    if not captured.get("x-mas"):
        print("✗ Failed to capture x-mas token")
        sys.exit(1)

intercept_token()

# ─── Step 2: Fetch fixtures ───────────────────────────────────────────────────

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

print("Fetching fixtures from API ...")
r = requests.get(API_URL, headers=headers, timeout=15)

if r.status_code != 200:
    print(f"✗ API returned HTTP {r.status_code}")
    sys.exit(1)

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
        "league_name":      LEAGUE_NAME,
        "country":          COUNTRY,
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

next_cmd = f'python scrape_match_details.py {LEAGUE_KEY}_{SEASON_SLUG}_fixtures.json raw_json/{LEAGUE_KEY}_{SEASON_SLUG} "{LEAGUE_NAME}"'
print(f"\nNext step — scrape match details:")
print(f"  {next_cmd}")

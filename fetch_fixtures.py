"""
Fetch fixture list for a given league and season using Playwright to intercept
the x-mas token, then immediately hit the FotMob API.

Looks up league metadata from master_leagues.json automatically.

Usage (unchanged):
    python fetch_fixtures.py <league_name> <season>

Example:
    python fetch_fixtures.py LaLiga "2023/2024"
    python fetch_fixtures.py "Premier League" "2022/2023"

Can also be imported and called directly:
    from fetch_fixtures import fetch_fixtures
    out_path = fetch_fixtures("LaLiga", "2023/2024")
"""

import json
import sys
import re
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

CCODE = "USA_NY"


def fetch_fixtures(league_name: str, season: str) -> Path:
    """
    Fetch the fixture list for (league_name, season) from FotMob and save it
    to fixtures_tiredness/<league_key>_<season_slug>_fixtures.json.

    Returns the Path to the saved file.
    Raises RuntimeError / SystemExit-equivalent exceptions on failure so callers
    (like run_pipeline.py) can catch and continue past a bad pair.
    """
    # ─── Lookup league from master_leagues.json ───────────────────────────────
    # Supports two input forms:
    #   "LaLiga"                 - plain name lookup (fine when the name is unique)
    #   "Serie A (BRA)"          - name + country code, required when the name collides
    #                              across countries (e.g. "Premier League", "Serie A")
    master_leagues = Path("master_leagues.json")
    if not master_leagues.exists():
        raise FileNotFoundError("master_leagues.json not found in current directory")

    with open(master_leagues) as f:
        leagues = json.load(f)

    country_hint = None
    name_query = league_name
    if "(" in league_name and league_name.endswith(")"):
        name_query, country_part = league_name.rsplit("(", 1)
        name_query = name_query.strip()
        country_hint = country_part.rstrip(")").strip().upper()

    candidates = [l for l in leagues if l["name"].lower() == name_query.lower()]

    if country_hint:
        candidates = [l for l in candidates if l["country"].upper() == country_hint]

    if not candidates:
        available = ", ".join(l["name"] for l in leagues)
        raise ValueError(f"League '{league_name}' not found in master_leagues.json. Available: {available}")

    if len(candidates) > 1:
        options = ", ".join(f"{l['name']} ({l['country']})" for l in candidates)
        raise ValueError(
            f"'{league_name}' is ambiguous - matches multiple countries: {options}. "
            f"Specify the country, e.g. \"{candidates[0]['name']} ({candidates[0]['country']})\"."
        )

    match = candidates[0]

    league_id   = match["id"]
    league_name = match["name"]
    country     = match["country"]
    league_key  = f"{country.lower()}_{league_id}"
    league_slug = re.sub(r'[^a-z0-9]+', '-', league_name.lower()).strip('-')

    season_slug = season.replace("/", "_")
    season_url  = season.replace("/", "-")
    season_enc  = season.replace("/", "%2F")

    out_dir = Path("fixtures_tiredness")
    out_dir.mkdir(parents=True, exist_ok=True)

    page_url = f"https://www.fotmob.com/leagues/{league_id}/overview/{league_slug}?season={season_url}"
    api_url  = f"https://www.fotmob.com/api/data/leagues?id={league_id}&ccode3={CCODE}&season={season_enc}"

    print(f"League:  {league_name} (id={league_id}, key={league_key}, slug={league_slug})")
    print(f"Season:  {season}")
    print(f"Country: {country}")

    # ─── Step 1: Playwright intercepts token ──────────────────────────────────
    captured = {}

    def handle_request(request):
        if f"api/data/leagues?id={league_id}" in request.url and "season=" in request.url:
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
        print(f"Navigating to {page_url} ...")
        page.goto(page_url, wait_until="networkidle", timeout=30000)
        browser.close()

    if not captured.get("x-mas"):
        raise RuntimeError("Failed to capture x-mas token")

    # ─── Step 2: Fetch fixtures ────────────────────────────────────────────────
    headers = {
        "accept":             "*/*",
        "accept-language":    "en-US,en;q=0.9",
        "user-agent":         captured["user-agent"],
        "cookie":             captured["cookie"],
        "x-mas":              captured["x-mas"],
        "referer":            page_url,
        "sec-ch-ua":          '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest":     "empty",
        "sec-fetch-mode":     "cors",
        "sec-fetch-site":     "same-origin",
    }

    print("Fetching fixtures from API ...")
    r = requests.get(api_url, headers=headers, timeout=15)

    if r.status_code != 200:
        raise RuntimeError(f"API returned HTTP {r.status_code}")

    data        = r.json()
    sel_season  = data.get("details", {}).get("selectedSeason", "")
    all_matches = data.get("fixtures", {}).get("allMatches", [])
    finished    = [m for m in all_matches if m["status"].get("finished")]
    upcoming    = [m for m in all_matches if not m["status"].get("finished")]

    if sel_season != season:
        print(f"⚠️  Season mismatch: requested '{season}' but got '{sel_season}'")
    else:
        print(f"✓ Season confirmed: {sel_season}")

    print(f"✓ {len(finished)} finished | {len(upcoming)} upcoming")

    output = {
        "meta": {
            "league_key":       league_key,
            "league_id":        league_id,
            "league_name":      league_name,
            "country":          country,
            "requested_season": season,
            "selected_season":  sel_season,
            "finished_count":   len(finished),
            "upcoming_count":   len(upcoming),
        },
        "data": data
    }

    out_path = out_dir / f"{league_key}_{season_slug}_fixtures.json"
    with open(out_path, "w") as f:
        json.dump(output, f)

    print(f"✓ Saved to {out_path}")

    next_cmd = f'python scrape_match_details.py {out_path.name} raw_json/{league_key}_{season_slug} "{league_name}"'
    print(f"\nNext step — scrape match details:")
    print(f"  {next_cmd}")

    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Usage: python fetch_fixtures.py <league_name> <season>')
        print('Example: python fetch_fixtures.py LaLiga "2023/2024"')
        sys.exit(1)

    try:
        fetch_fixtures(sys.argv[1], sys.argv[2])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)

"""
Run the full fetch_fixtures + scrape_match_details pipeline across every
(league, season) pair in a config file, updating progress_tracker.json as it goes.

Usage:
    python run_pipeline.py                          # uses pipeline_config.json
    python run_pipeline.py --config myconfig.json
    python run_pipeline.py --force                  # re-run pairs already marked complete
    python run_pipeline.py --pair-delay 20           # seconds to wait between pairs (default 15)

Config file shape (pipeline_config.json) — per-league season lists, NOT a cross-product.
This matters because different leagues use different season formats: cross-year leagues
(most of Europe) use "2022/2023", calendar-year leagues (Brazil, MLS, etc.) use "2022".
A single global "seasons" list applied to every league would be wrong for at least one of them.

{
  "pairs": [
    {"league": "Premier League", "seasons": ["2022/2023", "2023/2024", "2024/2025"]},
    {"league": "LaLiga",         "seasons": ["2022/2023", "2023/2024", "2024/2025"]},
    {"league": "Brazil Serie A", "seasons": ["2022", "2023", "2024", "2025"]}
  ]
}

Tip: use build_pipeline_config.py to generate the "pairs" list automatically from
league_season_calendars.json instead of typing season strings by hand:
    python build_pipeline_config.py "Premier League" "LaLiga" "Brazil Serie A" --through 2025
"""

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

from fetch_fixtures import fetch_fixtures
from scrape_match_details import scrape_match_details

MASTER_LEAGUES_PATH  = Path("master_leagues.json")
PROGRESS_TRACKER_PATH = Path("progress_tracker.json")
DEFAULT_CONFIG_PATH  = Path("pipeline_config.json")
DEFAULT_PAIR_DELAY   = 15  # seconds between (league, season) pairs


def load_master_leagues() -> list:
    if not MASTER_LEAGUES_PATH.exists():
        print(f"✗ {MASTER_LEAGUES_PATH} not found")
        sys.exit(1)
    with open(MASTER_LEAGUES_PATH) as f:
        return json.load(f)


def league_lookup(leagues: list, league_name: str) -> dict:
    """
    Same "Name" or "Name (CCODE)" lookup as fetch_fixtures.py, kept in sync so the
    tracker key (country_leagueid) always matches the league fetch_fixtures actually hit.
    """
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
        raise ValueError(f"League '{league_name}' not found in master_leagues.json")
    if len(candidates) > 1:
        options = ", ".join(f"{l['name']} ({l['country']})" for l in candidates)
        raise ValueError(f"'{league_name}' is ambiguous - matches: {options}. Specify the country.")
    return candidates[0]


def load_tracker() -> dict:
    if PROGRESS_TRACKER_PATH.exists():
        with open(PROGRESS_TRACKER_PATH) as f:
            return json.load(f)
    return {}


def save_tracker(tracker: dict):
    with open(PROGRESS_TRACKER_PATH, "w") as f:
        json.dump(tracker, f, indent=2)


def get_pair_state(tracker: dict, league_key: str, season: str) -> dict:
    return tracker.get(league_key, {}).get("seasons", {}).get(season, {})


def update_tracker(tracker: dict, league_entry: dict, season: str, updates: dict, updated_by: str = "run_pipeline.py"):
    league_key = f"{league_entry['country'].lower()}_{league_entry['id']}"
    league_node = tracker.setdefault(league_key, {
        "league_name": league_entry["name"],
        "league_id":   league_entry["id"],
        "country":     league_entry["country"],
        "seasons":     {}
    })
    season_node = league_node["seasons"].setdefault(season, {
        "fixtures_fetched": False,
        "match_details":    {"status": "not_started", "success": None, "failed": None, "skipped": None, "related_competition": None},
        "parsed_to_stats":  False,
        "last_updated":     None,
        "updated_by":       None,
        "notes":            ""
    })
    season_node.update(updates)
    season_node["last_updated"] = time.strftime("%Y-%m-%d")
    season_node["updated_by"]   = updated_by
    save_tracker(tracker)


def season_slug(season: str) -> str:
    return season.replace("/", "_")


def run_pair(league_name: str, season: str, leagues: list, tracker: dict, force: bool) -> dict:
    """Returns a summary dict for the final report table."""
    league_entry = league_lookup(leagues, league_name)
    league_key   = f"{league_entry['country'].lower()}_{league_entry['id']}"
    slug         = season_slug(season)

    state = get_pair_state(tracker, league_key, season)
    already_done = (
        state.get("fixtures_fetched")
        and state.get("match_details", {}).get("status") == "complete"
    )
    if already_done and not force:
        print(f"⏭  {league_name} {season} — already complete, skipping (use --force to re-run)")
        return {"league": league_name, "season": season, "fixtures": "skipped (already done)",
                "success": state["match_details"].get("success"),
                "related_competition": state["match_details"].get("related_competition"),
                "failed": state["match_details"].get("failed"),
                "skipped": state["match_details"].get("skipped")}

    # ── Fixtures ────────────────────────────────────────────────────────────
    fixtures_file_name = f"{league_key}_{slug}_fixtures.json"
    fixtures_path = Path("fixtures_tiredness") / fixtures_file_name

    if fixtures_path.exists() and not force:
        print(f"⏭  Fixtures already fetched for {league_name} {season}, skipping fetch step")
        fixtures_status = "skipped (file exists)"
    else:
        fetch_fixtures(league_name, season)
        fixtures_status = "fetched"

    update_tracker(tracker, league_entry, season, {"fixtures_fetched": True})

    # ── Match details ───────────────────────────────────────────────────────
    update_tracker(tracker, league_entry, season, {
        "match_details": {"status": "in_progress", "success": None, "failed": None, "skipped": None, "related_competition": None}
    })

    output_dir = f"raw_json/{league_key}_{slug}"
    result = scrape_match_details(fixtures_file_name, output_dir, league_entry["name"], league_entry["id"])

    update_tracker(tracker, league_entry, season, {
        "match_details": {
            "status":  "complete",
            "success": result["success"],
            "failed":  result["failed"],
            "skipped": result["skipped"],
            "related_competition": result["related_competition"],
        }
    })

    return {"league": league_name, "season": season, "fixtures": fixtures_status,
            "success": result["success"], "failed": result["failed"], "skipped": result["skipped"], "related_competition": result["related_competition"]}


def main():
    parser = argparse.ArgumentParser(description="Run fetch_fixtures + scrape_match_details across a league/season grid.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config JSON (default: pipeline_config.json)")
    parser.add_argument("--force", action="store_true", help="Re-run pairs even if the tracker marks them complete")
    parser.add_argument("--pair-delay", type=float, default=DEFAULT_PAIR_DELAY, help="Seconds to wait between league/season pairs")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"✗ Config file not found: {config_path}")
        print(f"  Copy pipeline_config.example.json to {config_path} and edit it.")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    if "pairs" not in config:
        print("✗ Config file uses the old {\"leagues\": [...], \"seasons\": [...]} cross-product format.")
        print("  That format assumes every league uses the same season strings, which breaks for")
        print("  calendar-year leagues (e.g. Brazil uses \"2022\", not \"2022/2023\").")
        print("  Use the new {\"pairs\": [{\"league\": ..., \"seasons\": [...]}]} format instead —")
        print("  see build_pipeline_config.py to generate it automatically.")
        sys.exit(1)

    pairs = [(entry["league"], season) for entry in config["pairs"] for season in entry["seasons"]]

    all_leagues = load_master_leagues()
    tracker = load_tracker()

    print(f"Running pipeline for {len(pairs)} (league, season) pairs:")
    for l, s in pairs:
        print(f"  - {l} {s}")
    print()

    results = []
    for idx, (league_name, season) in enumerate(pairs):
        print(f"\n{'='*70}")
        print(f"[{idx+1}/{len(pairs)}] {league_name} — {season}")
        print(f"{'='*70}\n")
        try:
            summary = run_pair(league_name, season, all_leagues, tracker, args.force)
            results.append(summary)
        except Exception as e:
            print(f"✗ Failed on {league_name} {season}: {e}")
            traceback.print_exc()
            results.append({"league": league_name, "season": season, "fixtures": "ERROR",
                             "success": None, "failed": None, "skipped": None, "related_competition": None, "error": str(e)})

        # Inter-pair delay, skip after the very last pair
        if idx < len(pairs) - 1:
            print(f"\nWaiting {args.pair_delay}s before next pair ...")
            time.sleep(args.pair_delay)

    # ── Final summary table ─────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'League':<20} {'Season':<12} {'Fixtures':<24} {'Success':<8} {'Failed':<8} {'Skipped':<8} {'Related':<8}")
    print("-" * 98)
    for r in results:
        print(f"{r['league']:<20} {r['season']:<12} {str(r['fixtures']):<24} "
              f"{str(r.get('success','')):<8} {str(r.get('failed','')):<8} {str(r.get('skipped','')):<8} {str(r.get('related_competition','')):<8}")


if __name__ == "__main__":
    main()

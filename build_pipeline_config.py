"""
Helper: generate a pipeline_config.json's "pairs" list from league_season_calendars.json,
walking each league forward from its target_start_season to a given end point.

Usage:
    python build_pipeline_config.py "Premier League" "LaLiga" "Brazil Serie A" --through 2025
"""
import json
import sys
import argparse
from collections import Counter

def _load_ambiguous_names(calendars_path="league_season_calendars.json"):
    try:
        cal = json.load(open(calendars_path))
    except FileNotFoundError:
        return set()
    counts = Counter(v["name"].lower() for v in cal.values())
    return {name for name, c in counts.items() if c > 1}

AMBIGUOUS_NAMES = _load_ambiguous_names()

def next_cross_year(season: str) -> str:
    start, end = season.split("/")
    return f"{int(start)+1}/{int(end)+1}"

def next_calendar_year(season: str) -> str:
    return str(int(season) + 1)

def seasons_forward(start_season: str, season_type: str, through_year: int) -> list:
    seasons = [start_season]
    current = start_season
    while True:
        end_year = int(current.split("/")[-1]) if season_type == "cross_year" else int(current)
        if end_year >= through_year:
            break
        current = next_cross_year(current) if season_type == "cross_year" else next_calendar_year(current)
        seasons.append(current)
    return seasons

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("league_names", nargs="+")
    parser.add_argument("--through", type=int, default=2025, help="Last year to include (default 2025)")
    parser.add_argument("--calendars", default="league_season_calendars.json")
    parser.add_argument("--out", default="pipeline_config.json")
    args = parser.parse_args()

    calendars = json.load(open(args.calendars))

    def resolve(name_input):
        # Accept "Name" or "Name (CCODE)"
        country_hint = None
        name_query = name_input
        if "(" in name_input and name_input.endswith(")"):
            name_query, country_part = name_input.rsplit("(", 1)
            name_query = name_query.strip()
            country_hint = country_part.rstrip(")").strip().upper()

        candidates = [v for v in calendars.values() if v["name"].lower() == name_query.lower()]
        if country_hint:
            candidates = [c for c in candidates if c["country"].upper() == country_hint]
        return candidates

    pairs = []
    for name in args.league_names:
        candidates = resolve(name)
        if not candidates:
            print(f"⚠️  '{name}' not found in {args.calendars} - skipping")
            continue
        if len(candidates) > 1:
            options = ", ".join(f"{c['name']} ({c['country']})" for c in candidates)
            print(f"⚠️  '{name}' is ambiguous - matches: {options}. Use e.g. \"{candidates[0]['name']} ({candidates[0]['country']})\" - skipping")
            continue
        entry = candidates[0]
        seasons = seasons_forward(entry["target_start_season"], entry["season_type"], args.through)
        league_key = f"{entry['name']} ({entry['country']})" if entry["name"].lower() in AMBIGUOUS_NAMES else entry["name"]
        pairs.append({"league": league_key, "seasons": seasons})
        conf_flag = f" [{entry['confidence']} confidence]" if entry["confidence"] != "high" else ""
        print(f"{league_key}: {seasons}{conf_flag}")

    config = {"pairs": pairs}
    with open(args.out, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\nWrote {args.out}")

if __name__ == "__main__":
    main()

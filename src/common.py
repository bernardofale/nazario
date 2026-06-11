"""Shared paths and helpers for the Phase 0 data pipeline."""
import csv
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
GAME = RAW / "game"
CURATED = ROOT / "data" / "curated"
PROCESSED = ROOT / "data" / "processed"

# columns of the common match schema — every results source maps to this
MATCH_COLUMNS = [
    "source", "competition", "confederation", "season", "match_id", "date",
    "stage", "group", "matchday", "home_team", "away_team", "home_code",
    "away_code", "home_score", "away_score", "ht_home_score", "ht_away_score",
    "extra_time", "penalty_shootout", "home_penalty_score",
    "away_penalty_score", "venue",
]

GOAL_COLUMNS = [
    "source", "match_id", "date", "team", "team_code", "player",
    "player_id", "minute", "penalty", "own_goal",
]


def norm_name(s):
    """Normalize a player/team name for matching: lowercase, strip accents,
    collapse hyphens/whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return " ".join(s.replace("-", " ").replace("'", "").split())


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in columns})


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

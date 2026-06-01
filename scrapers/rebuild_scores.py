"""Regenerate scores.json and rollups.json from the source-of-truth logs.

Scores are *derived* data: a pure function of forecasts + decisions. This
command rebuilds them from scratch (not append-only — they're recomputed,
never accumulated), validates, and writes. Run it after every scrape.

    python -m scrapers.rebuild_scores
    python -m scrapers.rebuild_scores --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .scorer import build_rollups, score_all
from .validate import validate_records

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> list[dict]:
    path = DATA_DIR / name
    return json.loads(path.read_text()) if path.exists() else []


def rebuild(today: date | None = None, dry_run: bool = False) -> int:
    forecasts = _load("forecasts.json")
    decisions = _load("decisions.json")
    forecasters = _load("forecasters.json")

    scores = score_all(forecasts, decisions, today=today)
    rollups = build_rollups(forecasters, forecasts, decisions, scores, today=today)

    validate_records(scores, "score.schema.json")
    validate_records(rollups, "forecaster_rollup.schema.json")

    resolved = sum(1 for s in scores if s["status"] == "resolved")
    print(f"scored {len(scores)} forecast(s): {resolved} resolved, "
          f"{len(scores) - resolved} pending/in-progress")
    print(f"rolled up {len(rollups)} forecaster(s)")

    if dry_run:
        print("(dry-run, nothing written)")
        return 0

    (DATA_DIR / "scores.json").write_text(json.dumps(scores, indent=2) + "\n")
    (DATA_DIR / "rollups.json").write_text(json.dumps(rollups, indent=2) + "\n")
    print("wrote data/scores.json, data/rollups.json")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Recompute scores + rollups")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return rebuild(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

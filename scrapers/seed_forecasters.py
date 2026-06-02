"""Seed the forecaster registry with major banks, research houses, surveys and
named economists who publish formal rate / inflation / unemployment forecasts.

Append-only by id (never overwrites an existing forecaster, so re-running is
safe and won't clobber provenance discovered by the live scrapers). Validates
the full merged set before writing.

    python -m scrapers.seed_forecasters
    python -m scrapers.seed_forecasters --dry-run

The list is compiled from public research on which institutions publish
timestamped, attributable point forecasts for US (Fed funds, CPI, unemployment)
and AU (RBA cash rate, CPI, unemployment). These identities let the next
backfill attribute scraped forecasts to a known forecaster.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .validate import validate_records

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FORECASTERS = DATA_DIR / "forecasters.json"

# (id, name, type, affiliation, country_focus, source_url, source_name)
SEED = [
    # ---- US investment banks ----
    ("jpmorgan", "JPMorgan", "bank", None, ["US"],
     "https://www.jpmorgan.com/insights/global-research/economy/", "JPMorgan Global Research"),
    ("bank_of_america", "Bank of America", "bank", None, ["US"],
     "https://business.bofa.com/en-us/content/economic-insights.html", "BofA Global Research"),
    ("citigroup", "Citigroup", "bank", None, ["US"],
     "https://www.citigroup.com/global/insights", "Citi Global Insights"),
    ("morgan_stanley", "Morgan Stanley", "bank", None, ["US"],
     "https://www.morganstanley.com/im/en-us/individual-investor/insights.html", "Morgan Stanley Research"),

    # ---- US research houses ----
    ("pantheon_macro", "Pantheon Macroeconomics", "research", None, ["US"],
     "https://www.pantheonmacro.com/", "Pantheon Macroeconomics"),
    ("capital_economics", "Capital Economics", "research", None, ["US", "AU"],
     "https://www.capitaleconomics.com/", "Capital Economics"),
    ("oxford_economics", "Oxford Economics", "research", None, ["US", "AU"],
     "https://www.oxfordeconomics.com/", "Oxford Economics"),

    # ---- US central bank + surveys ----
    ("fomc", "FOMC (Fed projections)", "central_bank", None, ["US"],
     "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "Federal Reserve"),
    ("spf_philly_fed", "Survey of Professional Forecasters", "survey", None, ["US"],
     "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/survey-of-professional-forecasters",
     "Federal Reserve Bank of Philadelphia"),
    ("blue_chip_indicators", "Blue Chip Economic Indicators", "survey", None, ["US"],
     "https://www.wolterskluwer.com/en/solutions/blue-chip", "Wolters Kluwer"),

    # ---- US named economists ----
    ("samuel_tombs", "Samuel Tombs", "individual", "Pantheon Macroeconomics", ["US"],
     "https://www.pantheonmacro.com/", "Pantheon Macroeconomics"),

    # ---- Australian banks ----
    ("cba", "Commonwealth Bank", "bank", None, ["AU"],
     "https://www.commbank.com.au/articles/newsroom.html", "CBA Newsroom"),
    ("nab", "NAB", "bank", None, ["AU"],
     "https://business.nab.com.au/category/economy/", "NAB Economics"),
    ("anz", "ANZ", "bank", None, ["AU"],
     "https://www.anz.com.au/about-us/economy-markets/", "ANZ Research"),
    ("macquarie", "Macquarie", "bank", None, ["AU"],
     "https://www.macquarie.com/au/en/insights.html", "Macquarie"),

    # ---- AU central bank + economist ----
    ("rba_smp", "RBA (SMP projections)", "central_bank", None, ["AU"],
     "https://www.rba.gov.au/publications/smp/", "Reserve Bank of Australia"),
    ("saul_eslake", "Saul Eslake", "individual", "Corinna Economic Advisory", ["AU"],
     "https://www.corinna.com.au/", "Corinna Economic Advisory"),
]


def _content_hash(seed_id: str) -> str:
    return "sha256:" + hashlib.sha256(("seed:" + seed_id).encode()).hexdigest()


def _record(entry) -> dict:
    seed_id, name, ftype, affiliation, country_focus, source_url, source_name = entry
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": seed_id,
        "name": name,
        "type": ftype,
        "affiliation": affiliation,
        "country_focus": country_focus,
        "first_seen": None,
        "provenance": {
            "source_url": source_url,
            "source_name": source_name,
            "scraped_at": now,
            "ingest_method": "manual_url",
            "parser": "seed_forecasters.py",
            "parser_version": "0.1.0",
            "content_hash": _content_hash(seed_id),
        },
    }


def seed(dry_run: bool = False) -> int:
    existing = json.loads(FORECASTERS.read_text()) if FORECASTERS.exists() else []
    by_id = {f["id"]: f for f in existing}

    added = 0
    for entry in SEED:
        rec = _record(entry)
        if rec["id"] not in by_id:        # append-only — never overwrite
            by_id[rec["id"]] = rec
            added += 1

    merged = sorted(by_id.values(), key=lambda f: f["id"])
    validate_records(merged, "forecaster.schema.json")

    print(f"seed: {len(SEED)} known forecasters, {added} new, "
          f"{len(merged)} total")
    if dry_run:
        print("(dry-run, nothing written)")
        return 0
    FORECASTERS.write_text(json.dumps(merged, indent=2) + "\n")
    print(f"wrote {FORECASTERS.relative_to(DATA_DIR.parent)}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Seed the forecaster registry")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return seed(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

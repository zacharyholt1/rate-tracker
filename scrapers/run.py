"""Scraper orchestrator.

Runs the scheduled scrapers, validates everything, and merges new records into
data/ append-only (existing ids are never overwritten — git is the audit log,
and immutability is what keeps the leaderboard honest).

Each source is isolated: a failure in one (network, parser, validation) is
logged and skipped, so a single bad source can't sink the whole cron run.

    python -m scrapers.run                 # run all sources, write data/
    python -m scrapers.run --dry-run       # parse + validate, write nothing
    python -m scrapers.run --only fred rba  # subset of sources
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import abs as abs_mod
from . import fed, fred, rba
from .fetch import FetchError, fetch_text
from .sources import SOURCES
from .validate import ValidationError, validate_records

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---- merge -----------------------------------------------------------------

def merge_into(filename: str, schema_file: str, new_records: list[dict]) -> int:
    """Merge new records into a data file, append-only by id. Returns count of
    records actually added. Validates the full merged set before writing."""
    path = DATA_DIR / filename
    existing = json.loads(path.read_text()) if path.exists() else []
    by_id = {r["id"]: r for r in existing}

    added = 0
    for rec in new_records:
        if rec["id"] not in by_id:      # never overwrite — append-only
            by_id[rec["id"]] = rec
            added += 1

    merged = sorted(by_id.values(), key=lambda r: r["id"])
    validate_records(merged, schema_file)   # gate before write
    path.write_text(json.dumps(merged, indent=2) + "\n")
    return added


# ---- per-source collection (network-dependent) -----------------------------

def collect_fred() -> list[dict]:
    cfg = SOURCES["fred"]
    records = []
    for key, series_id in cfg["series"].items():
        url = f"{cfg['base_url']}?id={series_id}"
        csv_text = fetch_text(url)
        records.extend(fred.build_records(key, series_id, csv_text))
    return records


def collect_rba() -> list[dict]:
    index_html = fetch_text(SOURCES["rba"]["index_url"])
    records = []
    for href in rba.parse_index(index_html):
        url = "https://www.rba.gov.au" + href
        html = fetch_text(url)
        # meeting date isn't in the URL slug; parse it from the page in a real
        # run. Here we defer that to the page parser when wiring live HTML.
        meeting_date = _guess_date_from_release(html)
        if not meeting_date:
            continue
        rec = rba.parse_decision(html, url=url, meeting_date=meeting_date)
        if rec:
            records.append(rec)
    return records


def collect_fed() -> list[dict]:
    index_html = fetch_text(SOURCES["fed"]["index_url"])
    records = []
    for href in fed.parse_index(index_html):
        url = "https://www.federalreserve.gov" + href
        # The 8-digit date is embedded in the release filename.
        import re
        m = re.search(r"monetary(\d{4})(\d{2})(\d{2})", href)
        if not m:
            continue
        meeting_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        html = fetch_text(url)
        rec = fed.parse_decision(html, url=url, meeting_date=meeting_date)
        if rec:
            records.append(rec)
    return records


def _guess_date_from_release(html: str) -> str | None:
    """Best-effort extraction of an ISO date from an RBA release page."""
    import re
    text = abs_mod.extract_text(html)
    months = ("January February March April May June July August September "
              "October November December").split()
    m = re.search(r"(\d{1,2})\s+(" + "|".join(months) + r")\s+(\d{4})", text)
    if not m:
        return None
    day = int(m.group(1))
    mon = months.index(m.group(2)) + 1
    return f"{m.group(3)}-{mon:02d}-{day:02d}"


# ---- driver ----------------------------------------------------------------

# (collector, target data file, schema)
PIPELINE = {
    "fred": (collect_fred, "indicators.json", "indicator.schema.json"),
    "abs":  (None,         "indicators.json", "indicator.schema.json"),  # see note
    "rba":  (collect_rba,  "decisions.json",  "decision.schema.json"),
    "fed":  (collect_fed,  "decisions.json",  "decision.schema.json"),
}


def run(only: list[str] | None, dry_run: bool) -> int:
    sources = only or [s for s in PIPELINE if PIPELINE[s][0] is not None]
    failures = 0

    for name in sources:
        collector, filename, schema = PIPELINE.get(name, (None, None, None))
        if collector is None:
            print(f"skip  {name}: no collector wired yet")
            continue
        try:
            records = collector()
            validate_records(records, schema)   # validate before merge
            if dry_run:
                print(f"ok    {name}: parsed {len(records)} record(s) (dry-run)")
            else:
                added = merge_into(filename, schema, records)
                print(f"ok    {name}: {len(records)} parsed, {added} new -> {filename}")
        except (FetchError, ValidationError) as exc:
            failures += 1
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # isolate any unexpected parser error
            failures += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")

    return 1 if failures else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run scrapers and merge into data/")
    ap.add_argument("--dry-run", action="store_true", help="parse + validate, write nothing")
    ap.add_argument("--only", nargs="+", metavar="SRC", help="subset of sources")
    args = ap.parse_args(argv)
    return run(args.only, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

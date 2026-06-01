"""Schema validation and provenance helpers.

This is the security gate: nothing reaches ``data/`` without passing through
here. Every data file is an array of records; each record is validated against
its schema (including the embedded provenance block).

Usage:
    python -m scrapers.validate data/        # validate every data file
    python -m scrapers.validate data/decisions.json

As a library:
    from scrapers.validate import validate_records, make_provenance, content_hash
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# --- schema registry -------------------------------------------------------

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

# Maps each data filename to the schema that validates its records.
DATA_FILE_SCHEMAS = {
    "decisions.json": "decision.schema.json",
    "indicators.json": "indicator.schema.json",
    "forecasters.json": "forecaster.schema.json",
    "forecasts.json": "forecast.schema.json",
    "scores.json": "score.schema.json",
    "rollups.json": "forecaster_rollup.schema.json",
}


def _load_registry() -> Registry:
    """Load every schema so cross-file ``$ref`` (e.g. provenance) resolves."""
    registry = Registry()
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )
    return registry


_REGISTRY = _load_registry()


def _validator_for(schema_file: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / schema_file).read_text())
    return Draft202012Validator(schema, registry=_REGISTRY)


# --- provenance helpers ----------------------------------------------------


def content_hash(raw: str | bytes) -> str:
    """sha256 of raw source content, prefixed for the schema pattern."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def make_provenance(
    *,
    source_url: str,
    source_name: str,
    raw_content: str | bytes,
    ingest_method: str = "scraper",
    parser: str | None = None,
    parser_version: str | None = None,
) -> dict:
    """Build a provenance block. Every scraper calls this so the audit trail
    is consistent and the content hash is always computed the same way."""
    prov = {
        "source_url": source_url,
        "source_name": source_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ingest_method": ingest_method,
        "content_hash": content_hash(raw_content),
    }
    if parser:
        prov["parser"] = parser
    if parser_version:
        prov["parser_version"] = parser_version
    return prov


# --- validation ------------------------------------------------------------


class ValidationError(Exception):
    """Raised when one or more records fail their schema."""


def validate_records(records: list[dict], schema_file: str) -> None:
    """Validate every record in a list. Raises ValidationError listing all
    failures (not just the first) so a bad scrape can be fixed in one pass."""
    validator = _validator_for(schema_file)
    problems: list[str] = []
    for i, record in enumerate(records):
        for err in validator.iter_errors(record):
            loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
            rec_id = record.get("id", f"index {i}") if isinstance(record, dict) else f"index {i}"
            problems.append(f"  [{rec_id}] {loc}: {err.message}")
    if problems:
        raise ValidationError(
            f"{len(problems)} validation error(s) in {schema_file}:\n"
            + "\n".join(problems)
        )


def validate_file(path: Path) -> int:
    """Validate one data file. Returns the record count."""
    schema_file = DATA_FILE_SCHEMAS.get(path.name)
    if schema_file is None:
        raise ValidationError(
            f"No schema mapped for {path.name}. "
            f"Known: {', '.join(sorted(DATA_FILE_SCHEMAS))}"
        )
    records = json.loads(path.read_text())
    if not isinstance(records, list):
        raise ValidationError(f"{path.name}: top level must be a JSON array.")
    validate_records(records, schema_file)
    return len(records)


def _main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    target = Path(argv[0])
    if target.is_dir():
        files = [target / name for name in DATA_FILE_SCHEMAS if (target / name).exists()]
    else:
        files = [target]

    if not files:
        print(f"No known data files found in {target}")
        return 1

    failed = False
    for path in files:
        try:
            count = validate_file(path)
            print(f"ok   {path}  ({count} records)")
        except ValidationError as exc:
            failed = True
            print(f"FAIL {path}\n{exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

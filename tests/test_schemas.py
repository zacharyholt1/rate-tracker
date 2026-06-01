"""Schema + validation tests.

Proves (a) the committed mock data validates, (b) the validator actually
rejects bad records — including the security-relevant rules (non-https
source URLs, malformed content hashes), and (c) provenance helpers behave.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scrapers.validate import (
    DATA_FILE_SCHEMAS,
    ValidationError,
    content_hash,
    make_provenance,
    validate_file,
    validate_records,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.mark.parametrize("filename", sorted(DATA_FILE_SCHEMAS))
def test_committed_data_validates(filename):
    path = DATA_DIR / filename
    assert path.exists(), f"missing data file {filename}"
    count = validate_file(path)
    assert count > 0


def test_content_hash_format():
    h = content_hash("hello")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_make_provenance_roundtrips_through_schema():
    prov = make_provenance(
        source_url="https://www.rba.gov.au/x",
        source_name="RBA",
        raw_content="<html>...</html>",
        parser="rba.py",
        parser_version="0.1.0",
    )
    # Embed in a minimal valid decision and validate the whole thing.
    record = {
        "id": "RBA_2025-05-20",
        "bank": "RBA",
        "country": "AU",
        "meeting_date": "2025-05-20",
        "decision": "cut",
        "rate_after": 3.85,
        "provenance": prov,
    }
    validate_records([record], "decision.schema.json")


def _valid_decision():
    return copy.deepcopy(json.loads((DATA_DIR / "decisions.json").read_text())[0])


def test_rejects_non_https_source_url():
    bad = _valid_decision()
    bad["provenance"]["source_url"] = "http://insecure.example/x"
    with pytest.raises(ValidationError):
        validate_records([bad], "decision.schema.json")


def test_rejects_malformed_content_hash():
    bad = _valid_decision()
    bad["provenance"]["content_hash"] = "not-a-hash"
    with pytest.raises(ValidationError):
        validate_records([bad], "decision.schema.json")


def test_rejects_unknown_decision_direction():
    bad = _valid_decision()
    bad["decision"] = "yolo"
    with pytest.raises(ValidationError):
        validate_records([bad], "decision.schema.json")


def test_rejects_extra_properties():
    bad = _valid_decision()
    bad["surprise"] = "injection"
    with pytest.raises(ValidationError):
        validate_records([bad], "decision.schema.json")


def test_forecast_oneof_rejects_mixed_prediction():
    forecasts = json.loads((DATA_DIR / "forecasts.json").read_text())
    point = next(f for f in forecasts if f["forecast_type"] == "point")
    bad = copy.deepcopy(point)
    # Mix point + path fields — oneOf must reject ambiguity.
    bad["prediction"]["horizon_start"] = "2025-01-01"
    with pytest.raises(ValidationError):
        validate_records([bad], "forecast.schema.json")

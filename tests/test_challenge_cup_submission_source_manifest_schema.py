from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "challenge_cup_submission_source_manifest.schema.json"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "challenge_cup"


def _issues(name: str) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return [error.message for error in Draft202012Validator(schema).iter_errors(value)]


def test_source_manifest_accepts_only_relative_tracked_paths_and_complete_hashes() -> None:
    assert _issues("source_manifest_valid.json") == []


@pytest.mark.parametrize(
    "fixture",
    [
        "source_manifest_invalid_absolute_path.json",
        "source_manifest_invalid_parent_path.json",
        "source_manifest_invalid_hash.json",
    ],
)
def test_source_manifest_rejects_unsafe_or_unverifiable_entries(fixture: str) -> None:
    assert _issues(fixture)

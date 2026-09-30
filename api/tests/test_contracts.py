"""Contract tests: shared fixtures must validate (or fail) against the JSON Schemas.

The SDK gets the same test in M1, reading the same fixtures and manifest.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMAS = ["shop-config", "event-envelope"]


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _validator(contracts: Path, name: str) -> Draft202012Validator:
    return Draft202012Validator(_load(contracts / f"{name}.schema.json"))


def _pointer(path: Any) -> str:
    return "".join(f"/{part}" for part in path)


def _all_error_paths(errors: Iterator[ValidationError]) -> set[str]:
    """Paths of every error, including those nested inside oneOf/anyOf contexts."""
    paths: set[str] = set()
    stack = list(errors)
    while stack:
        err = stack.pop()
        paths.add(_pointer(err.absolute_path))
        stack.extend(err.context or [])
    return paths


def _fixtures(contracts: Path, kind: str) -> list[Path]:
    return sorted((contracts / "fixtures" / kind).glob("*.json"))


def _schema_name(fixture: Path) -> str:
    name = fixture.name.split(".")[0]
    assert name in SCHEMAS, f"fixture {fixture.name} does not start with a known schema name"
    return name


@pytest.mark.parametrize("name", SCHEMAS)
def test_schema_is_a_valid_json_schema(contracts_dir: Path, name: str) -> None:
    Draft202012Validator.check_schema(_load(contracts_dir / f"{name}.schema.json"))


def test_every_schema_has_valid_and_invalid_fixtures(contracts_dir: Path) -> None:
    for kind in ("valid", "invalid"):
        seen = {_schema_name(f) for f in _fixtures(contracts_dir, kind)}
        assert seen == set(SCHEMAS), f"{kind} fixtures missing for {set(SCHEMAS) - seen}"


def test_valid_fixtures_validate(contracts_dir: Path) -> None:
    fixtures = _fixtures(contracts_dir, "valid")
    assert fixtures
    for fixture in fixtures:
        errors = list(_validator(contracts_dir, _schema_name(fixture)).iter_errors(_load(fixture)))
        assert not errors, f"{fixture.name}: {[e.message for e in errors]}"


def test_manifest_lists_exactly_the_invalid_fixtures(contracts_dir: Path) -> None:
    manifest = _load(contracts_dir / "fixtures" / "manifest.json")["invalid"]
    on_disk = {f.name for f in _fixtures(contracts_dir, "invalid")}
    assert set(manifest) == on_disk


def test_invalid_fixtures_fail_for_the_documented_reason(contracts_dir: Path) -> None:
    manifest = _load(contracts_dir / "fixtures" / "manifest.json")["invalid"]
    for fixture in _fixtures(contracts_dir, "invalid"):
        validator = _validator(contracts_dir, _schema_name(fixture))
        paths = _all_error_paths(validator.iter_errors(_load(fixture)))
        assert paths, f"{fixture.name} unexpectedly validates"
        expected = manifest[fixture.name]
        assert expected in paths, (
            f"{fixture.name}: expected an error at {expected!r}, got {sorted(paths)}"
        )

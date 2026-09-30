"""Pydantic models and JSON Schemas must agree on every shared fixture (spec 4, NOTES A14)."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from app.schemas import ConsentPing, Envelope, ShopConfig

MODELS: dict[str, type[BaseModel]] = {"shop-config": ShopConfig, "event-envelope": Envelope}


def fixtures(contracts: Path, kind: str) -> list[Path]:
    return sorted((contracts / "fixtures" / kind).glob("*.json"))


def model_for(path: Path) -> type[BaseModel]:
    return MODELS[path.name.split(".")[0]]


def schema_for(contracts: Path, path: Path) -> Draft202012Validator:
    name = path.name.split(".")[0]
    return Draft202012Validator(json.loads((contracts / f"{name}.schema.json").read_text()))


def test_every_valid_fixture_validates_in_pydantic(contracts_dir: Path) -> None:
    files = fixtures(contracts_dir, "valid")
    assert len(files) >= 6
    for f in files:
        model_for(f).model_validate(json.loads(f.read_text()))


def test_every_invalid_fixture_is_rejected_by_pydantic(contracts_dir: Path) -> None:
    files = fixtures(contracts_dir, "invalid")
    assert len(files) >= 20
    for f in files:
        with pytest.raises(ValidationError):
            model_for(f).model_validate(json.loads(f.read_text()))


def test_pydantic_and_json_schema_agree_on_every_fixture(contracts_dir: Path) -> None:
    for kind in ("valid", "invalid"):
        for f in fixtures(contracts_dir, kind):
            data = json.loads(f.read_text())
            schema_ok = not list(schema_for(contracts_dir, f).iter_errors(data))
            try:
                model_for(f).model_validate(data)
                pydantic_ok = True
            except ValidationError:
                pydantic_ok = False
            assert schema_ok == pydantic_ok == (kind == "valid"), f"{kind}/{f.name}"


def mutate(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(base))
    out.update(changes)
    return out


def test_pydantic_and_json_schema_agree_on_edge_cases(contracts_dir: Path) -> None:
    """Hand-made variants that the fixtures do not cover, in both directions."""
    base = json.loads(
        (
            contracts_dir / "fixtures" / "valid" / "event-envelope.rule-fired-and-summary.json"
        ).read_text()
    )
    validator = Draft202012Validator(
        json.loads((contracts_dir / "event-envelope.schema.json").read_text())
    )
    ev = base["events"]
    cases: list[dict[str, Any]] = [
        mutate(base, sent_at=1.5),
        mutate(base, sent_at=-1),
        mutate(base, sent_at="1"),
        mutate(base, session_id="short"),
        mutate(base, session_id="has space 12345"),
        mutate(base, shop_id=""),
        mutate(base, shop_id="x" * 65),
        mutate(base, visitor_hash="A" * 64),
        mutate(base, events=[]),
        mutate(base, events=ev * 40),
        mutate(base, extra=1),
        mutate(base, visitor_hash=None),
        {k: v for k, v in base.items() if k != "page_id"},
        {k: v for k, v in base.items() if k != "visitor_hash"},
    ]
    for c in cases:
        schema_ok = not list(validator.iter_errors(c))
        try:
            Envelope.model_validate(c)
            pydantic_ok = True
        except ValidationError:
            pydantic_ok = False
        assert schema_ok == pydantic_ok, c


def test_consent_ping_model() -> None:
    assert ConsentPing.model_validate({"shop_id": "s", "consented": True}).consented is True
    for bad in (
        {"shop_id": "s"},
        {"shop_id": "s", "consented": "true"},
        {"shop_id": "s", "consented": True, "x": 1},
    ):
        with pytest.raises(ValidationError):
            ConsentPing.model_validate(bad)

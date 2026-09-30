"""Pydantic models that conform to contracts/*.schema.json (spec 4).

tests/test_contracts_pydantic.py runs every shared fixture through both these models and the
JSON Schemas, so the two cannot drift apart silently.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

ID = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
ShopId = Annotated[StrictStr, Field(min_length=1, max_length=64)]
Country = Annotated[StrictStr, Field(pattern=r"^[A-Z]{2}$")]
NonEmpty = Annotated[StrictStr, Field(min_length=1)]
Number = StrictInt | StrictFloat
Scalar = StrictBool | StrictInt | StrictFloat | StrictStr | None
FrictionState = Literal["delivery_uncertainty", "returns_uncertainty", "sizing_uncertainty"]
SCHEMA_VERSION = "1.0"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# ---------------------------------------------------------------- event envelope


def _features(v: dict[str, Scalar]) -> dict[str, Scalar]:
    if len(v) > 40:
        raise ValueError("at most 40 features")
    return v


class PageView(Strict):
    type: Literal["page_view"]
    event_id: ID
    ts: Annotated[StrictInt, Field(ge=0)]
    page_type: Literal["product", "cart", "shipping_policy", "returns_policy", "other"]
    device: Literal["mobile", "tablet", "desktop"]
    product_id: StrictStr | None
    country: Country | None


class RuleFired(Strict):
    type: Literal["rule_fired"]
    event_id: ID
    ts: Annotated[StrictInt, Field(ge=0)]
    decision_id: ID
    friction_state: FrictionState
    rule_id: NonEmpty
    rule_version: NonEmpty
    fire_seq: Annotated[StrictInt, Field(ge=1)]
    arm: Literal["holdout", "treatment"]
    mode: Literal["shadow", "live"]
    play: StrictStr | None
    propensity: Annotated[Number, Field(gt=0, le=1)] | None
    content_ref: StrictStr | None
    has_content: StrictBool
    features: dict[StrictStr, Scalar]

    _f = field_validator("features")(_features)


class PageSummary(Strict):
    type: Literal["page_summary"]
    event_id: ID
    ts: Annotated[StrictInt, Field(ge=0)]
    features: dict[StrictStr, Scalar]
    eval_count: Annotated[StrictInt, Field(ge=0)]
    eval_p50_us: Annotated[Number, Field(ge=0)]
    eval_max_us: Annotated[Number, Field(ge=0)]

    _f = field_validator("features")(_features)


class Outcome(Strict):
    type: Literal["outcome"]
    event_id: ID
    ts: Annotated[StrictInt, Field(ge=0)]
    kind: Literal["add_to_cart", "checkout_started", "order_completed"]
    value: Annotated[Number, Field(ge=0)] | None
    source: Literal["sdk", "pixel", "webhook"]


Event = Annotated[PageView | RuleFired | PageSummary | Outcome, Field(discriminator="type")]


class Envelope(Strict):
    schema_version: Literal["1.0"]
    shop_id: ShopId
    visitor_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    session_id: ID
    page_id: ID | None = None
    sent_at: Annotated[StrictInt, Field(ge=0)]
    events: Annotated[list[Event], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _identity_for_sdk_events(self) -> Envelope:
        # Page-scoped events need the visitor and page; pixel outcomes carry only a session.
        if any(e.type in ("page_view", "rule_fired", "page_summary") for e in self.events) and (
            self.visitor_hash is None or self.page_id is None
        ):
            raise ValueError("visitor_hash and page_id are required with page events")
        return self


class ConsentPing(Strict):
    shop_id: ShopId
    consented: StrictBool


# ---------------------------------------------------------------- shop config


class Leaf(Strict):
    f: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    op: Literal["eq", "gte", "lte", "gt", "lt"]
    v: StrictBool | StrictInt | StrictFloat | StrictStr


class AllOf(Strict):
    all: Annotated[list[Condition], Field(min_length=1)]


class AnyOf(Strict):
    any: Annotated[list[Condition], Field(min_length=1)]


Condition = Leaf | AllOf | AnyOf
AllOf.model_rebuild()
AnyOf.model_rebuild()


def _unique(v: list[str]) -> list[str]:
    if len(set(v)) != len(v):
        raise ValueError("items must be unique")
    return v


class Rule(Strict):
    id: NonEmpty
    version: NonEmpty
    priority: Annotated[StrictInt, Field(ge=0)]
    friction_state: FrictionState
    pages: Annotated[list[Literal["product", "cart"]], Field(min_length=1)]
    when: Condition

    _u = field_validator("pages")(_unique)


class Selectors(Strict):
    shipping_block: NonEmpty
    returns_block: NonEmpty
    size_block: NonEmpty
    size_chart_trigger: NonEmpty
    variant_selector: NonEmpty
    add_to_cart_form: NonEmpty


class UrlPatterns(Strict):
    product: NonEmpty
    cart: NonEmpty
    shipping_policy: NonEmpty
    returns_policy: NonEmpty


class DeliveryContent(Strict):
    by_country: dict[StrictStr, NonEmpty] | None = None

    @field_validator("by_country")
    @classmethod
    def _countries(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None and any(not re.fullmatch(r"[A-Z]{2}", k) for k in v):
            raise ValueError("keys must be ISO-3166 alpha-2, uppercase")
        return v


class ReturnsContent(Strict):
    shop: NonEmpty | None = None


class SizingContent(Strict):
    product_ids: list[NonEmpty] | None = None

    @field_validator("product_ids")
    @classmethod
    def _ids_unique(cls, v: list[str] | None) -> list[str] | None:
        return v if v is None else _unique(v)


class Content(Strict):
    delivery_uncertainty: DeliveryContent | None = None
    returns_uncertainty: ReturnsContent | None = None
    sizing_uncertainty: SizingContent | None = None


class ShopConfig(Strict):
    schema_version: Literal["1.0"]
    shop_id: ShopId
    mode: Literal["shadow", "live"]
    kill_switch: StrictBool
    holdout_bps: Annotated[StrictInt, Field(ge=0, le=10000)]
    holdout_salt: NonEmpty
    log_endpoint: Annotated[StrictStr, Field(pattern=r"^https?://")]
    required_consent: Annotated[list[NonEmpty], Field(min_length=1)]
    consent_ping: StrictBool
    selectors: Selectors
    url_patterns: UrlPatterns
    rules: list[Rule]
    plays: dict[FrictionState, Annotated[list[NonEmpty], Field(min_length=1)]]
    content: Content

    _u = field_validator("required_consent")(_unique)

    @field_validator("plays")
    @classmethod
    def _plays_unique(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for items in v.values():
            _unique(items)
        return v


def dump(model: BaseModel) -> dict[str, Any]:
    """JSON-ready dict without unset optional fields, so output matches the schema."""
    return model.model_dump(mode="json", exclude_unset=True)

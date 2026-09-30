"""Table definitions for queries. Alembic (alembic/versions) is the only source of schema;
tests/test_schema.py fails if these and the migrated database disagree."""

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

shop = Table(
    "shop",
    metadata,
    Column("shop_id", Text, primary_key=True),
    Column("platform", Text, nullable=False),
    Column("allowed_origins", ARRAY(Text), nullable=False),
    Column("config", JSONB, nullable=False),
    Column("webhook_secret_ref", Text),
)

page_view = Table(
    "page_view",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("shop_id", Text, nullable=False),
    Column("visitor_hash", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("page_id", Text, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("page_type", Text, nullable=False),
    Column("device", Text, nullable=False),
    Column("product_id", Text),
    Column("country", Text),
)

decision_log = Table(
    "decision_log",
    metadata,
    Column("decision_id", Text, primary_key=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("shop_id", Text, nullable=False),
    Column("visitor_hash", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("page_id", Text, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("friction_state", Text, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("rule_version", Text, nullable=False),
    Column("fire_seq", Integer, nullable=False),
    Column("arm", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("play", Text),
    Column("propensity", Float),
    Column("content_ref", Text),
    Column("has_content", Boolean, nullable=False),
    Column("features", JSONB, nullable=False),
)

page_summary = Table(
    "page_summary",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("shop_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("page_id", Text, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("features", JSONB, nullable=False),
    Column("eval_count", Integer, nullable=False),
    Column("eval_p50_us", Float, nullable=False),
    Column("eval_max_us", Float, nullable=False),
)

outcome_event = Table(
    "outcome_event",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("shop_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("value", Numeric),
    Column("source", Text, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
)

consent_ping_daily = Table(
    "consent_ping_daily",
    metadata,
    Column("shop_id", Text, primary_key=True),
    Column("day", Date, primary_key=True),
    Column("consented", Boolean, primary_key=True),
    Column("count", Integer, nullable=False),
)

__all__ = [
    "consent_ping_daily",
    "decision_log",
    "metadata",
    "outcome_event",
    "page_summary",
    "page_view",
    "shop",
]

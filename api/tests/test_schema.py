"""The migrated database and app/models.py must agree; Alembic is the only source of schema."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import metadata
from tests.conftest import API_DIR, Db


def test_models_match_the_migrated_columns(db: Db) -> None:
    rows = db.rows(
        "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )
    actual: dict[str, dict[str, bool]] = {}
    for r in rows:
        actual.setdefault(r["table_name"], {})[r["column_name"]] = r["is_nullable"] == "YES"
    for name, table in metadata.tables.items():
        assert name in actual, f"table {name} is not in the migrated schema"
        declared = {c.name: bool(c.nullable) for c in table.columns}
        # server-side defaults mean received_at / platform etc. may be non-null in the DB
        assert set(declared) == set(actual[name]), name
        for col, nullable in declared.items():
            assert nullable == actual[name][col], f"{name}.{col} nullability differs"


def test_every_spec_table_and_the_view_exist(db: Db) -> None:
    names = {
        r["table_name"]
        for r in db.rows(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )
    }
    assert {
        "shop",
        "page_view",
        "decision_log",
        "page_summary",
        "outcome_event",
        "consent_ping_daily",
        "session_rollup",
    } <= names
    views = {
        r["table_name"]
        for r in db.rows(
            "SELECT table_name FROM information_schema.views WHERE table_schema='public'"
        )
    }
    assert "session_rollup" in views


def test_event_tables_are_indexed_on_shop_session_and_ts(db: Db) -> None:
    for table in ("page_view", "decision_log", "page_summary", "outcome_event"):
        idx = db.rows("SELECT indexdef FROM pg_indexes WHERE tablename = :t", t=table)
        assert any("(shop_id, session_id, ts)" in i["indexdef"] for i in idx), table


def test_primary_keys_follow_the_spec(db: Db) -> None:
    pks = {
        r["table_name"]: r["cols"]
        for r in db.rows(
            "SELECT tc.table_name, "
            "array_agg(kcu.column_name::text ORDER BY kcu.ordinal_position) AS cols "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu USING (constraint_name, table_name) "
            "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public' "
            "GROUP BY tc.table_name"
        )
    }
    assert pks["shop"] == ["shop_id"]
    assert pks["page_view"] == ["event_id"]
    assert pks["decision_log"] == ["decision_id"]
    assert pks["page_summary"] == ["event_id"]
    assert pks["outcome_event"] == ["event_id"]
    assert pks["consent_ping_daily"] == ["shop_id", "day", "consented"]


def test_decision_log_event_id_is_unique(db: Db) -> None:
    rows = db.rows("SELECT indexdef FROM pg_indexes WHERE tablename = 'decision_log'")
    assert any("UNIQUE" in r["indexdef"] and "(event_id)" in r["indexdef"] for r in rows)


def test_there_is_exactly_one_migration_head(migrated: object) -> None:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(API_DIR / "alembic")))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1

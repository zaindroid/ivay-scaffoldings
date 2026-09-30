"""initial schema: tables, indexes and the session_rollup view

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# No column anywhere holds an IP address or user agent (spec 9.3).
TABLES = """
CREATE TABLE shop (
    shop_id            text PRIMARY KEY,
    platform           text NOT NULL DEFAULT 'shopify',
    allowed_origins    text[] NOT NULL DEFAULT '{}',
    config             jsonb NOT NULL,
    -- Name of the environment variable that holds the webhook secret. Never the secret itself.
    webhook_secret_ref text
);

CREATE TABLE page_view (
    event_id     text PRIMARY KEY,
    shop_id      text NOT NULL,
    visitor_hash text NOT NULL,
    session_id   text NOT NULL,
    page_id      text NOT NULL,
    ts           timestamptz NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now(),
    page_type    text NOT NULL,
    device       text NOT NULL,
    product_id   text,
    country      text
);

CREATE TABLE decision_log (
    decision_id    text PRIMARY KEY,
    event_id       text NOT NULL UNIQUE,
    shop_id        text NOT NULL,
    visitor_hash   text NOT NULL,
    session_id     text NOT NULL,
    page_id        text NOT NULL,
    ts             timestamptz NOT NULL,
    received_at    timestamptz NOT NULL DEFAULT now(),
    friction_state text NOT NULL,
    rule_id        text NOT NULL,
    rule_version   text NOT NULL,
    fire_seq       integer NOT NULL,
    arm            text NOT NULL,
    mode           text NOT NULL,
    play           text,
    propensity     double precision,
    content_ref    text,
    has_content    boolean NOT NULL,
    features       jsonb NOT NULL
);

CREATE TABLE page_summary (
    event_id     text PRIMARY KEY,
    shop_id      text NOT NULL,
    session_id   text NOT NULL,
    page_id      text NOT NULL,
    ts           timestamptz NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now(),
    features     jsonb NOT NULL,
    eval_count   integer NOT NULL,
    eval_p50_us  double precision NOT NULL,
    eval_max_us  double precision NOT NULL
);

CREATE TABLE outcome_event (
    event_id    text PRIMARY KEY,
    shop_id     text NOT NULL,
    session_id  text NOT NULL,
    kind        text NOT NULL,
    value       numeric,
    source      text NOT NULL,
    ts          timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

-- Aggregated counter only: no per-request rows.
CREATE TABLE consent_ping_daily (
    shop_id   text NOT NULL,
    day       date NOT NULL,
    consented boolean NOT NULL,
    count     integer NOT NULL DEFAULT 0,
    PRIMARY KEY (shop_id, day, consented)
);
"""

INDEXES = """
CREATE INDEX ix_page_view_shop_session_ts ON page_view (shop_id, session_id, ts);
CREATE INDEX ix_decision_log_shop_session_ts ON decision_log (shop_id, session_id, ts);
CREATE INDEX ix_page_summary_shop_session_ts ON page_summary (shop_id, session_id, ts);
CREATE INDEX ix_outcome_event_shop_session_ts ON outcome_event (shop_id, session_id, ts);
-- One order_completed per session: the pixel and the webhook both report it (spec 9.2).
CREATE UNIQUE INDEX uq_outcome_order_per_session
    ON outcome_event (shop_id, session_id) WHERE kind = 'order_completed';
"""

# One row per (shop, session). The gate report reads this view (spec 9.1).
ROLLUP = """
CREATE VIEW session_rollup AS
WITH sessions AS (
    SELECT shop_id, session_id FROM page_view
    UNION SELECT shop_id, session_id FROM page_summary
    UNION SELECT shop_id, session_id FROM decision_log
    UNION SELECT shop_id, session_id FROM outcome_event
),
snaps AS (
    SELECT shop_id, session_id, ts, features FROM page_summary
    UNION ALL
    SELECT shop_id, session_id, ts, features FROM decision_log
),
latest AS (
    SELECT DISTINCT ON (shop_id, session_id) shop_id, session_id, features
    FROM snaps ORDER BY shop_id, session_id, ts DESC
),
page_max AS (
    SELECT shop_id, session_id,
        max((features->>'shipping_block_dwell_s')::numeric) AS max_shipping_block_dwell_s,
        max((features->>'returns_block_dwell_s')::numeric)  AS max_returns_block_dwell_s,
        max((features->>'size_block_dwell_s')::numeric)     AS max_size_block_dwell_s,
        max((features->>'scroll_reversals_30s')::numeric)   AS max_scroll_reversals_30s,
        max((features->>'variant_toggles_since_atc')::numeric) AS max_variant_toggles_since_atc,
        max((features->>'repeated_taps_5s')::numeric)       AS max_repeated_taps_5s,
        max((features->>'cart_value')::numeric)             AS cart_value
    FROM snaps GROUP BY shop_id, session_id
),
pv AS (
    SELECT shop_id, session_id,
        max(visitor_hash) AS visitor_hash,
        min(ts) AS first_ts,
        max(ts) AS last_ts,
        count(*) AS page_views,
        count(*) FILTER (WHERE page_type = 'product')         AS product_views,
        count(*) FILTER (WHERE page_type = 'cart')            AS cart_views,
        count(*) FILTER (WHERE page_type = 'shipping_policy') AS shipping_policy_views,
        count(*) FILTER (WHERE page_type = 'returns_policy')  AS returns_policy_views,
        (array_agg(device ORDER BY ts))[1] AS device,
        (array_agg(country ORDER BY ts) FILTER (WHERE country IS NOT NULL))[1] AS country
    FROM page_view GROUP BY shop_id, session_id
),
dec AS (
    SELECT DISTINCT ON (shop_id, session_id) shop_id, session_id,
        friction_state AS first_fired_state, arm
    FROM decision_log ORDER BY shop_id, session_id, fire_seq
),
fired AS (
    SELECT shop_id, session_id,
        count(*) AS rules_fired,
        bool_or(friction_state = 'delivery_uncertainty') AS fired_delivery,
        bool_or(friction_state = 'returns_uncertainty')  AS fired_returns,
        bool_or(friction_state = 'sizing_uncertainty')   AS fired_sizing
    FROM decision_log GROUP BY shop_id, session_id
),
oc AS (
    SELECT shop_id, session_id,
        bool_or(kind = 'add_to_cart')       AS has_add_to_cart,
        bool_or(kind = 'checkout_started')  AS has_checkout_started,
        bool_or(kind = 'order_completed')   AS has_order_completed,
        max(value) FILTER (WHERE kind = 'order_completed') AS order_value
    FROM outcome_event GROUP BY shop_id, session_id
)
SELECT
    s.shop_id,
    s.session_id,
    pv.visitor_hash,
    pv.first_ts,
    pv.last_ts,
    pv.device,
    pv.country,
    coalesce(pv.page_views, 0)            AS page_views,
    coalesce(pv.product_views, 0)         AS product_views,
    coalesce(pv.cart_views, 0)            AS cart_views,
    coalesce(pv.shipping_policy_views, 0) AS shipping_policy_views,
    coalesce(pv.returns_policy_views, 0)  AS returns_policy_views,
    -- final session-scoped features: the latest snapshot
    coalesce((l.features->>'shipping_page_visited')::boolean, false) AS shipping_page_visited,
    coalesce((l.features->>'returns_page_visited')::boolean, false)  AS returns_page_visited,
    coalesce((l.features->>'size_chart_opens')::integer, 0)          AS size_chart_opens,
    coalesce((l.features->>'tab_hidden_count')::integer, 0)          AS tab_hidden_count,
    coalesce((l.features->>'pages_viewed')::integer, 0)              AS pages_viewed,
    coalesce((l.features->>'cart_adds')::integer, 0)                 AS cart_adds,
    -- max of page-scoped features over the session
    pm.max_shipping_block_dwell_s,
    pm.max_returns_block_dwell_s,
    pm.max_size_block_dwell_s,
    pm.max_scroll_reversals_30s,
    pm.max_variant_toggles_since_atc,
    pm.max_repeated_taps_5s,
    pm.cart_value,
    -- touched shipping, returns or size information (gate number 1)
    (coalesce((l.features->>'shipping_page_visited')::boolean, false)
        OR coalesce(pm.max_shipping_block_dwell_s, 0) > 0) AS touched_shipping,
    (coalesce((l.features->>'returns_page_visited')::boolean, false)
        OR coalesce(pm.max_returns_block_dwell_s, 0) > 0)  AS touched_returns,
    (coalesce((l.features->>'size_chart_opens')::integer, 0) > 0
        OR coalesce(pm.max_size_block_dwell_s, 0) > 0)     AS touched_size,
    d.first_fired_state,
    d.arm,
    coalesce(f.rules_fired, 0)            AS rules_fired,
    coalesce(f.fired_delivery, false)     AS fired_delivery,
    coalesce(f.fired_returns, false)      AS fired_returns,
    coalesce(f.fired_sizing, false)       AS fired_sizing,
    coalesce(o.has_add_to_cart, false)      AS has_add_to_cart,
    coalesce(o.has_checkout_started, false) AS has_checkout_started,
    coalesce(o.has_order_completed, false)  AS has_order_completed,
    o.order_value,
    -- abandoning session: viewed a product or cart page and no order_completed (spec 2)
    (coalesce(pv.product_views, 0) + coalesce(pv.cart_views, 0) > 0
        AND NOT coalesce(o.has_order_completed, false)) AS abandoned
FROM sessions s
LEFT JOIN pv ON pv.shop_id = s.shop_id AND pv.session_id = s.session_id
LEFT JOIN latest l ON l.shop_id = s.shop_id AND l.session_id = s.session_id
LEFT JOIN page_max pm ON pm.shop_id = s.shop_id AND pm.session_id = s.session_id
LEFT JOIN dec d ON d.shop_id = s.shop_id AND d.session_id = s.session_id
LEFT JOIN fired f ON f.shop_id = s.shop_id AND f.session_id = s.session_id
LEFT JOIN oc o ON o.shop_id = s.shop_id AND o.session_id = s.session_id;
"""


def upgrade() -> None:
    for block in (TABLES, INDEXES, ROLLUP):
        for stmt in [s.strip() for s in block.split(";\n") if s.strip()]:
            op.execute(stmt if stmt.endswith(";") else stmt + ";")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS session_rollup")
    for t in (
        "consent_ping_daily",
        "outcome_event",
        "page_summary",
        "decision_log",
        "page_view",
        "shop",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t}")

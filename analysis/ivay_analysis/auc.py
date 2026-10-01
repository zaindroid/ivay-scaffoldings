"""Number 5: signal lift. Cross-validated AUC of (baseline + signals) minus AUC of baseline.

The two models see the same folds, so the difference is not an artefact of the split.

Leakage matters here. The default outcome is add_to_cart, so nothing that is only true after an
add-to-cart may be a feature: `cart_adds` is the outcome itself, `pages_viewed` and the page counts
include the cart page that follows an add-to-cart, and the live cart value jumps once an item is in
the cart. The baseline therefore uses the page type and cart value of the FIRST thing seen in the
session, and the signals exclude every counter that includes later pages.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ivay_analysis.config import AucConfig

# Signals: behaviour the SDK observes that is not a consequence of the outcome.
SIGNAL_COLUMNS = (
    "shipping_page_visited",
    "returns_page_visited",
    "size_chart_opens",
    "tab_hidden_count",
    "max_shipping_block_dwell_s",
    "max_returns_block_dwell_s",
    "max_size_block_dwell_s",
    "max_scroll_reversals_30s",
    "max_variant_toggles_since_atc",
    "max_repeated_taps_5s",
)
# Never features: they contain, or follow from, the outcomes.
EXCLUDED_AS_LEAKY = (
    "cart_adds",
    "pages_viewed",
    "page_views",
    "product_views",
    "cart_views",
    "has_add_to_cart",
    "has_checkout_started",
    "has_order_completed",
    "order_value",
    "abandoned",
    "cart_value",
)


@dataclass(frozen=True)
class AucResult:
    auc_full: float
    auc_base: float
    lift: float
    n: int
    positives: int
    folds: int
    note: str = ""


def baseline_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Device, the cart value at the start of the session, and the first page type."""
    out = pd.DataFrame(index=df.index)
    out["device_mobile"] = (df["device"] == "mobile").astype(float)
    out["device_tablet"] = (df["device"] == "tablet").astype(float)
    out["log_cart_value"] = np.log1p(df["first_cart_value"].fillna(0).astype(float))
    out["first_page_cart"] = (df["first_page_type"] == "cart").astype(float)
    out["first_page_product"] = (df["first_page_type"] == "product").astype(float)
    return out


def signal_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The signals as measured, plus a "touched at all" indicator for each count or dwell time.
    Behavioural counts sit mostly at zero, and whether a shopper did something at all is often more
    informative than how often; the indicators let a linear model use that."""
    raw = df[list(SIGNAL_COLUMNS)].astype(float).fillna(0.0)
    flags = {
        f"{c}_any": (raw[c] > 0).astype(float) for c in SIGNAL_COLUMNS if not c.endswith("_visited")
    }
    return pd.concat([raw, pd.DataFrame(flags, index=raw.index)], axis=1)


def _oof_auc(x: pd.DataFrame, y: np.ndarray, cv: StratifiedKFold) -> float:
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    proba = cross_val_predict(model, x.to_numpy(), y, cv=cv, method="predict_proba")[:, 1]
    return float(roc_auc_score(y, proba))


def select_population(sessions: pd.DataFrame, population: str) -> pd.DataFrame:
    seen = sessions[sessions["page_views"] > 0]  # the SDK actually ran
    if population == "product_sessions":
        return seen[seen["product_views"] > 0]
    return seen


def cross_validated_lift(sessions: pd.DataFrame, cfg: AucConfig) -> AucResult:
    df = select_population(sessions, cfg.population).reset_index(drop=True)
    y = df[f"has_{cfg.outcome}"].astype(int).to_numpy()
    n, pos = len(df), int(y.sum())
    nan = float("nan")
    if pos < cfg.folds or n - pos < cfg.folds:
        return AucResult(nan, nan, nan, n, pos, cfg.folds, "not computable: too few of one class")
    cv = StratifiedKFold(n_splits=cfg.folds, shuffle=True, random_state=cfg.seed)
    base = baseline_frame(df)
    full = pd.concat([base, signal_frame(df)], axis=1)
    auc_base = _oof_auc(base, y, cv)
    auc_full = _oof_auc(full, y, cv)
    return AucResult(auc_full, auc_base, auc_full - auc_base, n, pos, cfg.folds)

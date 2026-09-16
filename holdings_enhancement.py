from __future__ import annotations

"""Holdings enrichment used by the Streamlit fund-analysis app.

Adds three things without changing the existing MoneyDJ parsing contract:
1. market/country fallback for foreign holdings whose investment theme is unknown;
2. clearer holding-change labels (新增/加碼/減碼/持平/退出);
3. latest quarterly revenue/net-income growth from yfinance when available.

Missing quote/fundamental data is intentionally left blank instead of guessed.
"""

from functools import lru_cache
import re

import numpy as np
import pandas as pd
import yfinance as yf


UNKNOWN_LABELS = {"", "未分類", "其他", "其他／待確認", "待確認", "nan", "none"}


def infer_market(ticker: str, name: str = "") -> str:
    symbol = str(ticker or "").strip().upper()
    text = str(name or "").strip().lower()

    suffixes = (
        ((".TW", ".TWO"), "台股"),
        ((".T",), "日股"),
        ((".HK",), "港股"),
        ((".KS", ".KQ"), "韓股"),
        ((".SS", ".SZ"), "陸股"),
    )
    for endings, market in suffixes:
        if symbol.endswith(endings):
            return market

    if symbol.endswith((".L", ".DE", ".PA", ".AS", ".SW", ".TO", ".V", ".AX", ".NZ", ".SI", ".BO", ".NS")):
        return "其他海外"

    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol) and not symbol.endswith((".TW", ".TWO")):
        return "美股"

    # Name-only fallback for common markets when the source does not provide a Yahoo ticker.
    if any(word in text for word in ("samsung", "sk hynix", "korea", "korean")):
        return "韓股"
    if any(word in text for word in ("mitsubishi", "sumitomo", "toyota", "sony", "hitachi", "murata", "kioxia", "japan")):
        return "日股"
    if any(word in text for word in ("petrochina", "ping an", "tencent", "meituan", "hong kong")):
        return "港股"
    return "其他海外"


def _clean_label(value) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in UNKNOWN_LABELS or text in UNKNOWN_LABELS else text


def _quarterly_value(frame: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    for label in candidates:
        if label in frame.index:
            return pd.to_numeric(frame.loc[label], errors="coerce").dropna().sort_index(ascending=False)
    return pd.Series(dtype=float)


def _growth_pct(series: pd.Series) -> float:
    if len(series) < 2:
        return np.nan
    latest = float(series.iloc[0])
    # Prefer YoY (four quarters back); otherwise show QoQ when only two quarters exist.
    prior = float(series.iloc[4]) if len(series) >= 5 else float(series.iloc[1])
    if not np.isfinite(latest) or not np.isfinite(prior) or prior == 0:
        return np.nan
    return (latest / prior - 1.0) * 100.0


@lru_cache(maxsize=256)
def earnings_snapshot(ticker: str) -> dict[str, float | str]:
    symbol = str(ticker or "").strip()
    if not symbol or " " in symbol:
        return {}
    try:
        stock = yf.Ticker(symbol)
        frame = stock.quarterly_income_stmt
        if frame is None or frame.empty:
            frame = stock.quarterly_financials
        revenue = _quarterly_value(frame, ("Total Revenue", "Operating Revenue", "Revenue"))
        net_income = _quarterly_value(frame, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"))
        dates = list(frame.columns) if frame is not None and not frame.empty else []
        latest_date = pd.to_datetime(dates[0], errors="coerce") if dates else pd.NaT
        return {
            "最新財報期": "" if pd.isna(latest_date) else latest_date.strftime("%Y-%m-%d"),
            "最新營收": float(revenue.iloc[0]) if len(revenue) else np.nan,
            "營收成長%": _growth_pct(revenue),
            "最新淨利": float(net_income.iloc[0]) if len(net_income) else np.nan,
            "淨利成長%": _growth_pct(net_income),
        }
    except Exception:
        return {}


def install(fund_analysis_module) -> None:
    fa = fund_analysis_module
    if getattr(fa, "_holdings_enhancement_installed", False):
        return

    # Extend high-value Korean memory/HBM names before wrapping identity lookup.
    fa.MONEYDJ_HOLDING_MAP.setdefault(
        "sk hynix", ("000660.KS", "記憶體", "DRAM、HBM與AI記憶體")
    )
    fa.MONEYDJ_HOLDING_MAP.setdefault(
        "samsung electronics", ("005930.KS", "半導體與電子", "DRAM、HBM與AI記憶體")
    )

    original_identity = fa._holding_identity
    original_normalize = fa.normalize_holdings
    original_changes = fa.holding_changes

    def enhanced_identity(name: str):
        ticker, sector, theme = original_identity(name)
        market = infer_market(ticker, name)
        clean_sector = _clean_label(sector)
        clean_theme = _clean_label(theme)
        # Recognised investment theme always wins. Unknown names fall back to market,
        # never to a generic "其他／待確認" bucket.
        return ticker, clean_sector or market, clean_theme or market

    def enhanced_normalize_holdings(df: pd.DataFrame) -> pd.DataFrame:
        out = original_normalize(df)
        out = out.copy()
        out["market"] = [infer_market(t, n) for t, n in zip(out["ticker"], out["name"])]
        theme_clean = out["theme"].map(_clean_label)
        sector_clean = out["sector"].map(_clean_label)
        out["theme"] = [theme if theme else market for theme, market in zip(theme_clean, out["market"])]
        out["sector"] = [sector if sector else market for sector, market in zip(sector_clean, out["market"])]
        out["classification"] = out["theme"]
        return out

    def enhanced_holding_changes(holdings: pd.DataFrame, fund: str, start_date, end_date) -> pd.DataFrame:
        out = original_changes(holdings, fund, start_date, end_date).copy()
        if out.empty:
            return out
        out["市場"] = [infer_market(t, n) for t, n in zip(out["ticker"], out["name"])]
        out["分類"] = [
            _clean_label(theme) or market
            for theme, market in zip(out["theme"], out["市場"])
        ]
        out["動作"] = np.select(
            [
                out["期初權重"].eq(0) & out["期末權重"].gt(0),
                out["期末權重"].eq(0) & out["期初權重"].gt(0),
                out["權重變化"].gt(0.05),
                out["權重變化"].lt(-0.05),
            ],
            ["新增", "退出", "加碼", "減碼"],
            default="持平",
        )

        snapshots = [earnings_snapshot(ticker) for ticker in out["ticker"]]
        for column in ("最新財報期", "最新營收", "營收成長%", "最新淨利", "淨利成長%"):
            out[column] = [snapshot.get(column, np.nan if column != "最新財報期" else "") for snapshot in snapshots]
        return out

    fa._holding_identity = enhanced_identity
    fa.normalize_holdings = enhanced_normalize_holdings
    fa.holding_changes = enhanced_holding_changes
    fa.infer_market = infer_market
    fa.earnings_snapshot = earnings_snapshot
    fa._holdings_enhancement_installed = True

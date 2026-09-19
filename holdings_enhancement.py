from __future__ import annotations

"""Holdings enrichment for market fallback, holding status, earnings and attribution."""

from functools import lru_cache
import re

import numpy as np
import pandas as pd
import yfinance as yf

UNKNOWN_LABELS = {"", "未分類", "其他", "其他／待確認", "待確認", "nan", "none"}


def infer_market(ticker: str, name: str = "") -> str:
    symbol = str(ticker or "").strip().upper()
    text = str(name or "").strip().lower()
    for endings, market in (
        ((".TW", ".TWO"), "台股"), ((".T",), "日股"), ((".HK",), "港股"),
        ((".KS", ".KQ"), "韓股"), ((".SS", ".SZ"), "陸股"),
    ):
        if symbol.endswith(endings):
            return market
    if symbol.endswith((".L", ".DE", ".PA", ".AS", ".SW", ".TO", ".V", ".AX", ".NZ", ".SI", ".BO", ".NS")):
        return "其他海外"
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol) and not symbol.endswith((".TW", ".TWO")):
        return "美股"
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


def theme_attribution(changes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate stock price attribution into an explainable theme-level table."""
    if changes is None or changes.empty:
        return pd.DataFrame()
    work = changes.copy()
    if "分類" not in work:
        work["分類"] = work.get("theme", "未分類")
    valid = work.dropna(subset=["估計貢獻"]).copy()
    if valid.empty:
        return pd.DataFrame()
    rows = []
    for theme, group in valid.groupby("分類", dropna=False):
        ranked = group.assign(_abs=group["估計貢獻"].abs()).sort_values("_abs", ascending=False)
        leaders = ranked["name"].astype(str).head(3).tolist()
        rows.append({
            "題材／市場": theme,
            "代表持股": "、".join(leaders),
            "持股檔數": int(group["ticker"].nunique()),
            "期末權重": group["期末權重"].sum(),
            "權重變化": group["權重變化"].sum(),
            "估計貢獻": group["估計貢獻"].sum(),
        })
    return pd.DataFrame(rows).sort_values("估計貢獻", ascending=False)


def driver_summary(changes: pd.DataFrame) -> list[str]:
    """Generate factual, calculation-based driver sentences; no causal claims beyond attribution."""
    if changes is None or changes.empty:
        return []
    valid = changes.dropna(subset=["估計貢獻"]).copy()
    if valid.empty:
        return ["目前缺少足夠的個股市場價格，暫時無法完成基金漲跌歸因。"]
    themes = theme_attribution(valid)
    messages = []
    positive = themes[themes["估計貢獻"] > 0].head(3)
    negative = themes[themes["估計貢獻"] < 0].sort_values("估計貢獻").head(3)
    if not positive.empty:
        labels = "、".join(f"{r['題材／市場']} ({r['估計貢獻']:+.2f}pp)" for _, r in positive.iterrows())
        messages.append(f"依持股權重與個股區間報酬估算，主要正貢獻來自：{labels}。")
    if not negative.empty:
        labels = "、".join(f"{r['題材／市場']} ({r['估計貢獻']:+.2f}pp)" for _, r in negative.iterrows())
        messages.append(f"主要負貢獻／拖累來自：{labels}。")
    additions = valid[valid.get("狀態", pd.Series(index=valid.index, dtype=str)).isin(["新增", "加碼"])]
    reductions = valid[valid.get("狀態", pd.Series(index=valid.index, dtype=str)).isin(["減碼", "退出"])]
    if not additions.empty:
        labels = "、".join(additions.sort_values("權重變化", ascending=False)["分類"].drop_duplicates().astype(str).head(3))
        messages.append(f"經理人本期較明顯新增／加碼的方向包括：{labels}。")
    if not reductions.empty:
        labels = "、".join(reductions.sort_values("權重變化")["分類"].drop_duplicates().astype(str).head(3))
        messages.append(f"較明顯減碼／退出的方向包括：{labels}。")
    return messages


def install(fund_analysis_module) -> None:
    fa = fund_analysis_module
    if getattr(fa, "_holdings_enhancement_installed", False):
        return
    fa.MONEYDJ_HOLDING_MAP.setdefault("sk hynix", ("000660.KS", "記憶體", "DRAM、HBM與AI記憶體"))
    fa.MONEYDJ_HOLDING_MAP.setdefault("samsung electronics", ("005930.KS", "半導體與電子", "DRAM、HBM與AI記憶體"))
    original_identity = fa._holding_identity
    original_normalize = fa.normalize_holdings
    original_changes = fa.holding_changes

    def enhanced_identity(name: str):
        ticker, sector, theme = original_identity(name)
        market = infer_market(ticker, name)
        return ticker, _clean_label(sector) or market, _clean_label(theme) or market

    def enhanced_normalize_holdings(df: pd.DataFrame) -> pd.DataFrame:
        out = original_normalize(df).copy()
        out["market"] = [infer_market(t, n) for t, n in zip(out["ticker"], out["name"])]
        themes = out["theme"].map(_clean_label)
        sectors = out["sector"].map(_clean_label)
        out["theme"] = [x or m for x, m in zip(themes, out["market"])]
        out["sector"] = [x or m for x, m in zip(sectors, out["market"])]
        out["classification"] = out["theme"]
        return out

    def enhanced_holding_changes(holdings: pd.DataFrame, fund: str, start_date, end_date) -> pd.DataFrame:
        out = original_changes(holdings, fund, start_date, end_date).copy()
        if out.empty:
            return out
        out["市場"] = [infer_market(t, n) for t, n in zip(out["ticker"], out["name"])]
        out["分類"] = [_clean_label(t) or m for t, m in zip(out["theme"], out["市場"])]
        status = np.select(
            [out["期初權重"].eq(0) & out["期末權重"].gt(0), out["期末權重"].eq(0) & out["期初權重"].gt(0), out["權重變化"].gt(0.05), out["權重變化"].lt(-0.05)],
            ["新增", "退出", "加碼", "減碼"], default="持平",
        )
        out["狀態"] = status
        out["動作"] = pd.Series(status, index=out.index).replace({"新增": "新進", "退出": "出清"})
        snapshots = [earnings_snapshot(ticker) for ticker in out["ticker"]]
        for column in ("最新財報期", "最新營收", "營收成長%", "最新淨利", "淨利成長%"):
            default = "" if column == "最新財報期" else np.nan
            out[column] = [item.get(column, default) for item in snapshots]
        return out

    fa._holding_identity = enhanced_identity
    fa.normalize_holdings = enhanced_normalize_holdings
    fa.holding_changes = enhanced_holding_changes
    fa.infer_market = infer_market
    fa.earnings_snapshot = earnings_snapshot
    fa.theme_attribution = theme_attribution
    fa.driver_summary = driver_summary
    fa._holdings_enhancement_installed = True

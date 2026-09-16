"""Runtime reliability patch for Yahoo Finance downloads used by fund attribution.

Python imports sitecustomize automatically when the repository root is on sys.path.
The wrapper keeps the normal yfinance behavior, but if a multi-ticker request is
empty or incomplete it retries missing tickers individually. This prevents one
bad/unsupported symbol from blanking the whole holdings P/L attribution table.
"""
from __future__ import annotations

try:
    import pandas as pd
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


if yf is not None and not getattr(yf.download, "_fund_app_robust", False):
    _original_download = yf.download

    def _symbols(value):
        if isinstance(value, str):
            return [x for x in value.replace(",", " ").split() if x]
        try:
            return [str(x) for x in value if str(x)]
        except TypeError:
            return [str(value)] if value else []

    def _has_symbol(frame, symbol):
        if frame is None or getattr(frame, "empty", True):
            return False
        cols = frame.columns
        if isinstance(cols, pd.MultiIndex):
            return symbol in cols.get_level_values(-1) or symbol in cols.get_level_values(0)
        return len(cols) > 0

    def robust_download(tickers, *args, **kwargs):
        symbols = _symbols(tickers)
        try:
            base = _original_download(tickers, *args, **kwargs)
        except Exception:
            base = pd.DataFrame()
        if len(symbols) <= 1:
            return base
        missing = [s for s in symbols if not _has_symbol(base, s)]
        if not missing:
            return base
        pieces = []
        if base is not None and not base.empty:
            pieces.append(base)
        for symbol in missing:
            try:
                one = _original_download(symbol, *args, **kwargs)
            except Exception:
                continue
            if one is None or one.empty:
                continue
            if not isinstance(one.columns, pd.MultiIndex):
                one.columns = pd.MultiIndex.from_product([one.columns, [symbol]])
            pieces.append(one)
        if not pieces:
            return base
        try:
            return pd.concat(pieces, axis=1).loc[:, ~pd.concat(pieces, axis=1).columns.duplicated()]
        except Exception:
            return base

    robust_download._fund_app_robust = True
    yf.download = robust_download

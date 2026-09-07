from __future__ import annotations

import io
import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests
import yfinance as yf


NAV_ALIASES = {
    "日期": "date", "date": "date", "Date": "date",
    "基金": "fund", "基金名稱": "fund", "fund": "fund",
    "淨值": "nav", "NAV": "nav", "nav": "nav",
    "基金規模": "fund_size", "規模": "fund_size", "fund_size": "fund_size",
}

HOLDING_ALIASES = {
    "日期": "date", "date": "date", "Date": "date",
    "基金": "fund", "基金名稱": "fund", "fund": "fund",
    "代碼": "ticker", "股票代碼": "ticker", "ticker": "ticker",
    "持股": "name", "股票名稱": "name", "名稱": "name", "name": "name",
    "權重": "weight", "持股比重": "weight", "持股比重%": "weight", "weight": "weight",
    "產業": "sector", "sector": "sector",
    "投資題材": "theme", "題材": "theme", "theme": "theme",
    "區間報酬": "period_return", "區間報酬%": "period_return", "period_return": "period_return",
}


MONEYDJ_HOLDING_MAP = {
    "advanced micro devices": ("AMD", "半導體設計", "AI運算與資料中心"),
    "台積電": ("2330.TW", "晶圓代工", "AI先進製程"),
    "台光電": ("2383.TW", "銅箔基板", "AI伺服器與高速傳輸"),
    "貿聯": ("3665.TW", "連接線束", "AI伺服器高速連接與電力傳輸"),
    "健策": ("3653.TW", "散熱模組", "AI伺服器散熱與均熱片"),
    "聯發科": ("2454.TW", "IC設計", "邊緣AI與高階運算晶片"),
    "奇鋐": ("3017.TW", "散熱模組", "AI伺服器液冷與散熱"),
    "智邦": ("2345.TW", "網通設備", "AI資料中心高速交換器"),
    "南電": ("8046.TW", "IC載板", "AI與高效能運算ABF載板"),
    "台燿": ("6274.TWO", "銅箔基板", "AI伺服器高速傳輸材料"),
    "旺矽": ("6223.TWO", "半導體測試介面", "AI與高效能運算晶片測試"),
    "欣興": ("3037.TW", "IC載板與PCB", "AI伺服器ABF載板與高階PCB"),
    "國巨": ("2327.TW", "被動元件", "AI伺服器與車用高階被動元件"),
    "murata manufacturing": ("6981.T", "被動元件", "高階被動元件"),
    "micron technology": ("MU", "記憶體", "DRAM與HBM"),
    "sandisk": ("SNDK", "資料儲存", "NAND與儲存"),
    "taiyo yuden": ("6976.T", "被動元件", "MLCC與電子元件"),
    "kioxia holdings": ("285A.T", "記憶體", "NAND快閃記憶體"),
    "bloom energy": ("BE", "新能源設備", "AI資料中心電力"),
    "spdr標普生技": ("XBI", "生技ETF", "生技創新"),
}

MONEYDJ_FUND_NAMES = {
    "ACPS38-5818": "統一全球新科技基金(台幣)",
}


@dataclass
class RiskMetrics:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe: float
    sortino: float
    var_95: float
    positive_ratio: float


def read_table(uploaded) -> pd.DataFrame:
    if uploaded is None:
        return pd.DataFrame()
    raw = uploaded.getvalue()
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    for encoding in ("utf-8-sig", "utf-8", "big5"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.BytesIO(raw))


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只接受完整的 http 或 https 網址。")
    if parsed.username or parsed.password:
        raise ValueError("網址不可包含帳號或密碼。")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("無法解析網址主機。") from exc
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise ValueError("基於安全考量，不接受內網或本機網址。")
    return parsed.geturl()


def read_url_tables(url: str, max_bytes: int = 12_000_000) -> list[pd.DataFrame]:
    """Read public CSV, Excel or HTML tables without allowing local-network URLs."""
    safe_url = _validate_public_url(url)
    response = None
    for _ in range(4):
        parsed = urlparse(safe_url)
        # MoneyDJ目前使用的憑證缺少Subject Key Identifier；相容模式僅限此公開資料主機。
        verify_certificate = parsed.hostname != "tcbbankfund.moneydj.com"
        request_error = None
        for attempt in range(3):
            try:
                response = requests.get(
                    safe_url,
                    timeout=(15, 45),
                    headers={"User-Agent": "Mozilla/5.0 FundAnalysisReportGenerator/1.0"},
                    allow_redirects=False,
                    stream=True,
                    verify=verify_certificate,
                )
                request_error = None
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                request_error = exc
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
        if request_error is not None:
            raise ValueError("MoneyDJ 回應逾時，已自動重試 3 次；請稍後再按一次分析。") from request_error
        if response.is_redirect or response.is_permanent_redirect:
            destination = response.headers.get("location")
            response.close()
            if not destination:
                raise ValueError("網站重新導向缺少目的網址。")
            safe_url = _validate_public_url(urljoin(safe_url, destination))
            continue
        break
    if response is None or response.is_redirect or response.is_permanent_redirect:
        raise ValueError("網站重新導向次數過多。")
    response.raise_for_status()
    _validate_public_url(response.url)
    chunks, size = [], 0
    for chunk in response.iter_content(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise ValueError("網頁或檔案超過 12 MB，請改用檔案上傳。")
        chunks.append(chunk)
    raw = b"".join(chunks)
    content_type = response.headers.get("content-type", "").lower()
    path = urlparse(response.url).path.lower()
    if "spreadsheet" in content_type or path.endswith((".xlsx", ".xls")):
        return [pd.read_excel(io.BytesIO(raw))]
    if "csv" in content_type or path.endswith(".csv"):
        for encoding in ("utf-8-sig", "utf-8", "big5"):
            try:
                return [pd.read_csv(io.BytesIO(raw), encoding=encoding)]
            except UnicodeDecodeError:
                continue
        return [pd.read_csv(io.BytesIO(raw))]
    text = raw.decode(response.encoding or "utf-8", errors="replace")
    tables = pd.read_html(io.StringIO(text))
    if not tables:
        raise ValueError("頁面中找不到可讀取的表格。")
    return tables


def classify_url_tables(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    nav_candidates, holding_candidates, descriptions = [], [], []
    nav_keys = set(NAV_ALIASES)
    holding_keys = set(HOLDING_ALIASES)
    for idx, table in enumerate(tables):
        flat = table.copy()
        if isinstance(flat.columns, pd.MultiIndex):
            flat.columns = [" ".join(str(v) for v in col if str(v) != "nan").strip() for col in flat.columns]
        cols = {str(c).strip() for c in flat.columns}
        nav_score = len(cols & nav_keys)
        holding_score = len(cols & holding_keys)
        descriptions.append(f"表格 {idx + 1}：{len(flat)} 列；欄位 {', '.join(map(str, flat.columns[:8]))}")
        if nav_score >= 2:
            nav_candidates.append((nav_score, flat))
        if holding_score >= 3:
            holding_candidates.append((holding_score, flat))
    nav = max(nav_candidates, key=lambda x: x[0])[1] if nav_candidates else pd.DataFrame()
    holdings = max(holding_candidates, key=lambda x: x[0])[1] if holding_candidates else pd.DataFrame()
    return nav, holdings, descriptions


def moneydj_fund_id(url: str) -> str | None:
    if "moneydj.com" not in url.lower():
        return None
    match = re.search(r"(ACPS\d+(?:-[A-Za-z0-9]+)?)", url, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _numeric_percent(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False).replace({"N/A": np.nan, "--": np.nan}),
        errors="coerce",
    )


def _holding_identity(name: str) -> tuple[str, str, str]:
    normalized = re.sub(r"\s+", " ", str(name)).strip().lower()
    for keyword, identity in MONEYDJ_HOLDING_MAP.items():
        if keyword in normalized:
            return identity
    return str(name).strip(), "其他／待確認", "其他／待確認"


def _market_returns(tickers: list[str], start_date: pd.Timestamp, end_date: pd.Timestamp) -> dict[str, float]:
    """Return actual adjusted-close changes; a quote failure never breaks the report."""
    unique = list(dict.fromkeys(t for t in tickers if t))
    if not unique:
        return {}
    try:
        prices = yf.download(
            unique,
            start=(start_date - pd.Timedelta(days=10)).date(),
            end=(end_date + pd.Timedelta(days=3)).date(),
            auto_adjust=True,
            progress=False,
            threads=True,
            timeout=12,
        )
        if prices.empty:
            return {}
        close = prices["Close"] if "Close" in prices else prices
        if isinstance(close, pd.Series):
            close = close.to_frame(unique[0])
        results = {}
        for ticker in unique:
            if ticker not in close.columns:
                continue
            series = pd.to_numeric(close[ticker], errors="coerce").dropna().sort_index()
            before_start = series[series.index <= start_date]
            before_end = series[series.index <= end_date]
            if before_start.empty:
                after_start = series[series.index >= start_date]
                start_value = after_start.iloc[0] if not after_start.empty else np.nan
            else:
                start_value = before_start.iloc[-1]
            end_value = before_end.iloc[-1] if not before_end.empty else np.nan
            if np.isfinite(start_value) and np.isfinite(end_value) and start_value != 0:
                results[ticker] = (end_value / start_value - 1) * 100
        return results
    except Exception:
        return {}


def load_moneydj_fund(url: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Convert a MoneyDJ wrapper URL to its public NAV and holdings pages."""
    fund_id = moneydj_fund_id(url)
    if not fund_id:
        raise ValueError("MoneyDJ 網址中找不到 ACPS 基金代碼。")
    base = "https://tcbbankfund.moneydj.com/w/wr"
    profile_url = f"{base}/wr01.djhtm?a={fund_id}"
    nav_url = f"{base}/wr02.djhtm?a={fund_id}"
    holdings_url = f"{base}/wr04.djhtm?a={fund_id}"
    profile_tables = read_url_tables(profile_url)
    nav_tables = read_url_tables(nav_url)
    holdings_tables = read_url_tables(holdings_url)

    nav_source = next((t for t in nav_tables if {"日期", "淨值"}.issubset({str(c).strip() for c in t.columns})), pd.DataFrame())
    if nav_source.empty:
        raise ValueError("MoneyDJ 淨值頁目前沒有可辨識的日期與淨值表。")
    today = pd.Timestamp.today().normalize()
    dates = []
    for value in nav_source["日期"].astype(str):
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed) or parsed.year == 1900:
            match = re.search(r"(\d{1,2})/(\d{1,2})", value)
            parsed = pd.Timestamp(today.year, int(match.group(1)), int(match.group(2))) if match else pd.NaT
        elif not re.search(r"\d{4}", value):
            parsed = pd.Timestamp(today.year, parsed.month, parsed.day)
        if pd.notna(parsed) and parsed > today + pd.Timedelta(days=7):
            parsed -= pd.DateOffset(years=1)
        dates.append(parsed)
    fund_name = MONEYDJ_FUND_NAMES.get(fund_id, f"MoneyDJ基金 {fund_id}")
    fund_size, fund_size_date = np.nan, pd.NaT
    if profile_tables:
        profile = profile_tables[0]
        for _, row in profile.iterrows():
            values = [str(value).strip() for value in row.tolist() if pd.notna(value)]
            if values and values[0] == "基金規模" and len(values) > 1:
                size_match = re.search(r"([\d,.]+)\s*億元", values[1])
                date_match = re.search(r"(\d{4}/\d{1,2}/\d{1,2})", values[1])
                if size_match:
                    fund_size = float(size_match.group(1).replace(",", ""))
                if date_match:
                    fund_size_date = pd.to_datetime(date_match.group(1), errors="coerce")
                break
    nav_df = pd.DataFrame({
        "date": dates,
        "fund": fund_name,
        "nav": pd.to_numeric(nav_source["淨值"], errors="coerce"),
        "fund_size": fund_size,
        "fund_size_date": fund_size_date,
    }).dropna()

    holding_frames = []
    for table in holdings_tables:
        flat = table.copy()
        if isinstance(flat.columns, pd.MultiIndex):
            flat.columns = [" ".join(str(v) for v in col if str(v) != "nan").strip() for col in flat.columns]
        columns = list(map(str, flat.columns))
        name_cols = [c for c in columns if "股票名稱" in c]
        weight_cols = [c for c in columns if "比例" in c]
        change_cols = [c for c in columns if "增減" in c]
        for idx, name_col in enumerate(name_cols):
            if idx >= len(weight_cols):
                continue
            frame = pd.DataFrame({"name": flat[name_col], "weight": _numeric_percent(flat[weight_cols[idx]])})
            frame["change"] = _numeric_percent(flat[change_cols[idx]]) if idx < len(change_cols) else np.nan
            holding_frames.append(frame)
    if not holding_frames:
        raise ValueError("MoneyDJ 持股頁目前沒有可辨識的股票名稱與比例表。")
    current = pd.concat(holding_frames, ignore_index=True).dropna(subset=["name", "weight"])
    current = current[~current["name"].astype(str).str.contains("股票名稱|合計", na=False)].drop_duplicates("name")
    latest_nav_date = nav_df["date"].max()
    current_date = latest_nav_date - pd.offsets.MonthEnd(1)
    prior_date = current_date - pd.offsets.MonthEnd(1)
    # MoneyDJ's 增減欄是相對前期的權重變化；缺值視為無法判斷並保留相同權重。
    prior_weight = current["weight"] - current["change"].fillna(0.0)
    identities = current["name"].astype(str).map(_holding_identity)
    tickers = [item[0] for item in identities]
    sectors = [item[1] for item in identities]
    themes = [item[2] for item in identities]
    returns = _market_returns(tickers, pd.Timestamp(prior_date), pd.Timestamp(current_date))
    common = pd.DataFrame({
        "fund": fund_name, "ticker": tickers, "name": current["name"].astype(str).values,
        "sector": sectors, "theme": themes,
        "period_return": [returns.get(ticker, np.nan) for ticker in tickers],
    })
    latest = common.assign(date=current_date, weight=current["weight"].clip(lower=0).values)
    prior = common.assign(date=prior_date, weight=prior_weight.clip(lower=0).values)
    holdings_df = pd.concat([prior, latest], ignore_index=True)
    quote_count = int(common["period_return"].notna().sum())
    descriptions = [
        f"已讀取基金基本資料頁：{profile_url}",
        f"已將外層網址轉為淨值頁：{nav_url}", f"已將外層網址轉為持股頁：{holdings_url}",
        f"已辨識 {len(common)} 檔持股的產業與題材；取得 {quote_count} 檔區間市場報酬。",
    ]
    if np.isfinite(fund_size):
        descriptions.append(f"基金規模：{fund_size:,.2f} 億元（資料日 {fund_size_date:%Y-%m-%d}）。")
    return normalize_nav(nav_df), normalize_holdings(holdings_df), descriptions


def normalize_nav(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: NAV_ALIASES.get(str(c).strip(), str(c).strip()) for c in df.columns}).copy()
    required = {"date", "fund", "nav"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"淨值檔缺少欄位：{', '.join(sorted(missing))}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    if "fund_size" in df:
        df["fund_size"] = pd.to_numeric(df["fund_size"], errors="coerce")
    return df.dropna(subset=["date", "fund", "nav"]).sort_values(["fund", "date"])


def normalize_holdings(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: HOLDING_ALIASES.get(str(c).strip(), str(c).strip()) for c in df.columns}).copy()
    required = {"date", "fund", "ticker", "name", "weight"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"持股檔缺少欄位：{', '.join(sorted(missing))}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("weight", "period_return"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("sector", "theme"):
        if col not in df:
            df[col] = "未分類"
        df[col] = df[col].fillna("未分類").astype(str)
    if "period_return" not in df:
        df["period_return"] = np.nan
    return df.dropna(subset=["date", "fund", "ticker", "weight"]).sort_values(["fund", "date", "weight"])


def calculate_risk_metrics(nav: pd.Series, risk_free_rate: float = 0.015) -> RiskMetrics:
    nav = pd.to_numeric(nav, errors="coerce").dropna()
    returns = nav.pct_change().dropna()
    if len(nav) < 2 or returns.empty:
        return RiskMetrics(*(float("nan"),) * 8)
    periods = max(len(returns), 1)
    total = nav.iloc[-1] / nav.iloc[0] - 1
    annual = (1 + total) ** (252 / periods) - 1 if total > -1 else -1.0
    vol = returns.std(ddof=1) * np.sqrt(252)
    drawdown = nav / nav.cummax() - 1
    downside = returns[returns < 0].std(ddof=1) * np.sqrt(252)
    sharpe = (annual - risk_free_rate) / vol if vol and np.isfinite(vol) else np.nan
    sortino = (annual - risk_free_rate) / downside if downside and np.isfinite(downside) else np.nan
    return RiskMetrics(total, annual, vol, drawdown.min(), sharpe, sortino, returns.quantile(0.05), (returns > 0).mean())


def holding_changes(holdings: pd.DataFrame, fund: str, start_date, end_date) -> pd.DataFrame:
    subset = holdings[holdings["fund"] == fund]
    dates = subset["date"].drop_duplicates().sort_values()
    if dates.empty:
        return pd.DataFrame()
    start = dates[dates <= pd.Timestamp(start_date)].max() if (dates <= pd.Timestamp(start_date)).any() else dates.min()
    end = dates[dates <= pd.Timestamp(end_date)].max() if (dates <= pd.Timestamp(end_date)).any() else dates.max()
    fields = ["ticker", "name", "sector", "theme", "weight", "period_return"]
    old = subset[subset["date"] == start][fields].rename(columns={"weight": "期初權重", "period_return": "區間報酬"})
    new = subset[subset["date"] == end][fields].rename(columns={"weight": "期末權重", "period_return": "區間報酬_期末"})
    out = old.merge(new, on=["ticker", "name", "sector", "theme"], how="outer")
    out["期初權重"] = out["期初權重"].fillna(0.0)
    out["期末權重"] = out["期末權重"].fillna(0.0)
    out["權重變化"] = out["期末權重"] - out["期初權重"]
    out["區間報酬"] = out["區間報酬_期末"].combine_first(out["區間報酬"])
    out["估計貢獻"] = ((out["期初權重"] + out["期末權重"]) / 2) * out["區間報酬"] / 100
    out["動作"] = np.select(
        [out["期初權重"].eq(0), out["期末權重"].eq(0), out["權重變化"].gt(0.05), out["權重變化"].lt(-0.05)],
        ["新進", "出清", "加碼", "減碼"], default="持平"
    )
    return out.drop(columns=["區間報酬_期末"]).sort_values("權重變化", ascending=False)


def exposure_table(changes: pd.DataFrame, column: str) -> pd.DataFrame:
    if changes.empty:
        return pd.DataFrame(columns=[column, "期初權重", "期末權重", "權重變化"])
    return changes.groupby(column, as_index=False)[["期初權重", "期末權重", "權重變化"]].sum().sort_values("期末權重", ascending=False)


def peer_metrics(nav_df: pd.DataFrame, start_date, end_date, risk_free_rate: float) -> pd.DataFrame:
    sample = nav_df[(nav_df["date"] >= pd.Timestamp(start_date)) & (nav_df["date"] <= pd.Timestamp(end_date))]
    rows = []
    for fund, group in sample.groupby("fund"):
        m = calculate_risk_metrics(group.sort_values("date")["nav"], risk_free_rate)
        rows.append({
            "基金": fund, "區間報酬": m.total_return * 100, "年化報酬": m.annualized_return * 100,
            "年化波動": m.annualized_volatility * 100, "最大回撤": m.max_drawdown * 100,
            "Sharpe": m.sharpe, "Sortino": m.sortino, "上漲日占比": m.positive_ratio * 100,
        })
    return pd.DataFrame(rows).sort_values("區間報酬", ascending=False)

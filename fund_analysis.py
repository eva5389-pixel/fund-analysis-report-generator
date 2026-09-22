from __future__ import annotations

import io
import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, unquote

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
    "mtar technologies": ("MTAR TECHNOLOGIES", "精密工程製造", "潔淨能源與精密零組件"),
    "高力": ("8996.TW", "熱交換與能源設備", "液冷散熱與燃料電池零組件"),
    "sterlite technologies": ("STERLITE TECHNOLOGIES", "光纖線纜", "光纖通訊與資料中心連接"),
    "aehr test systems": ("AEHR", "半導體測試設備", "晶片測試與老化測試"),
    "yuanjie semiconductor": ("YUANJIE SEMICONDUCTOR", "光半導體", "光通訊雷射晶片"),
    "robotechnik": ("ROBOTECHNIK", "自動化設備", "智慧製造與光伏自動化設備"),
    "lumentum": ("LITE", "光通訊元件", "光通訊與雷射元件"),
    "聯亞": ("3081.TWO", "光半導體", "光通訊磊晶材料"),
    "amazon": ("AMZN", "電子商務與雲端服務", "電商消費與雲端運算"),
    "nebius": ("NBIS", "AI雲端基礎設施", "GPU雲端與AI運算"),
    "tesla": ("TSLA", "電動車與能源", "電動車與儲能"),
    "modine": ("MOD", "熱管理設備", "資料中心冷卻與熱管理"),
    "sumitomo electric": ("5802.T", "電線電纜與光通訊", "光纖通訊與電力線纜"),
    "ajinomoto": ("2802.T", "食品與電子材料", "食品消費與ABF封裝材料"),
    "carvana": ("CVNA", "汽車零售", "二手車電商"),
    "allegro microsystems": ("ALGM", "類比與功率半導體", "車用與工業感測晶片"),
    "coherent": ("COHR", "光電元件", "光通訊與雷射元件"),
    "advanced micro devices": ("AMD", "半導體設計", "AI運算與資料中心"),
    # Business classifications checked against company product pages (2026-09-15).
    # https://www.kingslide.com/products_cloud?___store=taiwan
    "川湖": ("2059.TW", "伺服器機構件", "伺服器滑軌與機櫃機構件"),
    # https://www.aspeedtech.com/tw/server/
    "信驊": ("5274.TWO", "伺服器管理IC", "伺服器遠端管理晶片BMC"),
    # https://www.elaser.com.tw/sp2-4.htm
    "聯鈞": ("3450.TW", "光通訊元件封測", "光通訊雷射元件封裝測試"),
    # Sources for the six-fund expansion are recorded in theme_sources.md.
    "創意": ("3443.TW", "IC設計服務", "客製化ASIC設計與先進封裝整合"),
    "禾伸堂": ("3026.TW", "被動元件與電子零組件", "MLCC陶瓷電容與電子元件通路"),
    "上詮": ("3363.TWO", "光纖通訊元件", "光纖連接與高速光通訊"),
    "緯穎": ("6669.TW", "雲端伺服器", "AI伺服器與雲端資料中心"),
    "景碩": ("3189.TW", "IC載板", "IC封裝載板與系統級封裝"),
    "南亞科": ("2408.TW", "記憶體", "DRAM記憶體"),
    "華邦電": ("2344.TW", "記憶體", "利基型DRAM與快閃記憶體"),
    "金像電": ("2368.TW", "印刷電路板", "伺服器與高速網通PCB"),
    # 金居公司產品為銅箔基板及PCB上游的電解銅箔，並非銅箔基板成品。
    "金居": ("8358.TWO", "銅箔基板上游材料", "銅箔基板用電解銅箔"),
    "aspeed technology": ("5274.TWO", "伺服器管理IC", "伺服器遠端管理晶片BMC"),
    "mitsubishi heavy industries": ("7011.T", "重工業", "航太國防與能源設備"),
    "ping an insurance": ("2318.HK", "綜合金融", "保險與綜合金融"),
    "ase technology holding": ("3711.TW", "半導體封裝測試", "先進封裝與半導體測試"),
    "mainfreight": ("MFT.NZ", "物流運輸", "全球貨運與供應鏈物流"),
    "mitsubishi corp": ("8058.T", "綜合商社", "綜合商社與多元產業投資"),
    "petrochina": ("0857.HK", "石油天然氣", "油氣開採與煉化"),
    "hon precision": ("2317.TW", "電子製造服務", "電子代工與雲端伺服器"),
    "hon hai precision": ("2317.TW", "電子製造服務", "電子代工與雲端伺服器"),
    "sumitomo corp": ("8053.T", "綜合商社", "綜合商社與多元產業投資"),
    "sumitomo mitsui financial": ("8316.T", "銀行與金融服務", "銀行與綜合金融服務"),
    "mitsubishi ufj financial": ("8306.T", "銀行與金融服務", "銀行與綜合金融服務"),
    "toyota motor": ("7203.T", "汽車製造", "汽車製造與移動服務"),
    "sony group": ("6758.T", "娛樂與影像電子", "遊戲娛樂與影像感測"),
    "tokio marine holdings": ("8766.T", "保險", "產險與壽險服務"),
    "japan post bank": ("7182.T", "銀行", "郵政銀行與資產運用"),
    "tdk corporation": ("6762.T", "電子元件", "被動元件感測器與電池"),
    "mitsui & co": ("8031.T", "綜合商社", "綜合商社與多元產業投資"),
    "hitachi, ltd": ("6501.T", "數位服務與工業設備", "數位轉型電網與軌道建設"),
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
    "元大金": ("2885.TW", "金融控股", "金融控股、證券與資產管理"),
    "華星光": ("4979.TWO", "光通訊元件", "光通訊主動元件與高速光模組"),
    "鴻勁": ("7769.TW", "半導體設備", "半導體測試分選設備與自動化"),
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
    try:
        tables = pd.read_html(io.StringIO(text), flavor="lxml")
    except ValueError as exc:
        raise ValueError("此網址沒有可讀取的資料表，請貼基金的完整資料頁網址，或改用檔案上傳。") from exc
    if not tables:
        raise ValueError("頁面中找不到可讀取的表格。")
    # Keep the page's dated labels so importers do not invent a holdings date.
    from lxml import html as lxml_html
    if tables:
        tables[0].attrs['source_text'] = lxml_html.fromstring(text).text_content()
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


def moneydj_fund_route(url: str) -> str:
    """Use the source page's market, which is independent of provider code."""
    decoded = unquote(str(url)).lower()
    match = re.search(r"/w/(wr|wb)/|\$w\$(wr|wb)\$", decoded)
    if match:
        return match.group(1) or match.group(2)
    code = moneydj_fund_id(url) or ""
    return "wr" if code.startswith("ACPS") else "wb"


def moneydj_fund_id(url: str) -> str | None:
    decoded = unquote(str(url)).replace('^', 'Z')
    host = (urlparse(decoded).hostname or '').lower()
    if host != 'moneydj.com' and not host.endswith('.moneydj.com'):
        return None
    match = re.search(r"(?:\{A\}|[?&]a=)([A-Z]{2,6}\d+[A-Z0-9]*(?:-[A-Za-z0-9]+)?)(?![A-Za-z0-9])", decoded, flags=re.IGNORECASE)
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
    """Return adjusted-close changes with a direct Yahoo chart fallback."""
    unique = list(dict.fromkeys(str(t).strip() for t in tickers if str(t).strip()))
    if not unique:
        return {}
    start_date = pd.Timestamp(start_date).tz_localize(None).normalize()
    end_date = pd.Timestamp(end_date).tz_localize(None).normalize()
    results = {}
    try:
        prices = yf.download(
            unique,
            start=(start_date - pd.Timedelta(days=10)).date(),
            end=(end_date + pd.Timedelta(days=5)).date(),
            auto_adjust=True, progress=False, threads=False, timeout=15,
        )
        if not prices.empty:
            close = prices["Close"] if "Close" in prices else prices
            if isinstance(close, pd.Series):
                close = close.to_frame(unique[0])
            close.index = pd.to_datetime(close.index).tz_localize(None)
            for ticker in unique:
                if ticker not in close.columns:
                    continue
                series = pd.to_numeric(close[ticker], errors="coerce").dropna().sort_index()
                before_start = series[series.index <= start_date]
                before_end = series[series.index <= end_date]
                if not before_start.empty and not before_end.empty and before_start.iloc[-1] != 0:
                    results[ticker] = (before_end.iloc[-1] / before_start.iloc[-1] - 1) * 100
    except Exception:
        pass

    # Streamlit Cloud occasionally blocks yfinance's batch/cookie request.
    # The public chart endpoint does not need that session and is retried ticker by ticker.
    period1 = int((start_date - pd.Timedelta(days=10)).timestamp())
    period2 = int((end_date + pd.Timedelta(days=5)).timestamp())
    for ticker in (t for t in unique if t not in results):
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            try:
                response = requests.get(
                    f"https://{host}/v8/finance/chart/{ticker}",
                    params={"period1": period1, "period2": period2, "interval": "1d", "events": "history"},
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=15,
                )
                response.raise_for_status()
                item = response.json()["chart"]["result"][0]
                timestamps = item.get("timestamp") or []
                indicators = item.get("indicators", {})
                adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
                values = adjusted or (indicators.get("quote") or [{}])[0].get("close") or []
                series = pd.Series(values, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None))
                series = pd.to_numeric(series, errors="coerce").dropna().sort_index()
                before_start = series[series.index <= start_date + pd.Timedelta(days=1)]
                before_end = series[series.index <= end_date + pd.Timedelta(days=1)]
                if not before_start.empty and not before_end.empty and before_start.iloc[-1] != 0:
                    results[ticker] = (before_end.iloc[-1] / before_start.iloc[-1] - 1) * 100
                    break
            except Exception:
                continue
    return results

def load_moneydj_fund(url: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Convert a MoneyDJ wrapper URL to its public NAV and holdings pages."""
    fund_id = moneydj_fund_id(url)
    if not fund_id:
        raise ValueError("MoneyDJ 網址中找不到基金代碼，請貼上完整基金資料頁網址。")
    if not fund_id.startswith("ACPS"):
        from moneydj_comparison import load_comparison_fund
        nav, holdings, descriptions = load_comparison_fund(url)
        return normalize_nav(nav), normalize_holdings(holdings), descriptions
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

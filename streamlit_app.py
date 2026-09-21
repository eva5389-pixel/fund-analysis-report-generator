from __future__ import annotations

from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from fund_analysis import (
    calculate_risk_metrics, classify_url_tables, exposure_table, holding_changes,
    load_moneydj_fund, moneydj_fund_id, normalize_holdings, normalize_nav,
    peer_metrics, read_table, read_url_tables,
)
from report_builder import build_report


MAPPING_CACHE_VERSION = "2026-09-21-yahoo-chart-fallback"


st.set_page_config(page_title="基金分析報告產生器", page_icon=":material/analytics:", layout="wide")
st.caption("版本：2026-09-21｜基金規模修正＋HTML報告預覽")
view = st.segmented_control("選擇分析功能", ["績效題材與匯率比較", "原有基金深度分析"], default="績效題材與匯率比較", key="analysis_view")
if view == "績效題材與匯率比較":
    from comparison_ui import render_comparison
    render_comparison()
    st.stop()

st.title("基金分析報告產生器")
st.caption("上傳淨值與持股資料，自動整理持股變化、題材曝險、風險、損益歸因及同類基金比較。")


@st.cache_data
def load_sample():
    return normalize_nav(pd.read_csv("sample_data/nav_sample.csv")), normalize_holdings(pd.read_csv("sample_data/holdings_sample.csv"))


@st.cache_data(ttl="30m", max_entries=20, show_spinner=False)
def load_url(url: str):
    return read_url_tables(url)


@st.cache_data(ttl="6h", max_entries=20, show_spinner=False)
def load_moneydj_url(url: str, mapping_version: str):
    return load_moneydj_fund(url)


with st.sidebar:
    st.header("資料與設定")
    source_mode = st.segmented_control("匯入方式", ["範例資料", "檔案上傳", "網址分析"], default="範例資料")
    nav_file = holdings_file = None
    url = peer_url = nav_url = holdings_url = ""
    if source_mode == "檔案上傳":
        nav_file = st.file_uploader("淨值與規模檔", type=["csv", "xlsx", "xls"])
        holdings_file = st.file_uploader("持股檔", type=["csv", "xlsx", "xls"])
    elif source_mode == "網址分析":
        st.caption("可貼單一基金頁面，或分別貼淨值與持股資料網址。")
        url = st.text_input("基金頁面網址", placeholder="https://example.com/fund")
        peer_url = st.text_input("同類基金網址（選填）", placeholder="可貼另一個 MoneyDJ 基金網址進行比較")
        nav_url = st.text_input("淨值資料網址（選填）", placeholder="公開 CSV、Excel 或含表格網頁")
        holdings_url = st.text_input("持股資料網址（選填）", placeholder="公開 CSV、Excel 或含表格網頁")
    risk_free = st.number_input("無風險利率 %", min_value=0.0, max_value=20.0, value=1.5, step=0.1) / 100
    source = st.text_input("資料來源", value="基金月報、投信官網或使用者上傳資料")
    notes = st.text_area("報告補充說明", placeholder="可填寫經理人異動、申贖、特殊事件等")
    with st.expander("檔案欄位格式"):
        st.markdown("**淨值檔：** 日期、基金、淨值、基金規模（選填）\n\n**持股檔：** 日期、基金、代碼、持股、權重、產業、投資題材、區間報酬")

try:
    url_descriptions = []
    primary_funds = []
    peer_load_error = ""
    if source_mode == "範例資料":
        nav_df, holdings_df = load_sample()
    elif source_mode == "檔案上傳":
        if not nav_file or not holdings_file:
            st.info("請上傳淨值檔與持股檔，或開啟範例資料。", icon=":material/upload_file:")
            st.stop()
        nav_df = normalize_nav(read_table(nav_file))
        holdings_df = normalize_holdings(read_table(holdings_file))
    else:
        urls = [value.strip() for value in (url, nav_url, holdings_url) if value.strip()]
        if not urls:
            st.info("請至少貼上一個公開網址。", icon=":material/link:")
            st.stop()
        nav_raw, holdings_raw = pd.DataFrame(), pd.DataFrame()
        with st.spinner("正在讀取公開頁面與辨識表格…"):
            moneydj_url = next((item for item in urls if moneydj_fund_id(item)), None)
            if moneydj_url:
                nav_df, holdings_df, url_descriptions = load_moneydj_url(moneydj_url, MAPPING_CACHE_VERSION)
                primary_funds = nav_df["fund"].dropna().unique().tolist()
                if peer_url.strip():
                    if not moneydj_fund_id(peer_url):
                        peer_load_error = "同類基金網址請貼含基金代碼的 MoneyDJ 完整基金資料頁。"
                    else:
                        try:
                            peer_nav, peer_holdings, peer_descriptions = load_moneydj_url(peer_url.strip(), MAPPING_CACHE_VERSION)
                            nav_df = pd.concat([nav_df, peer_nav], ignore_index=True).drop_duplicates(["fund", "date"], keep="last")
                            holdings_df = pd.concat([holdings_df, peer_holdings], ignore_index=True).drop_duplicates(
                                ["fund", "date", "ticker"], keep="last"
                            )
                            url_descriptions.extend([f"同類基金｜{item}" for item in peer_descriptions])
                        except Exception as exc:
                            peer_load_error = str(exc)
            else:
                for current_url in urls:
                    n, h, descriptions = classify_url_tables(load_url(current_url))
                    url_descriptions.extend([f"{current_url}｜{item}" for item in descriptions])
                    if nav_raw.empty and not n.empty:
                        nav_raw = n
                    if holdings_raw.empty and not h.empty:
                        holdings_raw = h
        if not moneydj_url and (nav_raw.empty or holdings_raw.empty):
            with st.expander("已找到的網頁表格", expanded=True):
                for item in url_descriptions:
                    st.write(item)
            raise ValueError("未能同時辨識淨值表與持股表；請改貼直接資料網址，或下載後使用檔案上傳。")
        if not moneydj_url:
            nav_df = normalize_nav(nav_raw)
            holdings_df = normalize_holdings(holdings_raw)
            primary_funds = nav_df["fund"].dropna().unique().tolist()
except Exception as exc:
    st.error(f"資料格式無法讀取：{exc}")
    st.stop()

if source_mode == "網址分析":
    with st.expander("網址匯入結果"):
        st.success(f"已辨識 {len(nav_df):,} 筆淨值資料與 {len(holdings_df):,} 筆持股資料。")
        if peer_load_error:
            st.warning(f"同類基金暫時無法讀取，主基金仍可分析：{peer_load_error}")
        for item in url_descriptions:
            st.caption(item)

funds = sorted(set(nav_df["fund"]) & set(holdings_df["fund"]))
if not funds:
    st.error("淨值檔與持股檔沒有相同的基金名稱。")
    st.stop()

with st.container(border=True):
    with st.container(horizontal=True):
        selectable_funds = [item for item in primary_funds if item in funds] or funds
        fund = st.selectbox("分析基金", selectable_funds)
        fund_nav_all = nav_df[nav_df["fund"] == fund]
        min_date, max_date = fund_nav_all["date"].min().date(), fund_nav_all["date"].max().date()
        start_date = st.date_input("期初", value=max(min_date, date(max_date.year - 1, max_date.month, min(max_date.day, 28))), min_value=min_date, max_value=max_date)
        end_date = st.date_input("期末", value=max_date, min_value=min_date, max_value=max_date)

if start_date >= end_date:
    st.warning("期初必須早於期末。")
    st.stop()

fund_nav = fund_nav_all[(fund_nav_all["date"] >= pd.Timestamp(start_date)) & (fund_nav_all["date"] <= pd.Timestamp(end_date))].sort_values("date")
metrics = calculate_risk_metrics(fund_nav["nav"], risk_free)
changes = holding_changes(holdings_df, fund, start_date, end_date)
themes = exposure_table(changes, "theme")
sectors = exposure_table(changes, "sector")
peers = peer_metrics(nav_df, start_date, end_date, risk_free)
latest_size = fund_nav["fund_size"].dropna().iloc[-1] if "fund_size" in fund_nav and fund_nav["fund_size"].notna().any() else np.nan
latest_size_date = (
    pd.to_datetime(fund_nav["fund_size_date"], errors="coerce").dropna().iloc[-1]
    if "fund_size_date" in fund_nav and pd.to_datetime(fund_nav["fund_size_date"], errors="coerce").notna().any()
    else pd.NaT
)

with st.container(horizontal=True):
    st.metric("區間報酬", f"{metrics.total_return * 100:.2f}%", border=True, chart_data=fund_nav["nav"].tail(30).tolist())
    st.metric(
        "基金規模",
        "—" if pd.isna(latest_size) else f"{latest_size:,.2f} 億元",
        help="資料日期未知" if pd.isna(latest_size_date) else f"資料日期：{latest_size_date:%Y-%m-%d}",
        border=True,
    )
    st.metric("年化波動", f"{metrics.annualized_volatility * 100:.2f}%", border=True)
    st.metric("最大回撤", f"{metrics.max_drawdown * 100:.2f}%", border=True)
    st.metric("Sharpe", f"{metrics.sharpe:.2f}", border=True)
    st.metric("Sortino", f"{metrics.sortino:.2f}", border=True)

tabs = st.tabs(["總覽", "持股變化", "投資題材", "獲利與虧損", "同類基金比較", "產生報告"])

with tabs[0]:
    normalized = fund_nav.assign(累積報酬=(fund_nav["nav"] / fund_nav["nav"].iloc[0] - 1) * 100)
    chart = alt.Chart(normalized).mark_line(color="#2F80ED", strokeWidth=2.5).encode(
        x=alt.X("date:T", title="日期"), y=alt.Y("累積報酬:Q", title="累積報酬 %"),
        tooltip=[alt.Tooltip("date:T", title="日期"), alt.Tooltip("累積報酬:Q", format=".2f")],
    ).interactive()
    with st.container(border=True):
        st.subheader("區間淨值表現")
        st.altair_chart(chart)
    with st.container(horizontal=True):
        with st.container(border=True):
            st.subheader("題材曝險")
            st.bar_chart(themes.head(10), x="theme", y="期末權重")
        with st.container(border=True):
            st.subheader("產業曝險")
            st.bar_chart(sectors.head(10), x="sector", y="期末權重")

with tabs[1]:
    action = st.multiselect("篩選動作", ["新進", "加碼", "持平", "減碼", "出清"], default=["新進", "加碼", "減碼", "出清"])
    view = changes[changes["動作"].isin(action)]
    st.dataframe(view, hide_index=True, column_config={
        "期初權重": st.column_config.NumberColumn(format="%.2f%%"), "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
        "權重變化": st.column_config.NumberColumn(format="%+.2f%%"), "區間報酬": st.column_config.NumberColumn(format="%+.2f%%"),
    })

with tabs[2]:
    st.subheader("投資題材變化")
    st.dataframe(themes, hide_index=True)
    st.subheader("產業配置變化")
    st.dataframe(sectors, hide_index=True)

with tabs[3]:
    valid = changes.dropna(subset=["估計貢獻"])
    if valid.empty:
        st.info("目前未取得個股期初與期末市場價格，因此暫時無法計算獲利／虧損歸因；持股權重變化仍可正常查看。")
    else:
        industry = (
            valid.groupby("sector", as_index=False)
            .agg(持股檔數=("ticker", "nunique"), 期末權重=("期末權重", "sum"), 估計貢獻=("估計貢獻", "sum"))
        )
        gain_industry = industry[industry["估計貢獻"] > 0].sort_values("估計貢獻", ascending=False)
        loss_industry = industry[industry["估計貢獻"] < 0].sort_values("估計貢獻")
        st.subheader("產業損益歸因")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 獲利產業")
            st.dataframe(gain_industry, hide_index=True, column_config={
                "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
                "估計貢獻": st.column_config.NumberColumn("估計貢獻（百分點）", format="%+.2f"),
            })
        with c2:
            st.markdown("#### 虧損產業")
            st.dataframe(loss_industry, hide_index=True, column_config={
                "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
                "估計貢獻": st.column_config.NumberColumn("估計貢獻（百分點）", format="%+.2f"),
            })

        holding_columns = ["ticker", "name", "sector", "theme", "期初權重", "期末權重", "區間報酬", "估計貢獻", "動作"]
        st.subheader("個別持股損益歸因")
        c3, c4 = st.columns(2)
        holding_config = {
            "期初權重": st.column_config.NumberColumn(format="%.2f%%"),
            "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
            "區間報酬": st.column_config.NumberColumn(format="%+.2f%%"),
            "估計貢獻": st.column_config.NumberColumn("估計貢獻（百分點）", format="%+.2f"),
        }
        with c3:
            st.markdown("#### 獲利持股")
            st.dataframe(valid[valid["估計貢獻"] > 0].sort_values("估計貢獻", ascending=False)[holding_columns], hide_index=True, column_config=holding_config)
        with c4:
            st.markdown("#### 虧損持股")
            st.dataframe(valid[valid["估計貢獻"] < 0].sort_values("估計貢獻")[holding_columns], hide_index=True, column_config=holding_config)
    st.caption("估計貢獻＝期初與期末平均權重 × 個股區間報酬，未納入日內交易、現金及衍生工具。")

with tabs[4]:
    st.subheader("同類基金指標比較")
    comparison = peers.copy()
    if source_mode == "網址分析" and (not peer_url.strip() or peer_load_error):
        comparison = pd.concat([comparison, pd.DataFrame([{"基金": "—"}])], ignore_index=True)
        if peer_load_error:
            st.caption("同類基金資料暫時無法取得；比較欄位以「—」表示，主基金分析不受影響。")
        else:
            st.caption("尚未提供同類基金網址；同類基金欄位以「—」表示。")
    percent_cols = ["區間報酬", "年化報酬", "年化波動", "最大回撤", "上漲日占比"]
    ratio_cols = ["Sharpe", "Sortino"]
    for col in percent_cols:
        if col not in comparison:
            comparison[col] = np.nan
        comparison[col] = comparison[col].map(lambda value: "—" if pd.isna(value) else f"{value:+.2f}%")
    for col in ratio_cols:
        if col not in comparison:
            comparison[col] = np.nan
        comparison[col] = comparison[col].map(lambda value: "—" if pd.isna(value) else f"{value:.2f}")
    comparison["基金"] = comparison["基金"].fillna("—")
    st.dataframe(comparison, hide_index=True, width="stretch")

with tabs[5]:
    rank = peers.reset_index(drop=True).index[peers.reset_index(drop=True)["基金"].eq(fund)]
    rank_text = f"同類基金區間報酬排名第 {int(rank[0]) + 1} 名，共 {len(peers)} 檔。" if len(rank) else ""
    conclusion = (
        f"{fund}於分析期間報酬為{metrics.total_return * 100:.2f}%，最大回撤為{metrics.max_drawdown * 100:.2f}%，"
        f"風險調整後報酬 Sharpe 為{metrics.sharpe:.2f}。{rank_text}"
    )
    summary = {"conclusion": conclusion, "metrics": {
        "區間報酬": f"{metrics.total_return * 100:.2f}%", "年化報酬": f"{metrics.annualized_return * 100:.2f}%",
        "年化波動": f"{metrics.annualized_volatility * 100:.2f}%", "最大回撤": f"{metrics.max_drawdown * 100:.2f}%",
        "Sharpe": f"{metrics.sharpe:.2f}", "Sortino": f"{metrics.sortino:.2f}",
        "基金規模": "—" if pd.isna(latest_size) else f"{latest_size:,.1f} 億",
    }}
    st.write(conclusion)
    report = build_report(fund, f"{start_date} 至 {end_date}", summary, changes, themes, peers, notes, source)
    st.download_button("下載 Word 分析報告", report, file_name=f"{fund}_基金分析報告.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", icon=":material/download:", type="primary")

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

import fund_analysis as fa
from holdings_enhancement import driver_summary, install, theme_attribution

install(fa)

st.set_page_config(page_title="持股歸因與企業獲利", page_icon="📊", layout="wide")
st.title("持股歸因與企業獲利")
st.caption("從基金漲跌一路拆到題材、個股、經理人加減碼與企業獲利變化。估計貢獻為持股權重與個股區間報酬的近似歸因，不代表完整基金會計損益。")


@st.cache_data(ttl="6h", show_spinner=False)
def load_fund(url: str):
    return fa.load_moneydj_fund(url)


url = st.text_input("MoneyDJ 基金完整網址", placeholder="https://tcbbankfund.moneydj.com/...")
if not url.strip():
    st.info("貼上基金的 MoneyDJ 完整網址後即可分析。")
    st.stop()

try:
    with st.spinner("讀取基金、持股與市場資料…"):
        nav_df, holdings_df, descriptions = load_fund(url.strip())
except Exception as exc:
    st.error(f"基金資料讀取失敗：{exc}")
    st.stop()

funds = sorted(set(nav_df["fund"]) & set(holdings_df["fund"]))
if not funds:
    st.error("沒有找到可同時對應淨值與持股的基金。")
    st.stop()

fund = st.selectbox("分析基金", funds)
fund_nav = nav_df[nav_df["fund"] == fund].sort_values("date")
min_date = fund_nav["date"].min().date()
max_date = fund_nav["date"].max().date()
default_start = max(min_date, date(max_date.year - 1, max_date.month, min(max_date.day, 28)))

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("期初", default_start, min_value=min_date, max_value=max_date)
with c2:
    end_date = st.date_input("期末", max_date, min_value=min_date, max_value=max_date)
if start_date >= end_date:
    st.warning("期初必須早於期末。")
    st.stop()

with st.spinner("計算持股變化、價格歸因與企業獲利…"):
    changes = fa.holding_changes(holdings_df, fund, start_date, end_date)

if changes.empty:
    st.info("所選期間沒有足夠的持股快照可比較。")
    st.stop()

st.subheader("基金漲跌重點")
for sentence in driver_summary(changes):
    st.write(f"• {sentence}")

st.subheader("題材／市場貢獻")
attribution = theme_attribution(changes)
if attribution.empty:
    st.info("目前缺少足夠的個股價格，題材貢獻暫時無法估算。")
else:
    st.dataframe(
        attribution,
        hide_index=True,
        width="stretch",
        column_config={
            "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
            "權重變化": st.column_config.NumberColumn("權重變化（pp）", format="%+.2f"),
            "估計貢獻": st.column_config.NumberColumn("估計貢獻（pp）", format="%+.2f"),
        },
    )

st.subheader("持股變化與個股貢獻")
status_options = ["新增", "加碼", "持平", "減碼", "退出"]
market_options = sorted(changes["市場"].dropna().astype(str).unique()) if "市場" in changes else []
theme_options = sorted(changes["分類"].dropna().astype(str).unique()) if "分類" in changes else []
f1, f2, f3 = st.columns(3)
with f1:
    statuses = st.multiselect("狀態", status_options, default=status_options)
with f2:
    markets = st.multiselect("市場", market_options, default=market_options)
with f3:
    themes = st.multiselect("題材", theme_options, default=theme_options)

view = changes.copy()
if "狀態" in view:
    view = view[view["狀態"].isin(statuses)]
if market_options:
    view = view[view["市場"].isin(markets)]
if theme_options:
    view = view[view["分類"].isin(themes)]

columns = [c for c in ["name", "ticker", "市場", "分類", "期初權重", "期末權重", "權重變化", "狀態", "區間報酬", "估計貢獻"] if c in view]
st.dataframe(
    view[columns].sort_values("估計貢獻", ascending=False, na_position="last") if "估計貢獻" in view else view[columns],
    hide_index=True,
    width="stretch",
    column_config={
        "name": "持股",
        "ticker": "代碼",
        "期初權重": st.column_config.NumberColumn(format="%.2f%%"),
        "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
        "權重變化": st.column_config.NumberColumn("權重變化（pp）", format="%+.2f"),
        "區間報酬": st.column_config.NumberColumn(format="%+.2f%%"),
        "估計貢獻": st.column_config.NumberColumn("估計貢獻（pp）", format="%+.2f"),
    },
)

st.subheader("企業獲利變化")
earnings_cols = [c for c in ["name", "ticker", "市場", "分類", "狀態", "期末權重", "最新財報期", "營收成長%", "淨利成長%"] if c in changes]
earnings = changes[earnings_cols].copy()
coverage_cols = [c for c in ["營收成長%", "淨利成長%"] if c in earnings]
if not coverage_cols or earnings[coverage_cols].notna().any(axis=None) is False:
    st.info("目前資料源沒有回傳足夠的企業季報資料；持股與價格歸因仍可正常使用。")
else:
    st.dataframe(
        earnings.sort_values("期末權重", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "name": "公司",
            "ticker": "代碼",
            "期末權重": st.column_config.NumberColumn(format="%.2f%%"),
            "營收成長%": st.column_config.NumberColumn("營收成長", format="%+.2f%%"),
            "淨利成長%": st.column_config.NumberColumn("淨利成長", format="%+.2f%%"),
        },
    )
    st.caption("企業獲利資料取自可取得的公開季報；缺值表示資料源未提供或無法可靠計算。")

with st.expander("資料辨識結果"):
    for item in descriptions:
        st.caption(item)

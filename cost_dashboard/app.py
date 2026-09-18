import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="台股成本儀表板",page_icon="📊",layout="wide")
st.title("📊 台股成本・籌碼儀表板")
st.caption("成本為成交/分點資料估算；訊號僅供研究，不構成投資建議。")

def weighted_cost(df):
    d=df.dropna(subset=["price","qty"])
    q=d["qty"].abs()
    return np.average(d["price"],weights=q) if q.sum() else np.nan

def signal(px,cost,flow=0):
    if pd.isna(px) or pd.isna(cost): return "資料不足"
    gap=(px/cost-1)*100
    if gap<=-5 and flow>0:return "🟢 成本下方＋買超：觀察買入"
    if gap>=12 and flow<0:return "🔴 成本上方＋賣超：留意減碼"
    if abs(gap)<=2:return "🟡 接近估算成本"
    return "⚪ 中性"

with st.sidebar:
    symbol=st.text_input("台股代號","3189")
    current=st.number_input("目前股價",min_value=0.0,value=0.0,step=0.5)

tabs=st.tabs(["🏠 總覽","🏦 分點成本","🌍 外資追蹤","📈 期貨市場","🇺🇸 Pelosi","📢 重大訊息"])
with tabs[0]:
    st.subheader(f"{symbol} 成本總覽")
    st.info("上傳分點 CSV 後計算 5/10/20/60 日加權成本、成本乖離與觀察訊號。")
with tabs[1]:
    f=st.file_uploader("CSV：date, broker, buy, sell, price, qty",type="csv",key="branch")
    if f:
        df=pd.read_csv(f);df.columns=[c.strip().lower() for c in df.columns]
        df["date"]=pd.to_datetime(df["date"],errors="coerce")
        for c in ["buy","sell","price","qty"]: df[c]=pd.to_numeric(df[c],errors="coerce")
        df["net"]=df["buy"]-df["sell"]; end=df["date"].max()
        cols=st.columns(4); costs={}
        for i,n in enumerate([5,10,20,60]):
            costs[n]=weighted_cost(df[df["date"]>=end-pd.Timedelta(days=n-1)])
            cols[i].metric(f"{n}日估算成本",f"{costs[n]:.2f}")
        st.success(signal(current,costs[20],df.net.sum()) if current else "輸入現價後顯示訊號")
        st.dataframe(df.groupby("broker",as_index=False)["net"].sum().sort_values("net",ascending=False).head(10),use_container_width=True)
with tabs[2]:
    f=st.file_uploader("外資分點 CSV",type="csv",key="foreign")
    if f:
        d=pd.read_csv(f);d.columns=[c.strip().lower() for c in d.columns]
        d["net"]=pd.to_numeric(d.buy,errors="coerce")-pd.to_numeric(d.sell,errors="coerce")
        x=d[d.broker.astype(str).str.contains(r"摩根|jpm|merrill|美林|goldman|高盛",case=False,regex=True)]
        st.dataframe(x,use_container_width=True);st.metric("三大外資淨買賣",f"{x.net.sum():,.0f}")
with tabs[3]:
    f=st.file_uploader("期貨法人 CSV",type="csv")
    if f:
        d=pd.read_csv(f);st.dataframe(d,use_container_width=True)
        if len(d.select_dtypes(include=np.number).columns):st.line_chart(d.select_dtypes(include=np.number))
with tabs[4]:
    st.caption("依公開揭露交易金額區間估算；選擇權揭露金額不等同股票成本。")
    f=st.file_uploader("Pelosi CSV：ticker,date,type,amount_min,amount_max,shares",type="csv")
    if f:
        d=pd.read_csv(f)
        d["amount_mid"]=(pd.to_numeric(d.amount_min,errors="coerce")+pd.to_numeric(d.amount_max,errors="coerce"))/2
        if "shares" in d:d["est_cost"]=d.amount_mid/pd.to_numeric(d.shares,errors="coerce")
        st.dataframe(d,use_container_width=True)
    st.link_button("Pelosi Stock Tracker","https://nancypelosistocktracker.org/zh-TW")
with tabs[5]:
    st.write("官方重大訊息入口；自動抓取版下一階段接入。")
    st.link_button("MOPS 公開資訊觀測站","https://mopsov.twse.com.tw/mops/web/index")

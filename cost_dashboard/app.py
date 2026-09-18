import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import StringIO
from datetime import datetime

st.set_page_config(page_title="台股成本儀表板",page_icon="📊",layout="wide")
st.title("📊 台股成本・籌碼儀表板")
st.caption("輸入股票代號自動更新行情與可取得的分點資料；成本/訊號為研究估算，不構成投資建議。")

HEADERS={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36"}

@st.cache_data(ttl=300)
def stock_data(symbol):
    # 直接使用 Yahoo Finance chart endpoint，避免 Streamlit Cloud 額外 yfinance 套件依賴
    last_err=None
    for suffix in [".TW",".TWO"]:
        ticker=symbol+suffix
        try:
            url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            params={"range":"6mo","interval":"1d","events":"history","includeAdjustedClose":"true"}
            res=requests.get(url,params=params,headers=HEADERS,timeout=15)
            res.raise_for_status()
            obj=res.json()["chart"]["result"]
            if not obj: continue
            x=obj[0]; q=x["indicators"]["quote"][0]
            h=pd.DataFrame({"Close":q["close"],"Volume":q["volume"]},
                index=pd.to_datetime(x["timestamp"],unit="s"))
            h=h.dropna(subset=["Close"])
            if not h.empty:
                return ticker,h,float(h["Close"].iloc[-1]),None
        except Exception as e:
            last_err=str(e)
    return None,pd.DataFrame(),np.nan,last_err or "查無行情"

@st.cache_data(ttl=900)
def wantgoo_branch(symbol):
    # WantGoo 個股分點頁。公開 HTML 若因會員權限遮蔽數值，會回傳狀態而非假資料。
    urls=[
      f"https://www.wantgoo.com/stock/{symbol}/major-investors/branch-buysell",
      f"https://www.wantgoo.com/stock/etf/{symbol}/major-investors/branch-buysell"
    ]
    for url in urls:
        try:
            r=requests.get(url,headers=HEADERS,timeout=15); r.raise_for_status()
            tables=pd.read_html(StringIO(r.text))
            candidates=[]
            for x in tables:
                cols=" ".join(map(str,x.columns))
                if "券商" in cols and ("買" in cols or "賣" in cols):
                    candidates.append(x)
            if candidates:
                d=max(candidates,key=len).copy()
                d.columns=[str(c[-1] if isinstance(c,tuple) else c).strip() for c in d.columns]
                return d,url,("WantGoo 公開頁會遮蔽部分買賣張數；目前僅顯示公開可讀欄位。" if d.astype(str).apply(lambda c: c.str.contains(r"\\*\\*\\*",regex=True).any()).any() else None)
            if "登入" in r.text or "會員" in r.text:
                return pd.DataFrame(),url,"WantGoo 此個股完整分點數值需要會員登入，公開頁無法取得完整數字。"
        except Exception as e:last=str(e)
    return pd.DataFrame(),urls[0],locals().get("last","無法讀取 WantGoo")

def market_costs(h):
    out={}
    for n in [5,10,20,60]:
        d=h.tail(n)
        out[n]=np.average(d["Close"],weights=d["Volume"]) if len(d) and d["Volume"].sum()>0 else np.nan
    return out

def find_col(cols,keys):
    for c in cols:
        if any(k in str(c) for k in keys): return c
    return None

def clean_num(s):
    return pd.to_numeric(s.astype(str).str.replace(",","",regex=False).str.replace("*","",regex=False),errors="coerce")

with st.sidebar:
    symbol=st.text_input("台股代號","3189").strip()
    run=st.button("🔎 查詢 / 更新",type="primary",use_container_width=True)
    st.caption("行情快取 5 分鐘；分點快取 15 分鐘。")

ticker,h,current,price_err=stock_data(symbol)
branch,branch_url,branch_err=wantgoo_branch(symbol)
costs=market_costs(h) if not h.empty else {}

tabs=st.tabs(["🏠 總覽","🏦 分點成本","🌍 外資追蹤","📈 期貨市場","🇺🇸 Pelosi","📢 重大訊息"])
with tabs[0]:
    st.subheader(f"{symbol} 自動更新總覽")
    if not h.empty:
        prev=float(h["Close"].iloc[-2]) if len(h)>1 else current
        c1,c2,c3=st.columns(3)
        c1.metric("最新收盤",f"{current:,.2f}",f"{current-prev:,.2f}")
        c2.metric("資料日期",str(h.index[-1].date()))
        c3.metric("Yahoo 代號",ticker)
        st.line_chart(h["Close"])
        cols=st.columns(4)
        for i,n in enumerate([5,10,20,60]):
            v=costs[n]; gap=(current/v-1)*100 if v else np.nan
            cols[i].metric(f"{n}日量價估算成本",f"{v:,.2f}",f"現價 {gap:+.1f}%")
    else: st.error("行情取得失敗："+str(price_err))

with tabs[1]:
    st.subheader("WantGoo 券商分點")
    st.caption("來源：玩股網個股券商分點頁；網站若要求登入，程式不繞過會員限制。")
    if not branch.empty:
        st.dataframe(branch,use_container_width=True,hide_index=True)
        broker=find_col(branch.columns,["券商"])
        buy=find_col(branch.columns,["買張","買進"])
        sell=find_col(branch.columns,["賣張","賣出"])
        avg=find_col(branch.columns,["均價"])
        if broker and buy and sell:
            x=branch.copy(); x["_buy"]=clean_num(x[buy]);x["_sell"]=clean_num(x[sell]);x["_net"]=x["_buy"]-x["_sell"]
            st.subheader("買超 Top 10");st.dataframe(x.sort_values("_net",ascending=False).head(10)[[broker,buy,sell,"_net"]],use_container_width=True,hide_index=True)
            if avg:
                x["_avg"]=clean_num(x[avg])
                st.metric("Top 分點加權均價",f"{np.average(x['_avg'].dropna(),weights=(x.loc[x['_avg'].notna(),'_buy']+x.loc[x['_avg'].notna(),'_sell']).clip(lower=1)):,.2f}" if x["_avg"].notna().any() else "—")
    else:
        st.warning(branch_err or "目前未取得分點表格")
    st.link_button("開啟此股 WantGoo 分點頁",branch_url)

with tabs[2]:
    st.subheader("摩根／美林／高盛自動追蹤")
    if not branch.empty:
        broker=find_col(branch.columns,["券商"])
        if broker:
            foreign=branch[branch[broker].astype(str).str.contains(r"摩根|JPM|美林|Merrill|高盛|Goldman",case=False,regex=True)]
            if len(foreign):st.dataframe(foreign,use_container_width=True,hide_index=True)
            else:st.info("目前公開表格中未找到摩根／美林／高盛；可能不在排行内或數值受會員權限限制。")
    else: st.warning(branch_err or "分點資料目前不可用")

with tabs[3]:
    st.subheader("期貨市場")
    st.info("下一資料源：TAIFEX 官方三大法人、未平倉與台指期資料。此頁不再要求 CSV。")
    st.link_button("TAIFEX 官方資料","https://www.taifex.com.tw/")

with tabs[4]:
    st.subheader("Nancy Pelosi 公開交易")
    st.info("此頁將接公開揭露資料並估算申報區間成本；不再要求 CSV。")
    st.link_button("Pelosi Stock Tracker","https://nancypelosistocktracker.org/zh-TW")

with tabs[5]:
    st.subheader("台股重大訊息")
    st.info("此頁將接 MOPS 公開資訊觀測站；不再要求 CSV。")
    st.link_button("MOPS 公開資訊觀測站","https://mopsov.twse.com.tw/mops/web/index")

st.caption("最後重新執行："+datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

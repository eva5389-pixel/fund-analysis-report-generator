import streamlit as st
import pandas as pd
import numpy as np
import requests
import re
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

@st.cache_data(ttl=900)
def fubon_stock_brokers(symbol, period=1):
    """富邦 eBrokerDJ / MoneyDJ 個股主力進出公開頁。"""
    suffix={1:"",5:"_5",20:"_20",60:"_60"}.get(int(period),"")
    url=f"https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco_{symbol}{suffix}.djhtm"
    try:
        r=requests.get(url,headers=HEADERS,timeout=15)
        r.raise_for_status()
        r.encoding=r.apparent_encoding
        tables=pd.read_html(StringIO(r.text))
        rows=[]
        for t in tables:
            # flattened table text is robust to MoneyDJ's paired buy/sell layout
            for _,rr in t.iterrows():
                vals=[str(x).strip() for x in rr.tolist()]
                if len(vals)>=10:
                    rows.append(vals)
        # Prefer parsing page text directly because the table is two broker lists side-by-side.
        from bs4 import BeautifulSoup
        txt=BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)
        return txt,url,None
    except Exception as e:
        return "",url,str(e)

def parse_fubon_brokers(text):
    names=["台灣摩根士丹利","摩根大通","美商高盛","美林","新加坡商瑞銀","花旗環球"]
    out=[]
    # MoneyDJ text sequence: broker buy sell net ratio. Capture signed/unsigned integer fields.
    for name in names:
        m=re.search(re.escape(name)+r"\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)%",text)
        if m:
            buy=int(m.group(1).replace(",","")); sell=int(m.group(2).replace(",","")); shown=int(m.group(3).replace(",",""))
            net=buy-sell
            out.append({"主要券商":name,"買進張數":buy,"賣出張數":sell,"淨買超":net,"成交占比%":float(m.group(4)),
                        "隔日沖判斷":daytrade_flag(buy,sell,net)})
        else:
            out.append({"主要券商":name,"買進張數":np.nan,"賣出張數":np.nan,"淨買超":np.nan,"成交占比%":np.nan,"隔日沖判斷":"本期未進榜"})
    return pd.DataFrame(out)

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


def daytrade_flag(buy,sell,net):
    """僅以當期分點買賣結構判斷疑似隔日沖，不宣稱實際交易策略。"""
    if pd.isna(buy) or pd.isna(sell): return "資料不足"
    total=buy+sell
    if total<=0: return "—"
    turnover=min(buy,sell)/max(buy,sell) if max(buy,sell)>0 else 0
    net_ratio=abs(net)/total
    if total>=100 and turnover>=0.80 and net_ratio<=0.10:
        return "🔴 高疑似隔日沖"
    if total>=50 and turnover>=0.60 and net_ratio<=0.25:
        return "🟠 疑似短線/隔日沖"
    return "⚪ 未見明顯隔日沖特徵"

with st.sidebar:
    symbol=st.text_input("台股代號","3189").strip()
    run=st.button("🔎 查詢 / 更新",type="primary",use_container_width=True)
    st.caption("行情快取 5 分鐘；分點快取 15 分鐘。")

ticker,h,current,price_err=stock_data(symbol)
branch=pd.DataFrame()
branch_url=f"https://www.wantgoo.com/stock/etf/{symbol}/major-investors/branch-buysell"
branch_err="WantGoo 僅提供瀏覽器登入後查閱；Streamlit 不直接爬取登入資料。"

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
    st.subheader("主要券商成本／籌碼")
    period=st.segmented_control("期間",[1,5,20,60],default=5,format_func=lambda x:f"{x}日",key="broker_period")
    text_data,fubon_url,fubon_err=fubon_stock_brokers(symbol,period)
    if text_data:
        broker_df=parse_fubon_brokers(text_data)
        st.dataframe(broker_df,use_container_width=True,hide_index=True)
        st.caption("此公開頁提供各券商買進、賣出、淨買賣超與成交占比；頁面顯示的『平均買超/賣超成本』是排行合計成本，不是每一家券商的個別成本，因此不把它誤標成單一券商成本。")
        # show aggregate costs if present
        mb=re.search(r"平均買超成本\s*([\d.]+)",text_data)
        ms=re.search(r"平均賣超成本\s*([\d.]+)",text_data)
        c1,c2=st.columns(2)
        c1.metric("排行平均買超成本",mb.group(1) if mb else "—")
        c2.metric("排行平均賣超成本",ms.group(1) if ms else "—")
    else:
        st.warning("富邦個股分點資料讀取失敗："+str(fubon_err))
    st.link_button("富邦 eBrokerDJ 個股分點原始頁",fubon_url)
    st.link_button("WantGoo 此股分點頁（登入後交叉查看）",branch_url)

with tabs[2]:
    st.subheader("外資券商追蹤")
    st.caption("自動追蹤摩根士丹利、摩根大通、美林、高盛、瑞銀、花旗環球。")
    foreign_period=st.segmented_control("外資期間",[1,5,20,60],default=5,format_func=lambda x:f"{x}日",key="foreign_period")
    ft,fu,fe=fubon_stock_brokers(symbol,foreign_period)
    if ft:
        fd=parse_fubon_brokers(ft)
        st.dataframe(fd,use_container_width=True,hide_index=True)
        valid=fd["淨買超"].dropna()
        if len(valid):
            st.metric("六大外資分點合計淨買賣",f"{valid.sum():,.0f} 張")
    else:
        st.warning("外資分點資料讀取失敗："+str(fe))
    st.link_button("查看資料原頁",fu)

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

import streamlit as st
import pandas as pd
import numpy as np
import requests
import re
from io import StringIO
from bs4 import BeautifulSoup
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
    """富邦 eBrokerDJ / MoneyDJ 個股主力進出公開頁；純 BeautifulSoup，不依賴 lxml。"""
    suffix={1:"",5:"_5",20:"_20",60:"_60"}.get(int(period),"")
    url=f"https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco_{symbol}{suffix}.djhtm"
    try:
        r=requests.get(url,headers=HEADERS,timeout=15)
        r.raise_for_status()
        r.encoding=r.apparent_encoding
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

@st.cache_data(ttl=900)
def taifex_institutional():
    url="https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
    try:
        r=requests.get(url,headers=HEADERS,timeout=20); r.raise_for_status()
        d=pd.DataFrame(r.json())
        return d,url,None
    except Exception as e: return pd.DataFrame(),url,str(e)

@st.cache_data(ttl=900)
def twse_material(symbol):
    urls=[
      "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
      "https://openapi.twse.com.tw/v1/opendata/t187ap04_O"
    ]
    frames=[]; errs=[]
    for url in urls:
        try:
            r=requests.get(url,headers=HEADERS,timeout=20); r.raise_for_status()
            x=pd.DataFrame(r.json())
            if not x.empty:
                codecol=next((c for c in x.columns if "公司代號" in str(c)),None)
                if codecol: x=x[x[codecol].astype(str).str.strip()==str(symbol)]
                if not x.empty: frames.append(x)
        except Exception as e: errs.append(str(e))
    return (pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()),urls[0],"; ".join(errs) if errs and not frames else None

def numeric_col(df, words):
    for c in df.columns:
        if all(w in str(c) for w in words):
            return c
    return None

@st.cache_data(ttl=1800)
def pelosi_public():
    url="https://nancypelosistocktracker.org/zh-TW"
    try:
        r=requests.get(url,headers=HEADERS,timeout=20); r.raise_for_status()
        soup=BeautifulSoup(r.text,"html.parser")
        rows=[]
        for tr in soup.select("table tr"):
            cells=[x.get_text(" ",strip=True) for x in tr.select("th,td")]
            if len(cells)>=3: rows.append(cells)
        if len(rows)>1:
            width=max(map(len,rows)); rows=[x+[""]*(width-len(x)) for x in rows]
            return pd.DataFrame(rows[1:],columns=rows[0]),url,None
        return pd.DataFrame(),url,"公開追蹤頁為動態載入，伺服器 HTML 沒有交易表格。"
    except Exception as e: return pd.DataFrame(),url,str(e)

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
        chart_df=broker_df.dropna(subset=["淨買超"]).set_index("主要券商")
        if not chart_df.empty:
            st.markdown("#### 六大外資券商淨買賣超")
            st.bar_chart(chart_df["淨買超"],horizontal=True)
            st.markdown("#### 買進 vs 賣出")
            st.bar_chart(chart_df[["買進張數","賣出張數"]],horizontal=True)
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
        fchart=fd.dropna(subset=["淨買超"]).set_index("主要券商")
        if not fchart.empty:
            st.bar_chart(fchart["淨買超"],horizontal=True)
        valid=fd["淨買超"].dropna()
        if len(valid):
            st.metric("六大外資分點合計淨買賣",f"{valid.sum():,.0f} 張")
    else:
        st.warning("外資分點資料讀取失敗："+str(fe))
    st.link_button("查看資料原頁",fu)

with tabs[3]:
    st.subheader("期貨市場")
    st.caption("TAIFEX 三大法人資料只能觀察法人合計部位，無法直接辨識每一口是避險或方向交易；下方採『現貨－期貨對照』做研究性推估。")
    td,tu,te=taifex_institutional()
    if not td.empty:
        # Flexible column discovery across TAIFEX OpenAPI naming variants
        cols=list(td.columns)
        product=next((c for c in cols if "商品" in str(c)),None)
        ident=next((c for c in cols if "身份" in str(c) or "身分" in str(c)),None)
        datec=next((c for c in cols if "日期" in str(c)),None)
        oi_net=next((c for c in cols if "未平倉" in str(c) and ("淨" in str(c) or "多空" in str(c)) and ("口" in str(c) or "數" in str(c))),None)
        long_oi=next((c for c in cols if "未平倉" in str(c) and "多方" in str(c) and ("口" in str(c) or "數" in str(c))),None)
        short_oi=next((c for c in cols if "未平倉" in str(c) and "空方" in str(c) and ("口" in str(c) or "數" in str(c))),None)
        tx=td.copy()
        if product:
            mask=tx[product].astype(str).str.contains("臺股期貨|台股期貨",regex=True,na=False)
            if mask.any(): tx=tx[mask]
        for c in [oi_net,long_oi,short_oi]:
            if c: tx[c]=pd.to_numeric(tx[c].astype(str).str.replace(",","",regex=False),errors="coerce")
        if oi_net is None and long_oi and short_oi:
            tx["_淨未平倉"]=tx[long_oi]-tx[short_oi]; oi_net="_淨未平倉"

        show=[c for c in [datec,product,ident,long_oi,short_oi,oi_net] if c]
        st.dataframe(tx[show] if show else tx,use_container_width=True,hide_index=True)

        if oi_net and tx[oi_net].notna().any():
            if ident:
                cc=tx.groupby(ident,as_index=False)[oi_net].sum()
            else:
                ident="法人"
                cc=pd.DataFrame({ident:["三大法人合計"],oi_net:[tx[oi_net].sum()]})
            st.markdown("#### 三大法人臺股期貨淨未平倉")
            plot_df=cc[[ident,oi_net]].dropna().copy()
            plot_df[oi_net]=pd.to_numeric(plot_df[oi_net],errors="coerce").fillna(0)
            st.bar_chart(plot_df,x=ident,y=oi_net,horizontal=True,use_container_width=True)

            # Heuristic classification: do not assert true intent.
            rows=[]
            for _,r in cc.iterrows():
                who=str(r[ident]); net=float(r[oi_net])
                if who=="投信" and net>0:
                    label="🟠 較可能含避險／配置調整"
                    reason="投信期貨需和基金現貨曝險一起看；單靠期貨多空不能確認意圖"
                elif who=="外資" and net<0:
                    label="🟠 可能混合避險＋方向部位"
                    reason="外資是多家機構合計，空單可能對沖現貨，也可能是方向交易"
                elif who=="自營商":
                    label="🟡 可能含造市／套利／避險"
                    reason="自營商包含期貨及證券自營商，常同時存在造市、套利與避險需求"
                else:
                    label="⚪ 無法僅由三大法人資料判定"
                    reason="需要搭配現貨買賣超、選擇權、跨月價差與部位變化"
                rows.append({"法人":who,"淨未平倉口數":net,"部位性質推估":label,"判讀依據":reason})
            judge=pd.DataFrame(rows)
            st.markdown("#### 避險／方向部位推估")
            st.dataframe(judge,use_container_width=True,hide_index=True)
            st.caption("⚠️ 這是推估，不是 TAIFEX 對部位用途的官方分類。期交所也明確提醒：三大法人數字是眾多機構合計互抵結果，不能代表單一法人或整類法人的交易策略。")

            st.markdown("#### 如何判斷")
            st.markdown("**偏避險：** 現貨大量淨買，同期台指期空單增加；或自營商期貨與選擇權呈現明顯對沖結構。\n\n**偏方向：** 現貨與期貨方向一致，且淨未平倉連續增加；例如現貨賣超同時期貨空單持續增加。\n\n**混合／無法判定：** 現貨與期貨訊號不一致、或只有單日資料。")
    else:
        st.warning("TAIFEX 官方資料暫時讀取失敗："+str(te))
    st.link_button("TAIFEX OpenAPI",tu)

with tabs[4]:
    st.subheader("Nancy Pelosi 公開交易")
    pdx,pu,pe=pelosi_public()
    if not pdx.empty:
        st.dataframe(pdx,use_container_width=True,hide_index=True)
        st.caption("直接顯示公開追蹤頁可讀取的交易表格；申報金額通常是區間，不把區間中點當成精確成交成本。")
        # 若頁面存在可辨識 ticker 欄，顯示交易筆數圖
        tc=next((c for c in pdx.columns if any(k in str(c).lower() for k in ["ticker","股票","代號"])),None)
        if tc:
            cnt=pdx[tc].astype(str).value_counts().head(15)
            st.markdown("#### 公開交易筆數")
            st.bar_chart(cnt,horizontal=True)
    else:
        st.warning("Pelosi 追蹤頁目前無法由 Streamlit 伺服器直接取得表格："+str(pe))
        st.caption("這一頁不會捏造交易資料；等可讀的公開揭露來源接通後才會畫圖。")
    st.link_button("Pelosi Stock Tracker",pu)

with tabs[5]:
    st.subheader("台股重大訊息")
    md,mu,me=twse_material(symbol)
    if not md.empty:
        st.caption(f"直接顯示 {symbol} 的 TWSE OpenAPI 每日重大訊息")
        preferred=[c for c in md.columns if any(k in str(c) for k in ["日期","時間","公司代號","公司名稱","主旨","說明"])]
        st.dataframe(md[preferred] if preferred else md,use_container_width=True,hide_index=True)
        dc=next((c for c in md.columns if "日期" in str(c)),None)
        if dc:
            counts=md[dc].astype(str).value_counts().sort_index()
            st.markdown("#### 重大訊息發布筆數")
            st.bar_chart(counts)
        st.metric("目前取得重大訊息",f"{len(md)} 筆")
    else:
        st.info(f"目前官方 OpenAPI 沒有取得 {symbol} 的重大訊息。"+((" "+str(me)) if me else ""))
    st.link_button("TWSE OpenAPI 重大訊息",mu)

st.caption("最後重新執行："+datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

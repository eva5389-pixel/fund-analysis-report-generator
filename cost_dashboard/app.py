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

@st.cache_data(ttl=900)
def fubon_branch(branch_id):
    """讀取富邦 eBrokerDJ 公開分點頁；branch_id 例如 5660。"""
    url=f"https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm?a={branch_id}&b={branch_id}"
    try:
        r=requests.get(url,headers=HEADERS,timeout=15)
        r.raise_for_status()
        r.encoding=r.apparent_encoding
        tables=pd.read_html(StringIO(r.text))
        tables=[x for x in tables if len(x)>=2]
        if tables:
            return max(tables,key=lambda x: x.size),url,None
        return pd.DataFrame(),url,"富邦分點頁目前沒有可解析表格"
    except Exception as e:
        return pd.DataFrame(),url,str(e)

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
    fubon_id=st.text_input("富邦分點代號（選填）","",help="例如你提供的 5660；用來查該券商分點公開資料")
    run=st.button("🔎 查詢 / 更新",type="primary",use_container_width=True)
    st.caption("行情快取 5 分鐘；分點快取 15 分鐘。")

ticker,h,current,price_err=stock_data(symbol)
branch=pd.DataFrame()
branch_url=f"https://www.wantgoo.com/stock/etf/{symbol}/major-investors/branch-buysell"
branch_err="WantGoo 僅提供瀏覽器登入後查閱；Streamlit 不直接爬取登入資料。"
fubon_df,fubon_url,fubon_err=fubon_branch(fubon_id) if fubon_id else (pd.DataFrame(),"",None)
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
    st.subheader("主要券商成本")
    period=st.segmented_control("成本期間",[1,5,20,60],default=5,format_func=lambda x:f"{x}日")
    st.caption("固定追蹤摩根士丹利、摩根大通、美林、高盛、瑞銀、花旗環球；另顯示公開資料中的主要分點。隔日沖為買賣結構推估，不代表該券商實際策略。")
    core=["摩根士丹利","摩根大通","美林","高盛","瑞銀","花旗環球"]
    if fubon_id and not fubon_df.empty:
        d=fubon_df.copy()
        d.columns=[str(c[-1] if isinstance(c,tuple) else c).strip() for c in d.columns]
        broker=find_col(d.columns,["券商","分點"])
        buy=find_col(d.columns,["買進","買張","買"])
        sell=find_col(d.columns,["賣出","賣張","賣"])
        avg_buy=find_col(d.columns,["買均","買進均價","平均買"])
        avg_sell=find_col(d.columns,["賣均","賣出均價","平均賣"])
        if broker:
            out=pd.DataFrame({"主要券商":core})
            rows=[]
            for name in core:
                hit=d[d[broker].astype(str).str.contains(name,regex=False)]
                row={"主要券商":name,"期間":f"{period}日"}
                if len(hit):
                    r=hit.iloc[0]
                    bv=float(clean_num(pd.Series([r[buy]])).iloc[0]) if buy else np.nan
                    sv=float(clean_num(pd.Series([r[sell]])).iloc[0]) if sell else np.nan
                    bc=float(clean_num(pd.Series([r[avg_buy]])).iloc[0]) if avg_buy else np.nan
                    sc=float(clean_num(pd.Series([r[avg_sell]])).iloc[0]) if avg_sell else np.nan
                    row.update({"買進張數":bv,"賣出張數":sv,"淨買超":bv-sv if pd.notna(bv) and pd.notna(sv) else np.nan,
                                "平均買進成本":bc,"平均賣出價":sc,
                                "現價距成本%":(current/bc-1)*100 if pd.notna(bc) and bc and pd.notna(current) else np.nan,
                                "隔日沖判斷":daytrade_flag(bv,sv,bv-sv) if pd.notna(bv) and pd.notna(sv) else "資料不足"})
                rows.append(row)
            cost_table=pd.DataFrame(rows)
            st.dataframe(cost_table,use_container_width=True,hide_index=True,
                column_config={"平均買進成本":st.column_config.NumberColumn(format="%.2f"),
                               "平均賣出價":st.column_config.NumberColumn(format="%.2f"),
                               "現價距成本%":st.column_config.NumberColumn(format="%.2f%%")})
            if buy and sell:
                x=d.copy();x["_buy"]=clean_num(x[buy]);x["_sell"]=clean_num(x[sell]);x["_net"]=x["_buy"]-x["_sell"]
                x["隔日沖判斷"]=[daytrade_flag(bv,sv,nv) for bv,sv,nv in zip(x["_buy"],x["_sell"],x["_net"])]
                st.subheader("其他主要買超分點")
                show=[c for c in [broker,buy,sell,avg_buy,avg_sell] if c]+["隔日沖判斷"]
                st.dataframe(x.sort_values("_net",ascending=False).head(10)[show],use_container_width=True,hide_index=True)
        else:
            st.warning("富邦表格已取得，但目前無法辨識券商名稱欄位。")
    else:
        st.info("目前主要券商成本需要富邦分點資料。左側輸入可用的富邦分點代號後會自動計算；下一版再把股票代號直接對應到分點排行。")
    if fubon_id:
        st.link_button("富邦 eBrokerDJ 原始資料",fubon_url)
    st.link_button("WantGoo 此股分點頁（登入後交叉查看）",branch_url)

with tabs[2]:
    st.subheader("摩根／美林／高盛追蹤")\n    st.caption("不再以 WantGoo 伺服器爬取作為唯一來源；避免 403 被誤顯示成資料為零。")
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

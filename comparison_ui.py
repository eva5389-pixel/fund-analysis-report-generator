from hashlib import sha256
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from risk_metadata import load_risk
from auto_metadata import infer_metadata, fetch_fx
from fund_analysis import moneydj_fund_id, read_table
from moneydj_comparison import load_comparison_fund, holding_identity
from comparison_engine import (BASIS, CURRENCIES, METHOD, common_period, compare, conclusions, demo_data,
                               endpoint_rates, read_fx, read_nav, report_html, theme_comparison)


@st.cache_data(ttl=3600, max_entries=30, show_spinner=False)
def load_comparison_url(url):
    return load_comparison_fund(url)


@st.cache_data(ttl=3600, max_entries=50, show_spinner=False)
def load_auto_fx(currencies, start, end):
    return fetch_fx(currencies, start, end)


@st.cache_data(ttl=3600, max_entries=50, show_spinner=False)
def cached_risk(url):
    return load_risk(url)


def _nearest_return(series: pd.Series, months: int):
    s = pd.Series(series).dropna()
    if len(s) < 2:
        return np.nan
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    target = s.index[-1] - pd.DateOffset(months=months)
    eligible = s[s.index <= target]
    if eligible.empty:
        return np.nan
    start_value, end_value = float(eligible.iloc[-1]), float(s.iloc[-1])
    return (end_value / start_value - 1) * 100 if start_value > 0 else np.nan


def _first_finite(frame: pd.DataFrame, column: str):
    if column not in frame:
        return np.nan
    values = pd.to_numeric(frame[column], errors='coerce').dropna()
    return float(values.iloc[-1]) if not values.empty else np.nan


def _fund_screen_metrics(nav: pd.DataFrame, funds, risk_free: float = 0.015) -> pd.DataFrame:
    rows = []
    for fund in funds:
        frame = nav[nav.fund == fund].sort_values('date').dropna(subset=['date', 'nav'])
        s = frame.set_index('date').nav.astype(float)
        daily = s.pct_change().dropna()
        calculated_sharpe = np.nan
        if len(daily) >= 20 and daily.std(ddof=1) > 0:
            calculated_sharpe = ((daily.mean() - risk_free / 252) / daily.std(ddof=1)) * np.sqrt(252)
        published_sharpe = _first_finite(frame, 'moneydj_sharpe')
        published_beta = _first_finite(frame, 'moneydj_beta')
        values = {}
        for months, key, source_col in [(1, '1M %', 'moneydj_1m'), (3, '3M %', 'moneydj_3m'), (6, '6M %', 'moneydj_6m')]:
            published = _first_finite(frame, source_col)
            values[key] = published if np.isfinite(published) else _nearest_return(s, months)
        rows.append({'基金': fund,
                     'Sharpe': published_sharpe if np.isfinite(published_sharpe) else calculated_sharpe,
                     'Beta': published_beta,
                     **values})
    return pd.DataFrame(rows)


def _attach_beta(metrics: pd.DataFrame, nav: pd.DataFrame, benchmark_name: str | None) -> pd.DataFrame:
    result = metrics.copy()
    if not benchmark_name or benchmark_name not in set(nav.fund):
        return result
    bm = nav[nav.fund == benchmark_name].set_index('date').nav.astype(float).pct_change().rename('bm').dropna()
    for idx, row in result.iterrows():
        fund = row['基金']
        if fund == benchmark_name:
            result.at[idx, 'Beta'] = 1.0
            continue
        fr = nav[nav.fund == fund].set_index('date').nav.astype(float).pct_change().rename('fund').dropna()
        merged = pd.concat([fr, bm], axis=1).dropna()
        if len(merged) >= 20 and merged['bm'].var(ddof=1) > 0:
            result.at[idx, 'Beta'] = merged['fund'].cov(merged['bm']) / merged['bm'].var(ddof=1)
    return result


def _fmt_metric(value, suffix=''):
    return 'N/A' if pd.isna(value) else f'{value:+.2f}{suffix}'


def render_comparison():
    st.header('基金績效題材與匯率比較')
    st.write('同時比較原幣、台幣、美元及日幣報酬，並把 Sharpe、Beta、1M／3M／6M 績效納入選定基金的最終評估。')
    source_mode = st.segmented_control('比較資料來源', ['MoneyDJ 網址','檔案上傳','示範資料'], default='MoneyDJ 網址', key='cmp_source')
    sample = source_mode == '示範資料'
    nav_raw = holdings = pd.DataFrame(); descriptions=[]
    if sample:
        st.warning('目前為模擬資料，僅供操作示範，不能作為真實基金績效。'); nav_raw, holdings, sample_fx = demo_data()
    elif source_mode == '檔案上傳':
        nav_files = st.file_uploader('淨值資料（可上傳多檔，每檔需含基金名稱）', type=['csv','xlsx','xls'], accept_multiple_files=True, key='cmp_nav_files')
        holdings_file = st.file_uploader('題材／持股資料（選填）', type=['csv','xlsx','xls'], key='cmp_holdings_file')
        with st.expander('欄位說明與下載範本'):
            st.write('淨值：日期、基金、淨值、幣別。不同計價或配息級別請使用不同基金名稱。')
            st.write('題材：日期、基金、投資題材、權重。15 代表 15%；可以逐筆持股或已彙總題材，請勿混合或重複歸類。')
            template_nav=pd.DataFrame({'日期':['2025-09-01','2026-09-01']*2,'基金':['基金A美元級別']*2+['基金B台幣級別']*2,'淨值':[100,110,20,21],'幣別':['USD']*2+['TWD']*2})
            template_hold=pd.DataFrame({'日期':['2026-09-01']*2,'基金':['基金A美元級別','基金B台幣級別'],'投資題材':['AI運算','醫療創新'],'權重':[25,30]})
            st.download_button('下載淨值欄位範本',template_nav.to_csv(index=False).encode('utf-8-sig'),'淨值欄位範本.csv',key='cmp_nav_template')
            st.download_button('下載題材欄位範本',template_hold.to_csv(index=False).encode('utf-8-sig'),'題材欄位範本.csv',key='cmp_hold_template')
        if not nav_files: st.info('請先上傳至少包含兩檔基金的淨值資料。持股資料可稍後補上。'); return
        try:
            nav_raw=pd.concat([read_table(f) for f in nav_files],ignore_index=True)
            if holdings_file: holdings=read_table(holdings_file)
            descriptions=[f'淨值：{f.name}' for f in nav_files]+([f'持股：{holdings_file.name}'] if holdings_file else [])
        except Exception as exc: st.error(f'檔案無法讀取：{exc}'); return
    elif source_mode == 'MoneyDJ 網址':
        st.session_state.setdefault('cmp_fund_basket', {}); basket=st.session_state.cmp_fund_basket
        if st.session_state.pop('cmp_clear_url',False): st.session_state['cmp_single_url']=''
        if st.session_state.get('cmp_add_notice'): st.success(st.session_state.pop('cmp_add_notice'))
        url=st.text_input('貼上一檔基金網址',key='cmp_single_url',placeholder='https://tcbbankfund.moneydj.com/main.html?...',help='一次貼一個合庫 MoneyDJ 基金網址，按加入後再貼下一檔。支援境內與境外基金。')
        if st.button('加入比較清單',key='cmp_add_url',type='primary'):
            fund_id=moneydj_fund_id(url.strip())
            if not fund_id: st.error('請貼上一個有效的 MoneyDJ 基金完整網址。')
            elif fund_id in basket: st.info('這檔基金已在比較清單中，不會重複加入。')
            elif len(basket)>=10: st.warning('最多加入10檔基金，請先移除一檔。')
            else:
                try:
                    with st.spinner('正在讀取這檔基金…'): n,h,d=load_comparison_url(url.strip()); n=read_nav(n)
                    basket[fund_id]=(n,h,[url.strip()]+d); st.session_state['cmp_selected']=[name for entry in basket.values() for name in entry[0].fund.unique()]
                    st.session_state['cmp_add_notice']='已加入：'+'、'.join(n.fund.unique()); st.session_state['cmp_clear_url']=True; st.rerun()
                except Exception as exc: st.error(f'這檔基金加入失敗：{exc}。原本的比較清單已保留，可修正網址後重試。')
        st.subheader(f'已加入基金（{len(basket)}/10）')
        for fund_id,(n,h,d) in list(basket.items()):
            left,right=st.columns([5,1]); left.write('、'.join(n.fund.unique()))
            if right.button('移除',key='cmp_remove_'+fund_id): del basket[fund_id]; st.session_state['cmp_selected']=[name for entry in basket.values() for name in entry[0].fund.unique()]; st.rerun()
        if not basket: st.info('先貼上一檔基金網址，按「加入比較清單」，再加入另一檔即可比較。'); return
        nav_raw=pd.concat([entry[0] for entry in basket.values()],ignore_index=True); holdings=pd.concat([entry[1] for entry in basket.values()],ignore_index=True)
        descriptions=[description for entry in basket.values() for description in entry[2]]
    else: return

    if not holdings.empty and {'name','theme'} <= set(holdings):
        holdings=holdings.copy()
        for idx,row in holdings.iterrows():
            if source_mode=='MoneyDJ 網址' or pd.isna(row['theme']) or str(row['theme']) in ('其他／待確認','未分類','其他',''):
                ticker,sector,theme=holding_identity(row['name'])
                if theme!='其他／待確認': holdings.loc[idx,['ticker','sector','theme']]=[ticker,sector,theme]
    if source_mode == 'MoneyDJ 網址':
        st.success('已讀取：'+'、'.join(nav_raw.fund.unique()))
        with st.expander('基金來源與資料日期'):
            for description in descriptions: st.write(description)
    try: nav=read_nav(nav_raw)
    except ValueError as exc: st.error(str(exc)); return

    all_funds=sorted(nav.fund.unique())
    st.subheader('基金評估指標')
    st.caption('MoneyDJ 網址模式優先採用 MoneyDJ 公布的 Sharpe、Beta、1M／3M／6M；短期報酬抓不到時才由淨值計算補足。')
    beta_benchmark=st.selectbox('Beta 比較基準',['MoneyDJ 公布 Beta']+all_funds,key='cmp_beta_benchmark')
    screen=_fund_screen_metrics(nav,all_funds)
    if beta_benchmark!='MoneyDJ 公布 Beta': screen=_attach_beta(screen,nav,beta_benchmark)
    st.dataframe(screen,hide_index=True,column_config={'Sharpe':st.column_config.NumberColumn(format='%.2f'),'Beta':st.column_config.NumberColumn(format='%.2f'),'1M %':st.column_config.NumberColumn(format='%+.2f'),'3M %':st.column_config.NumberColumn(format='%+.2f'),'6M %':st.column_config.NumberColumn(format='%+.2f')})
    selected=st.multiselect('選擇比較基金（2 至 10 檔）',all_funds,default=None if 'cmp_selected' in st.session_state else all_funds[:min(5,len(all_funds))],key='cmp_selected')
    if not 2<=len(selected)<=10: st.info('請選擇 2 至 10 檔基金。'); return

    sub=nav[nav.fund.isin(selected)]; d0,d1=sub.date.min().date(),sub.date.max().date(); left,right=st.columns(2)
    start=left.date_input('希望比較起日',d0,min_value=d0,max_value=d1,key='cmp_start'); end=right.date_input('希望比較迄日',d1,min_value=d0,max_value=d1,key='cmp_end')
    try: actual_start,actual_end=common_period(nav,selected,start,end)
    except ValueError as exc: st.error(str(exc)); return
    st.caption(f'實際共同淨值日期：{actual_start:%Y/%m/%d} 至 {actual_end:%Y/%m/%d}；匯率必須對應這兩天。')
    if source_mode=='MoneyDJ 網址':
        nav=nav.copy()
        for entry in basket.values():
            try:
                rating,risk_source=cached_risk(entry[2][0]); nav.loc[nav.fund.isin(entry[0].fund.unique()),'risk_level']=rating
                if risk_source: descriptions.append('風險等級來源：'+risk_source)
            except Exception: pass
    meta=[infer_metadata(nav,fund,moneydj=source_mode=='MoneyDJ 網址',sample=sample) for fund in selected]
    st.subheader('自動判讀基金級別與報酬口徑'); st.caption('已依資料來源自動帶入，可直接修改。風險等級取自來源公布的 RR1～RR5；查不到時可手動補填。')
    source_id=sha256((nav.to_csv(index=False)+repr(selected)).encode()).hexdigest()[:10]
    meta=st.data_editor(pd.DataFrame(meta),hide_index=True,disabled=['基金','判讀依據'],key='cmp_meta_rr_'+source_id,column_config={'級別幣別':st.column_config.SelectboxColumn(options=['請確認']+CURRENCIES,required=True),'報酬口徑':st.column_config.SelectboxColumn(options=BASIS,required=True),'風險報酬等級':st.column_config.SelectboxColumn(options=['未確認','RR1','RR2','RR3','RR4','RR5'],required=True)})
    if not meta['級別幣別'].isin(CURRENCIES).all(): st.info('請先在上表確認每檔基金的級別幣別，再設定匯率。'); return

    currencies=sorted(set(meta['級別幣別'])|{'USD','TWD','JPY'}); st.subheader('期初與期末匯率'); st.write('統一填「1 單位該幣別＝多少台幣」，例如 USD 匯率 32 代表 1 美元可換 32 台幣。JPY 請填 1 日圓兌台幣，例如 0.22。')
    fx_mode=st.segmented_control('匯率輸入方式',['自動取得','手動輸入','匯率檔上傳'],default='手動輸入' if sample else '自動取得',key='cmp_fx_mode_v2'); rates=None; fx_source=''
    if fx_mode=='自動取得':
        try:
            with st.spinner('正在取得比較起訖日匯率…'): rates,fx_source=load_auto_fx(tuple(currencies),actual_start,actual_end)
            st.dataframe(rates,hide_index=True); st.caption('Frankfurter 歷史參考匯率，已換算成 1 單位外幣兌台幣；非銀行實際買賣成交價。')
        except Exception: st.warning('暫時無法取得完整同日匯率，請切換手動輸入或匯率檔上傳；不會套用其他日期。')
    elif fx_mode=='匯率檔上傳':
        f=st.file_uploader('匯率資料（CSV／Excel）',type=['csv','xlsx','xls'],key='cmp_fx_upload'); st.caption('欄位：日期、幣別、台幣匯率。需涵蓋實際共同淨值起訖日。')
        if f:
            try: rates=endpoint_rates(read_fx(read_table(f)),currencies,actual_start,actual_end)
            except Exception as exc: st.error(str(exc)); return
            st.dataframe(rates,hide_index=True)
    else:
        defaults=pd.DataFrame([{'幣別':c,'期初匯率':1.0 if c=='TWD' else None,'期末匯率':1.0 if c=='TWD' else None} for c in currencies])
        if sample and actual_start==nav.date.min() and actual_end==nav.date.max(): defaults=endpoint_rates(sample_fx,currencies,actual_start,actual_end)
        for c in ['期初匯率','期末匯率']: defaults[c]=pd.to_numeric(defaults[c],errors='coerce')
        rates=st.data_editor(defaults,disabled=['幣別'],hide_index=True,key=f'cmp_rates_{sample}_{actual_start}_{actual_end}_{"_".join(currencies)}',column_config={c:st.column_config.NumberColumn(format='%.6f',min_value=0.000001,required=True) for c in ['期初匯率','期末匯率']})
    if rates is None: return
    sources=st.text_area('資料來源與匯率報價來源',value='模擬資料（非市場報價）' if sample else '\n'.join(descriptions+[fx_source]),key='cmp_sources_v2_'+source_id+'_'+str(actual_start)+'_'+str(actual_end)+'_'+str(fx_mode)); notes=st.text_area('報告補充說明',key='cmp_notes',placeholder='例如：配息處理方式、幣別避險資訊、資料時點差異')
    if not sample and not st.checkbox('已確認基金幣別、報酬口徑與同日匯率來源',key='cmp_confirm_'+source_id): return

    try: performance=compare(nav,meta,rates,actual_start,actual_end); themes,coverage=theme_comparison(holdings,selected,actual_end)
    except ValueError as exc: st.error(str(exc)); return
    selected_metrics=screen[screen['基金'].isin(selected)][['基金','Sharpe','Beta','1M %','3M %','6M %']]
    performance=performance.merge(selected_metrics,on='基金',how='left')

    st.subheader('績效、風險與動能綜合評估')
    for line in conclusions(performance,themes): st.write(line)
    st.markdown('#### 選定基金的 Sharpe、Beta 與短期績效')
    for _,row in performance.iterrows():
        st.write(f'{row["基金"]}：Sharpe {_fmt_metric(row["Sharpe"])}、Beta {_fmt_metric(row["Beta"])}、1M {_fmt_metric(row["1M %"], "%")}、3M {_fmt_metric(row["3M %"], "%")}、6M {_fmt_metric(row["6M %"], "%")}；區間台幣報酬 {_fmt_metric(row["台幣報酬 %"], "%")}。')
    st.caption('MoneyDJ 網址模式優先採用來源公布值；N/A 表示來源與已載入淨值都不足。若改選基金作 Beta 基準，Beta 會依共同淨值重新計算。')
    columns=['基金','Sharpe','Beta','1M %','3M %','6M %','級別幣別','原幣報酬 %','台幣報酬 %','美元報酬 %','日幣報酬 %','台幣匯率影響 百分點','美元匯率影響 百分點','日幣匯率影響 百分點']
    st.dataframe(performance[columns],hide_index=True,column_config={c:st.column_config.NumberColumn(format='%.2f') for c in ['Sharpe','Beta']}|{c:st.column_config.NumberColumn(format='%+.2f') for c in columns if c.endswith('%') or '百分點' in c})
    chart=performance.melt(id_vars=['基金'],value_vars=['原幣報酬 %','台幣報酬 %','美元報酬 %','日幣報酬 %'],var_name='報酬基準',value_name='報酬 %'); st.altair_chart(alt.Chart(chart).mark_bar().encode(x=alt.X('基金:N',axis=alt.Axis(labelAngle=0)),xOffset='報酬基準:N',y=alt.Y('報酬 %:Q'),color='報酬基準:N',tooltip=['基金','報酬基準',alt.Tooltip('報酬 %:Q',format='.2f')]))
    st.caption('原幣柱是不同計價幣別；請以台幣、美元或日幣柱作相同幣別的比較。匯率影響欄為百分點，已包含交互作用。'); st.subheader('投資題材配置'); st.caption('題材依公司業務分類，非基金經理人的官方投資理由；多元業務以合併題材呈現，每筆持股只計一次權重。')
    if not holdings.empty and {'name','theme'} <= set(holdings):
        with st.expander('查看持股與題材分類對照'):
            detail=holdings[holdings.fund.isin(selected)].copy()
            if 'date' in detail: detail['date']=pd.to_datetime(detail['date'],errors='coerce'); detail=detail[detail.date<=actual_end]; detail=detail[detail.date==detail.groupby('fund').date.transform('max')]
            st.dataframe(detail[[c for c in ['fund','name','sector','theme','weight'] if c in detail]].rename(columns={'fund':'基金','name':'持股','sector':'產業','theme':'投資題材','weight':'權重 %'}),hide_index=True)
    if themes.empty: st.info('未提供有效持股題材資料，績效與匯率比較仍可使用。')
    else:
        st.dataframe(themes.pivot(index='投資題材',columns='基金',values='權重 %').reindex(columns=selected),column_config={f:st.column_config.NumberColumn(format='%.2f%%') for f in selected}); st.caption('空白表示沒有該題材紀錄，不代表曝險一定為零；此表只涵蓋已揭露資料。'); st.markdown('#### 題材持股比例柱狀圖')
        theme_order=themes.groupby('投資題材')['權重 %'].max().sort_values(ascending=False).index.tolist(); theme_chart=alt.Chart(themes).mark_bar().encode(y=alt.Y('投資題材:N',sort=theme_order,title=None,axis=alt.Axis(labelLimit=320)),yOffset=alt.YOffset('基金:N',sort=selected),x=alt.X('權重 %:Q',title='占基金淨資產比例（%）',scale=alt.Scale(zero=True)),color=alt.Color('基金:N',sort=selected,legend=alt.Legend(orient='bottom',labelLimit=350)),tooltip=['基金:N','投資題材:N','持股日期:N',alt.Tooltip('權重 %:Q',format='.2f')]).properties(height=max(280,len(theme_order)*max(40,len(selected)*16))); st.altair_chart(theme_chart); st.caption('每種顏色代表一檔基金。以橫向柱狀呈現完整題材名稱；未揭露部位不補零、不放大至100%。'); st.dataframe(coverage,hide_index=True)
        missing=set(selected)-set(coverage['基金'])
        if missing: st.warning('以下基金沒有期末以前的持股資料：'+'、'.join(sorted(missing)))
        if (coverage['資料距期末 天']>90).any(): st.warning('部分持股距績效期末超過90天，題材配置可能已改變。')
    with st.expander('計算方式、淨值端點與資料限制'):
        st.dataframe(performance,hide_index=True)
        for line in METHOD: st.write(line)
    html=report_html(performance,themes,coverage,rates,actual_start,actual_end,sources,notes,sample)
    if st.button('產生比較報告下載',type='primary',key='cmp_prepare'):
        st.download_button('下載完整比較報告（HTML，可列印為 PDF）',html.encode('utf-8'),f'基金績效題材匯率比較_{actual_end:%Y%m%d}.html',mime='text/html',on_click='ignore')
        st.download_button('下載績效比較數據（CSV）',performance.to_csv(index=False).encode('utf-8-sig'),f'基金比較數據_{actual_end:%Y%m%d}.csv',mime='text/csv',on_click='ignore')
        st.download_button('下載題材比較數據（CSV）',themes.to_csv(index=False).encode('utf-8-sig'),f'基金題材數據_{actual_end:%Y%m%d}.csv',mime='text/csv',on_click='ignore')
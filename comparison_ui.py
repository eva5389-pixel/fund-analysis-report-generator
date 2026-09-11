from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from fund_analysis import moneydj_fund_id, read_table
from moneydj_comparison import load_comparison_fund
from comparison_engine import (BASIS, CURRENCIES, METHOD, common_period, compare, conclusions, demo_data,
                               endpoint_rates, read_fx, read_nav, report_html, theme_comparison)


@st.cache_data(ttl=3600, max_entries=30, show_spinner=False)
def load_comparison_url(url):
    return load_comparison_fund(url)


def render_comparison():
    st.header('基金績效題材與匯率比較')
    st.write('同時比較原幣、台幣、美元及日幣報酬，拆解匯率影響，並列持股題材與資料涵蓋率。')
    source_mode = st.segmented_control('比較資料來源', ['MoneyDJ 網址','檔案上傳','示範資料'], default='MoneyDJ 網址', key='cmp_source')
    sample = source_mode == '示範資料'
    nav_raw = holdings = pd.DataFrame()
    descriptions=[]
    if sample:
        st.warning('目前為模擬資料，僅供操作示範，不能作為真實基金績效。')
        nav_raw, holdings, sample_fx = demo_data()
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
        if not nav_files:
            st.info('請先上傳至少包含兩檔基金的淨值資料。持股資料可稍後補上。')
            return
        try:
            nav_raw=pd.concat([read_table(f) for f in nav_files],ignore_index=True)
            if holdings_file: holdings=read_table(holdings_file)
            descriptions=[f'淨值：{f.name}' for f in nav_files]+([f'持股：{holdings_file.name}'] if holdings_file else [])
        except Exception as exc:
            st.error(f'檔案無法讀取：{exc}'); return
    elif source_mode == 'MoneyDJ 網址':
        st.session_state.setdefault('cmp_fund_basket', {})
        basket=st.session_state.cmp_fund_basket
        if st.session_state.pop('cmp_clear_url',False):
            st.session_state['cmp_single_url']=''
        if st.session_state.get('cmp_add_notice'):
            st.success(st.session_state.pop('cmp_add_notice'))
        url=st.text_input('貼上一檔基金網址',key='cmp_single_url',placeholder='https://tcbbankfund.moneydj.com/main.html?...',
            help='一次貼一個合庫 MoneyDJ 基金網址，按加入後再貼下一檔。支援境內與境外基金。')
        if st.button('加入比較清單',key='cmp_add_url',type='primary'):
            fund_id=moneydj_fund_id(url.strip())
            if not fund_id:
                st.error('請貼上一個有效的 MoneyDJ 基金完整網址。')
            elif fund_id in basket:
                st.info('這檔基金已在比較清單中，不會重複加入。')
            elif len(basket)>=10:
                st.warning('最多加入10檔基金，請先移除一檔。')
            else:
                try:
                    with st.spinner('正在讀取這檔基金…'):
                        n,h,d=load_comparison_url(url.strip())
                        n=read_nav(n)
                    basket[fund_id]=(n,h,[url.strip()]+d)
                    st.session_state['cmp_selected']=[name for entry in basket.values() for name in entry[0].fund.unique()]
                    st.session_state['cmp_add_notice']='已加入：'+'、'.join(n.fund.unique())
                    st.session_state['cmp_clear_url']=True
                    st.rerun()
                except Exception as exc:
                    st.error(f'這檔基金加入失敗：{exc}。原本的比較清單已保留，可修正網址後重試。')
        st.subheader(f'已加入基金（{len(basket)}/10）')
        for fund_id,(n,h,d) in list(basket.items()):
            left,right=st.columns([5,1])
            left.write('、'.join(n.fund.unique()))
            if right.button('移除',key='cmp_remove_'+fund_id):
                del basket[fund_id]
                st.session_state['cmp_selected']=[name for entry in basket.values() for name in entry[0].fund.unique()]
                st.rerun()
        if not basket:
            st.info('先貼上一檔基金網址，按「加入比較清單」，再加入另一檔即可比較。')
            return
        nav_raw=pd.concat([entry[0] for entry in basket.values()],ignore_index=True)
        holdings=pd.concat([entry[1] for entry in basket.values()],ignore_index=True)
        descriptions=[description for entry in basket.values() for description in entry[2]]
    else:
        return
    if source_mode == 'MoneyDJ 網址':
        st.success('已讀取：'+'、'.join(nav_raw.fund.unique()))
        with st.expander('基金來源與資料日期'):
            for description in descriptions: st.write(description)
    try: nav=read_nav(nav_raw)
    except ValueError as exc: st.error(str(exc)); return
    all_funds=sorted(nav.fund.unique())
    selected=st.multiselect('選擇比較基金（2 至 10 檔）',all_funds,default=None if 'cmp_selected' in st.session_state else all_funds[:min(5,len(all_funds))],key='cmp_selected')
    if not 2<=len(selected)<=10:
        st.info('請選擇 2 至 10 檔基金。'); return
    sub=nav[nav.fund.isin(selected)]
    d0,d1=sub.date.min().date(),sub.date.max().date()
    left,right=st.columns(2)
    start=left.date_input('希望比較起日',d0,min_value=d0,max_value=d1,key='cmp_start')
    end=right.date_input('希望比較迄日',d1,min_value=d0,max_value=d1,key='cmp_end')
    try: actual_start,actual_end=common_period(nav,selected,start,end)
    except ValueError as exc: st.error(str(exc)); return
    st.caption(f'實際共同淨值日期：{actual_start:%Y/%m/%d} 至 {actual_end:%Y/%m/%d}；匯率必須對應這兩天。')
    meta=[]
    for fund in selected:
        currencies=nav.loc[nav.fund==fund,'currency'].dropna().astype(str).str.upper().unique() if 'currency' in nav else []
        currency=currencies[0] if len(currencies)==1 and currencies[0] in CURRENCIES else '請確認'
        meta.append({'基金':fund,'級別幣別':currency,'報酬口徑':BASIS[0] if sample else '未確認','避險級別':'未確認'})
    st.subheader('確認基金級別與報酬口徑')
    st.caption('填淨值的計價幣別，不要填底層持股幣別。避險級別的基金內部避險已反映在淨值，不重複調整。')
    source_id=sha256((nav.to_csv(index=False)+repr(selected)).encode()).hexdigest()[:10]
    meta=st.data_editor(pd.DataFrame(meta),hide_index=True,disabled=['基金'],key='cmp_meta_'+source_id,
        column_config={'級別幣別':st.column_config.SelectboxColumn(options=['請確認']+CURRENCIES,required=True),
                       '報酬口徑':st.column_config.SelectboxColumn(options=BASIS,required=True),
                       '避險級別':st.column_config.SelectboxColumn(options=['未確認','避險級別','非避險級別'],required=True)})
    if not meta['級別幣別'].isin(CURRENCIES).all():
        st.info('請先在上表確認每檔基金的級別幣別，再設定匯率。'); return
    currencies=sorted(set(meta['級別幣別'])|{'USD','TWD','JPY'})
    st.subheader('期初與期末匯率')
    st.write('統一填「1 單位該幣別＝多少台幣」，例如 USD 匯率 32 代表 1 美元可換 32 台幣。系統會同時計算台幣、美元及日幣結果。JPY 請填 1 日圓兌台幣，例如 0.22，不是 100 日圓的報價。')
    fx_mode=st.segmented_control('匯率輸入方式',['手動輸入','匯率檔上傳'],default='手動輸入',key='cmp_fx_mode')
    rates=None
    if fx_mode=='匯率檔上傳':
        f=st.file_uploader('匯率資料（CSV／Excel）',type=['csv','xlsx','xls'],key='cmp_fx_upload')
        st.caption('欄位：日期、幣別、台幣匯率。需涵蓋實際共同淨值起訖日；不自動套用其他日期。')
        if f:
            try: rates=endpoint_rates(read_fx(read_table(f)),currencies,actual_start,actual_end)
            except Exception as exc: st.error(str(exc)); return
            st.dataframe(rates,hide_index=True)
    elif fx_mode=='手動輸入':
        defaults=pd.DataFrame([{'幣別':c,'期初匯率':1.0 if c=='TWD' else None,'期末匯率':1.0 if c=='TWD' else None} for c in currencies])
        if sample and actual_start==nav.date.min() and actual_end==nav.date.max():
            defaults=endpoint_rates(sample_fx,currencies,actual_start,actual_end)
        for c in ['期初匯率','期末匯率']: defaults[c]=pd.to_numeric(defaults[c],errors='coerce')
        rates=st.data_editor(defaults,disabled=['幣別'],hide_index=True,key=f'cmp_rates_{sample}_{actual_start}_{actual_end}_{"_".join(currencies)}',
            column_config={c:st.column_config.NumberColumn(format='%.6f',min_value=0.000001,required=True) for c in ['期初匯率','期末匯率']})
    if rates is None: return
    sources=st.text_area('資料來源與匯率報價來源',value='模擬資料（非市場報價）' if sample else '\n'.join(descriptions),key='cmp_sources_'+source_id)
    notes=st.text_area('報告補充說明',key='cmp_notes',placeholder='例如：配息處理方式、幣別避險資訊、資料時點差異')
    if not sample and not st.checkbox('已確認基金幣別、報酬口徑與同日匯率來源',key='cmp_confirm_'+source_id): return
    try:
        performance=compare(nav,meta,rates,actual_start,actual_end)
        themes,coverage=theme_comparison(holdings,selected,actual_end)
    except ValueError as exc: st.error(str(exc)); return
    st.subheader('績效與匯率比較結果')
    for line in conclusions(performance,themes): st.write(line)
    columns=['基金','級別幣別','原幣報酬 %','台幣報酬 %','美元報酬 %','日幣報酬 %','台幣匯率影響 百分點','美元匯率影響 百分點','日幣匯率影響 百分點']
    st.dataframe(performance[columns],hide_index=True,column_config={c:st.column_config.NumberColumn(format='%+.2f') for c in columns[2:]})
    chart=performance.melt(id_vars=['基金'],value_vars=['原幣報酬 %','台幣報酬 %','美元報酬 %','日幣報酬 %'],var_name='報酬基準',value_name='報酬 %')
    st.altair_chart(alt.Chart(chart).mark_bar().encode(x=alt.X('基金:N',axis=alt.Axis(labelAngle=0)),xOffset='報酬基準:N',y=alt.Y('報酬 %:Q'),color='報酬基準:N',tooltip=['基金','報酬基準',alt.Tooltip('報酬 %:Q',format='.2f')]))
    st.caption('原幣柱是不同計價幣別；請以台幣、美元或日幣柱作相同幣別的比較。匯率影響欄為百分點，已包含交互作用。')
    st.subheader('投資題材配置')
    if themes.empty:
        st.info('未提供有效持股題材資料，績效與匯率比較仍可使用。')
    else:
        st.dataframe(themes.pivot(index='投資題材',columns='基金',values='權重 %').reindex(columns=selected),column_config={f:st.column_config.NumberColumn(format='%.2f%%') for f in selected})
        st.caption('空白表示沒有該題材紀錄，不代表曝險一定為零；此表只涵蓋已揭露資料。')
        st.dataframe(coverage,hide_index=True)
        missing=set(selected)-set(coverage['基金'])
        if missing: st.warning('以下基金沒有期末以前的持股資料：'+'、'.join(sorted(missing)))
        if (coverage['資料距期末 天']>90).any(): st.warning('部分持股距績效期末超過90天，題材配置可能已改變。')
    with st.expander('計算方式、淨值端點與資料限制'):
        st.dataframe(performance,hide_index=True)
        for line in METHOD: st.write(line)
        st.markdown('[Investor.gov：匯率與國際投資](https://www.investor.gov/introduction-investing/investing-basics/investment-products/international-investing) · [FINRA：基金與配息](https://www.finra.org/investors/investing/investment-products/mutual-funds)')
    # Recompute with current inputs on every rerun; filenames identify the valuation window.
    html=report_html(performance,themes,coverage,rates,actual_start,actual_end,sources,notes,sample)
    if st.button('產生比較報告下載',type='primary',key='cmp_prepare'):
        st.download_button('下載完整比較報告（HTML，可列印為 PDF）',html.encode('utf-8'),f'基金績效題材匯率比較_{actual_end:%Y%m%d}.html',mime='text/html',on_click='ignore')
        st.download_button('下載績效比較數據（CSV）',performance.to_csv(index=False).encode('utf-8-sig'),f'基金比較數據_{actual_end:%Y%m%d}.csv',mime='text/csv',on_click='ignore')
        st.download_button('下載題材比較數據（CSV）',themes.to_csv(index=False).encode('utf-8-sig'),f'基金題材數據_{actual_end:%Y%m%d}.csv',mime='text/csv',on_click='ignore')

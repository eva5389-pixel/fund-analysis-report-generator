"""Evidence-based defaults; absence of a hedge label is not proof of no hedge."""
import re
import pandas as pd
import requests
from comparison_engine import BASIS, CURRENCIES, endpoint_rates, read_fx


def infer_metadata(nav, fund, moneydj=False, sample=False):
    rows=nav[nav.fund==fund]
    def single(column):
        values=rows[column].dropna().astype(str).str.strip().unique() if column in rows else []
        return values[0] if len(values)==1 else None
    currency=(single('currency') or '').upper()
    basis=single('return_basis') or single('報酬口徑')
    if basis not in BASIS: basis=BASIS[0] if sample else BASIS[1] if moneydj else '未確認'
    hedge=single('hedge') or single('避險級別')
    if hedge not in ['避險級別','非避險級別']:
        if re.search(r'非避險|不避險|未避險|unhedged',fund,re.I): hedge='非避險級別'
        elif re.search(r'避險|對沖|\bhedged\b',fund,re.I): hedge='避險級別'
        else: hedge='未確認'
    reason='MoneyDJ 原始淨值，未加入現金配息' if moneydj else '依上傳欄位／基金名稱'
    if hedge=='未確認': reason+='；來源未明示避險級別'
    return {'基金':fund,'級別幣別':currency if currency in CURRENCIES else '請確認','報酬口徑':basis,'避險級別':hedge,'判讀依據':reason}


def fetch_fx(currencies, start, end):
    rows=[]; sources=[]
    for date in (pd.Timestamp(start),pd.Timestamp(end)):
        url='https://api.frankfurter.dev/v2/rates'
        response=requests.get(url,params={'base':'TWD','quotes':','.join(c for c in currencies if c!='TWD'),'date':date.strftime('%Y-%m-%d')},timeout=20)
        response.raise_for_status()
        data=response.json()
        if not isinstance(data,list): raise ValueError('匯率來源回傳格式不符。')
        for item in data:
            if item.get('base')!='TWD' or pd.Timestamp(item['date'])!=date:
                raise ValueError(f'{date:%Y/%m/%d} 沒有同日匯率，請手動補填或上傳。')
            rate=float(item['rate'])
            if rate<=0: raise ValueError('匯率來源包含無效報價。')
            rows.append({'date':date,'currency':item['quote'],'twd_rate':1/rate})
        rows.append({'date':date,'currency':'TWD','twd_rate':1.0})
        sources.append(response.url)
    return endpoint_rates(read_fx(pd.DataFrame(rows)),currencies,start,end), '\n'.join(sources)

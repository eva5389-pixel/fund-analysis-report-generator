"""Read the publicly linked WB/WR pages, including their actual date labels."""
import re
import numpy as np
import pandas as pd
from fund_analysis import moneydj_fund_id, read_url_tables, _holding_identity, _numeric_percent

CURRENCY_NAMES={'美元':'USD','美金':'USD','新台幣':'TWD','台幣':'TWD','日圓':'JPY','日元':'JPY','日幣':'JPY','歐元':'EUR','英鎊':'GBP','澳幣':'AUD','澳元':'AUD','加幣':'CAD','港幣':'HKD','人民幣':'CNY','南非幣':'ZAR','瑞士法郎':'CHF','新加坡幣':'SGD','紐西蘭幣':'NZD'}
IDENTITIES={'sk hynix':('000660.KS','記憶體','DRAM與HBM'),'nvidia':('NVDA','半導體設計','AI運算與資料中心'),'broadcom':('AVGO','半導體設計','AI網路與客製化晶片'),'samsung electronics':('005930.KS','半導體','記憶體與電子裝置'),'lam research':('LRCX','半導體設備','半導體製程設備'),'apple inc':('AAPL','消費電子','行動裝置與服務'),'taiwan semiconductor':('TSM','晶圓代工','AI先進製程'),'intel':('INTC','半導體','處理器與晶圓製造'),'alphabet':('GOOGL','網路服務','雲端與網路服務')}


def holding_identity(name):
    # Match English company words, not substrings such as Intel in Intelligent.
    text=str(name).lower()
    for keyword,value in IDENTITIES.items():
        if re.search(r'(?<![a-z0-9])'+re.escape(keyword)+r'(?![a-z0-9])',text):
            return value
    return _holding_identity(name)


def parse_pages(profile_tables, nav_tables, holding_tables, fund_id):
    profile={}
    for table in profile_tables:
        for row in table.itertuples(index=False,name=None):
            cells=[str(v).strip() for v in row]
            for label in ['基金名稱','計價幣別']:
                if label in cells and cells.index(label)+1<len(cells):
                    profile[label]=cells[cells.index(label)+1]
    name=profile.get('基金名稱',f'MoneyDJ基金 {fund_id}')
    currency_text=profile.get('計價幣別','')
    currency=CURRENCY_NAMES.get(currency_text,currency_text if currency_text in CURRENCY_NAMES.values() else None)
    anchor=None
    for table in profile_tables:
        if '淨值日期' in table:
            full_dates=table['淨值日期'].astype(str).str.extract(r'(\d{4}/\d{1,2}/\d{1,2})')[0].dropna()
            if not full_dates.empty: anchor=pd.to_datetime(full_dates.iloc[0]);break
    if anchor is None:
        # Domestic profiles have no latest-NAV table. The NAV page's own end-date
        # picker contains the year; never use the machine's current year.
        for table in nav_tables:
            page_text=table.attrs.get('source_text','')
            match=re.search(r"eDate\s*=\s*\$\.datepicker\.formatDate\([\s\S]{0,180}?parseDate\(\s*['\"]yy-mm-dd['\"]\s*,\s*['\"](\d{4}-\d{1,2}-\d{1,2})['\"]",page_text)
            if match:
                anchor=pd.Timestamp(match[1]);break
    nav_frames=[]
    for table in nav_tables:
        if {'日期','淨值'} <= set(table): nav_frames.append(table[['日期','淨值']].copy())
    if not nav_frames: raise ValueError('該基金的淨值頁沒有可讀取資料。')
    raw=pd.concat(nav_frames,ignore_index=True)
    def parsed_date(value):
        text=str(value).strip()
        if re.fullmatch(r'\d{1,2}/\d{1,2}',text):
            if anchor is None: raise ValueError('淨值只有月日但找不到最新淨值年份，請改上傳含完整日期的淨值資料。')
            month,day=map(int,text.split('/'))
            candidate=pd.Timestamp(anchor.year,month,day)
            return candidate if candidate<=anchor else pd.Timestamp(anchor.year-1,month,day)
        return pd.to_datetime(text,errors='coerce')
    nav=pd.DataFrame({'date':raw['日期'].map(parsed_date),'nav':pd.to_numeric(raw['淨值'],errors='coerce'),'fund':name,'currency':currency})
    nav=nav.dropna(subset=['date','nav']).drop_duplicates(['fund','date']).sort_values('date')
    if len(nav)<2: raise ValueError('目前可用淨值不足兩筆。')
    columns=['date','fund','name','ticker','theme','sector','weight']
    rows=[];warnings=[]
    if holding_tables:
        page_text=holding_tables[0].attrs.get('source_text','')
        month=re.search(r'資料月份\s*[：:]\s*(\d{4})年\s*(\d{1,2})月',page_text)
        if month:
            holding_date=pd.Timestamp(int(month[1]),int(month[2]),1)+pd.offsets.MonthEnd(0)
            warnings.append(f'持股按頁面揭露月份 {month[1]}年{month[2]}月歸於月底，並非淨值日期。')
        else:
            holding_date=None
            warnings.append('持股資料未找到明確月份，未納入題材比較；可另行上傳有日期的持股檔。')
        if holding_date is not None:
            for table in holding_tables:
                names=[c for c in table if '持股名稱' in str(c) or '股票名稱' in str(c)]
                weights=[c for c in table if '比例' in str(c)]
                for nc,wc in zip(names,weights):
                    for holding,weight in zip(table[nc],_numeric_percent(table[wc])):
                        if pd.isna(weight) or pd.isna(holding): continue
                        identity=holding_identity(holding)
                        rows.append(dict(date=holding_date,fund=name,name=str(holding),ticker=identity[0],sector=identity[1],theme=identity[2],weight=float(weight)))
    else: warnings.append('持股暫時無法取得；仍可比較淨值績效。')
    holdings=pd.DataFrame(rows,columns=columns).drop_duplicates(['date','fund','name'])
    warnings += [f'{name}：計價幣別 {currency or "未確認"}，淨值 {len(nav)} 筆（{nav.date.min():%Y-%m-%d} 至 {nav.date.max():%Y-%m-%d}）。',
                 '讀取頁面公布的原始淨值，非含息績效表；配息口徑需確認。頁面只提供近期淨值，較長期間請上傳歷史淨值。',
                 '持股題材為規則對照分類，非基金公司官方題材標籤；未辨識者保留待確認。']
    return nav,holdings,warnings


def load_comparison_fund(url):
    fund_id=moneydj_fund_id(url)
    if not fund_id: raise ValueError('請貼上支援的 MoneyDJ 基金完整網址。')
    route='wr' if fund_id.startswith('ACPS') else 'wb'
    urls=[f'https://tcbbankfund.moneydj.com/w/{route}/{route}{n:02d}.djhtm?a={fund_id}' for n in (1,2,4)]
    profile=read_url_tables(urls[0]);nav=read_url_tables(urls[1])
    try:holdings=read_url_tables(urls[2])
    except Exception:holdings=[]
    n,h,warnings=parse_pages(profile,nav,holdings,fund_id)
    return n,h,urls+warnings

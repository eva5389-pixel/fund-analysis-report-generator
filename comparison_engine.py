"""Common-date fund and investor-currency comparison, without FX double counting."""
from __future__ import annotations
from dataclasses import dataclass
from html import escape
import numpy as np
import pandas as pd

CURRENCIES = ['TWD', 'USD', 'EUR', 'JPY', 'GBP', 'AUD', 'CAD', 'CHF', 'HKD', 'CNY', 'SGD', 'NZD', 'ZAR']
BASIS = ['含息還原淨值／累積型', '未還原淨值（不含配息）', '未確認']


def read_nav(raw):
    frame = raw.rename(columns={'日期':'date','基金':'fund','基金名稱':'fund','淨值':'nav','幣別':'currency','級別幣別':'currency'}).copy()
    if not {'date','fund','nav'} <= set(frame):
        raise ValueError('淨值資料需要日期、基金、淨值欄位；幣別可在下一步確認。')
    frame['date'] = pd.to_datetime(frame['date'], errors='coerce').dt.normalize()
    frame['nav'] = pd.to_numeric(frame['nav'], errors='coerce')
    if frame[['date','fund','nav']].isna().any().any() or not np.isfinite(frame.nav).all() or (frame.nav <= 0).any():
        raise ValueError('淨值資料含空白、無效日期或非正數淨值，請修正後重新上傳。')
    frame['fund'] = frame.fund.astype(str).str.strip()
    if frame.fund.eq('').any() or frame.duplicated(['fund','date']).any():
        raise ValueError('基金名稱不可空白；同一基金同一天只能有一筆淨值。不同級別請用不同名稱。')
    return frame.sort_values(['fund','date'])


def common_period(nav, funds, start, end):
    selected = nav[nav.fund.isin(funds) & nav.date.between(pd.Timestamp(start), pd.Timestamp(end))]
    dates = selected.groupby('date').fund.nunique()
    common = dates[dates == len(funds)].index.sort_values()
    if len(common) < 2:
        raise ValueError('所選期間沒有至少兩個所有基金皆有淨值的共同日期。請延長期間或調整基金。')
    return common[0], common[-1]


def read_fx(raw):
    frame = raw.rename(columns={'日期':'date','幣別':'currency','台幣匯率':'twd_rate','一單位外幣兌台幣':'twd_rate'}).copy()
    if not {'date','currency','twd_rate'} <= set(frame):
        raise ValueError('匯率檔需要：日期、幣別、台幣匯率（1 單位該幣別可換多少台幣）。')
    frame['date'] = pd.to_datetime(frame.date, errors='coerce').dt.normalize()
    frame['currency'] = frame.currency.astype(str).str.upper().str.strip()
    frame['twd_rate'] = pd.to_numeric(frame.twd_rate, errors='coerce')
    if frame[['date','twd_rate']].isna().any().any() or not np.isfinite(frame.twd_rate).all() or (frame.twd_rate <= 0).any():
        raise ValueError('匯率必須是正數，日期必須有效。')
    if frame.duplicated(['date','currency']).any():
        raise ValueError('同一幣別同一天不可有重複匯率。')
    if (~frame.currency.isin(CURRENCIES)).any():
        raise ValueError('匯率幣別須使用支援的三碼代碼，例如 USD、TWD、JPY。')
    if (frame.loc[frame.currency.eq('TWD'), 'twd_rate'] != 1).any():
        raise ValueError('TWD 對台幣匯率必須為 1。')
    return frame


def endpoint_rates(fx, currencies, start, end):
    """Use exact, matching valuation dates. Never silently forward fill or interpolate."""
    rows = []
    for currency in sorted(set(currencies) | {'USD', 'TWD', 'JPY'}):
        vals = []
        for day in (start, end):
            if currency == 'TWD':
                vals.append(1.0)
            else:
                match = fx[(fx.currency == currency) & (fx.date == pd.Timestamp(day))]
                if len(match) != 1:
                    raise ValueError(f'缺少 {pd.Timestamp(day):%Y-%m-%d} 的 {currency}/TWD 匯率。請補上相同日期匯率；系統不自行沿用其他日期。')
                vals.append(float(match.twd_rate.iloc[0]))
        rows.append({'幣別':currency, '期初匯率':vals[0], '期末匯率':vals[1]})
    return pd.DataFrame(rows)


def compare(nav, metadata, rates, start, end):
    if metadata['基金'].duplicated().any():
        raise ValueError('基金設定不可重複。')
    if (~metadata['級別幣別'].isin(CURRENCIES)).any():
        raise ValueError('請先確認每檔基金的級別幣別。')
    table = rates.set_index('幣別')
    if table.index.duplicated().any() or not {'USD','TWD','JPY'} <= set(table.index):
        raise ValueError('匯率設定需包含且不得重複 USD、TWD、JPY。')
    values = table[['期初匯率','期末匯率']].apply(pd.to_numeric, errors='coerce')
    if values.isna().any().any() or not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
        raise ValueError('請填入全部期初及期末匯率，且匯率必須大於零。')
    if not values.loc['TWD'].eq(1).all():
        raise ValueError('TWD 的期初與期末匯率固定為 1。')
    result = []
    for _, meta in metadata.iterrows():
        name, currency = meta['基金'], meta['級別幣別']
        if currency not in values.index:
            raise ValueError(f'缺少 {currency} 匯率。')
        series = nav[(nav.fund == name) & nav.date.between(start,end)].set_index('date').nav
        if start not in series.index or end not in series.index:
            raise ValueError(f'{name}缺少共同起訖日淨值。')
        local = float(series.loc[end] / series.loc[start] - 1)
        c0, c1 = values.loc[currency]
        usd0, usd1 = values.loc['USD']
        jpy0, jpy1 = values.loc['JPY']
        twd_fx = c1 / c0 - 1
        usd_fx = (c1 / usd1) / (c0 / usd0) - 1
        jpy_fx = (c1 / jpy1) / (c0 / jpy0) - 1
        jpy = (1+local)*(1+jpy_fx)-1
        twd = (1+local)*(1+twd_fx)-1
        usd = (1+local)*(1+usd_fx)-1
        result.append({'基金':name, '級別幣別':currency, '報酬口徑':meta['報酬口徑'], '風險報酬等級':meta.get('風險報酬等級','未確認'),
            '期初淨值':float(series.loc[start]), '期末淨值':float(series.loc[end]),
            '原幣報酬 %':local*100, '台幣報酬 %':twd*100, '美元報酬 %':usd*100, '日幣報酬 %':jpy*100,
            '對日幣匯率變動 %':jpy_fx*100, '日幣匯率影響 百分點':(jpy-local)*100,
            '對台幣匯率變動 %':twd_fx*100, '台幣匯率影響 百分點':(twd-local)*100,
            '對美元匯率變動 %':usd_fx*100, '美元匯率影響 百分點':(usd-local)*100,
            '原幣觀測回撤 %':float((series/series.cummax()-1).min()*100), '淨值筆數':len(series)})
    return pd.DataFrame(result)


def theme_comparison(raw, funds, end):
    columns = ['基金','持股日期','投資題材','權重 %']
    coverage_cols = ['基金','持股日期','已揭露權重 %','未揭露權重 %','資料距期末 天']
    if raw is None or raw.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=coverage_cols)
    frame = raw.rename(columns={'基金':'fund','日期':'date','投資題材':'theme','題材':'theme','權重':'weight','代碼':'ticker'}).copy()
    if not {'fund','date','theme','weight'} <= set(frame):
        raise ValueError('持股題材檔需要基金、日期、投資題材、權重；權重以百分比填寫，例如 15 代表 15%。')
    frame['date']=pd.to_datetime(frame.date,errors='coerce').dt.normalize()
    frame['weight']=pd.to_numeric(frame.weight,errors='coerce')
    if frame[['date','fund','weight']].isna().any().any() or not np.isfinite(frame.weight).all() or (frame.weight < 0).any():
        raise ValueError('持股日期、基金或權重無效；此版只接受非負的持股權重。')
    frame['theme']=frame.theme.fillna('未分類').astype(str).replace('', '未分類')
    rows, coverage = [], []
    for fund in funds:
        subset = frame[(frame.fund==fund) & (frame.date <= end)]
        if subset.empty:
            continue
        day=subset.date.max(); latest=subset[subset.date==day]
        if 'ticker' in latest and latest.ticker.duplicated().any():
            raise ValueError(f'{fund}在{day:%Y-%m-%d}有重複持股代碼，請先合併。')
        total=float(latest.weight.sum())
        if total > 100.01:
            raise ValueError(f'{fund}的權重合計超過100%，請確認是否重複計算或使用槓桿；此版採單一題材分類。')
        coverage.append({'基金':fund,'持股日期':day.strftime('%Y-%m-%d'),'已揭露權重 %':total,'未揭露權重 %':max(0,100-total),'資料距期末 天':int((end-day).days)})
        for theme, weight in latest.groupby('theme').weight.sum().items():
            rows.append({'基金':fund,'持股日期':day.strftime('%Y-%m-%d'),'投資題材':theme,'權重 %':float(weight)})
    return pd.DataFrame(rows,columns=columns), pd.DataFrame(coverage,columns=coverage_cols)


def conclusions(performance, themes):
    lines=[]
    if performance['報酬口徑'].nunique() == 1 and performance['報酬口徑'].iloc[0] != '未確認':
        for basis in ['台幣','美元','日幣']:
            col=f'{basis}報酬 %'; best=performance.loc[performance[col].idxmax()]
            ties=performance.loc[np.isclose(performance[col],best[col]),'基金'].tolist()
            lines.append(f'本次選定基金中，{basis}報酬最高為{"、".join(ties)}，區間報酬 {best[col]:+.2f}%。')
    else:
        lines.append('基金報酬口徑不同或尚未確認，僅並列數值，不作績效排名。')
    for _, row in performance.iterrows():
        lines.append(f'{row["基金"]}原幣報酬 {row["原幣報酬 %"]:+.2f}%，匯率對台幣報酬影響 {row["台幣匯率影響 百分點"]:+.2f} 個百分點，對美元報酬影響 {row["美元匯率影響 百分點"]:+.2f} 個百分點，對日幣報酬影響 {row["日幣匯率影響 百分點"]:+.2f} 個百分點。')
    for fund in themes['基金'].unique():
        group=themes[themes['基金']==fund]; top=group.loc[group['權重 %'].idxmax()]
        lines.append(f'{fund}已揭露持股中，最大題材為{top["投資題材"]}，占基金 {top["權重 %"]:.2f}%；持股資料日 {top["持股日期"]}。')
    return lines


METHOD = [
    '換算報酬＝（1＋原幣報酬）×（期末換匯比率／期初換匯比率）－1。所有匯率均以1單位該幣別可換多少台幣輸入；美元與日幣報酬分別透過同期USD/TWD與JPY/TWD交叉換算。JPY請填1日圓兌台幣，例如0.22，不是100日圓的報價。',
    '匯率影響以百分點表示，等於換算後報酬減原幣報酬，包含基金報酬與匯率的交互作用，不可直接相加兩個百分比。',
    '級別幣別是淨值的報價幣別，不是底層資產幣別。基金內部避險及其成本已反映於該級別淨值，不另扣一次；投資人自行換匯的效果仍須計入。',
    '含息還原淨值／累積型資料按再投資基礎比較；未還原的配息型淨值不含現金配息，不代表總報酬。報酬口徑須由使用者依來源確認。',
    '採所有選定基金皆有淨值的共同起訖日。匯率需與這兩日一致；同日資料仍可能採不同收盤時點。結果未扣投資人的申贖費、換匯價差、稅費及外部避險成本。',
    '原幣觀測回撤只使用提供的淨值觀測點，稀疏月資料可能低估區間內回撤。僅提供期初、期末匯率時，不推算台幣／美元／日幣的日波動或回撤。',
    '題材為上傳分類或既有對照表標籤，不是未來報酬預測或正式績效歸因；每筆持股只歸一個題材，未揭露部位不視為現金。不同基金持股資料日期可能不同。'
]


def report_html(performance, themes, coverage, rates, start, end, sources, notes, sample=False):
    def table(df):
        if df.empty: return '<p>未提供資料。</p>'
        return df.to_html(index=False,escape=True,border=0,float_format=lambda v:f'{v:,.2f}')
    perfcols=['基金','級別幣別','原幣報酬 %','台幣報酬 %','美元報酬 %','日幣報酬 %']
    fxcols=['基金','台幣匯率影響 百分點','美元匯率影響 百分點','日幣匯率影響 百分點']
    sections=[('比較結論',''.join(f'<p>{escape(t)}</p>' for t in conclusions(performance,themes))),
              ('原幣 台幣 美元與日幣績效',table(performance[perfcols])),
              ('匯率拉抬與拖累',table(performance[fxcols])),
              ('淨值與報酬口徑',table(performance[['基金','期初淨值','期末淨值','報酬口徑','風險報酬等級','原幣觀測回撤 %','淨值筆數']])),
              ('題材配置比較',table(themes)),('持股資料涵蓋率',table(coverage)),('期初與期末匯率',table(rates)),
              ('計算方式與資料限制',''.join(f'<p>{escape(t)}</p>' for t in METHOD)),
              ('資料來源與補充說明',f'<p>{escape(sources)}</p><p>{escape(notes)}</p>')]
    title='基金績效題材與匯率比較報告'
    return '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>'+title+'</title><style>body{max-width:7.5in;margin:24px auto;font-family:DFKai-SB,"標楷體",serif;font-size:16pt;line-height:1.65;color:#222;background:white}h1{font-size:22pt}h2{font-size:18pt;margin-top:28px}table{width:100%;border-collapse:collapse;font-size:12pt;table-layout:auto}td,th{padding:8px;text-align:left;border-bottom:1px solid #ccc;overflow-wrap:anywhere}th{background:#eef2f6}p{white-space:pre-wrap}@media print{body{margin:0}h2{break-after:avoid}tr{break-inside:avoid}}</style><body><h1>'+title+'</h1>'+('<p><strong>示範資料｜以下基金、淨值與匯率均為模擬，非真實市場績效。</strong></p>' if sample else '')+f'<p>共同評估期間：{start:%Y-%m-%d} 至 {end:%Y-%m-%d}</p>'+''.join(f'<h2>{h}</h2>{body}' for h,body in sections)+'</body></html>'


def demo_data():
    dates=pd.date_range('2025-09-01','2026-09-01',freq='MS')
    nav=[]; hold=[]
    for name,currency,gain,themes in [('示範科技基金','USD',.20,[('AI運算',40),('雲端服務',25)]),('示範全球股票基金','EUR',.12,[('AI運算',15),('醫療創新',25)]),('示範台灣成長基金','TWD',.15,[('AI運算',30),('資料中心電力',20)])]:
        for i,day in enumerate(dates):
            nav.append(dict(date=day,fund=name,nav=100*(1+gain*i/(len(dates)-1)+.015*np.sin(i)),currency=currency))
        for theme,weight in themes:
            hold.append(dict(date=dates[-1],fund=name,theme=theme,weight=weight))
    fx=pd.DataFrame([dict(currency=c,date=day,twd_rate=rate) for c,a,b in [('USD',32.,30.),('EUR',35.,34.),('JPY',.22,.20)] for day,rate in [(dates[0],a),(dates[-1],b)]])
    return pd.DataFrame(nav),pd.DataFrame(hold),fx

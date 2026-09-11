import unittest
from urllib.parse import quote
import pandas as pd
from fund_analysis import moneydj_fund_id
from moneydj_comparison import parse_pages

URL='https://tcbbankfund.moneydj.com/main.html?sUrl=$W$WB$WB01]DJHTM{A}SH^71-2456'

class MoneyDJTests(unittest.TestCase):
    def test_wrapper_direct_and_encoded_ids(self):
        self.assertEqual(moneydj_fund_id(URL),'SHZ71-2456')
        self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/main.html?sUrl='+quote('$W$WB$WB01]DJHTM{A}SH^71-2456')),'SHZ71-2456')
        self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/w/wb/wb01.djhtm?a=SHZ71-2456'),'SHZ71-2456')
        self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/w/wr/wr01.djhtm?a=ACPS38-5818'),'ACPS38-5818')
        self.assertIsNone(moneydj_fund_id('https://moneydj.com.evil.example/?a=SHZ71-2456'))
    def test_all_nav_tables_anchor_and_missing_size(self):
        profile=[pd.DataFrame([['基金名稱','測試美元基金'],['計價幣別','美元']]),pd.DataFrame({'淨值日期':['2026/01/05']})]
        nav=[pd.DataFrame({'日期':['01/05','01/02'],'淨值':[11,10.9]}),pd.DataFrame({'日期':['12/31'],'淨值':[10.8]})]
        h=pd.DataFrame({'持股名稱':['NVIDIA CORP'],'比例':['6.69%']})
        h.attrs['source_text']='資料月份：2025年11月'
        n,hold,notes=parse_pages(profile,nav,[h],'SHZ71-2456')
        self.assertEqual(len(n),3)
        self.assertEqual(n.date.min(),pd.Timestamp('2025-12-31'))
        self.assertTrue(n.currency.eq('USD').all())
        self.assertEqual(hold.date.iloc[0],pd.Timestamp('2025-11-30'))
        h.attrs.clear()
        _,hold,notes=parse_pages(profile,nav,[h],'SHZ71-2456')
        self.assertTrue(hold.empty)
        self.assertTrue(any('未找到明確月份' in item for item in notes))

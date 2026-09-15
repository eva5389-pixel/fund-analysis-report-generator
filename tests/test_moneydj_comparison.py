import unittest
from urllib.parse import quote
import pandas as pd
from fund_analysis import moneydj_fund_id
from moneydj_comparison import parse_pages

URL='https://tcbbankfund.moneydj.com/main.html?sUrl=$W$WB$WB01]DJHTM{A}SH^71-2456'

class MoneyDJTests(unittest.TestCase):
    def test_domestic_provider_route_from_source_page(self):
        from unittest.mock import patch
        from moneydj_comparison import load_comparison_fund
        from fund_analysis import load_moneydj_fund, moneydj_fund_route
        profile=[pd.DataFrame([['基金名稱','元大新主流基金A不配息(台幣)'],['計價幣別','台幣']]),pd.DataFrame({'淨值日期':['2026/09/14']})]
        nav=[pd.DataFrame({'日期':['09/14','09/11'],'淨值':[180.08,179.0]})]
        for path in ('$W$WR$WR01]DJHTM{A}ACYT11-5407', quote('$W$WR$WR01]DJHTM{A}ACYT11-5407')):
            url='https://tcbbankfund.moneydj.com/main.html?sUrl='+path
            for loader in (load_comparison_fund, load_moneydj_fund):
                with patch('moneydj_comparison.read_url_tables', side_effect=[profile,nav,[]]) as read:
                    result,_,_=loader(url)
                    self.assertEqual(len(result),2)
                    self.assertEqual(result.fund.iloc[0],'元大新主流基金A不配息(台幣)')
                    self.assertEqual([c.args[0] for c in read.call_args_list],[
                        f'https://tcbbankfund.moneydj.com/w/wr/wr{n:02d}.djhtm?a=ACYT11-5407' for n in (1,2,4)])
        self.assertEqual(moneydj_fund_route('https://tcbbankfund.moneydj.com/w/wr/wr01.djhtm?a=ACYT11-5407'),'wr')
        self.assertEqual(moneydj_fund_route(URL),'wb')

    def test_wrapper_direct_and_encoded_ids(self):
        self.assertEqual(moneydj_fund_id(URL),'SHZ71-2456')
        self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/main.html?sUrl='+quote('$W$WB$WB01]DJHTM{A}SH^71-2456')),'SHZ71-2456')
        self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/w/wb/wb01.djhtm?a=SHZ71-2456'),'SHZ71-2456')
        self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/w/wr/wr01.djhtm?a=ACPS38-5818'),'ACPS38-5818')
        self.assertIsNone(moneydj_fund_id('https://moneydj.com.evil.example/?a=SHZ71-2456'))
    def test_other_offshore_provider_ids(self):
        for code in ('IS^04-0104', 'ISZ04-0104', 'SH^71-2456'):
            expected=code.replace('^','Z')
            self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/main.html?sUrl='+quote('$W$WB$WB02]DJHTM{A}'+code)),expected)
            self.assertEqual(moneydj_fund_id('https://tcbbankfund.moneydj.com/w/wb/wb02.djhtm?a='+code),expected)
        from unittest.mock import patch
        from moneydj_comparison import load_comparison_fund
        with patch('moneydj_comparison.read_url_tables', return_value=[]) as read, patch('moneydj_comparison.parse_pages', return_value=(None,None,[])):
            load_comparison_fund('https://tcbbankfund.moneydj.com/main.html?sUrl=$W$WB$WB02]DJHTM{A}IS^04-0104')
            self.assertEqual(read.call_args_list[0].args[0], 'https://tcbbankfund.moneydj.com/w/wb/wb01.djhtm?a=ISZ04-0104')

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

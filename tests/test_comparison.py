import unittest
from pathlib import Path
import pandas as pd
from comparison_engine import *

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.start=pd.Timestamp('2025-01-01'); self.end=pd.Timestamp('2026-01-01')
        self.nav=read_nav(pd.DataFrame({'日期':[self.start,self.end]*2,'基金':['美元基金']*2+['台幣基金']*2,'淨值':[100,110,100,110]}))
        self.meta=pd.DataFrame({'基金':['美元基金','台幣基金'],'級別幣別':['USD','TWD'],'報酬口徑':[BASIS[0]]*2,'避險級別':['避險級別','非避險級別']})
        self.rates=pd.DataFrame({'幣別':['USD','TWD'],'期初匯率':[32.,1.],'期末匯率':[30.,1.]})
    def test_conversion_and_hedged_class_not_double_counted(self):
        p=compare(self.nav,self.meta,self.rates,self.start,self.end).set_index('基金')
        self.assertAlmostEqual(p.loc['美元基金','台幣報酬 %'],3.125)
        self.assertAlmostEqual(p.loc['美元基金','美元報酬 %'],10)
        self.assertAlmostEqual(p.loc['美元基金','台幣匯率影響 百分點'],-6.875)
        self.assertAlmostEqual(p.loc['台幣基金','台幣報酬 %'],10)
        self.assertAlmostEqual(p.loc['台幣基金','美元報酬 %'],17.3333333333)
    def test_shared_dates(self):
        extra=pd.DataFrame({'date':[pd.Timestamp('2024-12-01')],'fund':['美元基金'],'nav':[90]})
        a,b=common_period(pd.concat([self.nav,extra]),self.meta['基金'],pd.Timestamp('2024-12-01'),self.end)
        self.assertEqual(a,self.start)
        with self.assertRaises(ValueError): common_period(self.nav,self.meta['基金'],self.end,self.end)
    def test_bad_rates_and_missing_dates(self):
        r=self.rates.copy();r.loc[0,'期末匯率']=None
        with self.assertRaises(ValueError): compare(self.nav,self.meta,r,self.start,self.end)
        fx=read_fx(pd.DataFrame({'日期':['2024-12-31','2026-01-01'],'幣別':['USD']*2,'台幣匯率':[32,30]}))
        with self.assertRaises(ValueError): endpoint_rates(fx,['USD'],self.start,self.end)
    def test_invalid_nav(self):
        with self.assertRaises(ValueError): read_nav(pd.concat([self.nav,self.nav]))
        with self.assertRaises(ValueError): read_nav(self.nav.assign(nav=0))
    def test_theme_asof_and_coverage(self):
        holdings=pd.DataFrame({'基金':['美元基金']*3,'日期':['2025-12-01','2025-12-01','2026-02-01'],'投資題材':['AI','醫療','未來資料'],'權重':[30,20,90]})
        t,c=theme_comparison(holdings,['美元基金'],self.end)
        self.assertEqual(set(t['投資題材']),{'AI','醫療'})
        self.assertEqual(c.iloc[0]['未揭露權重 %'],50)
        with self.assertRaises(ValueError):theme_comparison(holdings.assign(權重=101),['美元基金'],self.end)
    def test_mixed_basis_does_not_rank(self):
        meta=self.meta.copy();meta.loc[0,'報酬口徑']=BASIS[1]
        p=compare(self.nav,meta,self.rates,self.start,self.end)
        t,c=theme_comparison(None,[],self.end)
        self.assertIn('不作績效排名',conclusions(p,t)[0])
        output=report_html(p,t,c,self.rates,self.start,self.end,'<script>bad</script>','',True)
        self.assertIn('模擬',output);self.assertNotIn('<script>',output)
    def test_app_demo_and_original_view(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        app.button(key='cmp_prepare').click().run()
        self.assertEqual(len(app.get('download_button')),3)
        app.session_state['analysis_view']='原有基金深度分析'
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value,'基金分析報告產生器')

if __name__=='__main__':unittest.main()

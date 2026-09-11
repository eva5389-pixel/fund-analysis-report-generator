import unittest
from unittest.mock import patch
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from moneydj_comparison import parse_pages

class IncrementalTests(unittest.TestCase):
    def test_domestic_nav_year_from_page(self):
        profile=[pd.DataFrame([['基金名稱','統一奔騰基金'],['計價幣別','台幣']])]
        nav=pd.DataFrame({'日期':['01/05','12/31'],'淨值':[110,100]})
        nav.attrs['source_text']="var bDate = $.datepicker.formatDate( 'yy/mm/dd', $.datepicker.parseDate('yy-mm-dd', '2025-1-5') ), eDate = $.datepicker.formatDate( 'yy/mm/dd', $.datepicker.parseDate('yy-mm-dd', '2026-1-5') )"
        n,h,d=parse_pages(profile,[nav],[],'ACPS10-5808')
        self.assertEqual(list(n.date.dt.year),[2025,2026])
    def test_add_duplicate_failure_and_remove(self):
        def load(url):
            if '9999' in url: raise ValueError('測試來源失敗')
            name='甲基金' if '5808' in url else '乙基金'
            n=pd.DataFrame({'date':pd.to_datetime(['2026-08-01','2026-09-01']),'fund':[name]*2,'nav':[100,110],'currency':['TWD']*2})
            return n,pd.DataFrame(),[]
        with patch('comparison_ui.load_comparison_url',side_effect=load):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py')).run()
            def add(code):
                app.text_input(key='cmp_single_url').set_value('https://tcbbankfund.moneydj.com/w/wr/wr02.djhtm?a='+code).run()
                app.button(key='cmp_add_url').click().run()
                self.assertFalse(app.exception)
            add('ACPS10-5808')
            self.assertEqual(len(app.session_state.cmp_fund_basket),1)
            self.assertEqual(app.text_input(key='cmp_single_url').value,'')
            add('ACPS10-5808')
            self.assertEqual(len(app.session_state.cmp_fund_basket),1)
            add('ACPS38-5818')
            self.assertEqual(len(app.session_state.cmp_fund_basket),2)
            add('ACPS99-9999')
            self.assertEqual(len(app.session_state.cmp_fund_basket),2)
            app.button(key='cmp_remove_ACPS10-5808').click().run()
            self.assertEqual(len(app.session_state.cmp_fund_basket),1)
            self.assertFalse(app.exception)

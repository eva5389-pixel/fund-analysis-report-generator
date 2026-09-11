import unittest
from unittest.mock import patch, Mock
import pandas as pd
from auto_metadata import infer_metadata, fetch_fx

class AutoTests(unittest.TestCase):
    def test_evidence_and_unknown(self):
        n=pd.DataFrame({'fund':['基金美元非避險'],'currency':['USD']})
        m=infer_metadata(n,n.fund[0],moneydj=True)
        self.assertEqual(m['避險級別'],'非避險級別')
        self.assertEqual(m['報酬口徑'],'未還原淨值（不含配息）')
        n['fund']='基金美元'
        self.assertEqual(infer_metadata(n,n.fund[0])['避險級別'],'未確認')
        n['fund']='基金美元避險'
        self.assertEqual(infer_metadata(n,n.fund[0])['避險級別'],'避險級別')
    def test_fx_inversion_and_exact_dates(self):
        def response(date):
            r=Mock(); r.url='https://api.frankfurter.dev/v2/rates'
            r.json.return_value=[{'date':date,'base':'TWD','quote':'USD','rate':0.03125},{'date':date,'base':'TWD','quote':'JPY','rate':5}]
            return r
        with patch('auto_metadata.requests.get',side_effect=[response('2026-01-02'),response('2026-01-05')]):
            rates,_=fetch_fx(('TWD','USD','JPY'),'2026-01-02','2026-01-05')
            self.assertEqual(rates.set_index('幣別').loc['USD','期初匯率'],32)
            self.assertEqual(rates.set_index('幣別').loc['JPY','期末匯率'],0.2)
        with patch('auto_metadata.requests.get',return_value=response('2026-01-01')):
            with self.assertRaises(ValueError): fetch_fx(('TWD','USD','JPY'),'2026-01-02','2026-01-05')

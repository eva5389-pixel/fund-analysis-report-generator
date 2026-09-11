import unittest
from unittest.mock import patch, Mock
import pandas as pd
from auto_metadata import infer_metadata, fetch_fx

class AutoTests(unittest.TestCase):
    def test_risk_evidence(self):
        n=pd.DataFrame({'fund':['基金'],'currency':['TWD'],'risk_level':['RR5']})
        self.assertEqual(infer_metadata(n,'基金')['風險報酬等級'],'RR5')
        n['risk_level']=''
        self.assertEqual(infer_metadata(n,'基金')['風險報酬等級'],'未確認')
        from risk_metadata import parse_risk
        self.assertEqual(parse_risk('風險報酬等級 RR5'),'RR5')
        self.assertEqual(parse_risk('評等五星'),'未確認')
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

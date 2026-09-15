import unittest
from unittest.mock import patch
from fund_analysis import moneydj_fund_id, read_url_tables
class ImportTests(unittest.TestCase):
 def test_japan_provider_ids(self):
  for c in ['IOFA3-2819','IOFA4-2820','AN^33-1312','ACPS10-5808']:
   for u in ['https://tcbbankfund.moneydj.com/main.html?sUrl=$W$WB$WB01]DJHTM{A}'+c,'https://tcbbankfund.moneydj.com/w/wb/wb01.djhtm?a='+c]:
    self.assertEqual(moneydj_fund_id(u),c.replace('^','Z'))
  self.assertIsNone(moneydj_fund_id('https://moneydj.com.evil.example/?a=IOFA3-2819'))
 def test_html_and_missing_table(self):
  class Response:
   is_redirect=False;is_permanent_redirect=False;encoding='utf-8';headers={'content-type':'text/html'};url='https://example.com/fund'
   def raise_for_status(self):pass
   def iter_content(self,n):yield self.body
  r=Response()
  with patch('fund_analysis._validate_public_url',side_effect=lambda u:u),patch('fund_analysis.requests.get',return_value=r):
   r.body='<html><body>沒有表格</body></html>'.encode()
   with self.assertRaisesRegex(ValueError,'沒有可讀取的資料表'):read_url_tables(r.url)
   r.body='<table><tr><th>基金</th><th>淨值</th></tr><tr><td>日本基金</td><td>12.3</td></tr></table>'.encode()
   t=read_url_tables(r.url)
   self.assertEqual(t[0].iloc[0]['基金'],'日本基金')
   self.assertEqual(t[0].iloc[0]['淨值'],12.3)

import unittest
from fund_analysis import _holding_identity
class ThemeTests(unittest.TestCase):
    def test_six_fund_snapshot_has_no_unclassified_disclosed_holdings(self):
        import json
        from pathlib import Path
        from moneydj_comparison import holding_identity
        funds=json.loads((Path(__file__).parent/'fixtures/six_fund_holdings.json').read_text())
        self.assertEqual(len(funds),6)
        for fund in funds:
            for row in fund['holdings']:
                self.assertNotEqual(holding_identity(row['name'])[2], '其他／待確認', row['name'])
        self.assertEqual(holding_identity('ASPEED TECHNOLOGY INC,資訊科技,台灣'),holding_identity('信驊'))
        self.assertNotEqual(holding_identity('MITSUBISHI HEAVY INDUSTRIES')[2],holding_identity('MITSUBISHI CORP')[2])
        self.assertEqual(holding_identity('SUMITOMO CORP,房地產,日本')[1], '綜合商社')

    def test_yuanta_new_mainstream_unclassified_holdings(self):
        from moneydj_comparison import holding_identity
        expected = {'川湖': '伺服器滑軌與機櫃機構件', '信驊': '伺服器遠端管理晶片BMC', '聯鈞': '光通訊雷射元件封裝測試'}
        for name, theme in expected.items():
            self.assertEqual(holding_identity(name)[2], theme)

    def test_known_and_unknown(self):
        for name in ['Amazon.com','Nebius Group NV','Tesla','Modine Manufacturing Co','Sumitomo Electric Industries','Ajinomoto Co','Carvana Co','Allegro MicroSystems','Coherent']:
            self.assertNotEqual(_holding_identity(name)[2],'其他／待確認')
        self.assertEqual(_holding_identity('Unidentified Holding')[2],'其他／待確認')
        self.assertEqual(_holding_identity('Ajinomoto Co')[2],'食品消費與ABF封裝材料')

    def test_dragon_and_intel_word_boundary(self):
        from moneydj_comparison import holding_identity
        for name in ['MTAR TECHNOLOGIES LTD','高力','STERLITE TECHNOLOGIES LTD','AEHR TEST SYSTEMS','YUANJIE SEMICONDUCTOR TECH-A','ROBOTECHNIK INTELLIGENT TE-A','LUMENTUM HOLDINGS INC','聯亞']:
            self.assertNotEqual(holding_identity(name)[2],'其他／待確認')
        self.assertEqual(holding_identity('Intel Corp')[0],'INTC')
        self.assertNotEqual(holding_identity('ROBOTECHNIK INTELLIGENT TE-A')[0],'INTC')
        self.assertEqual(holding_identity('UNKNOWN INTELLIGENT LTD')[2],'其他／待確認')

import unittest
from fund_analysis import _holding_identity
class ThemeTests(unittest.TestCase):
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

import unittest
from fund_analysis import _holding_identity
class ThemeTests(unittest.TestCase):
    def test_known_and_unknown(self):
        for name in ['Amazon.com','Nebius Group NV','Tesla','Modine Manufacturing Co','Sumitomo Electric Industries','Ajinomoto Co','Carvana Co','Allegro MicroSystems','Coherent']:
            self.assertNotEqual(_holding_identity(name)[2],'其他／待確認')
        self.assertEqual(_holding_identity('Unidentified Holding')[2],'其他／待確認')
        self.assertEqual(_holding_identity('Ajinomoto Co')[2],'食品消費與ABF封裝材料')

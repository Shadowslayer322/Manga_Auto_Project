import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from typeo_core import opening_punctuation,compose_proportional,typography_ratio,resolve_font
class NewTypographyTests(unittest.TestCase):
 def test_opening_signs(self):
  for a,b in [('Hola!','\u00a1Hola!'),('Vienes?','\u00bfVienes?'),('Qu\u00e9?!','\u00a1\u00bfQu\u00e9?!'),('\u00a1Hola!','\u00a1Hola!')]:self.assertEqual(opening_punctuation(a),b)
 def test_fonts_have_spanish_signs(self):
  for role in ('normal','grito','fuera_globo','titulo','murmullo'):
   f=resolve_font(role)
   self.assertTrue(all(ord(c) in f.cmap for c in '\u00bf\u00a1'))
 def test_grows_to_raw_reference_instead_of_remaining_at_18(self):
  z={'id':'test','box_contenedor':[0,0,600,240],'alto_letra_ingles_px':40,'minimo_px':12,'margen_revision_px':0}
  lines,size,_,_=compose_proportional('Hola mundo',resolve_font('normal'),z,'normal')
  self.assertGreater(size,18)
  self.assertEqual(' '.join(lines),'Hola mundo')
 def test_uniform_scale_keeps_line_breaks(self):
  z={'id':'test','box_contenedor':[0,0,360,240],'alto_letra_ingles_px':40,'minimo_px':12,'margen_revision_px':0}
  bigger={**z,'box_contenedor':[0,0,720,480],'alto_letra_ingles_px':80}
  a=compose_proportional('Este texto ocupa varias lineas',resolve_font('normal'),z,'normal')
  b=compose_proportional('Este texto ocupa varias lineas',resolve_font('normal'),bigger,'normal')
  self.assertEqual(a[0],b[0]);self.assertAlmostEqual(b[1]/a[1],2,delta=.05)
 def test_style_ratios(self):
  self.assertAlmostEqual(typography_ratio('normal'),20/18)
  self.assertAlmostEqual(typography_ratio('titulo'),20/22)
  self.assertAlmostEqual(typography_ratio('murmullo'),20/22)
if __name__=='__main__':unittest.main()

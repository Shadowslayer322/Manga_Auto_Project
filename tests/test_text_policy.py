from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from text_policy import protected_reason
from ocr_ingles import enrich_zones,geometry_from_record
from typeo_core import sha256,bind_translation,compose,resolve_font,english_reference_size


class TextPolicyTests(unittest.TestCase):
    def test_standalone_sounds_numbers_and_punctuation_are_protected(self):
        for text in ['VRRR','BRRR','TMP','12','3:36 AM','?!','!','…']:
            self.assertIsNotNone(protected_reason(text),text)
        for text in ['¡Hola!','120 años','I have a bad feeling about this...']:
            self.assertIsNone(protected_reason(text),text)

    def test_protected_pixels_are_removed_even_from_an_old_full_mask(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder)/'01.png';cv2.imwrite(str(raw),np.full((140,180,3),255,np.uint8))
            line={'texto':'3:36 AM','confianza':.99,'box':[30,40,110,60],
                  'poligono':[[30,40],[110,40],[110,60],[30,60]]}
            zone={'id':1,'origen':'ocr_ingles','box_contenedor':[25,35,115,65]}
            ocr={'raw_sha256':sha256(raw),'lineas':[line],'pendientes':[]}
            zones,mask,ocr=enrich_zones(raw,[zone],np.full((140,180),255,np.uint8),ocr,{'confianza_nueva_zona':.9})
            expanded=cv2.dilate(mask,np.ones((5,5),np.uint8))
            self.assertFalse(expanded[40:61,30:111].any())
            self.assertFalse(geometry_from_record(raw,{'zonas':zones})['zonas'])
            self.assertFalse(ocr['bloques'])

    def test_old_protected_translation_does_not_require_spanish(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'01_RAW').mkdir()
            raw=Path(folder)/'01_RAW/01.png';cv2.imwrite(str(raw),np.full((40,40,3),255,np.uint8))
            page={'archivo':'01.png','raw_sha256':sha256(raw),'width':40,'height':40,'zonas':[],
                  'zonas_protegidas':[{'id':'01_01','texto_original':'BRRR'}]}
            result=bind_translation({'paginas':[{'archivo':'01.png','bloques':[{'id':'01_01','texto_original':'BRRR'}]}]}, {'paginas':[page]},Path(folder))
            self.assertEqual(result['paginas'][0]['bloques'],[])

    def test_new_font_fits_readably_and_preserves_complete_phrase(self):
        font=resolve_font('normal')
        zone={'id':'01_01','box_contenedor':[0,0,181,265],'alto_letra_ingles_px':42.3,
              'trazo_px':5,'margen_revision_px':1,'minimo_px':18,'tipo_contenedor':'rotulo'}
        lines,size,shape,split=compose('tengo un mal presentimiento...',font,zone,'normal')
        self.assertGreaterEqual(size,zone['minimo_px'])
        self.assertLessEqual(size,english_reference_size(font,zone))
        self.assertEqual(''.join(lines).replace(' ','').replace('-',''),'tengounmalpresentimiento...')

    def test_number_attached_to_a_phrase_is_cleaned_with_the_phrase(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder)/'01.png';image=np.full((140,220,3),255,np.uint8)
            cv2.putText(image,'120',(30,55),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),2)
            cv2.putText(image,'YEARS',(30,80),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),2);cv2.imwrite(str(raw),image)
            def line(text,y,width):return {'texto':text,'confianza':.99,'box':[25,y,25+width,y+25], 'poligono':[[25,y],[25+width,y],[25+width,y+25],[25,y+25]]}
            zone={'id':1,'origen':'ocr_ingles','box_contenedor':[20,25,150,90]}
            ocr={'raw_sha256':sha256(raw),'lineas':[line('120',30,50),line('YEARS',55,80)],'pendientes':[]}
            zones,mask,ocr=enrich_zones(raw,[zone],np.zeros((140,220),np.uint8),ocr,{'confianza_nueva_zona':.9})
            self.assertFalse(ocr['protegidos']);self.assertTrue(mask[30:55,25:75].any())
            self.assertIn('120',ocr['bloques'][0]['texto_original'])

    def test_photoshop_open_document_and_protection_guards(self):
        subprocess.run(['node',str(Path(__file__).with_name('protecciones_ps_harness.js'))],check=True,capture_output=True)


if __name__=='__main__':unittest.main()

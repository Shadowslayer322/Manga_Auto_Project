import unittest,sys,tempfile
import cv2
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from ocr_ingles import text_area_mask,enrich_zones
from typeo_core import sha256
class SolidTextMaskTests(unittest.TestCase):
 def test_full_interior_and_margin(self):
  im=np.full((80,160,3),255,np.uint8)
  m=text_area_mask(im,[[20,20],[120,20],[120,45],[20,45]],6)
  self.assertTrue(np.all(m[20:46,20:121]==255))
  self.assertEqual(m[30,15],255)
  self.assertEqual(m[30,5],0)
 def test_diagonal_does_not_fill_bounding_box(self):
  m=text_area_mask(np.zeros((120,160,3),np.uint8),[[20,70],[110,20],[120,40],[30,90]],3)
  self.assertEqual(m[50,70],255)
  self.assertEqual(m[25,25],0)
 def test_border_clips_to_page(self):
  m=text_area_mask(np.zeros((30,30,3),np.uint8),[[0,0],[20,0],[20,10],[0,10]],6)
  self.assertEqual(m[0,0],255);self.assertEqual(m[-1,-1],0)
 def test_low_confidence_new_zone_is_pending_and_not_cleaned(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   raw=Path(folder)/'01.png';cv2.imwrite(str(raw),np.full((80,160,3),255,np.uint8))
   line={'texto':'HELLO','confianza':.85,'poligono':[[20,20],[120,20],[120,45],[20,45]],'box':[20,20,120,45]}
   ocr={'lineas':[line],'pendientes':[]}
   zones,mask,result=enrich_zones(raw,[],np.zeros((80,160),np.uint8),ocr,{'confianza_nueva_zona':.9})
   self.assertFalse(zones);self.assertFalse(np.any(mask));self.assertEqual(len(result['pendientes']),1)

 def test_complex_line_replaces_legacy_band_and_preserves_reviewed_art(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   raw=Path(folder)/'01.png'
   image=np.full((90,200,3),215,np.uint8)
   cv2.putText(image,'HELLO',(25,58),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),3)
   cv2.circle(image,(155,50),9,(0,0,0),2)
   cv2.imwrite(str(raw),image)
   polygon=[[20,30],[170,30],[170,65],[20,65]]
   art=[[144,39],[166,39],[166,61],[144,61]]
   line={'texto':'HELLO','confianza':.99,'poligono':polygon,'box':[20,30,170,65]}
   ocr={'raw_sha256':sha256(raw),'lineas':[line],'pendientes':[]}
   config={'confianza_nueva_zona':.9,'limpieza_revisada':{
       sha256(raw):{'arte_protegido':[art]}}}
   old=text_area_mask(image,polygon)
   zones,mask,result=enrich_zones(raw,[],old,ocr,config)
   self.assertEqual(zones[0]['ocr_id'],'01_01')
   self.assertFalse(zones[0]['fondo_limpieza_blanco'])
   self.assertTrue((mask[35:62,25:121][image[35:62,25:121,0]==0]>0).all())
   self.assertFalse(mask[39:62,144:167].any())
   self.assertLess(np.count_nonzero(mask),np.count_nonzero(old)*.65)
   self.assertEqual(result['arte_protegido'],[art])
if __name__=='__main__':unittest.main()

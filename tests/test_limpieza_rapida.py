import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from limpieza_rapida import ENGINE_VERSION,MaskEngine,partition_mask,flat_white_background
from pipeline_manga import procesar_pagina
from prueba_segmentacion_pixel import procesar_mascara_pagina
from pipeline_completo import prepare_run,masks_worker,Events
from typeo_core import sha256,write_json,read_json,TypeoError


class FastCleaningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='clean_fixture_')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        (self.base/'01_RAW').mkdir();(self.base/'config').mkdir();(self.base/'04_DIAGNOSTICO').mkdir()
        self.image=np.full((240,400,3),255,np.uint8)
        cv2.putText(self.image,'HELLO WORLD',(70,110),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
        self.raw=self.base/'01_RAW/01.png';cv2.imwrite(str(self.raw),self.image)
        self.seg=np.ones((240,400),np.float32)

    def models(self,boxes):
        class Session:
            calls=0
            def run(inner,*args):
                inner.calls+=1
                seg=np.full((1,1,1024,1024),.9,np.float32)
                det=np.zeros((1,2,1024,1024),np.float32)
                det[:,:,360:490,170:740]=.9
                return None,seg,det
        yolo=lambda *a,**k:[SimpleNamespace(boxes=[SimpleNamespace(xyxy=np.array([b]),conf=[.9]) for b in boxes])]
        return yolo,Session()

    def test_horizontal_dialogue_uses_white_brush(self):
        yolo,session=self.models([[40,40,350,170]])
        info,seg=procesar_pagina(str(self.raw),yolo,session,return_maps=True)
        self.assertEqual(session.calls,1)
        self.assertEqual(info['zonas'][0]['origen'],'globo_solido_yolo')
        mask,_=procesar_mascara_pagina(str(self.raw),info,seg_map=seg)
        self.assertGreater(np.count_nonzero(mask),100)
        self.assertEqual(session.calls,1)
        self.assertEqual(np.count_nonzero(mask[:30]),0)

    def test_narration_is_recovered_when_yolo_has_no_boxes(self):
        yolo,session=self.models([])
        info,seg=procesar_pagina(str(self.raw),yolo,session,return_maps=True)
        self.assertTrue(info['zonas'])
        self.assertTrue(all(z['origen']=='globo_solido_yolo' for z in info['zonas']))

    def test_mask_cannot_leak_outside_white_container(self):
        info={'zonas':[{'origen':'globo_solido_yolo','rectangulos_texto':[[50,70,330,120]],
                        'poligono_contenedor':[[60,60],[340,60],[340,140],[60,140]]}]}
        mask,_=procesar_mascara_pagina(str(self.raw),info,seg_map=self.seg)
        self.assertFalse(mask[:60].any());self.assertFalse(mask[:, :60].any())

    def test_partition_preserves_every_selected_pixel(self):
        mask=np.zeros((400,400),np.uint8)
        for x,y in ((20,20),(200,20),(20,250),(250,250),(120,150)):
            mask[y:y+20,x:x+20]=255
        parts=partition_mask(mask)
        self.assertEqual(len(parts),3)
        self.assertTrue(np.array_equal(np.bitwise_or.reduce(parts),mask))

    def test_production_writes_only_masks_and_small_state(self):
        engine=object.__new__(MaskEngine);engine.base=self.base;engine.yolo,engine.session=self.models([[40,40,350,170]])
        cfg=self.base/'config/ocr.json';write_json(cfg,{})
        engine.ocr=SimpleNamespace(config={'confianza_nueva_zona':.9},page=lambda raw,zones:{'version':3,'raw_sha256':sha256(raw),
            'config_path':str(cfg),'config_sha256':sha256(cfg),'lineas':[],'pendientes':[]})
        record=engine.page(self.raw,self.base/'masks')
        self.assertEqual(engine.session.calls,1)
        self.assertEqual(record['pares'],[])
        self.assertEqual({p.suffix for p in (self.base/'masks').iterdir()},{'.png','.json'})

    def test_clean_only_does_not_need_old_chapter_geometry(self):
        job=prepare_run(self.base/'missing.json',self.base/'FINAL',base=self.base,clean_only=True)
        self.assertTrue(job['clean_only']);self.assertEqual(job['pages'][0]['page'],'01.png')
        self.assertFalse(list(self.base.rglob('*.psd')))

    def test_first_page_masks_publish_before_second_page_inference(self):
        cv2.imwrite(str(self.base/'01_RAW/02.png'),self.image)
        job=prepare_run(self.base/'missing.json',self.base/'FINAL',base=self.base,clean_only=True)
        write_json(job['opened'],{'job_id':job['job_id']})
        from limpieza_rapida import signature
        class FakeEngine:
            def __init__(inner,base):pass
            def page(inner,raw,output):
                if Path(raw).name=='02.png':self.assertTrue(Path(job['pages'][0]['clean_ready']).exists())
                output.mkdir(parents=True,exist_ok=True);p=output/'pincel.png'
                cv2.imwrite(str(p),np.zeros((240,400),np.uint8));info=signature(p)
                config=output/'config.json';write_json(config,{})
                ocr=output/'ocr.json';write_json(ocr,{'version':3,'config_path':str(config),'config_sha256':sha256(config)})
                return {'engine_version':ENGINE_VERSION,'raw_sha256':sha256(raw),'pincel':info,'genfill':info,'pares':[],
                        'ocr':{'path':str(ocr),'sha256':sha256(ocr)}}
        import threading
        with patch('limpieza_rapida.MaskEngine',FakeEngine):
            masks_worker(job,threading.Event(),Events(Path(job['folder'])/'eventos.jsonl'),base=self.base)
        self.assertTrue(all(Path(p['clean_ready']).exists() for p in job['pages']))

    def test_clean_only_cannot_replace_a_typeset_psd(self):
        (self.base/'FINAL').mkdir();path=self.base/'FINAL/01.psd'
        path.write_bytes(b'8BPS-test-8BIMTySh-editable text')
        with self.assertRaisesRegex(TypeoError,'texto editable'):
            prepare_run(self.base/'missing.json',self.base/'FINAL',base=self.base,clean_only=True,replace=True)
        self.assertIn(b'editable text',path.read_bytes())

    def test_light_screentone_is_not_treated_as_flat_white(self):
        gray=np.full((200,300),255,np.uint8)
        poly=[[0,0],[299,0],[299,199],[0,199]]
        cv2.putText(gray,'HELLO',(30,100),cv2.FONT_HERSHEY_SIMPLEX,1,0,2)
        self.assertTrue(flat_white_background(gray,poly))
        for y in range(10,190,8):
            for x in range(10,290,8):cv2.circle(gray,(x,y),1,0,-1)
        self.assertFalse(flat_white_background(gray,poly))


if __name__=='__main__':unittest.main()

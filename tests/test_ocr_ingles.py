from pathlib import Path
import math
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ocr_ingles import (valid_english,deduplicate,paragraph_text,box_of,glyph_mask,
                        enrich_zones,geometry_from_record,proposed_context)
from typeo_core import (sha256,write_json,read_json,bind_translation,build_items,resolve_font,TypeoError)
from pipeline_completo import prepare_run,translation_worker,Events


def line(text,x,y,width=150,height=20,angle=0,confidence=.99):
    p=np.array([[x,y],[x+width,y],[x+width,y+height],[x,y+height]],np.float32)
    c,s=math.cos(angle),math.sin(angle);p=p@np.array([[c,s],[-s,c]])+[100,100]
    return {'texto':text,'confianza':confidence,'poligono':p.tolist(),'box':box_of(p),'pasada':'prueba'}


class EnglishOCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='ocr_fixture_')
        self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        (self.base/'01_RAW').mkdir();(self.base/'04_DIAGNOSTICO').mkdir()
        self.raw=self.base/'01_RAW/01.png';self.image=np.full((250,400,3),255,np.uint8)
        cv2.putText(self.image,'SEND',(120,125),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
        cv2.imwrite(str(self.raw),self.image)

    def test_accept_english_names_numbers_and_i_but_reject_artifacts(self):
        for text in ['I...', 'Airin', "I'll just pass the time by",'3:36 AM','SEND']:
            self.assertTrue(valid_english(text,.99,.82),text)
        for text in ['8','\ufffd','あいう','8\ufffd','noise']:
            self.assertFalse(valid_english(text,.5,.82),text)

    def test_rotated_message_lines_are_not_deduplicated_by_bounding_box(self):
        a=line('I was so excited',0,0,350,25,-.35)
        b=line('our meet-up spot early',0,40,350,25,-.35)
        self.assertEqual(len(deduplicate([a,b])),2)
        self.assertEqual(paragraph_text([b,a]),'I was so excited\nour meet-up spot early')

    def test_partial_retry_does_not_duplicate_the_original_line(self):
        a=line('the time by',100,0,100,20,0,.99)
        b=line("I'll just pass the time by",0,0,250,20,0,.98)
        result=deduplicate([a,b])
        self.assertEqual([r['texto'] for r in result],["I'll just pass the time by"])

    def test_glyph_selection_stays_local_to_text(self):
        mask=glyph_mask(self.image,[[115,100],[200,100],[200,130],[115,130]])
        self.assertGreater(mask.sum(),0)
        self.assertEqual(mask[:95].sum(),0);self.assertEqual(mask[135:].sum(),0)
        self.assertEqual(mask[:,:110].sum(),0)

    def scene(self):
        l={'texto':'SEND','confianza':.99,'poligono':[[115,100],[200,100],[200,130],[115,130]],'box':[115,100,200,130]}
        ocr={'version':2,'raw_sha256':sha256(self.raw),'lineas':[l],'pendientes':[]}
        zones,mask,ocr=enrich_zones(self.raw,[],np.zeros((250,400),np.uint8),ocr,{'confianza_nueva_zona':.9})
        for z in zones:z['metodo_efectivo']='pincel_blanco'
        return {'zonas':zones},ocr

    def test_phone_text_enters_cleaning_translation_and_native_typeo_contract(self):
        record,ocr=self.scene();g=geometry_from_record(self.raw,record)
        self.assertEqual(g['zonas'][0]['rol_revisado'],'pantalla')
        data={'paginas':[{'archivo':'01.png','bloques':[{'id':'01_01','traduccion_es':'Enviar','rol_fuente':'pantalla'}]}]}
        contract=bind_translation(data,{'paginas':[g]},self.base)
        item=build_items(contract,{'paginas':[g]})[0]['items'][0]
        self.assertEqual(item['font_ps'],'CCKissAndTell-BoldItalic');self.assertEqual(item['rotacion'],0)
        self.assertEqual(item['lineas'],['Enviar'])

    def test_diagonal_phone_preserves_raw_angle_and_left_alignment(self):
        record,_=self.scene()
        z=record['zonas'][0]
        z['poligonos_ocr']=[[[80,100],[240,60],[246,84],[86,124]]]
        z['texto_original']='Good night'
        g=geometry_from_record(self.raw,record)
        zone=g['zonas'][0]
        self.assertAlmostEqual(zone['rotacion'],-14.036243,places=4)
        self.assertEqual(zone['alineacion'],'izquierda')
        self.assertIn('box_composicion',zone)
        data={'paginas':[{'archivo':'01.png','bloques':[{'id':zone['id'],'traduccion_es':'Buenas noches','rol_fuente':'pantalla'}]}]}
        item=build_items(bind_translation(data,{'paginas':[g]},self.base),{'paginas':[g]})[0]['items'][0]
        self.assertEqual(item['rotacion'],zone['rotacion'])
        self.assertEqual(item['alineacion'],'izquierda')

    def test_sign_uses_printed_font_not_dialogue_or_myriad(self):
        font=resolve_font('cartel');self.assertEqual(font.postscript,'CCKissAndTell-BoldItalic')
        self.assertNotIn('myriad',font.postscript.lower())
        self.assertEqual(proposed_context('OPEN',override='cartel'),'cartel')

    def test_review_override_cannot_be_reused_for_different_raw(self):
        ocr={'raw_sha256':sha256(self.raw),'lineas':[],'pendientes':[]}
        config={'zonas_revisadas':{'01.png':{'raw_sha256':'old','bloques':{}}}}
        with self.assertRaisesRegex(TypeoError,'otra RAW'):
            enrich_zones(self.raw,[],np.zeros((250,400),np.uint8),ocr,config)

    def test_auto_geometry_translation_worker_uses_ocr_ids_and_scene_font(self):
        record,ocr=self.scene();g=geometry_from_record(self.raw,record)
        job=prepare_run(self.base/'missing.json',self.base/'FINAL',auto_geometry=True,base=self.base)
        write_json(job['opened'],{'job_id':job['job_id']});p=job['pages'][0]
        write_json(p['geometry_ready'],g);write_json(p['ocr_ready'],ocr)
        guion=self.base/'guion.json';write_json(guion,{'paginas':[{'archivo':'01.png','bloques':[
            {'id':'01_01','traduccion_es':'Enviar','rol_fuente':'pantalla'}]}]})
        translation_worker(job,threading.Event(),Events(Path(job['folder'])/'eventos_python.jsonl'),guion=guion,base=self.base)
        ready=read_json(p['typeo_ready'])
        self.assertEqual(ready['items'][0]['font_ps'],'CCKissAndTell-BoldItalic')
        self.assertIsNone(ready['preview']);self.assertFalse(list(self.base.rglob('*.psd')))

    def test_provider_receives_scene_ids_as_json_without_network(self):
        import traducir_capitulo_gemini as provider
        calls=[]
        def generate(**kwargs):calls.append(kwargs);return SimpleNamespace(text='{"version":1,"paginas":[]}')
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        result=provider.traducir_pagina(client,str(self.raw),1,'01.png',ocr_page={'geometry':{'zonas':[{'id':'01_01'}]},'ocr':{}})
        self.assertEqual(read_json_text(result)['version'],1)
        self.assertEqual(calls[0]['config'].response_mime_type,'application/json')
        self.assertIn('01_01',calls[0]['contents'][1])

    def test_unknown_provider_model_falls_back_without_five_pointless_retries(self):
        import traducir_capitulo_gemini as provider
        calls=[]
        def generate(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:raise RuntimeError('404 NOT_FOUND')
            return SimpleNamespace(text='{"version":1,"paginas":[]}')
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        with patch('time.sleep',side_effect=AssertionError('No hay que esperar ante modelo inexistente')):
            provider.traducir_pagina(client,str(self.raw),1,'01.png',ocr_page={'geometry':{'zonas':[]},'ocr':{}})
        self.assertEqual(len(calls),2)


def read_json_text(text):
    import json
    return json.loads(text)


if __name__=='__main__':unittest.main()

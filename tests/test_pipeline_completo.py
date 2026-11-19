import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from typeo_core import TypeoError,read_json,sha256,write_json
from pipeline_completo import prepare_run,translation_worker,mask_cache_valid,Events,verify_timeline


class CompletePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='pipeline_fixture_')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        (self.base/'01_RAW').mkdir();(self.base/'04_DIAGNOSTICO').mkdir()
        pages=[]
        for stem in ('001','002'):
            raw=self.base/'01_RAW'/(stem+'.png');Image.new('RGB',(120,120),'white').save(raw)
            pages.append({'archivo':raw.name,'width':120,'height':120,'raw_sha256':sha256(raw),'zonas':[
                {'id':stem+'_01','texto_original':'はい','rol_revisado':'normal','tipo_contenedor':'globo',
                 'box_contenedor':[15,15,105,105],'poligono_globo':[[10,10],[110,10],[110,110],[10,110]],
                 'poligono_panel':[[0,0],[120,0],[120,120],[0,120]],'permite_fuera_panel_raw':False,
                 'trazo_px':0,'margen_revision_px':6,'tamano_px':28}]})
        self.geometry=self.base/'geometria.json';write_json(self.geometry,{'version':1,'paginas':pages})

    def prepare(self,**kwargs):
        return prepare_run(self.geometry,self.base/'FINAL',base=self.base,**kwargs)

    def test_preparation_needs_no_clean_psd_and_creates_no_intermediate_psd(self):
        job=self.prepare()
        self.assertEqual(len(job['pages']),2)
        self.assertFalse(list(self.base.rglob('*.psd')))
        self.assertEqual([Path(p['output']).name for p in job['pages']],['001.psd','002.psd'])
        self.assertTrue(all(Path(p['raw']).exists() for p in job['pages']))

    def test_existing_final_is_not_versioned_or_overwritten_without_flag(self):
        (self.base/'FINAL').mkdir();existing=self.base/'FINAL/001.psd';existing.write_bytes(b'user work')
        with self.assertRaisesRegex(TypeoError,'--reemplazar'):self.prepare()
        self.assertEqual(existing.read_bytes(),b'user work')
        job=self.prepare(replace=True)
        self.assertEqual(Path(job['pages'][0]['output']),existing)
        self.assertEqual(existing.read_bytes(),b'user work')
        self.assertEqual(list((self.base/'FINAL').glob('*.psd')),[existing])

    def test_retype_reuses_only_verified_final_of_same_raw(self):
        old=self.prepare(selected=['001']);old['status']='complete'
        page=old['pages'][0];Path(page['output']).write_bytes(b'8BPS-test')
        write_json(page['typeo_ready'],{'items':[{'id':'001_01'}]})
        write_json(Path(old['folder'])/'trabajo.json',old)
        write_json(self.base/'FINAL/estado_final.json',{'job_id':old['job_id'],'paginas':[{'archivo':'001.png','job_id':old['job_id']}]})
        current=self.prepare(selected=['001'],replace=True,reuse_final=True)
        self.assertEqual(current['old_typeo_ids'],{'001.png':['001_01']})
        page['raw_sha256']='different';write_json(Path(old['folder'])/'trabajo.json',old)
        with self.assertRaisesRegex(TypeoError,'esta RAW'):
            self.prepare(selected=['001'],replace=True,reuse_final=True)

    def test_translation_publishes_first_page_before_processing_second(self):
        job=self.prepare();write_json(job['opened'],{'job_id':job['job_id']})
        guion=self.base/'guion.json';write_json(guion,{'version':1,'paginas':[
            {'archivo':p['page'],'bloques':[{'id':p['stem']+'_01','traduccion_es':'sí','texto_original':'はい'}]} for p in job['pages']]})
        events=Events(Path(job['folder'])/'events.jsonl');original=events.record
        def record(stage,page=None,**kwargs):
            if stage=='translation_start' and page=='002.png':
                self.assertTrue(Path(job['pages'][0]['typeo_ready']).exists())
                self.assertFalse(Path(job['pages'][1]['typeo_ready']).exists())
            original(stage,page,**kwargs)
        events.record=record
        translation_worker(job,threading.Event(),events,guion=guion,base=self.base)
        self.assertTrue(all(Path(p['typeo_ready']).exists() for p in job['pages']))
        self.assertFalse(list(self.base.rglob('*.psd')))

    def test_worker_waits_for_pages_to_open(self):
        job=self.prepare();stop=threading.Event();stop.set()
        with patch('pipeline_completo.load_translation') as load:
            translation_worker(job,stop,Events(Path(job['folder'])/'events.jsonl'),guion='unused',base=self.base)
            load.assert_not_called()

    def test_masks_changed_or_different_raw_are_not_reused(self):
        from limpieza_rapida import ENGINE_VERSION
        job=self.prepare();cache={'paginas':{}}
        for p in job['pages']:
            mask=Path(p['folder'])/'mask.png';Image.new('L',(120,120),0).save(mask)
            info={'path':str(mask),'sha256':sha256(mask),'size':[120,120],'nonempty':False}
            config=Path(p['folder'])/'config.json';write_json(config,{})
            ocr=Path(p['folder'])/'ocr.json';write_json(ocr,{'version':3,'config_path':str(config),'config_sha256':sha256(config)})
            cache['paginas'][p['page']]={'engine_version':ENGINE_VERSION,'raw_sha256':p['raw_sha256'],'pincel':info,'genfill':info,'pares':[],
                                       'ocr':{'path':str(ocr),'sha256':sha256(ocr)}}
        self.assertTrue(mask_cache_valid(cache,job['pages']))
        outdated=copy.deepcopy(cache);outdated['paginas']['001.png']['engine_version']=ENGINE_VERSION-1
        self.assertFalse(mask_cache_valid(outdated,job['pages']))
        altered=copy.deepcopy(cache);altered['paginas']['001.png']['raw_sha256']='old'
        self.assertFalse(mask_cache_valid(altered,job['pages']))
        Path(cache['paginas']['001.png']['pincel']['path']).write_bytes(b'changed')
        self.assertFalse(mask_cache_valid(cache,job['pages']))

    def test_cached_masks_are_validated_once_and_empty_masks_not_copied(self):
        from pipeline_completo import masks_worker
        from limpieza_rapida import ENGINE_VERSION
        job=self.prepare(selected=['001']);page=job['pages'][0]
        write_json(job['opened'],{'job_id':job['job_id']})
        cfg=self.base/'config';cfg.mkdir();settings=cfg/'ocr_settings.json';write_json(settings,{})
        mask=cfg/'empty.png';Image.new('L',(120,120),0).save(mask)
        ocr=cfg/'ocr.json';protected=[{'poligono':[[1,1],[9,1],[9,9],[1,9]]}]
        art=[[[20,20],[29,20],[29,29],[20,29]]]
        write_json(ocr,{'version':3,'config_path':str(settings),'config_sha256':sha256(settings),
                        'protegidos':protected,'arte_protegido':art})
        info={'path':str(mask),'sha256':sha256(mask),'size':[120,120],'nonempty':False}
        record={'engine_version':ENGINE_VERSION,'raw_sha256':page['raw_sha256'],'pincel':info,'genfill':info,'pares':[],
                'ocr':{'path':str(ocr),'sha256':sha256(ocr)}}
        write_json(cfg/'limpieza_cache.json',{'paginas':{page['page']:record}})
        with patch('pipeline_completo.mask_cache_valid',wraps=mask_cache_valid) as validate,patch('pipeline_completo.shutil.copy2') as copy_mask:
            masks_worker(job,threading.Event(),Events(Path(job['folder'])/'events.jsonl'),base=self.base)
            self.assertEqual(validate.call_count,1);copy_mask.assert_not_called()
        ready=read_json(page['clean_ready'])
        self.assertIsNone(ready['pincel']);self.assertIsNone(ready['generativo'])
        self.assertEqual(ready['regiones_protegidas'],[protected[0]['poligono']])
        self.assertEqual(ready['arte_protegido'],art)

    def test_final_timeline_rejects_next_typeo_before_previous_revision(self):
        job=self.prepare();folder=Path(job['folder'])
        native=[{'stage':'pages_opened','page':None,'time_ms':1}];workers=[]
        for index,page in enumerate(job['pages']):
            start=10+index*10
            native.extend({'stage':stage,'page':page['page'],'time_ms':start+n} for n,stage in enumerate(
                ('clean_start','clean_complete','typeo_start','page_complete')))
            workers.extend({'stage':stage,'page':page['page'],'time_ms':2+n} for n,stage in enumerate(
                ('translation_start','typeo_inputs_ready')))
        def save():
            for name,records in [('eventos_photoshop.jsonl',native),('eventos_python.jsonl',workers)]:
                (folder/name).write_text('\n'.join(json.dumps(r) for r in records),encoding='utf-8')
        save();self.assertTrue(verify_timeline(job))
        native[4]['time_ms']=100
        save()
        with self.assertRaisesRegex(TypeoError,'Orden'):verify_timeline(job)

    @unittest.skipUnless(shutil.which('node'),'Node no instalado')
    def test_real_native_scheduler_and_json_parser(self):
        p=Path(__file__).with_name('pipeline_ps_harness.js')
        result=subprocess.run(['node',str(p)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()

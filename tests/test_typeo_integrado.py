import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
import subprocess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from typeo_core import (TypeoError, FontInfo, bind_translation, compose, original_key,
                        parse_markdown, resolve_font, sha256, typography_text, validate_geometry)
from typeo_pipeline import dispatch_job, verify_job


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base/'01_RAW').mkdir()
        raw = self.base/'01_RAW/001.jpg'
        Image.new('RGB', (100,100), 'white').save(raw)
        self.geometry = {'paginas':[{'archivo':'001.jpg','raw_sha256':sha256(raw),'width':100,'height':100,
                          'zonas':[{'id':'001_01','texto_original':'何？','box_contenedor':[10,10,90,90],
                                    'tipo_contenedor':'globo','poligono_globo':[[10,10],[90,10],[90,90],[10,90]],
                                    'poligono_panel':[[0,0],[100,0],[100,100],[0,100]],'rol_revisado':'normal'}]}]}
        self.translation = {'paginas':[{'archivo':'001.jpg','bloques':[{'texto_original':'何?','traduccion_es':'¿qué?'}]}]}

    def bind(self):
        return bind_translation(self.translation,self.geometry,self.base)

    def test_matches_original_not_row_position(self):
        z = copy.deepcopy(self.geometry['paginas'][0]['zonas'][0]);z['id']='001_02';z['texto_original']='はい'
        self.geometry['paginas'][0]['zonas'].append(z)
        self.translation['paginas'][0]['bloques'].insert(0,{'texto_original':'はい','traduccion_es':'sí'})
        self.assertEqual([b['id'] for b in self.bind()['paginas'][0]['bloques']],['001_02','001_01'])

    def test_ambiguous_original_requires_id(self):
        z=copy.deepcopy(self.geometry['paginas'][0]['zonas'][0]);z['id']='001_02'
        self.geometry['paginas'][0]['zonas'].append(z)
        with self.assertRaisesRegex(TypeoError,'ambigua'):self.bind()

    def test_repeated_originals_can_use_explicit_ids(self):
        z=copy.deepcopy(self.geometry['paginas'][0]['zonas'][0]);z['id']='001_02'
        self.geometry['paginas'][0]['zonas'].append(z)
        self.translation['paginas'][0]['bloques']=[{'id':i,'traduccion_es':'¿qué?'} for i in ['001_02','001_01']]
        self.assertEqual(len(self.bind()['paginas'][0]['bloques']),2)

    def test_duplicate_translation_rejected(self):
        self.translation['paginas'][0]['bloques']*=2
        with self.assertRaisesRegex(TypeoError,'misma zona'):self.bind()

    def test_wrong_page_id_rejected(self):
        self.translation['paginas'][0]['bloques'][0]['id']='002_01'
        with self.assertRaisesRegex(TypeoError,'otra pagina'):self.bind()

    def test_modified_raw_rejected(self):
        Image.new('RGB',(100,100),'black').save(self.base/'01_RAW/001.jpg')
        with self.assertRaisesRegex(TypeoError,'modificada'):self.bind()

    def test_pending_geometry_rejected(self):
        self.geometry['estado']='pendiente_revision'
        with self.assertRaisesRegex(TypeoError,'pendiente'):self.bind()

    def test_stale_translation_raw_hash_rejected(self):
        self.translation['paginas'][0]['raw_sha256']='old'
        with self.assertRaisesRegex(TypeoError,'otra RAW'):self.bind()

    def test_missing_panel_rejected(self):
        del self.geometry['paginas'][0]['zonas'][0]['poligono_panel']
        with self.assertRaisesRegex(TypeoError,'panel revisado'):self.bind()

    def test_missing_translation_rejected(self):
        self.translation['paginas'][0]['bloques']=[]
        with self.assertRaisesRegex(TypeoError,'sin traduccion'):self.bind()

    def test_untranslated_japanese_rejected(self):
        self.translation['paginas'][0]['bloques'][0]['traduccion_es']='何？'
        with self.assertRaisesRegex(TypeoError,'pendiente'):self.bind()

    def test_cleanup_method_does_not_make_bubble_outside_text(self):
        self.geometry['paginas'][0]['zonas'][0]['metodo_limpieza']='relleno_generativo'
        self.translation['paginas'][0]['bloques'][0]['rol_fuente']='fuera_globo'
        self.assertEqual(self.bind()['paginas'][0]['bloques'][0]['rol_fuente'],'normal')

    def test_no_fuzzy_original_matching(self):
        self.translation['paginas'][0]['bloques'][0]['texto_original']='違う'
        with self.assertRaisesRegex(TypeoError,'ausente'):self.bind()


class TypographyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font=resolve_font('normal')

    def zone(self,w=300,h=220):
        return {'id':'test','box_contenedor':[0,0,w,h],'margen_revision_px':6,'tipo_contenedor':'rotulo',
                'trazo_px':5,'tamano_px':34}

    def test_sfx_table_is_not_dialogue(self):
        md='''Página 1 - Archivo: 001.jpg
| Ubicación | Texto Original | Traducción (ES) |
| --- | --- | --- |
| Globo | 何？ | ¿qué? |
#### Onomatopeyas / SFX (Solo Referencia)
| Ubicación | SFX Original | Significado / Efecto (ES) |
| --- | --- | --- |
| Fondo | ドン | golpe |
'''
        self.assertEqual(len(parse_markdown(md)['paginas'][0]['bloques']),1)

    def test_markdown_optional_id_and_escaped_pipe(self):
        md=r'''Página 1 - Archivo: 001.jpg
| Zona ID | Ubicación | Texto Original | Traducción (ES) |
| --- | --- | --- | --- |
| 001_01 | Globo | a\|b | uno\|dos |
'''
        row=parse_markdown(md)['paginas'][0]['bloques'][0]
        self.assertEqual(row['id'],'001_01');self.assertEqual(row['traduccion_es'],'uno|dos')

    def test_case_and_numbers(self):
        self.assertEqual(typography_text('HOLA. ¿QUÉ TAL?\n120 AÑOS',self.font),'Hola. ¿Qué tal?\n120 años')

    def test_keeps_proper_names_and_a_continuation(self):
        text = '...contigo, Mejiro-kun. Morino, ven.'
        self.assertEqual(typography_text(text,self.font),text)

    def test_ascii_quotes_are_prepared_for_photoshop(self):
        text=typography_text('el "experimento"',self.font)
        self.assertEqual(text,'El “experimento”')
        self.assertTrue(all(ord(c) in self.font.cmap or c.isspace() for c in text))

    def test_unsupported_symbol_never_falls_back(self):
        fake=FontInfo(Path('none'),'Test',frozenset(map(ord,'hola H')),True)
        with self.assertRaises(TypeoError):typography_text('hola ☃',fake)

    def test_whole_words_take_priority(self):
        lines,size,shape,divided=compose('Exorcizaré a todos',self.font,self.zone(),'normal')
        self.assertFalse(divided);self.assertIn('Exorcizaré',' '.join(lines))

    def test_hyphen_only_when_word_cannot_fit(self):
        lines,size,shape,divided=compose('Originalmente',self.font,self.zone(115,280),'normal')
        self.assertTrue(divided);self.assertEqual(''.join(lines).replace('-',''),'Originalmente')

    def test_oval_uses_syllable_break_to_recover_readable_size(self):
        zone = self.zone(210, 235)
        zone.update(
            tipo_contenedor='globo', alto_letra_ingles_px=36, minimo_px=12,
            margen_revision_px=4, trazo_px=0,
            poligono_globo=[[1,118],[14,55],[49,17],[105,1],[161,17],[196,55],
                           [209,118],[196,180],[161,218],[105,234],[49,218],[14,180]],
        )
        lines, size, _, divided = compose('Estoy descansando.',self.font,zone,'normal')
        self.assertTrue(divided)
        self.assertEqual(lines,['Estoy','descan-','sando.'])
        self.assertGreaterEqual(size,32)

    def test_short_words_stacked_and_single_word_moderated(self):
        lines,size,shape,divided=compose('¡Jo, jo, jo!',self.font,self.zone(169,207),'normal')
        self.assertEqual(lines,['¡Jo,','jo,','jo!']);self.assertEqual(shape,'apilado_vertical')
        self.assertLessEqual(compose('Sí...',self.font,self.zone(),'normal')[1],28)

    def test_cache_does_not_invent_missing_pages(self):
        from traducir_nativo_antigravity import generar_tablas_markdown
        with self.assertRaisesRegex(TypeoError,'No hay traduccion'):generar_tablas_markdown(['999.jpg'],{})

    def test_translation_memory_is_idempotent_for_same_raw(self):
        import traducir_nativo_antigravity as translator
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'001.jpg').write_bytes(b'raw version')
            memory={'lotes_procesados':[]}
            with patch.object(translator,'RAW_DIR',str(p)),patch.object(translator,'MEMORIA_PATH',str(p/'memory.json')):
                translator.actualizar_memoria(memory,['001.jpg'])
                translator.actualizar_memoria(memory,['001.jpg'])
                self.assertEqual(len(memory['lotes_procesados']),1)
                (p/'001.jpg').write_bytes(b'new raw version')
                translator.actualizar_memoria(memory,['001.jpg'])
                self.assertEqual(len(memory['lotes_procesados']),2)


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);p=Path(self.temp.name)
        self.source=p/'source.psd';self.source.write_bytes(b'8BPSsource')
        self.output=p/'output.psd';self.output.write_bytes(b'8BPSoutput')
        self.preview=p/'preview.jpg';Image.new('RGB',(30,30),'white').save(self.preview)
        self.state=p/'state.json';self.state.write_text(json.dumps({'job_id':'test','status':'complete'}))
        self.review=p/'review.json';self.measure={'id':'001_01','font':'Expected','editable':True,'rotation':0,'centerErrorPx':[0,.5]}
        self.review.write_text(json.dumps([self.measure]))
        self.job={'job_id':'test','original_sha256':{str(self.source):sha256(self.source)},'pages':[
            {'page':'001.jpg','result':str(self.state),'output':str(self.output),'preview':str(self.preview),
             'revision_log':str(self.review),'items':[{'id':'001_01','font_ps':'Expected'}]}]}

    def test_verified_completion(self):self.assertEqual(verify_job(self.job)['capas_editables'],1)

    def test_stale_status_rejected(self):
        self.state.write_text(json.dumps({'job_id':'old','status':'complete'}))
        with self.assertRaises(TypeoError):verify_job(self.job)

    def test_myriad_rejected(self):
        self.measure['font']='MyriadPro-Regular';self.review.write_text(json.dumps([self.measure]))
        with self.assertRaises(TypeoError):verify_job(self.job)

    def test_source_changed_rejected(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(TypeoError):verify_job(self.job)

    def test_panel_escape_rejected_even_if_center_claims_success(self):
        it=self.job['pages'][0]['items'][0]
        it.update({'box_contenedor':[0,0,100,100],'poligono_panel':[[0,0],[50,0],[50,100],[0,100]],'permite_fuera_panel_raw':False})
        self.measure['after']=[40,10,80,30]
        self.review.write_text(json.dumps([self.measure]))
        with self.assertRaisesRegex(TypeoError,'fuera del panel'):verify_job(self.job)

    def test_finished_job_cannot_be_resent(self):
        p=Path(self.temp.name)/'job.json';p.write_text(json.dumps({'status':'complete'}))
        with patch('typeo_pipeline.subprocess.Popen') as launch:
            with self.assertRaises(TypeoError):dispatch_job(p)
            launch.assert_not_called()


class NativeStatusTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node no instalado para la prueba del serializador JSX')
    def test_actual_jsx_status_writer_with_review_variable(self):
        path=Path(__file__).with_name('status_jsx_harness.js')
        result=subprocess.run(['node',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class TimeoutTests(unittest.TestCase):
    def test_timeout_retains_lock_without_killing_photoshop(self):
        # Esta prueba reemplaza estados atomicamente, igual que los trabajos del workspace.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='typeo_timeout_') as temp:
            base=Path(temp);(base/'scripts').mkdir();(base/'02_TRABAJO_PSD').mkdir()
            folder=base/'output';folder.mkdir();(folder/'typeo_lote.jsx').write_text('test')
            page={k:str(folder/(k+'.file')) for k in ['input','output','preview','log','done','result','revision_log']}
            page['page']='001.jpg';Path(page['input']).write_text('base')
            job={'status':'prepared','job_id':'test','folder':str(folder),'pages':[page]}
            job_path=folder/'job.json';job_path.write_text(json.dumps(job))
            with patch('typeo_pipeline.BASE',base),patch('typeo_pipeline.subprocess.Popen') as launch,patch('typeo_pipeline.time.monotonic',side_effect=[0,2]):
                with self.assertRaisesRegex(TypeoError,'plazo'):dispatch_job(job_path,timeout=1)
                launch.assert_called_once()
            self.assertTrue((base/'02_TRABAJO_PSD/.typeo_photoshop.lock').exists())


if __name__=='__main__':unittest.main()

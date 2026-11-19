"""Verificaciones de equivalencia exacta y no-regresion de las optimizaciones de velocidad."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
BACKUP = ROOT / 'backups/optimizacion_velocidad_20261119'


def _load_backup(name):
    spec = importlib.util.spec_from_file_location('bak_' + name, BACKUP / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)
    return mod


class SpeedOptimizationTests(unittest.TestCase):
    def test_split_positions_cache_avoids_repeated_imports_and_matches_compose(self):
        import builtins
        import typeo_core as tc
        bak_tc = _load_backup('typeo_core')

        tc._split_positions_cached.cache_clear()
        tc._spanish_hyphenator.cache_clear()
        imports = []
        orig_import = builtins.__import__

        def counting_import(name, *args, **kwargs):
            if name == 'pyphen':
                imports.append(name)
            return orig_import(name, *args, **kwargs)

        expected_uncached = bak_tc.split_positions('inconstitucional')
        with patch.object(builtins, '__import__', side_effect=counting_import):
            for idx in range(200):
                self.assertEqual(tc.split_positions('inconstitucional'), expected_uncached)
                self.assertEqual(tc.split_positions(f'palabranueva{idx}'), [])
                self.assertEqual(tc.split_positions('descansando'), [3, 6, 9])
        self.assertLessEqual(len(imports), 1)

        font = tc.resolve_font('normal')
        bak_font = bak_tc.resolve_font('normal')
        oval = {
            'id': '01_test', 'box_contenedor': [0, 0, 210, 235],
            'tipo_contenedor': 'globo', 'alto_letra_ingles_px': 36, 'minimo_px': 12,
            'margen_revision_px': 4, 'trazo_px': 0,
            'poligono_globo': [[1, 118], [14, 55], [49, 17], [105, 1], [161, 17], [196, 55],
                               [209, 118], [196, 180], [161, 218], [105, 234], [49, 218], [14, 180]],
        }
        for phrase, zone in [
            ('Estoy descansando.', oval),
            ('Exorcizaré a todos los enemigos difíciles.', {'id': 'z2', 'box_contenedor': [0, 0, 260, 220], 'margen_revision_px': 6, 'tipo_contenedor': 'rotulo', 'trazo_px': 5, 'tamano_px': 34}),
            ('¡Jo, jo, jo!', {'id': 'z3', 'box_contenedor': [0, 0, 169, 207], 'margen_revision_px': 6, 'tipo_contenedor': 'rotulo', 'trazo_px': 5, 'tamano_px': 34}),
        ]:
            self.assertEqual(tc.compose(phrase, font, zone, 'normal'), bak_tc.compose(phrase, bak_font, zone, 'normal'))

    def test_roi_masks_and_border_polygons_are_bit_identical(self):
        import ocr_ingles as oi
        import prueba_segmentacion_pixel as psp
        bak_oi = _load_backup('ocr_ingles')
        bak_psp = _load_backup('prueba_segmentacion_pixel')

        img = np.full((180, 240, 3), 255, np.uint8)
        cv2.putText(img, 'BORDER TEST', (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.putText(img, 'CENTER', (70, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        for poly in [
            [[0, 0], [95, 2], [92, 42], [0, 40]],
            [[160, 130], [250, 140], [248, 190], [155, 175]],
            [[60, 80], [185, 65], [192, 120], [65, 135]],
            [[-10, -10], [-2, -10], [-2, -2], [-10, -2]],
        ]:
            for pad in (0, 3, 6, 12):
                self.assertTrue(np.array_equal(oi.text_area_mask(img, poly, pad), bak_oi.text_area_mask(img, poly, pad)))
            self.assertTrue(np.array_equal(oi.glyph_mask(img, poly, 5), bak_oi.glyph_mask(img, poly, 5)))

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='roi_eq_') as tmp:
            raw = Path(tmp) / '01.png'
            cv2.imwrite(str(raw), img)
            seg = np.full((180, 240), 0.9, np.float32)
            info = {
                'zonas': [
                    {
                        'id': 1, 'origen': 'globo_solido_yolo',
                        'box_contenedor': [0, 0, 140, 60],
                        'poligono_contenedor': [[0, 0], [135, 0], [135, 55], [0, 55]],
                        'rectangulos_texto': [[2, 5, 130, 45]],
                    },
                    {
                        'id': 2, 'origen': 'globo_solido_yolo',
                        'box_contenedor': [55, 70, 210, 140],
                        'poligono_contenedor': [[50, 75], [205, 75], [205, 135], [50, 135]],
                        'rectangulos_texto': [[60, 80, 195, 125]],
                    },
                ]
            }
            m_new, r_new = psp.procesar_mascara_pagina(str(raw), info, seg_map=seg)
            m_old, r_old = bak_psp.procesar_mascara_pagina(str(raw), info, seg_map=seg)
            self.assertTrue(np.array_equal(m_new, m_old))
            self.assertEqual(r_new, r_old)

            record = {
                'zonas': [{
                    'id': 1, 'origen': 'globo_solido_yolo', 'box_contenedor': [55, 70, 210, 140],
                    'poligono_contenedor': [[55, 70], [210, 70], [210, 140], [55, 140]],
                    'poligonos_ocr': [[[65, 85], [175, 85], [175, 120], [65, 120]]],
                    'texto_original': 'CENTER', 'metodo_efectivo': 'pincel_blanco', 'tipo_texto': 'dialogo',
                }]
            }
            g_new = oi.geometry_from_record(raw, json.loads(json.dumps(record)))
            g_old = bak_oi.geometry_from_record(raw, json.loads(json.dumps(record)))
            self.assertEqual(g_new, g_old)

    def test_partition_mask_empty_fast_and_preserves_pixels(self):
        import limpieza_rapida as lr
        empty = np.zeros((100, 100), dtype=np.uint8)
        with patch('limpieza_rapida.cv2.dilate') as mock_dilate:
            self.assertEqual(lr.partition_mask(empty), [])
            mock_dilate.assert_not_called()

        mask = np.zeros((300, 300), dtype=np.uint8)
        for x, y in ((20, 20), (150, 20), (20, 220), (220, 220)):
            mask[y:y + 18, x:x + 18] = 255
        parts = lr.partition_mask(mask)
        self.assertEqual(len(parts), 2)
        self.assertTrue(np.array_equal(np.bitwise_or.reduce(parts), mask))

    def test_rgba_zeroed_background_validates_and_local_session_streams(self):
        import motores_abiertos as ma
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='local_rgba_') as tmp:
            root = Path(tmp)
            raw = root / '01.png'
            mask_p = root / 'mask.png'
            out_p = root / 'out.png'
            Image.new('RGB', (40, 30), (120, 140, 160)).save(raw)
            mask = np.zeros((30, 40), dtype='uint8')
            mask[5:15, 8:24] = 255
            Image.fromarray(mask).save(mask_p)

            infer = lambda im, msk: np.full_like(im, 255)
            item = ma._run_case(infer, {'id': '01_0', 'imagen': str(raw), 'mascara': str(mask_p), 'salida': str(out_p)}, {}, threading.Lock(), rgba=True)
            rgba = np.asarray(Image.open(out_p))
            self.assertEqual(rgba.shape, (30, 40, 4))
            self.assertFalse(np.any(rgba[mask == 0]))
            self.assertTrue(np.all(rgba[mask > 0, 3] == 255))

            manifest = root / 'capas.json'
            ma.write(manifest, {
                'version': 1, 'motor': 'comic',
                'paginas': [{'archivo': '01.png', 'raw_sha256': ma.digest(raw),
                             'capas': [{'path': str(out_p), 'sha256': item['sha256'], 'mascara_sha256': ma.digest(mask_p)}]}],
            })
            self.assertEqual(ma.validate_local_page(manifest, raw, [mask_p]), [str(out_p.resolve())])

            # Verificar protocolo de LocalInpainterSession sin cargar modelos reales.
            fake_server = root / 'fake_serve.py'
            fake_server.write_text(
                'import json, sys\n'
                'proto = sys.stdout\n'
                'sys.stdout = sys.stderr\n'
                'proto.write("__MOTOR_JSON__:" + json.dumps({"ready": True, "carga_segundos": 0.01}) + "\\n")\n'
                'proto.flush()\n'
                'for line in sys.stdin:\n'
                '    msg = json.loads(line)\n'
                '    if msg.get("cmd") == "quit": break\n'
                '    proto.write("__MOTOR_JSON__:" + json.dumps({"ok": True, "casos": msg["casos"]}) + "\\n")\n'
                '    proto.flush()\n',
                encoding='utf-8',
            )
            with patch('motores_abiertos.interpreter', return_value=Path(sys.executable)), \
                 patch('motores_abiertos.__file__', str(fake_server)):
                # En __init__, Path(__file__).resolve() apunta al fake_server
                sess = ma.LocalInpainterSession('comic', root / 'logs', timeout=15)
                try:
                    res = sess.infer([{'id': 'c1'}], rgba=True)
                    self.assertEqual(res, [{'id': 'c1'}])
                finally:
                    sess.close()

    def test_hybrid_run_dispatches_photoshop_before_local_cleaning_and_compacts_cache(self):
        import pipeline_completo as pc
        from limpieza_rapida import ENGINE_VERSION
        from typeo_core import sha256, write_json

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='hybrid_dispatch_') as tmp:
            base = Path(tmp)
            for d in ['scripts', '01_RAW', '02_TRABAJO_PSD', '03_TRADUCCIONES', 'config', '04_DIAGNOSTICO/mascaras_produccion/01']:
                (base / d).mkdir(parents=True, exist_ok=True)
            for f in ['typeo_ps.jsx', 'pipeline_ps.jsx']:
                (base / 'scripts' / f).write_text('// fixture', encoding='utf-8')
            raw = base / '01_RAW/01.png'
            Image.new('RGB', (40, 40), 'white').save(raw)
            mask_dir = base / '04_DIAGNOSTICO/mascaras_produccion/01'
            empty = mask_dir / 'empty.png'
            gen = mask_dir / 'par_1.png'
            Image.new('L', (40, 40), 0).save(empty)
            pair = np.zeros((40, 40), dtype='uint8')
            pair[10:20, 10:20] = 255
            Image.fromarray(pair).save(gen)
            cfg = base / 'config/ocr_settings.json'
            write_json(cfg, {})
            ocr = mask_dir / 'ocr_ingles.json'
            write_json(ocr, {'version': 3, 'config_path': str(cfg), 'config_sha256': sha256(cfg), 'protegidos': [], 'bloques': []})
            sidecar = {
                'engine_version': ENGINE_VERSION, 'raw_sha256': sha256(raw),
                'pincel': {'path': str(empty), 'sha256': sha256(empty), 'size': [40, 40], 'nonempty': False},
                'genfill': {'path': str(gen), 'sha256': sha256(gen), 'size': [40, 40], 'nonempty': True},
                'pares': [{'path': str(gen), 'sha256': sha256(gen), 'size': [40, 40], 'nonempty': True}],
                'ocr': {'path': str(ocr), 'sha256': sha256(ocr)},
            }
            write_json(mask_dir / 'mascaras.json', sidecar)
            job = pc.prepare_run(base / 'missing.json', base / 'FINAL', base=base, clean_only=True)
            job['cleaning_engine'] = 'hibrido'

            order = []

            class FakeSession:
                def __init__(self, engine, folder, timeout=900):
                    self.folder = Path(folder)
                    order.append('session_init')

                def infer(self, casos, rgba=True):
                    order.append('session_infer')
                    out = []
                    for c in casos:
                        rgba_arr = np.zeros((40, 40, 4), dtype='uint8')
                        rgba_arr[pair > 0] = [255, 255, 255, 255]
                        Image.fromarray(rgba_arr, mode='RGBA').save(c['salida'])
                        from motores_abiertos import digest
                        out.append({'id': c['id'], 'salida': c['salida'], 'sha256': digest(c['salida'])})
                    return out

                def close(self):
                    order.append('session_close')

            def fake_popen(cmd, **kwargs):
                order.append('photoshop_launch')
                write_json(job['opened'], {'job_id': job['job_id']})
                # Esperar a que masks_worker publique clean_ready antes de completar.
                deadline = threading.Event()
                while not Path(job['pages'][0]['clean_ready']).exists() and not deadline.is_set():
                    deadline.wait(0.01)
                write_json(job['native_status'], {'job_id': job['job_id'], 'status': 'complete'})

            with patch('auto_ok_photoshop.PhotoshopAutoDismisser'), \
                 patch('motores_abiertos.LocalInpainterSession', FakeSession), \
                 patch('pipeline_completo.subprocess.Popen', side_effect=fake_popen), \
                 patch('pipeline_completo.finish_run', return_value={'ok': True}):
                res = pc.run(job, base=base, timeout=15)
            self.assertEqual(res, {'ok': True})
            self.assertLess(order.index('photoshop_launch'), order.index('session_infer'))
            cache_text = (base / 'config/limpieza_cache.json').read_text(encoding='utf-8')
            self.assertNotIn('\n', cache_text)
            self.assertIn('01.png', json.loads(cache_text)['paginas'])

    @unittest.skipUnless(shutil.which('node'), 'Node no instalado')
    def test_pipeline_ps_clean_step_minimizes_select_mask_calls(self):
        harness = r'''
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const source = fs.readFileSync(path.join(__dirname, '../scripts/pipeline_ps.jsx'), 'utf8').replace(/\r\n/g, '\n');
const functions = source.slice(source.indexOf('function jq'), source.lastIndexOf('try{\n    app.preferences'));

let selectMaskCalls = 0;
let transparencyCalls = 0;
let storedAlphas = 0;
let loadedAlphas = 0;
let nextId = 100;

const sandbox = {
  job: { job_id: 'J1', native_events: 'ev.jsonl' },
  content: '',
  SaveOptions: { DONOTSAVECHANGES: 2 },
  DocumentMode: { RGB: 'RGB' },
  ChangeMode: { RGB: 'RGB' },
  ElementPlacement: { PLACEATBEGINNING: 1, INSIDE: 2 },
  ColorBlendMode: { NORMAL: 'normal' },
  SelectionType: { REPLACE: 'replace', INTERSECT: 'intersect', DIMINISH: 'diminish' },
  DialogModes: { NO: 'no' },
  SolidColor: function () { this.rgb = {}; },
  ActionDescriptor: function () {
    this.putReference = () => {};
    this.putEnumerated = () => {};
    this.putClass = () => {};
    this.putString = () => {};
  },
  ActionReference: function () {
    this.putProperty = () => {};
    this.putEnumerated = () => {};
    this.putIdentifier = () => {};
  },
  charIDToTypeID: k => k,
  stringIDToTypeID: k => k,
  executeActionGet: () => ({ hasKey: () => false }),
  executeAction: id => { if (id === 'setd') transparencyCalls++; },
  File: function (p) {
    this.fsName = p; this.exists = true;
    this.open = () => true; this.read = () => sandbox.content;
    this.close = () => {}; this.write = () => {}; this.writeln = () => {};
  },
};

const layers = [];
const doc = {
  layers,
  componentChannels: ['R', 'G', 'B'],
  activeChannels: ['R', 'G', 'B'],
  channels: {
    add: () => ({ name: '', remove: () => {} }),
  },
  layerSets: {
    add: () => {
      const grp = { id: ++nextId, typename: 'LayerSet', name: '', layers: [] };
      layers.push(grp);
      return grp;
    },
  },
  selection: {
    bounds: [0, 0, 20, 20],
    expand: () => {},
    feather: () => {},
    deselect: () => {},
    store: () => { storedAlphas++; },
    load: () => { loadedAlphas++; },
  },
};

sandbox.app = {
  activeDocument: doc,
  doAction: () => {
    const gen = { id: ++nextId, typename: 'ArtLayer', name: 'Gen', move: () => {} };
    layers.push(gen);
    doc.activeLayer = gen;
  },
  open: f => {
    if (f.fsName.includes('mask_')) {
      selectMaskCalls++;
      return {
        mode: 'RGB',
        channels: [{ duplicate: () => ({ name: '', remove: () => {} }) }],
        close: () => {},
      };
    }
    return {
      activeLayer: {
        duplicate: () => {
          const lyr = { id: ++nextId, typename: 'ArtLayer', name: 'Local', move: () => {} };
          layers.push(lyr);
          return lyr;
        },
      },
      close: () => {},
    };
  },
};

vm.createContext(sandbox);
vm.runInContext(functions, sandbox);

// 1. Local path pair: 0 calls to selectMask, 1 call to selectLayerTransparency
const localState = {
  doc, initialized: true, step: 0, generativeIds: [],
  base: { id: 1 }, original: { name: 'ORIGINAL_TRADUCCION' },
  mask: { job_id: 'J1', pares: ['mask_0.png'], capas_locales: ['local_0.png'] },
};
sandbox.cleanStep(localState, { page: '01.jpg' });
if (selectMaskCalls !== 0) throw Error('Se esperaba 0 selectMask en localPath, hubo ' + selectMaskCalls);
if (transparencyCalls !== 1) throw Error('Se esperaba 1 selectLayerTransparency en localPath, hubo ' + transparencyCalls);

// 2. GenFill pair: exactamente 1 selectMask, guardado y recargado en canal temporal
selectMaskCalls = 0; storedAlphas = 0; loadedAlphas = 0;
const genState = {
  doc, initialized: true, step: 0, generativeIds: [],
  base: { id: 1 }, original: { name: 'ORIGINAL_TRADUCCION' },
  mask: { job_id: 'J1', pares: ['mask_1.png'], capas_locales: [null] },
};
sandbox.cleanStep(genState, { page: '02.jpg' });
if (selectMaskCalls !== 1) throw Error('Se esperaba 1 selectMask en GenFill, hubo ' + selectMaskCalls);
if (storedAlphas !== 1 || loadedAlphas < 2) throw Error('No reutilizo el canal alfa en GenFill');
'''
        result = subprocess.run(['node', '-e', harness], cwd=ROOT / 'tests', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

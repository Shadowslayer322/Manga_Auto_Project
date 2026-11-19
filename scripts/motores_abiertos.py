"""Pruebas y limpieza local con motores externos, sin modificar las RAW ni los PSD.

Las inferencias se ejecutan en procesos separados para no mezclar Qt, NumPy o Torch.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

BASE = Path(__file__).resolve().parents[1]
EXTERNAL = BASE / 'motores_externos'
ENGINES = ('ballons', 'comic', 'mit')
_PROTO_PREFIX = '__MOTOR_JSON__:'


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def interpreter(engine):
    if engine == 'comic':
        return EXTERNAL / 'entornos/comic/Scripts/python.exe'
    if engine == 'mit':
        return EXTERNAL / 'entornos/mit313/Scripts/python.exe'
    return Path(sys.executable)


def invoke(engine, request, folder, timeout=900):
    request_path = folder / ('peticion_' + uuid.uuid4().hex + '.json')
    write(request_path, request)
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1', LOCALAPPDATA=str(EXTERNAL / 'datos'))
    with (folder / (engine + '.log')).open('a', encoding='utf-8') as log:
        result = subprocess.run([str(interpreter(engine)), str(Path(__file__).resolve()),
                                 '_worker', '--motor', engine, '--peticion', str(request_path)],
                                env=env, cwd=BASE, stdout=log, stderr=log, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{engine}: error {result.returncode}; revisar {folder / (engine + ".log")}')
    return read(request['resultado'])


def _lama_thread_config(parallel_workers=1):
    logical = os.cpu_count() or 4
    phys = max(1, logical // 2) if logical >= 8 else logical
    if parallel_workers > 1:
        return max(1, phys // parallel_workers)
    return phys


def load_inpainter(engine, intra_threads=None):
    if engine == 'comic':
        sys.path.insert(0, str(EXTERNAL / 'comic-translate'))
        import onnxruntime as ort
        import modules.inpainting.lama as lama_mod
        from modules.inpainting.lama import LaMa
        from modules.inpainting.schema import Config, HDStrategy
        from modules.utils.onnx import make_session_options
        orig_make_session = lama_mod.make_session
        intra = intra_threads or _lama_thread_config(1)
        def _tuned_make_session(model_path, *, providers, sess_options=None):
            so = sess_options if sess_options is not None else make_session_options()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            so.inter_op_num_threads = 1
            so.intra_op_num_threads = intra
            return ort.InferenceSession(model_path, sess_options=so, providers=providers)
        lama_mod.make_session = _tuned_make_session
        try:
            model = LaMa('cpu', backend='onnx')
        finally:
            lama_mod.make_session = orig_make_session
        config = Config(hd_strategy=HDStrategy.CROP, hd_strategy_crop_margin=48,
                        hd_strategy_crop_trigger_size=640)
        return lambda image, mask: model(image.copy(), mask.copy(), config)
    if engine == 'ballons':
        sys.path.insert(0, str(EXTERNAL / 'BallonsTranslator'))
        from ballontranslator.modules.inpaint.inpaint_default import OpenCVInpainter
        import cv2
        model = OpenCVInpainter()
        def inpaint(image, mask):
            bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            return cv2.cvtColor(model.inpaint(bgr, mask.copy()), cv2.COLOR_BGR2RGB)
        return inpaint
    if engine == 'mit':
        import asyncio
        sys.path.insert(0, str(EXTERNAL / 'manga-image-translator'))
        from manga_translator.inpainting import dispatch
        from manga_translator.config import Inpainter, InpainterConfig
        return lambda image, mask: asyncio.run(dispatch(
            Inpainter.lama_large, image.copy(), mask.copy(), InpainterConfig(),
            inpainting_size=640, device='cpu'))
    raise ValueError('Motor desconocido: ' + engine)


def _run_case(infer, case, image_cache, cache_lock, rgba=False):
    import numpy as np
    from PIL import Image
    print('Caso ' + case['id'], flush=True)
    img_path = case['imagen']
    with cache_lock:
        image = image_cache.get(img_path)
    if image is None:
        with Image.open(img_path) as im:
            loaded = np.array(im.convert('RGB'))
        with cache_lock:
            image = image_cache.setdefault(img_path, loaded)
    with Image.open(case['mascara']) as m_im:
        mask = np.array(m_im.convert('L'))
    if mask.shape != image.shape[:2] or not np.any(mask):
        raise ValueError('Mascara vacia o dimensiones incompatibles')
    mask = (mask > 127).astype('uint8') * 255
    start = time.perf_counter()
    output = np.asarray(infer(image, mask)).clip(0, 255).astype('uint8')
    elapsed = time.perf_counter() - start
    if output.shape != image.shape:
        raise ValueError('El motor cambio las dimensiones de la imagen')
    if rgba:
        h, w = image.shape[:2]
        sel = mask > 0
        out_rgba = np.zeros((h, w, 4), dtype='uint8')
        out_rgba[sel, :3] = output[sel]
        out_rgba[sel, 3] = 255
        Image.fromarray(out_rgba, mode='RGBA').save(case['salida'], compress_level=1)
        diff_mask = np.any(output != image, axis=2)
        return {
            'id': case['id'], 'segundos': elapsed, 'size': [h, w],
            'cambios_fuera_mascara_nativo': int(np.count_nonzero(diff_mask & (~sel))),
            'cambios_fuera_mascara_final': 0,
            'pixeles_modificados': int(np.count_nonzero(diff_mask & sel)),
            'salida': case['salida'], 'sha256': digest(case['salida']),
        }
    native_changed = int(np.count_nonzero(np.any(output != image, axis=2) & (mask == 0)))
    # El contrato local solo permite modificar los pixeles autorizados por mascara.
    composed = np.where(mask[:, :, None] > 0, output, image)
    Image.fromarray(composed).save(case['salida'])
    item = {'id': case['id'], 'segundos': elapsed, 'size': list(image.shape[:2]),
            'cambios_fuera_mascara_nativo': native_changed,
            'cambios_fuera_mascara_final': int(np.count_nonzero(
                np.any(composed != image, axis=2) & (mask == 0))),
            'pixeles_modificados': int(np.count_nonzero(np.any(composed != image, axis=2))),
            'salida': case['salida'], 'sha256': digest(case['salida'])}
    if case.get('referencia'):
        with Image.open(case['referencia']) as ref_im:
            reference = np.array(ref_im.convert('RGB'))
        selected = mask > 0
        item['mae_region_reconstruida'] = float(np.abs(
            composed.astype(float) - reference.astype(float))[selected].mean())
        item['mae_region_danada'] = float(np.abs(
            image.astype(float) - reference.astype(float))[selected].mean())
    return item


def _run_cases(engine, infer, casos, rgba=False):
    image_cache = {}
    cache_lock = threading.Lock()
    if engine == 'comic' and len(casos) >= 2:
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(lambda c: _run_case(infer, c, image_cache, cache_lock, rgba=rgba), casos))
    return [_run_case(infer, c, image_cache, cache_lock, rgba=rgba) for c in casos]


def worker(engine, request):
    if engine == 'mit':
        import torch
        torch.set_num_threads(4)
    print('Cargando ' + engine, flush=True)
    start = time.perf_counter()
    parallel = 2 if engine == 'comic' and len(request.get('casos', [])) >= 2 else 1
    infer = load_inpainter(engine, intra_threads=_lama_thread_config(parallel) if engine == 'comic' else None)
    loaded = time.perf_counter() - start
    print('Motor listo', flush=True)
    results = _run_cases(engine, infer, request['casos'], rgba=bool(request.get('rgba')))
    write(request['resultado'], {'motor': engine, 'carga_segundos': loaded, 'casos': results})


def serve_worker(engine):
    proto = sys.stdout
    sys.stdout = sys.stderr
    def emit(obj):
        proto.write(_PROTO_PREFIX + json.dumps(obj, ensure_ascii=False) + '\n')
        proto.flush()
    try:
        if engine == 'mit':
            import torch
            torch.set_num_threads(4)
        print('Cargando ' + engine + ' (servidor persistente)', flush=True)
        start = time.perf_counter()
        intra = _lama_thread_config(2) if engine == 'comic' else None
        infer = load_inpainter(engine, intra_threads=intra)
        loaded = time.perf_counter() - start
        print(f'Motor listo en {loaded:.3f}s', flush=True)
        emit({'ready': True, 'carga_segundos': loaded})
    except Exception as exc:
        emit({'ready': False, 'error': str(exc)})
        return
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            cmd = msg.get('cmd')
            if cmd == 'quit':
                break
            if cmd == 'infer':
                results = _run_cases(engine, infer, msg.get('casos', []), rgba=bool(msg.get('rgba')))
                emit({'ok': True, 'casos': results})
            else:
                emit({'ok': False, 'error': 'Comando desconocido: ' + str(cmd)})
        except Exception as exc:
            emit({'ok': False, 'error': str(exc)})


class LocalInpainterSession:
    """Subproceso persistente del motor local; carga el modelo una sola vez por ejecucion."""

    def __init__(self, engine, folder, timeout=900):
        self.engine = engine
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.log_path = self.folder / (engine + '.log')
        self._log_handle = self.log_path.open('a', encoding='utf-8')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', LOCALAPPDATA=str(EXTERNAL / 'datos'))
        try:
            self._proc = subprocess.Popen(
                [str(interpreter(engine)), str(Path(__file__).resolve()), '_serve', '--motor', engine],
                env=env, cwd=BASE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._log_handle, text=True, encoding='utf-8', bufsize=1,
            )
        except Exception:
            self._log_handle.close()
            raise
        self._queue = queue.Queue()
        self._ready = False
        self._closed = False
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self):
        try:
            for line in self._proc.stdout:
                stripped = line.strip()
                if stripped.startswith(_PROTO_PREFIX):
                    self._queue.put(stripped[len(_PROTO_PREFIX):])
                elif stripped:
                    try:
                        self._log_handle.write(line)
                        self._log_handle.flush()
                    except OSError:
                        pass
        finally:
            self._queue.put(None)

    def _next_message(self):
        try:
            raw = self._queue.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise TimeoutError(f'{self.engine}: tiempo de espera agotado; revisar {self.log_path}') from exc
        if raw is None:
            rc = self._proc.poll()
            raise RuntimeError(f'{self.engine}: proceso terminado ({rc}); revisar {self.log_path}')
        return json.loads(raw)

    def ensure_ready(self):
        if self._ready:
            return
        msg = self._next_message()
        if not msg.get('ready'):
            raise RuntimeError(f'{self.engine}: error al cargar ({msg.get("error")}); revisar {self.log_path}')
        self._ready = True

    def infer(self, casos, rgba=True):
        if not casos:
            return []
        self.ensure_ready()
        payload = json.dumps({'cmd': 'infer', 'casos': casos, 'rgba': rgba}, ensure_ascii=False)
        self._proc.stdin.write(payload + '\n')
        self._proc.stdin.flush()
        msg = self._next_message()
        if not msg.get('ok'):
            raise RuntimeError(f'{self.engine}: {msg.get("error", "error en inferencia")}; revisar {self.log_path}')
        return msg['casos']

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.poll() is None and self._proc.stdin:
                self._proc.stdin.write('{"cmd":"quit"}\n')
                self._proc.stdin.flush()
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            if self._proc.poll() is None:
                self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        for stream in (self._proc.stdout, self._log_handle):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def page_record(stem, current=False, recalculate=False, *, engine=None, cache_dict=None):
    folder = BASE / '04_DIAGNOSTICO/mascaras_produccion' / stem
    sidecar = folder / 'mascaras.json'
    record = read(sidecar) if sidecar.exists() or not current else {}
    raw = next((BASE / '01_RAW').glob(stem + '.*'))
    if current:
        from PIL import Image
        from pipeline_completo import mask_cache_valid
        with Image.open(raw) as im:
            width, height = im.size
        page = {'page': raw.name, 'raw_sha256': digest(raw),
                'geometry': {'width': width, 'height': height}}
        if recalculate or not mask_cache_valid({'paginas': {raw.name: record}}, [page]):
            if engine is None:
                from limpieza_rapida import MaskEngine
                engine = MaskEngine(BASE)
            record = engine.page(str(raw), folder)
            if cache_dict is not None:
                cache_dict.setdefault('paginas', {})[raw.name] = record
    if digest(raw) != record['raw_sha256']:
        raise ValueError('La RAW no coincide con las mascaras: ' + stem)
    for mask in [record['pincel'], record['genfill'], *record['pares']]:
        if digest(mask['path']) != mask['sha256']:
            raise ValueError('La mascara fue modificada: ' + mask['path'])
    return raw, record


def prepare_cases(folder, pages):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    cases = []
    for stem in pages:
        raw, record = page_record(stem)
        image = Image.open(raw).convert('RGB')
        mask = Image.open(record['genfill']['path']).convert('L')
        coords = np.argwhere(np.asarray(mask) > 127)
        if not len(coords):
            continue
        y, x = coords[len(coords) // 2]
        left = min(max(0, int(x) - 256), max(0, image.width - 512))
        top = min(max(0, int(y) - 256), max(0, image.height - 512))
        box = (left, top, min(image.width, left + 512), min(image.height, top + 512))
        source = folder / f'{stem}_raw.png'
        selection = folder / f'{stem}_mask.png'
        image.crop(box).save(source)
        mask.crop(box).save(selection)
        cases.append({'id': stem, 'raw': str(raw), 'raw_sha256': digest(raw),
                      'recorte': list(box), 'imagen': str(source), 'mascara': str(selection)})
    # Referencia conocida para medir reconstruccion, sin confundirla con calidad editorial.
    raw, _ = page_record(pages[0])
    reference = Image.open(raw).convert('RGB').resize((384, 384))
    damaged = reference.copy()
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 28)
    ink = Image.new('L', reference.size)
    ImageDraw.Draw(ink).text((90, 170), 'PRUEBA 123', font=font, fill=255, stroke_width=1)
    damaged.paste((0, 0, 0), mask=ink)
    import cv2
    expanded = cv2.dilate(np.asarray(ink), np.ones((5, 5), dtype='uint8'))
    for name, obj in [('sintetico_raw', damaged), ('sintetico_mask', Image.fromarray(expanded)),
                      ('sintetico_referencia', reference)]:
        obj.save(folder / (name + '.png'))
    cases.append({'id': 'sintetico', 'imagen': str(folder / 'sintetico_raw.png'),
                  'mascara': str(folder / 'sintetico_mask.png'),
                  'referencia': str(folder / 'sintetico_referencia.png')})
    return cases


def benchmark(pages, engines):
    folder = BASE / '04_DIAGNOSTICO/motores_abiertos' / (time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    cases = prepare_cases(folder, pages)
    report = {'tipo': 'pruebas_de_limpieza_no_traduccion', 'casos': cases, 'motores': []}
    for engine in engines:
        try:
            requests = [{**case, 'salida': str(folder / f'{engine}_{case["id"]}.png')} for case in cases]
            result = invoke(engine, {'casos': requests, 'resultado': str(folder / (engine + '.json'))}, folder)
            result['estado'] = 'prueba_tecnica_superada' if all(
                c['cambios_fuera_mascara_final'] == 0 and c['pixeles_modificados'] > 0 for c in result['casos']) else 'fallo'
            result['revision_visual'] = 'pendiente'
        except Exception as exc:
            result = {'motor': engine, 'estado': 'error', 'error': str(exc)}
        report['motores'].append(result)
        write(folder / 'informe.json', report)
        print(engine + ': ' + result['estado'], flush=True)
    lines = ['# Pruebas de motores abiertos', '',
             'Pruebas de limpieza sobre recortes de RAW y un caso sintetico con referencia conocida.',
             'No comprueban traduccion, deteccion, typeo ni calidad del PSD. No activan motores por defecto.', '',
             '| Motor | Estado | Inferencia total (s) | Pixeles cambiados fuera de mascara |',
             '|---|---|---:|---:|']
    for result in report['motores']:
        lines.append(f'| {result["motor"]} | {result["estado"]} | '
                     f'{sum(c["segundos"] for c in result.get("casos", [])):.2f} | '
                     f'{sum(c["cambios_fuera_mascara_final"] for c in result.get("casos", []))} |')
        if result.get('error'):
            lines.extend(['', result['error']])
    (folder / 'RESULTADOS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(folder, flush=True)
    return folder


def route_character_regions(record, zones, folder, stem):
    """Separar las zonas revisadas sin ampliar la cobertura de borrado."""
    import cv2
    import numpy as np
    from limpieza_rapida import signature

    def load(entry):
        return cv2.imread(entry['path'], cv2.IMREAD_GRAYSCALE)

    def save(name, mask):
        path = folder / f'{stem}_{name}.png'
        if not cv2.imwrite(str(path), mask):
            raise ValueError('No se pudo guardar la mascara: ' + str(path))
        return signature(path)

    brush = load(record['pincel'])
    original_fill = load(record['genfill'])
    combined = brush | original_fill
    height, width = combined.shape
    reserved = np.zeros_like(combined)
    selections = []
    for zone in zones:
        left, top, right, bottom = zone['rectangulo']
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError(f'Zona GenFill fuera de la RAW: {stem}')
        selection = np.zeros_like(combined)
        selection[top:bottom, left:right] = combined[top:bottom, left:right]
        selection &= ~reserved
        if not np.any(selection):
            raise ValueError(f'Zona GenFill sin pixeles de texto: {stem}')
        reserved |= selection
        selections.append((save(f'personaje_{len(selections) + 1}', selection), zone['motivo']))

    local = [save(f'local_{n + 1}', load(pair) & ~reserved)
             for n, pair in enumerate(record['pares'])]
    local = [entry for entry in local if entry['nonempty']]
    record = {**record, 'pincel': save('pincel', brush & ~reserved),
              'genfill': save('generativo', original_fill | reserved),
              'pares': local + [entry for entry, _ in selections]}
    return record, [None] * len(local) + [reason for _, reason in selections]


def manifest_page(manifest_path, raw, *, manifest=None, raw_hash=None):
    manifest = manifest if manifest is not None else read(manifest_path)
    if manifest.get('version') != 1 or manifest.get('motor') not in ENGINES:
        raise ValueError('Manifiesto local incompatible')
    pages = [page for page in manifest['paginas'] if page['archivo'] == Path(raw).name]
    expected = raw_hash or digest(raw)
    if len(pages) != 1 or pages[0]['raw_sha256'] != expected:
        raise ValueError('La limpieza externa no corresponde a esta RAW')
    return pages[0]


class _LazyMaskEngine:
    def __init__(self, base=BASE):
        self.base = base
        self.instance = None

    def page(self, raw, output):
        if self.instance is None:
            from limpieza_rapida import MaskEngine
            self.instance = MaskEngine(self.base)
        return self.instance.page(raw, output)


def clean_pages(pages, engine, *, recalculate=False, hybrid=False):
    """Prepara capas RGBA por par para el flujo nativo de Photoshop, sin abrirlo."""
    folder = BASE / '04_DIAGNOSTICO/limpieza_local' / (time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    manifest = {'version': 1, 'motor': engine, 'paginas': []}
    rules = read(BASE / 'config/zonas_genfill.json') if hybrid else {}
    cache_path = BASE / 'config/limpieza_cache.json'
    cache_dict = read(cache_path) if cache_path.exists() else {'paginas': {}}
    before_pages = dict(cache_dict.get('paginas', {}))
    mask_engine = _LazyMaskEngine(BASE)
    cases = []
    for stem in pages:
        raw, record = page_record(stem, current=True, recalculate=recalculate, engine=mask_engine, cache_dict=cache_dict)
        page = {'archivo': raw.name, 'raw_sha256': record['raw_sha256'], 'capas': []}
        reasons = [None] * len(record['pares'])
        rule = rules.get(raw.name)
        if rule and rule['raw_sha256'] == page['raw_sha256'] and rule['zonas']:
            record, reasons = route_character_regions(record, rule['zonas'], folder, stem)
            page['mascaras_ruteadas'] = {key: record[key] for key in ('pincel', 'genfill', 'pares')}
        for index, (mask, reason) in enumerate(zip(record['pares'], reasons)):
            if not mask['nonempty']:
                continue
            if reason is not None:
                page['capas'].append({'motor': 'genfill', 'motivo': reason, 'mascara_sha256': mask['sha256']})
                print(f'[GENFILL] {raw.name}: {reason}', flush=True)
                continue
            output = folder / f'{stem}_{index}.png'
            cases.append({'id': f'{stem}_{index}', 'imagen': str(raw), 'mascara': mask['path'], 'salida': str(output)})
            page['capas'].append({'path': str(output), 'mascara_sha256': mask['sha256'], 'mascara': mask['path']})
        manifest['paginas'].append(page)
    if cache_dict.get('paginas', {}) != before_pages:
        from typeo_core import write_json
        write_json(cache_path, cache_dict, compact=True)
    if cases:
        infer_result = invoke(engine, {'casos': cases, 'rgba': True, 'resultado': str(folder / 'inferencia.json')}, folder)
        sha_by_out = {c['salida']: c['sha256'] for c in infer_result['casos']}
        for page in manifest['paginas']:
            for layer in page['capas']:
                if layer.get('motor') == 'genfill':
                    continue
                layer['sha256'] = sha_by_out[layer['path']]
    write(folder / 'capas.json', manifest)
    print(folder / 'capas.json', flush=True)
    return folder / 'capas.json'


def validate_local_page(manifest_path, raw, pair_paths, *, manifest=None, raw_hash=None, raw_size=None):
    """Rechaza capas de otra RAW, otras mascaras o con pixeles visibles fuera de ellas."""
    import numpy as np
    from PIL import Image
    page = manifest_page(manifest_path, raw, manifest=manifest, raw_hash=raw_hash)
    layers = page['capas']
    if len(layers) != len(pair_paths):
        raise ValueError('Numero de capas locales distinto de los pares')
    if raw_size is None:
        with Image.open(raw) as raw_im:
            raw_size = raw_im.size
    paths = []
    for layer, pair in zip(layers, pair_paths):
        if digest(pair) != layer['mascara_sha256']:
            raise ValueError('Capa local o mascara modificada')
        if layer.get('motor') == 'genfill':
            if not page.get('mascaras_ruteadas'):
                raise ValueError('GenFill requiere una zona hibrida preparada')
            paths.append(None)
            continue
        if digest(layer['path']) != layer['sha256']:
            raise ValueError('Capa local o mascara modificada')
        with Image.open(layer['path']) as image:
            if image.mode != 'RGBA' or image.size != raw_size:
                raise ValueError('Capa local sin transparencia o dimensiones incorrectas')
            alpha = np.asarray(image)[:, :, 3]
        with Image.open(pair) as pair_im:
            mask = np.asarray(pair_im.convert('L')) > 127
        if np.any(alpha[~mask]) or np.any(alpha[mask] != 255):
            raise ValueError('Transparencia de capa local fuera de su mascara')
        paths.append(str(Path(layer['path']).resolve()))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('accion', choices=['pruebas', 'limpieza', '_worker', '_serve'])
    parser.add_argument('--motor', choices=ENGINES)
    parser.add_argument('--paginas', default='01,24,32')
    parser.add_argument('--peticion', type=Path)
    args = parser.parse_args()
    pages = args.paginas.split(',')
    if args.accion == '_worker':
        worker(args.motor, read(args.peticion))
    elif args.accion == '_serve':
        serve_worker(args.motor)
    elif args.accion == 'pruebas':
        benchmark(pages, [args.motor] if args.motor else ENGINES)
    else:
        if not args.motor:
            parser.error('limpieza requiere --motor')
        clean_pages(pages, args.motor)


if __name__ == '__main__':
    main()

"""Contrato traduccion-geometria, fuentes y composicion del typeo de produccion.

No detecta globos de nuevo ni deduce su ubicacion a partir del metodo de limpieza.
La geometria se valida contra la RAW antes de aceptar una traduccion.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import unicodedata
import uuid
from text_policy import protected_reason

BASE = Path(__file__).resolve().parents[1]
ROLES = {
    'normal': ('CC-KISSANDTELL-REGULAR.TTF','CCKissAndTell'),
    **{r:('CC-KISSANDTELL-ITALIC.TTF','CCKissAndTell-Italic') for r in ('grito','miedo','emocion','narrador','pensamiento')},
    **{r:('CC-KISSANDTELL-BOLD-ITALIC.TTF','CCKissAndTell-BoldItalic') for r in ('fuera_globo','cartel','pantalla','impreso')},
    'titulo': ('Bebas Neue.otf','BebasNeue'),
    'murmullo': ('NeetsHand-Modificado.otf','NeetsHandRegular'),
}

SYLLABLES = {
    'descansando': 'des-can-san-do',
    'recibiré': 're-ci-bi-ré', 'exorcizaré': 'ex-or-ci-za-ré',
    'migradores': 'mi-gra-do-res', 'poseída': 'po-se-í-da',
    'experimento': 'ex-pe-ri-men-to', 'transferencia': 'trans-fe-ren-cia',
    'originalmente': 'o-ri-gi-nal-men-te', 'incendiaria': 'in-cen-dia-ria',
    'escándalo': 'es-cán-da-lo', 'personas': 'per-so-nas', 'mental': 'men-tal',
    'definitivamente': 'de-fi-ni-ti-va-men-te', 'enemigos': 'e-ne-mi-gos',
    'difíciles': 'di-fí-ci-les', 'autoproclamada': 'au-to-pro-cla-ma-da',
    'exorcista': 'ex-or-cis-ta', 'condena': 'con-de-na',
    'ejecutora': 'e-je-cu-to-ra', 'malditas': 'mal-di-tas',
    'iniciador': 'i-ni-cia-dor', 'realidad': 're-a-li-dad',
    'hermana': 'her-ma-na', 'ruidoso': 'rui-do-so', 'sagrada': 'sa-gra-da',
    'presentimiento': 'pre-sen-ti-mien-to', 'conveniencia': 'con-ve-nien-cia',
}


class TypeoError(ValueError):
    """Datos pendientes de revision: no iniciar Photoshop."""


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.'+uuid.uuid4().hex+'.tmp')
    try:
        dumped = json.dumps(data, ensure_ascii=False, separators=(',', ':') if compact else None, indent=None if compact else 2)
        temp.write_text(dumped, encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def sha256(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def original_key(text):
    # Solo normalizar espacios/signos. Nunca aproximar palabras ni usar el orden de filas.
    text = unicodedata.normalize('NFKC', text)
    return ''.join(c for c in text if unicodedata.category(c)[0] in 'LN').casefold()


def infer_role(location):
    t = unicodedata.normalize('NFKD', location.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    for words, role in [(('celular','telefono','pantalla','mensaje','interfaz'), 'pantalla'),
                        (('cartel','letrero','senal','anuncio'), 'cartel'),
                        (('impreso','etiqueta','documento'), 'impreso'),
                        (('titulo',), 'titulo'), (('narrador', 'narracion', 'recuadro'), 'narrador'),
                        (('pensamiento',), 'pensamiento'), (('grito',), 'grito'),
                        (('susurro', 'murmullo'), 'murmullo'), (('miedo', 'temblor'), 'miedo'),
                        (('emocion', 'alegria'), 'emocion'), (('fuera', 'flotante'), 'fuera_globo')]:
        if any(w in t for w in words):
            return role
    return 'normal'


def parse_markdown(text):
    pages, page, in_sfx, headers = [], None, False, None
    for raw in text.splitlines():
        line = raw.strip()
        match = re.search(r'P[áa]gina\s+(\d+)\s*-\s*Archivo:\s*([^\s()]+)', line, re.I)
        if match:
            page = {'archivo': match[2], 'numero': int(match[1]), 'bloques': []}
            pages.append(page)
            in_sfx, headers = False, None
            continue
        if page is None:
            continue
        if line.startswith('#'):
            in_sfx = bool(re.search(r'sfx|onomatopeya', line, re.I))
            headers = None
        if in_sfx or not line.startswith('|'):
            continue
        cells = [c.strip().replace(r'\|', '|') for c in re.split(r'(?<!\\)\|', line.strip('|'))]
        if cells and all(re.fullmatch(r':?-+:?', c.replace(' ', '')) for c in cells):
            continue
        if any('original' in c.lower() for c in cells) and any('traducci' in c.lower() for c in cells):
            headers = [c.lower() for c in cells]
            continue
        if len(cells) < 3:
            continue
        if headers and len(cells) != len(headers):
            raise TypeoError(f'Tabla invalida en {page["archivo"]}: revisar barras | y columnas')
        def field(fragment, default):
            if headers:
                return next((cells[i] for i, h in enumerate(headers) if fragment in h), default)
            return default
        location = field('ubicaci', cells[0])
        original = field('original', cells[1])
        translated = field('traducci', cells[2])
        if translated.lower() == 'sin texto':
            continue
        zone_id = field('zona', '') or field('id', '')
        page['bloques'].append({'id': zone_id, 'texto_original': original,
                                 'traduccion_es': translated, 'ubicacion': location})
    if not pages:
        raise TypeoError('No hay paginas reconocibles en el guion')
    return {'version': 1, 'paginas': pages}


def load_translation(path):
    path = Path(path)
    data = read_json(path) if path.suffix.lower() == '.json' else parse_markdown(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('paginas'), list):
        raise TypeoError('El guion debe contener paginas y bloques')
    return data


def validate_geometry(data, base=BASE):
    from PIL import Image
    if data.get('estado') == 'pendiente_revision':
        raise TypeoError('La geometria todavia esta pendiente de revision')
    seen = set()
    for page in data.get('paginas', []):
        name = page['archivo']
        if Path(name).name != name or '/' in name or '\\' in name or name in seen:
            raise TypeoError('Nombre de pagina invalido o repetido: ' + name)
        seen.add(name)
        raw = Path(base) / '01_RAW' / name
        if not raw.is_file() or sha256(raw) != page.get('raw_sha256'):
            raise TypeoError(f'{name}: RAW nueva o modificada; revisar geometria antes de typear')
        with Image.open(raw) as im:
            if im.size != (page['width'], page['height']):
                raise TypeoError('Dimensiones de RAW incompatibles: ' + name)
        ids = set()
        for z in page['zonas']:
            if z['id'] in ids:
                raise TypeoError('Zona duplicada: ' + z['id'])
            ids.add(z['id'])
            if z.get('tipo_contenedor') not in ('globo', 'rotulo'):
                raise TypeoError('Tipo de contenedor pendiente de revision: ' + z['id'])
            b = z.get('box_contenedor', [])
            if len(b) != 4 or not (0 <= b[0] < b[2] <= page['width'] and 0 <= b[1] < b[3] <= page['height']):
                raise TypeoError('Contenedor invalido: ' + z['id'])
            if len(z.get('poligono_panel', [])) < 3:
                raise TypeoError('Falta panel revisado: ' + z['id'])
            if z.get('tipo_contenedor') == 'globo' and len(z.get('poligono_globo') or []) < 3:
                raise TypeoError('Falta contorno de globo revisado: ' + z['id'])
            angle=z.get('rotacion',0)
            if not isinstance(angle,(int,float)) or not math.isfinite(angle) or abs(angle)>180:
                raise TypeoError('Rotacion invalida: '+z['id'])
            if z.get('alineacion','centro') not in {'centro','izquierda','derecha'}:
                raise TypeoError('Alineacion invalida: '+z['id'])
    if not seen:
        raise TypeoError('Geometria sin paginas')


def bind_translation(translation, geometry, base=BASE):
    validate_geometry(geometry, base)
    gp = {p['archivo']: p for p in geometry['paginas']}
    tp = {}
    for p in translation['paginas']:
        if p['archivo'] in tp:
            raise TypeoError('Pagina duplicada en traduccion: ' + p['archivo'])
        tp[p['archivo']] = p
    if set(tp) != set(gp):
        raise TypeoError(f'Paginas de traduccion y geometria diferentes: faltan {sorted(set(gp)-set(tp))}; sobran {sorted(set(tp)-set(gp))}')
    result = []
    for name, pg in gp.items():
        if tp[name].get('raw_sha256') and tp[name]['raw_sha256'] != pg['raw_sha256']:
            raise TypeoError('La traduccion pertenece a otra RAW: ' + name)
        excluded={z['id'] for z in pg.get('zonas_protegidas',[])}
        excluded.update(z['id'] for z in pg['zonas'] if z.get('no_procesar') or protected_reason(z.get('texto_original'),z.get('tipo_texto')))
        zones = {z['id']: z for z in pg['zonas'] if z['id'] not in excluded}
        originals = {}
        for z in zones.values():
            for text in [z.get('texto_original', ''), *z.get('original_aliases', [])]:
                key = original_key(text)
                if key:
                    originals.setdefault(key, set()).add(z['id'])
        blocks, used = [], set()
        for row in tp[name].get('bloques', []):
            if row.get('id') in excluded or protected_reason(row.get('texto_original'),row.get('tipo')):continue
            if row.get('tipo') == 'sfx':
                continue
            text = row.get('traduccion_es', '').strip()
            if not text or text == '...' or re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', text):
                print(f'[TYPEO][OMITIDO] Traduccion pendiente o no localizada en {name}: {row.get("id") or row.get("texto_original", "")}', flush=True)
                continue
            uid = row.get('id') or ''
            if uid and uid not in zones:
                print(f'[TYPEO][OMITIDO] ID desconocido o de otra pagina: {uid} ({name})', flush=True)
                continue
            if not uid:
                candidates = originals.get(original_key(row.get('texto_original', '')), set())
                if len(candidates) == 1:
                    uid = next(iter(candidates))
                else:
                    pos = row.get('pos')
                    if isinstance(pos, (list, tuple)) and len(pos) == 2:
                        pw = float(pg.get('width') or 1)
                        ph = float(pg.get('height') or 1)
                        px = float(pos[0]) / 1000.0 * pw
                        py = float(pos[1]) / 1000.0 * ph
                        best_uid, best_dist = None, None
                        max_dist = max(pw, ph) * 0.25
                        for cand_id, z in zones.items():
                            if cand_id in used:
                                continue
                            bx1, by1, bx2, by2 = z['box_contenedor']
                            inside = (bx1 - 35 <= px <= bx2 + 35) and (by1 - 35 <= py <= by2 + 35)
                            cx, cy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
                            dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                            if inside or dist <= max_dist:
                                score = (0 if inside else 1, dist)
                                if best_dist is None or score < best_dist:
                                    best_uid, best_dist = cand_id, score
                        uid = best_uid or ''
                    if not uid:
                        print(f'[TYPEO][OMITIDO] Correspondencia ausente o ambigua en {name}: {row.get("texto_original", "")}', flush=True)
                        continue
            if uid in used:
                print(f'[TYPEO][OMITIDO] Dos traducciones para la misma zona: {uid}', flush=True)
                continue
            used.add(uid)
            z = zones[uid]
            role = row.get('rol_fuente') or z.get('rol_revisado') or infer_role(row.get('ubicacion', ''))
            if z.get('tipo_texto') in {'pantalla','cartel','texto_escena'} and role not in {'pantalla','cartel','impreso'}:
                role=z.get('rol_revisado') if z.get('rol_revisado') in {'pantalla','cartel','impreso'} else 'impreso'
            if z.get('tipo_contenedor') == 'globo' and role == 'fuera_globo':
                role = 'normal'
            if role not in ROLES:
                print(f'[TYPEO][AVISO] Rol tipografico desconocido ({role}) en {uid}; usando normal', flush=True)
                role = 'normal'
            blocks.append({'id': uid, 'texto_original': row.get('texto_original') or z.get('texto_original', ''),
                           'traduccion_es': text, 'ubicacion': row.get('ubicacion', ''),
                           'rol_fuente': role})
        if used != set(zones):
            print(f'[TYPEO][AVISO] Zonas sin traduccion en {name} (omitidas): {sorted(set(zones)-used)}', flush=True)
        result.append({'archivo': name, 'raw_sha256': pg['raw_sha256'], 'bloques': blocks})
    return {'version': 1, 'paginas': result}


@dataclass
class FontInfo:
    path: Path
    postscript: str
    cmap: frozenset
    changes_case: bool


@lru_cache(maxsize=256)
def _load_truetype(path_str, size):
    from PIL import ImageFont
    return ImageFont.truetype(path_str, size)


@lru_cache(maxsize=256)
def _font_measurer(path_str, size):
    return lru_cache(maxsize=4096)(_load_truetype(path_str, size).getlength)


@lru_cache(maxsize=32)
def _font_ag_height(path_str):
    probe = _load_truetype(path_str, 100).getbbox('Ag')
    return max(1, probe[3] - probe[1])


@lru_cache(maxsize=32)
def _load_font_info(path_str, expected):
    from fontTools.ttLib import TTFont
    path = Path(path_str)
    font = TTFont(path)
    actual = {n.toUnicode() for n in font['name'].names if n.nameID == 6}
    cmap = frozenset(font.getBestCmap() or {})
    font.close()
    if expected not in actual or 'myriad' in expected.lower():
        raise TypeoError('Archivo de fuente incorrecto: ' + str(path))
    rendered = _load_truetype(path_str, 100)
    different = False
    for char in 'abcdefghijklmnopqrstuvwxyzñáéíóúü':
        if ord(char) not in cmap or ord(char.upper()) not in cmap:
            continue
        a, b = rendered.getmask(char), rendered.getmask(char.upper())
        if a.size != b.size or bytes(a) != bytes(b):
            different = True
            break
    return FontInfo(path, expected, cmap, different)


@lru_cache(maxsize=32)
def resolve_font(role):
    name, expected = ROLES[role]
    roots = [Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Microsoft/Windows/Fonts',
             Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts']
    configured = read_json(BASE/'config/typeo_fuentes.json') if (BASE/'config/typeo_fuentes.json').exists() else {}
    candidates = ([Path(os.path.expandvars(configured[role]))] if role in configured else []) + [r/name for r in roots]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise TypeoError(f'Fuente obligatoria no instalada: {expected}; no se permite Myriad')
    return _load_font_info(str(path), expected)


def resolve_photoshop_exe(explicit=None):
    """Localiza Photoshop.exe en una ruta explicita, variable de entorno o Program Files."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env_exe = os.environ.get('PHOTOSHOP_EXE')
    if env_exe:
        candidates.append(Path(os.path.expandvars(env_exe)))
    adobe_root = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Adobe'
    for year in ('2025', '2026', '2024'):
        candidates.append(adobe_root / f'Adobe Photoshop {year}' / 'Photoshop.exe')
    if adobe_root.exists():
        candidates.extend(sorted(adobe_root.glob('Adobe Photoshop */Photoshop.exe'), reverse=True))
    found = next((p for p in candidates if p.is_file()), None)
    if found is None:
        raise TypeoError('No se encontro Photoshop.exe; configurar la variable de entorno PHOTOSHOP_EXE')
    return str(found)


def _symbol_font():
    try:
        return resolve_font('murmullo')
    except TypeoError:
        return None


def symbol_ranges(lines, font, sym_font):
    if sym_font is None or sym_font.postscript == font.postscript:
        return []
    text = '\r'.join(lines)
    ranges = []
    start = None
    for idx, ch in enumerate(text):
        is_sym = not ch.isspace() and ord(ch) not in font.cmap and ord(ch) in sym_font.cmap
        if is_sym and start is None:
            start = idx
        elif not is_sym and start is not None:
            ranges.append([start, idx])
            start = None
    if start is not None:
        ranges.append([start, len(text)])
    return ranges


def typography_text(text, font):
    if not font.changes_case or text.isupper():
        text = text.lower()
    if font.changes_case:
        ellipsis_length = 3 if text.startswith('...') else 1 if text.startswith('…') else 0
        start = not ellipsis_length
        chars = list(text[:ellipsis_length])
        for c in text[ellipsis_length:]:
            if start and c.isalpha():
                c, start = c.upper(), False
            elif c.isdigit():
                start = False
            chars.append(c)
            if c in '.!?\n':
                start = True
        text = ''.join(chars)
    equivalents = {'«': '"', '»': '"', '“': '"', '”': '"', '‘': "'", '’': "'", '…': '...', '—': '-', '–': '-'}
    sym_font = _symbol_font()
    result, quote_open = [], True
    for c in text:
        # Photoshop convierte comillas ASCII a tipograficas incluso al asignar contents.
        # Elegir de antemano un par que exista en esta fuente evita cambios y fallbacks.
        if c == '"':
            curly = '“' if quote_open else '”'
            replacement = curly if ord(curly) in font.cmap else ('(' if quote_open else ')')
            quote_open = not quote_open
        elif c in ('«', '»') and ord(c) not in font.cmap:
            curly = '“' if c == '«' else '”'
            replacement = curly if ord(curly) in font.cmap else ('(' if c == '«' else ')')
        else:
            replacement = c if c.isspace() or ord(c) in font.cmap else equivalents.get(c)
        if replacement is None or any(not x.isspace() and ord(x) not in font.cmap for x in replacement):
            if sym_font is not None and not c.isspace() and ord(c) in sym_font.cmap:
                replacement = c
            else:
                print(f'[TYPEO][AVISO] Simbolo {c!r} omitido (no soportado por {font.postscript})', flush=True)
                continue
        result.append(replacement)
    return re.sub(r' {2,}', ' ', ''.join(result)).strip()


def polygon_width(poly, y, cx):
    xs = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] <= y < b[1]) or (b[1] <= y < a[1]):
            xs.append(a[0] + (y-a[1]) * (b[0]-a[0]) / (b[1]-a[1]))
    xs.sort()
    for lo, hi in zip(xs[::2], xs[1::2]):
        if lo <= cx <= hi:
            return 2 * min(cx-lo, hi-cx)
    return 0


def point_in_polygon(x, y, poly):
    inside = False
    for a, b in zip(poly, poly[1:]+poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def shape_profile(poly, box):
    cx = (box[0]+box[2])/2
    values = [polygon_width(poly, box[1]+(box[3]-box[1])*f, cx) for f in (.15, .5, .85)]
    top, mid, bottom = values
    if min(values) <= 0:
        return 'rectangular'
    if mid > max(top, bottom)*1.12:
        return 'ovalada'
    if bottom > top*1.25:
        return 'triangular_ensancha_abajo'
    if top > bottom*1.25:
        return 'triangular_ensancha_arriba'
    return 'rectangular'


def shape_factor(shape, i, n):
    if n <= 2:
        return 1
    t = i/(n-1)
    if shape == 'ovalada':
        return max(.8, math.sqrt(1-.65*(2*t-1)**2))
    if shape == 'triangular_ensancha_abajo':
        return .58+.42*t
    if shape == 'triangular_ensancha_arriba':
        return 1-.42*t
    return 1


_SYLLABLE_SUFFIXES = {}
for _syl in SYLLABLES.values():
    _parts = _syl.split('-')
    for _start in range(len(_parts)):
        _suffix = _parts[_start:]
        _key = ''.join(_suffix)
        if _key not in _SYLLABLE_SUFFIXES:
            _SYLLABLE_SUFFIXES[_key] = tuple(len(''.join(_suffix[:_i])) for _i in range(1, len(_suffix)))


@lru_cache(maxsize=1)
def _spanish_hyphenator():
    # Un silabeador instalado puede ampliar el vocabulario; no es obligatorio.
    try:
        import pyphen
    except ImportError:
        return None
    return pyphen.Pyphen(lang='es')


@lru_cache(maxsize=4096)
def _split_positions_cached(word):
    cached = _SYLLABLE_SUFFIXES.get(word.casefold())
    if cached is not None:
        return cached
    hyphenator = _spanish_hyphenator()
    return tuple(hyphenator.positions(word)) if hyphenator is not None else ()


def split_positions(word):
    return list(_split_positions_cached(word))


def english_reference_size(font_info,zone):
    reference=zone.get('alto_letra_ingles_px')
    if not reference:return None
    return max(8,round(reference*100/_font_ag_height(str(font_info.path))))


def compose(text, font_info, zone, role):
    leading_ratio = zone.get("interlineado_ratio",20/(22 if role in {"titulo","murmullo"} else 18))
    box = zone.get('box_composicion',zone['box_contenedor'])
    bw, bh = box[2]-box[0], box[3]-box[1]
    border = zone.get('trazo_px', 5 if zone.get('metodo_limpieza') == 'relleno_generativo' else 0)
    margin = zone.get('margen_revision_px', 6)
    maxw, maxh = bw-2*border-2*margin, bh-2*border-2*margin
    if min(maxw, maxh) < 8:
        raise TypeoError('Area insuficiente: ' + zone['id'])
    words = tuple(text.split())
    if not words:
        raise TypeoError('Texto vacio: ' + zone['id'])
    minsize = zone.get('minimo_px', 18)
    reference=zone.get('alto_letra_ingles_px')
    if reference:
        cap=english_reference_size(font_info,zone)
        minsize=min(minsize,cap)
        # No encoger toda la frase para evitar un guion. Agotar primero las
        # composiciones legibles a escala inglesa, y dividir solo al final.
        # La fuente nueva puede requerir otra escala para caber en el mismo contorno.
        # Se conserva la proporcion tipografica durante el ajuste.
    else:
        cap=min(max(34, zone.get('tamano_px', 34)),76)
    font_path_str = str(font_info.path)
    letters = lambda w: sum(c.isalpha() for c in w)
    short_stack = role not in {'cartel','pantalla','impreso'} and 1 < len(words) <= 4 and all(letters(w) <= 3 for w in words)
    if short_stack or (len(words) == 1 and letters(words[0]) <= 6):
        lines = list(words) if short_stack else [text]
        if short_stack and not reference:
            cap = 72
        elif not reference and 'ancho objetivo' not in zone.get('criterio_tamano', ''):
            cap = 38 if role == 'grito' else 28
        for size in range(cap, minsize-1, -1):
            measure = _font_measurer(font_path_str, size)
            if max(measure(s) for s in lines) <= maxw and len(lines)*size*leading_ratio+size*.4 <= maxh:
                return lines, size, 'apilado_vertical' if short_stack else 'palabra_aislada', False
    poly = zone.get('poligono_globo') if zone.get('tipo_contenedor') == 'globo' else zone.get('poligono_objeto')
    if zone.get('box_composicion'):
        poly=None  # La caja local ya esta inscrita en el objeto orientado.
    shape = shape_profile(poly, box) if poly else 'rectangular'
    cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
    oval_dialogue = shape == 'ovalada' and zone.get('tipo_contenedor') == 'globo' and zone.get('alineacion', 'centro') == 'centro'
    target_ratio = max(.5, min(1., .8*bw/bh)) if oval_dialogue else max(.65, min(1.3, bw/bh))
    # Probar un corte silabico si un globo ovalado obliga a reducir mucho la letra.
    # Conservar la version sin guion si el corte no recupera suficiente escala.
    whole_word_fit = None
    profiles = tuple(dict.fromkeys([shape, 'rectangular']))
    max_lines_cap = min(24, len(words)+10, zone.get('lineas_maximas',24))
    for allow_split in (False, True):
        best = None
        minimum = max(minsize, math.ceil(cap*.8)) if allow_split and whole_word_fit else minsize
        for size in range(cap, minimum-1, -1):
            measure = _font_measurer(font_path_str, size)
            for nlines in range(1, max_lines_cap+1):
                if nlines*size*leading_ratio+size*.3 > maxh:
                    continue
                block_height = (nlines - 1)*size*leading_ratio + size*.8 if oval_dialogue else nlines*size*leading_ratio
                preferred_width = block_height*target_ratio
                base_limits = []
                for i in range(nlines):
                    y = cy + (i-(nlines-1)/2)*size*leading_ratio
                    available = maxw
                    if poly:
                        available = min(available, min(polygon_width(poly, yy, cx) for yy in (y-size*.5, y+size*.5))-2*border-2*margin)
                    base_limits.append(max(0, available))
                if min(base_limits) < 8:
                    continue
                for profile in profiles:
                    limits = [avail*shape_factor(profile, i, nlines) for i, avail in enumerate(base_limits)]
                    if min(limits) < 8:
                        continue
                    desired_widths = [(limit+min(limit, preferred_width))/2 if oval_dialogue else limit for limit in limits]
                    @lru_cache(None)
                    def dp(rest, idx):
                        if idx == nlines:
                            return (0, 0., ()) if not rest else None
                        if not rest:
                            return None
                        choices, limit = [], limits[idx]
                        desired = desired_widths[idx]
                        for take in range(1, len(rest)+1):
                            line = ' '.join(rest[:take])
                            width = measure(line)
                            if width <= limit:
                                tail = dp(rest[take:], idx+1)
                                if tail:
                                    penalty = ((desired-width)/desired)**2 + (1 if width < desired*.35 else 0)
                                    choices.append((tail[0], tail[1]+penalty, (line,)+tail[2]))
                            if allow_split:
                                token = rest[take-1]
                                plain = token.strip('¡!¿?,.…"«»():;')
                                if len(plain) >= 4:
                                    for cut in split_positions(plain):
                                        if min(cut, len(plain)-cut) < 2:
                                            continue
                                        off = token.index(plain)
                                        first = token[:off]+plain[:cut]+'-'
                                        remaining = plain[cut:]+token[off+len(plain):]
                                        split_line = ' '.join(rest[:take-1]+(first,))
                                        split_width = measure(split_line)
                                        if split_width <= limit:
                                            tail = dp((remaining,)+rest[take:], idx+1)
                                            if tail:
                                                choices.append((tail[0]+1, tail[1]+((desired-split_width)/desired)**2, (split_line,)+tail[2]))
                            if width > limit:
                                break
                        return min(choices) if choices else None
                    candidate = dp(words, 0)
                    if not candidate:
                        continue
                    cuts, cost, lines = candidate
                    ratio = max(measure(x) for x in lines)/block_height
                    scale_penalty = (cap-size)*(.055 if oval_dialogue else .025)
                    score = cost/nlines+abs(math.log(ratio/target_ratio))*.35+scale_penalty
                    rank = (cuts, score)
                    if best is None or rank < best[0]:
                        best = (rank, list(lines), size, profile, bool(cuts))
        if best:
            if not allow_split and oval_dialogue and reference and best[2] < cap*.8:
                whole_word_fit = best[1:]
                continue
            return best[1:]
    if whole_word_fit:
        return whole_word_fit
    raise TypeoError(f'{zone["id"]}: no cabe en un tamano legible; revisar contenedor o redaccion')


def opening_punctuation(text):
    def repair(m):
        body=m[2];ending=re.search(r'[!?]+$',body)[0]
        prefix=('¡' if '!' in ending and '¡' not in body else '')+('¿' if '?' in ending and '¿' not in body else '')
        return m[1]+prefix+body
    return re.sub(r'(^|(?<=[.!?])\s+)([^.!?]*[!?]+)',repair,text)


def typography_ratio(role):
    return 20/(22 if role in {'titulo','murmullo'} else 18)


def compose_proportional(text,font_info,zone,role):
    """Componer al espacio RAW con la proporcion tipografica del estilo."""
    layout={**zone,'interlineado_ratio':typography_ratio(role)}
    return compose(text,font_info,layout,role)


def build_items(contract, geometry):
    gp = {p['archivo']: p for p in geometry['paginas']}
    output = []
    for p in contract['paginas']:
        page = gp[p['archivo']]
        zones = {z['id']: z for z in page['zonas']}
        items = []
        for row in p['bloques']:
            zone = zones[row['id']]
            if zone.get('no_procesar') or protected_reason(zone.get('texto_original'),zone.get('tipo_texto')):continue
            role = row['rol_fuente']
            if re.search(r'chapter|cap[ií]tulo',row.get('texto_original','')+' '+row['traduccion_es'],re.I):role='titulo'
            elif role=='titulo':role='fuera_globo'
            try:
                font = resolve_font(role)
                text = typography_text(opening_punctuation(row['traduccion_es']), font)
                if not text.strip():
                    print(f'[TYPEO][OMITIDO] {row["id"]}: texto vacio tras omitir simbolos no soportados', flush=True)
                    continue
                lines, size, shape, split = compose_proportional(text, font, zone, role)
                if ''.join(lines).replace('-', '').replace(' ', '') != ''.join(text.split()).replace('-', ''):
                    raise TypeoError('La composicion altero el contenido: ' + row['id'])
            except TypeoError as exc:
                print(f'[TYPEO][OMITIDO] {row["id"]}: {exc}', flush=True)
                continue
            item = {**zone, 'rol': role, 'font_ps': font.postscript, 'fuente_archivo': str(font.path),
                    'traduccion_es': text, 'traduccion_recibida': row['traduccion_es'],
                    'lineas': lines, 'tamano_px': size, 'forma_composicion': shape,
                    'particion_utilizada': split, 'tamano_fijo':False, 'interlineado_ratio':typography_ratio(role), 'interlineado_px':size*typography_ratio(role), 'rotacion': zone.get('rotacion',0),
                    'alineacion':zone.get('alineacion','izquierda' if role=='pantalla' else 'centro'),
                    'trazo_px': zone.get('trazo_px', 5 if zone.get('metodo_limpieza') == 'relleno_generativo' else 0),
                    'trazo_rgb': zone.get('trazo_rgb', [255,255,255]),
                    'relleno_rgb': zone.get('relleno_rgb', [0,0,0]), 'margen_revision_px': zone.get('margen_revision_px', 6)}
            sym_font = _symbol_font()
            sym_ranges = symbol_ranges(lines, font, sym_font)
            if sym_ranges:
                item['fuente_simbolos_ps'] = sym_font.postscript
                item['rangos_simbolos'] = sym_ranges
            target=english_reference_size(font,zone)
            if target and not item.get('tamano_fijo'):
                item['tamano_objetivo_ingles_px']=target
                if role not in {'cartel','pantalla','impreso'}:item['minimo_px']=max(min(zone.get('minimo_px',18),target),round(target*.8))
            item['minimo_px']=min(zone.get('minimo_px',12),size)
            items.append(item)
        output.append({**page, 'items': items})
    return output

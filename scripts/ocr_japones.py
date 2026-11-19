"""Manga OCR local por zonas identificadas; no traduce ni modifica mascaras."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time

from motores_abiertos import BASE, digest, read, write


def load_model(path=None):
    from manga_ocr import MangaOcr
    if path is None:
        snapshots = Path.home() / '.cache/huggingface/hub/models--kha-white--manga-ocr-base/snapshots'
        candidates = sorted(snapshots.glob('*'))
        if not candidates:
            raise ValueError('Falta manga-ocr-base local; indicar --modelo con su carpeta')
        path = candidates[-1]
    return MangaOcr(pretrained_model_name_or_path=str(path))


def transcribe(geometry, output, model_path=None):
    from PIL import Image
    model = load_model(model_path)
    result = {'version': 1, 'motor': 'manga-ocr', 'idioma': 'ja', 'paginas': []}
    for page in read(geometry)['paginas']:
        raw = BASE / '01_RAW' / page['archivo']
        if digest(raw) != page['raw_sha256']:
            raise ValueError('La geometria japonesa corresponde a otra RAW')
        image = Image.open(raw).convert('RGB')
        blocks = []
        seen = set()
        for zone in page['zonas']:
            if zone['id'] in seen:
                raise ValueError('ID japones duplicado')
            seen.add(zone['id'])
            box = zone.get('box_ocr', zone.get('box_contenedor'))
            if not box or len(box) != 4 or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise ValueError('Recorte japones fuera de RAW')
            blocks.append({'id': zone['id'], 'texto_original': model(image.crop(box))})
        result['paginas'].append({'archivo': raw.name, 'raw_sha256': digest(raw), 'bloques': blocks})
    # Es un contrato OCR de origen: no rellenar traduccion_es con una falsa traduccion.
    with Path(output).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def official_tests(output, model_path=None):
    from PIL import Image
    data = BASE / 'motores_externos/manga-ocr/tests/data'
    model = load_model(model_path)
    expected_path = data / 'expected_results.json'
    if not expected_path.exists():
        expected_path = next(data.glob('*.json'))
    expected = read(expected_path)
    if isinstance(expected, list):
        expected = {item['filename']: item['result'] for item in expected}
    results = []
    for image_path in sorted((data / 'images').glob('*.jpg')):
        start = time.perf_counter()
        text = model(Image.open(image_path).convert('RGB'))
        target = expected.get(image_path.name, expected.get(image_path.stem))
        if isinstance(target, dict):
            target = target.get('text', target.get('expected'))
        results.append({'archivo': image_path.name, 'texto': text, 'esperado': target,
                        'coincide': text == target, 'segundos': time.perf_counter() - start})
    write(output, {'motor': 'manga-ocr', 'referencia': str(expected_path), 'casos': results})
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometria', type=Path)
    parser.add_argument('--salida', required=True, type=Path)
    parser.add_argument('--modelo', type=Path)
    parser.add_argument('--prueba-oficial', action='store_true')
    args = parser.parse_args()
    if args.prueba_oficial:
        official_tests(args.salida, args.modelo)
    elif args.geometria:
        transcribe(args.geometria, args.salida, args.modelo)
    else:
        parser.error('Indicar --geometria o --prueba-oficial')


if __name__ == '__main__':
    main()

"""Extrae unicamente recortes de globos y zonas de texto para traduccion segura."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw
from ocr_ingles import geometry_from_record
from typeo_core import BASE, TypeoError, read_json, sha256, write_json

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


def _raw_pages(base, selected=None):
    raw_dir = base / '01_RAW'
    if not raw_dir.exists():
        raise TypeoError('No existe la carpeta 01_RAW')
    pages = sorted(
        p for p in raw_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and (selected is None or p.stem in selected)
    )
    if not pages:
        raise TypeoError('No hay paginas RAW seleccionadas en 01_RAW')
    return pages


def _load_or_detect_record(raw, masks_root, *, detect=True, engine_holder=None):
    mask_path = masks_root / raw.stem / 'mascaras.json'
    raw_digest = sha256(raw)
    if mask_path.exists():
        record = read_json(mask_path)
        if record.get('raw_sha256') == raw_digest:
            return record, raw_digest
    if not detect:
        raise TypeoError('Falta deteccion/OCR actualizado para ' + raw.name)
    if engine_holder is None:
        engine_holder = {}
    if 'engine' not in engine_holder:
        from limpieza_rapida import MaskEngine
        engine_holder['engine'] = MaskEngine()
    record = engine_holder['engine'].page(raw, masks_root / raw.stem)
    return record, raw_digest


def _crop_box(box, width, height, padding):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    return (
        max(0, x1 - padding),
        max(0, y1 - padding),
        min(width, x2 + padding),
        min(height, y2 + padding),
    )


def _build_collage(crops, out_path):
    """Construye una tira vertical solo con globos recortados sobre fondo blanco."""
    if not crops:
        return None
    header_h = 24
    margin = 14
    max_w = max(im.width for _, _, im in crops)
    canvas_w = max(360, max_w + margin * 2)
    total_h = margin + sum(header_h + im.height + margin for _, _, im in crops)
    canvas = Image.new('RGB', (canvas_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    y = margin
    for zid, role, im in crops:
        draw.rectangle([margin, y, canvas_w - margin, y + header_h - 4], fill=(240, 242, 245))
        draw.text((margin + 6, y + 4), f'{zid}  [{role}]', fill=(20, 20, 20))
        y += header_h
        canvas.paste(im, (margin, y))
        y += im.height + margin
        draw.line([(margin, y - margin // 2), (canvas_w - margin, y - margin // 2)], fill=(210, 210, 210), width=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def extract_balloons(*, base=BASE, selected=None, padding=8, detect=True):
    base = Path(base)
    masks_root = base / '04_DIAGNOSTICO/mascaras_produccion'
    crops_root = base / '03_TRADUCCIONES/recortes_globos'
    crops_root.mkdir(parents=True, exist_ok=True)
    engine_holder = {}
    pages_out = []

    for raw in _raw_pages(base, selected):
        record, raw_digest = _load_or_detect_record(raw, masks_root, detect=detect, engine_holder=engine_holder)
        geom = geometry_from_record(raw, record, raw_hash=raw_digest)
        page_crop_dir = crops_root / raw.stem
        page_crop_dir.mkdir(parents=True, exist_ok=True)

        bloques = []
        collage_inputs = []
        with Image.open(raw) as im:
            rgb = im.convert('RGB')
            w, h = rgb.size
            for z in geom.get('zonas', []):
                zid = z['id']
                box = _crop_box(z['box_contenedor'], w, h, padding)
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                crop = rgb.crop(box)
                crop_path = page_crop_dir / f'{zid}.png'
                crop.save(crop_path)
                role = z.get('rol_revisado', 'normal')
                collage_inputs.append((zid, role, crop))
                bloques.append({
                    'id': zid,
                    'texto_ocr': z.get('texto_original', ''),
                    'rol_sugerido': role,
                    'box_contenedor': list(z['box_contenedor']),
                    'recorte': str(crop_path.relative_to(base)).replace('\\', '/'),
                })

        collage_path = crops_root / f'{raw.stem}_globos.png'
        saved_collage = _build_collage(collage_inputs, collage_path)
        pages_out.append({
            'archivo': raw.name,
            'raw_sha256': raw_digest,
            'collage': str(saved_collage.relative_to(base)).replace('\\', '/') if saved_collage else None,
            'bloques': bloques,
        })

    manifest_path = base / '03_TRADUCCIONES/pendiente_traduccion.json'
    payload = {'version': 1, 'paginas': pages_out}
    write_json(manifest_path, payload)
    return manifest_path, payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paginas', help='Nombres sin extension separados por coma')
    parser.add_argument('--padding', type=int, default=8, help='Margen extra en px alrededor de cada globo')
    parser.add_argument('--sin-detectar', action='store_true', help='No ejecutar deteccion si faltan mascaras')
    parser.add_argument('--base', type=Path, default=BASE)
    args = parser.parse_args(argv)
    selected = set(args.paginas.split(',')) if args.paginas else None
    manifest_path, payload = extract_balloons(
        base=args.base,
        selected=selected,
        padding=args.padding,
        detect=not args.sin_detectar,
    )
    total = sum(len(p['bloques']) for p in payload['paginas'])
    print(f'[GLOBOS] Extraidos {total} recortes en {len(payload["paginas"])} paginas -> {manifest_path}')


if __name__ == '__main__':
    main()

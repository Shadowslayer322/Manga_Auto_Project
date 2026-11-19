import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from extraer_globos_traduccion import extract_balloons
from typeo_core import sha256


class ExtractBalloonsTests(unittest.TestCase):
    def test_extracts_only_balloon_crops_and_collage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / '01_RAW').mkdir(parents=True)
            raw = base / '01_RAW/001.png'
            # Imagen con fondo rojo (arte) y un globo blanco en (20, 30, 120, 90)
            im = Image.new('RGB', (400, 500), (200, 10, 10))
            for x in range(20, 120):
                for y in range(30, 90):
                    im.putpixel((x, y), (255, 255, 255))
            im.save(raw)

            mask_dir = base / '04_DIAGNOSTICO/mascaras_produccion/001'
            mask_dir.mkdir(parents=True)
            mask_img = mask_dir / '001_01.png'
            Image.new('L', (400, 500), 0).save(mask_img)

            record = {
                'version': 1,
                'raw_sha256': sha256(raw),
                'width': 400,
                'height': 500,
                'zonas': [
                    {
                        'id': 1,
                        'ocr_id': '001_01',
                        'texto_original': 'HELLO',
                        'tipo_texto': 'dialogo',
                        'metodo_efectivo': 'pincel_blanco',
                        'box_contenedor': [20, 30, 120, 90],
                        'poligono_globo': [[20, 30], [120, 30], [120, 90], [20, 90]],
                    }
                ],
                'pares': [],
            }
            (mask_dir / 'mascaras.json').write_text(json.dumps(record), encoding='utf-8')

            manifest_path, payload = extract_balloons(base=base, padding=4, detect=False)
            self.assertTrue(manifest_path.exists())
            self.assertEqual(len(payload['paginas']), 1)
            page = payload['paginas'][0]
            self.assertEqual(page['archivo'], '001.png')
            self.assertEqual(len(page['bloques']), 1)
            blk = page['bloques'][0]
            self.assertEqual(blk['id'], '001_01')
            self.assertEqual(blk['texto_ocr'], 'HELLO')

            crop_file = base / blk['recorte']
            self.assertTrue(crop_file.exists())
            with Image.open(crop_file) as crop_im:
                # 120-20 + 8 = 108, 90-30 + 8 = 68 (nunca la imagen entera 400x500)
                self.assertEqual(crop_im.size, (108, 68))

            collage_file = base / page['collage']
            self.assertTrue(collage_file.exists())


if __name__ == '__main__':
    unittest.main()

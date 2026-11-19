"""Integridad de RAW, mascaras y capas externas antes de Photoshop."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from motores_abiertos import digest, route_character_regions, validate_local_page, write


class LocalLayersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / '01.png'
        Image.new('RGB', (20, 15), 'white').save(self.raw)
        self.mask = self.root / 'mask.png'
        mask = np.zeros((15, 20), dtype='uint8')
        mask[3:7, 4:10] = 255
        Image.fromarray(mask).save(self.mask)
        self.layer = self.root / 'layer.png'
        rgba = np.zeros((15, 20, 4), dtype='uint8')
        rgba[:, :, 3] = mask
        Image.fromarray(rgba).save(self.layer)
        self.manifest = self.root / 'capas.json'
        self.payload = {'version': 1, 'motor': 'comic', 'paginas': [{
            'archivo': self.raw.name, 'raw_sha256': digest(self.raw),
            'capas': [{'path': str(self.layer), 'sha256': digest(self.layer),
                       'mascara_sha256': digest(self.mask)}]}]}
        write(self.manifest, self.payload)

    def validate(self):
        return validate_local_page(self.manifest, self.raw, [self.mask])

    def test_valid_rgba_is_accepted(self):
        self.assertEqual(self.validate(), [str(self.layer.resolve())])

    def test_changed_raw_is_rejected(self):
        Image.new('RGB', (20, 15), 'red').save(self.raw)
        with self.assertRaisesRegex(ValueError, 'RAW'):
            self.validate()

    def test_other_mask_is_rejected(self):
        Image.new('L', (20, 15), 255).save(self.mask)
        with self.assertRaisesRegex(ValueError, 'modificada'):
            self.validate()

    def test_changed_layer_is_rejected(self):
        Image.new('RGBA', (20, 15), 'red').save(self.layer)
        with self.assertRaisesRegex(ValueError, 'modificada'):
            self.validate()

    def test_visible_pixels_outside_mask_are_rejected_even_with_updated_hash(self):
        rgba = np.array(Image.open(self.layer))
        rgba[0, 0, 3] = 255
        Image.fromarray(rgba).save(self.layer)
        self.payload['paginas'][0]['capas'][0]['sha256'] = digest(self.layer)
        write(self.manifest, self.payload)
        with self.assertRaisesRegex(ValueError, 'Transparencia'):
            self.validate()

    def test_missing_pair_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Numero'):
            validate_local_page(self.manifest, self.raw, [])

    def test_duplicate_page_is_rejected(self):
        self.payload['paginas'] *= 2
        write(self.manifest, self.payload)
        with self.assertRaisesRegex(ValueError, 'RAW'):
            self.validate()

    def test_character_mask_moves_pixels_from_both_routes_without_expanding(self):
        from limpieza_rapida import signature

        brush = np.zeros((15, 20), dtype=np.uint8)
        brush[4:6, 3:8] = 255
        brush[12, 2] = 255
        fill = np.zeros_like(brush)
        fill[4:6, 8:15] = 255
        fill[2, 17] = 255
        brush_path = self.root / 'pincel.png'
        fill_path = self.root / 'fill.png'
        Image.fromarray(brush).save(brush_path)
        Image.fromarray(fill).save(fill_path)
        record = {'pincel': signature(brush_path), 'genfill': signature(fill_path),
                  'pares': [signature(fill_path)]}
        routed, reasons = route_character_regions(
            record, [{'rectangulo': [3, 3, 15, 7], 'motivo': 'manga'}], self.root, '01')
        self.assertEqual(reasons, [None, 'manga'])

        remaining_brush = np.asarray(Image.open(routed['pincel']['path']))
        local, genfill = [np.asarray(Image.open(pair['path'])) for pair in routed['pares']]
        np.testing.assert_array_equal(remaining_brush | local | genfill, brush | fill)
        self.assertFalse(np.any(genfill & (remaining_brush | local)))
        self.assertTrue(np.all(genfill[4:6, 3:15] == 255))

        alpha = np.zeros((15, 20, 4), dtype=np.uint8)
        alpha[:, :, 3] = local
        Image.fromarray(alpha).save(self.layer)
        page = self.payload['paginas'][0]
        page['mascaras_ruteadas'] = routed
        page['capas'] = [
            {'path': str(self.layer), 'sha256': digest(self.layer),
             'mascara_sha256': routed['pares'][0]['sha256']},
            {'motor': 'genfill', 'mascara_sha256': routed['pares'][1]['sha256']},
        ]
        write(self.manifest, self.payload)
        paths = [p['path'] for p in routed['pares']]
        self.assertEqual(validate_local_page(self.manifest, self.raw, paths),
                         [str(self.layer.resolve()), None])


if __name__ == '__main__':
    unittest.main()

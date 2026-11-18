"""Fusionなしで配置・出力・保存・設定を確認する。"""
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('sheet_layout_test')
package.__path__ = [str(ROOT / 'commands' / 'mdfExport')]
sys.modules[package.__name__] = package

def module(name):
    return importlib.import_module(package.__name__ + '.' + name)

g = module('geometry')
service = module('service')
settings = module('settings')

class PipelineTests(unittest.TestCase):
    def parts(self):
        points = [(0., 0.), (100., 0.), (100., 40.), (0., 40.)]
        outer = g.Loop(True, tuple(g.Curve('LINE', points[i], points[(i+1)%4]) for i in range(4)))
        hole = g.Loop(False, (g.Curve('CIRCLE', center=(20., 20.), radius=5.),))
        return [g.Part('1', 'plate', 2.5, (outer, hole))]

    def test_arrange_and_output(self):
        extracted = module('results').ExtractionResult(self.parts(), ['notice'], 2)
        result = service.arrange(extracted, settings.DEFAULT_SETTINGS)
        self.assertEqual(result.size, (100., 40.))
        self.assertEqual(result.warnings, ['notice'])
        self.assertEqual(result.hidden_count, 2)
        for name, writer, validator in [('dxf_writer', 'dxf_text', 'validate_dxf'), ('svg_writer', 'svg_text', 'validate_svg')]:
            m = module(name)
            text = getattr(m, writer)(result.parts)
            getattr(m, validator)(text, result.parts)
        narrow = service.arrange(extracted, dict(settings.DEFAULT_SETTINGS, width=50.))
        self.assertEqual(narrow.parts, [])
        self.assertIn('PART_TOO_WIDE', narrow.warnings[-1])

    def test_save_and_failure_preserve_existing(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as folder:
            path = Path(folder) / 'cut.svg'
            path.write_text('original', encoding='utf-8')
            service.export_file(path, self.parts(), 'SVG')
            self.assertEqual(path.with_name('cut(バックアップ).svg').read_text(), 'original')
            saved = path.read_bytes()
            def reject(text):
                raise ValueError('invalid')
            with self.assertRaises(ValueError):
                module('file_io').safe_write(path, 'invalid', reject)
            self.assertEqual(path.read_bytes(), saved)
            self.assertEqual(list(Path(folder).glob('.mdf_*.tmp')), [])

    def test_settings_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as folder:
            with patch.object(settings, 'SETTINGS_FILE', Path(folder) / 'settings.json'), patch.object(settings, 'SETTINGS', {}):
                settings.load_settings()
                self.assertEqual(settings.SETTINGS, settings.DEFAULT_SETTINGS)
                changed = dict(settings.DEFAULT_SETTINGS, gap=7.)
                settings.save_settings(changed)
                settings.load_settings()
                self.assertEqual(settings.SETTINGS, changed)
                settings.SETTINGS_FILE.write_text('{broken')
                errors = []
                settings.load_settings(errors.append)
                self.assertTrue(errors)
                self.assertEqual(settings.SETTINGS, settings.DEFAULT_SETTINGS)
                self.assertEqual(settings.SETTINGS_FILE.read_text(), '{broken')

if __name__ == '__main__':
    unittest.main()

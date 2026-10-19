import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('site_build',ROOT/'scripts/build_site.py')
site_build=importlib.util.module_from_spec(spec);spec.loader.exec_module(site_build)

class PublicSiteTests(unittest.TestCase):
    def test_only_allowlisted_synthetic_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            names=site_build.build(tmp)
            self.assertFalse(any(n.startswith('.env') or n in {'.git','.local','bundle.json'} for n in names))
            text=(Path(tmp)/'data.js').read_text()
            data=json.loads(text.removeprefix('window.MEAL_DEMO_DATA = ').removesuffix(';\n'))
            self.assertEqual(data['mode'],'demo');self.assertTrue(data['plans'])
            for private in ['couponId','couponCode','SYNTHETIC-ID-ONLY','SYNTHETIC-CODE-NOT-FOR-USE','structuredContent','Authorization','request_text']:
                self.assertNotIn(private,text)

    def test_build_refuses_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'private.json';marker.write_text('preserve')
            with self.assertRaises(ValueError):site_build.build(tmp)
            self.assertEqual(marker.read_text(),'preserve')

    def test_site_has_no_external_runtime_dependencies(self):
        text=(ROOT/'site/index.html').read_text()
        self.assertIn("connect-src 'none'",text)
        self.assertIn('name="referrer" content="no-referrer"',text)
        self.assertNotIn('<script src="http',text)
        js=(ROOT/'site/app.js').read_text()
        for unsafe in ['innerHTML','eval(','new Function','fetch(','XMLHttpRequest','WebSocket','localStorage','document.cookie']:
            self.assertNotIn(unsafe,js)

    def test_canonical_and_synthetic_disclosure(self):
        text=(ROOT/'site/index.html').read_text()
        self.assertIn('rel="canonical"',text)
        self.assertIn('合成数据',text)

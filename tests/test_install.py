import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_complete_portable_skill(self):
        with tempfile.TemporaryDirectory() as folder:
            target=installer.install(folder)
            self.assertTrue((target/'SKILL.md').is_file())
            self.assertTrue((target/'scripts/advisor.py').is_file())
            self.assertTrue((target/'assets/report.js').is_file())
            self.assertTrue((target/'references/workflow.md').is_file())
            report=Path(folder)/'offline.html'
            subprocess.run([sys.executable,'-B',str(target/'scripts/demo.py'),'--output',str(report)],capture_output=True,text=True,check=True)
            self.assertIn('report-data',report.read_text())

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            target=installer.install(folder); marker=target/'private.txt';marker.write_text('keep')
            with self.assertRaises(FileExistsError):installer.install(folder)
            self.assertEqual(marker.read_text(),'keep')

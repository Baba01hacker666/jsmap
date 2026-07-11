import json
import tempfile
import unittest
from pathlib import Path

from jsmap import ScanOptions, analyze_directory


class TestApi(unittest.TestCase):
    def test_analyze_directory_writes_reports_and_strings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            assets = root / "assets"
            assets.mkdir()
            (assets / "app.js").write_text(
                'fetch("/api/v1/users");', encoding="utf-8"
            )

            result = analyze_directory(
                assets,
                root / "out",
                ScanOptions(extract_strings=True, report_format="md"),
            )

            self.assertEqual(result.finding_count, 1)
            self.assertTrue(result.report_paths["json"].is_file())
            self.assertTrue(result.report_paths["html"].is_file())
            self.assertTrue(result.report_paths["md"].is_file())
            self.assertEqual(
                result.strings["paths"],
                [{"value": "/api/v1/users", "file": "app.js"}],
            )
            summary = json.loads((root / "out" / "summary.json").read_text())
            self.assertEqual(summary["findings"]["total"], 1)

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

    def test_sarif_report_redacts_values_and_supports_ci_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            assets = root / "assets"
            assets.mkdir()
            assets.joinpath("app.js").write_text(
                "const apiKey = 'not-a-real-key-but-long-enough';", encoding="utf-8"
            )
            result = analyze_directory(
                assets,
                root / "out",
                ScanOptions(report_format="sarif", redact_values=True),
            )

            sarif = json.loads(result.report_paths["sarif"].read_text())
            self.assertEqual(sarif["version"], "2.1.0")
            self.assertEqual(sarif["runs"][0]["results"][0]["message"]["text"], "[REDACTED]")
            self.assertTrue(result.has_severity_at_least("HIGH"))
            self.assertFalse(result.has_severity_at_least("CRITICAL"))

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
            self.assertEqual(sarif["results"][0]["message"]["text"] if "results" in sarif else sarif["runs"][0]["results"][0]["message"]["text"], "[REDACTED]")
            self.assertTrue(result.has_severity_at_least("HIGH"))
            self.assertFalse(result.has_severity_at_least("CRITICAL"))

    def test_scan_code(self):
        import jsmap
        code = "const token = 'ghp_123456789012345678901234567890123456';"
        findings = jsmap.scan_code(code, filename="test.js")
        self.assertGreaterEqual(len(findings), 1)
        self.assertEqual(findings[0].subcategory, "GitHub Token")
        self.assertEqual(findings[0].file, "test.js")
        self.assertEqual(findings[0].severity, "CRITICAL")

    def test_scan_file(self):
        import jsmap
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write("const secret = 'sk-proj-" + "C" * 50 + "';")
            path = Path(tf.name)
        try:
            findings = jsmap.scan_file(path)
            self.assertGreaterEqual(len(findings), 1)
            self.assertEqual(findings[0].subcategory, "OpenAI API Key")
        finally:
            path.unlink()

    def test_reconstruct_api(self):
        import jsmap
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            map_data = {
                "version": 3,
                "sources": ["webpack:///src/app.component.ts"],
                "sourcesContent": ["export class AppComponent {}"]
            }
            map_file = root / "app.js.map"
            map_file.write_text(json.dumps(map_data), encoding="utf-8")

            out_dir = root / "reconstructed"
            res = jsmap.reconstruct(map_file, output_dir=out_dir)
            self.assertTrue(bool(res))
            self.assertEqual(res.total_files, 1)
            self.assertTrue((out_dir / "src/app.component.ts").exists())
            self.assertEqual((out_dir / "src/app.component.ts").read_text(), "export class AppComponent {}")

    def test_unpack_sourcemap_api(self):
        import jsmap
        map_data = {
            "version": 3,
            "sources": ["webpack:///src/math.ts"],
            "sourcesContent": ["export const square = (x: number) => x * x;"]
        }
        # In-memory unpack
        res = jsmap.unpack_sourcemap(map_data)
        self.assertIn("src/math.ts", res)
        self.assertEqual(res["src/math.ts"], "export const square = (x: number) => x * x;")

    def test_extract_strings_api(self):
        import jsmap
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write('const url = "https://api.example.com/v1/auth"; const email = "admin@example.com";')
            path = Path(tf.name)
        try:
            res = jsmap.extract_strings(path)
            self.assertTrue(any("https://api.example.com/v1/auth" in u["value"] for u in res["urls"]))
            self.assertTrue(any("admin@example.com" in e["value"] for e in res["emails"]))
        finally:
            path.unlink()

    def test_scan_result_helpers(self):
        import jsmap
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            js_file = root / "sample.js"
            js_file.write_text(
                "const key = 'AKIAIOSFODNN7EXAMPLE'; const api = '/api/v1/data';",
                encoding="utf-8"
            )
            res = jsmap.analyze(js_file, output=root / "out")
            self.assertGreaterEqual(res.finding_count, 1)
            self.assertIn("CRITICAL", res.findings_by_severity())
            self.assertGreaterEqual(len(res.critical_findings), 1)
            d = res.to_dict()
            self.assertIn("total_findings", d)
            self.assertEqual(d["total_findings"], res.finding_count)

    def test_download_crawls_esm_when_main_tsx_linked(self):
        import jsmap
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            html_index = '<!doctype html><html><script type="module" src="/src/main.tsx"></script></html>'
            main_code = "import App from './App.tsx';"
            app_code = "export default function App() { const token = 'ghp_123456789012345678901234567890123456'; }"

            def mock_get(url, *args, **kwargs):
                r = MagicMock()
                r.status_code = 200
                r.headers = {"content-type": "application/javascript"}
                if "index.html" in url or url.endswith("/"):
                    r.text = html_index
                    r.content = html_index.encode()
                elif "main.tsx" in url:
                    r.text = main_code
                    r.content = main_code.encode()
                elif "App.tsx" in url:
                    r.text = app_code
                    r.content = app_code.encode()
                else:
                    r.status_code = 404
                return r

            with patch("requests.Session.get", side_effect=mock_get):
                res = jsmap.download("http://example.com/", output=root / "out", extract_sources=True, crawl_esm=True)
                self.assertIn("main.tsx", res.downloaded_files)
                self.assertIn("App.tsx", res.downloaded_files)
                self.assertIsNotNone(res.sources_directory)
                self.assertTrue((res.sources_directory / "src/App.tsx").exists())



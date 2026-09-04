import tempfile
import unittest
from pathlib import Path

from jsmap.debundler import (
    debundle_directory,
    debundle_file,
    extract_bundle_architecture,
    extract_webpack_modules,
    generate_architecture_report,
)
from jsmap.reconstructor import SourceMapReconstructor


class TestDebundler(unittest.TestCase):
    def test_extract_webpack_modules(self):
        sample = """
        (self["webpackChunkapp"] = self["webpackChunkapp"] || []).push([[101], {
          "./src/components/Header.jsx": (function (module, exports, __webpack_require__) {
            "use strict";
            function Header() { return "Header"; }
            exports.default = Header;
          }),
          992: (function (e, t, n) {
            "use strict";
            const api = "https://api.test.com";
          })
        }]);
        """
        mods = extract_webpack_modules(sample)
        self.assertIn("./src/components/Header.jsx", mods)
        self.assertIn("992", mods)
        self.assertIn("function Header()", mods["./src/components/Header.jsx"])

    def test_extract_bundle_architecture(self):
        sample = """
        const routes = [{ path: "/dashboard" }, { path: "/users/:id" }];
        fetch("/api/v1/auth/login");
        function UserProfile() {}
        class AdminView {}
        localStorage.getItem("token");
        const item = { id: "tiger-01" };
        """
        arch = extract_bundle_architecture(sample, "app.js")
        self.assertIn("/dashboard", arch["routes"])
        self.assertIn("/users/:id", arch["routes"])
        self.assertIn("/api/v1/auth/login", arch["endpoints"])
        self.assertIn("UserProfile", arch["components"])
        self.assertIn("AdminView", arch["components"])
        self.assertIn("token", arch["storage_keys"])
        self.assertIn("tiger-01", arch["entities"])

    def test_generate_architecture_report(self):
        arch = {
            "file": "main.js",
            "routes": ["/home", "/about"],
            "endpoints": ["/api/status"],
            "components": ["Navbar", "Footer"],
            "storage_keys": ["theme"],
            "entities": ["item-1"],
        }
        report = generate_architecture_report(arch)
        self.assertIn("# Application Architecture & Source Blueprint", report)
        self.assertIn("`/home`", report)
        self.assertIn("`/api/status`", report)
        self.assertIn("`Navbar`", report)

    def test_debundle_file(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td) / "app.bundle.js"
            bundle.write_text(
                '(self["webpackChunkapp"] = self["webpackChunkapp"] || []).push([[1], {\n'
                '  "./src/main.js": (function(e, t, n) { const a = !0; return a; })\n'
                '}]);',
                encoding="utf-8",
            )
            out_dir = Path(td) / "output"
            res = debundle_file(bundle, out_dir, beautify=True)
            self.assertGreaterEqual(res.total_modules, 1)
            self.assertTrue((out_dir / "src/main.js").exists())
            self.assertTrue((out_dir / "ARCHITECTURE.md").exists())
            self.assertTrue((out_dir / "beautified/app.bundle.js").exists())
            # Verify de-minification
            content = (out_dir / "src/main.js").read_text(encoding="utf-8")
            self.assertIn("true", content)

    def test_reconstruct_fallback_without_sourcemaps(self):
        # When no .map file exists, reconstruct() should fall back to debundling & beautifying!
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td) / "chunks"
            chunks_dir.mkdir()
            bundle = chunks_dir / "app.js"
            bundle.write_text(
                'const routes = [{ path: "/explore" }]; function Page() { return !0; }',
                encoding="utf-8",
            )
            out_dir = Path(td) / "sources"
            recon = SourceMapReconstructor(output_dir=out_dir, beautify=True, debundle=True)
            res = recon.reconstruct(chunks_dir)
            self.assertTrue(bool(res))
            self.assertGreaterEqual(res.total_files, 1)
            self.assertTrue((out_dir / "ARCHITECTURE.md").exists())
            self.assertTrue((out_dir / "beautified/app.js").exists())
            content = (out_dir / "beautified/app.js").read_text(encoding="utf-8")
            self.assertIn("true", content)
            self.assertNotIn("!0", content)


if __name__ == "__main__":
    unittest.main()

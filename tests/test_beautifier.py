import tempfile
import unittest
from pathlib import Path

from jsmap.beautifier import (
    beautify_code,
    beautify_css,
    beautify_directory,
    beautify_file,
    beautify_html,
    beautify_javascript,
    clean_minified_syntax,
    fallback_format_js,
)


class TestBeautifier(unittest.TestCase):
    def test_clean_minified_booleans_and_undefined(self):
        minified = "function f(a){if(a===!0)return!1;else return void 0;}"
        cleaned = clean_minified_syntax(minified)
        self.assertIn("true", cleaned)
        self.assertIn("false", cleaned)
        self.assertIn("undefined", cleaned)
        self.assertNotIn("!0", cleaned)
        self.assertNotIn("!1", cleaned)
        self.assertNotIn("void 0", cleaned)

    def test_clean_minified_preserves_strings(self):
        code_with_strings = 'const msg = "!0 and !1 and void 0 inside string";'
        cleaned = clean_minified_syntax(code_with_strings)
        self.assertEqual(cleaned, code_with_strings)

    def test_clean_minified_preserves_comments(self):
        code_with_comment = "// Test !0 and !1 in comment\nconst x = !0;"
        cleaned = clean_minified_syntax(code_with_comment)
        self.assertIn("// Test !0 and !1 in comment", cleaned)
        self.assertIn("const x = true;", cleaned)

    def test_unescape_safe_unicode(self):
        escaped = 'const path = "\\u002Fapi\\u002Fv1"; const tag = "\\u003Cdiv\\u003E";'
        cleaned = clean_minified_syntax(escaped)
        self.assertIn('"/api/v1"', cleaned)
        self.assertIn('"<div>"', cleaned)

    def test_beautify_javascript_basic(self):
        minified = "function add(a,b){return a+b;}const res=add(1,2);"
        beautified = beautify_javascript(minified, indent_size=2)
        self.assertIn("\n", beautified)
        self.assertIn("function add(a, b)", beautified)
        self.assertIn("return a + b;", beautified)

    def test_fallback_format_js(self):
        raw = "function calc(x){if(x>0){return x*2;}return 0;}"
        formatted = fallback_format_js(raw, indent_size=2)
        self.assertIn("function calc(x) {", formatted)
        self.assertIn("  if(x>0) {", formatted)
        self.assertIn("    return x*2;", formatted)
        self.assertIn("  }", formatted)

    def test_beautify_css(self):
        min_css = "body{margin:0;padding:0;}h1{color:red;font-size:16px;}"
        beautified = beautify_css(min_css, indent_size=2)
        self.assertIn("margin: 0;", beautified)
        self.assertIn("color: red;", beautified)
        self.assertIn("{\n", beautified)

    def test_beautify_html(self):
        min_html = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
        beautified = beautify_html(min_html, indent_size=2)
        self.assertIn("<title>", beautified)
        self.assertIn("<h1>Hello</h1>", beautified)

    def test_beautify_code_dispatcher(self):
        js = "const x=!0;"
        self.assertIn("true", beautify_code(js, "js"))

        css = "a{color:blue;}"
        self.assertIn("color: blue;", beautify_code(css, "css"))

    def test_beautify_file_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            js_file = Path(td) / "bundle.js"
            js_file.write_text("function test(){if(!0)return!1;}", encoding="utf-8")
            beautify_file(js_file)
            content = js_file.read_text(encoding="utf-8")
            self.assertIn("true", content)
            self.assertIn("false", content)
            self.assertIn("\n", content)

    def test_beautify_directory(self):
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            (dir_path / "a.js").write_text("const a=!0;", encoding="utf-8")
            (dir_path / "b.css").write_text("div{width:100px;}", encoding="utf-8")
            count = beautify_directory(dir_path)
            self.assertEqual(count, 2)
            self.assertIn("true", (dir_path / "a.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""Advanced code beautification and de-minification engine for jsmap.

Handles JavaScript, TypeScript, CSS, HTML, and JSON.
Expands minified booleans (!0, !1) and undefined (void 0), unescapes unicode,
and formats code into human-readable, properly indented source files.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Union

# Optional dependency on jsbeautifier with graceful pure-Python fallback
try:
    import jsbeautifier  # type: ignore
    HAS_JSBEAUTIFIER = True
except ImportError:
    HAS_JSBEAUTIFIER = False


# Regex to match and protect string literals and comments during de-minification
LITERAL_REGEX = re.compile(
    r"(?P<str1>'(?:[^'\\]|\\.)*')|"
    r'(?P<str2>"(?:[^"\\]|\\.)*")|'
    r"(?P<str3>`(?:[^`\\]|\\.)*`)|"
    r"(?P<comment>//[^\n]*)|"
    r"(?P<comment2>/\*[\s\S]*?\*/)"
)


def clean_minified_syntax(code: str) -> str:
    """De-minify common minifier idioms outside of string literals and comments.

    - !0 -> true
    - !1 -> false
    - void 0, void(0), void 1 -> undefined
    - return!0 -> return true
    - return!1 -> return false
    - throw!0 -> throw true
    - Unescapes safe unicode escape sequences (e.g. \\u002F -> /)
    """
    if not code:
        return code

    last_end = 0
    out: List[str] = []

    for m in LITERAL_REGEX.finditer(code):
        start, end = m.span()
        if start > last_end:
            out.append(_clean_code_segment(code[last_end:start]))
        
        # In string literals, unescape common safe unicode escapes
        matched_str = m.group(0)
        if matched_str.startswith(("'", '"', "`")):
            matched_str = _unescape_safe_unicode(matched_str)
        out.append(matched_str)
        last_end = end

    if last_end < len(code):
        out.append(_clean_code_segment(code[last_end:]))

    return "".join(out)


def _clean_code_segment(seg: str) -> str:
    """Transform minified idioms in non-string, non-comment code segments."""
    # 1. Keywords attached directly to !0 / !1 without spaces: return!0, throw!1, etc.
    seg = re.sub(r"\b(return|throw|case|yield|delete)!0\b", r"\1 true", seg)
    seg = re.sub(r"\b(return|throw|case|yield|delete)!1\b", r"\1 false", seg)

    # 2. Standalone !0 and !1
    seg = re.sub(r"(?<![\w\$])!0(?![\w\$])", "true", seg)
    seg = re.sub(r"(?<![\w\$])!1(?![\w\$])", "false", seg)

    # 3. void 0, void(0), void 1, void(1) -> undefined
    seg = re.sub(
        r"\b(return|throw|case|yield)?void\s*(?:\(0\)|0|\(1\)|1)\b",
        lambda m: (m.group(1) + " undefined" if m.group(1) else "undefined"),
        seg,
    )

    # 4. Spacing around common operators when squished
    seg = re.sub(r"([;{}])([a-zA-Z0-9_\$])", r"\1 \2", seg)

    return seg


def _unescape_safe_unicode(s: str) -> str:
    """Unescape safe ASCII unicode escape sequences inside string literals."""
    safe_escapes = {
        r"\u002F": "/",
        r"\u002f": "/",
        r"\u003C": "<",
        r"\u003c": "<",
        r"\u003E": ">",
        r"\u003e": ">",
        r"\u0026": "&",
        r"\u0020": " ",
        r"\u003D": "=",
        r"\u003d": "=",
    }
    for esc, char in safe_escapes.items():
        s = s.replace(esc, char)
    return s


def fallback_format_js(code: str, indent_size: int = 2) -> str:
    """Pure-Python fallback formatter when jsbeautifier is not available.

    Uses brace-depth tracking and statement boundaries to produce readable indented code.
    """
    indent_str = " " * indent_size
    lines: List[str] = []
    current_line: List[str] = []
    indent_level = 0
    in_for_paren = 0

    tokens = re.split(r"([;{}()\[\]]|//[^\n]*|/\*[\s\S]*?\*/|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`)", code)

    for token in tokens:
        if not token:
            continue

        if token == "{":
            current_line.append(" {")
            lines.append((indent_level, "".join(current_line).strip()))
            current_line = []
            indent_level += 1
        elif token == "}":
            if current_line and "".join(current_line).strip():
                lines.append((indent_level, "".join(current_line).strip()))
                current_line = []
            indent_level = max(0, indent_level - 1)
            current_line.append("}")
            lines.append((indent_level, "".join(current_line).strip()))
            current_line = []
        elif token == "(":
            current_line.append("(")
            if any(k in "".join(current_line) for k in ("for ", "for(")):
                in_for_paren += 1
        elif token == ")":
            current_line.append(")")
            if in_for_paren > 0:
                in_for_paren -= 1
        elif token == ";":
            current_line.append(";")
            if in_for_paren == 0:
                lines.append((indent_level, "".join(current_line).strip()))
                current_line = []
        elif token.startswith("//") or token.startswith("/*"):
            current_line.append(token)
            lines.append((indent_level, "".join(current_line).strip()))
            current_line = []
        elif "\n" in token:
            parts = token.split("\n")
            for i, p in enumerate(parts):
                current_line.append(p)
                if i < len(parts) - 1:
                    lines.append((indent_level, "".join(current_line).strip()))
                    current_line = []
        else:
            current_line.append(token)

    if current_line and "".join(current_line).strip():
        lines.append((indent_level, "".join(current_line).strip()))

    formatted_lines = []
    for level, text in lines:
        if not text:
            continue
        formatted_lines.append((indent_str * level) + text)

    return "\n".join(formatted_lines)


def beautify_javascript(code: str, indent_size: int = 2) -> str:
    """Format and de-minify JavaScript/TypeScript code.

    Expands booleans and undefined, and formats indentation and braces.
    """
    if not code or not code.strip():
        return code

    had_trailing_newline = code.endswith("\n")

    # Step 1: De-minify syntax idioms
    cleaned = clean_minified_syntax(code)

    # Step 2: Format using jsbeautifier if available
    res = None
    if HAS_JSBEAUTIFIER:
        try:
            opts = jsbeautifier.default_options()
            opts.indent_size = indent_size
            opts.space_after_anon_function = True
            opts.brace_style = "collapse"
            opts.preserve_newlines = True
            opts.max_preserve_newlines = 2
            opts.unescape_strings = True
            opts.wrap_line_length = 120
            opts.end_with_newline = False
            res = jsbeautifier.beautify(cleaned, opts)
        except Exception:
            pass

    # Step 3: Pure Python fallback formatter
    if res is None:
        res = fallback_format_js(cleaned, indent_size)

    if had_trailing_newline and not res.endswith("\n"):
        res += "\n"
    elif not had_trailing_newline and res.endswith("\n"):
        res = res.rstrip("\r\n")

    return res


def beautify_css(css: str, indent_size: int = 2) -> str:
    """Format CSS code into clean, indented rules."""
    if not css or not css.strip():
        return css

    indent = " " * indent_size
    # Normalize colons with spaces
    css = re.sub(r":\s*", ": ", css)
    css = re.sub(r"\s*\{\s*", " {\n" + indent, css)
    css = re.sub(r"\s*;\s*", ";\n" + indent, css)
    css = re.sub(r"\s*\}\s*", "\n}\n\n", css)
    css = re.sub(r"\n\s+\n", "\n\n", css)
    return css.strip() + "\n"


def beautify_html(html: str, indent_size: int = 2) -> str:
    """Format HTML code with clean tag indentation."""
    if not html or not html.strip():
        return html

    if HAS_JSBEAUTIFIER and hasattr(jsbeautifier, "beautify_html"):
        try:
            opts = jsbeautifier.default_options()
            opts.indent_size = indent_size
            return jsbeautifier.beautify_html(html, opts)
        except Exception:
            pass

    return html


def beautify_code(code: str, file_type: str = "js", indent_size: int = 2) -> str:
    """High-level dispatcher to beautify any code content."""
    ft = file_type.lower().lstrip(".")
    if ft in ("js", "mjs", "cjs", "jsx", "ts", "tsx"):
        return beautify_javascript(code, indent_size)
    elif ft == "css":
        return beautify_css(code, indent_size)
    elif ft in ("html", "htm", "svg"):
        return beautify_html(html=code, indent_size=indent_size)
    return code


def beautify_file(
    file_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    indent_size: int = 2,
) -> Path:
    """Beautify a file on disk.

    If output_path is omitted, the file is beautified in-place.
    """
    src_path = Path(file_path).expanduser().resolve()
    dest_path = Path(output_path).expanduser().resolve() if output_path else src_path

    content = src_path.read_text(encoding="utf-8", errors="ignore")
    ext = src_path.suffix.lstrip(".")
    beautified = beautify_code(content, file_type=ext, indent_size=indent_size)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(beautified, encoding="utf-8")
    return dest_path


def beautify_directory(
    directory: Union[str, Path],
    extensions: Optional[List[str]] = None,
    indent_size: int = 2,
) -> int:
    """Beautify all matching files within a directory tree in-place.

    Returns the count of beautified files.
    """
    dir_path = Path(directory).expanduser().resolve()
    if not dir_path.is_dir():
        return 0

    target_exts = set(extensions or [".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html"])
    count = 0

    for file_path in dir_path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in target_exts:
            try:
                beautify_file(file_path, indent_size=indent_size)
                count += 1
            except Exception:
                pass

    return count

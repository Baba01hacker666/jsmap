"""Module debundler and architecture extractor for JavaScript bundles.

When source maps are not available, this module:
1. Slices Webpack, Vite, and Rollup bundles into discrete, readable module files.
2. Extracts frontend routes, API endpoints, entity data models, and component names.
3. Formats and beautifies every recovered module.
4. Generates an ARCHITECTURE.md report outlining the application blueprint.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .beautifier import beautify_code, beautify_javascript, clean_minified_syntax
from .logger import info, success, warn


@dataclass
class DebundleResult:
    """Result of debundling a JavaScript chunk or directory of chunks."""

    total_modules: int = 0
    extracted_files: Dict[str, Path] = field(default_factory=dict)
    routes: List[str] = field(default_factory=list)
    endpoints: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    architecture_report: Optional[Path] = None


def extract_webpack_modules(code: str) -> Dict[str, str]:
    """Extract individual modules from Webpack 4 / 5 chunk definitions.

    Matches object dictionaries:
    `{ "./src/App.js": function(...) { ... }, 1234: (e, t, n) => { ... } }`
    """
    modules: Dict[str, str] = {}

    # Key pattern: either a quoted string path (e.g. "./src/main.js") or numeric module ID
    key_pattern = re.compile(
        r"(?:[\s,{]\s*)(?P<key>[\"'][^\"'\n\r]{1,200}[\"']|\d+)\s*:\s*(?P<fn_start>\(?\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>))"
    )

    for m in key_pattern.finditer(code):
        raw_key = m.group("key").strip("\"'")
        start_idx = m.start("fn_start")

        # Find opening brace of module function
        brace_start = code.find("{", start_idx)
        if brace_start == -1 or brace_start - start_idx > 80:
            continue

        depth = 0
        in_str: Optional[str] = None
        pos = brace_start
        end_pos = -1

        while pos < len(code):
            ch = code[pos]
            if in_str:
                if ch == "\\":
                    pos += 2
                    continue
                elif ch == in_str:
                    in_str = None
            else:
                if ch in ('"', "'", "`"):
                    in_str = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_pos = pos + 1
                        break
            pos += 1

        if end_pos != -1:
            mod_code = code[start_idx:end_pos].strip()
            # If function wrapped in parentheses, strip them
            if mod_code.startswith("(") and mod_code.endswith(")"):
                mod_code = mod_code[1:-1].strip()
            modules[raw_key] = mod_code

    return modules


def extract_bundle_architecture(code: str, filename: str = "bundle.js") -> Dict[str, Any]:
    """Extract high-level architecture details from minified or beautified JavaScript."""
    # 1. Routes (React Router, Vue Router, Next.js, Angular)
    routes: Set[str] = set()
    for m in re.finditer(r'path:\s*["\']([a-zA-Z0-9_\-/:*]+)["\']', code):
        r = m.group(1).strip()
        if r and (r.startswith("/") or r in ("*", "")) and len(r) < 80:
            routes.add(r)

    # 2. API Endpoints
    endpoints: Set[str] = set()
    for m in re.finditer(r'["\`](/(?:api|v[0-9]+|auth|users|graphql|data)[a-zA-Z0-9_\-/\.]*)["\`]', code):
        ep = m.group(1).strip()
        if len(ep) > 3 and not ep.endswith((".js", ".css", ".png", ".jpg", ".svg")):
            endpoints.add(ep)

    # 3. Component Names (React, Vue, Web Components)
    components: Set[str] = set()
    # PascalCase function names
    for m in re.finditer(r'(?:function\s+|class\s+|const\s+)([A-Z][a-zA-Z0-9_]{2,40})\s*(?:=|\(|\{)', code):
        cname = m.group(1)
        # Exclude built-ins and standard globals
        if cname not in ("Promise", "Object", "Array", "String", "Number", "Boolean", "RegExp", "Error", "Date", "Math", "JSON", "Map", "Set", "Symbol", "Proxy", "Reflect", "WeakMap", "WeakSet", "Intl"):
            components.add(cname)

    # 4. Storage keys (localStorage, sessionStorage, cookies)
    storage_keys: Set[str] = set()
    for m in re.finditer(r'(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem)\s*\(\s*["\']([^"\']+)["\']', code):
        storage_keys.add(m.group(1))

    # 5. Entity IDs / Data models (common in headless CMS, mock stores, catalogs)
    entities: Set[str] = set()
    for m in re.finditer(r'id:\s*["\']([a-zA-Z0-9_\-]{3,50})["\']', code):
        entities.add(m.group(1))

    # 6. Environment variables and config keys
    env_keys: Set[str] = set()
    for m in re.finditer(r'(?:VITE_|REACT_APP_|NEXT_PUBLIC_|NG_APP_|process\.env\.)([A-Z0-9_]+)', code):
        env_keys.add(m.group(1))

    return {
        "file": filename,
        "routes": sorted(routes),
        "endpoints": sorted(endpoints),
        "components": sorted(components),
        "storage_keys": sorted(storage_keys),
        "entities": sorted(entities)[:50],
        "env_keys": sorted(env_keys),
    }


def generate_architecture_report(arch: Dict[str, Any]) -> str:
    """Generate a clean Markdown architectural summary of the application."""
    lines = [
        "# Application Architecture & Source Blueprint",
        "",
        f"> Automatically reconstructed from **{arch.get('file', 'bundle.js')}** without source maps.",
        "",
        "## Discovered Frontend Routes",
    ]
    routes = arch.get("routes", [])
    if routes:
        for r in routes:
            lines.append(f"- `{r}`")
    else:
        lines.append("*No route definitions found.*")

    lines.extend(["", "## API Endpoints"])
    endpoints = arch.get("endpoints", [])
    if endpoints:
        for ep in endpoints:
            lines.append(f"- `{ep}`")
    else:
        lines.append("*No explicit REST / API endpoints matched.*")

    lines.extend(["", "## Key Components & Views"])
    components = arch.get("components", [])
    if components:
        lines.append(f"Found {len(components)} component/class declarations:")
        lines.append("")
        lines.append(", ".join(f"`{c}`" for c in components[:40]))
        if len(components) > 40:
            lines.append(f"... and {len(components) - 40} more")
    else:
        lines.append("*No top-level component declarations found.*")

    lines.extend(["", "## Storage & Client State Keys"])
    keys = arch.get("storage_keys", [])
    if keys:
        for k in keys:
            lines.append(f"- `{k}`")
    else:
        lines.append("*No localStorage / sessionStorage keys detected.*")

    lines.extend(["", "## Data Entity IDs & Models"])
    entities = arch.get("entities", [])
    if entities:
        lines.append(", ".join(f"`{e}`" for e in entities[:30]))
    else:
        lines.append("*No structured entities detected.*")

    lines.append("")
    return "\n".join(lines)


def debundle_file(
    bundle_path: Union[str, Path],
    output_dir: Union[str, Path],
    beautify: bool = True,
) -> DebundleResult:
    """Debundle a single JavaScript file into readable module files and architecture docs."""
    bundle_path = Path(bundle_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    result = DebundleResult()
    raw_code = bundle_path.read_text(encoding="utf-8", errors="ignore")

    # Step 1: Extract Architecture
    arch = extract_bundle_architecture(raw_code, filename=bundle_path.name)
    result.routes = arch["routes"]
    result.endpoints = arch["endpoints"]
    result.components = arch["components"]

    arch_file = output_dir / "ARCHITECTURE.md"
    arch_file.write_text(generate_architecture_report(arch), encoding="utf-8")
    result.architecture_report = arch_file

    # Step 2: Try Webpack module extraction
    wp_modules = extract_webpack_modules(raw_code)

    if wp_modules:
        info(f"Detected Webpack bundle in {bundle_path.name}: extracting {len(wp_modules)} module(s)...")
        for key, code in wp_modules.items():
            clean_key = re.sub(r"^[./\\]+", "", key)
            if not clean_key.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".json")):
                clean_key = f"modules/module_{clean_key}.js"
            elif not clean_key.startswith(("src/", "modules/")):
                clean_key = f"src/{clean_key}"

            dest = output_dir / clean_key
            dest.parent.mkdir(parents=True, exist_ok=True)

            formatted = beautify_javascript(code) if beautify else code
            dest.write_text(formatted, encoding="utf-8")
            result.extracted_files[clean_key] = dest
            result.total_modules += 1

    # Step 3: Always produce a full beautified, readable source file of the chunk
    beautified_dir = output_dir / "beautified"
    beautified_dir.mkdir(parents=True, exist_ok=True)
    beautified_file = beautified_dir / bundle_path.name

    header_comment = (
        f"// ============================================================================\n"
        f"// Beautified & De-minified Source: {bundle_path.name}\n"
        f"// Generated by jsmap - https://github.com/Baba01hacker666/jsmap\n"
        f"// ============================================================================\n\n"
    )

    formatted_bundle = header_comment + (beautify_javascript(raw_code) if beautify else raw_code)
    beautified_file.write_text(formatted_bundle, encoding="utf-8")
    result.extracted_files[f"beautified/{bundle_path.name}"] = beautified_file
    result.total_modules += 1

    return result


def debundle_directory(
    directory: Union[str, Path],
    output_dir: Union[str, Path],
    beautify: bool = True,
) -> DebundleResult:
    """Debundle all JavaScript bundles in a directory."""
    dir_path = Path(directory).expanduser().resolve()
    out_path = Path(output_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    combined_result = DebundleResult()
    all_routes: Set[str] = set()
    all_endpoints: Set[str] = set()
    all_components: Set[str] = set()

    for js_file in sorted(dir_path.rglob("*.js")) + sorted(dir_path.rglob("*.mjs")):
        res = debundle_file(js_file, out_path, beautify=beautify)
        combined_result.total_modules += res.total_modules
        combined_result.extracted_files.update(res.extracted_files)
        all_routes.update(res.routes)
        all_endpoints.update(res.endpoints)
        all_components.update(res.components)

    combined_result.routes = sorted(all_routes)
    combined_result.endpoints = sorted(all_endpoints)
    combined_result.components = sorted(all_components)

    # Write combined ARCHITECTURE.md
    arch = {
        "file": f"{len(list(dir_path.rglob('*.js')))} downloaded chunk(s)",
        "routes": combined_result.routes,
        "endpoints": combined_result.endpoints,
        "components": combined_result.components,
    }
    arch_file = out_path / "ARCHITECTURE.md"
    arch_file.write_text(generate_architecture_report(arch), encoding="utf-8")
    combined_result.architecture_report = arch_file

    return combined_result

# jsmap

```
     ██╗███████╗███╗   ███╗ █████╗ ██████╗       ███████╗██╗   ██╗██╗████████╗███████╗
     ██║██╔════╝████╗ ████║██╔══██╗██╔══██╗      ██╔════╝██║   ██║██║╚══██╔══╝██╔════╝
     ██║███████╗██╔████╔██║███████║██████╔╝      ███████╗██║   ██║██║   ██║   █████╗
██   ██║╚════██║██║╚██╔╝██║██╔══██║██╔═══╝       ╚════██║██║   ██║██║   ██║   ██╔══╝
╚█████╔╝███████║██║ ╚═╝ ██║██║  ██║██║           ███████║╚██████╔╝██║   ██║   ███████╗
 ╚════╝ ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝           ╚══════╝ ╚═════╝ ╚═╝   ╚═╝   ╚══════╝
```

**Enhanced Modular JavaScript Analyzer** — a pip-installable toolkit for analyzing JavaScript assets you own or are authorized to assess. It supports asset discovery, source-map recovery, endpoint/configuration detection, structured reporting, and optional Angular build validation.

> Developed by **baba01hacker** · [Doraemon Cyber Team (DCT)](https://github.com/Baba01hacker666)

---

--

## Installation

**Requirements:** Python 3.9+

```bash
git clone https://github.com/Baba01hacker666/jsmap
cd jsmap
python -m pip install .

# Development install (tests and package build tools)
python -m pip install -e ".[dev]"
```

**Optional external tools (for `--all-extractors`):**

```bash
# ripgrep
apt install ripgrep   # Debian/Ubuntu
brew install ripgrep  # macOS
```

**For `--ng-build` (Phase 4):**

```bash
npm install -g @angular/cli
```

---

## Overview

jsmap supports modern JavaScript-heavy applications (Angular, React, Webpack, Next.js, Vue, and static bundles). Use it only for applications and artifacts you own or are explicitly authorized to assess.

**4-phase pipeline:**

```
Phase 1: Download    →  Auto-detect runtime.js, extract chunk map, download JS chunks + .map files
Phase 2: Extract     →  Multi-engine analysis: native regex, TruffleHog, ripgrep
Phase 3: Reconstruct →  Source tree recovery from .map files
Phase 4: Build       →  Scaffold Angular project + ng build --configuration production (Optional)
```


---

## Features

- **Auto chunk map detection** — Parses Webpack runtime.js for content-hash maps, named chunk maps, `case` switch patterns, and bracket notation variants
- **Source map fetching** — Automatically fetches and stores `.map` files referenced in JS (`sourceMappingURL`)
- **Pluggable extractor engine** — Abstract `BaseExtractor` interface; register native regex, TruffleHog, ripgrep, or custom engines
- **Comprehensive ruleset** — 20+ detection rules across secrets, endpoints, config, Angular/React routes, debug artifacts
- **Alternate path probing** — Falls back to `assets/`, `static/js/`, `js/`, `dist/`, `build/`, `public/` on 404
- **Source reconstruction** — Extracts `sourcesContent` from `.map` files into a navigable source tree
- **Angular project scaffold** — Creates a minimal Angular 17 project around recovered sources for `ng build` analysis
- **Strings dump** — Extracts all URLs, paths, and email addresses from JS chunks to `reports/all_strings.json`
- **Multi-format reporting** — JSON, HTML, Markdown, CSV, TXT reports; HTML report always generated
- **Threading + rate limiting** — Configurable thread count and per-request delay
- **Proxy support** — Full Burp/ZAP integration via `--proxy`
- **Custom headers + cookies** — Session injection for authenticated targets
- **Deduplication** — MD5 fingerprint dedup across findings from multiple extractors and files

---

## Detection Rules

| Category | Rule | Severity |
|----------|------|----------|
| Secrets | AWS Access Key ID (`AKIA...`) | CRITICAL |
| Secrets | AWS Secret Key | CRITICAL |
| Secrets | Google API Key (`AIza...`) | CRITICAL |
| Secrets | OpenAI API Key (`sk-...`, `sk-proj-...`) | CRITICAL |
| Secrets | Anthropic API Key (`sk-ant-...`) | CRITICAL |
| Secrets | Hugging Face Token (`hf_...`) | CRITICAL |
| Secrets | GitLab Token (`glpat-...`) | CRITICAL |
| Secrets | SendGrid API Key (`SG...`) | CRITICAL |
| Secrets | Stripe Live/Test Key | CRITICAL |
| Secrets | JWT Token | CRITICAL |
| Secrets | Private Key (PEM) | CRITICAL |
| Secrets | GitHub Token (`ghp_`, `github_pat_`) | CRITICAL |
| Secrets | Database Connection String (mongo/postgres/mysql/redis) | CRITICAL |
| Secrets | Generic API Key / Secret / Password | HIGH |
| Secrets | Firebase Config | HIGH |
| Secrets | Slack Webhook URL | HIGH |
| Config | S3 Bucket URL | HIGH |
| Config | GCS Bucket | HIGH |
| Config | Environment Config object | MEDIUM |
| Endpoints | REST API Path | INFO |
| Endpoints | GraphQL Endpoint / Query | INFO |
| Endpoints | WebSocket / SSE URL | MEDIUM |
| Angular | Route definitions (`path:`, `loadChildren:`, `loadComponent:`) | INFO |
| Angular | React Router paths | INFO |
| Angular | Exported `environment` constant | MEDIUM |
| Debug | Console log leaking sensitive keys | LOW |
| Debug | Debug/DevMode flags set to `true` | MEDIUM |
| Debug | Admin panel paths (`/admin`, `/swagger`, `/api-docs`) | HIGH |
| Debug | `sourceMappingURL` comment in JS | MEDIUM |


## Usage

```
jsmap [TARGET] [OPTIONS]
# TARGET can be a URL, a local directory, or a local .map / .js file!
```

### Basic Examples

```bash
# Reconstruct source code directly from a local .map file (like restore-source-tree or unwebpack)
jsmap ./bundle.js.map -o ./recovered_src

# Unpack inline sourcemaps from JS files in a local directory
jsmap ./dist --extract-sources -o ./recovered_src

# Reconstruct source code directly from a remote .map or .js URL
jsmap https://app.target.com/assets/main.js.map -o ./recovered_src

# Analyze a locally saved asset directory (no network access)
jsmap --analyze-only --dir ./assets -o ./jsmap-report
# Equivalent shortcut:
jsmap ./assets -o ./jsmap-report

# Full pipeline with all extractors + Angular build
jsmap https://app.target.com/ --all-extractors --ng-build

# Extract sources and run ng build
jsmap https://app.target.com/ --extract-sources --ng-build

# Use TruffleHog + ripgrep alongside native regex
jsmap https://app.target.com/ --use-ripgrep

# Analyze an existing directory (no download)
jsmap --analyze-only --dir ./jsmap_target_20250101/chunks/

# Download only, save to custom output directory
jsmap https://app.target.com/ --download-only -o /tmp/recon

# Run ng build on an existing ng_project (skip download/analysis)
jsmap --ng-only -o /tmp/recon/existing_output/

# Only show CRITICAL and HIGH findings
jsmap https://app.target.com/ --severity HIGH

# Authenticated target with Burp proxy
jsmap https://app.target.com/ \
    --cookie "session=abc123; auth=xyz" \
    --proxy http://127.0.0.1:8080 \
    --no-verify

# Custom headers + dump all strings
jsmap https://app.target.com/ \
    -H "Authorization: Bearer <token>" \
    -H "X-Custom-Header: value" \
    --strings

# Supply a chunk map JSON manually (bypass auto-detection)
jsmap https://app.target.com/ --map ./chunk_map.json

# Output in Markdown format with 10 threads
jsmap https://app.target.com/ --format md -t 10

# SARIF report for a code-scanning system; return exit status 1 on high findings
jsmap --analyze-only --dir ./assets --format sarif --redact --fail-on HIGH

# Rate-limited (500ms delay between requests), verbose
jsmap https://app.target.com/ -d 0.5 -v
```

---

## CLI Reference

```
positional:
  url                       Target URL (base of the Angular/Webpack app)

mode:
  --download-only           Phase 1 only — download chunks and maps
  --analyze-only            Phase 2 only — requires --dir
  --dir DIR                 Directory to analyze (used with --analyze-only)
  --ng-only                 Phase 4 only — run ng build on existing ng_project/

extractors:
  --all-extractors          Enable native regex + TruffleHog + ripgrep
  --use-trufflehog          Add TruffleHog to the extractor chain
  --use-ripgrep             Add ripgrep to the extractor chain
  --native-only             Native regex only (default)

download:
  -m, --map FILE            JSON chunk map file (skip auto-detection)
  -t, --threads N           Download threads (default: 5)
  -d, --delay SECONDS       Per-request delay (default: 0.0)
  --crawl-esm / --no-crawl-esm
                            Recursively crawl ES module import graphs when source files
                            like main.tsx are linked (default: true)
  --deep                    Deep crawl downloaded JS chunks for lazy-loaded modules,
                            dynamic imports, and secondary chunks; retry build
  --beautify / --no-beautify
                            Format, indent, and de-minify downloaded chunks and recovered
                            source files (default: true)
  --debundle / --no-debundle
                            Debundle and slice Webpack/Vite/Rollup chunks into modules
                            when no sourcemaps exist (default: true)

analysis:
  --severity LEVEL          Minimum severity to report: CRITICAL HIGH MEDIUM LOW INFO (default: INFO)
  --extract-sources         Phase 3: reconstruct source tree from .map files
  --strings                 Dump all URLs/paths/emails to reports/all_strings.json
  --no-print                Suppress console findings output

angular build:
  --ng-build                Phase 4: scaffold + ng build --configuration production
  --ng-version VERSION      Override Angular version (default: ^17.0.0)

output:
  -o, --output DIR          Output root directory
  --format FORMAT           Report format: json csv md txt html (default: json)
                            NOTE: JSON and HTML are always saved regardless of --format

network:
  --proxy URL               HTTP/HTTPS proxy (e.g. http://127.0.0.1:8080)
  --no-verify               Disable TLS verification
  --cookie STRING           Raw Cookie header value
  -H, --header KEY:VALUE    Extra request headers (repeatable)

  -v, --verbose             Verbose output
```

---

## What If No `.map` File Exists? (e.g. `main.tsx` Linked Directly)

In modern frontend frameworks (Vite, Astro, Next.js, Remix, SvelteKit) running in development, preview, or misconfigured production mode, there are often **no `.map` files at all**. Instead, `index.html` contains:

```html
<script type="module" src="/src/main.tsx"></script>
```

`jsmap` handles this scenario seamlessly through 4 layers of automated discovery:

1. **Modern Module Discovery:**
   - Detects `<script type="module" src="...">`, `<link rel="modulepreload" href="...">`, and direct links to `.tsx`, `.ts`, `.jsx`, `.vue`, and `.svelte` files.
   - Preserves source file extensions and relative directory structures (e.g., `src/main.tsx`).

2. **Recursive ESM Import Graph Crawling (`--crawl-esm`):**
   - Automatically parses ES module `import` and `export` statements (static imports, dynamic `import()`, re-exports).
   - Resolves relative paths (`./App.tsx`, `../components/Button`) and handles extensionless TypeScript/JavaScript imports (`./Header` → `./Header.tsx`, `./Header.ts`, etc.).
   - Recursively downloads the entire original application source tree.

3. **Webpack `eval()` with `sourceURL` Recovery:**
   - In Webpack development bundles (`devtool: 'eval'` or `eval-source-map`), modules are wrapped in `eval("... //# sourceURL=webpack:///./src/main.tsx")`.
   - `jsmap` parses and unescapes the code inside each `eval()` block and saves original files directly into `extracted_sources/` without requiring any `.map` file.

4. **Live Fallback for Missing `sourcesContent`:**
   - If a `.map` file is present but its `sourcesContent` field was stripped (`null`), `jsmap` automatically probes the live web server for each missing source path (e.g. `https://target.com/src/main.tsx`).

5. **Automated Code Beautification & De-minification (`--beautify`):**
   - Automatically de-minifies obfuscated constructs: expands minified booleans (`!0` → `true`, `!1` → `false`), expands `void 0` → `undefined`, formats keywords (`return!0` → `return true`), and safely unescapes unicode strings.
   - Formats JavaScript, TypeScript, CSS, and HTML with consistent 2-space indentation and line breaks, transforming 500 KB single-line blobs into readable, auditable code.

6. **Automated Debundling & Architecture Blueprint (`--debundle`):**
   - Slices Webpack chunk registries (`webpackChunk`, `webpackJsonp`, module arrays) into individual component and service files.
   - For Rollup/Vite/ESBuild bundles, extracts beautified source versions into `extracted_sources/beautified/`.
   - Generates `extracted_sources/ARCHITECTURE.md`, outlining all discovered frontend routes, API endpoints, key components, client storage keys, and data models directly from the minified bundles!

---

## Output Structure

```
jsmap_<host>_<timestamp>/
├── chunks/                 Raw downloaded JS chunks (.js files)
├── maps/                   Source map files (.map)
├── extracted_sources/      Reconstructed source tree (from Phase 3)
│   └── src/                Angular/React source hierarchy
├── ng_project/             Scaffolded Angular project (Phase 4)
│   ├── src/                Extracted sources copied here as src/recon/
│   └── dist/               ng build --configuration production output
├── reports/
│   ├── findings.json       Primary findings report (always saved)
│   ├── findings.html       HTML report (always saved)
│   ├── findings.<fmt>      Additional format if --format specified
│   └── all_strings.json    URL/path/email dump (with --strings)
├── logs/
│   ├── download.log        Per-chunk download log (JSON)
│   └── build.log           npm install + ng build output
└── summary.json            Top-level scan summary with finding counts
```

## Python API & Scripting Usage

`jsmap` provides a complete, modern Python API so you can use it directly in other scripts, automation pipelines, security tools, and CI/CD jobs.

### 1. Source Map Reconstruction & In-Memory Unpacking

```python
import jsmap

# Reconstruct original source files from a .map file, a .js file, or a directory:
result = jsmap.reconstruct("bundle.js.map", output_dir="./extracted_sources")
print(f"Extracted {result.total_files} files into {result.sources_directory}")

# In-memory unpacking without writing to disk:
sources = jsmap.unpack_sourcemap("bundle.js.map")
for file_path, code in sources.items():
    print(f"Source file: {file_path} ({len(code)} bytes)")
```

### 2. Scanning Code Snippets & Single Files

```python
import jsmap

# Quickly scan an in-memory snippet for secrets and endpoints:
findings = jsmap.scan_code("const apiKey = 'AKIAIOSFODNN7EXAMPLE';")
for f in findings:
    print(f"{f.severity} [{f.subcategory}] in {f.file}:{f.line} -> {f.value}")

# Scan a single JavaScript or TypeScript file:
file_findings = jsmap.scan_file("app.bundle.js", minimum_severity="HIGH")
```

### 3. Extracting Endpoints, URLs, Emails & IPs

```python
import jsmap

strings = jsmap.extract_strings("app.bundle.js")
print("Found URLs:", strings["urls"])
print("Found API Paths:", strings["paths"])
print("Found Emails:", strings["emails"])
print("Found IP Addresses:", strings["ips"])
```

### 4. Full Directory / Asset Analysis

```python
import jsmap

result = jsmap.analyze(
    target="./saved-assets",
    output="./analysis-output",
    options=jsmap.ScanOptions(
        minimum_severity="HIGH",
        extract_sources=True,
        extract_strings=True,
        report_format="sarif",
    ),
)

print(f"Total findings: {result.finding_count}")
print(f"Critical findings: {len(result.critical_findings)}")
if result.has_severity_at_least("CRITICAL"):
    print("Found critical security vulnerabilities!")
```

### 5. Programmatic Asset Downloading

```python
import jsmap

download_result = jsmap.download(
    "https://app.target.com",
    output="./downloads",
    threads=5,
    deep=True,            # Deep crawl for lazy-loaded modules and dynamic imports
    beautify=True,        # Automatically format & de-minify downloaded chunks
    extract_sources=True, # Automatically unpacks sourcemaps or falls back to debundling!
)
```

### 6. Standalone Code Beautification & De-minification

```python
import jsmap

# De-minify and format JavaScript/TypeScript code:
raw_js = "function test(a){if(a===!0)return!1;else return void 0;}"
readable = jsmap.beautify_code(raw_js)
print(readable)
# function test(a) {
#   if (a === true) return false;
#   else return undefined;
# }

# Format an entire file or directory:
jsmap.beautify_file("bundle.min.js", output_path="bundle.readable.js")
```

### 7. Module Debundling & Architecture Blueprint

```python
import jsmap

# Debundle a monolithic Webpack or Vite chunk without source maps:
result = jsmap.debundle("bundle.js", output_dir="./extracted_modules")
print(f"Extracted {result.total_modules} modules")
print(f"Discovered routes: {result.routes}")
print(f"Discovered endpoints: {result.endpoints}")

# Extract architecture blueprint directly:
blueprint = jsmap.get_architecture("bundle.js")
print(blueprint["routes"])
print(blueprint["components"])
```

The public package modules are organized as follows:

```
src/jsmap/
├── api.py             Stable local-analysis API and result models
├── beautifier.py      Code formatter & minification de-obfuscator (JS, CSS, HTML)
├── debundler.py       Module slicer & application architecture extractor
├── cli.py             Command-line interface and workflow coordinator
├── downloader.py      Asset and source-map retrieval
├── extractors.py      Native and optional extractor implementations
├── reconstructor.py   Source-map reconstruction and string extraction
├── reporting.py       JSON, CSV, Markdown, text, and HTML reports
├── layout.py          Output directory contract
├── network.py         HTTP session configuration
└── builder.py         Optional Angular build integration
```

Report formats include JSON, CSV, Markdown, text, HTML, and SARIF 2.1.0. Use `--redact` when reports might be shared outside the assessment team. Use `--fail-on HIGH` (or another severity) to make a scan suitable for CI gates.

---

## Chunk Map JSON Format

When using `--map` to bypass auto-detection, supply a JSON object mapping chunk IDs to content hashes:

```json
{
  "0":  "a1b2c3d4",
  "1":  "e5f6a7b8",
  "42": "main"
}
```

Chunk filenames are resolved as `<id_or_name>.<hash>.js`.

---

## Extractor Architecture

jsmap-suite uses an abstract `BaseExtractor` interface, making it trivial to add new analysis backends:

```python
class MyExtractor(BaseExtractor):
    @property
    def name(self) -> str:
        return "my-tool"

    @property
    def supported_extensions(self) -> tuple:
        return (".js", ".ts")

    def analyze_file(self, filepath: Path) -> List[Finding]:
        # Return list of Finding dataclass instances
        ...

# Register at runtime
orchestrator.register(MyExtractor())
```

The `Finding` dataclass fields: `category`, `subcategory`, `value`, `severity`, `file`, `line`, `context`, `confidence`, `tool`.

---

## Operational Notes

- **Authenticated targets** — Use `--cookie` for session cookies or `-H "Authorization: Bearer <token>"` for JWT-authenticated SPAs. Export cookies from Burp's Cookie Jar as a header string.
- **WAF evasion** — Combine `--delay 1.0` with `-t 1` for single-threaded slow scanning. The default `User-Agent` mimics Chrome 124.
- **Angular 17+ esbuild format** — Modern builds may use array-form chunk maps not fully covered by current patterns. If auto-detection yields 0 chunks, manually extract the chunk map from `runtime.js` and supply via `--map`.
- **Source map coverage** — `sourcesContent` must be present in `.map` files for Phase 3 to recover readable source. Production builds with `sourceMap: false` in `angular.json` won't have recoverable sources.
- **ng build utility** — Phase 4 is primarily useful for validating recovered source integrity and resolving TypeScript types. It requires a working Node.js + Angular CLI environment.



## Author

**baba01hacker** · Doraemon Cyber Team (DCT)

*Offensive security research · Web exploitation · CTF · CVE research*

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
jsmap [URL] [OPTIONS]
# equivalent: python -m jsmap [URL] [OPTIONS]
```

### Basic Examples

```bash
# Analyze a locally saved asset directory (no network access)
jsmap --analyze-only --dir ./assets -o ./jsmap-report

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

## Python API

Use the API when you want to include local asset analysis in a CI job or another Python tool. It makes no network requests.

```python
from jsmap import ScanOptions, analyze_directory

result = analyze_directory(
    "./saved-assets",
    "./analysis-output",
    ScanOptions(
        minimum_severity="MEDIUM",
        extract_sources=True,
        extract_strings=True,
        report_format="md",
    ),
)

print(result.finding_count)
print(result.report_paths["json"])
```

The public package modules are organized as follows:

```
src/jsmap/
├── api.py             Stable local-analysis API and result models
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

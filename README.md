# jsmap-suite

```
     ██╗███████╗███╗   ███╗ █████╗ ██████╗       ███████╗██╗   ██╗██╗████████╗███████╗
     ██║██╔════╝████╗ ████║██╔══██╗██╔══██╗      ██╔════╝██║   ██║██║╚══██╔══╝██╔════╝
     ██║███████╗██╔████╔██║███████║██████╔╝      ███████╗██║   ██║██║   ██║   █████╗
██   ██║╚════██║██║╚██╔╝██║██╔══██║██╔═══╝       ╚════██║██║   ██║██║   ██║   ██╔══╝
╚█████╔╝███████║██║ ╚═╝ ██║██║  ██║██║           ███████║╚██████╔╝██║   ██║   ███████╗
 ╚════╝ ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝           ╚══════╝ ╚═════╝ ╚═╝   ╚═╝   ╚══════╝
```

**Enhanced Modular JavaScript Recon Suite** — Webpack chunk harvesting, secret/endpoint extraction, source map reconstruction, and Angular build integration for web application security assessments.

> Developed by **baba01hacker** · [Doraemon Cyber Team (DCT)](https://github.com)

---

## Overview

jsmap-suite is an offensive reconnaissance tool targeting modern JavaScript-heavy web applications (Angular, React, Webpack). It automates the full recon pipeline from chunk discovery to source recovery, surfacing hardcoded secrets, internal API endpoints, environment configs, and debug artifacts that developers accidentally ship to production.

**4-phase pipeline:**

```
Phase 1: Download    →  Auto-detect runtime.js, extract chunk map, download all JS chunks + .map files
Phase 2: Extract     →  Multi-engine analysis: native regex, TruffleHog, ripgrep
Phase 3: Reconstruct →  Source tree recovery from .map files
Phase 4: Build       →  Scaffold Angular project + ng build --configuration production
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

---

## Installation

**Requirements:** Python 3.9+

```bash
git clone https://github.com/baba01hacker/jsmap-suite
cd jsmap-suite
pip install requests urllib3
```

**Optional external tools (for `--all-extractors`):**

```bash
# TruffleHog
curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sh

# ripgrep
apt install ripgrep   # Debian/Ubuntu
brew install ripgrep  # macOS
```

**For `--ng-build` (Phase 4):**

```bash
npm install -g @angular/cli
```

---

## Usage

```
python3 jsmap_suite.py [URL] [OPTIONS]
```

### Basic Examples

```bash
# Full recon against a target
python3 jsmap_suite.py https://app.target.com/

# Full pipeline with all extractors + Angular build
python3 jsmap_suite.py https://app.target.com/ --all-extractors --ng-build

# Extract sources and run ng build
python3 jsmap_suite.py https://app.target.com/ --extract-sources --ng-build

# Use TruffleHog + ripgrep alongside native regex
python3 jsmap_suite.py https://app.target.com/ --use-trufflehog --use-ripgrep

# Analyze an existing directory (no download)
python3 jsmap_suite.py --analyze-only --dir ./jsmap_target_20250101/chunks/

# Download only, save to custom output directory
python3 jsmap_suite.py https://app.target.com/ --download-only -o /tmp/recon

# Run ng build on an existing ng_project (skip download/analysis)
python3 jsmap_suite.py --ng-only -o /tmp/recon/existing_output/

# Only show CRITICAL and HIGH findings
python3 jsmap_suite.py https://app.target.com/ --severity HIGH

# Authenticated target with Burp proxy
python3 jsmap_suite.py https://app.target.com/ \
    --cookie "session=abc123; auth=xyz" \
    --proxy http://127.0.0.1:8080 \
    --no-verify

# Custom headers + dump all strings
python3 jsmap_suite.py https://app.target.com/ \
    -H "Authorization: Bearer <token>" \
    -H "X-Custom-Header: value" \
    --strings

# Supply a chunk map JSON manually (bypass auto-detection)
python3 jsmap_suite.py https://app.target.com/ --map ./chunk_map.json

# Output in Markdown format with 10 threads
python3 jsmap_suite.py https://app.target.com/ --format md -t 10

# Rate-limited (500ms delay between requests), verbose
python3 jsmap_suite.py https://app.target.com/ -d 0.5 -v
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

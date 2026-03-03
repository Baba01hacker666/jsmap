#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║                                                                          ║
║        jsmap-suite  ——  by baba01hacker                                  ║
║                                                                          ║
║   All-in-one Angular / Webpack / React / Vue JS Recon Tool               ║
║                                                                          ║
║   Phase 1 ▸ Download   — Webpack chunk map resolution + fetch            ║
║   Phase 2 ▸ Analyze    — Static analysis engine                          ║
║   Phase 3 ▸ Extract    — Source map reconstruction                       ║
║                                                                          ║
║   Finds:                                                                 ║
║     • API endpoints  (REST, GraphQL, WebSocket, gRPC)                    ║
║     • Secrets        (AWS, GCP, Stripe, JWT, tokens, passwords)          ║
║     • Config objects (env vars, feature flags, base URLs)                ║
║     • Hidden routes  (Angular router, React Router, lazy routes)         ║
║     • Cloud storage  (S3, GCS, Azure Blob, CDN refs)                     ║
║     • Auth artifacts (OAuth, Firebase, OIDC, SAML endpoints)             ║
║     • Debug/Dev      (console.log leaks, debug flags, admin panels)      ║
║     • Source files   (embedded TS/JS from .map sourcesContent)           ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import json
import time
import hashlib
import argparse
import requests
import urllib3
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse


# ══════════════════════════════════════════════════════════════════════════════
#  COLORS & LOGGING
# ══════════════════════════════════════════════════════════════════════════════

class C:
    RESET   = "\033[0m";  BOLD    = "\033[1m";  DIM     = "\033[2m"
    RED     = "\033[31m"; GREEN   = "\033[32m";  YELLOW  = "\033[33m"
    BLUE    = "\033[34m"; MAGENTA = "\033[35m";  CYAN    = "\033[36m"
    WHITE   = "\033[97m"; GRAY    = "\033[90m"
    BG_RED  = "\033[41m"; BG_YLW  = "\033[43m";  BG_GRN  = "\033[42m"
    BG_CYN  = "\033[46m"


def banner():
    print(f"""\
{C.MAGENTA}{C.BOLD}
     ██╗███████╗███╗   ███╗ █████╗ ██████╗       ███████╗██╗   ██╗██╗████████╗███████╗
     ██║██╔════╝████╗ ████║██╔══██╗██╔══██╗      ██╔════╝██║   ██║██║╚══██╔══╝██╔════╝
     ██║███████╗██╔████╔██║███████║██████╔╝      ███████╗██║   ██║██║   ██║   █████╗
██   ██║╚════██║██║╚██╔╝██║██╔══██║██╔═══╝       ╚════██║██║   ██║██║   ██║   ██╔══╝
╚█████╔╝███████║██║ ╚═╝ ██║██║  ██║██║           ███████║╚██████╔╝██║   ██║   ███████╗
 ╚════╝ ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝           ╚══════╝ ╚═════╝ ╚═╝   ╚═╝   ╚══════╝
{C.RESET}{C.YELLOW}  Angular / Webpack / React / Vue  —  Full Recon Suite{C.RESET}
{C.GRAY}  Download · Analyze · Extract  |  by baba01hacker{C.RESET}
{C.CYAN}  Endpoints · Secrets · Config · Routes · Cloud · Source Maps{C.RESET}
""")


def _log(prefix, color, msg):
    print(f"{color}{prefix}{C.RESET} {msg}")

def info(m):     _log("[*]", C.CYAN,    m)
def success(m):  _log("[+]", C.GREEN,   m)
def warn(m):     _log("[!]", C.YELLOW,  m)
def error(m):    _log("[-]", C.RED,     m)
def critical(m): print(f"{C.BG_RED}{C.WHITE}[!!]{C.RESET} {C.RED}{C.BOLD}{m}{C.RESET}")
def section(m):  print(f"\n{C.BOLD}{C.BLUE}{'─'*65}\n  {m}\n{'─'*65}{C.RESET}")
def dim(m):      print(f"{C.GRAY}    {m}{C.RESET}")
def step(n, m):  print(f"\n{C.BG_CYN}{C.WHITE} PHASE {n} {C.RESET} {C.BOLD}{m}{C.RESET}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — DOWNLOADER
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}


def extract_chunk_map_from_runtime(content: str) -> dict:
    """
    Parses Webpack runtime.js to extract chunk_id → hash mappings.
    Handles Webpack 4, 5, and Angular CLI formats.
    """
    chunk_map = {}

    # Pattern 1: object literal  { "76":"094b5e...", "112":"f831.." }
    pat1 = r'\{(\s*(?:"?\d+"?\s*:\s*"[a-f0-9]+"(?:\s*,\s*)?)+)\}'
    for match in re.findall(pat1, content):
        pairs = re.findall(r'"?(\d+)"?\s*:\s*"([a-f0-9]{8,})"', match)
        if len(pairs) > 2:
            for chunk_id, chunk_hash in pairs:
                chunk_map[chunk_id] = chunk_hash

    # Pattern 2: Webpack 5 array format  [chunkId, "hash"]
    for chunk_id, chunk_hash in re.findall(r'\[\s*(\d+)\s*,\s*"([a-f0-9]{8,})"', content):
        chunk_map[chunk_id] = chunk_hash

    # Pattern 3: Angular 17+ esbuild format — chunkId:"hash"  (no quotes on key)
    for chunk_id, chunk_hash in re.findall(r'(\d+):"([a-f0-9]{8,})"', content):
        chunk_map[chunk_id] = chunk_hash

    # Pattern 4: switch-case map  case 76: return "094b5e..."
    for chunk_id, chunk_hash in re.findall(r'case\s+(\d+)\s*:\s*return\s*["\']([a-f0-9]{8,})["\']', content):
        chunk_map[chunk_id] = chunk_hash

    return chunk_map


def extract_named_chunks(content: str) -> dict:
    """Extract named chunk overrides: e.g. 76 === e ? "common" : e"""
    special = {}
    for cid, cname in re.findall(r'(\d+)\s*===\s*\w+\s*\?\s*"([a-zA-Z0-9_\-]+)"', content):
        special[cid] = cname
    # Also: { 76: "common", 204: "shared" }  (string values, not hashes)
    for cid, cname in re.findall(r'"?(\d+)"?\s*:\s*"([a-zA-Z][a-zA-Z0-9_\-]+)"', content):
        if not re.match(r'^[a-f0-9]{8,}$', cname):  # not a hash
            special[cid] = cname
    return special


def resolve_chunk_filename(chunk_id: str, chunk_hash: str, special_names: dict = None) -> str:
    special_names = special_names or {}
    prefix = special_names.get(chunk_id, chunk_id)
    return f"{prefix}.{chunk_hash}.js"


def try_alternate_paths(session, base_url: str, filename: str) -> requests.Response | None:
    """Try common alternate asset serving paths when primary 404s."""
    alt_prefixes = ["assets/", "static/js/", "js/", "dist/", "build/", "public/"]
    for prefix in alt_prefixes:
        try:
            alt_url = urljoin(base_url, prefix + filename)
            r = session.get(alt_url, timeout=8)
            if r.status_code == 200:
                info(f"  Found at alternate path: {prefix}{filename}")
                return r
        except Exception:
            pass
    return None


def download_chunk(session, base_url: str, chunk_id: str, chunk_hash: str,
                   save_dir: Path, special_names: dict, delay: float = 0.0) -> dict:

    filename  = resolve_chunk_filename(chunk_id, chunk_hash, special_names)
    url       = urljoin(base_url, filename)
    save_path = save_dir / filename

    if save_path.exists():
        warn(f"Already exists, skipping: {filename}")
        return {"status": "skipped", "filename": filename, "chunk_id": chunk_id, "url": url}

    if delay > 0:
        time.sleep(delay)

    try:
        resp = session.get(url, timeout=15)

        if resp.status_code == 200:
            save_path.write_bytes(resp.content)
            size = len(resp.content)
            success(f"Downloaded: {filename} ({size:,} bytes)")
            return {"status": "ok", "filename": filename, "chunk_id": chunk_id, "size": size, "url": url}

        elif resp.status_code == 404:
            # Try alternate asset paths
            alt = try_alternate_paths(session, base_url, filename)
            if alt:
                save_path.write_bytes(alt.content)
                return {"status": "ok", "filename": filename, "chunk_id": chunk_id,
                        "size": len(alt.content), "url": url, "note": "alternate_path"}
            error(f"Not found (404): {filename}")
            return {"status": "404", "filename": filename, "chunk_id": chunk_id, "url": url}

        else:
            error(f"HTTP {resp.status_code}: {filename}")
            return {"status": f"http_{resp.status_code}", "filename": filename, "chunk_id": chunk_id, "url": url}

    except requests.exceptions.ConnectionError:
        error(f"Connection error: {url}")
        return {"status": "conn_error", "filename": filename, "chunk_id": chunk_id}
    except requests.exceptions.Timeout:
        error(f"Timeout: {url}")
        return {"status": "timeout", "filename": filename, "chunk_id": chunk_id}
    except Exception as e:
        error(f"Unexpected: {filename}: {e}")
        return {"status": "error", "filename": filename, "chunk_id": chunk_id}


def auto_detect_chunks(session, base_url: str) -> tuple[dict, dict, list]:
    """
    Fetch index.html → find runtime.js → extract chunk map.
    Also returns list of all found script URLs for direct download.
    Returns: (chunk_map, special_names, all_script_urls)
    """
    chunk_map     = {}
    special_names = {}
    all_scripts   = []

    info("Auto-detect: fetching index.html ...")
    try:
        resp = session.get(base_url, timeout=15)
        html = resp.text

        # Find all script tags
        raw_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', html)
        # Also grab from ngsw-config, angular.json style references
        raw_srcs += re.findall(r'"([^"]*\.js)"', html)

        for src in raw_srcs:
            try:
                full = urljoin(base_url, src.split("?")[0])
                if full not in all_scripts:
                    all_scripts.append(full)
                    dim(f"Script found: {src}")
            except Exception:
                pass

        info(f"Found {len(all_scripts)} script references")

        # Find runtime.js (contains hash map)
        runtime_url = None
        for url in all_scripts:
            if re.search(r'runtime', url, re.IGNORECASE):
                runtime_url = url
                break

        # Fallback guesses for runtime
        if not runtime_url:
            guesses = ["runtime.js", "runtime.min.js", "webpack-runtime.js",
                       "webpack.runtime.js", "app/runtime.js"]
            for g in guesses:
                test = urljoin(base_url, g)
                try:
                    r = session.get(test, timeout=5)
                    if r.status_code == 200 and ("webpackChunk" in r.text or "installedChunks" in r.text):
                        runtime_url = test
                        break
                except Exception:
                    pass

        if runtime_url:
            info(f"Fetching runtime: {runtime_url}")
            r = session.get(runtime_url, timeout=15)
            if r.status_code == 200:
                chunk_map = extract_chunk_map_from_runtime(r.text)
                if chunk_map:
                    success(f"Extracted {len(chunk_map)} chunks from runtime.js")
                special_names = extract_named_chunks(r.text)
                for cid, cname in special_names.items():
                    dim(f"Named chunk: {cid} → {cname}")
        else:
            warn("runtime.js not found. Falling back to direct script list.")

    except Exception as e:
        warn(f"Auto-detect failed: {e}")

    return chunk_map, special_names, all_scripts


def run_downloader(args, session: requests.Session, out_dir: Path) -> Path:
    """Phase 1: Download all chunks. Returns the directory with .js files."""

    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    base_url      = args.url.rstrip("/") + "/"
    chunk_map     = {}
    special_names = {}
    extra_scripts = []

    # ── Load / detect chunk map ─────────────────────────────────────────────
    if args.map:
        with open(args.map, "r") as f:
            chunk_map = json.load(f)
        info(f"Loaded {len(chunk_map)} chunks from {args.map}")

    elif not args.analyze_only:
        chunk_map, special_names, extra_scripts = auto_detect_chunks(session, base_url)

        if not chunk_map and not extra_scripts:
            # Fall back to inline default map
            warn("Auto-detect yielded nothing. Using inline example map.")
            chunk_map = {
                "76":  "094b5eab94e0a416",
                "112": "f83178c104f02a30",
                "204": "e2ca5d6df7d6d0c5",
                "254": "4403a23de181bef1",
                "273": "55c53802d2ada142",
                "277": "b10985ae2fcf3181",
                "306": "e2a2400c8760d048",
                "377": "e366cf539875560e",
                "481": "56d919162816907d",
                "499": "219cce52a480f28b",
                "524": "46f6348ebeb460e3",
                "545": "88be9176d1e5dd56",
                "561": "f0510bb6acf7a7ec",
                "589": "55e760e6ca20db15",
                "644": "22c290754ed70d00",
                "666": "06a43939552675dc",
                "684": "0d308d8f31481349",
                "712": "f2768ce2c7ef7486",
                "715": "513807d75b8378af",
                "750": "16a3c0ffaed9c1fd",
                "806": "cfedbf2ee5bd3670",
            }
            special_names = {"76": "common"}

    # Save chunk map
    if chunk_map:
        (chunks_dir / "chunk_map.json").write_text(json.dumps(chunk_map, indent=2))
        info(f"Chunk map: {len(chunk_map)} entries")

    # ── Download chunks via map ──────────────────────────────────────────────
    results = []
    stats   = {"ok": 0, "skipped": 0, "failed": 0}

    if chunk_map:
        info(f"Downloading {len(chunk_map)} chunks | threads={args.threads} | delay={args.delay}s")
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futures = {
                ex.submit(download_chunk, session, base_url, cid, chash,
                          chunks_dir, special_names, args.delay): cid
                for cid, chash in chunk_map.items()
            }
            for fut in as_completed(futures):
                r = fut.result()
                results.append(r)
                if r["status"] == "ok":       stats["ok"] += 1
                elif r["status"] == "skipped": stats["skipped"] += 1
                else:                          stats["failed"] += 1

    # ── Download extra directly-linked scripts ───────────────────────────────
    if extra_scripts:
        info(f"Downloading {len(extra_scripts)} directly linked scripts ...")
        for url in extra_scripts:
            fname = url.split("/")[-1].split("?")[0]
            if not fname.endswith(".js"):
                fname += ".js"
            save_path = chunks_dir / fname
            if save_path.exists():
                continue
            try:
                r = session.get(url, timeout=15)
                if r.status_code == 200:
                    save_path.write_bytes(r.content)
                    success(f"Downloaded: {fname} ({len(r.content):,} bytes)")
                    stats["ok"] += 1
            except Exception as e:
                warn(f"Failed {fname}: {e}")

    # ── Also try to download .map files for each downloaded .js ─────────────
    info("Attempting to fetch .map files ...")
    map_count = 0
    for js_file in chunks_dir.glob("*.js"):
        content = js_file.read_text(encoding="utf-8", errors="ignore")
        map_ref = re.search(r'//[#@]\s*sourceMappingURL=([^\s]+)', content)
        if map_ref:
            map_ref_val = map_ref.group(1).strip()
            if not map_ref_val.startswith("data:"):
                map_url = urljoin(base_url, map_ref_val)
                map_path = chunks_dir / (js_file.name + ".map")
                if not map_path.exists():
                    try:
                        mr = session.get(map_url, timeout=10)
                        if mr.status_code == 200:
                            map_path.write_bytes(mr.content)
                            dim(f"Map fetched: {js_file.name}.map")
                            map_count += 1
                    except Exception:
                        pass
    if map_count:
        success(f"Downloaded {map_count} source map files")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print(f"{C.BOLD}{'─'*55}{C.RESET}")
    print(f"{C.BOLD}  DOWNLOAD SUMMARY{C.RESET}")
    print(f"{'─'*55}")
    print(f"  {C.GREEN}Downloaded : {stats['ok']}{C.RESET}")
    print(f"  {C.YELLOW}Skipped    : {stats['skipped']}{C.RESET}")
    print(f"  {C.RED}Failed     : {stats['failed']}{C.RESET}")
    print(f"{'─'*55}")

    (chunks_dir / "download_log.json").write_text(json.dumps(results, indent=2))

    return chunks_dir


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — ANALYZER ENGINE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Finding:
    category:    str
    subcategory: str
    value:       str
    severity:    str          # CRITICAL / HIGH / MEDIUM / LOW / INFO
    file:        str
    line:        int
    context:     str = ""
    confidence:  str = "HIGH"

    def sev_color(self):
        return {
            "CRITICAL": C.BG_RED + C.WHITE,
            "HIGH":     C.RED,
            "MEDIUM":   C.YELLOW,
            "LOW":      C.CYAN,
            "INFO":     C.GRAY,
        }.get(self.severity, C.RESET)


RULES = {

    # ── API Endpoints ─────────────────────────────────────────────────────────
    "endpoints": [
        {
            "name":     "REST API Path",
            "severity": "INFO",
            "patterns": [
                r'(?:fetch|axios\.(?:get|post|put|patch|delete|request)|http(?:Client)?\.(?:get|post|put|patch|delete))\s*\(\s*[`"\']([/][^`"\']{3,200})[`"\']',
                r'`([/][a-zA-Z0-9_\-/]*(?:api|v\d|rest|endpoint|service|data|user|auth|account|admin)[^`\n]{0,120})`',
                r'["\'](\/(api|v\d+|rest|graphql|gql|auth|oauth|user|admin|account|service|internal|'
                r'private|public|health|status|webhook|notify|search|upload|download|report|export|'
                r'dashboard|settings|profile|payment|order|product|cart|checkout)[/a-zA-Z0-9_\-.:?=%&{}]{2,120})["\']',
            ],
            "blacklist": [r'node_modules', r'\.spec\.', r'\.test\.', r'example\.com',
                          r'localhost:\d{4}(?!/api)', r'schema\.org'],
        },
        {
            "name":     "GraphQL Endpoint / Operation",
            "severity": "INFO",
            "patterns": [
                r'["\`]((?:query|mutation|subscription)\s+\w+[^"\`]{10,300})["\`]',
                r'gql`([^`]{10,500})`',
                r'["\']([^"\']*\/graphql[^"\']{0,60})["\']',
                r'operationName\s*:\s*["\']([^"\']{3,80})["\']',
            ],
        },
        {
            "name":     "WebSocket / SSE URL",
            "severity": "MEDIUM",
            "patterns": [
                r'["\`](wss?://[^\s"\'`]{5,200})["\`]',
                r'new\s+WebSocket\s*\(\s*[`"\']([^"\'`]+)[`"\']',
                r'new\s+EventSource\s*\(\s*[`"\']([^"\'`]+)[`"\']',
                r'["\`](https?://[^\s"\'`]+/(?:sse|events|stream|subscribe|ws)[^\s"\'`]{0,80})["\`]',
            ],
        },
        {
            "name":     "Base URL / API Host",
            "severity": "MEDIUM",
            "patterns": [
                r'(?:baseUrl|apiUrl|baseURL|apiHost|API_URL|BASE_URL|apiBase|serverUrl|'
                r'backendUrl|serviceUrl|remoteUrl|apiEndpoint|API_ENDPOINT|apiRoot)\s*[=:]\s*["\`](https?://[^"\`\s]{5,200})["\`]',
                r'["\`](https?://(?:api|backend|service|internal|staging|prod|dev|uat|test|qa|'
                r'sandbox|preprod)\.[a-zA-Z0-9\-\.]{3,80}(?:/[a-zA-Z0-9/_\-]*)?)["\`]',
            ],
        },
        {
            "name":     "gRPC / Protobuf Endpoint",
            "severity": "MEDIUM",
            "patterns": [
                r'["\`](https?://[^"\'`\s]+:\d{4,5})["\`]',
                r'(?:grpcUrl|grpc_url|grpcHost)\s*[=:]\s*["\`]([^"\`\s]{5,150})["\`]',
            ],
        },
        {
            "name":     "OIDC / SSO Endpoint",
            "severity": "MEDIUM",
            "patterns": [
                r'(?:issuer|authority|stsServer|openIdConnect|oidcUrl|ssoUrl)\s*[=:]\s*["\`](https?://[^"\`\s]{5,200})["\`]',
                r'["\`](https?://[^\s"\'`]*(?:\.auth\.|/auth/|/oauth2/|/oidc/|/saml/|/sso/|/login|/token|/authorize)[^"\`\s]{0,100})["\`]',
            ],
        },
    ],

    # ── Secrets & Credentials ─────────────────────────────────────────────────
    "secrets": [
        {
            "name":     "AWS Access Key ID",
            "severity": "CRITICAL",
            "patterns": [r'(AKIA[0-9A-Z]{16})'],
        },
        {
            "name":     "AWS Secret Access Key",
            "severity": "CRITICAL",
            "patterns": [r'(?:aws[_\-]?secret|secretAccessKey|secret_access_key|AWS_SECRET)\s*[=:]\s*["\']([A-Za-z0-9/+]{40})["\']'],
        },
        {
            "name":     "Google API Key",
            "severity": "CRITICAL",
            "patterns": [r'(AIza[0-9A-Za-z\-_]{35})'],
        },
        {
            "name":     "Firebase Config",
            "severity": "HIGH",
            "patterns": [
                r'apiKey\s*:\s*["\']([^"\']{20,})["\']',
                r'(?:databaseURL|storageBucket|messagingSenderId|appId|measurementId)\s*:\s*["\']([^"\']{5,100})["\']',
                r'firebaseConfig\s*[=:]\s*\{([^}]{50,600})\}',
                r'initializeApp\s*\(\s*(\{[^)]{30,500}\})',
            ],
        },
        {
            "name":     "Stripe Key",
            "severity": "CRITICAL",
            "patterns": [r'((?:pk|sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,})'],
        },
        {
            "name":     "JWT Token (hardcoded)",
            "severity": "CRITICAL",
            "patterns": [r'["\`](ey[A-Za-z0-9\-_]{20,}\.ey[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,})["\`]'],
        },
        {
            "name":     "JWT / Signing Secret",
            "severity": "CRITICAL",
            "patterns": [
                r'(?:jwt[_\-]?secret|jwtSecret|JWT_SECRET|secretKey|signingKey|signing[_-]?key|'
                r'TOKEN_SECRET|APP_SECRET|SESSION_SECRET)\s*[=:]\s*["\']([^"\']{8,})["\']',
                r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
            ],
        },
        {
            "name":     "Generic API Key / Bearer Token",
            "severity": "HIGH",
            "patterns": [
                r'(?:api[_\-]?key|apiKey|API_KEY|x-api-key|access[_\-]?token|accessToken|'
                r'auth[_\-]?token|authToken|bearer[_\-]?token|BEARER_TOKEN|service[_-]?key)\s*[=:]\s*["\']([A-Za-z0-9\-_./+]{16,})["\']',
                r'(?:token|secret|password|passwd|pwd|credential|pass)\s*[=:]\s*["\']([A-Za-z0-9\-_@#$!%^&*]{8,})["\']',
            ],
            "blacklist": [r'placeholder', r'your[_\-]?', r'<token>', r'XXXX', r'\$\{', r'process\.env',
                          r'{{', r'__TOKEN__', r'INSERT_', r'REPLACE_'],
        },
        {
            "name":     "SendGrid / Mailgun / Twilio",
            "severity": "CRITICAL",
            "patterns": [
                r'(SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43})',
                r'(key-[a-z0-9]{32})',
                r'(AC[a-z0-9]{32})',
                r'(SK[a-z0-9]{32})',
            ],
        },
        {
            "name":     "GitHub / GitLab / Bitbucket Token",
            "severity": "CRITICAL",
            "patterns": [
                r'(gh[pousr]_[A-Za-z0-9_]{36,})',
                r'(glpat-[A-Za-z0-9\-_]{20,})',
                r'(ATBB[A-Za-z0-9]{32,})',
            ],
        },
        {
            "name":     "Slack Token / Webhook",
            "severity": "HIGH",
            "patterns": [
                r'(xox[baprs]-[A-Za-z0-9\-]{10,})',
                r'(https://hooks\.slack\.com/services/[A-Za-z0-9/]{30,})',
                r'(https://hooks\.slack\.com/workflows/[A-Za-z0-9/]{20,})',
            ],
        },
        {
            "name":     "Mapbox / Algolia / Pusher Token",
            "severity": "HIGH",
            "patterns": [
                r'(pk\.eyJ[A-Za-z0-9\-_]{20,})',       # Mapbox
                r'([A-Z0-9]{10})',                        # Algolia App ID (heuristic)
                r'(app_[a-z0-9]{8,})',                   # Pusher app key
            ],
        },
        {
            "name":     "Private IP / Internal Hostname",
            "severity": "MEDIUM",
            "patterns": [
                r'["\`]((?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?::\d+)?(?:/[^\s"\'`]*)?)["\`]',
                r'["\`](https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)[:\d/][^\s"\'`]{0,80})["\`]',
                r'["\`](https?://(?:[a-z0-9\-]+\.(?:internal|local|corp|intranet|lan))[^\s"\'`]{0,80})["\`]',
            ],
        },
        {
            "name":     "PEM / Certificate Material",
            "severity": "CRITICAL",
            "patterns": [
                r'-----BEGIN (?:CERTIFICATE|PUBLIC KEY|RSA PUBLIC KEY)-----',
                r'(MII[A-Za-z0-9+/]{20,}={0,2})',  # DER-encoded base64 cert/key
            ],
        },
    ],

    # ── Config & Environment ─────────────────────────────────────────────────
    "config": [
        {
            "name":     "Environment Config Object",
            "severity": "MEDIUM",
            "patterns": [
                r'(?:environment|config|appConfig|APP_CONFIG|appSettings|APP_SETTINGS)\s*=\s*(\{[^;]{30,1500}\})',
                r'(?:production|staging|development|isProduction|isDevelopment)\s*:\s*(?:true|false)',
                r'(?:enableDebug|debugMode|devMode|isDev|verbose|enableLogging)\s*[=:]\s*(?:true|false)',
            ],
        },
        {
            "name":     "Feature Flags",
            "severity": "LOW",
            "patterns": [
                r'(?:featureFlag|feature[_\-]?toggle|enableFeature|FEATURE_[A-Z_]+|flags?[_\-]?[A-Z_]+)\s*[=:]\s*(?:true|false|["\'][^"\']{1,80}["\'])',
            ],
        },
        {
            "name":     "Database / Connection String",
            "severity": "CRITICAL",
            "patterns": [
                r'["\`]((?:mongodb|postgres|postgresql|mysql|redis|mssql|oracle|jdbc|cassandra|couchdb|dynamodb)\+?://[^\s"\'`]{10,250})["\`]',
                r'(?:connectionString|db[_\-]?url|DATABASE_URL|MONGO_URI|REDIS_URL|DB_HOST|DB_CONN)\s*[=:]\s*["\']([^"\']{10,250})["\']',
            ],
        },
        {
            "name":     "AWS S3 / Cloud Storage Bucket",
            "severity": "HIGH",
            "patterns": [
                r'["\`](s3://[a-zA-Z0-9\-._/]{5,200})["\`]',
                r'["\`](https://[a-zA-Z0-9\-]+\.s3(?:\.[a-zA-Z0-9\-]+)?\.amazonaws\.com[/a-zA-Z0-9\-._?=&%]{0,200})["\`]',
                r'(?:s3Bucket|bucketName|storageBucket|S3_BUCKET|BUCKET_NAME)\s*[=:]\s*["\']([^"\']{3,80})["\']',
                r'["\`](https://[a-zA-Z0-9\-]+\.blob\.core\.windows\.net[^"\'`\s]{0,200})["\`]',
                r'["\`](https://storage\.googleapis\.com/[^"\'`\s]{3,200})["\`]',
                r'["\`](https://[a-zA-Z0-9\-]+\.digitaloceanspaces\.com[^"\'`\s]{0,200})["\`]',
            ],
        },
        {
            "name":     "OAuth / SSO / OIDC Config",
            "severity": "HIGH",
            "patterns": [
                r'(?:clientId|client_id|CLIENT_ID|oauthClientId|appClientId)\s*[=:]\s*["\']([A-Za-z0-9\-_.@]{8,200})["\']',
                r'(?:clientSecret|client_secret|CLIENT_SECRET|oauthSecret)\s*[=:]\s*["\']([A-Za-z0-9\-_.]{8,200})["\']',
                r'(?:tenantId|tenant_id|TENANT_ID|directoryId)\s*[=:]\s*["\']([A-Za-z0-9\-]{8,50})["\']',
                r'(?:redirectUri|redirect_uri|callbackUrl|CALLBACK_URL)\s*[=:]\s*["\`](https?://[^"\'`\s]{5,200})["\`]',
            ],
        },
        {
            "name":     "Hardcoded Credentials",
            "severity": "CRITICAL",
            "patterns": [
                r'(?:username|user)\s*[=:]\s*["\']([a-zA-Z0-9@._\-]{3,50})["\'].*?(?:password|passwd|pwd)\s*[=:]\s*["\']([^"\']{3,80})["\']',
                r'(?:password|passwd|pwd|defaultPassword|default_password)\s*[=:]\s*["\']([^"\']{6,})["\']',
                r'(?:admin|root|superuser)[_\-]?(?:pass|password|passwd|pwd|key)\s*[=:]\s*["\']([^"\']{3,})["\']',
            ],
            "blacklist": [r'placeholder', r'your[_\-]?password', r'\*{3,}', r'password123',
                          r'change[_\-]?me', r'changeme', r'\$\{', r'{{'],
        },
        {
            "name":     "CORS / CSP / Security Headers Config",
            "severity": "MEDIUM",
            "patterns": [
                r'(?:allowedOrigins|corsOrigins|cors[_\-]?origin|ALLOWED_ORIGINS)\s*[=:]\s*[\[\(]([^\]\)]{5,300})[\]\)]',
                r'(?:allowedOrigins|corsOrigins)\s*[=:]\s*["\'](\*)["\']',  # wildcard CORS
                r'(?:contentSecurityPolicy|csp|CSP)\s*[=:]\s*["\']([^"\']{10,300})["\']',
            ],
        },
    ],

    # ── Angular / Framework Specific ──────────────────────────────────────────
    "angular": [
        {
            "name":     "Angular Route Definition",
            "severity": "INFO",
            "patterns": [
                r'path\s*:\s*["\']([^"\']{1,150})["\']',
                r'loadChildren\s*:\s*["\']([^"\']{1,250})["\']',
                r'loadComponent\s*:\s*\(\s*\)\s*=>\s*import\s*\(["\']([^"\']+)["\']',
                r'redirectTo\s*:\s*["\']([^"\']{1,150})["\']',
                r'canActivate\s*:\s*\[([^\]]{3,200})\]',
                r'canLoad\s*:\s*\[([^\]]{3,200})\]',
            ],
        },
        {
            "name":     "Angular Environment Variable",
            "severity": "MEDIUM",
            "patterns": [
                r'environment\.([a-zA-Z0-9_]+)\s*[=:]\s*["\`]([^"\'`\n]{3,250})["\`]',
                r'environment\.([a-zA-Z0-9_]+)\s*[=:]\s*(true|false)',
                r'environment\.([a-zA-Z0-9_]+)\s*[=:]\s*(\{[^}]{5,300}\})',
            ],
        },
        {
            "name":     "Angular HTTP Interceptor / Auth Header",
            "severity": "MEDIUM",
            "patterns": [
                r'["\']Authorization["\'][^:,]{0,20}["\']([^"\']{5,300})["\']',
                r'setHeader\s*\(\s*["\'][^"\']+["\']\s*,\s*["\']([^"\']{3,300})["\']',
                r'headers\s*[=:]\s*new\s+HttpHeaders\s*\((\{[^}]{5,400}\})\)',
            ],
        },
        {
            "name":     "Angular Injectable Service URL",
            "severity": "INFO",
            "patterns": [
                r'private\s+(?:readonly\s+)?(?:url|endpoint|apiUrl|baseUrl|serviceUrl)\s*[=:]\s*["\`]([^"\'`\n]{3,250})["\`]',
                r'@Injectable\s*\(\s*\{([^}]{3,200})\}\s*\)',
            ],
        },
        {
            "name":     "React Router / Next.js Route",
            "severity": "INFO",
            "patterns": [
                r'<Route\s+(?:exact\s+)?path=["\']([^"\']{1,150})["\']',
                r'router\.(?:get|post|put|delete|patch|use)\s*\(\s*["\']([^"\']{1,150})["\']',
                r'useNavigate|useHistory|history\.push\s*\(\s*["\`]([^"\'`\n]{2,150})["\`]',
                r'next\/router.*?pathname\s*[=:=]\s*["\']([^"\']{1,100})["\']',
            ],
        },
    ],

    # ── Debug / Dev Leaks ────────────────────────────────────────────────────
    "debug": [
        {
            "name":     "Console Log Sensitive Data",
            "severity": "LOW",
            "patterns": [
                r'console\.(?:log|warn|error|debug|info)\s*\([^)]{0,30}(?:password|token|secret|key|auth|credential|jwt)[^)]{0,100}\)',
                r'console\.log\s*\(\s*(?:JSON\.stringify\s*\()?(?:this\.|_)?(?:user|auth|session|state)\s*[,)]',
            ],
        },
        {
            "name":     "Debug / Dev Flag Enabled",
            "severity": "MEDIUM",
            "patterns": [
                r'(?:debug|debugMode|DEV_MODE|ENABLE_DEBUG|showDebug|verboseLogging)\s*[=:]\s*true',
                r'(?:disableAuth|skipAuth|bypassAuth|noAuth|AUTH_DISABLED)\s*[=:]\s*true',
                r'(?:disableSecurity|skipSecurity|DISABLE_SECURITY)\s*[=:]\s*true',
            ],
        },
        {
            "name":     "Admin / Hidden Panel Path",
            "severity": "HIGH",
            "patterns": [
                r'["\`](/(?:admin|administrator|manage|management|superadmin|super-admin|'
                r'control-panel|controlpanel|backstage|internal|staff|ops|devops|debug|'
                r'swagger|api-docs|redoc|graphiql)[/a-zA-Z0-9_\-]*)["\`]',
            ],
        },
        {
            "name":     "TODO / FIXME Security Note",
            "severity": "MEDIUM",
            "patterns": [
                r'(?:TODO|FIXME|HACK|XXX|SECURITY|INSECURE|VULNERABLE|REMOVE BEFORE|'
                r'DO NOT COMMIT|temp password|hardcoded|TEMP|not secure)\s*[:\-]?\s*([^\n]{5,150})',
            ],
        },
        {
            "name":     "Sourcemap Reference",
            "severity": "LOW",
            "patterns": [
                r'//[#@]\s*sourceMappingURL=([^\s]+)',
            ],
        },
    ],

    # ── Sensitive Keywords Sweep ──────────────────────────────────────────────
    "sensitive": [
        {
            "name":     "Encryption / Master Key",
            "severity": "CRITICAL",
            "patterns": [
                r'(?:encryptionKey|encryption_key|ENCRYPTION_KEY|masterKey|master_key|'
                r'aesKey|aes_key|iv[_\-]?key|hmac[_\-]?secret|HMAC_SECRET)\s*[=:]\s*["\']([^"\']{6,})["\']',
            ],
        },
        {
            "name":     "Hardcoded Admin / Backdoor",
            "severity": "CRITICAL",
            "patterns": [
                r'(?:adminPassword|admin_password|rootPassword|root_password|'
                r'superadminPass|backdoor|bypass[_\-]?key|masterPass)\s*[=:]\s*["\']([^"\']{3,})["\']',
            ],
        },
        {
            "name":     "Version / Build Info Leak",
            "severity": "INFO",
            "patterns": [
                r'(?:appVersion|APP_VERSION|buildVersion|BUILD_VERSION|version)\s*[=:]\s*["\']([0-9][^"\']{1,30})["\']',
                r'(?:gitHash|GIT_HASH|commitHash|COMMIT_HASH|BUILD_ID)\s*[=:]\s*["\']([a-f0-9]{6,})["\']',
            ],
        },
    ],
}


class Analyzer:
    def __init__(self, verbose=False, min_severity="INFO"):
        self.verbose      = verbose
        self.min_severity = min_severity
        self.findings: list[Finding] = []
        self.seen:     set           = set()
        self.file_stats              = defaultdict(lambda: defaultdict(int))
        self._sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

    def _sev_ok(self, sev: str) -> bool:
        return self._sev_order.index(sev) <= self._sev_order.index(self.min_severity)

    def _dedup(self, cat: str, val: str) -> str:
        return hashlib.md5(f"{cat}:{val[:80]}".encode()).hexdigest()

    def analyze_content(self, content: str, fname: str) -> int:
        lines = content.splitlines()
        count = 0

        for category, rule_list in RULES.items():
            for rule in rule_list:
                name      = rule["name"]
                severity  = rule["severity"]
                patterns  = rule["patterns"]
                blacklist = rule.get("blacklist", [])

                if not self._sev_ok(severity):
                    continue

                for pattern in patterns:
                    try:
                        for m in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                            value = (m.group(1) if m.lastindex and m.lastindex >= 1
                                     else m.group(0)).strip()
                            if not value or len(value) < 3:
                                continue
                            if any(re.search(bl, value, re.IGNORECASE) for bl in blacklist):
                                continue

                            dk = self._dedup(name, value)
                            if dk in self.seen:
                                continue
                            self.seen.add(dk)

                            line_no  = content[:m.start()].count("\n") + 1
                            ctx_s    = max(0, line_no - 2)
                            ctx_e    = min(len(lines), line_no + 1)
                            context  = " | ".join(l.strip()[:120] for l in lines[ctx_s:ctx_e])

                            f = Finding(
                                category    = category,
                                subcategory = name,
                                value       = value[:600],
                                severity    = severity,
                                file        = fname,
                                line        = line_no,
                                context     = context[:350],
                            )
                            self.findings.append(f)
                            self.file_stats[fname][category] += 1
                            count += 1
                    except re.error:
                        continue

        return count

    def analyze_file(self, filepath: Path) -> int:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            error(f"Cannot read {filepath}: {e}")
            return 0
        n = self.analyze_content(content, filepath.name)
        if self.verbose and n > 0:
            success(f"  {filepath.name}: {n} findings")
        return n

    def analyze_dir(self, dir_path: Path, extensions=(".js", ".ts", ".jsx", ".tsx", ".mjs")) -> list:
        files = [f for f in dir_path.rglob("*") if f.suffix in extensions and f.is_file()]
        info(f"Scanning {len(files)} files ...")
        for f in files:
            self.analyze_file(f)
        return self.findings


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — SOURCE MAP EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

def extract_source_maps(dir_path: Path, output_dir: Path) -> Path | None:
    """Extract embedded sourcesContent from .map files and reconstruct source tree."""
    map_files = list(dir_path.rglob("*.map")) + list(dir_path.rglob("*.js.map"))
    if not map_files:
        warn("No .map files found for source extraction.")
        return None

    src_dir = output_dir / "extracted_sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    total    = 0
    no_embed = 0

    for mf in map_files:
        try:
            raw  = json.loads(mf.read_text(encoding="utf-8", errors="ignore"))
            srcs = raw.get("sources", [])
            cont = raw.get("sourcesContent", [])

            for i, src_path in enumerate(srcs):
                if not src_path:
                    continue
                content = cont[i] if i < len(cont) else None
                if not content:
                    no_embed += 1
                    continue

                # Sanitize path
                safe = src_path
                safe = re.sub(r'^(webpack:///|webpack://|ng://|/\.\.)', '', safe)
                safe = re.sub(r'\.\.\/', '_UP_/', safe)
                safe = re.sub(r'[<>:"|?*]', '_', safe)
                safe = safe.lstrip("/\\")
                if not safe:
                    safe = f"source_{i}"

                dest = src_dir / safe
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                total += 1

        except Exception as e:
            warn(f"Map parse error {mf.name}: {e}")

    success(f"Extracted {total} source files → {src_dir}")
    if no_embed:
        dim(f"{no_embed} source entries had no embedded content (external refs)")
    return src_dir


def extract_all_strings(dir_path: Path, output_dir: Path):
    """Dump all discovered URLs and paths across all JS files."""
    urls  = []
    paths = []
    emails = []

    url_re   = re.compile(r'https?://[^\s"\'`<>\)]{8,250}')
    path_re  = re.compile(r'["\`](/[a-zA-Z0-9_/\-]{3,100})["\`]')
    email_re = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

    for f in dir_path.rglob("*.js"):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            fname   = f.name
            for m in url_re.finditer(content):
                urls.append({"value": m.group(), "file": fname})
            for m in path_re.finditer(content):
                paths.append({"value": m.group(1), "file": fname})
            for m in email_re.finditer(content):
                emails.append({"value": m.group(), "file": fname})
        except Exception:
            pass

    # Deduplicate
    urls   = list({v["value"]: v for v in urls}.values())
    paths  = list({v["value"]: v for v in paths}.values())
    emails = list({v["value"]: v for v in emails}.values())

    out = output_dir / "all_strings.json"
    out.write_text(json.dumps({"urls": urls, "paths": paths, "emails": emails}, indent=2))
    success(f"Strings dump: {len(urls)} URLs · {len(paths)} paths · {len(emails)} emails → {out}")


# ══════════════════════════════════════════════════════════════════════════════
#  REPORTING
# ══════════════════════════════════════════════════════════════════════════════

SEV_ICON = {"CRITICAL": "💀", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def print_report(findings: list[Finding]):
    if not findings:
        warn("No findings.")
        return

    by_sev = defaultdict(list)
    for f in findings:
        by_sev[f.severity].append(f)

    for sev in SEV_ORDER:
        group = by_sev.get(sev, [])
        if not group:
            continue
        icon  = SEV_ICON[sev]
        color = Finding(sev, "", "", sev, "", 0).sev_color()
        section(f"{icon}  {color}{sev}{C.RESET}  [{len(group)} findings]")

        by_cat = defaultdict(list)
        for f in group:
            by_cat[f.subcategory].append(f)

        for subcat, items in sorted(by_cat.items()):
            print(f"\n  {C.BOLD}{C.WHITE}{subcat}{C.RESET}  ({len(items)})")
            for item in items[:60]:
                val = item.value[:130].replace("\n", " ")
                print(f"  {C.GRAY}{item.file}:{item.line}{C.RESET}  →  {color}{val}{C.RESET}")
                if item.context:
                    print(f"  {C.DIM}  {item.context[:110]}{C.RESET}")

    # Summary bar
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  FINDINGS SUMMARY{C.RESET}")
    print(f"{'─'*65}")
    for sev in SEV_ORDER:
        n = len(by_sev.get(sev, []))
        if not n:
            continue
        color = Finding(sev, "", "", sev, "", 0).sev_color()
        bar   = "█" * min(n, 45)
        print(f"  {color}{sev:<12}{C.RESET}  {n:>4}  {C.GRAY}{bar}{C.RESET}")
    print(f"{'─'*65}")
    print(f"  {'Total':<12}  {len(findings):>4}")
    print(f"{'═'*65}\n")


def save_report(findings: list[Finding], out_path: Path, fmt="json"):
    if fmt == "json":
        out_path.write_text(json.dumps([asdict(f) for f in findings], indent=2))

    elif fmt == "csv":
        import csv
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            fields = ["severity", "category", "subcategory", "value", "file", "line", "context", "confidence"]
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for f in findings:
                w.writerow(asdict(f))

    elif fmt == "md":
        ts  = datetime.now().isoformat()
        md  = [
            "# jsmap-suite Report  —  by baba01hacker",
            f"**Generated:** {ts}  ",
            f"**Total Findings:** {len(findings)}",
            "",
        ]
        by_sev = defaultdict(list)
        for f in findings:
            by_sev[f.severity].append(f)
        for sev in SEV_ORDER:
            group = by_sev.get(sev, [])
            if not group:
                continue
            md.append(f"## {SEV_ICON[sev]} {sev} ({len(group)})")
            md.append("")
            by_cat = defaultdict(list)
            for f in group:
                by_cat[f.subcategory].append(f)
            for cat, items in by_cat.items():
                md.append(f"### {cat}")
                md.append("| File | Line | Value |")
                md.append("|------|------|-------|")
                for item in items[:200]:
                    v = item.value[:150].replace("|", "\\|").replace("\n", " ")
                    md.append(f"| `{item.file}` | {item.line} | `{v}` |")
                md.append("")
        out_path.write_text("\n".join(md), encoding="utf-8")

    elif fmt == "txt":
        lines = [f"jsmap-suite  —  by baba01hacker", f"Generated: {datetime.now()}", ""]
        for f in findings:
            lines += [
                f"[{f.severity}] {f.subcategory}",
                f"  File     : {f.file}:{f.line}",
                f"  Value    : {f.value[:250]}",
                f"  Context  : {f.context[:180]}",
                "",
            ]
        out_path.write_text("\n".join(lines), encoding="utf-8")

    elif fmt == "html":
        _save_html_report(findings, out_path)

    success(f"Report saved → {out_path}")


def _save_html_report(findings: list[Finding], out_path: Path):
    """Generate a self-contained HTML report."""
    sev_colors = {
        "CRITICAL": "#ff3b30", "HIGH": "#ff6b35",
        "MEDIUM":   "#ffcc00", "LOW":  "#5ac8fa", "INFO": "#8e8e93",
    }
    rows = ""
    for f in findings:
        col = sev_colors.get(f.severity, "#888")
        v   = f.value[:200].replace("<","&lt;").replace(">","&gt;").replace("\n"," ")
        ctx = f.context[:120].replace("<","&lt;").replace(">","&gt;")
        rows += (
            f'<tr>'
            f'<td><span class="badge" style="background:{col}">{f.severity}</span></td>'
            f'<td>{f.subcategory}</td>'
            f'<td><code>{f.file}:{f.line}</code></td>'
            f'<td><code class="val">{v}</code></td>'
            f'<td class="ctx">{ctx}</td>'
            f'</tr>\n'
        )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>jsmap-suite Report — baba01hacker</title>
<style>
  body{{font-family:monospace;background:#0d0d0d;color:#e0e0e0;padding:20px}}
  h1{{color:#0ff;border-bottom:1px solid #333;padding-bottom:8px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{background:#1a1a1a;color:#aaa;padding:8px;text-align:left;border-bottom:1px solid #333}}
  td{{padding:6px 8px;border-bottom:1px solid #1e1e1e;vertical-align:top}}
  tr:hover{{background:#111}}
  .badge{{padding:2px 7px;border-radius:3px;color:#000;font-weight:bold;font-size:11px}}
  code{{color:#0f0;word-break:break-all}}
  .val{{color:#ff9f0a}}
  .ctx{{color:#666;font-size:11px}}
  .meta{{color:#666;margin-bottom:20px;font-size:12px}}
</style>
</head><body>
<h1>⚡ jsmap-suite — by baba01hacker</h1>
<p class="meta">Generated: {datetime.now().isoformat()} &nbsp;|&nbsp; Total findings: {len(findings)}</p>
<table>
<tr><th>Severity</th><th>Type</th><th>Location</th><th>Value</th><th>Context</th></tr>
{rows}
</table></body></html>"""
    out_path.write_text(html, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN CLI
# ══════════════════════════════════════════════════════════════════════════════

def build_session(args) -> requests.Session:
    session = requests.Session()
    headers = {**DEFAULT_HEADERS}
    if hasattr(args, "url") and args.url:
        headers["Referer"] = args.url
    session.headers.update(headers)

    if getattr(args, "proxy", None):
        session.proxies = {"http": args.proxy, "https": args.proxy}
        info(f"Proxy: {args.proxy}")

    if getattr(args, "no_verify", False):
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        warn("SSL verification disabled")

    if getattr(args, "cookie", None):
        session.headers.update({"Cookie": args.cookie})
        info("Custom cookie set")

    if getattr(args, "header", None):
        for hdr in args.header:
            k, _, v = hdr.partition(":")
            session.headers.update({k.strip(): v.strip()})
            dim(f"Header: {k.strip()}")

    return session


def main():
    parser = argparse.ArgumentParser(
        description="jsmap-suite — Angular/Webpack/React/Vue Full Recon  |  by baba01hacker",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Full auto recon (download + analyze + extract):
    python3 jsmap_suite.py https://app.target.com/

  Download only:
    python3 jsmap_suite.py https://app.target.com/ --download-only

  Analyze existing directory:
    python3 jsmap_suite.py --analyze-only --dir chunks_target.com/

  HTML report + extract sources + dump all strings:
    python3 jsmap_suite.py https://app.target.com/ --format html --extract-sources --strings

  Load manual chunk map + Burp proxy:
    python3 jsmap_suite.py https://app.target.com/ -m chunks.json --proxy http://127.0.0.1:8080

  High severity only, verbose, markdown:
    python3 jsmap_suite.py https://app.target.com/ --severity HIGH -v --format md

  With custom cookie + extra headers:
    python3 jsmap_suite.py https://app.target.com/ --cookie "session=abc123" -H "X-API-Key: xyz"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
    )

    # Target
    parser.add_argument("url",            help="Target base URL (e.g. https://app.target.com/)", nargs="?", default=None)

    # Mode
    mode = parser.add_argument_group("Mode")
    mode.add_argument("--download-only",   help="Phase 1 only: download chunks, skip analysis",  action="store_true", dest="download_only")
    mode.add_argument("--analyze-only",    help="Phase 2 only: analyze existing dir, skip download", action="store_true", dest="analyze_only")
    mode.add_argument("--dir",             help="Directory to analyze (required with --analyze-only)", default=None)

    # Download options
    dl = parser.add_argument_group("Download")
    dl.add_argument("-m", "--map",         help="JSON file with chunk_map {id: hash}", default=None)
    dl.add_argument("-t", "--threads",     help="Concurrent download threads (default: 5)", type=int, default=5)
    dl.add_argument("-d", "--delay",       help="Delay between requests in seconds (default: 0)", type=float, default=0.0)

    # Analysis options
    an = parser.add_argument_group("Analysis")
    an.add_argument("--severity",          help="Min severity: CRITICAL|HIGH|MEDIUM|LOW|INFO (default: INFO)",
                    default="INFO", choices=["CRITICAL","HIGH","MEDIUM","LOW","INFO"])
    an.add_argument("--extract-sources",   help="Extract embedded sources from .map files",
                    action="store_true", dest="extract_sources")
    an.add_argument("--strings",           help="Dump all URLs/paths/emails for manual review",
                    action="store_true")
    an.add_argument("--no-print",          help="Skip terminal output, just save report",
                    action="store_true", dest="no_print")

    # Output
    out = parser.add_argument_group("Output")
    out.add_argument("-o", "--output",     help="Output directory base name (default: auto)", default=None)
    out.add_argument("--format",           help="Report format: json|csv|md|txt|html (default: json)",
                    default="json", choices=["json","csv","md","txt","html"])

    # Network
    net = parser.add_argument_group("Network")
    net.add_argument("--proxy",            help="HTTP proxy (e.g. http://127.0.0.1:8080)", default=None)
    net.add_argument("--no-verify",        help="Disable SSL certificate verification",
                    action="store_true", dest="no_verify")
    net.add_argument("--cookie",           help='Custom cookie string (e.g. "session=abc; csrf=xyz")', default=None)
    net.add_argument("-H", "--header",     help="Extra HTTP header (repeatable): \"Name: Value\"",
                    action="append", dest="header", default=[])

    # Misc
    parser.add_argument("-v", "--verbose", help="Verbose output", action="store_true")

    args = parser.parse_args()
    banner()

    # Validate
    if not args.url and not args.analyze_only:
        parser.print_help()
        sys.exit(1)
    if args.analyze_only and not args.dir:
        error("--analyze-only requires --dir <path>")
        sys.exit(1)

    # Output dir
    if args.output:
        out_dir = Path(args.output)
    elif args.url:
        host    = urlparse(args.url).netloc.replace(":", "_")
        out_dir = Path(f"jsmap_{host}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    else:
        out_dir = Path(f"jsmap_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    out_dir.mkdir(parents=True, exist_ok=True)
    info(f"Output: {out_dir.resolve()}")

    session = build_session(args)

    # ── PHASE 1: DOWNLOAD ────────────────────────────────────────────────────
    if not args.analyze_only:
        step(1, "DOWNLOADING CHUNKS")
        chunks_dir = run_downloader(args, session, out_dir)
    else:
        chunks_dir = Path(args.dir)
        if not chunks_dir.exists():
            error(f"Directory not found: {chunks_dir}")
            sys.exit(1)

    if args.download_only:
        success("Download complete. Exiting (--download-only)")
        sys.exit(0)

    # ── PHASE 2: ANALYZE ────────────────────────────────────────────────────
    step(2, "ANALYZING JS CHUNKS")
    analyzer = Analyzer(verbose=args.verbose, min_severity=args.severity)
    analyzer.analyze_dir(chunks_dir)
    findings = analyzer.findings

    if not args.no_print:
        print_report(findings)

    # Save report
    ext_map  = {"json":".json","csv":".csv","md":".md","txt":".txt","html":".html"}
    rep_file = out_dir / f"findings{ext_map[args.format]}"
    save_report(findings, rep_file, fmt=args.format)

    # ── PHASE 3: EXTRACT ────────────────────────────────────────────────────
    if args.extract_sources:
        step(3, "EXTRACTING SOURCE MAP FILES")
        extracted = extract_source_maps(chunks_dir, out_dir)
        # Re-analyze extracted TypeScript/JS sources
        if extracted and extracted.exists():
            info("Re-analyzing extracted sources ...")
            analyzer.analyze_dir(extracted, extensions=(".ts", ".js", ".tsx", ".jsx"))
            new_findings = [f for f in analyzer.findings if f not in findings]
            if new_findings:
                success(f"{len(new_findings)} additional findings in extracted sources")
                findings = analyzer.findings
                save_report(findings, rep_file, fmt=args.format)

    if args.strings:
        extract_all_strings(chunks_dir, out_dir)

    # ── FINAL SUMMARY ────────────────────────────────────────────────────────
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  COMPLETE{C.RESET}")
    print(f"{'─'*65}")

    crits = sum(1 for f in findings if f.severity == "CRITICAL")
    highs = sum(1 for f in findings if f.severity == "HIGH")

    if crits:
        critical(f"{crits} CRITICAL findings — review immediately!")
    if highs:
        warn(f"{highs} HIGH severity findings")

    print(f"  Total findings : {len(findings)}")
    print(f"  Report         : {rep_file.resolve()}")
    print(f"  Output dir     : {out_dir.resolve()}")
    print(f"{'═'*65}\n")


if __name__ == "__main__":
    main()

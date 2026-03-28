#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║        jsmap-suite  ——  Enhanced Modular Version                             ║
║                                                                              ║
║   • Downloader:    Robust Webpack chunk fetcher                              ║
║   • Extractor:     Pluggable analysis engines                                ║
║   • Reconstructor: Source map recovery + ng build                           ║
║   • Output:        Structured directory layout                               ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import re
import sys
import json
import time
import shutil
import hashlib
import argparse
import requests
import urllib3
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Callable, Any, Tuple
from abc import ABC, abstractmethod

# ══════════════════════════════════════════════════════════════════════════════
#  COLORS & LOGGING
# ══════════════════════════════════════════════════════════════════════════════


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    BG_RED = "\033[41m"
    BG_YLW = "\033[43m"
    BG_GRN = "\033[42m"
    BG_CYN = "\033[46m"
    BG_BLU = "\033[44m"


def banner():
    print(f"""\
{C.MAGENTA}{C.BOLD}
     ██╗███████╗███╗   ███╗ █████╗ ██████╗       ███████╗██╗   ██╗██╗████████╗███████╗
     ██║██╔════╝████╗ ████║██╔══██╗██╔══██╗      ██╔════╝██║   ██║██║╚══██╔══╝██╔════╝
     ██║███████╗██╔████╔██║███████║██████╔╝      ███████╗██║   ██║██║   ██║   █████╗
██   ██║╚════██║██║╚██╔╝██║██╔══██║██╔═══╝       ╚════██║██║   ██║██║   ██║   ██╔══╝
╚█████╔╝███████║██║ ╚═╝ ██║██║  ██║██║           ███████║╚██████╔╝██║   ██║   ███████╗
 ╚════╝ ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝           ╚══════╝ ╚═════╝ ╚═╝   ╚═╝   ╚══════╝
{C.RESET}{C.YELLOW}  Enhanced Modular Suite  ·  Structured Output  ·  ng build Integration{C.RESET}
{C.GRAY}  Phase 1: Download  |  Phase 2: Extract  |  Phase 3: Reconstruct  |  Phase 4: Build{C.RESET}
""")


def _log(prefix, color, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{C.GRAY}[{ts}]{C.RESET} {color}{prefix}{C.RESET} {msg}")


def info(m):
    _log("[*]", C.CYAN, m)


def success(m):
    _log("[+]", C.GREEN, m)


def warn(m):
    _log("[!]", C.YELLOW, m)


def error(m):
    _log("[-]", C.RED, m)


def critical(m):
    print(f"{C.BG_RED}{C.WHITE}[!!]{C.RESET} {C.RED}{C.BOLD}{m}{C.RESET}")


def section(m):
    print(f"\n{C.BOLD}{C.BLUE}{'─' * 68}\n  {m}\n{'─' * 68}{C.RESET}")


def dim(m):
    print(f"{C.GRAY}    {m}{C.RESET}")


def step(n, m):
    print(f"\n{C.BG_CYN}{C.WHITE} PHASE {n} {C.RESET} {C.BOLD}{m}{C.RESET}\n")


def substep(m):
    print(f"  {C.BG_BLU}{C.WHITE} ► {C.RESET} {C.BOLD}{m}{C.RESET}")


# ══════════════════════════════════════════════════════════════════════════════
#  OUTPUT DIRECTORY STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════


class OutputLayout:
    """
    Structured output directory:

    <root>/
    ├── chunks/                 Raw downloaded JS chunks
    ├── maps/                   Source map files (.map)
    ├── extracted_sources/      Reconstructed source tree
    │   └── src/                (Angular/React source hierarchy)
    ├── ng_project/             Scaffolded Angular project (for ng build)
    │   ├── src/                ← symlinked / copied extracted sources
    │   └── dist/               ← ng build --configuration production output
    ├── reports/
    │   ├── findings.json
    │   ├── findings.html
    │   ├── findings.md
    │   └── all_strings.json
    ├── logs/
    │   ├── download.log
    │   └── build.log
    └── summary.json            Top-level scan summary
    """

    def __init__(self, root: Path):
        self.root = root
        self.chunks_dir = root / "chunks"
        self.maps_dir = root / "maps"
        self.sources_dir = root / "extracted_sources"
        self.ng_project_dir = root / "ng_project"
        self.ng_src_dir = root / "ng_project" / "src"
        self.ng_dist_dir = root / "ng_project" / "dist"
        self.reports_dir = root / "reports"
        self.logs_dir = root / "logs"
        self.summary_file = root / "summary.json"

    def create_all(self):
        for d in [
            self.chunks_dir,
            self.maps_dir,
            self.sources_dir,
            self.ng_project_dir,
            self.ng_src_dir,
            self.ng_dist_dir,
            self.reports_dir,
            self.logs_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
        info(f"Output root: {C.BOLD}{self.root.resolve()}{C.RESET}")
        self._print_tree()

    def _print_tree(self):
        tree = [
            f"  {C.BOLD}{self.root.name}/{C.RESET}",
            f"  {C.GRAY}├── chunks/              ← raw webpack chunks{C.RESET}",
            f"  {C.GRAY}├── maps/                ← .map files{C.RESET}",
            f"  {C.GRAY}├── extracted_sources/   ← reconstructed source tree{C.RESET}",
            f"  {C.GRAY}├── ng_project/          ← Angular project scaffold{C.RESET}",
            f"  {C.GRAY}│   ├── src/             ← sources copied here{C.RESET}",
            f"  {C.GRAY}│   └── dist/            ← ng build output{C.RESET}",
            f"  {C.GRAY}├── reports/             ← findings & strings{C.RESET}",
            f"  {C.GRAY}└── logs/                ← download & build logs{C.RESET}",
        ]
        print("\n".join(tree) + "\n")

    def log_path(self, name: str) -> Path:
        return self.logs_dir / f"{name}.log"

    def report_path(self, fmt: str) -> Path:
        ext_map = {
            "json": ".json",
            "csv": ".csv",
            "md": ".md",
            "txt": ".txt",
            "html": ".html",
        }
        return self.reports_dir / f"findings{ext_map.get(fmt, '.json')}"


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — DOWNLOADER MODULE
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


class ChunkDownloader:
    """Robust Webpack chunk downloader with structured output support."""

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        layout: OutputLayout,
        threads: int = 5,
        delay: float = 0.0,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/") + "/"
        self.layout = layout
        self.threads = threads
        self.delay = delay
        self.stats = {"ok": 0, "skipped": 0, "failed": 0}
        self._dl_log: List[Dict[str, Any]] = []

    # ── chunk map extraction ──────────────────────────────────────────────────

    def extract_chunk_map_from_runtime(self, content: str) -> dict:
        chunk_map = {}
        patterns = [
            (
                r'\{(\s*(?:"?\d+"?\s*:\s*"[a-f0-9]+"(?:\s*,\s*)?)+)\}',
                lambda m: re.findall(r'"?(\d+)"?\s*:\s*"([a-f0-9]{8,})"', m),
            ),
            (
                r'\[\s*(\d+)\s*,\s*"([a-f0-9]{8,})"',
                lambda m: [(m.group(1), m.group(2))],
            ),
            (r'(\d+):"([a-f0-9]{8,})"', lambda m: [(m.group(1), m.group(2))]),
            (
                r'case\s+(\d+)\s*:\s*return\s*["\']([a-f0-9]{8,})["\']',
                lambda m: [(m.group(1), m.group(2))],
            ),
        ]
        for pattern, extractor in patterns:
            for match in re.finditer(pattern, content):
                try:
                    for chunk_id, chunk_hash in extractor(match):
                        chunk_map[chunk_id] = chunk_hash
                except Exception:
                    continue
        return chunk_map

    def extract_named_chunks(self, content: str) -> dict:
        special = {}
        patterns = [
            r'(\d+)\s*===\s*\w+\s*\?\s*"([a-zA-Z0-9_\-]+)"',
            r'"?(\d+)"?\s*:\s*"([a-zA-Z][a-zA-Z0-9_\-]+)"',
        ]
        for pat in patterns:
            for cid, cname in re.findall(pat, content):
                if not re.match(r"^[a-f0-9]{8,}$", cname):
                    special[cid] = cname
        return special

    def resolve_chunk_filename(
        self,
        chunk_id: str,
        chunk_hash: str,
        special_names: Optional[dict] = None,
    ) -> str:
        prefix = (special_names or {}).get(chunk_id, chunk_id)
        return f"{prefix}.{chunk_hash}.js"

    # ── network helpers ───────────────────────────────────────────────────────

    def try_alternate_paths(
        self, filename: str
    ) -> Optional[requests.Response]:
        alt_prefixes = [
            "assets/",
            "static/js/",
            "js/",
            "dist/",
            "build/",
            "public/",
            "",
        ]
        for prefix in alt_prefixes:
            try:
                alt_url = urljoin(self.base_url, prefix + filename)
                r = self.session.get(alt_url, timeout=8)
                if r.status_code == 200:
                    info(f"  Alternate path hit: {prefix}{filename}")
                    return r
            except Exception:
                pass
        return None

    def download_chunk(
        self,
        chunk_id: str,
        chunk_hash: str,
        save_dir: Path,
        special_names: Optional[dict] = None,
    ) -> dict:
        filename = self.resolve_chunk_filename(
            chunk_id, chunk_hash, special_names
        )
        url = urljoin(self.base_url, filename)
        save_path = save_dir / filename

        if save_path.exists():
            return {
                "status": "skipped",
                "filename": filename,
                "chunk_id": chunk_id,
            }

        if self.delay > 0:
            time.sleep(self.delay)

        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                save_path.write_bytes(resp.content)
                sz = len(resp.content)
                success(f"  {filename}  ({sz:,} bytes)")
                self._dl_log.append(
                    {"file": filename, "url": url, "bytes": sz, "status": "ok"}
                )
                return {"status": "ok", "filename": filename, "size": sz}
            elif resp.status_code == 404:
                alt = self.try_alternate_paths(filename)
                if alt:
                    save_path.write_bytes(alt.content)
                    sz = len(alt.content)
                    self._dl_log.append(
                        {
                            "file": filename,
                            "url": url,
                            "bytes": sz,
                            "status": "alt",
                        }
                    )
                    return {
                        "status": "ok",
                        "filename": filename,
                        "size": sz,
                        "note": "alternate_path",
                    }
                error(f"  404: {filename}")
                self._dl_log.append(
                    {"file": filename, "url": url, "status": "404"}
                )
                return {"status": "404", "filename": filename}
            else:
                self._dl_log.append(
                    {
                        "file": filename,
                        "url": url,
                        "status": f"http_{resp.status_code}",
                    }
                )
                return {
                    "status": f"http_{resp.status_code}",
                    "filename": filename,
                }
        except requests.exceptions.ConnectionError:
            return {"status": "conn_error", "filename": filename}
        except requests.exceptions.Timeout:
            return {"status": "timeout", "filename": filename}
        except Exception as e:
            return {"status": "error", "filename": filename, "error": str(e)}

    # ── auto-detect ───────────────────────────────────────────────────────────

    def auto_detect_chunks(self) -> Tuple[dict, dict, list]:
        chunk_map, special_names, all_scripts = {}, {}, []

        info("Auto-detect: fetching index.html ...")
        try:
            resp = self.session.get(self.base_url, timeout=15)
            html = resp.text

            raw_srcs = re.findall(
                r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', html
            )
            raw_srcs += re.findall(r'"([^"]*\.js)"', html)

            for src in raw_srcs:
                try:
                    full = urljoin(self.base_url, src.split("?")[0])
                    if full not in all_scripts:
                        all_scripts.append(full)
                except Exception:
                    pass

            runtime_url = next(
                (
                    u
                    for u in all_scripts
                    if re.search(r"runtime", u, re.IGNORECASE)
                ),
                None,
            )
            if not runtime_url:
                for g in [
                    "runtime.js",
                    "runtime.min.js",
                    "webpack-runtime.js",
                ]:
                    test = urljoin(self.base_url, g)
                    try:
                        r = self.session.get(test, timeout=5)
                        if r.status_code == 200 and "webpackChunk" in r.text:
                            runtime_url = test
                            break
                    except Exception:
                        pass

            if runtime_url:
                info(f"Runtime: {runtime_url}")
                r = self.session.get(runtime_url, timeout=15)
                if r.status_code == 200:
                    chunk_map = self.extract_chunk_map_from_runtime(r.text)
                    special_names = self.extract_named_chunks(r.text)
                    if chunk_map:
                        success(
                            f"Extracted {len(chunk_map)} chunks from runtime.js"
                        )

        except Exception as e:
            warn(f"Auto-detect failed: {e}")

        return chunk_map, special_names, all_scripts

    # ── main download entry ───────────────────────────────────────────────────

    def download_all(
        self,
        chunk_map: Optional[dict] = None,
        special_names: Optional[dict] = None,
        extra_scripts: Optional[list] = None,
    ) -> Path:
        """Download all chunks and maps into layout.chunks_dir."""
        save_dir = self.layout.chunks_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        results = []

        if chunk_map:
            substep(
                f"Downloading {len(chunk_map)} chunks  [threads={self.threads}]"
            )
            with ThreadPoolExecutor(max_workers=self.threads) as ex:
                futures = {
                    ex.submit(
                        self.download_chunk,
                        cid,
                        chash,
                        save_dir,
                        special_names,
                    ): cid
                    for cid, chash in chunk_map.items()
                }
                for fut in as_completed(futures):
                    results.append(fut.result())

        if extra_scripts:
            substep(
                f"Downloading {len(extra_scripts)} detected script references"
            )
            for url in extra_scripts:
                fname = url.split("/")[-1].split("?")[0]
                if not fname.endswith(".js"):
                    fname += ".js"
                save_path = save_dir / fname
                if save_path.exists():
                    continue
                try:
                    r = self.session.get(url, timeout=15)
                    if r.status_code == 200:
                        save_path.write_bytes(r.content)
                        success(f"  {fname}")
                        results.append({"status": "ok", "filename": fname})
                except Exception as e:
                    warn(f"  Failed {fname}: {e}")

        self._fetch_sourcemaps(save_dir)

        self.stats["ok"] = sum(1 for r in results if r["status"] == "ok")
        self.stats["skipped"] = sum(
            1 for r in results if r["status"] == "skipped"
        )
        self.stats["failed"] = (
            len(results) - self.stats["ok"] - self.stats["skipped"]
        )

        # Write download log
        log_path = self.layout.log_path("download")
        log_path.write_text(
            json.dumps(self._dl_log, indent=2), encoding="utf-8"
        )
        info(f"Download log → {log_path}")

        self._print_dl_stats()
        return save_dir

    def _fetch_sourcemaps(self, chunks_dir: Path):
        """Fetch .map files referenced in JS; move them to maps_dir."""
        map_count = 0
        for js_file in chunks_dir.glob("*.js"):
            content = js_file.read_text(encoding="utf-8", errors="ignore")
            map_ref = re.search(r"//[#@]\s*sourceMappingURL=([^\s]+)", content)
            if not map_ref:
                continue
            ref_val = map_ref.group(1).strip()
            if ref_val.startswith("data:"):
                continue
            map_url = urljoin(self.base_url, ref_val)
            map_name = js_file.name + ".map"
            # Store in both chunks (for compatibility) and maps dir
            map_path_chunks = chunks_dir / map_name
            map_path_maps = self.layout.maps_dir / map_name
            if map_path_maps.exists():
                continue
            try:
                mr = self.session.get(map_url, timeout=10)
                if mr.status_code == 200:
                    map_path_chunks.write_bytes(mr.content)
                    map_path_maps.write_bytes(mr.content)
                    map_count += 1
            except Exception:
                pass
        if map_count:
            success(f"Downloaded {map_count} source map files → maps/")

    def _print_dl_stats(self):
        print(
            f"\n  {C.BOLD}Download Stats:{C.RESET}  "
            f"{C.GREEN}OK: {self.stats['ok']}{C.RESET}  "
            f"{C.GRAY}Skipped: {self.stats['skipped']}{C.RESET}  "
            f"{C.RED}Failed: {self.stats['failed']}{C.RESET}\n"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — PLUGGABLE EXTRACTOR INTERFACE
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Finding:
    category: str
    subcategory: str
    value: str
    severity: str
    file: str
    line: int
    context: str = ""
    confidence: str = "HIGH"
    tool: str = "native"

    def sev_color(self):
        return {
            "CRITICAL": C.BG_RED + C.WHITE,
            "HIGH": C.RED,
            "MEDIUM": C.YELLOW,
            "LOW": C.CYAN,
            "INFO": C.GRAY,
        }.get(self.severity, C.RESET)


class BaseExtractor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> tuple:
        pass

    @abstractmethod
    def analyze_file(self, filepath: Path) -> List[Finding]:
        pass

    def analyze_directory(self, dir_path: Path) -> List[Finding]:
        findings = []
        for ext in self.supported_extensions:
            for f in dir_path.rglob(f"*{ext}"):
                if f.is_file():
                    try:
                        findings.extend(self.analyze_file(f))
                    except Exception as e:
                        warn(f"{self.name} failed on {f.name}: {e}")
        return findings


class ExternalToolExtractor(BaseExtractor):
    def __init__(
        self,
        tool_name: str,
        command_template: List[str],
        result_parser: Callable[[str, Path], List[Finding]],
    ):
        self.tool_name = tool_name
        self.command_template = command_template
        self.result_parser = result_parser
        self._available: Optional[bool] = None

    @property
    def name(self) -> str:
        return self.tool_name

    @property
    def supported_extensions(self) -> tuple:
        return (".js", ".ts", ".jsx", ".tsx", ".mjs", ".json", ".map")

    def is_available(self) -> bool:
        if self._available is None:
            try:
                subprocess.run(
                    [self.tool_name, "--version"],
                    capture_output=True,
                    check=True,
                )
                self._available = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                self._available = False
        return bool(self._available)

    def analyze_file(self, filepath: Path) -> List[Finding]:
        if not self.is_available():
            return []
        cmd = [arg.format(file=str(filepath)) for arg in self.command_template]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            return self.result_parser(result.stdout, filepath)
        except subprocess.TimeoutExpired:
            warn(f"{self.tool_name} timeout on {filepath.name}")
            return []
        except Exception as e:
            warn(f"{self.tool_name} error on {filepath.name}: {e}")
            return []


class NativeRegexExtractor(BaseExtractor):
    """Regex-based secret/endpoint extractor."""

    RULES = {
        "endpoints": [
            {
                "name": "REST API Path",
                "severity": "INFO",
                "patterns": [
                    r'(?:fetch|axios\.(?:get|post|put|patch|delete)|http(?:Client)?\.(?:get|post|put|patch|delete))\s*\(\s*[`"\']([/][^`"\']{3,200})[`"\']',
                    r'["\'](\/(api|v\d+|rest|graphql|gql|auth|oauth|user|admin|account|service)[/a-zA-Z0-9_\-.:?=%&{}]{2,120})["\']',
                ],
                "blacklist": [
                    r"node_modules",
                    r"\.spec\.",
                    r"localhost:\d{4}(?!/api)",
                ],
            },
            {
                "name": "GraphQL Endpoint",
                "severity": "INFO",
                "patterns": [
                    r'["\`]((?:query|mutation|subscription)\s+\w+[^"\`]{10,300})["\`]',
                    r'["\']([^"\']*\/graphql[^"\']{0,60})["\']',
                ],
            },
            {
                "name": "WebSocket / SSE URL",
                "severity": "MEDIUM",
                "patterns": [
                    r'["\`](wss?://[^\s"\'`]{5,200})["\`]',
                    r'new\s+WebSocket\s*\(\s*[`"\']([^"\'`]+)[`"\']',
                ],
            },
        ],
        "secrets": [
            {
                "name": "AWS Access Key ID",
                "severity": "CRITICAL",
                "patterns": [r"(AKIA[0-9A-Z]{16})"],
            },
            {
                "name": "AWS Secret Key",
                "severity": "CRITICAL",
                "patterns": [
                    r'(?:aws[_\-]?secret|secretAccessKey)\s*[=:]\s*["\']([A-Za-z0-9/+]{40})["\']'
                ],
            },
            {
                "name": "Google API Key",
                "severity": "CRITICAL",
                "patterns": [r"(AIza[0-9A-Za-z\-_]{35})"],
            },
            {
                "name": "Firebase Config",
                "severity": "HIGH",
                "patterns": [r"firebaseConfig\s*[=:]\s*\{([^}]{50,600})\}"],
            },
            {
                "name": "Stripe Key",
                "severity": "CRITICAL",
                "patterns": [r"((?:pk|sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,})"],
            },
            {
                "name": "JWT Token",
                "severity": "CRITICAL",
                "patterns": [
                    r'["\`](ey[A-Za-z0-9\-_]{20,}\.ey[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,})["\`]'
                ],
            },
            {
                "name": "Private Key (PEM)",
                "severity": "CRITICAL",
                "patterns": [r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"],
            },
            {
                "name": "Slack Webhook",
                "severity": "HIGH",
                "patterns": [
                    r"(https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+)"
                ],
            },
            {
                "name": "GitHub Token",
                "severity": "CRITICAL",
                "patterns": [
                    r"(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})"
                ],
            },
            {
                "name": "Generic Secret",
                "severity": "HIGH",
                "patterns": [
                    r'(?:api[_\-]?key|apiKey|API_KEY|access[_\-]?token|secret|password)\s*[=:]\s*["\']([A-Za-z0-9\-_./+]{16,})["\']',
                ],
                "blacklist": [
                    r"placeholder",
                    r"your[_\-]?",
                    r"<token>",
                    r"process\.env",
                ],
            },
        ],
        "config": [
            {
                "name": "Environment Config",
                "severity": "MEDIUM",
                "patterns": [
                    r"(?:environment|config|appConfig)\s*=\s*(\{[^;]{30,1500}\})"
                ],
            },
            {
                "name": "Database Connection String",
                "severity": "CRITICAL",
                "patterns": [
                    r'["\`]((?:mongodb|postgres|mysql|redis|mssql)://[^\s"\'`]{10,250})["\`]'
                ],
            },
            {
                "name": "S3 Bucket",
                "severity": "HIGH",
                "patterns": [
                    r'["\`](s3://[a-zA-Z0-9\-._/]{5,200})["\`]',
                    r'["\`](https://[a-zA-Z0-9\-]+\.s3[^"\'`\s]{0,200})["\`]',
                ],
            },
            {
                "name": "Cloud Storage Bucket",
                "severity": "HIGH",
                "patterns": [
                    r'["\`](gs://[a-zA-Z0-9\-._/]{5,200})["\`]',
                    r'storageRef\s*\(["\']([^"\']{5,200})["\']',
                ],
            },
        ],
        "angular": [
            {
                "name": "Angular Route",
                "severity": "INFO",
                "patterns": [
                    r'path\s*:\s*["\']([^"\']{1,150})["\']',
                    r'loadChildren\s*:\s*["\']([^"\']{1,250})["\']',
                    r'loadComponent\s*:\s*\(\s*\)\s*=>\s*import\s*\(["\']([^"\']+)["\']',
                ],
            },
            {
                "name": "React Router",
                "severity": "INFO",
                "patterns": [
                    r'<Route\s+(?:exact\s+)?path=["\']([^"\']{1,150})["\']',
                    r'useNavigate.*?\(\s*["\`]([^"\'`\n]{2,150})["\`]',
                ],
            },
            {
                "name": "Angular Environment",
                "severity": "MEDIUM",
                "patterns": [
                    r"export\s+const\s+environment\s*=\s*(\{[^}]{20,800}\})",
                ],
            },
        ],
        "debug": [
            {
                "name": "Console Log Leak",
                "severity": "LOW",
                "patterns": [
                    r"console\.(?:log|warn|error)\s*\([^)]{0,30}(?:password|token|secret|key)[^)]{0,100}\)"
                ],
            },
            {
                "name": "Debug Flag",
                "severity": "MEDIUM",
                "patterns": [
                    r"(?:debug|debugMode|DEV_MODE|disableAuth|enableDevTools)\s*[=:]\s*true"
                ],
            },
            {
                "name": "Admin Panel Path",
                "severity": "HIGH",
                "patterns": [
                    r'["\`](/(?:admin|administrator|manage|superadmin|control-panel|swagger|api-docs|dashboard)[/a-zA-Z0-9_\-]*)["\`]'
                ],
            },
            {
                "name": "Source Map Comment",
                "severity": "MEDIUM",
                "patterns": [r"//[#@]\s*sourceMappingURL=([^\s]+\.map)"],
            },
        ],
    }

    @property
    def name(self) -> str:
        return "native-regex"

    @property
    def supported_extensions(self) -> tuple:
        return (".js", ".ts", ".jsx", ".tsx", ".mjs")

    def __init__(self, min_severity: str = "INFO"):
        self.min_severity = min_severity
        self.seen: set[str] = set()
        self._sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

    def _sev_ok(self, sev: str) -> bool:
        return self._sev_order.index(sev) <= self._sev_order.index(
            self.min_severity
        )

    def _dedup(self, cat: str, val: str) -> str:
        return hashlib.md5(f"{cat}:{val[:80]}".encode()).hexdigest()

    def analyze_file(self, filepath: Path) -> List[Finding]:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            error(f"Cannot read {filepath.name}: {e}")
            return []

        lines = content.splitlines()
        findings = []

        for category, rule_list in self.RULES.items():
            for rule in rule_list:
                name = str(rule["name"])
                severity = str(rule["severity"])
                patterns = rule["patterns"]
                blacklist = rule.get("blacklist", [])

                if not self._sev_ok(severity):
                    continue

                for pattern in patterns:
                    try:
                        for m in re.finditer(
                            pattern, content, re.MULTILINE | re.DOTALL
                        ):
                            value = (
                                m.group(1)
                                if m.lastindex and m.lastindex >= 1
                                else m.group(0)
                            ).strip()
                            if not value or len(value) < 3:
                                continue
                            if any(
                                re.search(bl, value, re.IGNORECASE)
                                for bl in blacklist
                            ):
                                continue
                            dk = self._dedup(name, value)
                            if dk in self.seen:
                                continue
                            self.seen.add(dk)

                            line_no = content[: m.start()].count("\n") + 1
                            ctx_s = max(0, line_no - 2)
                            ctx_e = min(len(lines), line_no + 1)
                            context = " | ".join(
                                ln.strip()[:120] for ln in lines[ctx_s:ctx_e]
                            )

                            findings.append(
                                Finding(
                                    category=category,
                                    subcategory=name,
                                    value=value[:600],
                                    severity=severity,
                                    file=filepath.name,
                                    line=line_no,
                                    context=context[:350],
                                    tool=self.name,
                                )
                            )
                    except re.error:
                        continue
        return findings


class TruffleHogExtractor(ExternalToolExtractor):
    def __init__(self):
        super().__init__(
            tool_name="trufflehog",
            command_template=[
                "trufflehog",
                "filesystem",
                "{file}",
                "--json",
                "--no-verification",
            ],
            result_parser=self._parse_trufflehog_output,
        )

    def _parse_trufflehog_output(
        self, output: str, filepath: Path
    ) -> List[Finding]:
        findings = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                findings.append(
                    Finding(
                        category="secrets",
                        subcategory=data.get("DetectorName", "Unknown Secret"),
                        value=data.get("Raw", ""),
                        severity="CRITICAL",
                        file=filepath.name,
                        line=data.get("SourceMetadata", {})
                        .get("Data", {})
                        .get("Filesystem", {})
                        .get("line", 0),
                        context=data.get("RawV2", "")[:200],
                        tool="trufflehog",
                        confidence="HIGH"
                        if data.get("Verified")
                        else "MEDIUM",
                    )
                )
            except json.JSONDecodeError:
                continue
        return findings


class RipgrepExtractor(ExternalToolExtractor):
    def __init__(self, patterns_file: Optional[Path] = None):
        self.patterns_file = patterns_file
        super().__init__(
            tool_name="rg",
            command_template=self._build_command(),
            result_parser=self._parse_ripgrep_output,
        )

    def _build_command(self):
        cmd = ["rg", "--json", "--hidden", "--no-heading"]
        if self.patterns_file:
            cmd.extend(["-f", str(self.patterns_file)])
        else:
            cmd.extend(
                [
                    "-e",
                    r"(api|v\d|graphql|rest)/",
                    "-e",
                    r"AKIA[0-9A-Z]{16}",
                    "-e",
                    r"AIza[0-9A-Za-z\-_]{35}",
                ]
            )
        cmd.append("{file}")
        return cmd

    def _parse_ripgrep_output(
        self, output: str, filepath: Path
    ) -> List[Finding]:
        findings = []
        for line in output.strip().split("\n"):
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match = data["data"]
                    text = match["lines"]["text"].strip()
                    findings.append(
                        Finding(
                            category="pattern_match",
                            subcategory="ripgrep_hit",
                            value=text[:300],
                            severity="INFO",
                            file=filepath.name,
                            line=match["line_number"],
                            tool="ripgrep",
                        )
                    )
            except Exception:
                continue
        return findings


class ExtractorOrchestrator:
    def __init__(self):
        self.extractors: List[BaseExtractor] = []

    def register(self, extractor: BaseExtractor):
        self.extractors.append(extractor)
        info(f"Registered extractor: {extractor.name}")

    def analyze(self, dir_path: Path) -> List[Finding]:
        all_findings = []
        for ext in self.extractors:
            substep(f"Running {ext.name} on {dir_path.name}/")
            findings = ext.analyze_directory(dir_path)
            all_findings.extend(findings)
            success(f"  {ext.name}: {len(findings)} findings")
        return self._deduplicate(all_findings)

    def _deduplicate(self, findings: List[Finding]) -> List[Finding]:
        seen, unique = set(), []
        for f in findings:
            key = hashlib.md5(
                f"{f.category}:{f.subcategory}:{f.value[:50]}:{f.line}".encode()
            ).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — SOURCE MAP RECONSTRUCTOR
# ══════════════════════════════════════════════════════════════════════════════


class SourceMapReconstructor:
    """Extract source files from .map and prep for ng build."""

    def __init__(self, layout: OutputLayout):
        self.layout = layout
        self.src_dir = layout.sources_dir

    def extract(self, chunks_dir: Path) -> Optional[Path]:
        map_files = list(chunks_dir.rglob("*.map")) + list(
            chunks_dir.rglob("*.js.map")
        )
        # Also check the dedicated maps dir
        map_files += list(self.layout.maps_dir.glob("*.map"))
        # Deduplicate by name
        seen_names, deduped = set(), []
        for mf in map_files:
            if mf.name not in seen_names:
                seen_names.add(mf.name)
                deduped.append(mf)
        map_files = deduped

        if not map_files:
            warn("No .map files found for source extraction.")
            return None

        self.src_dir.mkdir(parents=True, exist_ok=True)
        total = 0

        for mf in map_files:
            try:
                raw = json.loads(
                    mf.read_text(encoding="utf-8", errors="ignore")
                )
                srcs = raw.get("sources", [])
                cont = raw.get("sourcesContent", [])

                for i, src_path in enumerate(srcs):
                    if not src_path or i >= len(cont) or not cont[i]:
                        continue
                    safe = self._sanitize_path(src_path)
                    dest = self.src_dir / safe
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(cont[i], encoding="utf-8")
                    total += 1

            except Exception as e:
                warn(f"Map parse error {mf.name}: {e}")

        success(f"Extracted {total} source files → extracted_sources/")
        return self.src_dir

    def _sanitize_path(self, path: str) -> str:
        safe = re.sub(r"^(webpack:///|webpack://|ng://|/\.\.)", "", path)
        safe = re.sub(r"\.\.\/", "_UP_/", safe)
        safe = re.sub(r'[<>:"|?*]', "_", safe)
        return safe.lstrip("/\\") or "source"

    def extract_strings(self, chunks_dir: Path) -> Dict:
        urls, paths, emails = [], [], []
        url_re = re.compile(r'https?://[^\s"\'`<>\)]{8,250}')
        path_re = re.compile(r'["\`](/[a-zA-Z0-9_/\-]{3,100})["\`]')
        email_re = re.compile(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        )

        for f in chunks_dir.rglob("*.js"):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for m in url_re.finditer(content):
                    urls.append({"value": m.group(), "file": f.name})
                for m in path_re.finditer(content):
                    paths.append({"value": m.group(1), "file": f.name})
                for m in email_re.finditer(content):
                    emails.append({"value": m.group(), "file": f.name})
            except Exception:
                pass

        urls = list({v["value"]: v for v in urls}.values())
        paths = list({v["value"]: v for v in paths}.values())
        emails = list({v["value"]: v for v in emails}.values())

        result = {"urls": urls, "paths": paths, "emails": emails}
        out_path = self.layout.reports_dir / "all_strings.json"
        out_path.write_text(json.dumps(result, indent=2))
        success(
            f"Strings dump: {len(urls)} URLs · {len(paths)} paths · {len(emails)} emails → reports/all_strings.json"
        )
        return result


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — ANGULAR BUILD MODULE
# ══════════════════════════════════════════════════════════════════════════════


class AngularBuilder:
    """
    Scaffold a minimal Angular project around the extracted sources
    and run: ng build --configuration production
    """

    NG_VERSION = "^17.0.0"  # override with --ng-version

    MINIMAL_PACKAGE_JSON = {
        "name": "jsmap-recon",
        "version": "1.0.0",
        "private": True,
        "scripts": {
            "ng": "ng",
            "start": "ng serve",
            "build": "ng build --configuration production",
        },
        "dependencies": {
            "@angular/animations": "^17.0.0",
            "@angular/common": "^17.0.0",
            "@angular/compiler": "^17.0.0",
            "@angular/core": "^17.0.0",
            "@angular/forms": "^17.0.0",
            "@angular/platform-browser": "^17.0.0",
            "@angular/platform-browser-dynamic": "^17.0.0",
            "@angular/router": "^17.0.0",
            "rxjs": "~7.8.0",
            "tslib": "^2.3.0",
            "zone.js": "~0.14.0",
        },
        "devDependencies": {
            "@angular-devkit/build-angular": "^17.0.0",
            "@angular/cli": "^17.0.0",
            "@angular/compiler-cli": "^17.0.0",
            "typescript": "~5.2.0",
        },
    }

    MINIMAL_TSCONFIG = {
        "compileOnSave": False,
        "compilerOptions": {
            "baseUrl": "./",
            "outDir": "./dist/out-tsc",
            "strict": False,
            "noImplicitOverride": True,
            "noPropertyAccessFromIndexSignature": True,
            "forceConsistentCasingInFileNames": True,
            "newLine": "lf",
            "noFallthroughCasesInSwitch": True,
            "sourceMap": True,
            "declaration": False,
            "downlevelIteration": True,
            "experimentalDecorators": True,
            "moduleResolution": "node",
            "importHelpers": True,
            "target": "ES2022",
            "module": "ES2022",
            "useDefineForClassFields": False,
            "lib": ["ES2022", "dom"],
        },
        "angularCompilerOptions": {
            "enableI18nLegacyMessageIdFormat": False,
            "strictInjectionParameters": True,
            "strictInputAccessModifiers": True,
            "strictTemplates": True,
        },
    }

    ANGULAR_JSON_TEMPLATE = {
        "$schema": "./node_modules/@angular/cli/lib/config/schema.json",
        "version": 1,
        "newProjectRoot": "projects",
        "projects": {
            "jsmap-recon": {
                "projectType": "application",
                "schematics": {},
                "root": "",
                "sourceRoot": "src",
                "prefix": "app",
                "architect": {
                    "build": {
                        "builder": "@angular-devkit/build-angular:application",
                        "options": {
                            "outputPath": "dist/jsmap-recon",
                            "index": "src/index.html",
                            "browser": "src/main.ts",
                            "polyfills": ["zone.js"],
                            "tsConfig": "tsconfig.json",
                            "assets": ["src/favicon.ico", "src/assets"],
                            "styles": ["src/styles.css"],
                            "scripts": [],
                        },
                        "configurations": {
                            "production": {
                                "budgets": [
                                    {
                                        "type": "initial",
                                        "maximumWarning": "500kb",
                                        "maximumError": "1mb",
                                    },
                                    {
                                        "type": "anyComponentStyle",
                                        "maximumWarning": "2kb",
                                        "maximumError": "4kb",
                                    },
                                ],
                                "outputHashing": "all",
                            },
                            "development": {
                                "optimization": False,
                                "extractLicenses": False,
                                "sourceMap": True,
                            },
                        },
                        "defaultConfiguration": "production",
                    },
                    "serve": {
                        "builder": "@angular-devkit/build-angular:dev-server",
                        "configurations": {
                            "production": {
                                "buildTarget": "jsmap-recon:build:production"
                            },
                            "development": {
                                "buildTarget": "jsmap-recon:build:development"
                            },
                        },
                        "defaultConfiguration": "development",
                    },
                },
            }
        },
    }

    MINIMAL_APP_MODULE = """\
import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { AppComponent } from './app.component';

@NgModule({
  declarations: [AppComponent],
  imports: [BrowserModule],
  bootstrap: [AppComponent],
})
export class AppModule {}
"""

    MINIMAL_APP_COMPONENT = """\
import { Component } from '@angular/core';

@Component({
  selector: 'app-root',
  template: '<h1>jsmap-suite recon build</h1>',
  styles: []
})
export class AppComponent {}
"""

    MINIMAL_MAIN_TS = """\
import { platformBrowserDynamic } from '@angular/platform-browser-dynamic';
import { AppModule } from './app/app.module';

platformBrowserDynamic()
  .bootstrapModule(AppModule)
  .catch(err => console.error(err));
"""

    MINIMAL_INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>jsmap-suite</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <app-root></app-root>
</body>
</html>
"""

    def __init__(self, layout: OutputLayout, ng_version: Optional[str] = None):
        self.layout = layout
        self.ng_version = ng_version or self.NG_VERSION
        self.project = layout.ng_project_dir
        self.build_log = layout.log_path("build")

    def _check_prerequisites(self) -> bool:
        for tool in ["node", "npm", "ng"]:
            if not shutil.which(tool):
                error(
                    f"'{tool}' not found in PATH. Install Node.js + Angular CLI first."
                )
                error("  npm install -g @angular/cli")
                return False
        return True

    def scaffold(self, extracted_sources: Optional[Path] = None) -> bool:
        """Create minimal Angular project skeleton."""
        substep("Scaffolding Angular project structure")
        proj = self.project

        # Write config files
        (proj / "package.json").write_text(
            json.dumps(self.MINIMAL_PACKAGE_JSON, indent=2), encoding="utf-8"
        )
        (proj / "tsconfig.json").write_text(
            json.dumps(self.MINIMAL_TSCONFIG, indent=2), encoding="utf-8"
        )
        (proj / "angular.json").write_text(
            json.dumps(self.ANGULAR_JSON_TEMPLATE, indent=2), encoding="utf-8"
        )

        # Create src structure
        src = proj / "src"
        app = src / "app"
        assets = src / "assets"
        for d in [src, app, assets]:
            d.mkdir(parents=True, exist_ok=True)

        (src / "main.ts").write_text(self.MINIMAL_MAIN_TS, encoding="utf-8")
        (src / "index.html").write_text(
            self.MINIMAL_INDEX_HTML, encoding="utf-8"
        )
        (src / "styles.css").write_text(
            "/* global styles */\n", encoding="utf-8"
        )
        (src / "favicon.ico").write_bytes(b"")
        (app / "app.module.ts").write_text(
            self.MINIMAL_APP_MODULE, encoding="utf-8"
        )
        (app / "app.component.ts").write_text(
            self.MINIMAL_APP_COMPONENT, encoding="utf-8"
        )

        # If we have extracted sources, symlink / copy them in
        if extracted_sources and extracted_sources.exists():
            substep("Copying extracted sources into ng_project/src/")
            dest_recon = src / "recon"
            if dest_recon.exists():
                shutil.rmtree(dest_recon)
            shutil.copytree(
                str(extracted_sources), str(dest_recon), dirs_exist_ok=False
            )
            success("Sources copied → ng_project/src/recon/")

        success("Angular project scaffolded → ng_project/")
        return True

    def npm_install(self) -> bool:
        substep("Running npm install (this may take a minute) ...")
        try:
            result = subprocess.run(
                ["npm", "install", "--legacy-peer-deps"],
                cwd=str(self.project),
                capture_output=True,
                text=True,
                timeout=300,
            )
            log_content = result.stdout + "\n" + result.stderr
            self.build_log.write_text(log_content, encoding="utf-8")

            if result.returncode != 0:
                error("npm install failed. Check logs/build.log")
                for line in result.stderr.splitlines()[-20:]:
                    dim(line)
                return False
            success("npm install complete")
            return True
        except subprocess.TimeoutExpired:
            error("npm install timed out (>5 min)")
            return False
        except Exception as e:
            error(f"npm install error: {e}")
            return False

    def build(self) -> bool:
        """Run ng build --configuration production."""
        substep("Running:  ng build --configuration production")
        try:
            result = subprocess.run(
                ["ng", "build", "--configuration", "production"],
                cwd=str(self.project),
                capture_output=True,
                text=True,
                timeout=600,
            )
            # Append to build log
            existing = (
                self.build_log.read_text(encoding="utf-8")
                if self.build_log.exists()
                else ""
            )
            self.build_log.write_text(
                existing
                + "\n\n─── ng build ───\n"
                + result.stdout
                + "\n"
                + result.stderr,
                encoding="utf-8",
            )

            if result.returncode != 0:
                error("ng build failed. Check logs/build.log")
                for line in result.stderr.splitlines()[-30:]:
                    dim(line)
                return False

            # Show output summary
            dist_contents = list((self.project / "dist").rglob("*"))
            js_files = [f for f in dist_contents if f.suffix == ".js"]
            success(
                f"Build complete!  {len(js_files)} JS bundle(s) in ng_project/dist/"
            )

            # Copy dist to layout for easy access
            dest_dist = self.layout.ng_dist_dir
            if dest_dist.exists():
                shutil.rmtree(dest_dist)
            shutil.copytree(
                str(self.project / "dist"), str(dest_dist), dirs_exist_ok=False
            )
            success(
                f"Dist output → {dest_dist.relative_to(self.layout.root)}/"
            )
            return True

        except subprocess.TimeoutExpired:
            error("ng build timed out (>10 min)")
            return False
        except Exception as e:
            error(f"ng build error: {e}")
            return False

    def run(self, extracted_sources: Optional[Path] = None) -> bool:
        """Full pipeline: prereq check → scaffold → npm install → ng build."""
        if not self._check_prerequisites():
            return False
        if not self.scaffold(extracted_sources):
            return False
        if not self.npm_install():
            return False
        return self.build()


# ══════════════════════════════════════════════════════════════════════════════
#  REPORTING MODULE
# ══════════════════════════════════════════════════════════════════════════════


class ReportGenerator:
    SEV_ICON = {
        "CRITICAL": "💀",
        "HIGH": "🔴",
        "MEDIUM": "🟡",
        "LOW": "🔵",
        "INFO": "⚪",
    }
    SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

    def __init__(self, findings: List[Finding]):
        self.findings = findings

    def print_console(self):
        if not self.findings:
            warn("No findings.")
            return
        by_sev = defaultdict(list)
        for f in self.findings:
            by_sev[f.severity].append(f)
        for sev in self.SEV_ORDER:
            group = by_sev.get(sev, [])
            if not group:
                continue
            icon = self.SEV_ICON[sev]
            color = Finding(sev, "", "", sev, "", 0).sev_color()
            section(f"{icon}  {color}{sev}{C.RESET}  [{len(group)} findings]")
            by_cat = defaultdict(list)
            for f in group:
                by_cat[f.subcategory].append(f)
            for subcat, items in sorted(by_cat.items()):
                print(
                    f"\n  {C.BOLD}{C.WHITE}{subcat}{C.RESET}  ({len(items)})"
                )
                for item in items[:60]:
                    val = item.value[:130].replace("\n", " ")
                    tool_tag = (
                        f" [{item.tool}]" if item.tool != "native" else ""
                    )
                    print(
                        f"  {C.GRAY}{item.file}:{item.line}{C.RESET}{C.CYAN}{tool_tag}{C.RESET}"
                    )
                    print(f"  {color}  →  {val}{C.RESET}")
        self._print_summary(by_sev)

    def _print_summary(self, by_sev: dict):
        print(f"\n{C.BOLD}{'═' * 68}{C.RESET}")
        print(f"{C.BOLD}  FINDINGS SUMMARY{C.RESET}")
        print(f"{'─' * 68}")
        for sev in self.SEV_ORDER:
            n = len(by_sev.get(sev, []))
            if not n:
                continue
            color = Finding(sev, "", "", sev, "", 0).sev_color()
            bar = "█" * min(n, 48)
            print(
                f"  {color}{sev:<12}{C.RESET}  {n:>4}  {C.GRAY}{bar}{C.RESET}"
            )
        print(f"{'─' * 68}")
        print(f"  {'Total':<12}  {len(self.findings):>4}")
        print(f"{'═' * 68}\n")

    def save(self, out_path: Path, fmt: str = "json"):
        if fmt == "json":
            out_path.write_text(
                json.dumps([asdict(f) for f in self.findings], indent=2)
            )
        elif fmt == "csv":
            self._save_csv(out_path)
        elif fmt == "md":
            self._save_markdown(out_path)
        elif fmt == "txt":
            self._save_text(out_path)
        elif fmt == "html":
            self._save_html(out_path)
        success(f"Report → {out_path}")

    def _save_csv(self, out_path: Path):
        import csv

        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            fields = [
                "severity",
                "category",
                "subcategory",
                "value",
                "file",
                "line",
                "context",
                "tool",
            ]
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for f in self.findings:
                w.writerow({k: getattr(f, k) for k in fields})

    def _save_markdown(self, out_path: Path):
        ts = datetime.now().isoformat()
        md = [
            f"# jsmap-suite Report\n\n**Generated:** {ts}  \n**Total:** {len(self.findings)}\n"
        ]
        by_sev = defaultdict(list)
        for f in self.findings:
            by_sev[f.severity].append(f)
        for sev in self.SEV_ORDER:
            group = by_sev.get(sev, [])
            if not group:
                continue
            md.append(f"## {self.SEV_ICON[sev]} {sev} ({len(group)})")
            by_cat = defaultdict(list)
            for f in group:
                by_cat[f.subcategory].append(f)
            for cat, items in by_cat.items():
                md.append(f"### {cat}")
                md.append("| File | Line | Tool | Value |")
                md.append("|------|------|------|-------|")
                for item in items[:200]:
                    v = item.value[:100].replace("|", "\\|").replace("\n", " ")
                    md.append(
                        f"| `{item.file}` | {item.line} | {item.tool} | `{v}` |"
                    )
                md.append("")
        out_path.write_text("\n".join(md), encoding="utf-8")

    def _save_text(self, out_path: Path):
        lines = ["jsmap-suite Report", f"Generated: {datetime.now()}", ""]
        for f in self.findings:
            lines += [
                f"[{f.severity}] {f.subcategory} (via {f.tool})",
                f"  File: {f.file}:{f.line}",
                f"  Value: {f.value[:250]}",
                "",
            ]
        out_path.write_text("\n".join(lines), encoding="utf-8")

    def _save_html(self, out_path: Path):
        sev_colors = {
            "CRITICAL": "#ff3b30",
            "HIGH": "#ff6b35",
            "MEDIUM": "#ffcc00",
            "LOW": "#5ac8fa",
            "INFO": "#8e8e93",
        }
        rows = ""
        for f in self.findings:
            col = sev_colors.get(f.severity, "#888")
            v = f.value[:200].replace("<", "&lt;").replace(">", "&gt;")
            rows += (
                f'<tr><td><span style="background:{col};padding:2px 6px;'
                f'border-radius:3px;color:#000">{f.severity}</span></td>'
                f"<td>{f.subcategory}</td><td>{f.tool}</td>"
                f"<td>{f.file}:{f.line}</td><td><code>{v}</code></td></tr>"
            )
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>jsmap-suite Report</title>
<style>
body{{font-family:monospace;background:#0d0d0d;color:#e0e0e0;padding:20px}}
h1{{color:#a855f7}} table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#1a1a1a;color:#aaa;padding:8px;text-align:left}}
td{{padding:6px 8px;border-bottom:1px solid #222}}
code{{color:#0f0;word-break:break-all}}
tr:hover{{background:#111}}
</style></head>
<body>
<h1>⚡ jsmap-suite  ·  {len(self.findings)} findings  ·  {datetime.now():%Y-%m-%d %H:%M}</h1>
<table>
<tr><th>Severity</th><th>Type</th><th>Tool</th><th>Location</th><th>Value</th></tr>
{rows}
</table></body></html>"""
        out_path.write_text(html, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY WRITER
# ══════════════════════════════════════════════════════════════════════════════


def write_summary(
    layout: OutputLayout,
    target_url: str,
    findings: List[Finding],
    dl_stats: dict,
    build_ok: Optional[bool],
):
    summary = {
        "target": target_url,
        "scan_time": datetime.now().isoformat(),
        "output_root": str(layout.root.resolve()),
        "download": dl_stats,
        "findings": {
            "total": len(findings),
            "critical": sum(1 for f in findings if f.severity == "CRITICAL"),
            "high": sum(1 for f in findings if f.severity == "HIGH"),
            "medium": sum(1 for f in findings if f.severity == "MEDIUM"),
            "low": sum(1 for f in findings if f.severity == "LOW"),
            "info": sum(1 for f in findings if f.severity == "INFO"),
        },
        "ng_build": ("success" if build_ok else "failed")
        if build_ok is not None
        else "skipped",
        "layout": {
            "chunks": str(layout.chunks_dir),
            "maps": str(layout.maps_dir),
            "sources": str(layout.sources_dir),
            "ng_dist": str(layout.ng_dist_dir),
            "reports": str(layout.reports_dir),
            "logs": str(layout.logs_dir),
        },
    }
    layout.summary_file.write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    success(f"Summary → {layout.summary_file}")


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
    if getattr(args, "no_verify", False):
        session.verify = False
        urllib3.disable_warnings()
    if getattr(args, "cookie", None):
        session.headers.update({"Cookie": args.cookie})
    if getattr(args, "header", None):
        for hdr in args.header:
            k, _, v = hdr.partition(":")
            session.headers.update({k.strip(): v.strip()})
    return session


def main():
    parser = argparse.ArgumentParser(
        description="jsmap-suite — Enhanced Modular JS Recon Tool",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
EXAMPLES:
  Full recon + ng build:
    python3 jsmap_suite.py https://app.target.com/ --all-extractors --ng-build

  Extract sources only, then build:
    python3 jsmap_suite.py https://app.target.com/ --extract-sources --ng-build

  Use external tools (trufflehog + ripgrep):
    python3 jsmap_suite.py https://app.target.com/ --use-trufflehog --use-ripgrep

  Analyze existing directory:
    python3 jsmap_suite.py --analyze-only --dir ./chunks

  Download only, custom output dir:
    python3 jsmap_suite.py https://app.target.com/ --download-only -o /tmp/recon
""",
    )

    parser.add_argument("url", nargs="?", default=None, help="Target URL")
    parser.add_argument(
        "--download-only", action="store_true", help="Phase 1 only"
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Phase 2 only (needs --dir)",
    )
    parser.add_argument(
        "--dir", help="Directory to analyze (with --analyze-only)"
    )

    # Extractor selection
    ext = parser.add_argument_group("Extractors")
    ext.add_argument(
        "--all-extractors",
        action="store_true",
        help="Enable all available extractors",
    )
    ext.add_argument(
        "--use-trufflehog",
        action="store_true",
        help="Use TruffleHog for secrets",
    )
    ext.add_argument(
        "--use-ripgrep",
        action="store_true",
        help="Use ripgrep for fast pattern matching",
    )
    ext.add_argument(
        "--native-only",
        action="store_true",
        help="Use only native regex (default)",
    )

    # Download options
    dl = parser.add_argument_group("Download")
    dl.add_argument("-m", "--map", help="JSON chunk map file")
    dl.add_argument("-t", "--threads", type=int, default=5)
    dl.add_argument("-d", "--delay", type=float, default=0.0)

    # Analysis options
    an = parser.add_argument_group("Analysis")
    an.add_argument(
        "--severity",
        default="INFO",
        choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
    )
    an.add_argument(
        "--extract-sources",
        action="store_true",
        help="Phase 3: reconstruct source tree from .map files",
    )
    an.add_argument(
        "--strings",
        action="store_true",
        help="Dump all URLs/paths/emails to reports/all_strings.json",
    )
    an.add_argument(
        "--no-print",
        action="store_true",
        help="Suppress console findings output",
    )

    # Angular build
    ng = parser.add_argument_group("Angular Build")
    ng.add_argument(
        "--ng-build",
        action="store_true",
        help="Phase 4: scaffold + ng build --configuration production",
    )
    ng.add_argument(
        "--ng-version",
        default=None,
        help="Override Angular version (default: ^17.0.0)",
    )
    ng.add_argument(
        "--ng-only",
        action="store_true",
        help="Skip download/analysis; only run ng build on existing ng_project/",
    )

    # Output
    out = parser.add_argument_group("Output")
    out.add_argument("-o", "--output", help="Output root directory")
    out.add_argument(
        "--format",
        default="json",
        choices=["json", "csv", "md", "txt", "html"],
    )

    # Network
    net = parser.add_argument_group("Network")
    net.add_argument("--proxy")
    net.add_argument("--no-verify", action="store_true")
    net.add_argument("--cookie")
    net.add_argument("-H", "--header", action="append", default=[])

    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    banner()

    # ── validation ────────────────────────────────────────────────────────────
    if not args.url and not args.analyze_only and not args.ng_only:
        parser.print_help()
        sys.exit(1)
    if args.analyze_only and not args.dir:
        error("--analyze-only requires --dir")
        sys.exit(1)

    # ── build output layout ───────────────────────────────────────────────────
    if args.output:
        root = Path(args.output)
    elif args.url:
        host = urlparse(args.url).netloc.replace(":", "_")
        root = Path(f"jsmap_{host}_{datetime.now():%Y%m%d_%H%M%S}")
    else:
        root = Path(f"jsmap_analysis_{datetime.now():%Y%m%d_%H%M%S}")

    layout = OutputLayout(root)
    layout.create_all()

    # ── ng-only mode ──────────────────────────────────────────────────────────
    if args.ng_only:
        step(4, "NG BUILD ONLY")
        builder = AngularBuilder(layout, args.ng_version)
        build_ok = builder.run()
        if build_ok:
            success("ng build complete.")
        sys.exit(0 if build_ok else 1)

    # ── Phase 1: Download ─────────────────────────────────────────────────────
    src_dir = None
    findings = []
    build_ok = None

    if not args.analyze_only:
        step(1, "DOWNLOADING CHUNKS")
        session = build_session(args)
        downloader = ChunkDownloader(
            session, args.url, layout, args.threads, args.delay
        )

        chunk_map, special_names, extra_scripts = {}, {}, []
        if args.map:
            with open(args.map) as f:
                chunk_map = json.load(f)
        else:
            chunk_map, special_names, extra_scripts = (
                downloader.auto_detect_chunks()
            )

        chunks_dir = downloader.download_all(
            chunk_map, special_names, extra_scripts
        )

        if args.download_only:
            write_summary(layout, args.url or "", [], downloader.stats, None)
            success("Download complete.")
            sys.exit(0)
    else:
        chunks_dir = Path(args.dir)
        # Fake downloader stats
        downloader = type(
            "FakeDownloader",
            (),
            {"stats": {"ok": 0, "skipped": 0, "failed": 0}},
        )()

    # ── Phase 2: Extract/Analyze ──────────────────────────────────────────────
    step(2, "EXTRACTING & ANALYZING")
    orchestrator = ExtractorOrchestrator()

    if not (args.all_extractors or args.use_trufflehog or args.use_ripgrep):
        args.native_only = True

    orchestrator.register(NativeRegexExtractor(args.severity))

    if args.all_extractors or args.use_trufflehog:
        th = TruffleHogExtractor()
        if th.is_available():
            orchestrator.register(th)
        else:
            warn("TruffleHog not found in PATH, skipping")

    if args.all_extractors or args.use_ripgrep:
        rg = RipgrepExtractor()
        if rg.is_available():
            orchestrator.register(rg)
        else:
            warn("ripgrep not found in PATH, skipping")

    findings = orchestrator.analyze(chunks_dir)

    # ── Phase 3: Reconstruct ──────────────────────────────────────────────────
    if args.extract_sources or args.ng_build:
        step(3, "RECONSTRUCTING SOURCES")
        recon = SourceMapReconstructor(layout)
        src_dir = recon.extract(chunks_dir)

        if src_dir:
            info("Re-analyzing extracted sources for additional findings...")
            additional = orchestrator.analyze(src_dir)
            new_count = len([f for f in additional if f not in findings])
            if new_count:
                success(
                    f"{new_count} additional findings in reconstructed sources"
                )
                findings = list(
                    {
                        f.value[:50] + f.file: f for f in findings + additional
                    }.values()
                )

        if args.strings:
            recon.extract_strings(chunks_dir)

    # ── Phase 4: ng build ─────────────────────────────────────────────────────
    if args.ng_build:
        step(4, "ANGULAR BUILD  [ng build --configuration production]")
        builder = AngularBuilder(layout, args.ng_version)
        build_ok = builder.run(extracted_sources=src_dir)

    # ── Reporting ─────────────────────────────────────────────────────────────
    reporter = ReportGenerator(findings)
    if not args.no_print:
        reporter.print_console()

    # Save all formats that are requested; always save JSON
    reporter.save(layout.report_path(args.format), args.format)
    if args.format != "json":
        reporter.save(layout.report_path("json"), "json")

    # Always save HTML report
    if args.format != "html":
        reporter.save(layout.report_path("html"), "html")

    write_summary(
        layout,
        args.url or args.dir or "",
        findings,
        downloader.stats,
        build_ok,
    )

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f"\n{C.BOLD}{'═' * 68}{C.RESET}")
    print(
        f"{C.BOLD}  COMPLETE{C.RESET}  ·  output: {C.CYAN}{layout.root.resolve()}{C.RESET}"
    )
    crits = sum(1 for f in findings if f.severity == "CRITICAL")
    highs = sum(1 for f in findings if f.severity == "HIGH")
    if crits:
        critical(f"{crits} CRITICAL findings!")
    if highs:
        warn(f"{highs} HIGH severity findings")
    print(f"  Total findings : {len(findings)}")
    print(f"  Reports        : {layout.reports_dir}/")
    print(f"  Logs           : {layout.logs_dir}/")
    if build_ok is not None:
        status = (
            f"{C.GREEN}SUCCESS{C.RESET}"
            if build_ok
            else f"{C.RED}FAILED{C.RESET}"
        )
        print(f"  ng build       : {status}")
    print(f"{'═' * 68}\n")


if __name__ == "__main__":
    main()

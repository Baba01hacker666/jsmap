#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║                                                                          ║
║        jsmap-suite  ——  Modular Version                                  ║
║                                                                          ║
║   Refactored architecture:                                               ║
║   • Downloader:    Your existing robust fetcher (unchanged)              ║
║   • Extractor:     Pluggable analysis engines                            ║
║   • Reconstructor: Source map recovery                                   ║
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
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Callable, Any
from abc import ABC, abstractmethod

# ══════════════════════════════════════════════════════════════════════════════
#  COLORS & LOGGING (unchanged)
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
{C.RESET}{C.YELLOW}  Modular Analysis Suite  —  Downloader + Pluggable Extractors{C.RESET}
{C.GRAY}  Phase 1: Download  |  Phase 2: Extract  |  Phase 3: Reconstruct{C.RESET}
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
#  PHASE 1 — DOWNLOADER MODULE (Your existing code, encapsulated)
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

class ChunkDownloader:
    """Your robust downloader, encapsulated as a reusable class."""
    
    def __init__(self, session: requests.Session, base_url: str, 
                 threads: int = 5, delay: float = 0.0):
        self.session = session
        self.base_url = base_url.rstrip("/") + "/"
        self.threads = threads
        self.delay = delay
        self.stats = {"ok": 0, "skipped": 0, "failed": 0}
        
    def extract_chunk_map_from_runtime(self, content: str) -> dict:
        """Parses Webpack runtime.js to extract chunk_id → hash mappings."""
        chunk_map = {}
        patterns = [
            (r'\{(\s*(?:"?\d+"?\s*:\s*"[a-f0-9]+"(?:\s*,\s*)?)+)\}', 
             lambda m: re.findall(r'"?(\d+)"?\s*:\s*"([a-f0-9]{8,})"', m)),
            (r'\[\s*(\d+)\s*,\s*"([a-f0-9]{8,})"',
             lambda m: [(m.group(1), m.group(2))]),
            (r'(\d+):"([a-f0-9]{8,})"',
             lambda m: [(m.group(1), m.group(2))]),
            (r'case\s+(\d+)\s*:\s*return\s*["\']([a-f0-9]{8,})["\']',
             lambda m: [(m.group(1), m.group(2))]),
        ]
        
        for pattern, extractor in patterns:
            for match in re.finditer(pattern, content):
                try:
                    pairs = extractor(match)
                    for chunk_id, chunk_hash in pairs:
                        chunk_map[chunk_id] = chunk_hash
                except:
                    continue
        return chunk_map

    def extract_named_chunks(self, content: str) -> dict:
        """Extract named chunk overrides."""
        special = {}
        patterns = [
            r'(\d+)\s*===\s*\w+\s*\?\s*"([a-zA-Z0-9_\-]+)"',
            r'"?(\d+)"?\s*:\s*"([a-zA-Z][a-zA-Z0-9_\-]+)"'
        ]
        for pat in patterns:
            for cid, cname in re.findall(pat, content):
                if not re.match(r'^[a-f0-9]{8,}$', cname):
                    special[cid] = cname
        return special

    def resolve_chunk_filename(self, chunk_id: str, chunk_hash: str, 
                               special_names: dict = None) -> str:
        prefix = (special_names or {}).get(chunk_id, chunk_id)
        return f"{prefix}.{chunk_hash}.js"

    def try_alternate_paths(self, filename: str) -> Optional[requests.Response]:
        """Try common alternate asset serving paths when primary 404s."""
        alt_prefixes = ["assets/", "static/js/", "js/", "dist/", "build/", "public/"]
        for prefix in alt_prefixes:
            try:
                alt_url = urljoin(self.base_url, prefix + filename)
                r = self.session.get(alt_url, timeout=8)
                if r.status_code == 200:
                    info(f"  Found at alternate path: {prefix}{filename}")
                    return r
            except Exception:
                pass
        return None

    def download_chunk(self, chunk_id: str, chunk_hash: str,
                       save_dir: Path, special_names: dict) -> dict:
        """Download a single chunk with error handling."""
        filename = self.resolve_chunk_filename(chunk_id, chunk_hash, special_names)
        url = urljoin(self.base_url, filename)
        save_path = save_dir / filename

        if save_path.exists():
            return {"status": "skipped", "filename": filename, "chunk_id": chunk_id}

        if self.delay > 0:
            time.sleep(self.delay)

        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                save_path.write_bytes(resp.content)
                success(f"Downloaded: {filename} ({len(resp.content):,} bytes)")
                return {"status": "ok", "filename": filename, "size": len(resp.content)}
            elif resp.status_code == 404:
                alt = self.try_alternate_paths(filename)
                if alt:
                    save_path.write_bytes(alt.content)
                    return {"status": "ok", "filename": filename, "size": len(alt.content), 
                            "note": "alternate_path"}
                error(f"Not found (404): {filename}")
                return {"status": "404", "filename": filename}
            else:
                return {"status": f"http_{resp.status_code}", "filename": filename}
        except requests.exceptions.ConnectionError:
            return {"status": "conn_error", "filename": filename}
        except requests.exceptions.Timeout:
            return {"status": "timeout", "filename": filename}
        except Exception as e:
            return {"status": "error", "filename": filename, "error": str(e)}

    def auto_detect_chunks(self) -> tuple[dict, dict, list]:
        """Fetch index.html → find runtime.js → extract chunk map."""
        chunk_map, special_names, all_scripts = {}, {}, []
        
        info("Auto-detect: fetching index.html ...")
        try:
            resp = self.session.get(self.base_url, timeout=15)
            html = resp.text
            
            # Find scripts
            raw_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', html)
            raw_srcs += re.findall(r'"([^"]*\.js)"', html)
            
            for src in raw_srcs:
                try:
                    full = urljoin(self.base_url, src.split("?")[0])
                    if full not in all_scripts:
                        all_scripts.append(full)
                except:
                    pass

            # Find runtime
            runtime_url = next((url for url in all_scripts 
                              if re.search(r'runtime', url, re.IGNORECASE)), None)
            
            if not runtime_url:
                for g in ["runtime.js", "runtime.min.js", "webpack-runtime.js"]:
                    test = urljoin(self.base_url, g)
                    try:
                        r = self.session.get(test, timeout=5)
                        if r.status_code == 200 and "webpackChunk" in r.text:
                            runtime_url = test
                            break
                    except:
                        pass

            if runtime_url:
                info(f"Fetching runtime: {runtime_url}")
                r = self.session.get(runtime_url, timeout=15)
                if r.status_code == 200:
                    chunk_map = self.extract_chunk_map_from_runtime(r.text)
                    special_names = self.extract_named_chunks(r.text)
                    if chunk_map:
                        success(f"Extracted {len(chunk_map)} chunks from runtime.js")
                        
        except Exception as e:
            warn(f"Auto-detect failed: {e}")
            
        return chunk_map, special_names, all_scripts

    def download_all(self, chunk_map: dict = None, special_names: dict = None,
                     extra_scripts: list = None, save_dir: Path = None) -> Path:
        """Main entry point for downloading."""
        save_dir = save_dir or Path("chunks")
        save_dir.mkdir(parents=True, exist_ok=True)
        
        results = []
        
        # Download mapped chunks
        if chunk_map:
            info(f"Downloading {len(chunk_map)} chunks | threads={self.threads}")
            with ThreadPoolExecutor(max_workers=self.threads) as ex:
                futures = {
                    ex.submit(self.download_chunk, cid, chash, save_dir, special_names): cid
                    for cid, chash in chunk_map.items()
                }
                for fut in as_completed(futures):
                    results.append(fut.result())
                    
        # Download direct scripts
        if extra_scripts:
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
                        success(f"Downloaded: {fname}")
                        results.append({"status": "ok", "filename": fname})
                except Exception as e:
                    warn(f"Failed {fname}: {e}")
                    
        # Try to get source maps
        self._fetch_sourcemaps(save_dir)
        
        # Calculate stats
        self.stats["ok"] = sum(1 for r in results if r["status"] == "ok")
        self.stats["skipped"] = sum(1 for r in results if r["status"] == "skipped")
        self.stats["failed"] = len(results) - self.stats["ok"] - self.stats["skipped"]
        
        return save_dir
    
    def _fetch_sourcemaps(self, chunks_dir: Path):
        """Attempt to download .map files for each .js."""
        map_count = 0
        for js_file in chunks_dir.glob("*.js"):
            content = js_file.read_text(encoding="utf-8", errors="ignore")
            map_ref = re.search(r'//[#@]\s*sourceMappingURL=([^\s]+)', content)
            if map_ref:
                map_ref_val = map_ref.group(1).strip()
                if not map_ref_val.startswith("data:"):
                    map_url = urljoin(self.base_url, map_ref_val)
                    map_path = chunks_dir / (js_file.name + ".map")
                    if not map_path.exists():
                        try:
                            mr = self.session.get(map_url, timeout=10)
                            if mr.status_code == 200:
                                map_path.write_bytes(mr.content)
                                map_count += 1
                        except:
                            pass
        if map_count:
            success(f"Downloaded {map_count} source map files")


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — PLUGGABLE EXTRACTOR INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Finding:
    category:    str
    subcategory: str
    value:       str
    severity:    str
    file:        str
    line:        int
    context:     str = ""
    confidence:  str = "HIGH"
    tool:        str = "native"  # Track which extractor found this

    def sev_color(self):
        return {
            "CRITICAL": C.BG_RED + C.WHITE, "HIGH": C.RED,
            "MEDIUM": C.YELLOW, "LOW": C.CYAN, "INFO": C.GRAY,
        }.get(self.severity, C.RESET)


class BaseExtractor(ABC):
    """Abstract base class for all extractors."""
    
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
        """Analyze a single file and return findings."""
        pass
    
    def analyze_directory(self, dir_path: Path) -> List[Finding]:
        """Analyze all matching files in directory."""
        findings = []
        for ext in self.supported_extensions:
            for f in dir_path.rglob(f"*{ext}"):
                if f.is_file():
                    try:
                        findings.extend(self.analyze_file(f))
                    except Exception as e:
                        warn(f"{self.name} failed on {f}: {e}")
        return findings


class ExternalToolExtractor(BaseExtractor):
    """Wrapper for external CLI tools (ripgrep, trufflehog, etc.)."""
    
    def __init__(self, tool_name: str, command_template: List[str], 
                 result_parser: Callable[[str, Path], List[Finding]]):
        self.tool_name = tool_name
        self.command_template = command_template
        self.result_parser = result_parser
        self._available = None
        
    @property
    def name(self) -> str:
        return self.tool_name
    
    @property
    def supported_extensions(self) -> tuple:
        return (".js", ".ts", ".jsx", ".tsx", ".mjs", ".json", ".map")
    
    def is_available(self) -> bool:
        """Check if the external tool is installed."""
        if self._available is None:
            try:
                subprocess.run([self.tool_name, "--version"], 
                             capture_output=True, check=True)
                self._available = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                self._available = False
        return self._available
    
    def analyze_file(self, filepath: Path) -> List[Finding]:
        if not self.is_available():
            return []
        
        cmd = [arg.format(file=str(filepath)) for arg in self.command_template]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return self.result_parser(result.stdout, filepath)
        except subprocess.TimeoutExpired:
            warn(f"{self.tool_name} timeout on {filepath}")
            return []
        except Exception as e:
            warn(f"{self.tool_name} error on {filepath}: {e}")
            return []


class NativeRegexExtractor(BaseExtractor):
    """Your original regex-based analyzer, extracted into a class."""
    
    RULES = {
        "endpoints": [
            {
                "name": "REST API Path",
                "severity": "INFO",
                "patterns": [
                    r'(?:fetch|axios\.(?:get|post|put|patch|delete)|http(?:Client)?\.(?:get|post|put|patch|delete))\s*\(\s*[`"\']([/][^`"\']{3,200})[`"\']',
                    r'["\'](\/(api|v\d+|rest|graphql|gql|auth|oauth|user|admin|account|service)[/a-zA-Z0-9_\-.:?=%&{}]{2,120})["\']',
                ],
                "blacklist": [r'node_modules', r'\.spec\.', r'localhost:\d{4}(?!/api)'],
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
                "patterns": [r'(AKIA[0-9A-Z]{16})'],
            },
            {
                "name": "AWS Secret Key",
                "severity": "CRITICAL", 
                "patterns": [r'(?:aws[_\-]?secret|secretAccessKey)\s*[=:]\s*["\']([A-Za-z0-9/+]{40})["\']'],
            },
            {
                "name": "Google API Key",
                "severity": "CRITICAL",
                "patterns": [r'(AIza[0-9A-Za-z\-_]{35})'],
            },
            {
                "name": "Firebase Config",
                "severity": "HIGH",
                "patterns": [r'firebaseConfig\s*[=:]\s*\{([^}]{50,600})\}'],
            },
            {
                "name": "Stripe Key",
                "severity": "CRITICAL",
                "patterns": [r'((?:pk|sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,})'],
            },
            {
                "name": "JWT Token",
                "severity": "CRITICAL",
                "patterns": [r'["\`](ey[A-Za-z0-9\-_]{20,}\.ey[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,})["\`]'],
            },
            {
                "name": "Generic Secret",
                "severity": "HIGH",
                "patterns": [
                    r'(?:api[_\-]?key|apiKey|API_KEY|access[_\-]?token|secret|password)\s*[=:]\s*["\']([A-Za-z0-9\-_./+]{16,})["\']',
                ],
                "blacklist": [r'placeholder', r'your[_\-]?', r'<token>', r'process\.env'],
            },
        ],
        "config": [
            {
                "name": "Environment Config",
                "severity": "MEDIUM",
                "patterns": [r'(?:environment|config|appConfig)\s*=\s*(\{[^;]{30,1500}\})'],
            },
            {
                "name": "Database Connection String",
                "severity": "CRITICAL",
                "patterns": [
                    r'["\`]((?:mongodb|postgres|mysql|redis)://[^\s"\'`]{10,250})["\`]',
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
        ],
        "angular": [
            {
                "name": "Angular Route",
                "severity": "INFO",
                "patterns": [
                    r'path\s*:\s*["\']([^"\']{1,150})["\']',
                    r'loadChildren\s*:\s*["\']([^"\']{1,250})["\']',
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
        ],
        "debug": [
            {
                "name": "Console Log Leak",
                "severity": "LOW",
                "patterns": [
                    r'console\.(?:log|warn|error)\s*\([^)]{0,30}(?:password|token|secret|key)[^)]{0,100}\)',
                ],
            },
            {
                "name": "Debug Flag",
                "severity": "MEDIUM",
                "patterns": [
                    r'(?:debug|debugMode|DEV_MODE|disableAuth)\s*[=:]\s*true',
                ],
            },
            {
                "name": "Admin Panel Path",
                "severity": "HIGH",
                "patterns": [
                    r'["\`](/(?:admin|administrator|manage|superadmin|control-panel|swagger|api-docs)[/a-zA-Z0-9_\-]*)["\`]',
                ],
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
        self.seen = set()
        self._sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        
    def _sev_ok(self, sev: str) -> bool:
        return self._sev_order.index(sev) <= self._sev_order.index(self.min_severity)
    
    def _dedup(self, cat: str, val: str) -> str:
        return hashlib.md5(f"{cat}:{val[:80]}".encode()).hexdigest()
    
    def analyze_file(self, filepath: Path) -> List[Finding]:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            error(f"Cannot read {filepath}: {e}")
            return []
            
        lines = content.splitlines()
        findings = []
        
        for category, rule_list in self.RULES.items():
            for rule in rule_list:
                name = rule["name"]
                severity = rule["severity"]
                patterns = rule["patterns"]
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
                            
                            line_no = content[:m.start()].count("\n") + 1
                            ctx_s = max(0, line_no - 2)
                            ctx_e = min(len(lines), line_no + 1)
                            context = " | ".join(l.strip()[:120] for l in lines[ctx_s:ctx_e])
                            
                            findings.append(Finding(
                                category=category,
                                subcategory=name,
                                value=value[:600],
                                severity=severity,
                                file=filepath.name,
                                line=line_no,
                                context=context[:350],
                                tool=self.name
                            ))
                    except re.error:
                        continue
                        
        return findings


class TruffleHogExtractor(ExternalToolExtractor):
    """Integration with TruffleHog for deep secret scanning."""
    
    def __init__(self):
        super().__init__(
            tool_name="trufflehog",
            command_template=["trufflehog", "filesystem", "{file}", "--json", "--no-verification"],
            result_parser=self._parse_trufflehog_output
        )
    
    def _parse_trufflehog_output(self, output: str, filepath: Path) -> List[Finding]:
        findings = []
        for line in output.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                findings.append(Finding(
                    category="secrets",
                    subcategory=data.get("DetectorName", "Unknown Secret"),
                    value=data.get("Raw", ""),
                    severity="CRITICAL",
                    file=filepath.name,
                    line=data.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {}).get("line", 0),
                    context=data.get("RawV2", "")[:200],
                    tool="trufflehog",
                    confidence="HIGH" if data.get("Verified") else "MEDIUM"
                ))
            except json.JSONDecodeError:
                continue
        return findings


class RipgrepExtractor(ExternalToolExtractor):
    """Fast pattern matching using ripgrep."""
    
    def __init__(self, patterns_file: Optional[Path] = None):
        self.patterns_file = patterns_file
        super().__init__(
            tool_name="rg",
            command_template=self._build_command(),
            result_parser=self._parse_ripgrep_output
        )
    
    def _build_command(self):
        cmd = ["rg", "--json", "--hidden", "--no-heading"]
        if self.patterns_file:
            cmd.extend(["-f", str(self.patterns_file)])
        else:
            cmd.extend([
                "-e", "(api|v\\d|graphql|rest)/",
                "-e", "AKIA[0-9A-Z]{16}",
                "-e", "AIza[0-9A-Za-z\\-_]{35}",
            ])
        cmd.append("{file}")
        return cmd
    
    def _parse_ripgrep_output(self, output: str, filepath: Path) -> List[Finding]:
        findings = []
        for line in output.strip().split('\n'):
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match = data["data"]
                    text = match["lines"]["text"].strip()
                    findings.append(Finding(
                        category="pattern_match",
                        subcategory="ripgrep_hit",
                        value=text[:300],
                        severity="INFO",
                        file=filepath.name,
                        line=match["line_number"],
                        tool="ripgrep"
                    ))
            except:
                continue
        return findings


class ExtractorOrchestrator:
    """Manages multiple extractors and aggregates results."""
    
    def __init__(self):
        self.extractors: List[BaseExtractor] = []
        
    def register(self, extractor: BaseExtractor):
        self.extractors.append(extractor)
        info(f"Registered extractor: {extractor.name}")
        
    def analyze(self, dir_path: Path) -> List[Finding]:
        all_findings = []
        for ext in self.extractors:
            info(f"Running {ext.name}...")
            findings = ext.analyze_directory(dir_path)
            all_findings.extend(findings)
            success(f"  {ext.name}: {len(findings)} findings")
        return self._deduplicate(all_findings)
    
    def _deduplicate(self, findings: List[Finding]) -> List[Finding]:
        """Remove duplicate findings across tools."""
        seen = set()
        unique = []
        for f in findings:
            key = hashlib.md5(f"{f.category}:{f.subcategory}:{f.value[:50]}:{f.line}".encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — SOURCE MAP RECONSTRUCTOR
# ══════════════════════════════════════════════════════════════════════════════

class SourceMapReconstructor:
    """Handles extraction and reconstruction from source maps."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.src_dir = output_dir / "extracted_sources"
        
    def extract(self, chunks_dir: Path) -> Optional[Path]:
        """Extract embedded sourcesContent from .map files."""
        map_files = list(chunks_dir.rglob("*.map")) + list(chunks_dir.rglob("*.js.map"))
        if not map_files:
            warn("No .map files found for source extraction.")
            return None

        self.src_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        
        for mf in map_files:
            try:
                raw = json.loads(mf.read_text(encoding="utf-8", errors="ignore"))
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
                
        success(f"Extracted {total} source files → {self.src_dir}")
        return self.src_dir
    
    def _sanitize_path(self, path: str) -> str:
        """Sanitize source paths for filesystem safety."""
        safe = re.sub(r'^(webpack:///|webpack://|ng://|/\.\.)', '', path)
        safe = re.sub(r'\.\.\/', '_UP_/', safe)
        safe = re.sub(r'[<>:"|?*]', '_', safe)
        return safe.lstrip("/\\") or "source"
    
    def extract_strings(self, chunks_dir: Path) -> Dict:
        """Dump all discovered URLs, paths, and emails."""
        urls, paths, emails = [], [], []
        
        url_re = re.compile(r'https?://[^\s"\'`<>\)]{8,250}')
        path_re = re.compile(r'["\`](/[a-zA-Z0-9_/\-]{3,100})["\`]')
        email_re = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
        
        for f in chunks_dir.rglob("*.js"):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for m in url_re.finditer(content):
                    urls.append({"value": m.group(), "file": f.name})
                for m in path_re.finditer(content):
                    paths.append({"value": m.group(1), "file": f.name})
                for m in email_re.finditer(content):
                    emails.append({"value": m.group(), "file": f.name})
            except:
                pass
                
        # Deduplicate
        urls = list({v["value"]: v for v in urls}.values())
        paths = list({v["value"]: v for v in paths}.values())
        emails = list({v["value"]: v for v in emails}.values())
        
        result = {"urls": urls, "paths": paths, "emails": emails}
        out_path = self.output_dir / "all_strings.json"
        out_path.write_text(json.dumps(result, indent=2))
        success(f"Strings dump: {len(urls)} URLs · {len(paths)} paths · {len(emails)} emails")
        return result


# ══════════════════════════════════════════════════════════════════════════════
#  REPORTING MODULE
# ══════════════════════════════════════════════════════════════════════════════

class ReportGenerator:
    """Handles all report formatting and output."""
    
    SEV_ICON = {"CRITICAL": "💀", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
    SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    
    def __init__(self, findings: List[Finding]):
        self.findings = findings
        
    def print_console(self):
        """Print formatted report to console."""
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
                print(f"\n  {C.BOLD}{C.WHITE}{subcat}{C.RESET}  ({len(items)})")
                for item in items[:60]:
                    val = item.value[:130].replace("\n", " ")
                    tool_tag = f" [{item.tool}]" if item.tool != "native" else ""
                    print(f"  {C.GRAY}{item.file}:{item.line}{C.RESET}{C.CYAN}{tool_tag}{C.RESET}")
                    print(f"  {color}  →  {val}{C.RESET}")
                    
        self._print_summary(by_sev)
        
    def _print_summary(self, by_sev: dict):
        print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
        print(f"{C.BOLD}  FINDINGS SUMMARY{C.RESET}")
        print(f"{'─'*65}")
        for sev in self.SEV_ORDER:
            n = len(by_sev.get(sev, []))
            if not n:
                continue
            color = Finding(sev, "", "", sev, "", 0).sev_color()
            bar = "█" * min(n, 45)
            print(f"  {color}{sev:<12}{C.RESET}  {n:>4}  {C.GRAY}{bar}{C.RESET}")
        print(f"{'─'*65}")
        print(f"  {'Total':<12}  {len(self.findings):>4}")
        print(f"{'═'*65}\n")
        
    def save(self, out_path: Path, fmt: str = "json"):
        """Save report to file in specified format."""
        ext_map = {"json": ".json", "csv": ".csv", "md": ".md", "txt": ".txt", "html": ".html"}
        
        if fmt == "json":
            out_path.write_text(json.dumps([asdict(f) for f in self.findings], indent=2))
        elif fmt == "csv":
            self._save_csv(out_path)
        elif fmt == "md":
            self._save_markdown(out_path)
        elif fmt == "txt":
            self._save_text(out_path)
        elif fmt == "html":
            self._save_html(out_path)
            
        success(f"Report saved → {out_path}")
        
    def _save_csv(self, out_path: Path):
        import csv
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            fields = ["severity", "category", "subcategory", "value", "file", "line", "context", "tool"]
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for f in self.findings:
                d = asdict(f)
                d["tool"] = f.tool
                w.writerow(d)
                
    def _save_markdown(self, out_path: Path):
        ts = datetime.now().isoformat()
        md = [f"# jsmap-suite Report\n\n**Generated:** {ts}  \n**Total:** {len(self.findings)}\n"]
        
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
                    md.append(f"| `{item.file}` | {item.line} | {item.tool} | `{v}` |")
                md.append("")
        out_path.write_text("\n".join(md), encoding="utf-8")
        
    def _save_text(self, out_path: Path):
        lines = [f"jsmap-suite Report", f"Generated: {datetime.now()}", ""]
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
            "CRITICAL": "#ff3b30", "HIGH": "#ff6b35",
            "MEDIUM": "#ffcc00", "LOW": "#5ac8fa", "INFO": "#8e8e93",
        }
        rows = ""
        for f in self.findings:
            col = sev_colors.get(f.severity, "#888")
            v = f.value[:200].replace("<","&lt;").replace(">","&gt;")
            rows += f'<tr><td><span style="background:{col};padding:2px 6px;border-radius:3px;">{f.severity}</span></td><td>{f.subcategory}</td><td>{f.tool}</td><td>{f.file}:{f.line}</td><td><code>{v}</code></td></tr>'
            
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>jsmap-suite Report</title>
<style>body{{font-family:monospace;background:#0d0d0d;color:#e0e0e0;padding:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#1a1a1a;color:#aaa;padding:8px;text-align:left}}
td{{padding:6px 8px;border-bottom:1px solid #222}}
code{{color:#0f0;word-break:break-all}}</style></head>
<body><h1>⚡ jsmap-suite Report</h1>
<table><tr><th>Severity</th><th>Type</th><th>Tool</th><th>Location</th><th>Value</th></tr>
{rows}</table></body></html>"""
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
        description="jsmap-suite — Modular JS Recon Tool",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
EXAMPLES:
  Full recon with all extractors:
    python3 jsmap_suite.py https://app.target.com/ --all-extractors
    
  Use only external tools (trufflehog, ripgrep):
    python3 jsmap_suite.py https://app.target.com/ --use-trufflehog --use-ripgrep
    
  Analyze existing directory with specific tools:
    python3 jsmap_suite.py --analyze-only --dir ./chunks --use-trufflehog
    
  Download only:
    python3 jsmap_suite.py https://app.target.com/ --download-only
        """
    )

    parser.add_argument("url", nargs="?", default=None, help="Target URL")
    parser.add_argument("--download-only", action="store_true", help="Phase 1 only")
    parser.add_argument("--analyze-only", action="store_true", help="Phase 2 only")
    parser.add_argument("--dir", help="Directory to analyze (with --analyze-only)")
    
    # Extractor selection
    ext = parser.add_argument_group("Extractors")
    ext.add_argument("--all-extractors", action="store_true", help="Enable all available extractors")
    ext.add_argument("--use-trufflehog", action="store_true", help="Use TruffleHog for secrets")
    ext.add_argument("--use-ripgrep", action="store_true", help="Use ripgrep for fast pattern matching")
    ext.add_argument("--native-only", action="store_true", help="Use only native regex (default)")
    
    # Download options
    dl = parser.add_argument_group("Download")
    dl.add_argument("-m", "--map", help="JSON chunk map file")
    dl.add_argument("-t", "--threads", type=int, default=5)
    dl.add_argument("-d", "--delay", type=float, default=0.0)
    
    # Analysis options
    an = parser.add_argument_group("Analysis")
    an.add_argument("--severity", default="INFO", choices=["CRITICAL","HIGH","MEDIUM","LOW","INFO"])
    an.add_argument("--extract-sources", action="store_true")
    an.add_argument("--strings", action="store_true")
    an.add_argument("--no-print", action="store_true")
    
    # Output
    out = parser.add_argument_group("Output")
    out.add_argument("-o", "--output", help="Output directory")
    out.add_argument("--format", default="json", choices=["json","csv","md","txt","html"])
    
    # Network
    net = parser.add_argument_group("Network")
    net.add_argument("--proxy")
    net.add_argument("--no-verify", action="store_true")
    net.add_argument("--cookie")
    net.add_argument("-H", "--header", action="append", default=[])
    
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    banner()

    # Validation
    if not args.url and not args.analyze_only:
        parser.print_help()
        sys.exit(1)
    if args.analyze_only and not args.dir:
        error("--analyze-only requires --dir")
        sys.exit(1)

    # Setup paths
    if args.output:
        out_dir = Path(args.output)
    elif args.url:
        host = urlparse(args.url).netloc.replace(":", "_")
        out_dir = Path(f"jsmap_{host}_{datetime.now():%Y%m%d_%H%M%S}")
    else:
        out_dir = Path(f"jsmap_analysis_{datetime.now():%Y%m%d_%H%M%S}")
    out_dir.mkdir(parents=True, exist_ok=True)
    info(f"Output: {out_dir.resolve()}")

    # Phase 1: Download
    if not args.analyze_only:
        step(1, "DOWNLOADING CHUNKS")
        session = build_session(args)
        downloader = ChunkDownloader(session, args.url, args.threads, args.delay)
        
        chunk_map, special_names, extra_scripts = {}, {}, []
        if args.map:
            with open(args.map) as f:
                chunk_map = json.load(f)
        else:
            chunk_map, special_names, extra_scripts = downloader.auto_detect_chunks()
            
        chunks_dir = downloader.download_all(chunk_map, special_names, extra_scripts, out_dir / "chunks")
        
        if args.download_only:
            success("Download complete.")
            sys.exit(0)
    else:
        chunks_dir = Path(args.dir)

    # Phase 2: Extract/Analyze
    step(2, "EXTRACTING & ANALYZING")
    
    orchestrator = ExtractorOrchestrator()
    
    # Always add native extractor
    if not args.all_extractors and not args.use_trufflehog and not args.use_ripgrep:
        args.native_only = True
        
    orchestrator.register(NativeRegexExtractor(args.severity))
    
    # Add external tools if requested and available
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
    
    # Phase 3: Reconstruct
    if args.extract_sources:
        step(3, "RECONSTRUCTING SOURCES")
        recon = SourceMapReconstructor(out_dir)
        src_dir = recon.extract(chunks_dir)
        
        if src_dir:
            info("Re-analyzing extracted sources...")
            additional = orchestrator.analyze(src_dir)
            new_count = len([f for f in additional if f not in findings])
            if new_count:
                success(f"{new_count} additional findings in sources")
                findings = list({f.value[:50]+f.file: f for f in findings + additional}.values())
                
        if args.strings:
            recon.extract_strings(chunks_dir)

    # Reporting
    reporter = ReportGenerator(findings)
    if not args.no_print:
        reporter.print_console()
        
    ext_map = {"json": ".json", "csv": ".csv", "md": ".md", "txt": ".txt", "html": ".html"}
    rep_file = out_dir / f"findings{ext_map[args.format]}"
    reporter.save(rep_file, args.format)

    # Final summary
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  COMPLETE{C.RESET}")
    crits = sum(1 for f in findings if f.severity == "CRITICAL")
    highs = sum(1 for f in findings if f.severity == "HIGH")
    if crits:
        critical(f"{crits} CRITICAL findings!")
    if highs:
        warn(f"{highs} HIGH severity findings")
    print(f"  Total: {len(findings)} | Report: {rep_file}")


if __name__ == "__main__":
    main()

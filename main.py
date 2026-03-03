#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         Angular / Webpack Chunk Downloader               ║
║         by baba01hacker                                  ║
║         Tool: jsmap-dl | Phase 1 - Downloader            ║
╚══════════════════════════════════════════════════════════╝

Replicates Webpack runtime chunk resolution logic:
  - Reads chunk_id → hash map from runtime.js or manual input
  - Reconstructs filenames: [prefix].[hash].js
  - Downloads all chunks to disk for Phase 2 (extractor)
"""

import requests
import os
import re
import sys
import json
import argparse
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin


# ─── ANSI Colors ─────────────────────────────────────────────────────────────
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    CYAN    = "\033[36m"
    MAGENTA = "\033[35m"
    GRAY    = "\033[90m"
    BLUE    = "\033[34m"


def banner():
    print(f"""
{C.MAGENTA}{C.BOLD}
     ██╗███████╗███╗   ███╗ █████╗ ██████╗        ██████╗ ██╗
     ██║██╔════╝████╗ ████║██╔══██╗██╔══██╗       ██╔══██╗██║
     ██║███████╗██╔████╔██║███████║██████╔╝ █████╗██║  ██║██║
██   ██║╚════██║██║╚██╔╝██║██╔══██║██╔═══╝        ██║  ██║██║
╚█████╔╝███████║██║ ╚═╝ ██║██║  ██║██║            ██████╔╝███████╗
 ╚════╝ ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝            ╚═════╝ ╚══════╝
{C.RESET}{C.YELLOW}  Angular / Webpack Chunk Downloader  |  by baba01hacker{C.RESET}
{C.GRAY}  Phase 1: Chunk Fetch → Phase 2: Source Extraction{C.RESET}
""")


# ─── Logging helpers ──────────────────────────────────────────────────────────
def info(msg):    print(f"{C.CYAN}[*]{C.RESET} {msg}")
def success(msg): print(f"{C.GREEN}[+]{C.RESET} {msg}")
def warn(msg):    print(f"{C.YELLOW}[!]{C.RESET} {msg}")
def error(msg):   print(f"{C.RED}[-]{C.RESET} {msg}")
def data(msg):    print(f"{C.GRAY}    {msg}{C.RESET}")


# ─── Default headers (mimics real browser) ───────────────────────────────────
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
    "Referer":         "",   # will be set to base_url at runtime
}


# ─── Auto-extract chunk map from runtime.js ──────────────────────────────────
def extract_chunk_map_from_runtime(content: str) -> dict:
    """
    Parses Webpack runtime.js patterns:
      e.u = function(e) { return (76 === e ? "common" : e) + "." + {76:"094b5e...", 112:"f831.."}[e] + ".js" }
    Also handles newer Webpack 5 formats.
    """
    chunk_map = {}

    # Pattern 1: object literal  { "76":"094b5e", "112":"f831.." }
    # inside chunkId map function
    patterns = [
        # Webpack 4/5 style
        r'\{(\s*(?:"?\d+"?\s*:\s*"[a-f0-9]+"(?:\s*,\s*)?)+)\}',
    ]

    for pat in patterns:
        matches = re.findall(pat, content)
        for match in matches:
            pairs = re.findall(r'"?(\d+)"?\s*:\s*"([a-f0-9]{8,})"', match)
            if len(pairs) > 2:  # likely the chunk hash map, not a small config obj
                for chunk_id, chunk_hash in pairs:
                    chunk_map[chunk_id] = chunk_hash

    # Pattern 2: array/spread format (Webpack 5)
    #   (self.webpackChunk=self.webpackChunk||[]).push([[912],{...}])
    array_pat = re.findall(r'\[\s*(\d+)\s*,\s*"([a-f0-9]{8,})"', content)
    for chunk_id, chunk_hash in array_pat:
        chunk_map[chunk_id] = chunk_hash

    return chunk_map


# ─── Resolve chunk filename using Webpack runtime logic ──────────────────────
def resolve_chunk_filename(chunk_id: str, chunk_hash: str, special_names: dict = None) -> str:
    """
    Mirrors Webpack runtime:
      (chunkId === "76" ? "common" : chunkId) + "." + hash + ".js"
    special_names: optional {chunk_id: "name"} for named chunks
    """
    special_names = special_names or {}

    if chunk_id in special_names:
        prefix = special_names[chunk_id]
    else:
        prefix = chunk_id

    return f"{prefix}.{chunk_hash}.js"


# ─── Download a single chunk ──────────────────────────────────────────────────
def download_chunk(session: requests.Session, base_url: str, chunk_id: str,
                   chunk_hash: str, save_dir: Path, special_names: dict,
                   delay: float = 0.0) -> dict:

    filename = resolve_chunk_filename(chunk_id, chunk_hash, special_names)
    url      = urljoin(base_url, filename)
    save_path = save_dir / filename

    if save_path.exists():
        warn(f"Already exists, skipping: {filename}")
        return {"status": "skipped", "filename": filename, "chunk_id": chunk_id}

    if delay > 0:
        time.sleep(delay)

    try:
        resp = session.get(url, timeout=15)

        if resp.status_code == 200:
            save_path.write_text(resp.text, encoding="utf-8")
            size = len(resp.content)
            success(f"Downloaded: {filename} ({size:,} bytes)")
            return {"status": "ok", "filename": filename, "chunk_id": chunk_id, "size": size}

        elif resp.status_code == 404:
            error(f"Not found (404): {filename}")
            # Try alternate path (some apps serve from /assets/ or /static/)
            return {"status": "404", "filename": filename, "chunk_id": chunk_id}

        else:
            error(f"HTTP {resp.status_code}: {filename}")
            return {"status": f"http_{resp.status_code}", "filename": filename, "chunk_id": chunk_id}

    except requests.exceptions.ConnectionError:
        error(f"Connection error: {url}")
        return {"status": "conn_error", "filename": filename, "chunk_id": chunk_id}

    except requests.exceptions.Timeout:
        error(f"Timeout: {url}")
        return {"status": "timeout", "filename": filename, "chunk_id": chunk_id}

    except Exception as e:
        error(f"Unexpected error on {filename}: {e}")
        return {"status": "error", "filename": filename, "chunk_id": chunk_id}


# ─── Try to auto-detect chunk map from the target ────────────────────────────
def auto_detect(session: requests.Session, base_url: str) -> tuple[dict, dict]:
    """
    Attempts to:
    1. Fetch the index.html
    2. Find runtime.js / main.js references
    3. Extract chunk map from runtime.js
    Returns: (chunk_map, special_names)
    """
    chunk_map     = {}
    special_names = {}

    info("Auto-detect mode: fetching index.html...")

    try:
        resp = session.get(base_url, timeout=15)
        html = resp.text

        # Find all <script src="..."> references
        script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', html)
        info(f"Found {len(script_srcs)} script tags")

        # Angular / Webpack bundle names to prioritize
        priority_names = ["runtime", "main", "polyfills", "vendor", "scripts"]

        found_scripts = []
        for src in script_srcs:
            full_url = urljoin(base_url, src)
            found_scripts.append(full_url)
            data(f"Script: {src}")

        # Try to fetch runtime.js first (contains the hash map)
        runtime_url = None
        for url in found_scripts:
            if "runtime" in url.lower():
                runtime_url = url
                break

        # Fallback: try common Angular runtime filenames
        if not runtime_url:
            for name in ["runtime.js", "runtime.0000000000000000.js"]:
                test = urljoin(base_url, name)
                try:
                    r = session.get(test, timeout=5)
                    if r.status_code == 200 and "webpackChunk" in r.text:
                        runtime_url = test
                        break
                except:
                    pass

        if runtime_url:
            info(f"Fetching runtime: {runtime_url}")
            r = session.get(runtime_url, timeout=15)
            if r.status_code == 200:
                chunk_map = extract_chunk_map_from_runtime(r.text)
                if chunk_map:
                    success(f"Auto-extracted {len(chunk_map)} chunks from runtime.js")

                # Also extract named chunks  e.g. 76 === e ? "common" : e
                named = re.findall(r'(\d+)\s*===\s*\w+\s*\?\s*"([a-zA-Z0-9_-]+)"', r.text)
                for cid, cname in named:
                    special_names[cid] = cname
                    data(f"Named chunk: {cid} → {cname}")

    except Exception as e:
        warn(f"Auto-detect failed: {e}")

    return chunk_map, special_names


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Angular/Webpack Chunk Downloader by baba01hacker",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("url",              help="Target base URL (e.g. https://app.target.com/)")
    parser.add_argument("-o", "--output",   help="Output directory (default: auto-named)", default=None)
    parser.add_argument("-m", "--map",      help="Path to JSON file with chunk_map {id: hash}", default=None)
    parser.add_argument("-t", "--threads",  help="Concurrent download threads (default: 5)", type=int, default=5)
    parser.add_argument("-d", "--delay",    help="Delay between requests in seconds (default: 0)", type=float, default=0.0)
    parser.add_argument("--auto",           help="Auto-detect chunk map from runtime.js", action="store_true")
    parser.add_argument("--proxy",          help="HTTP proxy (e.g. http://127.0.0.1:8080)", default=None)
    parser.add_argument("--no-verify",      help="Disable SSL verification", action="store_true", dest="no_verify")

    args = parser.parse_args()

    banner()

    # ── Normalize base URL ───────────────────────────────────────────────────
    base_url = args.url.rstrip("/") + "/"

    # ── Output directory ─────────────────────────────────────────────────────
    from urllib.parse import urlparse
    host     = urlparse(base_url).netloc.replace(":", "_")
    out_dir  = Path(args.output) if args.output else Path(f"chunks_{host}")
    out_dir.mkdir(parents=True, exist_ok=True)
    info(f"Output directory: {out_dir.resolve()}")

    # ── Session setup ────────────────────────────────────────────────────────
    session = requests.Session()
    session.headers.update({**DEFAULT_HEADERS, "Referer": base_url})
    if args.proxy:
        session.proxies = {"http": args.proxy, "https": args.proxy}
        info(f"Proxy: {args.proxy}")
    if args.no_verify:
        session.verify = False
        import urllib3; urllib3.disable_warnings()
        warn("SSL verification disabled")

    # ── Load chunk map ───────────────────────────────────────────────────────
    chunk_map     = {}
    special_names = {}

    if args.map:
        # Load from JSON file
        with open(args.map, "r") as f:
            chunk_map = json.load(f)
        info(f"Loaded {len(chunk_map)} chunks from {args.map}")

    elif args.auto:
        chunk_map, special_names = auto_detect(session, base_url)
        if not chunk_map:
            error("Auto-detect found no chunks. Try manual --map flag.")
            sys.exit(1)

    else:
        # ── INLINE CHUNK MAP (edit this for quick runs) ──────────────────────
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
        # Angular names named chunk 76 → "common"
        special_names = {"76": "common"}
        info(f"Using inline chunk map: {len(chunk_map)} chunks")

    # Save chunk map for reference / Phase 2
    map_save = out_dir / "chunk_map.json"
    map_save.write_text(json.dumps(chunk_map, indent=2))
    data(f"Chunk map saved to: {map_save}")

    # ── Download ─────────────────────────────────────────────────────────────
    info(f"Starting download | threads={args.threads} | delay={args.delay}s")
    print()

    results   = []
    stats     = {"ok": 0, "skipped": 0, "failed": 0}

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {
            executor.submit(
                download_chunk,
                session, base_url, cid, chash,
                out_dir, special_names, args.delay
            ): cid
            for cid, chash in chunk_map.items()
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            if result["status"] == "ok":
                stats["ok"] += 1
            elif result["status"] == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(f"{C.BOLD}{'─'*55}{C.RESET}")
    print(f"{C.BOLD}  DOWNLOAD SUMMARY{C.RESET}")
    print(f"{'─'*55}")
    print(f"  {C.GREEN}Downloaded : {stats['ok']}{C.RESET}")
    print(f"  {C.YELLOW}Skipped    : {stats['skipped']}{C.RESET}")
    print(f"  {C.RED}Failed     : {stats['failed']}{C.RESET}")
    print(f"  Total      : {len(chunk_map)}")
    print(f"{'─'*55}")
    print(f"  Output dir : {out_dir.resolve()}")
    print(f"{'─'*55}")
    print()

    if stats["ok"] > 0:
        success(f"Phase 1 complete. Run the extractor on: {out_dir}/")
        info("Next → python3 jsmap_extractor.py --dir " + str(out_dir))

    # Save results log
    log_path = out_dir / "download_log.json"
    log_path.write_text(json.dumps(results, indent=2))
    data(f"Full log: {log_path}")


if __name__ == "__main__":
    main()

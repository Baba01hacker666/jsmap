import re
import json
import time
import random
import base64
import requests
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Dict, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.logger import C, info, success, warn, error, substep
from core.layout import OutputLayout

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

        # Modern Esbuild/Angular 17+ ternary expressions
        for m in re.finditer(r'(?:[a-zA-Z0-9_]+\s*===\s*(\d+)\s*\?\s*["\']([a-f0-9]{8,})["\'])', content):
            chunk_map[m.group(1)] = m.group(2)
        for m in re.finditer(r'(?:(\d+)\s*===\s*[a-zA-Z0-9_]+\s*\?\s*["\']([a-f0-9]{8,})["\'])', content):
            chunk_map[m.group(1)] = m.group(2)

        # Modern Esbuild/Angular 17+ array expressions
        for m in re.finditer(r'\[(\s*(?:["\'][a-f0-9]{8,}["\']\s*,\s*)+["\'][a-f0-9]{8,}["\']\s*)\]', content):
            hashes = re.findall(r'["\']([a-f0-9]{8,})["\']', m.group(1))
            if len(hashes) > 1:
                for idx, h in enumerate(hashes):
                    chunk_map[str(idx)] = h

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
            "_next/static/chunks/",
            "_next/static/chunks/pages/",
            "_nuxt/",
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
            # OPSEC: Add ±20% jitter to evade simple timing-based rate limits
            jitter = random.uniform(0.8, 1.2)
            time.sleep(self.delay * jitter)

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

            # Match .js and .mjs files from <script> and link[rel="modulepreload"] tags
            raw_srcs = re.findall(
                r'<(?:script|link)[^>]+(?:src|href)=["\']([^"\']+\.(?:js|mjs)[^"\']*)["\']', html
            )
            raw_srcs += re.findall(r'"([^"]*\.(?:js|mjs))"', html)
            
            # Next.js / Nuxt / Vite specific inline data and manifests
            next_data = re.search(r'__NEXT_DATA__\s*=\s*({.*?})</script>', html, re.DOTALL)
            if next_data:
                try:
                    data = json.loads(next_data.group(1))
                    build_id = data.get('buildId')
                    if build_id:
                        raw_srcs.append(f"/_next/static/{build_id}/_buildManifest.js")
                        raw_srcs.append(f"/_next/static/{build_id}/_ssgManifest.js")
                except Exception:
                    pass

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
                    if re.search(r"(?:runtime|manifest|webpack-)", u, re.IGNORECASE)
                ),
                None,
            )
            if not runtime_url:
                for g in [
                    "runtime.js",
                    "runtime.min.js",
                    "webpack-runtime.js",
                    "manifest.js",
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
            map_name = js_file.name + ".map"
            map_path_chunks = chunks_dir / map_name
            map_path_maps = self.layout.maps_dir / map_name

            if map_path_maps.exists():
                continue

            if ref_val.startswith("data:"):
                b64_match = re.search(r"data:application/json(?:;charset=[^;]+)?;base64,([a-zA-Z0-9+/=]+)", ref_val)
                if b64_match:
                    try:
                        b64_data = b64_match.group(1)
                        decoded = base64.b64decode(b64_data)
                        map_path_chunks.write_bytes(decoded)
                        map_path_maps.write_bytes(decoded)
                        map_count += 1
                    except Exception:
                        pass
                continue

            map_url = urljoin(self.base_url, ref_val)
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

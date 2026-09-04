import re
import json
import time
import random
import base64
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
import urllib.parse
from typing import List, Dict, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .logger import C, info, success, warn, error, substep
from .layout import OutputLayout

class ChunkDownloader:
    """Robust Webpack and modern frontend chunk downloader with structured output support."""

    KNOWN_SOURCE_EXTENSIONS = (
        ".js", ".mjs", ".cjs",
        ".ts", ".tsx", ".jsx",
        ".mts", ".cts", ".vue", ".svelte",
        ".map",
    )

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        layout: Optional[OutputLayout] = None,
        threads: int = 5,
        delay: float = 0.0,
        crawl_esm: bool = True,
        deep: bool = False,
        beautify: bool = True,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/") + "/"
        self.layout = layout
        self.threads = threads
        self.delay = delay
        self.crawl_esm = crawl_esm
        self.deep = deep
        self.beautify = beautify
        self.stats = {"ok": 0, "skipped": 0, "failed": 0}
        self._dl_log: List[Dict[str, Any]] = []
        self._file_urls: Dict[str, str] = {}

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

        # Webpack 5 chunk maps with string identifiers (e.g. {"vendors": "abcdef12", "main": "12345678"})
        for m in re.finditer(r'\{(\s*(?:"?[a-zA-Z0-9_\-]+"?\s*:\s*"[a-f0-9]{8,}"(?:\s*,\s*)?)+)\}', content):
            try:
                for cid, chash in re.findall(r'"?([a-zA-Z0-9_\-]+)"?\s*:\s*"([a-f0-9]{8,})"', m.group(1)):
                    chunk_map[cid] = chash
            except Exception:
                pass

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
                self._file_urls[filename] = url
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
                    alt_hit_url = getattr(alt, "url", urljoin(self.base_url, filename))
                    self._file_urls[filename] = alt_hit_url
                    self._dl_log.append(
                        {
                            "file": filename,
                            "url": alt_hit_url,
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

    def _is_cdn_or_vendor_script(self, url: str) -> bool:
        """Heuristic check to skip common CDN/vendor scripts that add noise."""
        blacklist = [
            r'ajax\.googleapis\.com',
            r'cdnjs\.cloudflare\.com',
            r'cdn\.jsdelivr\.net',
            r'unpkg\.com',
            r'code\.jquery\.com',
            r'stackpath\.bootstrapcdn\.com',
            r'use\.fontawesome\.com',
            r'www\.google-analytics\.com',
            r'www\.googletagmanager\.com',
            r'connect\.facebook\.net',
            r'js\.stripe\.com',
            r'cdn\.segment\.com',
            r'widget\.intercom\.io',
            r'cdn\.amplitude\.com',
            r'browser\.sentry-cdn\.com',
            r'cdn\.datadoghq-browser-agent\.com',
            r'polyfill\.io',
            r'recaptcha/api\.js'
        ]
        return any(re.search(b, url, re.IGNORECASE) for b in blacklist)

    def auto_detect_chunks(self) -> Tuple[dict, dict, list]:
        chunk_map, special_names, all_scripts = {}, {}, []

        path_lower = urlparse(self.base_url).path.lower()
        if any(path_lower.endswith(ext) for ext in self.KNOWN_SOURCE_EXTENSIONS):
            info(f"Auto-detect: target is direct asset -> {self.base_url}")
            return {}, {}, [self.base_url]

        info("Auto-detect: fetching index.html ...")
        try:
            resp = self.session.get(self.base_url, timeout=15)
            html = resp.text

            # Match .js, .mjs, .ts, .tsx, .jsx, .vue, .svelte from <script> and link[rel="modulepreload"] tags
            raw_srcs = re.findall(
                r'<(?:script|link)[^>]+(?:src|href)=["\']([^"\']+\.(?:js|mjs|cjs|ts|tsx|jsx|mts|cts|vue|svelte)[^"\']*)["\']',
                html,
                re.IGNORECASE,
            )
            # Match <script type="module" src="..."> (including Vite /src/main.tsx or paths without extension)
            raw_srcs += re.findall(
                r'<script[^>]+type=["\']module["\'][^>]+src=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE,
            )
            raw_srcs += re.findall(
                r'<script[^>]+src=["\']([^"\']+)["\'][^>]+type=["\']module["\']',
                html,
                re.IGNORECASE,
            )
            raw_srcs += re.findall(
                r'["\'](/[^"\']+\.(?:js|mjs|cjs|ts|tsx|jsx|mts|cts|vue|svelte))["\']',
                html,
                re.IGNORECASE,
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
                    if not self._is_cdn_or_vendor_script(full):
                        if full not in all_scripts:
                            all_scripts.append(full)
                except Exception:
                    pass

            # Next.js build manifest page chunks discovery
            for bm_url in list(all_scripts):
                if "_buildManifest.js" in bm_url:
                    try:
                        bm_r = self.session.get(bm_url, timeout=10)
                        if bm_r.status_code == 200:
                            for chunk_rel in re.findall(r'"(static/chunks/[^"]+\.js)"', bm_r.text):
                                full_c = urljoin(self.base_url, chunk_rel)
                                if full_c not in all_scripts:
                                    all_scripts.append(full_c)
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
                f"Downloading {len(extra_scripts)} detected script/source references"
            )
            for url in extra_scripts:
                parsed_u = urlparse(url)
                url_path = parsed_u.path.strip("/")
                fname = Path(url_path).name or "script.js"
                has_known_ext = any(fname.lower().endswith(ext) for ext in self.KNOWN_SOURCE_EXTENSIONS)
                if not has_known_ext:
                    fname += ".js"

                rel_parts = [p for p in Path(url_path).parts if p not in ("..", ".", "")]
                if len(rel_parts) > 1:
                    save_path = save_dir / Path(*rel_parts)
                else:
                    save_path = save_dir / fname

                save_path.parent.mkdir(parents=True, exist_ok=True)
                rel_key = str(save_path.relative_to(save_dir)).replace("\\", "/")
                self._file_urls[fname] = url
                self._file_urls[save_path.name] = url
                self._file_urls[rel_key] = url

                if save_path.exists():
                    results.append({"status": "skipped", "filename": rel_key})
                    continue
                try:
                    r = self.session.get(url, timeout=15)
                    if r.status_code == 200:
                        save_path.write_bytes(r.content)
                        success(f"  {rel_key}")
                        results.append({"status": "ok", "filename": rel_key})
                except Exception as e:
                    warn(f"  Failed {rel_key}: {e}")

        if self.deep:
            self.deep_crawl_lazy_chunks(save_dir)

        if self.crawl_esm:
            self.crawl_esm_imports(save_dir)

        self._fetch_sourcemaps(save_dir)

        self.stats["ok"] = sum(1 for r in results if r["status"] == "ok")
        self.stats["skipped"] = sum(
            1 for r in results if r["status"] == "skipped"
        )
        self.stats["failed"] = (
            len(results) - self.stats["ok"] - self.stats["skipped"]
        )

        # Write download log
        if self.layout:
            log_path = self.layout.log_path("download")
            log_path.write_text(
                json.dumps(self._dl_log, indent=2), encoding="utf-8"
            )
            info(f"Download log → {log_path}")

        if self.beautify:
            from .beautifier import beautify_directory
            beautified_count = beautify_directory(save_dir)
            if beautified_count > 0:
                success(f"Beautified {beautified_count} downloaded asset(s) for readability")

        self._print_dl_stats()
        return save_dir

    def extract_esm_specifiers(self, content: str) -> List[str]:
        """Extract local ES module import and export specifiers from code."""
        specifiers = set()
        # 1. Static import/export: import ... from "..." or import "..." or export ... from "..."
        for m in re.finditer(
            r'(?:import|export)\s+(?:(?:(?:\*|type|\{[^}]*\}|[\w\s,]+)\s+from\s+)?["\']([^"\']+)["\'])',
            content,
        ):
            specifiers.add(m.group(1))

        # 2. Dynamic import("...")
        for m in re.finditer(r'import\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
            specifiers.add(m.group(1))

        # 3. require("...")
        for m in re.finditer(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
            specifiers.add(m.group(1))

        results = []
        for s in specifiers:
            s = s.strip()
            if not s or s.startswith("data:") or s.startswith("blob:"):
                continue
            # We only crawl relative local paths or root-relative paths:
            # e.g. ./App.tsx, ../components/Header, /src/main.tsx
            # Skip bare external package names like "react", "@angular/core", "vue", "axios"
            if s.startswith(("./", "../", "/")) or s.startswith("http://") or s.startswith("https://"):
                results.append(s)
        return sorted(results)

    def crawl_esm_imports(
        self,
        chunks_dir: Path,
        max_depth: int = 10,
        max_files: int = 300,
    ) -> List[Path]:
        """Recursively crawl local ES module dependencies starting from downloaded files.

        Particularly effective when no .map file exists, but entrypoints like
        main.tsx, index.ts, App.jsx are directly linked (e.g. in Vite, Astro, Next.js dev mode).
        """
        downloaded_files: List[Path] = []
        visited_urls: Set[str] = set()

        initial_files = []
        for ext in self.KNOWN_SOURCE_EXTENSIONS:
            if ext != ".map":
                initial_files.extend(chunks_dir.rglob(f"*{ext}"))

        if not initial_files:
            return downloaded_files

        queue: List[Tuple[str, Path, int]] = []
        for f in initial_files:
            try:
                rel_str = str(f.relative_to(chunks_dir)).replace("\\", "/")
            except ValueError:
                rel_str = f.name
            orig_url = self._file_urls.get(rel_str) or self._file_urls.get(f.name)
            if not orig_url:
                orig_url = urljoin(self.base_url, rel_str)
            visited_urls.add(orig_url)
            queue.append((orig_url, f, 0))

        substep("Scanning downloaded files for ES Module import dependencies...")
        crawled_count = 0

        while queue and len(downloaded_files) < max_files:
            parent_url, parent_path, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            try:
                content = parent_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            specifiers = self.extract_esm_specifiers(content)
            for spec in specifiers:
                if len(downloaded_files) >= max_files:
                    break

                spec_clean = spec.split("?")[0].split("#")[0]
                has_ext = any(spec_clean.lower().endswith(ext) for ext in self.KNOWN_SOURCE_EXTENSIONS if ext != ".map")
                if has_ext:
                    candidates = [spec_clean]
                else:
                    candidates = [
                        spec_clean + ext
                        for ext in (
                            ".tsx", ".ts", ".jsx", ".js", ".mjs",
                            "/index.tsx", "/index.ts", "/index.jsx", "/index.js",
                            ".vue", ".svelte"
                        )
                    ]

                for cand in candidates:
                    target_url = urljoin(parent_url, cand)
                    if target_url in visited_urls:
                        continue
                    visited_urls.add(target_url)

                    try:
                        resp = self.session.get(target_url, timeout=8)
                        if resp.status_code == 200 and resp.content:
                            ct = resp.headers.get("content-type", "").lower()
                            resp_text = resp.text
                            # SPA fallback protection: ignore if server returned fallback index.html for non-html assets
                            if "text/html" in ct and not any(cand.endswith(x) for x in (".html", ".vue", ".svelte")):
                                if "<!doctype html" in resp_text[:120].lower() or "<html" in resp_text[:120].lower():
                                    continue

                            parsed_u = urlparse(target_url)
                            url_path = parsed_u.path.strip("/")
                            rel_parts = [p for p in Path(url_path).parts if p not in ("..", ".", "")]
                            if rel_parts:
                                dest_path = chunks_dir / Path(*rel_parts)
                            else:
                                dest_path = chunks_dir / Path(cand).name

                            dest_path.parent.mkdir(parents=True, exist_ok=True)
                            dest_path.write_bytes(resp.content)

                            rel_key = str(dest_path.relative_to(chunks_dir)).replace("\\", "/")
                            self._file_urls[dest_path.name] = target_url
                            self._file_urls[rel_key] = target_url

                            downloaded_files.append(dest_path)
                            crawled_count += 1
                            self.stats["ok"] += 1
                            self._dl_log.append({
                                "file": rel_key,
                                "url": target_url,
                                "bytes": len(resp.content),
                                "status": "crawled_esm"
                            })
                            success(f"  [ESM module] {rel_key} ({len(resp.content):,} bytes)")

                            # Enqueue newly downloaded module to crawl its imports
                            queue.append((target_url, dest_path, depth + 1))
                            break
                    except Exception:
                        pass

        if crawled_count > 0:
            success(f"Discovered and crawled {crawled_count} ES module source file(s) via import graph")
        return downloaded_files

    def deep_crawl_lazy_chunks(
        self,
        chunks_dir: Path,
        max_rounds: int = 3,
    ) -> List[Path]:
        """Deeply inspect downloaded chunks for lazy-loaded modules, dynamic imports, and asset maps.

        Fetches any discovered secondary chunks and probes for their sourcemaps.
        """
        substep("Deep scan: inspecting chunk content for lazy-loaded modules and dynamic imports...")
        discovered_all: List[Path] = []
        known_files: Set[str] = {f.name for f in chunks_dir.rglob("*") if f.is_file()}
        visited_urls: Set[str] = set(self._file_urls.values())

        patterns = [
            # 1. Dynamic import in compiled code: import("./assets/...") or import("/assets/...")
            r'import\s*\(\s*["\']([^"\'\)]+\.(?:js|mjs))["\']\s*\)',
            # 2. Vite preload helper chunk call: __vitePreload(() => import("..."))
            r'__vitePreload\s*\(\s*\(\)\s*=>\s*import\s*\(\s*["\']([^"\'\)]+)["\']\s*\)',
            # 3. Quoted assets path: "assets/xxxx.js" or "/assets/xxxx.js"
            r'["\'](?:/)?(assets\/[a-zA-Z0-9_\-]+\.(?:js|mjs))["\']',
            # 4. Rollup/Vite hashed chunks: "ChunkName-abcdef12.js"
            r'["\']([a-zA-Z0-9_\-]+\-[a-zA-Z0-9_\-]{8,}\.(?:js|mjs))["\']',
            # 5. Next.js / Webpack static chunks: "static/chunks/xxxx.js"
            r'["\'](?:/_next/)?(static\/chunks\/[a-zA-Z0-9_\-\.\/]+\.js)["\']',
            # 6. Relative scripts: "./components/xxxx.js"
            r'["\'](\.?\/[a-zA-Z0-9_\-\.\/]+\.(?:js|mjs))["\']',
        ]

        for round_idx in range(max_rounds):
            new_urls = []
            for js_file in list(chunks_dir.rglob("*.js")) + list(chunks_dir.rglob("*.mjs")):
                try:
                    text = js_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                for pat in patterns:
                    for m in re.finditer(pat, text):
                        rel = m.group(1).strip().lstrip("/")
                        if not rel or "node_modules" in rel or rel.startswith("http") or len(rel) > 200:
                            continue

                        rel_clean = rel.split("?")[0].split("#")[0]
                        orig_url = self._file_urls.get(str(js_file.relative_to(chunks_dir))) or self._file_urls.get(js_file.name, self.base_url)
                        candidates = [
                            urljoin(orig_url, rel_clean),
                            urljoin(self.base_url, rel_clean),
                            urljoin(self.base_url, "assets/" + Path(rel_clean).name),
                        ]
                        for u in candidates:
                            if u not in visited_urls and not self._is_cdn_or_vendor_script(u):
                                visited_urls.add(u)
                                new_urls.append((u, rel_clean))

            if not new_urls:
                break

            round_new = 0
            for u, rel_hint in new_urls:
                fname = Path(rel_hint).name
                if fname in known_files:
                    continue

                try:
                    r = self.session.get(u, timeout=10)
                    if r.status_code == 200 and len(r.content) > 20:
                        ct = r.headers.get("content-type", "").lower()
                        if "text/html" in ct and ("<html" in r.text[:120].lower() or "<!doctype" in r.text[:120].lower()):
                            continue

                        parsed_u = urlparse(u)
                        url_path = parsed_u.path.strip("/")
                        rel_parts = [p for p in Path(url_path).parts if p not in ("..", ".", "")]
                        if len(rel_parts) > 1:
                            save_path = chunks_dir / Path(*rel_parts)
                        else:
                            save_path = chunks_dir / fname

                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        save_path.write_bytes(r.content)
                        rel_key = str(save_path.relative_to(chunks_dir)).replace("\\", "/")
                        self._file_urls[fname] = u
                        self._file_urls[save_path.name] = u
                        self._file_urls[rel_key] = u

                        known_files.add(fname)
                        discovered_all.append(save_path)
                        round_new += 1
                        self.stats["ok"] += 1
                        self._dl_log.append({
                            "file": rel_key,
                            "url": u,
                            "bytes": len(r.content),
                            "status": "deep_lazy_chunk"
                        })
                        success(f"  [Deep Lazy Chunk] {rel_key} ({len(r.content):,} bytes)")
                except Exception:
                    pass

            if round_new == 0:
                break

        if discovered_all:
            success(f"Deep discovery found {len(discovered_all)} lazy-loaded chunk(s)")
            self._fetch_sourcemaps(chunks_dir)
        else:
            info("Deep discovery: no additional lazy-loaded chunks found")

        return discovered_all

    def _fetch_sourcemaps(self, chunks_dir: Path):
        """Fetch .map files referenced in JS and source files; move them to maps_dir."""
        map_count = 0
        ref_re = re.compile(r"(?://|/\*)[#@]\s*sourceMappingURL=([^\s*]+)(?:\s*\*\/)?")
        candidate_files = []
        for ext in ("*.js", "*.mjs", "*.cjs", "*.ts", "*.tsx", "*.jsx"):
            candidate_files.extend(chunks_dir.rglob(ext))

        has_maps_dir = (
            self.layout is not None
            and hasattr(self.layout, "maps_dir")
            and isinstance(self.layout.maps_dir, Path)
        )

        for js_file in candidate_files:
            content = js_file.read_text(encoding="utf-8", errors="ignore")
            map_ref = ref_re.search(content)
            if not map_ref:
                continue
            ref_val = map_ref.group(1).strip()
            map_name = js_file.name + ".map"
            map_path_chunks = chunks_dir / map_name
            map_path_maps = (self.layout.maps_dir / map_name) if has_maps_dir else None

            if (map_path_maps and map_path_maps.exists()) or map_path_chunks.exists():
                continue

            if ref_val.startswith("data:"):
                b64_match = re.search(r"data:application/json(?:;charset=[^;]+)?;base64,([a-zA-Z0-9+/=]+)", ref_val)
                if b64_match:
                    try:
                        decoded = base64.b64decode(b64_match.group(1))
                        map_path_chunks.write_bytes(decoded)
                        if map_path_maps:
                            map_path_maps.write_bytes(decoded)
                        map_count += 1
                        continue
                    except Exception:
                        pass
                urlenc_match = re.search(r"data:application/json(?:;charset=[^;]+)?,([^\s*]+)", ref_val)
                if urlenc_match:
                    try:
                        decoded = urllib.parse.unquote(urlenc_match.group(1)).encode("utf-8")
                        map_path_chunks.write_bytes(decoded)
                        if map_path_maps:
                            map_path_maps.write_bytes(decoded)
                        map_count += 1
                        continue
                    except Exception:
                        pass
                continue

            rel_key = str(js_file.relative_to(chunks_dir)).replace("\\", "/")
            orig_url = self._file_urls.get(rel_key) or self._file_urls.get(js_file.name, self.base_url)
            candidate_urls = [
                urljoin(orig_url, ref_val),
                urljoin(self.base_url, ref_val),
                urljoin(self.base_url, js_file.name + ".map"),
            ]
            saved = False
            for map_url in candidate_urls:
                try:
                    mr = self.session.get(map_url, timeout=10)
                    if mr.status_code == 200 and ("\"sources\"" in mr.text or "\"sections\"" in mr.text):
                        map_path_chunks.write_bytes(mr.content)
                        if map_path_maps:
                            map_path_maps.write_bytes(mr.content)
                        map_count += 1
                        saved = True
                        break
                except Exception:
                    pass

            if not saved:
                alt = self.try_alternate_paths(js_file.name + ".map")
                if alt and ("\"sources\"" in alt.text or "\"sections\"" in alt.text):
                    map_path_chunks.write_bytes(alt.content)
                    if map_path_maps:
                        map_path_maps.write_bytes(alt.content)
                    map_count += 1

        if map_count:
            success(f"Downloaded {map_count} source map files → maps/")

    def _print_dl_stats(self):
        print(
            f"\n  {C.BOLD}Download Stats:{C.RESET}  "
            f"{C.GREEN}OK: {self.stats['ok']}{C.RESET}  "
            f"{C.GRAY}Skipped: {self.stats['skipped']}{C.RESET}  "
            f"{C.RED}Failed: {self.stats['failed']}{C.RESET}\n"
        )

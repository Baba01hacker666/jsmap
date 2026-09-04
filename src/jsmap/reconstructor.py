import base64
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .layout import OutputLayout
from .logger import info, success, warn


@dataclass
class ReconstructionResult:
    """Detailed result of source map reconstruction."""

    sources_directory: Optional[Path]
    extracted_files: Dict[str, Path] = field(default_factory=dict)
    total_files: int = 0
    source_maps_processed: int = 0
    skipped_sources: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.total_files > 0 and self.sources_directory is not None

    def __fspath__(self) -> str:
        return str(self.sources_directory or "")

    def __str__(self) -> str:
        return str(self.sources_directory or "")


class SourceMapReconstructor:
    """Extract and recover original source files from JavaScript source maps (.map)

    and JavaScript bundles with inline or external source maps.
    """

    INLINE_SOURCEMAP_REGEX = re.compile(
        r"(?://|/\*)[#@]\s*sourceMappingURL=data:application/json(?:;charset=[^;]+)?;base64,([a-zA-Z0-9+/=]+)(?:\s*\*\/)?",
        re.MULTILINE,
    )
    INLINE_URLENCODED_SOURCEMAP_REGEX = re.compile(
        r"(?://|/\*)[#@]\s*sourceMappingURL=data:application/json(?:;charset=[^;]+)?,([^\s*]+)(?:\s*\*\/)?",
        re.MULTILINE,
    )
    SOURCEMAP_REF_REGEX = re.compile(
        r"(?://|/\*)[#@]\s*sourceMappingURL=([^\s*]+)(?:\s*\*\/)?",
        re.MULTILINE,
    )

    def __init__(
        self,
        layout: Optional[OutputLayout] = None,
        output_dir: Optional[Union[str, Path]] = None,
        session: Optional[Any] = None,
        base_url: Optional[str] = None,
        beautify: bool = True,
        debundle: bool = True,
    ):
        self.layout = layout
        if layout is not None:
            self.src_dir = layout.sources_dir
        elif output_dir is not None:
            self.src_dir = Path(output_dir).expanduser().resolve()
        else:
            self.src_dir = Path("extracted_sources").resolve()
        self.session = session
        self.base_url = base_url
        self.beautify = beautify
        self.debundle = debundle
        self.last_result: Optional[ReconstructionResult] = None

    def extract(self, target: Union[str, Path, List[Union[str, Path]]]) -> Optional[Path]:
        """Extract source files from a directory, a single file, or a list of files.

        Returns the sources directory if files were extracted, or None.
        """
        result = self.reconstruct(target)
        self.last_result = result
        if result.total_files > 0:
            return self.src_dir
        return None

    def reconstruct(
        self,
        target: Union[str, Path, List[Union[str, Path]], dict],
    ) -> ReconstructionResult:
        """Reconstruct source trees from .map files or .js files containing sourcemaps.

        Returns a detailed ReconstructionResult.
        """
        self.src_dir.mkdir(parents=True, exist_ok=True)
        result = ReconstructionResult(sources_directory=self.src_dir)

        # Case 1: parsed dict passed directly
        if isinstance(target, dict):
            self._process_map_dict(target, "<memory>", result)
            return result

        map_sources: List[Tuple[str, Any]] = []

        targets = target if isinstance(target, list) else [target]
        seen_real_paths: Set[str] = set()

        for t in targets:
            p = Path(t).expanduser().resolve()
            if not p.exists():
                if isinstance(t, str) and (t.strip().startswith("{") or "sourceMappingURL=" in t):
                    map_sources.append(("<raw_string>", t))
                else:
                    result.errors.append(f"Target does not exist: {t}")
                continue

            if p.is_file():
                resolved = str(p.resolve())
                if resolved not in seen_real_paths:
                    seen_real_paths.add(resolved)
                    map_sources.append((p.name, p))
            elif p.is_dir():
                for mf in sorted(p.rglob("*.map")):
                    resolved = str(mf.resolve())
                    if resolved not in seen_real_paths:
                        seen_real_paths.add(resolved)
                        map_sources.append((mf.name, mf))

                if self.layout and self.layout.maps_dir.exists() and self.layout.maps_dir.resolve() != p.resolve():
                    for mf in sorted(self.layout.maps_dir.glob("*.map")):
                        resolved = str(mf.resolve())
                        if resolved not in seen_real_paths:
                            seen_real_paths.add(resolved)
                            map_sources.append((mf.name, mf))

                for jf in sorted(p.rglob("*.js")) + sorted(p.rglob("*.mjs")) + sorted(p.rglob("*.cjs")):
                    resolved = str(jf.resolve())
                    if resolved not in seen_real_paths:
                        seen_real_paths.add(resolved)
                        map_sources.append((jf.name, jf))

                # Also ingest directly linked/crawled original source files (.tsx, .ts, .jsx, .vue, .svelte)
                for ext in ("*.tsx", "*.ts", "*.jsx", "*.vue", "*.svelte"):
                    for sf in sorted(p.rglob(ext)):
                        resolved = str(sf.resolve())
                        if resolved not in seen_real_paths:
                            seen_real_paths.add(resolved)
                            map_sources.append((sf.name, sf))

        if not map_sources:
            warn("No .map, .js, or source files found for source extraction.")
            return result

        for origin_name, item in map_sources:
            try:
                self._process_item(origin_name, item, result)
            except Exception as e:
                err = f"Extraction error on {origin_name}: {e}"
                warn(err)
                result.errors.append(err)

        if result.total_files > 0:
            success(
                f"Extracted {result.total_files} source files from "
                f"{result.source_maps_processed} source map(s) → {self.src_dir.name}/"
            )
        elif self.debundle:
            warn("No source maps found. Automatically running debundler & beautification fallback...")
            from .debundler import debundle_file
            chunks_to_debundle: List[Path] = []
            if self.layout and self.layout.chunks_dir.exists():
                chunks_to_debundle.extend(sorted(self.layout.chunks_dir.rglob("*.js")))
                chunks_to_debundle.extend(sorted(self.layout.chunks_dir.rglob("*.mjs")))
            else:
                for origin_name, item in map_sources:
                    if isinstance(item, Path) and item.suffix.lower() in (".js", ".mjs", ".cjs"):
                        chunks_to_debundle.append(item)

            if chunks_to_debundle:
                for chunk in chunks_to_debundle:
                    try:
                        res = debundle_file(chunk, self.src_dir, beautify=self.beautify)
                        result.total_files += res.total_modules
                        result.extracted_files.update(res.extracted_files)
                    except Exception as e:
                        result.errors.append(f"Debundle failed on {chunk.name}: {e}")

                if result.total_files > 0:
                    success(
                        f"Extracted and beautified {result.total_files} module(s)/chunk(s) with architecture blueprint → {self.src_dir.name}/"
                    )
            else:
                warn("No JavaScript chunks found to debundle.")
        else:
            warn("No source files could be extracted from provided inputs.")

        return result

    def _process_item(
        self,
        origin_name: str,
        item: Union[Path, str],
        result: ReconstructionResult,
    ) -> None:
        if isinstance(item, str):
            content = item
            file_path = None
        else:
            file_path = item
            content = item.read_text(encoding="utf-8", errors="ignore")

        # 1. Direct source files (.tsx, .ts, .jsx, etc.) when no .map file exists
        if file_path is not None and file_path.suffix.lower() in {".tsx", ".ts", ".jsx", ".vue", ".svelte"}:
            try:
                if self.layout and file_path.is_relative_to(self.layout.chunks_dir):
                    rel_path = file_path.relative_to(self.layout.chunks_dir)
                else:
                    rel_path = Path(file_path.name)
                safe_rel = self._sanitize_path(str(rel_path))
                dest = self._safe_write_file(safe_rel, content)
                result.extracted_files[safe_rel] = dest
                result.total_files += 1
                return
            except Exception as e:
                result.errors.append(f"Failed ingesting direct source {origin_name}: {e}")
                return

        # 2. Raw JSON sourcemap string or file
        stripped = content.strip()
        if stripped.startswith("{") and ("\"sources\"" in stripped or "\"sections\"" in stripped):
            try:
                raw_map = json.loads(content)
                self._process_map_dict(raw_map, origin_name, result)
                return
            except json.JSONDecodeError:
                pass

        # 3. Webpack devtool: 'eval' / 'eval-source-map' blocks containing //# sourceURL=...
        self._extract_eval_modules(content, origin_name, result)

        # 4. Inline Base64 sourcemaps
        inline_found = False
        for m in self.INLINE_SOURCEMAP_REGEX.finditer(content):
            try:
                decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="ignore")
                raw_map = json.loads(decoded)
                self._process_map_dict(raw_map, f"{origin_name}[inline-base64]", result)
                inline_found = True
            except Exception as e:
                result.errors.append(f"Failed decoding inline base64 sourcemap in {origin_name}: {e}")

        # 5. Inline URL-encoded sourcemaps
        for m in self.INLINE_URLENCODED_SOURCEMAP_REGEX.finditer(content):
            try:
                decoded = urllib.parse.unquote(m.group(1))
                raw_map = json.loads(decoded)
                self._process_map_dict(raw_map, f"{origin_name}[inline-url]", result)
                inline_found = True
            except Exception as e:
                result.errors.append(f"Failed decoding inline urlencoded sourcemap in {origin_name}: {e}")

        # 6. Referenced sourcemap file on disk
        if not inline_found and file_path is not None:
            ref_match = self.SOURCEMAP_REF_REGEX.search(content)
            if ref_match:
                ref = ref_match.group(1).strip()
                if not ref.startswith("data:"):
                    candidate = (file_path.parent / ref).resolve()
                    if candidate.is_file() and candidate.exists():
                        try:
                            raw_map = json.loads(candidate.read_text(encoding="utf-8", errors="ignore"))
                            self._process_map_dict(raw_map, candidate.name, result)
                        except Exception as e:
                            result.errors.append(f"Failed reading referenced map {candidate.name}: {e}")

    def _extract_eval_modules(
        self,
        content: str,
        origin_name: str,
        result: ReconstructionResult,
    ) -> int:
        """Extract source files from eval("... //# sourceURL=...") blocks commonly used in

        Webpack (devtool: 'eval' / 'eval-source-map') and Vite/Rollup dev builds.
        """
        if "sourceURL=" not in content and "sourceMappingURL=" not in content:
            return 0

        extracted = 0
        eval_pattern = re.compile(
            r'eval\s*\(\s*(?:\"((?:[^\"\\]|\\.)*)\"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`)\s*\)',
            re.DOTALL,
        )
        for m in eval_pattern.finditer(content):
            code_str = m.group(1) or m.group(2) or m.group(3) or ""
            if "sourceURL=" not in code_str and "sourceMappingURL=" not in code_str:
                continue

            # Check for inline sourcemap inside the eval block
            inline_m = self.INLINE_SOURCEMAP_REGEX.search(code_str)
            if inline_m:
                try:
                    decoded = base64.b64decode(inline_m.group(1)).decode("utf-8", errors="ignore")
                    raw_map = json.loads(decoded)
                    self._process_map_dict(raw_map, f"{origin_name}[eval-inline-map]", result)
                    extracted += 1
                    continue
                except Exception:
                    pass

            surl_m = re.search(r'(?://|/\*)[#@]\s*sourceURL=([^\s*\'"\\]+)', code_str)
            if surl_m:
                src_path = surl_m.group(1).strip()
                unescaped = (
                    code_str.replace(r"\n", "\n")
                    .replace(r"\r", "\r")
                    .replace(r"\t", "\t")
                    .replace(r'\"', '"')
                    .replace(r"\'", "'")
                    .replace(r"\\", "\\")
                )
                unescaped = re.sub(r'(?://|/\*)[#@]\s*sourceURL=[^\n\r*]+(?:\*\/)?', '', unescaped).rstrip()
                safe_rel = self._sanitize_path(src_path)
                dest_file = self._safe_write_file(safe_rel, unescaped)
                result.extracted_files[safe_rel] = dest_file
                result.total_files += 1
                extracted += 1

        if extracted > 0:
            result.source_maps_processed += 1
            success(f"Extracted {extracted} source module(s) from eval() blocks in {origin_name}")
        return extracted

    def _process_map_dict(
        self,
        raw_map: dict,
        origin_name: str,
        result: ReconstructionResult,
    ) -> None:
        entries = self._collect_map_entries(raw_map)
        if not entries:
            return

        result.source_maps_processed += 1
        for src_path, src_content in entries:
            if not src_path:
                continue
            if src_content is None or src_content == "":
                fetched_content = None
                if self.session and self.base_url:
                    safe_candidate = self._sanitize_path(src_path)
                    candidate_urls = [
                        urllib.parse.urljoin(self.base_url, src_path),
                        urllib.parse.urljoin(self.base_url, safe_candidate),
                        urllib.parse.urljoin(self.base_url, "src/" + safe_candidate.lstrip("/")),
                    ]
                    for u in candidate_urls:
                        try:
                            r = self.session.get(u, timeout=5)
                            if r.status_code == 200 and r.text:
                                if not (r.text.strip().lower().startswith("<!doctype html") or r.text.strip().lower().startswith("<html")):
                                    fetched_content = r.text
                                    break
                        except Exception:
                            pass

                if fetched_content is not None:
                    src_content = fetched_content
                else:
                    result.skipped_sources.append(src_path)
                    continue

            safe_rel = self._sanitize_path(src_path)
            dest_file = self._safe_write_file(safe_rel, src_content)
            result.extracted_files[safe_rel] = dest_file
            result.total_files += 1

    def _collect_map_entries(
        self,
        map_data: dict,
        base_source_root: str = "",
    ) -> List[Tuple[str, Optional[str]]]:
        entries: List[Tuple[str, Optional[str]]] = []

        sections = map_data.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict):
                    sub_map = section.get("map")
                    if isinstance(sub_map, dict):
                        entries.extend(self._collect_map_entries(sub_map, base_source_root))

        sources = map_data.get("sources", [])
        sources_content = map_data.get("sourcesContent", [])
        source_root = map_data.get("sourceRoot") or base_source_root or ""

        if not isinstance(sources, list):
            return entries

        for i, src in enumerate(sources):
            if not src or not isinstance(src, str):
                continue
            full_src = f"{source_root.rstrip('/')}/{src.lstrip('/')}" if source_root else src
            content = sources_content[i] if (isinstance(sources_content, list) and i < len(sources_content)) else None
            entries.append((full_src, content))

        return entries

    def _sanitize_path(self, path: str) -> str:
        if not path:
            return "source"

        if "!" in path:
            path = path.rsplit("!", 1)[-1]

        prefixes = [
            r"^webpack:///+",
            r"^webpack-internal:///+",
            r"^webpack://[^/]+/+",
            r"^webpack://+",
            r"^turbopack:///[^/]+/+",
            r"^turbopack://+",
            r"^ng://+",
            r"^vite://+",
            r"^rollup://+",
            r"^file:///[a-zA-Z]:/+",
            r"^file:///+",
            r"^file://+",
            r"^https?://[^/]+/+",
            r"^\([^\)]+\)/+",
            r"^~/",
        ]
        for pat in prefixes:
            path = re.sub(pat, "", path)

        path = path.split("?")[0].split("#")[0]
        path = re.sub(r"\.\.[/\\]+", "_UP_/", path)
        path = re.sub(r"^\.[/\\]+", "", path)
        path = re.sub(r'[<>:"|?*\x00-\x1f]', "_", path)
        return path.lstrip("/\\") or "source"

    def _safe_write_file(self, rel_path: str, content: str) -> Path:
        norm_rel = rel_path.replace("\\", "/").strip("/")
        norm_rel = re.sub(r"/+", "/", norm_rel)
        dest = (self.src_dir / norm_rel).resolve()
        target_root = self.src_dir.resolve()

        if not dest.is_relative_to(target_root):
            cleaned = re.sub(r"^[./\\]+", "", norm_rel)
            dest = (target_root / cleaned).resolve()
            if not dest.is_relative_to(target_root):
                dest = target_root / "_safe" / Path(norm_rel).name

        try:
            rel_parts = dest.relative_to(target_root).parts
        except ValueError:
            rel_parts = Path(dest.name).parts
            dest = target_root / dest.name

        current = target_root
        for part in rel_parts[:-1]:
            current = current / part
            if current.is_file():
                backup_name = current.name + ".module"
                backup_path = current.with_name(backup_name)
                current.rename(backup_path)
            current.mkdir(parents=True, exist_ok=True)

        if dest.is_dir():
            dest = dest / "_module_index"

        if self.beautify:
            ext = dest.suffix.lstrip(".")
            if ext in ("js", "mjs", "cjs", "jsx", "ts", "tsx", "css", "html"):
                from .beautifier import beautify_code
                try:
                    content = beautify_code(content, file_type=ext)
                except Exception:
                    pass

        dest.write_text(content, encoding="utf-8", errors="replace")
        return dest

    def extract_strings(self, target: Union[str, Path]) -> Dict[str, List[dict]]:
        urls, paths, emails, ips = [], [], [], []
        url_re = re.compile(r'https?://[^\s"\'`<>\)]{8,250}')
        path_re = re.compile(r'["\`](/[a-zA-Z0-9_/\-]{3,100})["\`]')
        email_re = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
        ip_re = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

        p = Path(target).expanduser().resolve()
        files_to_scan: List[Path] = []
        if p.is_file():
            files_to_scan.append(p)
        elif p.is_dir():
            for ext in ("*.js", "*.mjs", "*.ts", "*.jsx", "*.tsx"):
                files_to_scan.extend(p.rglob(ext))

        for f in files_to_scan:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for m in url_re.finditer(content):
                    urls.append({"value": m.group(), "file": f.name})
                for m in path_re.finditer(content):
                    paths.append({"value": m.group(1), "file": f.name})
                for m in email_re.finditer(content):
                    emails.append({"value": m.group(), "file": f.name})
                for m in ip_re.finditer(content):
                    ip_val = m.group()
                    if not ip_val.startswith("0.") and not ip_val.startswith("127."):
                        ips.append({"value": ip_val, "file": f.name})
            except Exception:
                pass

        urls = list({v["value"]: v for v in urls}.values())
        paths = list({v["value"]: v for v in paths}.values())
        emails = list({v["value"]: v for v in emails}.values())
        ips = list({v["value"]: v for v in ips}.values())

        result = {"urls": urls, "paths": paths, "emails": emails, "ips": ips}

        if self.layout and self.layout.reports_dir.exists():
            out_path = self.layout.reports_dir / "all_strings.json"
            out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            success(
                f"Strings dump: {len(urls)} URLs · {len(paths)} paths · {len(emails)} emails → reports/all_strings.json"
            )
        return result


def unpack_sourcemap_to_dict(
    sourcemap: Union[str, Path, dict],
    source_root: Optional[str] = None,
) -> Dict[str, str]:
    """In-memory sourcemap unpacker.

    Returns a dictionary mapping sanitized relative source paths to source content.
    Does not require writing to disk.
    """
    raw_map: dict
    if isinstance(sourcemap, dict):
        raw_map = sourcemap
    elif isinstance(sourcemap, Path) or (isinstance(sourcemap, str) and not sourcemap.strip().startswith("{")):
        p = Path(sourcemap).expanduser().resolve()
        if p.is_file():
            content = p.read_text(encoding="utf-8", errors="ignore")
            match = SourceMapReconstructor.INLINE_SOURCEMAP_REGEX.search(content)
            if match:
                raw_map = json.loads(base64.b64decode(match.group(1)).decode("utf-8", errors="ignore"))
            else:
                raw_map = json.loads(content)
        else:
            raise ValueError(f"Source map file not found: {sourcemap}")
    else:
        raw_map = json.loads(sourcemap)

    recon = SourceMapReconstructor()
    entries = recon._collect_map_entries(raw_map, source_root or "")
    result: Dict[str, str] = {}
    for src_path, src_content in entries:
        if src_path and src_content is not None:
            safe = recon._sanitize_path(src_path)
            result[safe] = src_content
    return result


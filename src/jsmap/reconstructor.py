import json
import re
from pathlib import Path
from typing import Optional, Dict

from .logger import warn, success
from .layout import OutputLayout

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

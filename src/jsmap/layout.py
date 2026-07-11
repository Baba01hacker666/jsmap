from pathlib import Path
from .logger import C, info

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
            "sarif": ".sarif",
        }
        return self.reports_dir / f"findings{ext_map.get(fmt, '.json')}"

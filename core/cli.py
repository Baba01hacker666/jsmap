import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core.logger import C, banner, error, warn, info, success, critical, step
from core.layout import OutputLayout
from core.network import build_session
from core.downloader import ChunkDownloader
from core.extractors import (
    ExtractorOrchestrator,
    NativeRegexExtractor,
    TruffleHogExtractor,
    RipgrepExtractor,
)
from core.reconstructor import SourceMapReconstructor
from core.builder import AngularBuilder
from core.reporting import ReportGenerator, write_summary


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def validate_args(args, parser: argparse.ArgumentParser):
    if not args.url and not args.analyze_only and not args.ng_only:
        parser.print_help()
        sys.exit(1)
    if args.analyze_only and not args.dir:
        error("--analyze-only requires --dir")
        sys.exit(1)


def resolve_output_root(args) -> Path:
    if args.output:
        return Path(args.output)
    if args.url:
        host = urlparse(args.url).netloc.replace(":", "_")
        return Path(f"jsmap_{host}_{datetime.now():%Y%m%d_%H%M%S}")
    return Path(f"jsmap_analysis_{datetime.now():%Y%m%d_%H%M%S}")


def configure_extractors(args) -> ExtractorOrchestrator:
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
    return orchestrator


def main():
    parser = build_parser()
    args = parser.parse_args()
    banner()
    validate_args(args, parser)
    root = resolve_output_root(args)
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
    orchestrator = configure_extractors(args)

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

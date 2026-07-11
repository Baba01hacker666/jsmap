import json
import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from dataclasses import asdict
from typing import List, Optional

from .logger import C, warn, section, success
from .models import Finding
from .layout import OutputLayout

class ReportGenerator:
    SEV_ICON = {
        "CRITICAL": "💀",
        "HIGH": "🔴",
        "MEDIUM": "🟡",
        "LOW": "🔵",
        "INFO": "⚪",
    }
    SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

    def __init__(self, findings: List[Finding], redact_values: bool = False):
        self.findings = findings
        self.redact_values = redact_values

    def _value(self, value: str, limit: Optional[int] = None) -> str:
        """Return a report-safe representation without changing findings in memory."""
        if self.redact_values:
            value = "[REDACTED]"
        return value[:limit] if limit else value

    def _as_dict(self, finding: Finding) -> dict:
        result = asdict(finding)
        result["value"] = self._value(finding.value)
        result["context"] = self._value(finding.context)
        return result

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
                    val = self._value(item.value, 130).replace("\n", " ")
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
                json.dumps([self._as_dict(f) for f in self.findings], indent=2)
            )
        elif fmt == "csv":
            self._save_csv(out_path)
        elif fmt == "md":
            self._save_markdown(out_path)
        elif fmt == "txt":
            self._save_text(out_path)
        elif fmt == "html":
            self._save_html(out_path)
        elif fmt == "sarif":
            self._save_sarif(out_path)
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
                row = self._as_dict(f)
                w.writerow({k: row[k] for k in fields})

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
                    v = self._value(item.value, 100).replace("|", "\\|").replace("\n", " ")
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
                f"  Value: {self._value(f.value, 250)}",
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
            v = self._value(f.value, 200).replace("<", "&lt;").replace(">", "&gt;")
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

    def _save_sarif(self, out_path: Path):
        """Write SARIF 2.1.0 for GitHub and other code-scanning consumers."""
        level_map = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning", "LOW": "note", "INFO": "note"}
        rules, results = {}, []
        for finding in self.findings:
            rule_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{finding.category}.{finding.subcategory}")
            rules.setdefault(rule_id, {
                "id": rule_id,
                "name": finding.subcategory,
                "shortDescription": {"text": finding.subcategory},
                "properties": {"severity": finding.severity, "tool": finding.tool},
            })
            results.append({
                "ruleId": rule_id,
                "level": level_map.get(finding.severity, "note"),
                "message": {"text": self._value(finding.value, 600)},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": finding.file}, "region": {"startLine": max(1, finding.line)}}}],
            })
        payload = {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": [{"tool": {"driver": {"name": "jsmap", "rules": list(rules.values())}}, "results": results}]}
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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

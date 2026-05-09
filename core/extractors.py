import os
import re
import json
import hashlib
import bisect
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED

from core.logger import info, success, warn, error, substep
from core.models import Finding

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
        supported = set(self.supported_extensions)
        findings: List[Finding] = []
        max_workers = min(32, max(4, (os.cpu_count() or 4)))

        def _collect_done(done_futures):
            for future in done_futures:
                try:
                    findings.extend(future.result())
                except Exception as e:
                    warn(f"{self.name} failed: {e}")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending = set()
            queue_limit = max_workers * 4
            for file_path in dir_path.rglob("*"):
                if not file_path.is_file() or file_path.suffix not in supported:
                    continue
                pending.add(executor.submit(self.analyze_file, file_path))
                if len(pending) >= queue_limit:
                    done, pending = wait(
                        pending, return_when=FIRST_COMPLETED
                    )
                    _collect_done(done)
            if pending:
                _collect_done(as_completed(pending))
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
                "patterns": [r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"],
            },
            {
                "name": "Azure Storage Account Key",
                "severity": "CRITICAL",
                "patterns": [
                    r'(?:AccountKey|SharedAccessKey)[=:]\s*["\']([a-zA-Z0-9+/=]{88})["\']'
                ]
            },
            {
                "name": "Slack Bot Token",
                "severity": "CRITICAL",
                "patterns": [
                    r'(xoxb-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24})'
                ]
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
        "frameworks": [
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
                "name": "Vue Router",
                "severity": "INFO",
                "patterns": [
                    r'path\s*:\s*["\']([^"\']{1,150})["\']\s*,\s*(?:name|component)',
                    r'router\.push\(\s*["\']([^"\']{1,150})["\']\s*\)',
                ],
            },
            {
                "name": "Next.js / Nuxt Routing",
                "severity": "INFO",
                "patterns": [
                    r'router\.(?:push|replace)\(\s*["\']([^"\']{1,150})["\']\s*\)',
                    r'pages/([^"\']+)\.js',
                ],
            },
            {
                "name": "Environment Config",
                "severity": "MEDIUM",
                "patterns": [
                    r"export\s+const\s+environment\s*=\s*(\{[^}]{20,800}\})",
                    r"__NUXT__\s*=\s*(\{[^;]+\});",
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
        self._sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        self._compiled_rules = self._compile_rules()

    def _compile_rules(self) -> Dict[str, List[Dict[str, Any]]]:
        compiled: Dict[str, List[Dict[str, Any]]] = {}
        for category, rule_list in self.RULES.items():
            compiled_rules = []
            for rule in rule_list:
                compiled_rules.append(
                    {
                        "name": str(rule["name"]),
                        "severity": str(rule["severity"]),
                        "patterns": [
                            re.compile(p, re.MULTILINE | re.DOTALL)
                            for p in rule["patterns"]
                        ],
                        "blacklist": [
                            re.compile(bl, re.IGNORECASE)
                            for bl in rule.get("blacklist", [])
                        ],
                    }
                )
            compiled[category] = compiled_rules
        return compiled

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
        seen_in_file: set[str] = set()

        newline_positions = [
            pos for pos, ch in enumerate(content) if ch == "\n"
        ]

        for category, rule_list in self._compiled_rules.items():
            for rule in rule_list:
                name = rule["name"]
                severity = rule["severity"]
                patterns = rule["patterns"]
                blacklist = rule["blacklist"]

                if not self._sev_ok(severity):
                    continue

                for pattern in patterns:
                    try:
                        for m in pattern.finditer(content):
                            value = (
                                m.group(1)
                                if m.lastindex and m.lastindex >= 1
                                else m.group(0)
                            ).strip()
                            if not value or len(value) < 3:
                                continue
                            if any(bl.search(value) for bl in blacklist):
                                continue
                            dk = self._dedup(name, value)
                            if dk in seen_in_file:
                                continue
                            seen_in_file.add(dk)

                            line_no = (
                                bisect.bisect_right(newline_positions, m.start())
                                + 1
                            )
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
                    r"AKIA[0-9A-Z]{{16}}",
                    "-e",
                    r"AIza[0-9A-Za-z\-_]{{35}}",
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
        findings = sorted(
            findings,
            key=lambda f: (
                f.category,
                f.subcategory,
                f.value[:50],
                f.file,
                f.line,
            ),
        )
        seen, unique = set(), []
        for f in findings:
            key = hashlib.md5(
                f"{f.category}:{f.subcategory}:{f.value[:50]}:{f.file}:{f.line}".encode()
            ).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

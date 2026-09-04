from dataclasses import dataclass
from .logger import C

@dataclass
class Finding:
    category: str
    subcategory: str
    value: str
    severity: str
    file: str
    line: int
    context: str = ""
    confidence: str = "HIGH"
    tool: str = "native"

    def sev_color(self):
        return {
            "CRITICAL": C.BG_RED + C.WHITE,
            "HIGH": C.RED,
            "MEDIUM": C.YELLOW,
            "LOW": C.CYAN,
            "INFO": C.GRAY,
        }.get(self.severity, C.RESET)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "subcategory": self.subcategory,
            "value": self.value,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "context": self.context,
            "confidence": self.confidence,
            "tool": self.tool,
        }

    @property
    def is_secret(self) -> bool:
        return self.category.lower() == "secrets" or self.severity in {"CRITICAL", "HIGH"}

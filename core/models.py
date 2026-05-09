from dataclasses import dataclass
from core.logger import C

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

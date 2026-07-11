"""Public library interface for jsmap."""

from .api import ScanOptions, ScanResult, analyze_directory
from .models import Finding

__all__ = ["Finding", "ScanOptions", "ScanResult", "analyze_directory"]
__version__ = "0.2.0"

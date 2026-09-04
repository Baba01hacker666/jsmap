#!/usr/bin/env python3
import sys
from pathlib import Path

src_path = Path(__file__).resolve().parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from jsmap.cli import main

if __name__ == "__main__":
    main()


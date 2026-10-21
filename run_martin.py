"""Spuštění Martina z vývojového prostředí.

    python run_martin.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from martin.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
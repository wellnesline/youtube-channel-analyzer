"""synthetic stub: minimal .env loader (no external dependency).

Stands in for the private helper module that is not part of this repository.
"""
import os
from pathlib import Path


def load_dotenv(path=None):
    p = Path(path) if path else Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return True

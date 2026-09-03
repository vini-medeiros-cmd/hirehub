#!/usr/bin/env python3
"""Sobe o site.

    bin/servir.py                # 0.0.0.0:8080
    bin/servir.py 127.0.0.1 3000
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import servidor  # noqa: E402

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    porta = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    servidor.servir(host, porta)

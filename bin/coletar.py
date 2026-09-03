#!/usr/bin/env python3
"""Roda uma coleta.

    bin/coletar.py                 # todas as fontes
    bin/coletar.py gupy inhire     # só as fontes indicadas
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hirehub import coleta, fontes  # noqa: E402


def main(argv):
    conhecidas = {f.id for f in fontes.todas()}
    apenas = set(argv) & conhecidas
    if desconhecidas := set(argv) - conhecidas:
        print(f"Fonte desconhecida: {', '.join(sorted(desconhecidas))}")
        print(f"Disponíveis: {', '.join(sorted(conhecidas))}")
        return 2
    return 0 if coleta.executar(apenas or None) else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)

#!/usr/bin/env python3
"""Sobe o site.

    bin/servir.py                     # 0.0.0.0:8080
    bin/servir.py 127.0.0.1 3000
    bin/servir.py --agendar           # + dispara a coleta a cada N horas

Use --agendar apenas onde NÃO houver systemd (Termux, contêiner sem init). Em
produção quem agenda é o hirehub-coleta.timer, que sobrevive ao servidor cair e
recupera a rodada perdida depois de um reboot.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import servidor  # noqa: E402

if __name__ == "__main__":
    argumentos = [a for a in sys.argv[1:] if a != "--agendar"]
    host = argumentos[0] if argumentos else "0.0.0.0"
    porta = int(argumentos[1]) if len(argumentos) > 1 else 8080
    servidor.servir(host, porta, agendar="--agendar" in sys.argv)

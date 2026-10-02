#!/usr/bin/env python3
"""Cópia consistente do banco, com rotação.

    bin/backup.py            # grava em data/backups/
    bin/backup.py /mnt/hd    # ou onde você quiser

Por que não `cp`: o banco está em WAL e a coleta pode estar escrevendo. Copiar
o arquivo no meio disso produz uma cópia corrompida — que só se descobre no dia
em que ela é necessária. `VACUUM INTO` é a forma que o próprio SQLite oferece
para isso: tira um retrato consistente sem travar quem está lendo, e já sai
compactado.

Por que isto existe: a base acumula até 120 dias de histórico que as
plataformas NÃO oferecem — a Gupy só devolve as 10.000 mais recentes. Perder o
arquivo é perder dado que não volta por coleta nenhuma.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hirehub import config  # noqa: E402

MANTER = 7


def main(destino):
    if not config.BANCO.exists():
        print(f"Banco não encontrado em {config.BANCO}")
        return 1

    destino.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    arquivo = destino / f"hirehub-{marca}.db"

    con = sqlite3.connect(f"file:{config.BANCO}?mode=ro", uri=True)
    try:
        # Aspas simples e não parâmetro: VACUUM INTO não aceita bind.
        con.execute(f"VACUUM INTO '{arquivo}'")
    finally:
        con.close()

    vagas = sqlite3.connect(arquivo).execute("SELECT COUNT(*) FROM vagas").fetchone()[0]
    print(f"{arquivo}  ·  {arquivo.stat().st_size / 1048576:.1f} MB  ·  {vagas} vagas")

    # Rotação: guarda as MANTER mais recentes. Sem isso o disco enche sozinho
    # e a coleta é a primeira coisa a quebrar.
    copias = sorted(destino.glob("hirehub-*.db"))
    for velha in copias[:-MANTER]:
        velha.unlink()
        print(f"  removida: {velha.name}")
    return 0


if __name__ == "__main__":
    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else config.DATA_DIR / "backups"
    sys.exit(main(alvo))

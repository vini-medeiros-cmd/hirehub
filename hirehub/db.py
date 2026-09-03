"""Banco SQLite: esquema, gravação da coleta e as consultas que o site faz.

A filtragem acontece em SQL, nunca no navegador. A base passa de dezenas de
milhares de linhas e o site precisa abrir rápido numa VPS pequena — o SQLite
resolve em milissegundos e a página recebe uma dúzia de resultados por vez.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config, texto

POR_PAGINA = 20
# Vaga é "NOVA" quando foi publicada nas últimas 24 horas.
JANELA_NOVA_HORAS = 24

ESQUEMA = """
CREATE TABLE IF NOT EXISTS vagas (
  id            TEXT PRIMARY KEY,
  link          TEXT NOT NULL UNIQUE,
  titulo        TEXT NOT NULL,
  empresa       TEXT,
  fonte         TEXT NOT NULL,
  local         TEXT,
  modalidade    TEXT,
  -- Hoje só a Sólides publica salário; nas outras fica vazio.
  salario       TEXT,
  -- Texto puro, não HTML. Ver texto.texto_de_html().
  descricao     TEXT,
  publicada_em  TEXT,
  -- Quando a vaga ENTROU no HireHub. Nunca é sobrescrito.
  vista_em      TEXT NOT NULL,
  -- Carimbo da coleta que viu esta vaga por último. "No ar" é derivado disto.
  coleta        TEXT NOT NULL,
  -- Colunas desnormalizadas para busca sem acento (ver texto.chave_busca).
  busca_titulo  TEXT,
  busca_local   TEXT
);
CREATE INDEX IF NOT EXISTS idx_publicada ON vagas(publicada_em DESC);
CREATE INDEX IF NOT EXISTS idx_fonte ON vagas(fonte);
CREATE INDEX IF NOT EXISTS idx_coleta ON vagas(coleta);
CREATE INDEX IF NOT EXISTS idx_sem_descricao ON vagas(fonte) WHERE descricao IS NULL;

-- Uma linha por conector. É a origem da página /status.
CREATE TABLE IF NOT EXISTS fontes (
  id            TEXT PRIMARY KEY,
  nome          TEXT NOT NULL,
  ultima_coleta TEXT,
  ultimo_ok     TEXT,
  vagas         INTEGER DEFAULT 0,
  novas         INTEGER DEFAULT 0,
  duracao       REAL,
  erro          TEXT,
  -- A fonte entrega tudo ou só uma janela? Decide se ela pode marcar vagas
  -- como "saiu do ar". Ver fontes.Fonte.cobertura_completa e NO_AR.
  cobertura_completa INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
"""


# Colunas acrescentadas depois que já havia banco em produção. CREATE TABLE IF
# NOT EXISTS não altera tabela existente, então elas entram por ALTER.
MIGRACOES = [("fontes", "cobertura_completa", "INTEGER DEFAULT 0")]


def _migrar(con):
    for tabela, coluna, tipo in MIGRACOES:
        existentes = {c["name"] for c in con.execute(f"PRAGMA table_info({tabela})")}
        if coluna not in existentes:
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    con.commit()


def abrir(somente_leitura=False):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if somente_leitura and config.BANCO.exists():
        con = sqlite3.connect(f"file:{config.BANCO}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    con = sqlite3.connect(config.BANCO)
    # WAL deixa o site ler enquanto a coleta escreve, sem travar a página.
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(ESQUEMA)
    con.row_factory = sqlite3.Row
    _migrar(con)
    return con


# ------------------------------------------------------------------ gravação

def salvar(con, vagas, carimbo):
    """Grava as vagas de uma coleta e devolve quantas eram inéditas.

    O próprio banco é a memória do que já foi visto: vaga inédita é a que ainda
    não tem linha. Não existe arquivo de estado separado para dessincronizar.

    Dois campos são preservados no conflito, de propósito:

      * `vista_em` — é a data de entrada no HireHub. Sobrescrever faria o site
        inteiro parecer novo a cada 6 horas.
      * `descricao` — custa uma requisição extra por vaga em algumas fontes.
        A listagem seguinte vem sem descrição, e o COALESCE evita que ela
        apague o que o enriquecimento já tinha buscado.

    Os demais campos são atualizados: o anúncio pode ter sido editado na origem.
    """
    if not vagas:
        return 0
    antes = con.execute("SELECT COUNT(*) FROM vagas").fetchone()[0]
    con.executemany(
        """
        INSERT INTO vagas (id, link, titulo, empresa, fonte, local, modalidade,
                           salario, descricao, publicada_em, vista_em, coleta,
                           busca_titulo, busca_local)
        VALUES (:id, :link, :titulo, :empresa, :fonte, :local, :modalidade,
                :salario, :descricao, :publicada_em, :carimbo, :carimbo,
                :busca_titulo, :busca_local)
        ON CONFLICT(id) DO UPDATE SET
          titulo=excluded.titulo,
          empresa=excluded.empresa,
          local=excluded.local,
          modalidade=excluded.modalidade,
          salario=COALESCE(NULLIF(excluded.salario, ''), vagas.salario),
          descricao=COALESCE(excluded.descricao, vagas.descricao),
          publicada_em=COALESCE(excluded.publicada_em, vagas.publicada_em),
          busca_titulo=excluded.busca_titulo,
          busca_local=excluded.busca_local,
          coleta=excluded.coleta
        """,
        [_para_linha(v, carimbo) for v in vagas],
    )
    con.commit()
    return con.execute("SELECT COUNT(*) FROM vagas").fetchone()[0] - antes


def _para_linha(vaga, carimbo):
    link = vaga["link"]
    return {
        "id": texto.id_da_vaga(link),
        "link": link,
        "titulo": (vaga.get("titulo") or "").strip(),
        "empresa": (vaga.get("empresa") or "").strip(),
        "fonte": vaga["fonte"],
        "local": vaga.get("local") or "",
        "modalidade": vaga.get("modalidade") or "",
        "salario": vaga.get("salario") or "",
        "descricao": vaga.get("descricao") or None,
        "publicada_em": vaga.get("publicada_em"),
        "carimbo": carimbo,
        "busca_titulo": texto.chave_busca(vaga.get("titulo"), vaga.get("empresa")),
        "busca_local": texto.chave_busca(vaga.get("local")),
    }


CAMPOS_DETALHE = ("descricao", "publicada_em", "salario", "local", "modalidade")


def gravar_detalhes(con, detalhes):
    """detalhes: [(id_da_vaga, {campo: valor})], vindo do enriquecimento.

    `descricao` recebe string vazia quando a busca falhou, nunca NULL: é assim
    que uma vaga sem descrição obtenível para de ser tentada em toda execução.
    Sem isso, um punhado de anúncios quebrados consumiria a cota de detalhes
    para sempre e o enriquecimento nunca alcançaria o resto da base.
    """
    if not detalhes:
        return 0
    linhas = []
    for id_vaga, campos in detalhes:
        campos = {k: v for k, v in (campos or {}).items() if k in CAMPOS_DETALHE}
        campos.setdefault("descricao", "")
        linhas.append((campos, id_vaga))
    # Um UPDATE por conjunto de campos distinto; na prática são 1 ou 2 formatos.
    for campos, id_vaga in linhas:
        atribuicoes = ", ".join(f"{c}=COALESCE(?, {c})" for c in campos)
        con.execute(f"UPDATE vagas SET {atribuicoes} WHERE id=?",
                    (*campos.values(), id_vaga))
    con.commit()
    return len(linhas)


def pendentes_detalhe(con, fonte, limite):
    """Vagas da fonte que ainda nunca passaram pelo enriquecimento."""
    linhas = con.execute(
        "SELECT id, link FROM vagas WHERE fonte=? AND descricao IS NULL "
        "ORDER BY publicada_em IS NULL, publicada_em DESC LIMIT ?",
        (fonte, limite),
    ).fetchall()
    return [dict(l) for l in linhas]


def podar(con, dias):
    """Remove vagas que sumiram da origem e já estão velhas.

    Vaga fora do ar continua listada por um tempo de propósito: se ela sumisse
    da base no instante em que sai da API, um anúncio publicado e despublicado
    entre duas coletas nunca teria existido para quem usa o site.
    """
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    cur = con.execute("DELETE FROM vagas WHERE vista_em < ?", (corte,))
    con.commit()
    return cur.rowcount


def anotar_fonte(con, id_fonte, nome, **campos):
    colunas = ", ".join(f"{c}=excluded.{c}" for c in campos)
    con.execute(
        f"""INSERT INTO fontes (id, nome, {', '.join(campos)})
            VALUES (?, ?, {', '.join('?' * len(campos))})
            ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, {colunas}""",
        (id_fonte, nome, *campos.values()),
    )
    con.commit()


def gravar_meta(con, **valores):
    con.executemany(
        "INSERT INTO meta (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        [(k, str(v)) for k, v in valores.items()],
    )
    con.commit()


# ------------------------------------------------------------------ consultas

def ler_meta(con):
    try:
        return dict(con.execute("SELECT chave, valor FROM meta").fetchall())
    except sqlite3.OperationalError:
        return {}


def status_fontes(con):
    try:
        linhas = con.execute(
            "SELECT * FROM fontes ORDER BY nome COLLATE NOCASE").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(l) for l in linhas]


# "No ar" = a vaga foi vista na última coleta BEM-SUCEDIDA DA PRÓPRIA FONTE,
# e só vale para fontes de cobertura exaustiva.
#
# Duas condições, cada uma corrigindo um jeito de esconder vaga aberta:
#
#   * `fontes.ultimo_ok`, e não a última coleta global. Se a InHire falhasse
#     numa rodada, as 8.900 vagas dela ficariam com `coleta` mais antigo que o
#     carimbo global e sumiriam em bloco — 45% do catálogo apagado por um blip
#     de rede. A fonte que falha não move o próprio marco.
#
#   * `cobertura_completa = 1`. Numa fonte com janela, a vaga some da coleta
#     porque chegaram outras mais novas, não porque fechou. Medido: uma coleta
#     só da Gupy tirou do ar 1.740 vagas publicadas nos últimos 3 dias, todas
#     abertas. Fontes com janela nunca marcam nada como fora do ar — envelhecem
#     por `esquecer_apos_dias`, e é só.
#
# O COALESCE é o que faz a segunda condição funcionar: a subconsulta não devolve
# linha para fonte com janela (nem para fonte ainda sem registro, numa base
# recém-criada), e aí a vaga é comparada consigo mesma — sempre no ar.
NO_AR = ("vagas.coleta >= COALESCE((SELECT ultimo_ok FROM fontes "
         "WHERE fontes.id = vagas.fonte AND fontes.cobertura_completa = 1), "
         "vagas.coleta)")


def _filtros(criterios):
    onde, valores = ["1=1"], []

    # Ligado por padrão: quem chega ao site quer vaga aberta. Quem quiser o
    # histórico marca a opção, e aí o card avisa quais saíram do ar.
    if not criterios.get("incluir_fora_do_ar"):
        onde.append(NO_AR)

    termo = texto.chave_busca(criterios.get("q"))
    if termo:
        # Todas as palavras precisam aparecer, em qualquer ordem: quem busca
        # "analista python" não quer só o título que traz essa expressão exata.
        for palavra in termo.split():
            onde.append("busca_titulo LIKE ?")
            valores.append(f"%{palavra}%")

    onde_local = texto.chave_busca(criterios.get("local"))
    if onde_local:
        onde.append("busca_local LIKE ?")
        valores.append(f"%{onde_local}%")

    modalidade = criterios.get("modalidade")
    if modalidade in config.MODALIDADES:
        onde.append("modalidade = ?")
        valores.append(modalidade)

    fonte = criterios.get("fonte")
    if fonte:
        onde.append("fonte = ?")
        valores.append(fonte)

    dias = criterios.get("dias") or 0
    if dias > 0:
        corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        onde.append("publicada_em >= ?")
        valores.append(corte)

    return " AND ".join(onde), valores


def buscar(con, criterios, pagina=0, por_pagina=POR_PAGINA):
    filtro, valores = _filtros(criterios)
    total = con.execute(
        f"SELECT COUNT(*) FROM vagas WHERE {filtro}", valores).fetchone()[0]
    linhas = con.execute(
        f"""SELECT id, link, titulo, empresa, fonte, local, modalidade, salario,
                   publicada_em, vista_em, {NO_AR} AS no_ar
            FROM vagas WHERE {filtro}
            -- Sem data vai para o fim: não dá para ordenar pelo critério que o
            -- usuário escolheu se justamente esse dado não existe.
            ORDER BY publicada_em IS NULL, publicada_em DESC, id
            LIMIT ? OFFSET ?""",
        valores + [por_pagina, pagina * por_pagina],
    ).fetchall()
    return total, [dict(l) for l in linhas]


def por_id(con, id_vaga):
    """Busca por id ignora o filtro de "no ar" de propósito.

    Quem chegou aqui tem o link na mão — veio de um compartilhamento, de um
    buscador ou do próprio histórico. Devolver 404 porque o anúncio saiu do ar
    esconde a informação de quem foi atrás dela; a página abre e avisa.
    """
    linha = con.execute(
        f"SELECT *, {NO_AR} AS no_ar FROM vagas WHERE id = ?", (id_vaga,)).fetchone()
    return dict(linha) if linha else None


def relacionadas(con, vaga, limite=4):
    """Outras vagas com título parecido, para a página de detalhes não ser um beco.

    Aqui o filtro de "no ar" vale: sugerir uma vaga fechada a quem está olhando
    outra não ajuda ninguém.
    """
    primeira = (vaga.get("busca_titulo") or "").split()
    if not primeira:
        return []
    return [dict(l) for l in con.execute(
        f"""SELECT id, link, titulo, empresa, local, fonte, modalidade, salario,
                   publicada_em, 1 AS no_ar
            FROM vagas WHERE busca_titulo LIKE ? AND id != ? AND {NO_AR}
            ORDER BY publicada_em IS NULL, publicada_em DESC LIMIT ?""",
        (f"%{primeira[0]}%", vaga["id"], limite),
    ).fetchall()]


VAZIO = {"total": 0, "novas": 0, "empresas": 0, "fora_do_ar": 0}


def contagens(con):
    """Números da home, numa varredura só.

    Contam apenas o que está no ar: anunciar "19.870 vagas" e entregar uma
    listagem com menos seria mentir no primeiro número que o visitante lê.

    As quatro contas cabem num SELECT porque a base inteira precisa ser
    percorrida de qualquer jeito — o predicado de "no ar" não é indexável. Em
    consultas separadas eram quatro varreduras de ~60ms cada; numa só, 86ms.
    """
    corte = (datetime.now(timezone.utc)
             - timedelta(hours=JANELA_NOVA_HORAS)).isoformat()
    try:
        total, novas, empresas, fora = con.execute(
            f"""SELECT SUM({NO_AR}),
                       SUM(({NO_AR}) AND publicada_em >= ?),
                       COUNT(DISTINCT CASE WHEN ({NO_AR}) AND empresa != ''
                                           THEN empresa END),
                       SUM(NOT ({NO_AR}))
                FROM vagas""", (corte,)).fetchone()
    except sqlite3.OperationalError:
        return dict(VAZIO)
    return {"total": total or 0, "novas": novas or 0,
            "empresas": empresas or 0, "fora_do_ar": fora or 0}


def contagens_rapidas(con):
    """O mesmo, mas lido do que a última coleta deixou anotado.

    O rodapé mostra o total em TODAS as páginas. Varrer 20 mil linhas para
    imprimir um número no rodapé de uma página institucional é desperdício:
    esse total só muda quando uma coleta termina, que é exatamente quando ele é
    gravado. A home continua usando contagens(), porque ali os números são o
    conteúdo, não um detalhe do rodapé.
    """
    meta = ler_meta(con)
    if "vagasNoAr" not in meta:
        return contagens(con)
    return {**VAZIO, "total": int(meta.get("vagasNoAr") or 0),
            "fora_do_ar": int(meta.get("vagasForaDoAr") or 0)}

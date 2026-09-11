"""Vagas.com.br — listagem raspada, detalhe em JSON-LD.

Uma das maiores do país, e o `robots.txt` dela não restringe as páginas de
vaga (diferente da Catho e do Indeed, que proíbem justamente essas — por isso
nenhuma das duas está aqui).

Não tem API pública, mas tem algo melhor que raspagem de HTML no detalhe: cada
página de vaga publica um bloco **JSON-LD JobPosting** do schema.org, com data
de publicação, descrição completa, empresa e localidade em campos nomeados.
Isso é marcação que existe para os buscadores lerem, então muda muito menos que
classe de CSS — a parte frágil do conector fica restrita à listagem.

Como a Gupy e o InfoJobs, a cobertura é por janela, não exaustiva: a listagem
nacional (`/vagas-de-emprego`) é uma seleção curada de ~120 vagas, e o catálogo
de verdade só é alcançável por cidade ou por termo. Por isso `cobertura_completa`
fica False — ausência aqui não significa vaga encerrada.

Medido em 04/09/2026: São Paulo tem 992 vagas alcançáveis, 40 por página, e a
paginação vai até o fim sem repetir.
"""
import html
import re

from .. import net, schemaorg, texto
from . import Fonte, registrar

BASE = "https://www.vagas.com.br"

# Escolha editorial, igual à do InfoJobs: capitais, polos e as cidades da
# região do usuário. Configurável em `vagas_cidades`.
CIDADES_PADRAO = [
    "sao-paulo", "rio-de-janeiro", "belo-horizonte", "brasilia", "curitiba",
    "porto-alegre", "salvador", "recife", "fortaleza", "campinas",
    "macae", "rio-das-ostras",
]

# Cada vaga da listagem é um <li class="vaga ...">. Os campos internos são
# ancorados por classe; o título vem do atributo `title` e não do texto do
# link, porque o texto traz <mark> em volta do termo buscado.
_CARD = re.compile(r'<li class="vaga[^"]*">([\s\S]*?)</li>')
_LINK = re.compile(r'href="(/vagas/v[^"]+)"')
_TITULO = re.compile(r'class="link-detalhes-vaga"[^>]*title="([^"]*)"')
_EMPRESA = re.compile(r'class="emprVaga"[^>]*>\s*([^<]+)')
_LOCAL = re.compile(r'class="vaga-local"[^>]*>[\s\S]*?</i>\s*([^<]+)')


@registrar
class Vagas(Fonte):
    id = "vagas"
    nome = "Vagas.com.br"
    site = BASE
    cobertura_completa = False

    # Cloudflare, e o que ela mede é TAXA — não paralelismo. Isso custou dois
    # bloqueios de 24h para ficar claro:
    #
    #   1º) 968 detalhes a 8 threads. Reduzi para 2 threads e 120 detalhes.
    #   2º) mesmo assim. A listagem tinha crescido para 192 requisições, e ela
    #       sozinha já gastava o orçamento: sobraram 16 detalhes antes do 429.
    #
    # Limitar thread não conteve porque 2 threads sem pausa ainda disparam
    # várias requisições por segundo. `req_por_segundo` é o que realmente
    # importa aqui — uma por segundo, somando listagem e detalhe.
    #
    # E o segundo bloqueio ensinou outra coisa: nesta fonte, listagem e detalhe
    # disputam o MESMO orçamento. Ampliar a listagem aqui reduz o
    # enriquecimento, e como a data desta fonte só vem do detalhe, vagas sem
    # detalhe entram sem data e afundam na ordenação. Mais vagas piores não é
    # ganho — por isso as cidades dela ficam nas 12 originais, enquanto o
    # InfoJobs (que não reclama) foi para 25.
    threads = 2
    detalhes_por_execucao = 120
    req_por_segundo = 1

    def coletar(self, cfg, log):
        paginas = int(cfg.get("vagas_paginas_por_cidade") or 0)
        if paginas <= 0:
            return []
        cidades = cfg.get("vagas_cidades") or CIDADES_PADRAO
        tarefas = [(c, p) for c in cidades for p in range(1, paginas + 1)]
        log(f"{paginas} páginas x {len(cidades)} cidades")

        lotes = net.em_paralelo(lambda t: _listar(*t), tarefas, cfg["threads"],
                                ritmo=cfg.get("ritmo"))
        vistos, vagas = set(), []
        for lote in lotes:
            for vaga in lote or []:
                # A mesma vaga aparece em mais de uma cidade da lista.
                if vaga["link"] not in vistos:
                    vistos.add(vaga["link"])
                    vagas.append(vaga)
        return vagas

    @staticmethod
    def detalhar(vaga):
        pagina = net.html_de(vaga["link"])
        if pagina is None:
            return None  # não consegui buscar — tenta de novo depois
        # Página veio, mas sem a marcação: é resposta legítima, e a descrição
        # vazia marca a vaga como já enriquecida.
        return schemaorg.vaga_de(pagina) or {"descricao": ""}


def _listar(cidade, pagina):
    conteudo = net.html_de(f"{BASE}/vagas-em-{cidade}?pagina={pagina}")
    if not conteudo:
        return []
    vagas = []
    for bloco in _CARD.findall(conteudo):
        link = _busca(_LINK, bloco)
        titulo = _busca(_TITULO, bloco)
        if not link or not titulo:
            continue
        vagas.append({
            "link": BASE + link,
            "titulo": titulo,
            "empresa": _busca(_EMPRESA, bloco),
            "fonte": "vagas",
            # A listagem escreve "São Paulo / SP"; texto.local normaliza.
            "local": texto.local(*_busca(_LOCAL, bloco).split("/")),
            # Do TÍTULO, não do HTML do card. Passar o bloco inteiro varreria
            # classes de CSS e tooltips atrás de "remoto"/"presencial" — um
            # gerador de falso positivo. No título a menção é intencional
            # ("Analista — Remoto"), e o que faltar vem da JSON-LD do detalhe.
            "modalidade": texto.modalidade(titulo),
            "salario": "",
            # Nenhum dos dois vem na listagem; ambos saem da JSON-LD do
            # detalhe, numa requisição só. Ver detalhar().
            "descricao": None,
            "publicada_em": None,
        })
    return vagas


def _busca(padrao, bloco):
    casou = padrao.search(bloco)
    return html.unescape(casou.group(1)).strip() if casou else ""

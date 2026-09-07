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
import json
import re

from .. import net, texto
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
_JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>([\s\S]*?)</script>')


@registrar
class Vagas(Fonte):
    id = "vagas"
    nome = "Vagas.com.br"
    site = BASE
    cobertura_completa = False

    # Está atrás de Cloudflare, e ela não avisa antes: 968 páginas de detalhe a
    # 8 threads renderam um 429 com Retry-After de 24 horas. Estes dois números
    # foram escolhidos para o enriquecimento ocupar cerca de um minuto de
    # tráfego a cada 6 horas — o acervo converge em alguns dias, sem incomodar
    # a origem. Não suba sem medir.
    threads = 2
    detalhes_por_execucao = 120

    def coletar(self, cfg, log):
        paginas = int(cfg.get("vagas_paginas_por_cidade") or 0)
        if paginas <= 0:
            return []
        cidades = cfg.get("vagas_cidades") or CIDADES_PADRAO
        tarefas = [(c, p) for c in cidades for p in range(1, paginas + 1)]
        log(f"{paginas} páginas x {len(cidades)} cidades")

        lotes = net.em_paralelo(lambda t: _listar(*t), tarefas, cfg["threads"])
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
        if not pagina:
            return None
        anuncio = _json_ld_jobposting(pagina)
        if not anuncio:
            return {"descricao": ""}  # página existe, mas sem a marcação
        endereco = (anuncio.get("jobLocation") or {}).get("address") or {}
        # TELECOMMUTE é o vocabulário do schema.org para trabalho remoto.
        remoto = str(anuncio.get("jobLocationType") or "").upper() == "TELECOMMUTE"
        return {
            "descricao": texto.texto_de_html(anuncio.get("description")),
            "publicada_em": texto.data_iso(anuncio.get("datePosted")),
            "local": texto.local(endereco.get("addressLocality"),
                                 endereco.get("addressRegion")) or None,
            "salario": _salario(anuncio.get("baseSalary")) or None,
            "modalidade": "remote" if remoto else None,
        }


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


def _json_ld_jobposting(pagina):
    """O bloco schema.org/JobPosting da página, se houver.

    É marcação padronizada, publicada para os buscadores indexarem — bem mais
    estável que classe de CSS. Vale a pena procurar em qualquer fonte nova
    antes de partir para raspagem de HTML.
    """
    for bruto in _JSON_LD.findall(pagina):
        try:
            dados = json.loads(bruto)
        except json.JSONDecodeError:
            continue
        for item in (dados if isinstance(dados, list) else [dados]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _salario(base):
    """MonetaryAmount do schema.org → texto curto, no formato das outras fontes."""
    if not isinstance(base, dict):
        return ""
    valor = base.get("value")
    if not isinstance(valor, dict):
        return ""
    ini, fim = valor.get("minValue"), valor.get("maxValue")
    if not ini and not fim:
        return ""
    if ini and fim and ini != fim:
        return f"R$ {ini:,.0f} a R$ {fim:,.0f}".replace(",", ".")
    return f"R$ {(ini or fim):,.0f}".replace(",", ".")

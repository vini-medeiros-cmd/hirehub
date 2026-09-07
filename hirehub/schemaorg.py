"""Leitura do bloco JSON-LD `JobPosting` do schema.org.

Muita plataforma de vagas publica os dados do anúncio em marcação estruturada,
para os buscadores indexarem. Quando existe, é sempre a melhor porta de
entrada: são campos nomeados e padronizados, publicados justamente para serem
lidos por terceiros — mudam muito menos que classe de CSS, que é a alternativa.

**Vale procurar este bloco em qualquer fonte nova antes de considerar raspagem
de HTML.** Hoje a Vagas.com.br e a Trampos.co entram por aqui; o BNE também
publica (com salário), mas foi descartado por outro motivo — ver o README.

Este módulo só traduz: quem busca a página é o conector.
"""
import json
import re

from . import texto

_BLOCO = re.compile(r'<script[^>]+application/ld\+json[^>]*>([\s\S]*?)</script>')


def vaga_de(pagina):
    """O JobPosting da página, já traduzido para os campos do HireHub.

    Devolve None quando não há marcação — que o conector deve distinguir de
    "não consegui buscar a página": ver o contrato de `Fonte.detalhar`.

    Todo campo sai como None quando ausente, nunca como string vazia, porque
    `db.gravar_detalhes` usa COALESCE — None preserva o que já estava lá em vez
    de apagar com um valor pior. A exceção é `descricao`, que precisa vir como
    string (mesmo vazia) para marcar a vaga como já enriquecida.
    """
    anuncio = _bruto(pagina)
    if anuncio is None:
        return None

    endereco = (_primeiro(anuncio.get("jobLocation")) or {}).get("address") or {}
    # TELECOMMUTE é o vocabulário do schema.org para trabalho remoto.
    remoto = str(anuncio.get("jobLocationType") or "").upper() == "TELECOMMUTE"

    return {
        "descricao": texto.texto_de_html(anuncio.get("description")),
        "publicada_em": texto.data_iso(anuncio.get("datePosted")),
        "local": texto.local(endereco.get("addressLocality"),
                             endereco.get("addressRegion")) or None,
        "salario": salario(anuncio.get("baseSalary")) or None,
        "modalidade": "remote" if remoto else None,
    }


def _bruto(pagina):
    for texto_json in _BLOCO.findall(pagina or ""):
        try:
            dados = json.loads(texto_json)
        except json.JSONDecodeError:
            continue
        # O bloco pode ser um objeto, uma lista, ou um @graph com vários tipos.
        for item in _achatar(dados):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _achatar(dados):
    if isinstance(dados, list):
        for item in dados:
            yield from _achatar(item)
    elif isinstance(dados, dict):
        yield dados
        yield from _achatar(dados.get("@graph") or [])


def _primeiro(valor):
    """jobLocation pode vir como objeto ou como lista de locais."""
    if isinstance(valor, list):
        return valor[0] if valor else None
    return valor


def salario(base):
    """MonetaryAmount do schema.org → texto curto, no formato das outras fontes."""
    if not isinstance(base, dict):
        return ""
    valor = base.get("value")
    if isinstance(valor, (int, float)):
        return f"R$ {valor:,.0f}".replace(",", ".")
    if not isinstance(valor, dict):
        return ""
    ini, fim = valor.get("minValue"), valor.get("maxValue")
    if not ini and not fim:
        return ""
    if ini and fim and ini != fim:
        return f"R$ {ini:,.0f} a R$ {fim:,.0f}".replace(",", ".")
    return f"R$ {(ini or fim):,.0f}".replace(",", ".")

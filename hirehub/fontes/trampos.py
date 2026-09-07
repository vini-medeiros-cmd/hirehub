"""Trampos.co — vagas de áreas criativas e digitais.

A única das cinco com API pública **sem token**: `/api/oportunidades.json`
devolve JSON limpo e paginado, sem chave, sem cabeçalho especial e sem
cadastro. A documentação fala em "API para parceiros", mas este endereço
responde aberto — foi o que decidiu a entrada dela, e não a documentação.

É a menor fonte do HireHub, e de propósito: cerca de 230 vagas cobrindo umas
três semanas, concentradas em design, produto, marketing e tecnologia. Entra
por complementar o catálogo onde as generalistas são fracas, não por volume.

A listagem já traz data de publicação — melhor que a Vagas.com.br e o InfoJobs,
que exigem uma requisição por vaga só para isso. O que falta (descrição, local,
modalidade) vem da JSON-LD da página do anúncio.

Medido em 07/09/2026: 10 vagas por página, `?page=N` pagina de verdade (sem
repetir), e o acervo acaba por volta da página 24.
"""
from .. import net, schemaorg, texto
from . import Fonte, registrar

API = "https://trampos.co/api/oportunidades.json"
POR_PAGINA = 10


@registrar
class Trampos(Fonte):
    id = "trampos"
    nome = "Trampos.co"
    site = "https://trampos.co"

    # A paginação alcança o acervo inteiro, então seria tentador marcar True e
    # deixar a fonte sinalizar vaga encerrada. Fica False mesmo assim: se a API
    # passar a limitar profundidade — como a Gupy faz —, a mudança seria
    # silenciosa e o HireHub começaria a esconder vaga aberta. O prejuízo de
    # errar para este lado é só deixar um anúncio velho listado por mais tempo.
    cobertura_completa = False

    # Site pequeno, com API generosa. Não há motivo para apertá-lo.
    threads = 2
    detalhes_por_execucao = 150

    def coletar(self, cfg, log):
        maximo = int(cfg.get("trampos_paginas") or 0)
        if maximo <= 0:
            return []

        # Sequencial, não em paralelo: só se sabe que a página N+1 vale a pena
        # depois de ver que a N veio cheia. Disparar 30 páginas de uma vez para
        # descobrir que 6 existiam seria incomodar a origem à toa.
        vagas, vistos = [], set()
        for pagina in range(1, maximo + 1):
            dados = net.json_de(net.url_com(API, page=pagina))
            if not dados:
                break
            novas = [v for bruta in dados if (v := _traduzir(bruta))
                     and v["link"] not in vistos]
            vistos.update(v["link"] for v in novas)
            vagas += novas
            if len(dados) < POR_PAGINA:
                break  # última página
        log(f"{len(vagas)} vagas em {pagina} páginas")
        return vagas

    @staticmethod
    def detalhar(vaga):
        pagina = net.html_de(vaga["link"])
        if pagina is None:
            return None  # não consegui buscar — tenta de novo depois
        return schemaorg.vaga_de(pagina) or {"descricao": ""}


def _traduzir(bruta):
    """A API embrulha cada item em {"opportunity": {...}}."""
    anuncio = (bruta or {}).get("opportunity") or {}
    link = anuncio.get("permalink")
    titulo = (anuncio.get("name") or "").strip()
    if not link or not titulo:
        return None
    return {
        "link": link,
        "titulo": titulo,
        "empresa": (anuncio.get("company_name") or "").strip(),
        "fonte": "trampos",
        # Local e modalidade não vêm na listagem; saem da JSON-LD do detalhe.
        "local": "",
        "modalidade": texto.modalidade(titulo),
        "salario": "",
        "descricao": None,
        "publicada_em": texto.data_iso(anuncio.get("published_at")),
    }

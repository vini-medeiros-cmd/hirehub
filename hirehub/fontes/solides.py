"""Sólides — a plataforma que publicava salário antes de esvaziar.

ATENÇÃO, medido em 03/09/2026: o endpoint responde 200 com `success: true` e
`count: 0` para qualquer combinação de take/page/search. Ele não quebrou, ele
esvaziou. Não é limite de taxa (a resposta é imediata e consistente) nem falta
de cabeçalho (testado com Origin e Referer do próprio portal).

O conector fica no ar de propósito: a página /status mostra "sem retorno" em
vez de esconder o problema, e no dia em que a API voltar a responder, a coleta
volta sozinha. Enquanto isso, as outras três seguram o catálogo.

Limites conhecidos de quando ela respondia, mantidos porque voltarão a valer:

  * `take` acima de 12 devolve lista vazia. São ~6.000 requisições para as 72
    mil vagas, o que inviabiliza varrer tudo numa execução.
  * `page` não tem teto de profundidade (a Gupy trava em offset 10.000), então
    o histórico inteiro é alcançável ao longo das rodadas.
  * A paginação é instável: o mesmo id aparece em páginas diferentes. De 360
    itens buscados, 193 eram únicos. A ordenação é por data SEM hora, então
    vagas do mesmo dia empatam e saem em ordem arbitrária a cada consulta.
    Nenhum parâmetro corrige (testados orderBy, sort, order, sortBy).

Consequência: a cobertura da Sólides é ESTATÍSTICA, não exaustiva. Cada
execução amostra e o banco acumula o resto ao longo das rodadas.
"""
from .. import net, texto
from . import Fonte, registrar

API = "https://apigw.solides.com.br/jobs/v3/portal-vacancies-new"
PAGINA = 12  # teto da API: acima disso volta vazio


@registrar
class Solides(Fonte):
    id = "solides"
    nome = "Sólides"
    site = "https://vagas.solides.com.br"

    def coletar(self, cfg, log):
        max_paginas = int(cfg["solides_paginas"])
        if max_paginas <= 0:
            return []

        def pagina(p):
            dados = net.json_de(net.url_com(API, take=PAGINA, page=p))
            return ((dados or {}).get("data") or {}).get("data") or []

        paginas = net.em_paralelo(pagina, range(1, max_paginas + 1), cfg["threads"])
        brutas = [i for p in paginas if p for i in p]
        if not brutas:
            log("nenhum item retornado — ver o comentário no topo de solides.py")
            return []
        return [v for bruta in brutas if (v := self._traduzir(bruta))]

    @staticmethod
    def _traduzir(bruta):
        link = _link(bruta)
        if not link:
            return None
        return {
            "link": link,
            "titulo": (bruta.get("title") or "").strip(),
            "empresa": (bruta.get("companyName") or "").strip(),
            "fonte": "solides",
            "local": texto.local((bruta.get("city") or {}).get("name"),
                                 (bruta.get("state") or {}).get("code")),
            "modalidade": texto.modalidade(
                "remote" if bruta.get("homeOffice") else bruta.get("jobType")),
            "salario": _faixa(bruta.get("salary")),
            "descricao": texto.texto_de_html(bruta.get("description")),
            "publicada_em": texto.data_iso(bruta.get("createdAt")),
        }


def _link(bruta):
    """O `redirectLink` da API está quebrado na prática: os dois domínios que
    ele usa (`{empresa}.solides.jobs` e `{empresa}.vagas.solides.com.br`) não
    abrem no navegador, nem para slugs limpos.

    O que abre é o link sem subdomínio de empresa que o próprio portal usa nos
    resultados de busca. Só funciona quando o id é numérico — vagas nativas da
    plataforma. Ids alfanuméricos vêm de integrações externas via ATS e não têm
    página nesse domínio. Para essas não existe link confiável, e uma vaga cujo
    "Candidatar-se" não leva a lugar nenhum é pior do que uma vaga ausente:
    link vazio faz a vaga ser descartada na coleta.
    """
    id_vaga = bruta.get("id")
    if isinstance(id_vaga, int) or (isinstance(id_vaga, str) and id_vaga.isdigit()):
        return f"https://vagas.solides.com.br/vaga/{id_vaga}/{texto.slug(bruta.get('title') or '')}"
    return ""


def _faixa(salario):
    if not isinstance(salario, dict) or salario.get("negotiable"):
        return ""
    ini, fim = salario.get("initialRange"), salario.get("finalRange")
    if not ini and not fim:
        return ""
    if ini and fim and ini != fim:
        return f"R$ {ini:,.0f} a R$ {fim:,.0f}".replace(",", ".")
    return f"R$ {(ini or fim):,.0f}".replace(",", ".")

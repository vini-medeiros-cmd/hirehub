"""Sólides — sem saída, e não por falta de tentar.

DIAGNÓSTICO FINAL, 08/09/2026. O endpoint abaixo responde 200 com
`success: true` e `count: 0` para qualquer combinação de take/page/search. Não
é limite de taxa nem falta de cabeçalho (testado com Origin e Referer do
próprio portal): **o portal foi reescrito em Next.js e esta API saiu do ar
junto com a versão antiga do site.**

O que existe hoje, e por que nada disso serve:

  * O catálogo continua lá — 73.031 vagas em `/vagas/todas`, com título,
    empresa, local, salário e descrição completa visíveis na página.
  * Mas a listagem é montada por JavaScript: buscando por HTTP puro vem 1 card;
    no navegador, 12. Raspar exigiria navegador headless, e o projeto inteiro
    se sustenta em não ter dependências.
  * E isso nem seria o pior. **Não há link para a vaga individual.** O título
    não é link, o card não é clicável, e o único destino do card é a raiz do
    mural da empresa (`{slug}.vagas.solides.com.br`) — que também é renderizado
    por JavaScript e não expõe as vagas no HTML.

Ou seja: mesmo pagando o preço de um navegador headless, o botão
"Candidatar-se" não teria para onde apontar além da página inicial da empresa.
Isso quebra a regra que vale para todas as fontes — link não confiável não
entra. Ver `_link()` abaixo, que já aplicava o mesmo critério.

O conector fica no ar porque a /status dizendo "Sem retorno" é informação
honesta, e porque no dia em que a Sólides publicar uma API nova a volta custa
trocar uma URL. Não porque haja esperança de consertar a atual.

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

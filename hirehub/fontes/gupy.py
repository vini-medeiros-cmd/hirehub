"""Gupy — a fonte mais generosa de todas.

A listagem já devolve `description`, então esta é a única plataforma que não
precisa de enriquecimento: sai da coleta com a página de detalhes pronta.

O limite é de paginação: `offset + limit` não pode passar de 10.000. Sem termo
de busca, só dá para alcançar as 10.000 vagas mais recentes (das ~84 mil
publicadas). Como a API devolve em ordem de data, isso cobre os últimos dias —
que é exatamente o que interessa a quem roda de 6 em 6 horas. Cada termo em
`gupy_termos` abre uma janela de 10.000 adicional, para ir mais fundo numa área.
"""
from .. import net, texto
from . import Fonte, registrar

API = "https://employability-portal.gupy.io/api/v1/jobs"
PAGINA = 100
MAX_OFFSET = 10_000  # teto da API, não escolha nossa


@registrar
class Gupy(Fonte):
    id = "gupy"
    nome = "Gupy"
    site = "https://portal.gupy.io"

    def coletar(self, cfg, log):
        # Gerador, não lista: com 11 termos configurados esta fonte passa de
        # 43.000 vagas COM descrição, e juntá-las antes de gravar levava o pico
        # de memória a mais de 540 MB — inviável na VPS de 945 MB. Entregando
        # janela por janela, o orquestrador grava em lotes e o pico fica no
        # tamanho de uma janela, não do acervo.
        #
        # `vistas` guarda só os links, não as vagas: são alguns MB de texto
        # contra centenas de dicionários com descrição.
        vistas = set()
        for termo in [None, *cfg["gupy_termos"]]:
            novas = 0
            for vaga in self._janela(termo, cfg["threads"]):
                if vaga["link"] in vistas:
                    continue
                vistas.add(vaga["link"])
                novas += 1
                yield vaga
            if termo:
                log(f"termo '{termo}': +{novas} vagas")

    def _janela(self, termo, threads):
        total = min(self._total(termo), MAX_OFFSET)
        if total <= 0:
            return []

        pedidos = [(o, min(PAGINA, MAX_OFFSET - o)) for o in range(0, total, PAGINA)]

        def pagina(par):
            offset, limite = par
            url = net.url_com(API, limit=limite, offset=offset, jobName=termo)
            return (net.json_de(url) or {}).get("data") or []

        paginas = net.em_paralelo(pagina, pedidos, threads)
        return [
            v for bruta in (i for p in paginas if p for i in p)
            if (v := self._traduzir(bruta))
        ]

    @staticmethod
    def _total(termo):
        """A API ecoa `total` errado quando a página vem cheia: com limit=100 ela
        devolve 100 em vez do total real. Com limit=1 vem o número certo."""
        dados = net.json_de(net.url_com(API, limit=1, offset=0, jobName=termo))
        return (dados or {}).get("pagination", {}).get("total", 0)

    @staticmethod
    def _traduzir(bruta):
        link = bruta.get("jobUrl") or bruta.get("careerPageUrl") or ""
        if not link:
            return None
        return {
            "link": link,
            "titulo": (bruta.get("name") or "").strip(),
            "empresa": (bruta.get("careerPageName") or bruta.get("companyName") or "").strip(),
            "fonte": "gupy",
            "local": texto.local(bruta.get("city"), bruta.get("state"), bruta.get("country")),
            "modalidade": texto.modalidade(
                "remote" if bruta.get("isRemoteWork") else bruta.get("workplaceType")),
            "salario": "",
            "descricao": texto.texto_de_html(bruta.get("description")),
            "publicada_em": texto.data_iso(bruta.get("publishedDate")),
        }

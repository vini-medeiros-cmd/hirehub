"""InfoJobs — a única fonte sem API: HTML raspado.

Não existe endpoint público nem busca nacional. Cada URL redireciona para uma
cidade conforme a geolocalização do IP de quem pede, e `empregos-em-{cidade}`
só fica na cidade pedida quando vem com a UF (",-sp", ",-rj"); sem isso, volta
sempre para São Paulo. A cobertura é por cidade, e a lista abaixo é uma escolha
editorial (capitais e polos), não um limite técnico: acrescentar municípios é
acrescentar linhas.

Sendo raspagem, é a fonte mais frágil das quatro — uma reforma de layout no
InfoJobs quebra os padrões daqui, e é para isso que a página /status existe.
"""
import html
import re

from .. import net, texto
from . import Fonte, registrar

BASE = "https://www.infojobs.com.br"

CIDADES = [
    ("sao-paulo", "sp"), ("rio-janeiro", "rj"), ("belo-horizonte", "mg"),
    ("brasilia", "df"), ("curitiba", "pr"), ("porto-alegre", "rs"),
    ("salvador", "ba"), ("recife", "pe"), ("fortaleza", "ce"),
    ("campinas", "sp"), ("macae", "rj"), ("rio-das-ostras", "rj"),
]

# Cada card na listagem começa nesta marca (id + link), com título, data e
# empresa logo depois. Regex e não html.parser: há muito conteúdo alheio
# (tooltips, ícones, scripts) entre os campos, e ancorar nessas marcas é mais
# direto do que montar a árvore inteira só para procurar nela depois.
_CARD = re.compile(r'data-id="(\d+)"\s+class="[^"]*js_rowCard[^"]*"\s+data-href="([^"]+)"')
_TITULO = re.compile(r'js_vacancyTitle">\s*([^<]+?)\s*<')
_DATA = re.compile(r'class="js_date" data-value="(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})"')
# O link da empresa às vezes é /empresa-{slug}__-{id}.aspx, às vezes uma URL
# "vanity" tipo /personale. Ancorar na classe pega os dois formatos.
_EMPRESA = re.compile(
    r'class="text-body text-decoration-none" href="https://www\.infojobs\.com\.br/[^"]*"[^>]*>\s*(.*?)</a>',
    re.S,
)
_PAINEL = "js_vacancyDataPanel"
_TAG = re.compile(r"<[^>]+>")


@registrar
class InfoJobs(Fonte):
    id = "infojobs"
    nome = "InfoJobs"
    site = BASE

    def coletar(self, cfg, log):
        paginas = int(cfg["infojobs_paginas_por_cidade"])
        if paginas <= 0:
            return []
        tarefas = [
            (cidade, uf, remoto, p)
            for cidade, uf in CIDADES
            for remoto in (False, True)
            for p in range(1, paginas + 1)
        ]
        log(f"{paginas} páginas x {len(CIDADES)} cidades x 2 modalidades")
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
        inicio = pagina.find(_PAINEL)
        if inicio < 0:
            return {"descricao": ""}  # página existe, mas sem o painel esperado
        return {"descricao": _limpar(pagina[inicio:inicio + 12000])}


def _listar(cidade, uf, remoto, pagina):
    sufixo = "-trabalho-home-office" if remoto else ""
    conteudo = net.html_de(f"{BASE}/empregos-em-{cidade},-{uf}{sufixo}.aspx?Page={pagina}")
    if not conteudo:
        return []

    marcas = list(_CARD.finditer(conteudo))
    vagas = []
    for i, marca in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else min(len(conteudo), marca.end() + 4000)
        bloco = conteudo[marca.start():fim]

        titulo = _TITULO.search(bloco)
        if not titulo:
            continue

        data = _DATA.search(bloco)
        publicada = (
            f"{data.group(1)}-{data.group(2)}-{data.group(3)}"
            f"T{data.group(4)}:{data.group(5)}:{data.group(6)}" if data else None
        )

        href = marca.group(2)
        vagas.append({
            "link": href if href.startswith("http") else f"{BASE}{href}",
            "titulo": html.unescape(titulo.group(1)).strip(),
            "empresa": _empresa(bloco),
            "fonte": "infojobs",
            "local": texto.local(cidade.replace("-", " ").title(), uf.upper()),
            "modalidade": "remote" if remoto else "on-site",
            "salario": "",
            "descricao": None,  # só na página da vaga; ver detalhar()
            "publicada_em": texto.data_iso(publicada),
        })
    return vagas


def _empresa(bloco):
    casou = _EMPRESA.search(bloco)
    if not casou:
        return ""
    # O selo de "empresa verificada" é um <span> cujo atributo data-bs-title
    # carrega HTML embutido, com '>' DENTRO do valor — isso confunde a remoção
    # de tags, que para no primeiro '>' e come parte do nome. Cortar ali
    # resolve: o nome da empresa sempre vem antes do selo.
    bruto = casou.group(1).split("data-bs-title")[0]
    ultimo_abre, ultimo_fecha = bruto.rfind("<"), bruto.rfind(">")
    if ultimo_abre > ultimo_fecha:  # sobrou uma abertura de tag pendurada
        bruto = bruto[:ultimo_abre]
    return _limpar(bruto)[:120]


def _limpar(bruto):
    return texto.texto_de_html(_TAG.sub("\n", bruto))

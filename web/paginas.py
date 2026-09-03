"""Renderização das páginas.

HTML montado em Python puro, sem motor de template: o site tem sete páginas e
nenhuma delas justifica uma dependência. Duas regras valem para o arquivo
inteiro e não têm exceção:

  * Todo dado que veio de fora passa por `e()` antes de entrar no HTML. As
    descrições, os títulos e os nomes de empresa são texto de terceiros; tratar
    qualquer um deles como confiável é abrir XSS no site inteiro.
  * Nada de `<script>`. O site é server-rendered e navegável sem JavaScript,
    porque um agregador que não é indexável não cumpre o próprio propósito.
"""
import html
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from hirehub import config, db, texto

FUSO = ZoneInfo("America/Sao_Paulo")

DATAS = [
    ("1", "Últimas 24 horas"),
    ("7", "Última semana"),
    ("30", "Último mês"),
    ("", "Qualquer momento"),
]
MODALIDADES = [
    ("remote", "Remoto"),
    ("hybrid", "Híbrido"),
    ("on-site", "Presencial"),
    ("", "Qualquer modalidade"),
]

NAV = [("/", "Início"), ("/vagas", "Vagas"), ("/sobre", "Sobre"), ("/contato", "Contato")]


def _versao_estaticos():
    """Sufixo ?v= para CSS e imagens, derivado do arquivo mais recente.

    Sem isto, o `expires 30d; immutable` do Nginx entregaria o CSS antigo por
    até um mês depois de um deploy — e ninguém liga o layout quebrado do
    visitante a uma mudança feita semanas antes. Calculado uma vez, na carga do
    módulo: o processo reinicia a cada deploy, que é exatamente quando o valor
    precisa mudar.
    """
    try:
        return str(int(max(a.stat().st_mtime
                           for a in config.ESTATICOS.rglob("*") if a.is_file())))
    except ValueError:
        return "0"


VERSAO = _versao_estaticos()


def e(valor):
    """Escapa para HTML. Ponto de passagem obrigatório de todo dado externo."""
    return html.escape(str(valor if valor is not None else ""), quote=True)


def url(base, **params):
    limpos = {k: v for k, v in params.items() if v not in (None, "", 0)}
    return f"{base}?{urllib.parse.urlencode(limpos)}" if limpos else base


# ------------------------------------------------------------------ datas

def _local(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(FUSO)


def data_hora(iso, formato="%d/%m/%Y · %H:%M"):
    d = _local(iso)
    return d.strftime(formato) if d else ""


def ha_quanto(iso):
    """'Publicada há 4 horas'. Sem data, diz que não tem — não inventa."""
    d = _local(iso)
    if not d:
        return "Data não informada"
    delta = datetime.now(FUSO) - d
    minutos = int(delta.total_seconds() // 60)
    if minutos < 1:
        return "Publicada agora"
    if minutos < 60:
        return f"Publicada há {minutos} min"
    if minutos < 1440:
        horas = minutos // 60
        return f"Publicada há {horas} hora{'s' if horas > 1 else ''}"
    dias = minutos // 1440
    if dias < 30:
        return f"Publicada há {dias} dia{'s' if dias > 1 else ''}"
    return f"Publicada em {d:%d/%m/%Y}"


def e_nova(iso):
    d = _local(iso)
    return bool(d and datetime.now(FUSO) - d < timedelta(hours=db.JANELA_NOVA_HORAS))


def numero(n):
    return f"{n:,}".replace(",", ".")


# ------------------------------------------------------------------ layout

def _cabecalho(ctx):
    itens = "".join(
        f'<a href="{caminho}"{" class=\'ativo\'" if ctx["rota"] == caminho else ""}>{rotulo}</a>'
        for caminho, rotulo in NAV
    )
    return f"""
<a class="pular" href="#conteudo">Pular para o conteúdo</a>
<header class="topo">
  <div class="faixa">
    <a class="marca" href="/" aria-label="HireHub — página inicial">
      <img src="/static/img/logo.jpeg?v={VERSAO}" alt="HireHub" width="132" height="45">
    </a>
    <nav class="menu" aria-label="Principal">{itens}</nav>
    <time class="relogio" datetime="{e(ctx['agora'].isoformat())}">
      {e(ctx['agora'].strftime('%d/%m/%Y · %H:%M'))}
    </time>
  </div>
</header>"""


def _rodape(ctx):
    redes = []
    for rotulo, chave in (("LinkedIn", "linkedin"), ("GitHub", "github"),
                          ("Instagram", "instagram"), ("E-mail", "email")):
        destino = config.SITE.get(chave) or ""
        if not destino:
            continue
        href = f"mailto:{destino}" if chave == "email" else destino
        redes.append(f'<a href="{e(href)}" rel="me noopener">{rotulo}</a>')

    links = "".join(f'<a href="{c}">{r}</a>' for c, r in NAV[1:])
    return f"""
<footer class="rodape">
  <div class="faixa">
    <div class="rodape-topo">
      <div class="rodape-marca">
        <strong>HireHub</strong>
        <p>{e(config.SITE['slogan'])}</p>
      </div>
      <nav class="rodape-links" aria-label="Rodapé">{links}</nav>
      <nav class="rodape-redes" aria-label="Redes sociais">{"".join(redes)}</nav>
    </div>
    <div class="rodape-base">
      <span>© {ctx['agora'].year} HireHub</span>
      <span>{numero(ctx['contagens']['total'])} vagas na base ·
        <a href="/status">status das fontes</a></span>
    </div>
  </div>
</footer>"""


def layout(ctx, titulo, conteudo, descricao="", canonica=""):
    titulo_completo = f"{titulo} | HireHub" if titulo else "HireHub"
    descricao = descricao or config.SITE["slogan"]
    canonica = canonica or ctx["rota"]
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titulo_completo)}</title>
<meta name="description" content="{e(descricao[:300])}">
<link rel="canonical" href="{e(config.SITE['url'].rstrip('/') + canonica)}">
<meta property="og:title" content="{e(titulo_completo)}">
<meta property="og:description" content="{e(descricao[:300])}">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/fontes.css?v={VERSAO}">
<link rel="stylesheet" href="/static/estilo.css?v={VERSAO}">
</head>
<body>
{_cabecalho(ctx)}
<main id="conteudo">{conteudo}</main>
{_rodape(ctx)}
</body>
</html>"""


# ------------------------------------------------------------------ pedaços

def _campos_busca(criterios, compacto=False):
    return f"""
<form class="busca{' compacta' if compacto else ''}" action="/vagas" method="get" role="search">
  <div class="campo">
    <label for="q">Palavra-chave</label>
    <input id="q" name="q" type="search" value="{e(criterios.get('q'))}"
           placeholder="Cargo, tecnologia ou palavra-chave" autocomplete="off">
  </div>
  <div class="campo">
    <label for="local">Localização</label>
    <input id="local" name="local" type="search" value="{e(criterios.get('local'))}"
           placeholder="Cidade, estado ou região" autocomplete="off">
  </div>
  <button type="submit">Buscar vagas</button>
</form>"""


def _selo(vaga):
    """Um selo por vaga, e "saiu do ar" ganha da novidade.

    As duas condições podem coincidir (vaga publicada e removida no mesmo dia),
    e nesse caso a informação que muda a decisão de quem lê é a segunda.
    """
    if not vaga.get("no_ar", 1):
        return '<span class="selo-fora">SAIU DO AR</span>'
    if e_nova(vaga.get("publicada_em")):
        return '<span class="selo-nova">NOVA</span>'
    return ""


def _meta_vaga(vaga, fontes_por_id):
    linhas = []
    if vaga.get("local"):
        linhas.append(f'<span class="local">{e(vaga["local"])}</span>')
    if modalidade := config.MODALIDADES.get(vaga.get("modalidade")):
        linhas.append(f'<span class="modalidade">{e(modalidade)}</span>')
    if vaga.get("salario"):
        linhas.append(f'<span class="salario">{e(vaga["salario"])}</span>')
    nome_fonte = fontes_por_id.get(vaga["fonte"], vaga["fonte"])
    linhas.append(f'<span class="fonte">{e(nome_fonte)}</span>')
    return "".join(linhas)


def cartao(vaga, fontes_por_id):
    empresa = e(vaga.get("empresa") or "Empresa não informada")
    return f"""
<article class="cartao">
  {_selo(vaga)}
  <h3><a href="/vaga/{e(vaga['id'])}/{texto.slug(vaga['titulo'])}">{e(vaga['titulo'])}</a></h3>
  <p class="empresa">{empresa}</p>
  <div class="atributos">{_meta_vaga(vaga, fontes_por_id)}</div>
  <div class="rodape-cartao">
    <span class="publicada">{e(ha_quanto(vaga.get('publicada_em')))}</span>
    <a class="cta{'' if vaga.get('no_ar', 1) else ' apagado'}"
       href="{e(vaga['link'])}" target="_blank" rel="noopener nofollow">
      {'Candidatar-se' if vaga.get('no_ar', 1) else 'Ver na origem'}</a>
  </div>
</article>"""


def _atualizacao(meta):
    """Quando foi a última coleta e quando vem a próxima.

    Reforça que o portal é um sistema ativo — e, quando algo trava, é aqui que
    o usuário percebe antes de reclamar.
    """
    gerado = _local(meta.get("geradoEm"))
    if not gerado:
        return '<p class="atualizacao">Primeira coleta ainda não concluída.</p>'
    intervalo = int(meta.get("intervaloHoras") or config.PADROES["intervalo_horas"])
    proxima = gerado + timedelta(hours=intervalo)
    faltam = proxima - datetime.now(FUSO)
    horas = max(0, int(faltam.total_seconds() // 3600))
    quando = f"em aproximadamente {horas}h" if horas else "a qualquer momento"
    return (f'<p class="atualizacao">Última atualização: {gerado:%d/%m/%Y às %H:%M}'
            f' · Próxima atualização {quando}</p>')


def _paginacao(base, criterios, pagina, total, por_pagina):
    ultima = max(0, (total - 1) // por_pagina)
    if ultima == 0:
        return ""
    janela = [p for p in range(pagina - 2, pagina + 3) if 0 <= p <= ultima]
    links = []
    if pagina > 0:
        links.append(f'<a href="{url(base, **criterios, pagina=pagina - 1)}" rel="prev">Anterior</a>')
    for p in janela:
        if p == pagina:
            links.append(f'<span class="atual" aria-current="page">{p + 1}</span>')
        else:
            links.append(f'<a href="{url(base, **criterios, pagina=p)}">{p + 1}</a>')
    if pagina < ultima:
        links.append(f'<a href="{url(base, **criterios, pagina=pagina + 1)}" rel="next">Próxima</a>')
    return f'<nav class="paginacao" aria-label="Paginação">{"".join(links)}</nav>'


def _filtros(criterios, fontes_disponiveis):
    def grupo(nome, rotulo, opcoes, selecionado):
        itens = "".join(
            f'<option value="{e(v)}"{" selected" if str(selecionado) == v else ""}>{e(r)}</option>'
            for v, r in opcoes
        )
        return f"""<div class="filtro">
          <label for="f-{nome}">{rotulo}</label>
          <select id="f-{nome}" name="{nome}">{itens}</select>
        </div>"""

    plataformas = [(f["id"], f["nome"]) for f in fontes_disponiveis] + [("", "Todas")]
    ocultos = "".join(
        f'<input type="hidden" name="{k}" value="{e(criterios.get(k))}">'
        for k in ("q", "local") if criterios.get(k)
    )
    return f"""
<form class="filtros" action="/vagas" method="get">
  {ocultos}
  {grupo("dias", "Data de publicação", DATAS, criterios.get("dias") or "")}
  {grupo("modalidade", "Modalidade", MODALIDADES, criterios.get("modalidade") or "")}
  {grupo("fonte", "Plataforma", plataformas, criterios.get("fonte") or "")}
  <div class="filtro-caixa">
    <input type="checkbox" id="f-fora" name="fora" value="1"
           {"checked" if criterios.get("incluir_fora_do_ar") else ""}>
    <label for="f-fora">Incluir vagas que saíram do ar</label>
  </div>
  <button type="submit">Aplicar filtros</button>
  <a class="limpar" href="{url("/vagas", q=criterios.get("q"), local=criterios.get("local"))}">Limpar</a>
</form>"""


def _tira_fontes(fontes, compacta=True):
    if not fontes:
        return ""
    itens = []
    for f in fontes:
        estado, rotulo = situacao(f)
        itens.append(f'<li class="{estado}"><span class="ponto"></span>'
                     f'{e(f["nome"])}<em>{rotulo}</em></li>')
    return (f'<section class="tira-fontes"><h2>Fontes</h2><ul>{"".join(itens)}</ul>'
            f'<a href="/status">Ver status detalhado</a></section>')


def situacao(fonte):
    """Estado de uma fonte, derivado do que a última coleta registrou.

    "Sem retorno" é uma categoria própria, separada de "falha": a Sólides
    responde 200 e devolve zero vagas. Tratar isso como sucesso esconderia a
    quebra; tratar como erro seria mentir sobre o que aconteceu.
    """
    if fonte.get("erro"):
        return "erro", "Falha na última coleta"
    if not fonte.get("ultimo_ok"):
        return "erro", "Nunca coletada"
    if not fonte.get("vagas"):
        return "alerta", "Sem retorno"
    return "ok", "Operacional"


# ------------------------------------------------------------------ páginas

def home(ctx, recentes, fontes):
    contagens = ctx["contagens"]
    cartoes = "".join(cartao(v, ctx["fontes_por_id"]) for v in recentes)
    return layout(ctx, "", f"""
<section class="hero">
  <div class="faixa">
    <h1>O hub das oportunidades</h1>
    <p class="sub">Vagas da Gupy, da InHire, da Sólides e do InfoJobs reunidas
       em um só lugar. Sem cadastro, sem login, de graça.</p>
    {_campos_busca({})}
    <ul class="numeros">
      <li><strong>{numero(contagens['total'])}</strong> vagas na base</li>
      <li><strong>{numero(contagens['novas'])}</strong> publicadas nas últimas 24h</li>
      <li><strong>{numero(contagens['empresas'])}</strong> empresas</li>
    </ul>
  </div>
</section>
<section class="faixa bloco">
  <div class="titulo-bloco">
    <h2>Vagas mais recentes</h2>
    <a class="ver-tudo" href="/vagas">Ver todas as vagas</a>
  </div>
  {_atualizacao(ctx['meta'])}
  <div class="grade">{cartoes}</div>
</section>
<div class="faixa">{_tira_fontes(fontes)}</div>
""", descricao=config.SITE["slogan"], canonica="/")


def listagem(ctx, criterios, pagina, total, vagas, fontes):
    cartoes = "".join(cartao(v, ctx["fontes_por_id"]) for v in vagas) or """
      <p class="vazio">Nenhuma vaga encontrada com esses critérios.
      Tente uma palavra-chave mais ampla ou remova algum filtro.</p>"""
    # A paginação precisa carregar o estado dos filtros. `incluir_fora_do_ar` é
    # booleano interno e vira `fora=1` na URL, que é o nome que o formulário usa.
    filtros_url = {k: v for k, v in criterios.items()
                   if v and k != "incluir_fora_do_ar"}
    if criterios.get("incluir_fora_do_ar"):
        filtros_url["fora"] = "1"
    titulo = "Vagas"
    if criterios.get("q"):
        titulo = f"Vagas de {criterios['q']}"
    if criterios.get("local"):
        titulo += f" em {criterios['local']}"
    return layout(ctx, titulo, f"""
<section class="faixa bloco">
  <h1>{e(titulo)}</h1>
  {_campos_busca(criterios, compacto=True)}
  {_filtros(criterios, fontes)}
  <div class="resultado">
    <p class="contador"><strong>{numero(total)}</strong>
       {"vaga encontrada" if total == 1 else "vagas encontradas"}</p>
    {_atualizacao(ctx['meta'])}
  </div>
  <div class="grade">{cartoes}</div>
  {_paginacao("/vagas", filtros_url, pagina, total, db.POR_PAGINA)}
</section>
""", descricao=f"{numero(total)} vagas de {titulo.lower()} reunidas de várias plataformas.")


def detalhes(ctx, vaga, relacionadas):
    nome_fonte = ctx["fontes_por_id"].get(vaga["fonte"], vaga["fonte"])
    linhas = [f'<li><span>Empresa</span>{e(vaga.get("empresa") or "Não informada")}</li>']
    if vaga.get("local"):
        linhas.append(f'<li><span>Local</span>{e(vaga["local"])}</li>')
    if modalidade := config.MODALIDADES.get(vaga.get("modalidade")):
        linhas.append(f'<li><span>Modalidade</span>{e(modalidade)}</li>')
    if vaga.get("salario"):
        linhas.append(f'<li><span>Salário</span>{e(vaga["salario"])}</li>')
    linhas.append(f'<li><span>Plataforma</span>{e(nome_fonte)}</li>')
    if publicada := data_hora(vaga.get("publicada_em"), "%d/%m/%Y"):
        linhas.append(f'<li><span>Publicada em</span>{publicada}</li>')

    if vaga.get("descricao"):
        # Texto puro vindo de terceiros: escapado inteiro e depois quebrado em
        # parágrafos. Em nenhum momento o HTML da origem é reaproveitado.
        paragrafos = "".join(
            f"<p>{e(bloco)}</p>" for bloco in vaga["descricao"].split("\n") if bloco.strip())
        corpo = f'<section class="descricao"><h2>Descrição da vaga</h2>{paragrafos}</section>'
    else:
        corpo = """<section class="descricao aviso">
          <h2>Descrição</h2>
          <p>A descrição completa desta vaga está disponível na plataforma de
             origem. Use o botão abaixo para abri-la.</p>
        </section>"""

    outras = "".join(cartao(v, ctx["fontes_por_id"]) for v in relacionadas)
    bloco_relacionadas = f"""
      <section class="relacionadas">
        <h2>Vagas parecidas</h2>
        <div class="grade">{outras}</div>
      </section>""" if outras else ""

    no_ar = vaga.get("no_ar", 1)
    # A vaga abre mesmo fora do ar (ver db.por_id), mas o aviso vem ANTES do
    # botão: quem chegou por um link antigo precisa saber disso antes de
    # clicar, não depois de bater numa página de erro na plataforma de origem.
    if no_ar:
        alerta = ""
        acao = f"Candidatar-se em {e(nome_fonte)}"
    else:
        alerta = """<p class="alerta-fora"><strong>Esta vaga saiu do ar.</strong>
           Ela não apareceu na última coleta da plataforma de origem, o que
           costuma significar que o anúncio foi encerrado. O link abaixo pode
           não funcionar mais.</p>"""
        acao = f"Ver na {e(nome_fonte)}"

    resumo = (vaga.get("descricao") or "")[:280] or \
        f"{vaga['titulo']} na {vaga.get('empresa') or 'empresa'}."
    return layout(ctx, vaga["titulo"], f"""
<section class="faixa bloco detalhe">
  <a class="voltar" href="/vagas">← Voltar para vagas</a>
  {_selo(vaga)}
  <h1>{e(vaga['titulo'])}</h1>
  <p class="empresa-grande">{e(vaga.get('empresa') or 'Empresa não informada')}</p>
  <ul class="ficha">{"".join(linhas)}</ul>
  {alerta}
  <a class="cta grande{'' if no_ar else ' apagado'}"
     href="{e(vaga['link'])}" target="_blank" rel="noopener nofollow">{acao}</a>
  <p class="aviso-externo">A candidatura acontece no site da plataforma de
     origem. O HireHub não recebe currículos nem dados pessoais.</p>
  {corpo}
  {bloco_relacionadas}
</section>
""", descricao=resumo, canonica=f"/vaga/{vaga['id']}")


def sobre(ctx):
    return layout(ctx, "Sobre", f"""
<section class="faixa bloco texto">
  <h1>Sobre o HireHub</h1>
  <h2>O que é</h2>
  <p>O HireHub é um agregador de oportunidades que reúne vagas de diferentes
     plataformas de emprego em um único lugar. O objetivo é tornar a busca por
     oportunidades mais simples, rápida e centralizada.</p>
  <h2>Como funciona</h2>
  <ol class="fluxo">
    <li>As plataformas publicam suas vagas</li>
    <li>O HireHub coleta automaticamente, a cada
        {e(ctx['meta'].get('intervaloHoras') or config.PADROES['intervalo_horas'])} horas</li>
    <li>Organiza e normaliza os dados numa base própria</li>
    <li>Disponibiliza tudo em uma única busca</li>
    <li>Você encontra uma oportunidade</li>
    <li>E se candidata na plataforma original</li>
  </ol>
  <h2>O que o HireHub não faz</h2>
  <p>O HireHub não é responsável pelo processo seletivo. As candidaturas são
     realizadas diretamente nas plataformas responsáveis pela publicação da
     vaga. Não há cadastro, login, currículo nem área do candidato — nenhum
     dado pessoal é coletado ou armazenado.</p>
  <h2>Fontes atuais</h2>
  <p>{", ".join(e(f.nome) for f in ctx['fontes_registradas'])}. A arquitetura
     é modular: novas plataformas entram como conectores independentes.</p>
</section>
""", descricao="O que é o HireHub, como a coleta funciona e o que ele não faz.")


def contato(ctx):
    itens = []
    for rotulo, chave, prefixo in (("E-mail", "email", "mailto:"),
                                   ("LinkedIn", "linkedin", ""),
                                   ("GitHub", "github", ""),
                                   ("Instagram", "instagram", "")):
        destino = config.SITE.get(chave) or ""
        if destino:
            itens.append(f'<li><span>{rotulo}</span>'
                         f'<a href="{e(prefixo + destino)}" rel="noopener">{e(destino)}</a></li>')
    return layout(ctx, "Contato", f"""
<section class="faixa bloco texto">
  <h1>Entre em contato</h1>
  <p>Encontrou uma vaga com informação errada, quer sugerir uma plataforma nova
     ou só falar sobre o projeto? Qualquer um destes canais serve.</p>
  <ul class="contatos">{"".join(itens)}</ul>
  <h2>Sobre vagas específicas</h2>
  <p>O HireHub apenas indexa e redireciona. Dúvidas sobre uma vaga, sobre o
     processo seletivo ou sobre uma candidatura precisam ir para a empresa ou
     para a plataforma onde ela foi publicada.</p>
</section>
""", descricao="Canais de contato do HireHub.")


def status(ctx, fontes):
    if not fontes:
        corpo = '<p class="vazio">Nenhuma coleta registrada ainda.</p>'
    else:
        linhas = []
        for f in fontes:
            estado, rotulo = situacao(f)
            detalhe = e(f["erro"]) if f.get("erro") else (
                f'{numero(f.get("vagas") or 0)} vagas · {numero(f.get("novas") or 0)} novas'
                f' · {(f.get("duracao") or 0):.0f}s')
            linhas.append(f"""
              <li class="{estado}">
                <div class="linha-fonte">
                  <span class="ponto"></span>
                  <strong>{e(f['nome'])}</strong>
                  <em>{rotulo}</em>
                </div>
                <p class="detalhe-fonte">{detalhe}</p>
                <p class="quando">Última coleta:
                   {e(data_hora(f.get('ultima_coleta')) or '—')}</p>
              </li>""")
        corpo = f'<ul class="status-fontes">{"".join(linhas)}</ul>'

    return layout(ctx, "Status das integrações", f"""
<section class="faixa bloco texto">
  <h1>Status das integrações</h1>
  {_atualizacao(ctx['meta'])}
  {corpo}
  <h2>Como ler esta página</h2>
  <p><strong>Operacional</strong> — a última coleta trouxe vagas normalmente.<br>
     <strong>Sem retorno</strong> — a plataforma respondeu, mas não devolveu
     nenhuma vaga. Costuma ser mudança na API de origem.<br>
     <strong>Falha</strong> — a coleta terminou em erro. O motivo aparece ao lado.</p>
  <p>As vagas já coletadas continuam no ar mesmo quando uma fonte falha: a base
     é acumulada, e uma coleta ruim não apaga as anteriores.</p>
</section>
""", descricao="Situação de cada plataforma integrada ao HireHub.")


def erro(ctx, codigo, mensagem):
    return layout(ctx, mensagem, f"""
<section class="faixa bloco texto centro">
  <p class="codigo">{codigo}</p>
  <h1>{e(mensagem)}</h1>
  <p>A página que você procurou não existe, ou a vaga saiu do ar.</p>
  <a class="cta" href="/vagas">Ver as vagas disponíveis</a>
</section>
""")

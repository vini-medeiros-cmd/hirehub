"""Normalização de texto: o "N" de coletar → normalizar → armazenar.

Cada plataforma escreve a mesma informação de um jeito. Tudo o que
uniformiza dado bruto mora aqui, para os conectores só traduzirem os campos.
"""
import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?\s*>", re.I)
_ESPACOS = re.compile(r"[ \t]+")
_LINHAS = re.compile(r"\n{3,}")


def sem_acento(texto):
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )


def chave_busca(*partes):
    """Forma canônica usada nas colunas de busca do banco.

    Existe para a busca ser insensível a acento: quem digita "macae" precisa
    achar "Macaé", e o LIKE do SQLite não faz isso sozinho — ele compara byte a
    byte. Normalizamos na gravação para poder normalizar também na consulta.
    """
    junto = " ".join(p for p in partes if p)
    return _ESPACOS.sub(" ", sem_acento(junto).lower()).strip()


def slug(texto, padrao="vaga"):
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(texto).lower()).strip("-") or padrao


def id_da_vaga(link):
    """Identificador estável e curto para a URL de detalhes.

    Derivado do link de origem, não de um autoincremento: o mesmo anúncio
    recebe sempre o mesmo id, então /vaga/<id> continua válido entre coletas —
    e entre reconstruções do banco do zero.
    """
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def texto_de_html(bruto, limite=20000):
    """HTML de descrição → texto puro, preservando quebras de parágrafo.

    Guardamos texto, não HTML: as descrições vêm de várias plataformas
    diferentes, com marcação arbitrária e estilos embutidos. Renderizar isso
    cru na nossa página é convite a HTML quebrado e a XSS.
    """
    if not bruto:
        return ""
    texto = _BR.sub("\n", bruto)
    texto = _TAG.sub(" ", texto)
    texto = html.unescape(texto)
    texto = "\n".join(_ESPACOS.sub(" ", l).strip() for l in texto.split("\n"))
    return _LINHAS.sub("\n\n", texto).strip()[:limite]


def modalidade(valor):
    """Vocabulário de cada fonte → remote | hybrid | on-site (ou vazio)."""
    v = sem_acento(str(valor or "")).lower()
    if "remot" in v or "home office" in v or "home-office" in v:
        return "remote"
    if "hibrid" in v or "hybrid" in v:
        return "hybrid"
    if "on-site" in v or "onsite" in v or "presenc" in v:
        return "on-site"
    return ""


# A InHire devolve o local como código de país cru ("BR"), não como nome. Sem
# esta tradução o card exibe "BR", que não diz nada a quem está procurando vaga.
PAISES = {"BR": "Brasil", "PT": "Portugal", "US": "Estados Unidos",
          "AR": "Argentina", "MX": "México", "CL": "Chile", "CO": "Colômbia"}

# A Gupy manda o estado por extenso ("Minas Gerais"); as outras três mandam a
# sigla. Uniformizar na sigla resolve duas coisas de uma vez: o dado deixa de
# depender da fonte, e o badge do card encolhe de "Belo Horizonte, Minas
# Gerais" para "Belo Horizonte, MG" — que é o que faz caber três cards por
# linha sem quebrar em duas linhas.
UFS = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}


def local(*partes):
    """Junta pedaços de localização num texto só, em ordem de especificidade.

    Aceita tanto campos separados (cidade, estado, país) quanto uma string
    única já com vírgulas, que é como algumas fontes entregam.
    """
    pedacos = []
    for parte in partes:
        for pedaco in str(parte or "").split(","):
            pedaco = pedaco.strip()
            if pedaco:
                pedacos.append(PAISES.get(pedaco.upper(), pedaco))

    # Remove repetições preservando a ordem. A comparação ignora acento porque
    # as fontes se contradizem dentro do MESMO registro: a Gupy manda cidade
    # "Sao Paulo" e estado "São Paulo", e comparar as strings cruas deixava
    # "Sao Paulo, São Paulo" no card. Entre duas grafias iguais, fica a
    # acentuada — é a correta em português.
    unicos = {}
    for pedaco in pedacos:
        chave = sem_acento(pedaco).lower()
        anterior = unicos.get(chave)
        if anterior is None or (anterior == sem_acento(anterior) != pedaco):
            unicos[chave] = pedaco
    unicos = list(unicos.values())

    # Estado por extenso vira sigla — mas só quando não é a única informação.
    # Uma vaga que só diz "Bahia" precisa continuar dizendo "Bahia": "BA"
    # sozinho num card, sem cidade antes, lê-se como abreviação solta.
    if len(unicos) > 1:
        unicos = [UFS.get(sem_acento(p).lower(), p) if i else p
                  for i, p in enumerate(unicos)]
        # A troca pode ter criado repetição: "Rio de Janeiro, Rio de Janeiro"
        # vira "Rio de Janeiro, RJ", mas "RJ, Rio de Janeiro" viraria "RJ, RJ".
        unicos = list(dict.fromkeys(unicos))
    # "Brasil" só informa quando é a única coisa que se sabe.
    if len(unicos) > 1 and sem_acento(unicos[-1]).lower() in ("brasil", "brazil"):
        unicos.pop()
    return ", ".join(unicos)


def data_iso(valor):
    """Qualquer carimbo das fontes → ISO 8601 em UTC, ou None.

    Datas sem fuso são tratadas como UTC. É uma aproximação assumida: nenhuma
    das fontes documenta o fuso, e o erro máximo (3h) não muda nada num filtro
    cuja menor granularidade é "últimas 24 horas".
    """
    if not valor:
        return None
    if isinstance(valor, (int, float)):
        segundos = valor / 1000 if valor > 1e11 else valor
        return datetime.fromtimestamp(segundos, timezone.utc).isoformat()
    texto = str(valor).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def agora_iso():
    return datetime.now(timezone.utc).isoformat()

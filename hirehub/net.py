"""Camada HTTP dos conectores.

Regra que vale para as duas funções: uma requisição que falha devolve None em
vez de levantar exceção. Uma página quebrada não pode derrubar a varredura
inteira de uma fonte, muito menos a coleta das outras.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# A API da InHire responde 403 para User-Agent de cliente HTTP padrão. Sem isto,
# tudo volta vazio e sem erro aparente — o pior tipo de falha.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 20


def _abrir(url, headers, aceita, tentativas):
    pedido = urllib.request.Request(
        url, headers={"Accept": aceita, "User-Agent": USER_AGENT, **(headers or {})}
    )
    for tentativa in range(tentativas + 1):
        try:
            with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:
                return resposta.read()
        except urllib.error.HTTPError as erro:
            if erro.code == 429:
                # Limite de taxa. Insistir é o pior movimento possível: só
                # aprofunda o bloqueio. Sai na hora e deixa o chamador tratar
                # como falha transitória — o Retry-After costuma vir em horas.
                _avisar_limite(url, erro)
                return None
            if erro.code < 500:
                return None  # 4xx é definitivo: insistir só gasta tempo
        except Exception:
            pass
        if tentativa < tentativas:
            time.sleep(0.5 * (2 ** tentativa))  # backoff exponencial
    return None


# Domínios que responderam 429 nesta execução: {domínio: epoch de liberação}.
# O orquestrador consulta isto para persistir a espera e não voltar antes.
LIMITES = {}
# Teto para o Retry-After. Um cabeçalho absurdo (ou malformado) não pode
# desligar uma fonte por semanas — passado o teto, tentamos de novo.
MAX_ESPERA = 48 * 3600


def limite_de(url):
    """Até quando este domínio pediu para não ser incomodado. None se não pediu."""
    return LIMITES.get(urllib.parse.urlparse(url).netloc)


def _avisar_limite(url, erro):
    """Registra e avisa uma vez por domínio, não uma vez por requisição.

    Sem isso, um bloqueio de taxa vira milhares de linhas idênticas no log e
    esconde justamente a informação que interessa — que a origem parou de
    responder e por quanto tempo.
    """
    dominio = urllib.parse.urlparse(url).netloc
    try:
        espera = min(int(erro.headers.get("Retry-After", "3600")), MAX_ESPERA)
    except (TypeError, ValueError):
        espera = 3600  # veio em formato de data, ou não veio; uma hora serve
    if dominio in LIMITES:
        return
    LIMITES[dominio] = time.time() + espera
    print(f"[hirehub] {dominio} respondeu 429 (limite de taxa). "
          f"Aguardando {espera / 3600:.1f}h antes de tentar de novo.", flush=True)


def json_de(url, headers=None, tentativas=2):
    corpo = _abrir(url, headers, "application/json", tentativas)
    if corpo is None:
        return None
    try:
        return json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def html_de(url, headers=None, tentativas=1):
    """Como json_de, mas sem `Accept: application/json` — a maioria dos sites
    recusa esse cabeçalho em rotas que servem página."""
    corpo = _abrir(url, headers, "text/html", tentativas)
    return corpo.decode("utf-8", errors="replace") if corpo is not None else None


def url_com(base, **params):
    limpos = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{base}?{urllib.parse.urlencode(limpos)}"


def em_paralelo(funcao, itens, threads):
    """map paralelo com uma garantia a mais: um item que explode vira None em vez
    de matar o lote inteiro. Um tenant fora do ar não pode custar os outros 8.700."""
    def protegida(item):
        try:
            return funcao(item)
        except Exception:
            return None

    itens = list(itens)
    if not itens:
        return []
    with ThreadPoolExecutor(max_workers=max(1, threads)) as executor:
        return list(executor.map(protegida, itens))

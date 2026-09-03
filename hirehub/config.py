"""Caminhos e configuração.

A configuração é um JSON opcional em data/hirehub.config.json. Tudo tem padrão,
então o projeto roda sem nenhum arquivo de config — o JSON só existe para ajustar
profundidade de coleta e intervalo sem mexer no código.
"""
import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HIREHUB_DATA", RAIZ / "data"))
CACHE_DIR = DATA_DIR / "cache"
BANCO = DATA_DIR / "hirehub.db"
LOCK = CACHE_DIR / "coleta.lock"
CONFIG_FILE = DATA_DIR / "hirehub.config.json"
ESTATICOS = RAIZ / "web" / "static"

SITE = {
    "nome": "HireHub",
    "slogan": "O hub das oportunidades, seu próximo emprego começa aqui.",
    # AINDA PROVISÓRIO: é daqui que saem as URLs canônicas, o sitemap e o
    # robots.txt. Aponte HIREHUB_URL para o domínio real antes de publicar, ou
    # os buscadores vão indexar um endereço que não existe.
    "url": os.environ.get("HIREHUB_URL", "https://hirehub.com.br"),
    "email": "viniciusrangelm@gmail.com",
    "linkedin": "https://www.linkedin.com/in/viniciusrmedeiros/",
    "github": "https://github.com/vini-medeiros-cmd",
    # Vazio some do rodapé e da página de contato, em vez de virar link morto.
    "instagram": "",
}

PADROES = {
    # Termos extras de busca na Gupy. Cada termo abre uma janela ADICIONAL de
    # 10.000 vagas (o teto da API), para alcançar anúncios mais antigos de uma
    # área específica. Vazio = só a janela geral das mais recentes.
    "gupy_termos": [],
    # Páginas da Sólides por execução (12 vagas cada, teto da API).
    "solides_paginas": 150,
    # Páginas por cidade/modalidade no InfoJobs (20 vagas cada).
    "infojobs_paginas_por_cidade": 3,
    # Requisições de detalhe por fonte, por execução. Segura o tempo de cada
    # rodada; o cache converge ao longo das execuções seguintes.
    "detalhes_por_execucao": 400,
    # Vaga que sumiu da origem continua listada por este tanto de dias.
    "esquecer_apos_dias": 60,
    # A rede é o gargalo, não a CPU. Subir muito só irrita as APIs de origem.
    "threads": 6,
    # Horas entre coletas. Usado pelo agendador e pelo aviso de "próxima
    # atualização" no site.
    "intervalo_horas": 6,
}

# Modalidades canônicas. Toda fonte normaliza para uma destas.
MODALIDADES = {
    "remote": "Remoto",
    "hybrid": "Híbrido",
    "on-site": "Presencial",
}


def carregar():
    """Config efetiva: padrões sobrescritos pelo JSON, se existir."""
    try:
        do_arquivo = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        do_arquivo = {}
    return {**PADROES, **do_arquivo}

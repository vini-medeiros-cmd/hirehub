"""Registro de conectores.

Cada plataforma é um módulo independente nesta pasta. Adicionar uma fonte nova
é criar um arquivo aqui e decorar a classe com @registrar — nada no núcleo
muda, porque a descoberta é feita varrendo o pacote, não por uma lista escrita
à mão em algum lugar que alguém vai esquecer de atualizar.
"""
import importlib
import pkgutil

_REGISTRO = {}


class Fonte:
    """Contrato de um conector.

    `coletar` é obrigatório e devolve dicionários já normalizados:

        {link, titulo, empresa, fonte, local, modalidade, salario,
         publicada_em, descricao}

    Só `link` e `titulo` são realmente obrigatórios; o resto pode vir vazio,
    porque nem toda plataforma publica tudo.

    Pode devolver lista OU gerador. Gerador é preferível em fonte grande: o
    orquestrador grava em lotes conforme consome, e o pico de memória passa a
    depender do lote em vez do tamanho do acervo. A Gupy virou geradora quando
    passou de 43.000 vagas com descrição e o pico chegou a 540 MB.

    `detalhar` é opcional. Existe para as fontes cuja listagem não traz tudo e
    é preciso uma requisição por vaga para completar. Recebe {id, link} e
    devolve os campos a atualizar (descricao, publicada_em, salario, local,
    modalidade) ou None se não conseguiu. Quem não implementa simplesmente não
    é enriquecido — a página de detalhes se vira com os metadados.
    """

    id = ""
    nome = ""
    site = ""

    # A fonte devolve TODAS as vagas publicadas, ou só uma janela delas?
    #
    # É o que decide se "esta vaga não veio na última coleta" pode ser lido como
    # "esta vaga foi encerrada". Numa fonte exaustiva, pode. Numa fonte com
    # janela — a Gupy entrega as 10.000 mais recentes, o InfoJobs as primeiras
    # páginas de cada cidade —, a vaga some da coleta porque chegaram outras
    # mais novas, e concluir que fechou marca como morta uma vaga aberta
    # publicada hoje. Medido: numa coleta só da Gupy, 1.740 vagas publicadas nos
    # últimos 3 dias saíram da janela e seriam escondidas do site.
    #
    # Só quem marca True participa da regra de "saiu do ar" (ver db.NO_AR).
    cobertura_completa = False

    # Tetos próprios, para fontes que não aguentam o ritmo geral. None = usa a
    # configuração global. Nunca sobem além dela: são limites, não permissões.
    #
    # Existem porque a Vagas.com.br respondeu 429 com Retry-After de 24 HORAS
    # depois de 968 páginas de detalhe a 8 threads. Volume de coleta não é só
    # questão de tempo de execução — é de não ser bloqueado pela origem.
    threads = None
    detalhes_por_execucao = None

    def coletar(self, cfg, log):
        raise NotImplementedError

    detalhar = None


def registrar(cls):
    instancia = cls()
    if not instancia.id:
        raise ValueError(f"{cls.__name__} precisa de um id")
    _REGISTRO[instancia.id] = instancia
    return cls


def todas():
    if not _REGISTRO:
        for info in pkgutil.iter_modules(__path__):
            importlib.import_module(f"{__name__}.{info.name}")
    return [_REGISTRO[k] for k in sorted(_REGISTRO)]


def por_id(id_fonte):
    todas()
    return _REGISTRO.get(id_fonte)

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

    `detalhar` é opcional. Existe para as fontes cuja listagem não traz tudo e
    é preciso uma requisição por vaga para completar. Recebe {id, link} e
    devolve os campos a atualizar (descricao, publicada_em, salario, local,
    modalidade) ou None se não conseguiu. Quem não implementa simplesmente não
    é enriquecido — a página de detalhes se vira com os metadados.
    """

    id = ""
    nome = ""
    site = ""

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

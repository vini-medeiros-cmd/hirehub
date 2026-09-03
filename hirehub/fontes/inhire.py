"""InHire — cobertura completa, ao custo de uma lista de empresas.

A InHire não tem busca global: cada requisição é de UMA empresa, selecionada
pelo header X-Tenant. Por isso data/inhire-tenants.json não é um detalhe de
configuração — é o que torna a busca possível. Em compensação, o que vem, vem
inteiro: todas as vagas publicadas de cada empresa da lista, sem teto de
paginação.

A listagem não traz data nem descrição, mas o detalhe traz os dois na MESMA
requisição. Por isso `detalhar` devolve os dois de uma vez: enriquecer a
descrição sai de graça, já que a data sozinha exigiria a mesma chamada.
"""
import json
import re

from .. import config, net, texto
from . import Fonte, registrar

API = "https://api.inhire.app/job-posts/public/pages"
TENANTS = config.DATA_DIR / "inhire-tenants.json"
_LINK = re.compile(r"https://([^.]+)\.inhire\.app/vagas/([^/]+)")


def _cabecalhos(tenant):
    return {"X-Inhire-Client": "web-inhire", "X-Tenant": tenant}


@registrar
class InHire(Fonte):
    id = "inhire"
    nome = "InHire"
    site = "https://inhire.app"
    # Única das quatro: sem teto de paginação, cada empresa devolve o mural
    # inteiro. Por isso é a única em que "não veio na coleta" significa mesmo
    # "a vaga foi encerrada" — ver Fonte.cobertura_completa.
    cobertura_completa = True

    def coletar(self, cfg, log):
        empresas = self._empresas()
        if not empresas:
            raise RuntimeError(
                f"{TENANTS.name} ausente ou vazio — rode bin/atualizar-tenants.py")
        log(f"consultando {len(empresas)} empresas")
        murais = net.em_paralelo(self._mural, empresas, cfg["threads"])
        return [vaga for mural in murais if mural for vaga in mural]

    @staticmethod
    def _empresas():
        try:
            dados = json.loads(TENANTS.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return [e for e in dados if e.get("slug")]

    @staticmethod
    def _mural(empresa):
        dados = net.json_de(API, _cabecalhos(empresa["slug"]))
        if not dados or not dados.get("tenantName"):
            return []
        nome = (dados["tenantName"] or "").strip() or empresa.get("name", "")
        vagas = []
        for bruta in dados.get("jobsPage") or []:
            if str(bruta.get("status", "")).lower() != "published":
                continue
            titulo = (bruta.get("displayName") or "").strip()
            job_id = bruta.get("jobId")
            if not titulo or not job_id:
                continue
            vagas.append({
                "link": f"https://{empresa['slug']}.inhire.app/vagas/{job_id}/{texto.slug(titulo)}",
                "titulo": titulo,
                "empresa": nome,
                "fonte": "inhire",
                "local": texto.local(bruta.get("location")),
                "modalidade": texto.modalidade(bruta.get("workplaceType")),
                "salario": "",
                # Ambos só existem no detalhe. Ver detalhar().
                "descricao": None,
                "publicada_em": None,
            })
        return vagas

    @staticmethod
    def detalhar(vaga):
        casou = _LINK.match(vaga["link"])
        if not casou:
            return None
        tenant, job_id = casou.groups()
        dados = net.json_de(f"{API}/{job_id}", _cabecalhos(tenant), tentativas=1)
        if not dados:
            return None
        return {
            "descricao": texto.texto_de_html(dados.get("description")),
            "publicada_em": texto.data_iso(
                dados.get("publishedAt") or dados.get("lastPublishedAt")),
            "local": texto.local(dados.get("location"),
                                 dados.get("locationComplement")) or None,
            "modalidade": texto.modalidade(dados.get("workplaceType")) or None,
        }

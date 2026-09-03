#!/usr/bin/env python3
"""Redescobre as empresas da InHire e regrava data/inhire-tenants.json.

Por que existe: a InHire não tem busca global nem diretório público de
empresas. Cada empresa é um subdomínio (`<slug>.inhire.app`) e a API só
responde por tenant. A lista É o produto — sem ela, a fonte inteira some.

Ela envelhece conforme empresas entram e saem da plataforma, então convém
rodar de tempos em tempos (mensalmente já é bastante).

Duas origens, ambas públicas e sem chave:
  * Wayback CDX — histórico de URLs arquivadas em *.inhire.app
  * urlscan.io  — scans públicos do mesmo domínio

Cada candidato é validado contra a API antes de entrar no arquivo: subdomínio
que existiu um dia não é o mesmo que empresa com mural no ar hoje.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hirehub import config, net  # noqa: E402

API = "https://api.inhire.app/job-posts/public/pages"
DESTINO = config.DATA_DIR / "inhire-tenants.json"
THREADS = 8

# Subdomínios da própria infraestrutura da InHire, não são empresas.
NAO_SAO_EMPRESAS = {
    "api", "auth", "www", "app", "admin", "status", "sso-setup", "saml-setup",
    "inhire-admin", "data-viz", "inhub", "demo", "staging", "hml",
}
_SLUG = re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.inhire\.app", re.I)


def do_wayback():
    url = ("https://web.archive.org/cdx/search/cdx?url=*.inhire.app"
           "&output=json&fl=original&collapse=urlkey&limit=200000")
    linhas = net.json_de(url, tentativas=1) or []
    return [s for (original, *_) in linhas[1:] if (s := _slug(original))]


def do_urlscan():
    url = "https://urlscan.io/api/v1/search/?q=page.domain%3Ainhire.app&size=100"
    dados = net.json_de(url, tentativas=1) or {}
    return [s for r in dados.get("results", [])
            if (s := _slug("https://" + (r.get("page") or {}).get("domain", "")))]


def _slug(url):
    casou = _SLUG.match(url or "")
    if not casou:
        return None
    slug = casou.group(1).lower()
    return None if slug in NAO_SAO_EMPRESAS else slug


def validar(slug):
    """Devolve {slug, name} se a empresa tem mural respondendo, senão None."""
    dados = net.json_de(
        API, {"X-Inhire-Client": "web-inhire", "X-Tenant": slug}, tentativas=1)
    nome = (dados or {}).get("tenantName")
    return {"slug": slug, "name": nome.strip()} if nome and nome.strip() else None


def main():
    anteriores = []
    try:
        anteriores = json.loads(DESTINO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    candidatos = sorted({
        *(e["slug"] for e in anteriores if e.get("slug")),
        *do_wayback(),
        *do_urlscan(),
    })
    print(f"{len(candidatos)} candidatos ({len(anteriores)} já no arquivo). Validando...")

    validos = [e for e in net.em_paralelo(validar, candidatos, THREADS) if e]
    validos.sort(key=lambda e: e["slug"])

    if not validos:
        print("Nenhuma empresa validou. Arquivo mantido como estava.")
        return 1

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    tmp = DESTINO.with_suffix(".tmp")
    tmp.write_text(json.dumps(validos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DESTINO)

    print(f"{len(validos)} empresas gravadas em {DESTINO} "
          f"({len(validos) - len(anteriores):+d} em relação ao arquivo anterior).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

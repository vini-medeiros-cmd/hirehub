"""Servidor HTTP do HireHub.

http.server da biblioteca padrão, em modo threading. A escolha é deliberada: o
site é só leitura, cada resposta é uma consulta SQLite indexada e o alvo é uma
VPS gratuita. Colocar um framework e um servidor de aplicação aqui adicionaria
dependências, memória e superfície de manutenção para resolver um problema que
o HireHub não tem.

Em produção ele fica atrás do Nginx, que cuida de TLS, gzip e dos estáticos —
ver deploy/. Sozinho, aguenta o desenvolvimento e um tráfego modesto.
"""
import mimetypes
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hirehub import config, db, fontes, texto  # noqa: E402
from web import paginas  # noqa: E402

ROTA_VAGA = re.compile(r"^/vaga/([0-9a-f]{12})(?:/[^/]*)?/?$")
CACHE_ESTATICO = "public, max-age=86400"
CACHE_PAGINA = "public, max-age=300"


class Handler(BaseHTTPRequestHandler):
    server_version = "HireHub"
    protocol_version = "HTTP/1.1"

    # --------------------------------------------------------------- infra

    def log_message(self, formato, *args):
        print(f"[{datetime.now():%H:%M:%S}] {self.address_string()} {formato % args}",
              flush=True)

    def _responder(self, corpo, codigo=200, tipo="text/html; charset=utf-8", cache=None):
        dados = corpo.encode("utf-8") if isinstance(corpo, str) else corpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", cache or CACHE_PAGINA)
        # A página não executa script próprio e nunca embute HTML de terceiros
        # (ver paginas.py). Estas duas linhas garantem que continue assim mesmo
        # se algum dia alguém esquecer.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dados)

    def _redirecionar(self, destino):
        self.send_response(301)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        caminho = urlparse(self.path).path.rstrip("/") or "/"
        # O guarda envolve TODAS as rotas, inclusive os estáticos: o navegador
        # cancela requisições de imagem o tempo todo (troca de página, cache),
        # e cada cancelamento imprimia um traceback inteiro no log.
        try:
            self._despachar(caminho)
        except BrokenPipeError:
            pass  # visitante fechou a aba no meio da resposta
        except Exception as e:  # nunca devolver stack trace ao visitante
            self.log_message("ERRO em %s: %s: %s", caminho, type(e).__name__, e)
            try:
                self._responder(self._erro_simples(), 500, cache="no-store")
            except BrokenPipeError:
                pass

    def _despachar(self, caminho):
        if caminho.startswith("/static/"):
            return self._estatico(caminho)
        # Navegadores pedem /favicon.ico sozinhos, ignorando o <link> do HTML.
        if caminho == "/favicon.ico":
            return self._estatico("/static/favicon.svg")
        if caminho == "/robots.txt":
            return self._responder(
                f"User-agent: *\nAllow: /\nSitemap: "
                f"{config.SITE['url'].rstrip('/')}/sitemap.xml\n",
                tipo="text/plain; charset=utf-8")

        params = parse_qs(urlparse(self.path).query)
        con = db.abrir(somente_leitura=True)
        try:
            if caminho == "/sitemap.xml":
                return self._sitemap(con)
            ctx = self._contexto(con, caminho)
            # None = a rota já respondeu sozinha (é o caso do redirecionamento).
            if (resposta := self._pagina(con, ctx, caminho, params)) is not None:
                self._responder(*resposta)
        finally:
            con.close()

    # ------------------------------------------------------------- rotas

    def _pagina(self, con, ctx, caminho, params):
        if caminho == "/":
            _, recentes = db.buscar(con, {}, pagina=0, por_pagina=6)
            return paginas.home(ctx, recentes, ctx["status_fontes"]),

        if caminho == "/vagas":
            criterios = {
                "q": _texto(params, "q"),
                "local": _texto(params, "local"),
                "modalidade": _texto(params, "modalidade"),
                "fonte": _texto(params, "fonte"),
                "dias": _inteiro(params, "dias"),
            }
            pagina = max(0, _inteiro(params, "pagina"))
            total, vagas = db.buscar(con, criterios, pagina)
            return paginas.listagem(ctx, criterios, pagina, total, vagas,
                                    ctx["status_fontes"]),

        if casou := ROTA_VAGA.match(caminho):
            vaga = db.por_id(con, casou.group(1))
            if not vaga:
                return paginas.erro(ctx, 404, "Vaga não encontrada"), 404
            # URL canônica com slug: bom para quem compartilha o link e para
            # os buscadores lerem o título antes de abrir a página.
            esperada = f"/vaga/{vaga['id']}/{texto.slug(vaga['titulo'])}"
            if caminho != esperada:
                self._redirecionar(esperada)
                return None
            return paginas.detalhes(ctx, vaga, db.relacionadas(con, vaga)),

        if caminho == "/sobre":
            return paginas.sobre(ctx),
        if caminho == "/contato":
            return paginas.contato(ctx),
        if caminho == "/status":
            return paginas.status(ctx, ctx["status_fontes"]),

        return paginas.erro(ctx, 404, "Página não encontrada"), 404

    def _contexto(self, con, rota):
        registradas = fontes.todas()
        return {
            "rota": rota,
            "agora": datetime.now(paginas.FUSO),
            "meta": db.ler_meta(con),
            "contagens": db.contagens(con),
            "status_fontes": db.status_fontes(con),
            "fontes_registradas": registradas,
            "fontes_por_id": {f.id: f.nome for f in registradas},
        }

    def _estatico(self, caminho):
        # resolve() + is_relative_to fecham travessia de diretório: sem isso,
        # /static/../../etc/passwd seria servido de bandeja.
        alvo = (config.ESTATICOS / caminho[len("/static/"):]).resolve()
        if not alvo.is_relative_to(config.ESTATICOS.resolve()) or not alvo.is_file():
            return self._responder("Não encontrado", 404, "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        self._responder(alvo.read_bytes(), tipo=tipo, cache=CACHE_ESTATICO)

    def _sitemap(self, con):
        """Só as páginas fixas e as vagas recentes.

        Um sitemap com 19 mil URLs de anúncios que expiram em semanas não ajuda
        ninguém: os buscadores gastariam rastreamento em páginas mortas. As
        institucionais e as vagas da última semana é o que vale indexar.
        """
        base = config.SITE["url"].rstrip("/")
        urls = [f"{base}{c}" for c, _ in paginas.NAV] + [f"{base}/status"]
        _, recentes = db.buscar(con, {"dias": 7}, pagina=0, por_pagina=500)
        urls += [f"{base}/vaga/{v['id']}/{texto.slug(v['titulo'])}" for v in recentes]
        corpo = "".join(f"<url><loc>{paginas.e(u)}</loc></url>" for u in urls)
        self._responder(
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{corpo}</urlset>',
            tipo="application/xml; charset=utf-8")

    @staticmethod
    def _erro_simples():
        return ("<!doctype html><html lang=pt-BR><meta charset=utf-8>"
                "<title>Erro | HireHub</title>"
                "<p>Algo deu errado deste lado. Tente novamente em instantes.</p>"
                '<p><a href="/">Voltar para o início</a></p>')


def _texto(params, chave, limite=120):
    return (params.get(chave, [""])[0] or "").strip()[:limite]


def _inteiro(params, chave, padrao=0):
    try:
        return int(params.get(chave, [padrao])[0])
    except (ValueError, TypeError):
        return padrao


def servir(host="0.0.0.0", porta=8080):
    servidor = ThreadingHTTPServer((host, porta), Handler)
    servidor.daemon_threads = True
    print(f"HireHub no ar em http://{host}:{porta}", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        servidor.server_close()

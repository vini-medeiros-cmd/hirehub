"""Orquestrador da coleta: roda todos os conectores e grava o resultado.

Duas garantias moldam este arquivo:

  1. Uma fonte que falha não derruba as outras. Cada conector roda dentro do
     seu próprio try, e o erro vai para a tabela `fontes` — que é o que a
     página /status mostra. Um scraping quebrado vira um aviso no site, não uma
     coleta perdida.

  2. O carimbo de "no ar" só é gravado no FIM. Marcar antes deixaria o
     catálogo inteiro fora do ar durante os minutos da coleta, e
     permanentemente se o processo morresse no meio.
"""
import os
import time
from datetime import datetime

from . import config, db, fontes, net, texto


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _travar():
    """Impede duas coletas simultâneas.

    Lock por PID, não por existência de arquivo: se o processo for morto sem
    conseguir limpar, o arquivo fica para trás e travaria todas as execuções
    seguintes — a coleta pararia sozinha e em silêncio.
    """
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if config.LOCK.exists():
        try:
            pid = int(config.LOCK.read_text().strip())
        except (ValueError, OSError):
            pid = None
        if pid and pid != os.getpid() and _vivo(pid):
            return False
    config.LOCK.write_text(str(os.getpid()))
    return True


def _vivo(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _destravar():
    try:
        if config.LOCK.exists() and config.LOCK.read_text().strip() == str(os.getpid()):
            config.LOCK.unlink()
    except OSError:
        pass


def _coletar_fonte(con, fonte, cfg, carimbo):
    inicio = time.time()
    prefixo = lambda msg: log(f"  {fonte.nome}: {msg}")
    try:
        vagas = [v for v in fonte.coletar(cfg, prefixo) if v.get("link") and v.get("titulo")]
        novas = db.salvar(con, vagas, carimbo)
        duracao = time.time() - inicio
        db.anotar_fonte(
            con, fonte.id, fonte.nome, ultima_coleta=carimbo, ultimo_ok=carimbo,
            vagas=len(vagas), novas=novas, duracao=duracao, erro=None,
        )
        log(f"  {fonte.nome}: {len(vagas)} vagas ({novas} novas) em {duracao:.0f}s")
        return novas
    except Exception as erro:
        db.anotar_fonte(
            con, fonte.id, fonte.nome, ultima_coleta=carimbo,
            vagas=0, novas=0, duracao=time.time() - inicio,
            erro=f"{type(erro).__name__}: {erro}"[:300],
        )
        log(f"  {fonte.nome}: FALHOU — {type(erro).__name__}: {erro}")
        return 0


# Detalhes buscados entre uma gravação e a próxima. Um backfill de milhares de
# vagas leva dezenas de minutos, e gravar só no fim significaria perder tudo se
# o processo morresse no meio. Também é o que dá progresso visível no log.
LOTE_DETALHES = 250


def _enriquecer(con, fonte, cfg):
    """Completa as vagas cuja listagem não trouxe descrição.

    Tem teto por execução de propósito: são milhares de requisições e nenhuma
    rodada pode se arrastar por horas. O cache é o próprio banco, então cada
    execução avança de onde a anterior parou e o acervo converge sozinho.
    """
    if not fonte.detalhar:
        return 0
    pendentes = db.pendentes_detalhe(con, fonte.id, cfg["detalhes_por_execucao"])
    if not pendentes:
        return 0

    log(f"  {fonte.nome}: buscando detalhe de {len(pendentes)} vagas")
    gravados = 0
    for inicio in range(0, len(pendentes), LOTE_DETALHES):
        lote = pendentes[inicio:inicio + LOTE_DETALHES]
        resultados = net.em_paralelo(
            lambda v: (v["id"], fonte.detalhar(v)), lote, cfg["threads"])
        gravados += db.gravar_detalhes(con, [r for r in resultados if r])
        if len(pendentes) > LOTE_DETALHES:
            log(f"    {gravados}/{len(pendentes)}")
    log(f"  {fonte.nome}: {gravados} detalhes gravados")
    return gravados


def executar(apenas=None):
    inicio = time.time()
    cfg = config.carregar()
    carimbo = texto.agora_iso()

    if not _travar():
        log("Outra coleta já está em andamento. Saindo.")
        return False

    try:
        con = db.abrir()
        escolhidas = [f for f in fontes.todas() if not apenas or f.id in apenas]
        log(f"Coletando de {len(escolhidas)} fontes: "
            + ", ".join(f.nome for f in escolhidas))

        total_novas = sum(_coletar_fonte(con, f, cfg, carimbo) for f in escolhidas)

        log("Enriquecendo descrições...")
        for fonte in escolhidas:
            _enriquecer(con, fonte, cfg)

        removidas = db.podar(con, cfg["esquecer_apos_dias"])

        # Só agora, com a coleta concluída, este carimbo passa a valer como "o
        # que está no ar". Ver o comentário no topo do arquivo.
        db.gravar_meta(
            con,
            ultimaColetaOk=carimbo,
            geradoEm=carimbo,
            novasUltimaExecucao=total_novas,
            duracaoSegundos=round(time.time() - inicio),
            intervaloHoras=cfg["intervalo_horas"],
        )

        # Contado aqui, uma vez, para o rodapé do site não varrer a base a cada
        # página só para imprimir um número. Ver db.contagens_rapidas().
        contagens = db.contagens(con)
        db.gravar_meta(con, vagasNoAr=contagens["total"],
                       vagasForaDoAr=contagens["fora_do_ar"])

        no_banco = con.execute("SELECT COUNT(*) FROM vagas").fetchone()[0]
        con.execute("VACUUM")
        con.close()

        tamanho = config.BANCO.stat().st_size / 1048576
        log(f"Base: {no_banco} vagas ({contagens['total']} no ar, "
            f"{contagens['fora_do_ar']} fora) · {total_novas} novas · "
            f"{removidas} removidas · {tamanho:.1f} MB · {time.time() - inicio:.0f}s")
        return True
    finally:
        _destravar()

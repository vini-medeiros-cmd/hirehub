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
from datetime import datetime, timezone

from . import config, db, fontes, net, texto


_saida_viva = True


def log(msg):
    """Escreve no log, e desiste em silêncio se a saída padrão morreu.

    Sem isto, uma saída fechada derruba a coleta pelo caminho mais confuso
    possível: o `print` estoura BrokenPipeError DENTRO do try de uma fonte, e o
    orquestrador registra "InfoJobs: falha na última coleta — BrokenPipeError"
    na página /status. A fonte não falhou; quem morreu foi o log.

    Acontece de verdade e sem nada de exótico: basta um `coletar.py | head`, ou
    o terminal fechar durante uma execução manual. E não é motivo para parar de
    coletar — o que importa é o banco, não o texto na tela. A flag garante que
    a tentativa aconteça uma vez só, em vez de uma exceção por linha.
    """
    global _saida_viva
    if not _saida_viva:
        return
    try:
        print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    except (BrokenPipeError, ValueError, OSError):
        _saida_viva = False


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


def _intervalo(fonte, cfg):
    """Horas mínimas entre duas coletas desta fonte."""
    return int((cfg.get("intervalo_por_fonte") or {}).get(
        fonte.id, cfg["intervalo_horas"]))


def _horas_ate(fonte, cfg, linha):
    """Quanto falta para esta fonte poder ser coletada de novo. 0 = pode agora.

    Existe para uma fonte ter cadência própria sem precisar de um agendador
    separado: a rodada continua sendo de 6 em 6 horas e cada fonte decide se
    participa. Uma fonte adiada não é tocada — nem o `ultimo_ok` dela, o que
    mantém as vagas dela no ar (ver db.NO_AR).
    """
    intervalo = _intervalo(fonte, cfg)
    if intervalo <= cfg["intervalo_horas"] or not linha:
        return 0
    ultima = linha.get("ultima_coleta")
    if not ultima:
        return 0
    try:
        quando = datetime.fromisoformat(str(ultima).replace("Z", "+00:00"))
    except ValueError:
        return 0
    passadas = (datetime.now(timezone.utc) - quando).total_seconds() / 3600
    # Meia hora de folga: as rodadas do systemd têm RandomizedDelaySec de até
    # 5 min, e sem a folga uma rodada que chegasse 2 minutos adiantada adiaria
    # a fonte por um ciclo inteiro.
    return max(0.0, intervalo - passadas - 0.5)


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
            cobertura_completa=int(fonte.cobertura_completa),
        )
        log(f"  {fonte.nome}: {len(vagas)} vagas ({novas} novas) em {duracao:.0f}s")
        return novas
    except BrokenPipeError:
        # Nunca é culpa da fonte: é a saída do processo que sumiu. Registrar
        # isso como falha da plataforma mancharia a página /status com um erro
        # que não tem nada a ver com ela. Sobe e deixa a execução terminar.
        raise
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
    teto = min(cfg["detalhes_por_execucao"],
               fonte.detalhes_por_execucao or cfg["detalhes_por_execucao"])
    pendentes = db.pendentes_detalhe(con, fonte.id, teto)
    if not pendentes:
        return 0

    # A origem pediu para esperar (429) e a espera ainda não venceu. Insistir a
    # cada 6 horas contra quem já disse não é falta de educação e não adianta.
    if (falta := db.horas_bloqueada(con, fonte.id)) > 0:
        log(f"  {fonte.nome}: enriquecimento em espera por mais ~{falta:.0f}h "
            f"(a origem respondeu 429)")
        return 0

    threads = min(cfg["threads"], fonte.threads or cfg["threads"])
    log(f"  {fonte.nome}: buscando detalhe de {len(pendentes)} vagas"
        + (f" ({threads} threads)" if threads != cfg["threads"] else ""))

    gravados, falhas = 0, 0
    for inicio in range(0, len(pendentes), LOTE_DETALHES):
        lote = pendentes[inicio:inicio + LOTE_DETALHES]
        resultados = net.em_paralelo(
            lambda v: (v["id"], fonte.detalhar(v)), lote, threads)

        # A distinção que dá sentido ao contrato de `detalhar`:
        #   dict  = "busquei; isto é o que existe" (pode ser descrição vazia)
        #   None  = "não consegui buscar" — transitório, tenta na próxima
        # Gravar o None marcaria a vaga como já tentada e ela nunca mais seria
        # enriquecida. Foi assim que 946 vagas ficaram sem descrição para
        # sempre depois de um 429 da Cloudflare: o erro passou por sucesso.
        obtidos = [r for r in resultados if r and r[1] is not None]
        falhas += len(lote) - len(obtidos)
        gravados += db.gravar_detalhes(con, obtidos)

        # Uma fonte que começou a recusar não melhora insistindo: para e deixa
        # o resto para a próxima execução.
        if len(obtidos) == 0 and len(lote) >= LOTE_DETALHES:
            log(f"  {fonte.nome}: lote inteiro falhou — interrompendo "
                f"(a origem pode estar limitando; o resto fica para a próxima)")
            break
        if len(pendentes) > LOTE_DETALHES:
            log(f"    {gravados}/{len(pendentes)}")

    # Se a origem devolveu 429 durante o lote, guarda a espera no banco. Cada
    # coleta é um processo novo: em memória, a espera se perderia e a rodada
    # das 6 horas seguintes voltaria a bater na mesma porta.
    if ate := net.limite_de(pendentes[0]["link"]):
        db.anotar_fonte(con, fonte.id, fonte.nome,
                        bloqueado_ate=datetime.fromtimestamp(
                            ate, timezone.utc).isoformat())

    log(f"  {fonte.nome}: {gravados} detalhes gravados"
        + (f", {falhas} não obtidos (serão tentados de novo)" if falhas else ""))
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
        pedidas = [f for f in fontes.todas() if not apenas or f.id in apenas]

        # Pedir a fonte pelo nome na linha de comando ignora o intervalo: é uma
        # execução manual, e quem digitou `coletar.py solides` quer a Sólides
        # agora, não daqui a 19 horas.
        estado = {f["id"]: f for f in db.status_fontes(con)}
        escolhidas, adiadas = [], []
        for fonte in pedidas:
            faltam = 0 if apenas else _horas_ate(fonte, cfg, estado.get(fonte.id))
            (adiadas if faltam > 0 else escolhidas).append((fonte, faltam))

        log(f"Coletando de {len(escolhidas)} fontes: "
            + ", ".join(f.nome for f, _ in escolhidas))
        for fonte, faltam in adiadas:
            log(f"  {fonte.nome}: adiada, próxima em ~{faltam:.0f}h "
                f"(intervalo próprio de {_intervalo(fonte, cfg)}h)")

        escolhidas = [f for f, _ in escolhidas]
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

#!/usr/bin/env python3
"""Testes do núcleo. Sem dependência: `python3 tests/test_hirehub.py`.

Cobre o que quebra em silêncio — normalização e busca. Um acento perdido não
levanta exceção nenhuma, só faz a vaga sumir dos resultados de quem procura.
As chamadas de rede ficam de fora: conector é testado rodando `bin/coletar.py
<fonte>` contra a API de verdade, porque o que quebra neles é a API mudar, e
isso nenhum mock avisa.
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hirehub import config  # noqa: E402

# Banco temporário: os testes gravam de verdade, e não podem tocar em data/.
_TMP = tempfile.TemporaryDirectory()
config.DATA_DIR = Path(_TMP.name)
config.BANCO = config.DATA_DIR / "teste.db"

from hirehub import db, fontes, texto  # noqa: E402


class Texto(unittest.TestCase):
    def test_chave_busca_ignora_acento_e_caixa(self):
        self.assertEqual(texto.chave_busca("Macaé"), "macae")
        self.assertEqual(texto.chave_busca("SÃO PAULO"), "sao paulo")
        self.assertEqual(texto.chave_busca("Analista", "Sênior"), "analista senior")

    def test_modalidade_normaliza_vocabulario_das_fontes(self):
        for entrada in ("REMOTE", "remoto", "Home Office", "trabalho remoto"):
            self.assertEqual(texto.modalidade(entrada), "remote", entrada)
        for entrada in ("hybrid", "Híbrido", "HIBRIDO"):
            self.assertEqual(texto.modalidade(entrada), "hybrid", entrada)
        for entrada in ("on-site", "Presencial", "ONSITE"):
            self.assertEqual(texto.modalidade(entrada), "on-site", entrada)
        self.assertEqual(texto.modalidade(None), "")
        self.assertEqual(texto.modalidade("qualquer coisa"), "")

    def test_local_traduz_pais_e_remove_repeticao(self):
        self.assertEqual(texto.local("BR"), "Brasil")
        self.assertEqual(texto.local("São Paulo", "São Paulo"), "São Paulo")
        # A Gupy manda cidade sem acento e estado com acento, no mesmo registro.
        self.assertEqual(texto.local("Sao Paulo", "São Paulo"), "São Paulo")
        self.assertEqual(texto.local("São Paulo", "Sao Paulo"), "São Paulo")
        self.assertEqual(texto.local("Macaé", "RJ", "Brasil"), "Macaé, RJ")
        self.assertEqual(texto.local("Rio de Janeiro, BR"), "Rio de Janeiro")
        self.assertEqual(texto.local(None, "", None), "")

    def test_data_iso_aceita_os_formatos_das_quatro_fontes(self):
        self.assertTrue(texto.data_iso("2026-09-03T10:00:00Z").startswith("2026-09-03"))
        self.assertTrue(texto.data_iso("2026-09-03T10:00:00").startswith("2026-09-03"))
        self.assertTrue(texto.data_iso(1756900000).startswith("2025-"))
        self.assertIsNone(texto.data_iso("ontem"))
        self.assertIsNone(texto.data_iso(None))

    def test_html_vira_texto_sem_tags(self):
        bruto = "<p>Vaga <strong>&ccedil;</strong></p><ul><li>Python</li></ul><script>x</script>"
        saida = texto.texto_de_html(bruto)
        self.assertNotIn("<", saida)
        self.assertIn("ç", saida)
        self.assertIn("Python", saida)

    def test_id_da_vaga_e_estavel(self):
        link = "https://exemplo.gupy.io/job/123"
        self.assertEqual(texto.id_da_vaga(link), texto.id_da_vaga(link))
        self.assertNotEqual(texto.id_da_vaga(link), texto.id_da_vaga(link + "4"))
        self.assertEqual(len(texto.id_da_vaga(link)), 12)


def _vaga(**campos):
    base = {
        "link": "https://exemplo.com/vaga/1", "titulo": "Analista de Sistemas",
        "empresa": "Empresa XYZ", "fonte": "gupy", "local": "Macaé, RJ",
        "modalidade": "hybrid", "salario": "", "descricao": None,
        "publicada_em": "2026-09-03T09:00:00+00:00",
    }
    return {**base, **campos}


class Banco(unittest.TestCase):
    def setUp(self):
        config.BANCO.unlink(missing_ok=True)
        self.con = db.abrir()

    def tearDown(self):
        self.con.close()

    def test_salvar_conta_so_as_ineditas(self):
        self.assertEqual(db.salvar(self.con, [_vaga()], "c1"), 1)
        self.assertEqual(db.salvar(self.con, [_vaga()], "c2"), 0)
        self.assertEqual(db.salvar(self.con, [_vaga(link="https://x/2")], "c2"), 1)

    def test_recoleta_preserva_vista_em_e_descricao(self):
        """O ponto do COALESCE em salvar(): a listagem seguinte vem sem
        descrição e não pode apagar o que o enriquecimento buscou."""
        db.salvar(self.con, [_vaga()], "c1")
        id_vaga = texto.id_da_vaga(_vaga()["link"])
        db.gravar_detalhes(self.con, [(id_vaga, {"descricao": "Texto completo"})])

        db.salvar(self.con, [_vaga(titulo="Analista Pleno")], "c2")
        linha = db.por_id(self.con, id_vaga)
        self.assertEqual(linha["descricao"], "Texto completo")
        self.assertEqual(linha["vista_em"], "c1")
        self.assertEqual(linha["titulo"], "Analista Pleno")  # esse SIM atualiza
        self.assertEqual(linha["coleta"], "c2")

    def test_detalhe_sem_sucesso_nao_e_retentado_para_sempre(self):
        db.salvar(self.con, [_vaga(fonte="inhire")], "c1")
        pendentes = db.pendentes_detalhe(self.con, "inhire", 10)
        self.assertEqual(len(pendentes), 1)

        db.gravar_detalhes(self.con, [(pendentes[0]["id"], None)])
        self.assertEqual(db.pendentes_detalhe(self.con, "inhire", 10), [])

    def test_busca_ignora_acento_e_exige_todas_as_palavras(self):
        db.salvar(self.con, [_vaga()], "c1")
        for termo in ("macae", "Macaé", "MACAE"):
            self.assertEqual(db.buscar(self.con, {"local": termo})[0], 1, termo)
        self.assertEqual(db.buscar(self.con, {"q": "analista sistemas"})[0], 1)
        self.assertEqual(db.buscar(self.con, {"q": "sistemas analista"})[0], 1)
        self.assertEqual(db.buscar(self.con, {"q": "analista python"})[0], 0)

    def test_filtros_combinam(self):
        db.salvar(self.con, [
            _vaga(),
            _vaga(link="https://x/2", modalidade="remote", fonte="inhire"),
        ], "c1")
        self.assertEqual(db.buscar(self.con, {"modalidade": "remote"})[0], 1)
        self.assertEqual(db.buscar(self.con, {"fonte": "gupy"})[0], 1)
        self.assertEqual(db.buscar(self.con, {"fonte": "gupy", "modalidade": "remote"})[0], 0)
        self.assertEqual(db.buscar(self.con, {})[0], 2)

    def test_vaga_sem_data_vai_para_o_fim(self):
        db.salvar(self.con, [
            _vaga(link="https://x/sem", publicada_em=None),
            _vaga(link="https://x/com"),
        ], "c1")
        _, vagas = db.buscar(self.con, {})
        self.assertIsNotNone(vagas[0]["publicada_em"])
        self.assertIsNone(vagas[-1]["publicada_em"])

    def _quando(self, dias):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()

    def test_podar_remove_o_que_a_origem_nao_mostra_mais(self):
        db.salvar(self.con, [_vaga()], self._quando(90))
        db.salvar(self.con, [_vaga(link="https://x/2")], texto.agora_iso())
        self.assertEqual(db.podar(self.con, 60), 1)
        self.assertEqual(db.contagens(self.con)["total"], 1)

    def test_podar_nao_apaga_vaga_antiga_que_continua_no_ar(self):
        """A poda é por AUSÊNCIA, não por idade.

        Uma vaga pode estar aberta há meses e ser coletada todo dia. Podar por
        `vista_em` — a data de entrada, que nunca muda — apagava essas junto
        com as mortas: uma vaga coletada na mesma manhã sumia por ter entrado
        há mais de `esquecer_apos_dias`. O corte certo é `coleta`, a última vez
        que ela foi vista.
        """
        db.salvar(self.con, [_vaga()], self._quando(130))   # entrou há 130 dias
        db.salvar(self.con, [_vaga()], texto.agora_iso())   # e foi vista agora

        linha = db.por_id(self.con, texto.id_da_vaga(_vaga()["link"]))
        self.assertLess(linha["vista_em"], self._quando(120), "entrou faz tempo")

        self.assertEqual(db.podar(self.con, 120), 0, "está no ar; não pode sair")
        self.assertEqual(db.contagens(self.con)["total"], 1)


class ContagensBaratas(unittest.TestCase):
    """A home não pode varrer a tabela a cada visita.

    Na VPS, com 688 MB de banco e 945 MB de RAM, a tabela não cabe no cache: a
    varredura virava leitura de disco e a home chegou a 32 segundos — nginx
    desiste em 30 e devolve 504. `COUNT(DISTINCT empresa)` era o caro.
    """

    def setUp(self):
        config.BANCO.unlink(missing_ok=True)
        self.con = db.abrir()
        db.salvar(self.con, [
            _vaga(link="https://x/1", empresa="Alfa"),
            _vaga(link="https://x/2", empresa="Beta"),
            _vaga(link="https://x/3", empresa="Alfa"),
        ], texto.agora_iso())

    def tearDown(self):
        self.con.close()

    def test_cacheadas_batem_com_o_calculo_completo(self):
        cheia = db.contagens_completas(self.con)
        db.gravar_meta(self.con, vagasNoAr=cheia["total"],
                       vagasForaDoAr=cheia["fora_do_ar"], empresas=cheia["empresas"])
        barata = db.contagens(self.con)
        for campo in ("total", "empresas", "fora_do_ar", "novas"):
            self.assertEqual(barata[campo], cheia[campo], campo)
        self.assertEqual(barata["empresas"], 2, "Alfa e Beta")

    def test_sem_meta_cai_para_o_calculo_completo(self):
        """Base nova, antes da primeira coleta: tem de funcionar mesmo assim."""
        self.assertEqual(db.contagens(self.con)["total"], 3)

    def test_listagem_sem_filtro_usa_o_total_ja_contado(self):
        cheia = db.contagens_completas(self.con)
        db.gravar_meta(self.con, vagasNoAr=cheia["total"],
                       vagasForaDoAr=cheia["fora_do_ar"], empresas=cheia["empresas"])
        self.assertEqual(db.buscar(self.con, {})[0], 3)
        # Com filtro, o total tem de ser recontado de verdade.
        self.assertEqual(db.buscar(self.con, {"q": "analista"})[0], 3)
        self.assertEqual(db.buscar(self.con, {"q": "inexistente"})[0], 0)

    def test_novas_e_ao_vivo_e_nao_vem_do_cache(self):
        """"Publicadas nas últimas 24h" anda com o relógio: guardar erraria."""
        db.gravar_meta(self.con, vagasNoAr=999, vagasForaDoAr=0, empresas=0)
        recente = texto.agora_iso()
        db.salvar(self.con, [_vaga(link="https://x/9", publicada_em=recente)],
                  texto.agora_iso())
        self.assertEqual(db.contagens(self.con)["total"], 999, "esse vem do cache")
        self.assertEqual(db.contagens(self.con)["novas"], 1, "esse é consultado")


class Conectores(unittest.TestCase):
    def test_todos_se_registram_com_contrato_valido(self):
        registradas = fontes.todas()
        self.assertGreaterEqual(len(registradas), 4)
        for fonte in registradas:
            self.assertTrue(fonte.id and fonte.nome, fonte)
            self.assertTrue(callable(fonte.coletar), fonte.id)
            self.assertIs(fontes.por_id(fonte.id), fonte)

    def test_inventario_de_fontes(self):
        """Lista explícita: acrescentar plataforma é decisão, não acidente.

        Quebrar aqui ao adicionar um conector é o comportamento desejado —
        obriga a atualizar o README e a conferir se a fonte declarou
        `cobertura_completa` com consciência do que isso faz.
        """
        self.assertEqual(
            {f.id for f in fontes.todas()},
            {"gupy", "inhire", "infojobs", "solides", "trampos", "vagas"},
        )

    def test_conector_grava_a_fonte_com_o_proprio_id(self):
        """Se um conector escrevesse `"fonte": "outra-coisa"`, o filtro por
        plataforma pararia de achar as vagas dele — e sem erro nenhum, porque
        a coluna aceita qualquer texto. Confere no código, já que exercitar os
        conectores de verdade exigiria rede."""
        raiz = Path(__file__).resolve().parent.parent / "hirehub" / "fontes"
        for fonte in fontes.todas():
            fonte_py = raiz / f"{fonte.id}.py"
            self.assertTrue(fonte_py.is_file(),
                            f"{fonte.id}: esperado o módulo {fonte_py.name}")
            gravados = set(re.findall(r'"fonte":\s*"([^"]+)"',
                                      fonte_py.read_text(encoding="utf-8")))
            self.assertEqual(gravados, {fonte.id},
                             f"{fonte.id} grava {gravados or 'nada'}")

    def test_cobertura_completa_e_declarada_conscientemente(self):
        """Só fonte exaustiva pode marcar vaga como "saiu do ar". Hoje é uma
        só; se virarem duas, que seja por decisão."""
        exaustivas = {f.id for f in fontes.todas() if f.cobertura_completa}
        self.assertEqual(exaustivas, {"inhire"})


class NoAr(unittest.TestCase):
    """A regra do "saiu do ar": vaga some da origem, não some do site."""

    def setUp(self):
        config.BANCO.unlink(missing_ok=True)
        self.con = db.abrir()

    def tearDown(self):
        self.con.close()

    def _coleta(self, carimbo, vagas, fonte="inhire", nome="InHire", completa=True):
        # A vaga sempre pertence à fonte que a coletou; deixar divergir faria o
        # teste medir uma combinação que a coleta real nunca produz.
        db.salvar(self.con, [{**v, "fonte": fonte} for v in vagas], carimbo)
        db.anotar_fonte(self.con, fonte, nome, ultima_coleta=carimbo,
                        ultimo_ok=carimbo, vagas=len(vagas), erro=None,
                        cobertura_completa=int(completa))
        # A coleta real recalcula o "no ar" no fim; o teste simula o mesmo.
        db.atualizar_no_ar(self.con)

    def test_fonte_com_janela_nunca_marca_vaga_como_fora_do_ar(self):
        """A regra que 1.740 vagas abertas da Gupy pagaram para existir.

        A Gupy entrega as 10.000 mais recentes: a vaga sai da janela porque
        chegaram outras mais novas, não porque foi encerrada. Concluir que
        fechou esconde do site vaga publicada hoje.
        """
        self._coleta("c1", [_vaga(fonte="gupy"), _vaga(link="https://x/2", fonte="gupy")],
                     fonte="gupy", nome="Gupy", completa=False)
        self._coleta("c2", [_vaga(fonte="gupy")], fonte="gupy", nome="Gupy",
                     completa=False)

        total, vagas = db.buscar(self.con, {})
        self.assertEqual(total, 2, "fonte com janela não esconde nada")
        self.assertTrue(all(v["no_ar"] for v in vagas))

    def test_vaga_que_sumiu_fica_listada_mas_marcada(self):
        self._coleta("c1", [_vaga(), _vaga(link="https://x/2")])
        self._coleta("c2", [_vaga()])  # a segunda não veio mais

        total, _ = db.buscar(self.con, {})
        self.assertEqual(total, 1, "por padrão só as no ar")

        total, vagas = db.buscar(self.con, {"incluir_fora_do_ar": True})
        self.assertEqual(total, 2)
        self.assertEqual({v["id"]: bool(v["no_ar"]) for v in vagas},
                         {texto.id_da_vaga("https://exemplo.com/vaga/1"): True,
                          texto.id_da_vaga("https://x/2"): False})

    def test_fonte_que_falha_nao_derruba_as_vagas_dela(self):
        """O ponto de ancorar em fontes.ultimo_ok e não na coleta global.

        Se a InHire falhar numa rodada, as 8.900 vagas dela não podem sumir do
        site em bloco — seria quase metade do catálogo apagada por um blip.
        """
        self._coleta("c1", [_vaga()], fonte="inhire", nome="InHire")
        # A Gupy coleta com sucesso mais tarde; a InHire falha (ultimo_ok fica em c1).
        self._coleta("c2", [_vaga(link="https://x/g")], fonte="gupy", nome="Gupy",
                     completa=False)
        db.anotar_fonte(self.con, "inhire", "InHire", ultima_coleta="c2",
                        vagas=0, erro="ConnectionError")

        total, vagas = db.buscar(self.con, {})
        self.assertEqual(total, 2)
        self.assertTrue(all(v["no_ar"] for v in vagas))

    def test_pagina_da_vaga_abre_mesmo_fora_do_ar(self):
        """Quem chegou por link antigo merece a página com aviso, não um 404."""
        self._coleta("c1", [_vaga()])
        self._coleta("c2", [])
        vaga = db.por_id(self.con, texto.id_da_vaga(_vaga()["link"]))
        self.assertIsNotNone(vaga)
        self.assertFalse(vaga["no_ar"])

    def test_contagens_e_relacionadas_ignoram_as_fora_do_ar(self):
        self._coleta("c1", [_vaga(), _vaga(link="https://x/2")])
        self._coleta("c2", [_vaga()])
        self.assertEqual(db.contagens(self.con)["total"], 1)
        self.assertEqual(db.contagens(self.con)["fora_do_ar"], 1)

        vaga = db.por_id(self.con, texto.id_da_vaga(_vaga()["link"]))
        self.assertEqual(db.relacionadas(self.con, vaga), [])

    def test_base_sem_tabela_de_fontes_nao_esconde_nada(self):
        """Base recém-criada, antes da primeira coleta terminar: sem o COALESCE
        a comparação com NULL marcaria tudo como fora do ar."""
        db.salvar(self.con, [_vaga()], "c1")
        self.assertEqual(db.buscar(self.con, {})[0], 1)


class Enriquecimento(unittest.TestCase):
    """A diferença entre "busquei e não tinha" e "não consegui buscar".

    Confundir as duas custou 946 vagas da Vagas.com.br: um 429 da Cloudflare
    foi gravado como se fosse resposta legítima, marcando cada vaga como já
    tentada — e elas nunca mais seriam enriquecidas.
    """

    def setUp(self):
        from hirehub import coleta
        self.coleta = coleta
        config.BANCO.unlink(missing_ok=True)
        self.con = db.abrir()
        db.salvar(self.con, [_vaga(link=f"https://x/{i}", fonte="infojobs")
                             for i in range(3)], "c1")
        self.fonte = fontes.por_id("infojobs")
        self.original = self.fonte.__class__.detalhar
        self.cfg = {**config.PADROES, "threads": 1}

    def tearDown(self):
        self.fonte.__class__.detalhar = self.original
        self.con.close()

    def _com_detalhar(self, funcao):
        self.fonte.__class__.detalhar = staticmethod(funcao)

    def test_falha_de_rede_nao_marca_a_vaga_como_tentada(self):
        self._com_detalhar(lambda vaga: None)
        self.coleta._enriquecer(self.con, self.fonte, self.cfg)
        self.assertEqual(len(db.pendentes_detalhe(self.con, "infojobs", 10)), 3,
                         "todas devem continuar pendentes")

    def test_vaga_sem_descricao_na_origem_nao_e_retentada(self):
        self._com_detalhar(lambda vaga: {"descricao": ""})
        self.coleta._enriquecer(self.con, self.fonte, self.cfg)
        self.assertEqual(db.pendentes_detalhe(self.con, "infojobs", 10), [])

    def test_sucesso_grava_e_sai_da_fila(self):
        self._com_detalhar(lambda vaga: {"descricao": "Texto", "salario": "R$ 1"})
        self.coleta._enriquecer(self.con, self.fonte, self.cfg)
        self.assertEqual(db.pendentes_detalhe(self.con, "infojobs", 10), [])
        linha = db.por_id(self.con, texto.id_da_vaga("https://x/0"))
        self.assertEqual(linha["descricao"], "Texto")
        self.assertEqual(linha["salario"], "R$ 1")

    def test_origem_que_pediu_pausa_nao_e_incomodada_de_novo(self):
        """429 com Retry-After de 24h significa 24h — não "tente de novo em 6".

        A espera vai para o banco porque cada coleta é um processo novo: em
        memória ela se perderia e a rodada seguinte bateria na mesma porta.
        """
        from datetime import datetime, timedelta, timezone
        futuro = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
        db.anotar_fonte(self.con, "infojobs", "InfoJobs", bloqueado_ate=futuro)

        chamadas = []
        self._com_detalhar(lambda vaga: chamadas.append(vaga) or {"descricao": "x"})
        self.coleta._enriquecer(self.con, self.fonte, self.cfg)

        self.assertEqual(chamadas, [], "não pode ter buscado nada")
        self.assertEqual(len(db.pendentes_detalhe(self.con, "infojobs", 10)), 3)
        self.assertGreater(db.horas_bloqueada(self.con, "infojobs"), 19)

    def test_espera_vencida_libera_a_fonte(self):
        from datetime import datetime, timedelta, timezone
        passado = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.anotar_fonte(self.con, "infojobs", "InfoJobs", bloqueado_ate=passado)
        self.assertEqual(db.horas_bloqueada(self.con, "infojobs"), 0)

        self._com_detalhar(lambda vaga: {"descricao": "voltou"})
        self.coleta._enriquecer(self.con, self.fonte, self.cfg)
        self.assertEqual(db.pendentes_detalhe(self.con, "infojobs", 10), [])

    def test_teto_zero_significa_zero_e_nao_o_global(self):
        """`or` tratava 0 como "não definido" e caía no global.

        Isso impedia uma fonte de dizer "não me enriqueça" — exatamente o que a
        Vagas.com.br precisa dizer, depois de três bloqueios de 24h.
        """
        self.assertEqual(self.coleta._teto(0, 400), 0)
        self.assertEqual(self.coleta._teto(None, 400), 400, "None usa o global")
        self.assertEqual(self.coleta._teto(120, 400), 120, "menor dos dois")
        self.assertEqual(self.coleta._teto(900, 400), 400, "nunca sobe do global")

    def test_fonte_com_teto_zero_nao_e_enriquecida(self):
        chamadas = []
        self._com_detalhar(lambda vaga: chamadas.append(vaga) or {"descricao": "x"})
        apagada = {**self.cfg, "detalhes_por_execucao": 400}

        original = self.fonte.__class__.detalhes_por_execucao
        self.fonte.__class__.detalhes_por_execucao = 0
        try:
            self.assertEqual(
                self.coleta._enriquecer(self.con, self.fonte, apagada), 0)
        finally:
            self.fonte.__class__.detalhes_por_execucao = original
        self.assertEqual(chamadas, [], "não pode ter buscado nada")
        self.assertEqual(len(db.pendentes_detalhe(self.con, "infojobs", 10)), 3,
                         "seguem pendentes, para o dia em que religar")

    def test_vagas_com_br_esta_com_enriquecimento_desligado(self):
        """Decisão deliberada, não acidente — ver o comentário no conector."""
        vagas = fontes.por_id("vagas")
        self.assertEqual(vagas.detalhes_por_execucao, 0)
        self.assertIsNotNone(vagas.detalhar, "o método fica, para religar fácil")
        # As outras continuam sendo enriquecidas normalmente.
        for outra in ("infojobs", "inhire", "trampos"):
            self.assertNotEqual(fontes.por_id(outra).detalhes_por_execucao, 0, outra)

    def test_fonte_pode_baixar_o_proprio_teto_mas_nao_subir(self):
        """`threads` e `detalhes_por_execucao` do conector são limites, não
        permissões: uma fonte pode pedir para ir mais devagar que o global, e
        nenhuma pode decidir ir mais rápido."""
        trampos = fontes.por_id("trampos")
        self.assertIsNotNone(trampos.detalhes_por_execucao)

        # Global folgado: vale o teto da fonte.
        self.assertEqual(self.coleta._teto(trampos.detalhes_por_execucao, 400),
                         trampos.detalhes_por_execucao)
        # Global apertado: vale o global.
        self.assertEqual(self.coleta._teto(trampos.detalhes_por_execucao, 10), 10)

        vagas = fontes.por_id("vagas")
        self.assertLess(vagas.threads, config.PADROES["threads"],
                        "a Vagas.com.br precisa ir mais devagar que o global")
        self.assertEqual(self.coleta._teto(vagas.threads, 6), vagas.threads)
        self.assertEqual(self.coleta._teto(vagas.threads, 1), 1)


class LimiteDeTaxa(unittest.TestCase):
    """Limitar thread não é limitar taxa, e a Vagas.com.br cobrou a diferença.

    Ela levou 429 mesmo a 2 threads: duas threads sem pausa ainda disparam
    várias requisições por segundo, e um Cloudflare conta requisições por
    intervalo de tempo.
    """

    def test_ritmo_espaca_entre_todas_as_threads(self):
        import time

        from hirehub import net
        ritmo = net.Ritmo(10)  # uma a cada 100ms
        inicio = time.monotonic()
        saida = net.em_paralelo(lambda i: i * 2, range(8), threads=4, ritmo=ritmo)
        levou = time.monotonic() - inicio

        self.assertEqual(saida, [i * 2 for i in range(8)])
        # 8 requisições a 10/s = 7 intervalos = ~0,7s. Se o espaçamento valesse
        # por thread em vez de para o conjunto, seriam ~0,2s.
        self.assertGreater(levou, 0.55, "o ritmo não está sendo respeitado")
        self.assertLess(levou, 1.5, "está mais lento do que o configurado")

    def test_sem_ritmo_nao_atrasa_nada(self):
        import time

        from hirehub import net
        inicio = time.monotonic()
        net.em_paralelo(lambda i: i, range(20), threads=4, ritmo=None)
        self.assertLess(time.monotonic() - inicio, 0.3)

    def test_fonte_bloqueada_declara_o_proprio_ritmo(self):
        """A Vagas.com.br é a que apanhou; ela precisa declarar o limite."""
        vagas = fontes.por_id("vagas")
        self.assertEqual(vagas.req_por_segundo, 1)
        # As que nunca reclamaram seguem sem limite, para não ficarem lentas à toa.
        self.assertIsNone(fontes.por_id("gupy").req_por_segundo)


class ColetaEmLotes(unittest.TestCase):
    """Fonte grande não pode caber toda na memória antes de ir para o banco.

    Com `gupy_termos` configurado a Gupy passou de 10.000 para 43.000 vagas
    COM descrição, e o pico da coleta foi de 203 MB para 540 — perto demais do
    MemoryMax de 768 MB da unidade e de um OOM na VPS de 945 MB.
    """

    def setUp(self):
        from hirehub import coleta
        self.coleta = coleta
        config.BANCO.unlink(missing_ok=True)
        self.con = db.abrir()
        self.fonte = fontes.por_id("gupy")
        self.original = self.fonte.__class__.coletar
        self.cfg = {**config.PADROES, "threads": 1}

    def tearDown(self):
        self.fonte.__class__.coletar = self.original
        self.con.close()

    def test_gerador_e_gravado_em_lotes_sem_materializar_tudo(self):
        quantas = self.coleta.LOTE_GRAVACAO * 2 + 7
        vivas = {"max": 0}

        def muitas(cfg, log):
            # Conta quantas vagas o orquestrador segura ao mesmo tempo: se ele
            # acumulasse tudo, este número chegaria a `quantas`.
            for i in range(quantas):
                vivas["max"] = max(vivas["max"], i % self.coleta.LOTE_GRAVACAO + 1)
                yield _vaga(link=f"https://x/{i}", fonte="gupy")

        self.fonte.__class__.coletar = staticmethod(muitas)
        novas = self.coleta._coletar_fonte(self.con, self.fonte, self.cfg, "c1")

        self.assertEqual(novas, quantas)
        self.assertEqual(db.contagens(self.con)["total"], quantas)
        self.assertLessEqual(vivas["max"], self.coleta.LOTE_GRAVACAO)

    def test_lista_continua_funcionando(self):
        """Conectores que ainda devolvem lista não podem quebrar."""
        self.fonte.__class__.coletar = staticmethod(lambda cfg, log: [
            _vaga(link="https://x/1", fonte="gupy"),
            _vaga(link="https://x/2", fonte="gupy"),
        ])
        self.assertEqual(
            self.coleta._coletar_fonte(self.con, self.fonte, self.cfg, "c1"), 2)

    def test_vaga_sem_link_ou_titulo_e_descartada_no_meio_do_fluxo(self):
        self.fonte.__class__.coletar = staticmethod(lambda cfg, log: iter([
            _vaga(link="https://x/1", fonte="gupy"),
            _vaga(link="", fonte="gupy"),
            _vaga(link="https://x/3", titulo="", fonte="gupy"),
        ]))
        self.assertEqual(
            self.coleta._coletar_fonte(self.con, self.fonte, self.cfg, "c1"), 1)


class LogResiliente(unittest.TestCase):
    """Saída padrão morta não pode virar "falha da plataforma" no /status.

    Aconteceu de verdade: um `coletar.py | head -4` fechou o pipe, o print
    estourou dentro do try da InfoJobs, e a página de status passou dias
    dizendo "InfoJobs: BrokenPipeError" — sobre uma fonte que estava perfeita.
    """

    def setUp(self):
        from hirehub import coleta
        self.coleta = coleta
        coleta._saida_viva = True

    def tearDown(self):
        self.coleta._saida_viva = True

    def test_saida_fechada_nao_levanta_nem_repete_a_tentativa(self):
        import io

        class SaidaMorta(io.StringIO):
            def __init__(self):
                super().__init__()
                self.tentativas = 0

            def write(self, _):
                self.tentativas += 1
                raise BrokenPipeError(32, "Broken pipe")

        morta = SaidaMorta()
        original = sys.stdout
        sys.stdout = morta
        try:
            self.coleta.log("primeira")   # descobre que a saída morreu
            self.coleta.log("segunda")    # já nem tenta
            self.coleta.log("terceira")
        finally:
            sys.stdout = original

        self.assertEqual(morta.tentativas, 1,
                         "deve desistir depois da primeira falha")
        self.assertFalse(self.coleta._saida_viva)

    def test_saida_viva_continua_escrevendo(self):
        import io
        viva = io.StringIO()
        original = sys.stdout
        sys.stdout = viva
        try:
            self.coleta.log("um")
            self.coleta.log("dois")
        finally:
            sys.stdout = original
        self.assertIn("um", viva.getvalue())
        self.assertIn("dois", viva.getvalue())


class CompatibilidadeDeVersao(unittest.TestCase):
    """Guarda contra escrever código que só roda na máquina de desenvolvimento.

    O piso é Python 3.9 (`zoneinfo` e `Path.is_relative_to`), que é o que
    Ubuntu 22.04 e Oracle Linux 9 entregam. Quem desenvolve costuma estar num
    3.12, onde o PEP 701 liberou barra invertida e aspas repetidas dentro das
    expressões de f-string — construções que na VPS são SyntaxError, e o site
    simplesmente não sobe. Já aconteceu uma vez, no menu do cabeçalho.
    """

    # f-string de uma linha; o que estiver entre chaves é a expressão.
    LITERAL = re.compile(
        r'''(?<![A-Za-z0-9_])[fF][rR]?(?P<q>"""|\'\'\'|"|\')(?P<corpo>.*?)(?<!\\)(?P=q)''')

    def test_nada_de_f_string_exclusiva_do_312(self):
        raiz = Path(__file__).resolve().parent.parent
        problemas = []
        for arquivo in sorted(raiz.rglob("*.py")):
            if "__pycache__" in str(arquivo):
                continue
            for n, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
                for casou in self.LITERAL.finditer(linha):
                    corpo, aspa = casou.group("corpo"), casou.group("q")
                    expr = "".join(re.findall(r"\{([^{}]*)\}", corpo))
                    onde = f"{arquivo.relative_to(raiz)}:{n}"
                    if "\\" in expr:
                        problemas.append(f"{onde} barra invertida na expressão")
                    if len(aspa) == 1 and aspa in expr:
                        problemas.append(f"{onde} aspas {aspa} iguais ao delimitador")
        self.assertEqual(problemas, [], "\n".join(problemas))


class IntervaloPorFonte(unittest.TestCase):
    """A Sólides roda de 24 em 24h; as outras seguem de 6 em 6."""

    def setUp(self):
        from hirehub import coleta
        self.coleta = coleta
        self.cfg = {**config.PADROES}
        self.solides = fontes.por_id("solides")
        self.gupy = fontes.por_id("gupy")

    def _ha(self, horas):
        from datetime import datetime, timedelta, timezone
        return {"ultima_coleta":
                (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()}

    def test_fonte_no_intervalo_padrao_nunca_e_adiada(self):
        self.assertEqual(self.coleta._horas_ate(self.gupy, self.cfg, self._ha(0)), 0)

    def test_solides_adiada_dentro_das_24h(self):
        self.assertGreater(self.coleta._horas_ate(self.solides, self.cfg, self._ha(6)), 0)
        self.assertGreater(self.coleta._horas_ate(self.solides, self.cfg, self._ha(18)), 0)

    def test_solides_liberada_depois_das_24h(self):
        self.assertEqual(self.coleta._horas_ate(self.solides, self.cfg, self._ha(24)), 0)
        self.assertEqual(self.coleta._horas_ate(self.solides, self.cfg, self._ha(30)), 0)

    def test_folga_evita_perder_um_ciclo_inteiro(self):
        """Rodada que chega 2 minutos adiantada não pode adiar por mais 24h."""
        self.assertEqual(
            self.coleta._horas_ate(self.solides, self.cfg, self._ha(24 - 2 / 60)), 0)

    def test_fonte_nunca_coletada_roda_na_hora(self):
        self.assertEqual(self.coleta._horas_ate(self.solides, self.cfg, None), 0)
        self.assertEqual(self.coleta._horas_ate(self.solides, self.cfg, {}), 0)


class InfoJobsPagina(unittest.TestCase):
    """Raspagem é parsing de HTML de terceiro — o lugar mais fácil de errar."""

    def test_cidade_que_cai_para_sao_paulo_e_descartada(self):
        """O InfoJobs não erra para slug inválido: serve São Paulo calado.

        Como o conector rotula a vaga com a cidade PEDIDA, aceitar essa
        resposta gravaria vagas paulistas como se fossem de outro lugar.
        """
        from hirehub.fontes import infojobs

        pedida = '<html><head><title>Vagas de Emprego em São Paulo | Infojobs</title>'
        self.assertFalse(infojobs._confere_cidade(pedida, "campos-dos-goytacazes"))
        self.assertTrue(infojobs._confere_cidade(pedida, "sao-paulo"))

        certa = '<html><head><title>Vagas de Emprego em Cabo Frio - RJ | Infojobs</title>'
        self.assertTrue(infojobs._confere_cidade(certa, "cabo-frio"))
        self.assertFalse(infojobs._confere_cidade(certa, "niteroi"))

        # Sem título não dá para julgar: confia no slug em vez de descartar tudo.
        self.assertTrue(infojobs._confere_cidade("<html><body>vagas</body>", "macae"))

    def test_descricao_nao_traz_resto_da_tag_de_abertura(self):
        from hirehub.fontes import infojobs
        from hirehub import net

        html = ('<html><body><div class="js_vacancyDataPanels js_applyVacancyHidden">'
                '<p>Vendedor no centro.</p><p>Salário a combinar.</p></div></body></html>')
        original = net.html_de
        net.html_de = lambda *a, **k: html
        try:
            saida = infojobs.InfoJobs.detalhar({"link": "https://x"})["descricao"]
        finally:
            net.html_de = original

        self.assertFalse(saida.startswith("js_"), saida[:60])
        self.assertNotIn("js_applyVacancyHidden", saida)
        self.assertIn("Vendedor no centro.", saida)
        self.assertIn("Salário a combinar.", saida)


class Paginas(unittest.TestCase):
    """Renderiza cada página com dados reais do banco.

    Existe porque a renderização quebra por campo faltando, não por lógica: a
    consulta de vagas relacionadas não trazia `link`, e o cartão só descobria
    isso ao montar o botão Candidatar-se — um 500 na página de detalhes que
    nenhum teste de `db` pegaria.
    """

    def setUp(self):
        from datetime import datetime

        from web import paginas
        self.paginas = paginas

        config.BANCO.unlink(missing_ok=True)
        self.con = db.abrir()
        db.salvar(self.con, [
            _vaga(descricao="Linha um.\n\nLinha dois."),
            _vaga(link="https://x/2", titulo="Analista de Dados", fonte="inhire"),
        ], texto.agora_iso())
        db.anotar_fonte(self.con, "gupy", "Gupy", ultimo_ok="c1", vagas=10, erro=None)

        registradas = fontes.todas()
        self.ctx = {
            "rota": "/", "agora": datetime.now(paginas.FUSO),
            "meta": db.ler_meta(self.con), "contagens": db.contagens(self.con),
            "status_fontes": db.status_fontes(self.con),
            "fontes_registradas": registradas,
            "fontes_por_id": {f.id: f.nome for f in registradas},
        }

    def tearDown(self):
        self.con.close()

    def _valida(self, html):
        self.assertIn("</html>", html)
        self.assertNotIn("None", html)
        return html

    def test_todas_as_paginas_renderizam(self):
        _, vagas = db.buscar(self.con, {})
        vaga = db.por_id(self.con, vagas[0]["id"])
        self._valida(self.paginas.home(self.ctx, vagas, self.ctx["status_fontes"]))
        self._valida(self.paginas.listagem(self.ctx, {"q": "analista"}, 0, 2, vagas,
                                           self.ctx["status_fontes"]))
        self._valida(self.paginas.detalhes(
            self.ctx, vaga, db.relacionadas(self.con, vaga)))
        self._valida(self.paginas.sobre(self.ctx))
        self._valida(self.paginas.contato(self.ctx))
        self._valida(self.paginas.status(self.ctx, self.ctx["status_fontes"]))
        self._valida(self.paginas.erro(self.ctx, 404, "Não encontrada"))

    def test_pagina_vazia_nao_quebra(self):
        vazio = {**self.ctx, "contagens": {"total": 0, "novas": 0, "empresas": 0},
                 "status_fontes": [], "meta": {}}
        self._valida(self.paginas.home(vazio, [], []))
        self._valida(self.paginas.listagem(vazio, {}, 0, 0, [], []))
        self._valida(self.paginas.status(vazio, []))

    def test_dado_de_terceiro_e_escapado(self):
        """Títulos e descrições vêm de quatro plataformas. Um `<script>` num
        deles não pode chegar inteiro à página."""
        ataque = '<script>alert("x")</script>'
        db.salvar(self.con, [_vaga(link="https://x/3", titulo=ataque,
                                   empresa=ataque, descricao=ataque)], "c9")
        vaga = db.por_id(self.con, texto.id_da_vaga("https://x/3"))
        html = self.paginas.detalhes(self.ctx, vaga, [])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)

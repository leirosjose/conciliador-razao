"""Tela enxuta. Usuario-alvo: colaborador SEM experiencia contabil.
Teste de aceite: "entende sem perguntar?". So' a casca muda: os numeros vem
prontos do core, e o Excel continua com a informacao completa.
"""
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from app.apresentacao import resposta_conferido
from core.conferencia import conferir
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN
from tests.test_app_ponte import MAIN
from tests.test_ponte import COMPRA, PAGAMENTO, _conta

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()


@pytest.fixture(scope="module")
def golden():
    return conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)


@pytest.fixture(scope="module")
def tela_golden():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("golden_sintetico.xls", GOLDEN.read_bytes(), "application/vnd.ms-excel")).run()
    return at


# --- 2. resposta no topo ------------------------------------------------------

def test_resposta_com_uma_nota_diz_qual_e_quando():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1395.62", 30)]),
                   CLASSIFICADOR)
    assert resposta_conferido(res) == (
        "Conferido. Saldo de R$ 1.395,62 = NF 5001 (30/01/2026), em aberto.")


def test_resposta_com_varias_notas_diz_quantas_e_a_mais_antiga(golden):
    assert resposta_conferido(golden) == (
        "Conferido. Saldo de R$ 4.260,09 = 2 notas em aberto "
        "(a mais antiga de 11/12/2024).")


def test_resposta_separa_o_saldo_anterior_das_notas():
    """O saldo anterior nao e' nota nem tem data: contado como "nota", a
    "mais antiga" mentiria."""
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (COMPRA.format(nf="5002"), "0.00", "500.00", 9)],
                          saldo_anterior="-700.00"), CLASSIFICADOR)
    assert resposta_conferido(res) == (
        "Conferido. Saldo de R$ 2.200,00 = 2 notas em aberto "
        "(a mais antiga de 02/01/2026) e R$ 700,00 de saldo anterior.")


def test_resposta_so_existe_quando_a_conta_fecha():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (PAGAMENTO, "300.00", "0.00", 5)]), CLASSIFICADOR)
    assert resposta_conferido(res) is None          # INCOMPLETO: texto de hoje


def test_tela_abre_com_a_resposta(tela_golden):
    assert len(tela_golden.exception) == 0
    (verde,) = tela_golden.success
    # fonte markdown com o cifrao escapado
    assert verde.value == ("Conferido. Saldo de R\\$ 4.260,09 = 2 notas em "
                           "aberto (a mais antiga de 11/12/2024).")


# --- 3. composicao: so' o que esta em aberto, quitadas atras do toggle --------

SINTETICA = GOLDEN.parent / "sintetica_integra.xls"


def _tela_sintetica():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sintetica_integra.xls", SINTETICA.read_bytes(),
         "application/vnd.ms-excel")).run()
    return at


def _toggle(at, inicio):
    return next(t for t in at.toggle if t.label.startswith(inicio))


def test_composicao_mostra_so_as_notas_em_aberto_por_padrao():
    at = _tela_sintetica()
    tabela, total = at.dataframe[0].value, at.dataframe[1].value
    assert list(tabela["NF"]) == ["1111", "3333", "(transferência lote 3015)",
                                  "6666"]
    assert "0,00" not in list(tabela["EM ABERTO"])
    assert list(total["NF"]) == ["Total em aberto"]
    assert total.iloc[0]["EM ABERTO"] == "8.000,00"     # 1.900+750+250+5.100
    toggle = _toggle(at, "Mostrar notas quitadas")
    assert toggle.label == "Mostrar notas quitadas (4)"
    assert toggle.value is False


def test_toggle_mostra_as_quitadas_e_o_total_diz_o_escopo():
    at = _tela_sintetica()
    _toggle(at, "Mostrar notas quitadas").set_value(True).run()
    assert len(at.exception) == 0
    tabela, total = at.dataframe[0].value, at.dataframe[1].value
    assert len(tabela) == 8
    assert list(total["NF"]) == ["Total com quitadas"]
    assert total.iloc[0]["EM ABERTO"] == "8.000,00"     # quitada soma 0,00
    assert total.iloc[0]["Valor compra"] != _tela_sintetica().dataframe[1] \
        .value.iloc[0]["Valor compra"]                  # o escopo mudou de fato


def test_sem_quitadas_nao_ha_toggle(tela_golden):
    assert not [t for t in tela_golden.toggle
                if t.label.startswith("Mostrar notas quitadas")]


# --- 4. periodo zerado: expander fechado, texto sem jargao -------------------

from datetime import date  # noqa: E402

from app.apresentacao import (abrir_fechado, bloco_linhas_nfs,  # noqa: E402
                              bloco_linhas_sem_nf, frase_bloco, titulo_fechado)
from tests.test_ponte import ESTRANHO, PAGAMENTO_NF  # noqa: E402

PAGO_CONF = "Pago conf. FORNECEDOR FICTICIO"


def _caso_mini():
    return conferir(_conta([
        (COMPRA.format(nf="5001"), "0.00", "700.00", 2),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 2),
        (PAGO_CONF, "1000.00", "0.00", 5),                        # zera 05/01
        (COMPRA.format(nf="5003"), "0.00", "250.00", 9)]), CLASSIFICADOR)


def _nao_bate():
    """A 5001 e' comprada no 1o trecho e paga EM PARTE no 2o: o total do
    periodo zerado fecha (o corte vale), mas cada trecho, sozinho, nao bate."""
    return conferir(_conta([
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
        (ESTRANHO, "1000.00", "0.00", 3),                         # zera 03/01
        (COMPRA.format(nf="5002"), "0.00", "500.00", 4),
        (PAGAMENTO_NF.format(nf="5001"), "200.00", "0.00", 5),
        (ESTRANHO, "300.00", "0.00", 6),                          # zera 06/01
        (COMPRA.format(nf="5003"), "0.00", "50.00", 8)]), CLASSIFICADOR)


def test_frase_do_bloco_que_bate_no_modelo_da_spec():
    (bloco,) = _caso_mini().fechado.blocos
    assert frase_bloco(bloco) == (
        "Em 05/01/2026 entrou um pagamento de R$ 1.000,00 sem número de nota. "
        "Ele bate exatamente com 2 notas e em 05/01/2026 a conta ficou "
        "zerada. O total fecha; a quitação nota a nota não foi comprovada.")


def test_titulo_singular_e_expander_fechado_quando_bate():
    fechado = _caso_mini().fechado
    assert titulo_fechado(fechado) == "Pagamento sem nota que zerou a conta"
    assert abrir_fechado(fechado) is False


def test_quando_nao_bate_o_texto_diz_e_o_expander_abre():
    fechado = _nao_bate().fechado
    b1, b2 = fechado.blocos
    assert not b1.bate and not b2.bate
    assert abrir_fechado(fechado) is True
    assert titulo_fechado(fechado) == "Lançamentos sem nota que zeraram a conta"
    assert frase_bloco(b1) == (
        "Em 03/01/2026 entrou um lançamento de R$ 1.000,00 sem número de nota, "
        "e nenhuma nota em aberto até ali fecha com ele. Em 03/01/2026 a conta "
        "ficou zerada. Não bate exato.")
    assert frase_bloco(b2) == (
        "Em 06/01/2026 entrou um lançamento de R$ 300,00 sem número de nota, "
        "mas as 2 notas em aberto até ali somam R$ 1.300,00 (diferença de "
        "R$ 1.000,00). Em 06/01/2026 a conta ficou zerada. Não bate exato.")


def test_tabelas_enxutas_do_bloco():
    (bloco,) = _caso_mini().fechado.blocos
    assert bloco_linhas_nfs(bloco) == [
        {"NF": "5001", "Data": "02/01/2026", "Valor": "700,00"},
        {"NF": "5002", "Data": "02/01/2026", "Valor": "300,00"}]
    assert bloco_linhas_sem_nf(bloco) == [
        {"Lote": "L3", "Data": "05/01/2026", "Valor": "1.000,00",
         "Histórico": PAGO_CONF}]


def _xlsx(monkeypatch, lancamentos):
    from tests.fixtures import gerar_sinteticas as G
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("0.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", lancamentos)
    return G.montar_xlsx()


def _tela_xlsx(dados):
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("zera.xlsx", dados,
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert len(at.exception) == 0
    return at


def _expander(at, inicio):
    return next(e for e in at.expander if e.label.startswith(inicio))


def test_tela_periodo_zerado_em_expander_fechado(monkeypatch):
    from tests.test_app_corte import _xlsx_que_zera
    at = _tela_xlsx(_xlsx_que_zera(monkeypatch))
    exp = _expander(at, "Pagamento sem nota que zerou a conta")
    assert exp.proto.expanded is False
    textos = [m.value for m in exp.markdown]
    assert any(t.startswith("Em 05/01/2025 entrou um pagamento de R\\$ 1.000,00")
               for t in textos)
    # a tabela HTML propria de leitura (moeda a direita, wrap,
    # escape), nem st.table (ignora o alinhamento) nem st.dataframe (corta)
    tabelas = [m for m in exp.markdown if 'class="tabela-leitura' in m.value]
    assert len(tabelas) == 2
    assert all(m.proto.allow_html for m in tabelas)
    assert "<th>NF</th>" in tabelas[0].value
    assert '<th class="num">Valor</th>' in tabelas[1].value
    assert "<th>Histórico</th>" in tabelas[1].value
    assert not exp.table and not exp.dataframe


def test_tela_periodo_zerado_que_nao_bate_abre_sozinho(monkeypatch):
    E = "FORNECEDOR FICTICIO"
    at = _tela_xlsx(_xlsx(monkeypatch, [
        (date(2025, 1, 2), 5001, f"Vr. compras conf. 5001 {E} LTDA", None, D("1000.00")),
        (date(2025, 1, 3), 5002, "TARIFA SEM PADRÃO CONHECIDO", D("1000.00"), None),
        (date(2025, 1, 4), 5003, f"Vr. compras conf. 5002 {E} LTDA", None, D("500.00")),
        (date(2025, 1, 5), 5004, f"Valor ref. a PGTO A {E} NF 5001", D("200.00"), None),
        (date(2025, 1, 6), 5005, "TARIFA SEM PADRÃO CONHECIDO", D("300.00"), None),
        (date(2025, 1, 8), 5006, f"Vr. compras conf. 5003 {E} LTDA", None, D("50.00")),
    ]))
    exp = _expander(at, "Lançamentos sem nota que zeraram a conta")
    assert exp.proto.expanded is True


# --- 5/6. ponte em expander enxuto --------------------------------------------

from app.apresentacao import ponte_celulas_tela, titulo_ponte  # noqa: E402


def test_ponte_da_tela_so_traz_linhas_com_valor_mais_apurado_e_dominio(golden):
    linhas = [c["Linha"] for c in ponte_celulas_tela(golden)]
    assert linhas == ["Saldo anterior", "(+) Compras do período",
                      "(-) Pagamentos casados",
                      "(=) Em aberto pela composição",
                      "(=) Saldo final apurado", "Saldo final Domínio"]


def test_ponte_completa_da_tela_funde_as_duas_linhas_de_em_aberto(golden):
    linhas = [c["Linha"] for c in ponte_celulas_tela(golden, todas=True)]
    assert "(=) Em aberto NF a NF" not in linhas
    assert "(-) Pagamento sem nota que zerou a conta" in linhas
    assert "(-) Retenções" in linhas                    # o zero aparece aqui
    assert len(linhas) == 14                            # 15 do Excel - 1


def test_ponte_com_periodo_zerado_mostra_o_pagamento_sem_nota():
    res = _caso_mini()
    valores = {c["Linha"]: c["Valor"] for c in ponte_celulas_tela(res)}
    assert valores["(-) Pagamento sem nota que zerou a conta"] == D("1000.00")
    assert valores["(=) Em aberto pela composição"] == D("250.00")


def test_titulo_da_ponte_traz_o_resultado(golden):
    assert titulo_ponte(golden) == "Ponte do saldo — fecha em R$ 4.260,09"


def test_titulo_da_ponte_que_diverge():
    # fabrica um residuo: o saldo impresso da ultima linha errado em 5,00
    conta = _conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                    (PAGAMENTO, "300.00", "0.00", 5)], erro_no_saldo_final="5.00")
    res = conferir(conta, CLASSIFICADOR)
    assert titulo_ponte(res) == "Ponte do saldo — não fecha: diferença de R$ 5,00"


def test_tela_ponte_em_expander_fechado_com_toggle(tela_golden):
    exp = _expander(tela_golden, "Ponte do saldo")
    assert exp.label == "Ponte do saldo — fecha em R\\$ 4.260,09"   # escapado
    assert exp.proto.expanded is False
    (tabela,) = [m.value for m in exp.markdown if "Saldo final apurado" in m.value]
    assert "(-) Retenções" not in tabela
    assert ":green[**OK**]" in tabela
    # 6: a nota do saldo anterior fora da tabela mora DENTRO da ponte
    assert any("429,26" in c.value for c in exp.caption)
    assert not [c for c in tela_golden.caption
                if "429,26" in c.value and c not in exp.caption]


def test_toggle_da_ponte_mostra_todas_as_linhas():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("golden_sintetico.xls", GOLDEN.read_bytes(), "application/vnd.ms-excel")).run()
    _toggle(at, "Mostrar todas as linhas").set_value(True).run()
    exp = _expander(at, "Ponte do saldo")
    (tabela,) = [m.value for m in exp.markdown if "Saldo final apurado" in m.value]
    assert "| (-) Retenções | 0,00 |" in tabela
    assert "Em aberto NF a NF" not in tabela


# --- jargao -------------------------------------------------------------------

def test_saldo_no_dominio_vira_palavra():
    from app.apresentacao import saldo_dominio_texto
    from core.modelo import Conta
    assert saldo_dominio_texto(Conta("1", "x", "y", saldo_anterior=D("-500.00"))) \
        == "Saldo no Domínio: R$ 500,00 a pagar"
    assert saldo_dominio_texto(Conta("1", "x", "y", saldo_anterior=D("120.00"))) \
        == "Saldo no Domínio: R$ 120,00 a receber"
    assert saldo_dominio_texto(Conta("1", "x", "y")) == "Saldo no Domínio: R$ 0,00"


def test_toda_coluna_da_composicao_tem_ajuda(tela_golden):
    import json
    from app.apresentacao import AJUDA_COLUNAS, ajuda_coluna
    config = json.loads(tela_golden.dataframe[0].proto.columns)
    for coluna in AJUDA_COLUNAS:
        if coluna in config:
            assert config[coluna].get("help") == ajuda_coluna(coluna), coluna
            assert AJUDA_COLUNAS[coluna] in config[coluna]["help"], coluna


def test_vereditos_nao_falam_de_balde():
    from app.apresentacao import status_conta
    from core.modelo import Achado, Nivel
    for nivel in (Nivel.ERRO, Nivel.INCOMPLETO):
        _, titulo = status_conta([Achado(nivel, "x", "y")])
        assert "balde" not in titulo and "itens sem destino" in titulo


# --- observacoes com titulo proprio --------------------------------------------

def test_alertas_ficam_sob_observacoes_e_nao_sob_divergencias():
    at = _tela_sintetica()
    titulos = [m.value for m in at.markdown if m.value.startswith("#### ")]
    assert "#### ℹ️ Observações" in titulos
    divergencias = next(t for t in titulos if t.endswith(" Divergências"))
    assert titulos.index(divergencias) < titulos.index("#### ℹ️ Observações")
    assert len(at.info) > 0


def test_sem_observacao_sem_titulo(tela_golden):
    assert "#### ℹ️ Observações" not in [m.value for m in tela_golden.markdown]


# --- titulo da ponte segue a marca; plural da linha do periodo zerado ---------

def test_titulo_da_ponte_com_item_sem_destino_diz_quanto():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (PAGAMENTO, "300.00", "0.00", 5)]), CLASSIFICADOR)
    assert titulo_ponte(res) == ("Ponte do saldo — fecha em R$ 700,00, com "
                                 "R$ 300,00 sem destino")


def test_linha_do_periodo_zerado_no_plural_com_mais_de_um_pagamento():
    from tests.test_corte import _dois_blocos_com_pendencia
    res = _dois_blocos_com_pendencia()
    linhas = [c["Linha"] for c in ponte_celulas_tela(res)]
    assert "(-) Pagamentos sem nota que zeraram a conta" in linhas



def _bloco_com_cifroes():
    conta = _conta([
        (COMPRA.format(nf="5001"), "0.00", "600.00", 2),
        (COMPRA.format(nf="5004"), "0.00", "100.00", 2),
        ("Pago conf. R$ 700,00 de R$ 700,00 <b>&</b>", "700.00", "0.00", 3),
        (COMPRA.format(nf="5002"), "0.00", "50.00", 5)])
    from tests.test_corte import CLASSIFICADOR as C
    (bloco,) = conferir(conta, C).fechado.blocos
    return bloco


def test_historico_do_bloco_fica_cru_nas_linhas():
    """As linhas sao dado (evidencia); o escape e' do formato de saida --
    HTML na tabela da tela, nenhum no dict."""
    (linha,) = bloco_linhas_sem_nf(_bloco_com_cifroes())
    assert linha["Histórico"] == "Pago conf. R$ 700,00 de R$ 700,00 <b>&</b>"


def test_tabela_de_leitura_escapa_html_e_cifrao():
    """Historico e' texto CRU do arquivo: nunca HTML vivo. O cifrao sai como
    entidade, entao nenhum par de R$ vira formula no renderizador."""
    from app.apresentacao import tabela_html
    saida = tabela_html(bloco_linhas_sem_nf(_bloco_com_cifroes()))
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in saida and "<b>&</b>" not in saida
    assert "$" not in saida.split("</style>")[1]
    assert "R&#36; 700,00" in saida


def test_tabela_de_leitura_alinha_moeda_a_direita_e_quebra_o_historico():
    from app.apresentacao import tabela_html
    saida = tabela_html(bloco_linhas_sem_nf(_bloco_com_cifroes()))
    assert '<td class="num">700,00</td>' in saida
    assert '<td class="txt estica">' in saida
    assert "\n\n" not in saida      # linha em branco encerraria o bloco HTML


def test_tabela_de_leitura_das_nfs_fica_do_tamanho_do_conteudo():
    from app.apresentacao import tabela_html
    saida = tabela_html(bloco_linhas_nfs(_bloco_com_cifroes()))
    assert 'class="tabela-leitura hist"' in saida     # sem largura total
    assert '<td class="num">600,00</td>' in saida

# --- pago a maior --------------------------------------------------------------

def test_nf_com_em_aberto_negativo_ganha_a_marca_pago_a_maior():
    from app.apresentacao import composicao_linhas
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "100.00", 2),
                           ("- PAGTO REF. NF.:  5001.1 - PARC.:FORN", "102.46",
                            "0.00", 5),
                           (COMPRA.format(nf="5002"), "0.00", "50.00", 6)]), CLASSIFICADOR)
    linhas = {l["NF"]: l for l in composicao_linhas(res.itens)}
    assert linhas["5001 (pago a maior)"]["EM ABERTO"] == "-2,46"
    assert "5002" in linhas                       # positiva: sem marca
    assert res.totais_em_aberto.saldo_aberto == D("47.54")   # total soma o negativo



def test_residuo_dentro_da_tolerancia_nao_ganha_a_marca_so_a_nota():
    """-0,01 com 1 quitacao e' o arredondamento que o casamento ja
    aceitou (quitada_com_arredondamento, mesma tolerancia que cala o alerta
    de juros). A linha fica sem marca; a nota de arredondamento continua."""
    from app.apresentacao import composicao_linhas, notas_composicao_texto
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "100.00", 2),
                           ("- PAGTO REF. NF.:  5001.1 - PARC.:FORN", "100.01",
                            "0.00", 5),
                           (COMPRA.format(nf="5002"), "0.00", "50.00", 6)]), CLASSIFICADOR)
    linhas = {l["NF"]: l for l in composicao_linhas(res.itens)}
    assert linhas["5001"]["EM ABERTO"] == "-0,01"
    assert not any("pago a maior" in nf for nf in linhas)
    assert any("arredondamento" in n for n in notas_composicao_texto(res.itens))

# --- triagem com a mesma palavra da conta -------------------------------------

def test_triagem_usa_conferido_e_falta_alocar_zero(golden):
    from app.apresentacao import triagem_linhas
    (linha,) = triagem_linhas([("golden_sintetico.xls", [golden], None)])
    assert linha["Veredito"] == "🟢 Conferido"
    assert linha["Falta alocar"] == "0,00"


# --- colunas de dinheiro zeradas saem da tela ---------------------------------

def test_colunas_de_dinheiro_zeradas_saem_da_tela_e_do_total(tela_golden):
    import json
    from app.apresentacao import colunas_visiveis
    assert colunas_visiveis(golden_res := conferir(
        ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR).itens) == [
        "NF", "Data NF", "Valor compra", "Total pago", "EM ABERTO",
        "Última quitação", "Idade (dias)"]
    tabela, total = tela_golden.dataframe[0], tela_golden.dataframe[1]
    ordem = list(tabela.proto.column_order)
    assert ordem == list(total.proto.column_order)     # TOTAL acompanha
    assert "Retido" not in ordem and "Baixa adiant." not in ordem
    assert "EM ABERTO" in ordem



# --- regra geral -- a coluna aparece se ALGUMA linha tem dado ----------------

def test_golden_volta_a_mostrar_a_ultima_quitacao_das_nfs_pagas_em_parte(golden):
    from app.apresentacao import colunas_visiveis
    assert "Última quitação" in colunas_visiveis(golden.itens)


def test_coluna_sem_dado_em_nenhuma_linha_some(golden):
    """Data vazia (None) e dinheiro zerado nao sao dado. Basta UMA linha com
    dado pra coluna ficar."""
    from app.apresentacao import colunas_visiveis
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "100.00", 2),
                           (COMPRA.format(nf="5002"), "0.00", "50.00", 6)]), CLASSIFICADOR)
    visiveis = colunas_visiveis(res.itens)
    assert "Última quitação" not in visiveis          # nada foi pago
    assert "Total pago" not in visiveis
    assert visiveis == ["NF", "Data NF", "Valor compra", "EM ABERTO",
                        "Idade (dias)"]


def test_uma_linha_com_dado_segura_a_coluna():
    from app.apresentacao import colunas_visiveis
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "100.00", 2),
                           ("- PAGTO REF. NF.:  5001.1 - PARC.:FORN", "40.00",
                            "0.00", 5),
                           (COMPRA.format(nf="5002"), "0.00", "50.00", 6)]), CLASSIFICADOR)
    visiveis = colunas_visiveis(res.itens)
    assert "Última quitação" in visiveis and "Total pago" in visiveis


def test_idade_zero_e_dado():
    """0 dias e' uma idade (nota emitida no ultimo dia), nao ausencia."""
    from app.apresentacao import colunas_visiveis
    from core.modelo import ComposicaoItem
    from core.modelo import Origem
    item = ComposicaoItem(nf_numero="5001", origem=Origem.COMPRA_PERIODO,
                          valor_compra=D("10.00"), total_pago=D("0.00"),
                          total_retido=D("0.00"), saldo_aberto=D("10.00"),
                          idade_dias=0)
    assert "Idade (dias)" in colunas_visiveis([item])


def test_em_aberto_nunca_sai():
    """E' a pergunta da tela: mesmo com tudo quitado na visao com quitadas."""
    from app.apresentacao import colunas_visiveis
    from core.modelo import ComposicaoItem
    from core.modelo import Origem
    item = ComposicaoItem(nf_numero="5001", origem=Origem.COMPRA_PERIODO,
                          valor_compra=D("10.00"), total_pago=D("10.00"),
                          total_retido=D("0.00"), saldo_aberto=D("0.00"))
    assert "EM ABERTO" in colunas_visiveis([item])


def test_total_acompanha_as_colunas_da_tabela():
    at = _tela_sintetica()
    for ligado in (False, True):
        _toggle(at, "Mostrar notas quitadas").set_value(ligado).run()
        tabela, total = at.dataframe[0], at.dataframe[1]
        assert list(tabela.proto.column_order) == list(total.proto.column_order)


def test_coluna_com_valor_continua(golden):
    from app.apresentacao import colunas_visiveis
    res = _tela_sintetica()
    ordem = list(res.dataframe[0].proto.column_order)
    assert "Retido" in ordem                      # a 3333 tem IRRF retido


# --- triagem do lote sem rolagem lateral --------------------------------------

def _triagem_html():
    from app.apresentacao import tabela_triagem, triagem_linhas
    res = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    return tabela_triagem(triagem_linhas([
        ("golden_sintetico.xls", [res], None),
        ("quebrado.xls", None, "arquivo <corrompido> R$ 1 e R$ 2")]))


def test_triagem_quebra_texto_e_alinha_numero_a_direita():
    saida = _triagem_html()
    assert 'class="tabela-leitura triagem larga"' in saida
    assert "<td class=\"txt\">golden_<wbr>sintetico.<wbr>xls</td>" in saida  # quebra entre pedacos
    assert "estica" not in saida.split("</style>")[1]  # o navegador reparte a sobra
    assert '<td class="num">0,00</td>' in saida           # Falta alocar
    assert '<th class="num">Itens sem destino</th>' in saida


def test_triagem_erro_nao_reaparece_e_arquivo_continua_escapado():
    saida = _triagem_html()
    assert "corrompido" not in saida and "R&#36; 1" not in saida
    from app.apresentacao import tabela_triagem, triagem_linhas
    saida = tabela_triagem(triagem_linhas([
        ("arquivo <corrompido> R$ 1.xls", None, "fato do erro")]))
    assert "&lt;corrompido&gt;" in saida and "<corrompido>" not in saida
    assert "R&#36; 1" in saida
    assert "fato do erro" not in saida


def test_triagem_mantem_as_mesmas_colunas():
    """Nada de informacao nova nem a menos: so' o formato muda."""
    saida = _triagem_html()
    for coluna in ("Arquivo", "Conta", "Fornecedor", "Veredito", "Falta alocar",
                   "Itens sem destino", "Sugeridos", "Achados"):
        assert f">{coluna}</th>" in saida


# --- cabecalhos curtos na tela, nome completo no tooltip ----------------------

def test_cabecalhos_curtos_na_tela_com_nome_completo_no_help(tela_golden):
    import json
    colunas = json.loads(tela_golden.dataframe[0].proto.columns)
    assert colunas["Última quitação"]["label"] == "Últ. quitação"
    assert colunas["Idade (dias)"]["label"] == "Idade"
    assert colunas["Última quitação"]["help"].startswith("Última quitação:")
    assert colunas["Idade (dias)"]["help"].startswith("Idade (dias):")
    # o TOTAL usa a mesma config: cabecalho igual nas duas grades
    total = json.loads(tela_golden.dataframe[1].proto.columns)
    assert total["Idade (dias)"]["label"] == "Idade"


def test_planilha_continua_com_o_nome_completo():
    """A chave da coluna (Excel, testes, column_order) nao muda: so' o rotulo
    da tela encurta."""
    from app.apresentacao import composicao_celulas
    res = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    assert {"Última quitação", "Idade (dias)"} <= set(composicao_celulas(res.itens)[0])


# --- balde vazio diz o fato, sem afirmar que todo pagamento casou -------------

def test_balde_vazio_diz_so_o_fato(tela_golden):
    legendas = [c.value for c in tela_golden.caption]
    assert "Nenhum item sem destino." in legendas
    assert not any("todo pagamento casou" in c for c in legendas)


# --- saldo anterior no topo e em UM detalhe (Observacoes) ---------------------

def _tela_com_saldo_anterior(monkeypatch):
    from datetime import date
    from tests.fixtures import gerar_sinteticas as G
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("-700.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", [
        (date(2025, 1, 2), 4001, "Vr. compras conf. 5001 FORNECEDOR FICTICIO LTDA",
         None, D("1000.00"))])
    return _tela_xlsx(G.montar_xlsx())


def test_saldo_anterior_sai_da_nota_e_fica_em_observacoes(monkeypatch):
    at = _tela_com_saldo_anterior(monkeypatch)
    assert "saldo anterior" in at.success[0].value          # resposta do topo
    legendas = [c.value for c in at.caption]
    assert not any("de saldo trazido do período anterior" in c for c in legendas)
    assert any("saldo anterior" in i.value and "sem detalhe" in i.value
               for i in at.info)


def test_planilha_mantem_a_nota_do_saldo_anterior():
    """Excel e' o documento completo: a nota continua la'."""
    from app.apresentacao import notas_composicao_texto
    from tests.test_ponte import _conta
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "100.00", 2)],
                          saldo_anterior="-50.00"), CLASSIFICADOR)
    assert any("de saldo trazido do período anterior" in n
               for n in notas_composicao_texto(res.itens))


# --- lote sem divisoria e na ordem da triagem ---------------------------------

def _tela_lote_misto():
    """golden (verde limpo) + sintetica integra (alerta) -- a triagem poe a
    sintetica primeiro."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([
        ("golden_sintetico.xls", GOLDEN.read_bytes(), "application/vnd.ms-excel"),
        ("sintetica_integra.xls", SINTETICA.read_bytes(),
         "application/vnd.ms-excel")]).run()
    assert len(at.exception) == 0
    return at


def test_lote_sem_divisoria_antes_do_titulo_de_cada_conta():
    at = _tela_lote_misto()
    assert len(at.divider) == 0                  # a borda do container separa


def test_conta_unica_mantem_a_divisoria(tela_golden):
    assert len(tela_golden.divider) == 1


def test_lote_detalha_as_contas_na_ordem_da_triagem():
    """Upload: golden primeiro. Triagem: a sintetica (com alerta) antes do
    golden (verde limpo). O detalhe segue a triagem."""
    at = _tela_lote_misto()
    titulos = [s.value for s in at.subheader]
    assert "sintetica" in titulos[0] and "golden" in titulos[1]


def test_ordem_do_lote_poe_o_arquivo_com_erro_primeiro():
    from app.apresentacao import ordem_do_lote
    res = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    assert ordem_do_lote([("a.xls", [res], None),
                          ("b.xls", None, "erro de leitura")]) == [(1, None), (0, res)]


# --- botoes de exportar com a mesma largura ------------------------------------

def test_todo_botao_de_exportar_estica_na_sidebar():
    """AppTest nao expoe a largura do botao: a trava le o AST de app/main.py.
    Todo st.download_button pede width="stretch" (largura igual; o texto a
    esquerda vem do CSS do topo)."""
    import ast
    chamadas = [n for n in ast.walk(ast.parse(MAIN.read_text()))
                if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "download_button"]
    assert len(chamadas) >= 2
    for c in chamadas:
        largura = {k.arg: k.value for k in c.keywords}.get("width")
        assert isinstance(largura, ast.Constant) and largura.value == "stretch"

"""Na CASCA: secao "Fechado por saldo zero" e as linhas da ponte.

O core entrega `res.fechado` pronto; aqui se testa o que o contador LE. Nada
some em silencio (D3): o que o corte tirou da composicao aparece na secao,
sempre visivel, com o alerta. O rotulo da ponte nao usa a palavra "bloco"
(D1).
"""
from datetime import date
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from app.apresentacao import (fechado_celulas_balde, fechado_celulas_nfs,
                              frase_achado, ponte_celulas)
from core.conferencia import conferir
from parser.historico import ClassificadorHistorico
from tests.test_app_ponte import MAIN
from tests.test_ponte import COMPRA, _conta

D = Decimal
PAGO_CONF = "Pago conf. FORNECEDOR FICTICIO"


@pytest.fixture(scope="module")
def caso_sintetico():
    """Um caso em miniatura: duas NFs na abertura, um "Pago conf."
    que soma as duas sem casar com nenhuma, o saldo zera, e depois uma NF nova
    fica em aberto."""
    conta = _conta([
        (COMPRA.format(nf="5001"), "0.00", "700.00", 2),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 2),
        (PAGO_CONF, "1000.00", "0.00", 5),                        # zera
        (COMPRA.format(nf="5003"), "0.00", "250.00", 9)])
    return conferir(conta, ClassificadorHistorico())


# --- ponte -------------------------------------------------------------------

def test_ponte_mostra_o_salto_do_aberto_nf_a_nf_pro_aberto_da_composicao(
        caso_sintetico):
    linhas = {c["Linha"]: c["Valor"] for c in ponte_celulas(caso_sintetico.ponte)}
    assert linhas["(=) Em aberto NF a NF"] == D("1250.00")
    assert linhas["(-) Pagamentos sem NF em período já zerado"] == D("1000.00")
    assert linhas["(=) Em aberto pela composição"] == D("250.00")
    assert not [r for r in linhas if "bloco" in r.lower()]      # D1


# --- secao "Fechado por saldo zero" -------------------------------------------

# na TELA a secao virou expander com tabelas enxutas
# (tests/test_app_tela_enxuta.py); estas sao as celulas da PLANILHA, que
# continua com a informacao completa.

def test_planilha_lista_as_nfs_com_saldo_e_quando_o_saldo_zerou(caso_sintetico):
    linhas = fechado_celulas_nfs(caso_sintetico.fechado)
    assert [l["NF"] for l in linhas] == ["5001", "5002"]
    assert [l["EM ABERTO"] for l in linhas] == [D("700.00"), D("300.00")]
    assert {l["Zerou em"] for l in linhas} == {date(2026, 1, 5)}


def test_planilha_lista_os_lancamentos_sem_nf(caso_sintetico):
    (linha,) = fechado_celulas_balde(caso_sintetico.fechado)
    assert linha["Lote"] == "L3"
    assert linha["Lado"] == "Débito" and linha["Valor"] == D("1000.00")
    assert linha["Zerou em"] == date(2026, 1, 5)
    assert linha["Histórico"] == PAGO_CONF


def test_alerta_do_periodo_zerado_diz_os_dois_lados_e_que_nao_e_divergencia(
        caso_sintetico):
    (aviso,) = [a for a in caso_sintetico.achados
                if a.codigo == "periodo_zerado_com_pendencia"]
    frase = frase_achado(aviso)
    assert "05/01/2026" in frase and "L3" in frase
    assert "R$ 1.000,00 em NFs" in frase
    assert "R$ 1.000,00 em lançamentos sem NF" in frase
    assert "não divergência" in frase


# --- tela (AppTest), com um .xlsx sintetico gerado na hora --------------------

def _xlsx_que_zera(monkeypatch) -> bytes:
    from tests.fixtures import gerar_sinteticas as G
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("0.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", [
        (date(2025, 1, 2), 4001, "Vr. compras conf. 5001 FORNECEDOR FICTICIO LTDA",
         None, D("700.00")),
        (date(2025, 1, 2), 4002, "Vr. compras conf. 5002 FORNECEDOR FICTICIO LTDA",
         None, D("300.00")),
        (date(2025, 1, 5), 4003, "Pago conf. FORNECEDOR FICTICIO", D("1000.00"), None),
        (date(2025, 1, 9), 4004, "Vr. compras conf. 5003 FORNECEDOR FICTICIO LTDA",
         None, D("250.00")),
    ])
    return G.montar_xlsx()


def test_tela_com_corte_compoe_so_o_pos_corte_e_fecha(monkeypatch):
    """O periodo zerado nao e' mais secao aberta com aviso azul -- e' um
    expander fechado com texto sem jargao (tests/test_app_tela_enxuta.py).
    Aqui fica o que o corte garante na tela: composicao so' do pos-corte e a
    conta fechando."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("zera.xlsx", _xlsx_que_zera(monkeypatch),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert len(at.exception) == 0
    assert list(at.dataframe[0].value["NF"]) == ["5003"]
    assert len(at.success) == 1
    assert [e.label for e in at.expander
            if e.label == "Pagamento sem nota que zerou a conta"]


def test_tela_sem_corte_nao_mostra_a_secao():
    from tests.helpers import GOLDEN
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("golden_sintetico.xls", GOLDEN.read_bytes(), "application/vnd.ms-excel")).run()
    # o golden zera (o anterior consumido em 20/02/2024), mas nada ficou
    # pendente ali: sem expander, sem alerta
    assert not [e for e in at.expander if "zer" in e.label]


def test_tela_substitui_o_aviso_tecnico_pelo_texto_do_expander(monkeypatch):
    """Na tela o aviso tecnico ("...nao divergencia") nao aparece mais --
    nem na secao nem na lista de alertas. O que o substitui e' a frase sem
    jargao do expander. A planilha e a triagem continuam com o alerta (D2)."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("zera.xlsx", _xlsx_que_zera(monkeypatch),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert not [i for i in at.info if "não divergência" in i.value]

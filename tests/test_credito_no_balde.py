"""Credito no balde nunca vira R$ negativo.

Balde SO com credito (um caso: o "Recebimento PIX" de 598,40) deixava a
diferenca negativa e a tela dizia "Falta alocar R$ -598,40". Balde MISTO
(debito e credito) mostrava o liquido. Agora os dois lados aparecem
separados, cada um com o proprio valor, e balde so' com debito fica como
sempre. Os numeros vem prontos do core (ponte.balde_debitos/creditos).
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.apresentacao import (
    contexto_incompleto_texto,
    placar_composicao,
    resumo_do_trabalho,
    status_ponte,
    titulo_ponte,
    triagem_linhas,
)
from app.pipeline import processar_excel
from core.conferencia import conferir
from core.modelo import Conta
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()
FIXTURES = Path(__file__).parent / "fixtures"
MISTA = FIXTURES / "sintetica_integra.xls"          # balde: D 3.400,00 / C 500,00
PIX = "Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO"


def _so_credito():
    """Compra de 1961,28 em aberto e um recebimento de 598,40 no balde."""
    return conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN FICTICIO",
                          data_fim_periodo=date(2025, 12, 31),
                          lancamentos=[
                              lanc("Vr. compras conf. 860010 FORN", numero="c1",
                                   data=date(2025, 12, 11), credito="1961.28",
                                   saldo="-1961.28"),
                              lanc(PIX, numero="341018", data=date(2025, 12, 17),
                                   credito="598.40", saldo="-2559.68")]), CLF)


def _textos(res):
    placar = placar_composicao(res)
    _, status = status_ponte(res)
    (linha,) = triagem_linhas([("a.xls", [res], None)])
    return {
        "veredito": contexto_incompleto_texto(res.achados, res.ponte),
        "placar": f"{placar['rotulo_delta']} R$ {placar['delta']}",
        "placar_extra": placar["delta_extra"],
        "titulo_ponte": titulo_ponte(res),
        "status_ponte": status,
        "balde": resumo_do_trabalho(res),
        "triagem": linha["Falta alocar"],
    }


def _sem_negativo(textos):
    for chave, texto in textos.items():
        assert "-" not in (texto or "").replace("—", ""), (chave, texto)


# --- so' credito ----------------------------------------------------------------

def test_so_credito_diz_credito_e_nunca_negativo():
    t = _textos(_so_credito())
    _sem_negativo(t)
    assert t["veredito"].startswith(
        "O motor não conseguiu alocar um crédito de R$ 598,40")
    assert t["placar"] == "Crédito sem destino R$ 598,40"
    assert t["placar_extra"] is None
    assert t["titulo_ponte"].endswith("com um crédito de R$ 598,40 sem destino")
    assert t["status_ponte"] == "Fecha — crédito de R$ 598,40 sem destino"
    assert t["balde"] == "Crédito sem destino de R$ 598,40 em 1 item"
    assert t["triagem"] == "crédito 598,40"


# --- misto: os dois lados separados -----------------------------------------------

def test_misto_mostra_debitos_e_creditos_separados():
    t = _textos(processar_excel(MISTA).resultados[0])
    _sem_negativo(t)
    assert t["veredito"].startswith(
        "O motor não conseguiu alocar R$ 3.400,00 em débitos e R$ 500,00 em "
        "créditos")
    assert t["placar"] == "Débitos sem destino R$ 3.400,00"
    assert t["placar_extra"] == "crédito sem destino R$ 500,00"
    assert t["titulo_ponte"].endswith(
        "com R$ 3.400,00 em débitos e R$ 500,00 em créditos sem destino")
    assert t["status_ponte"] == ("Fecha — R$ 3.400,00 em débitos e R$ 500,00 em "
                                 "créditos sem destino")
    assert t["balde"] == ("Sem destino: R$ 3.400,00 em débitos e R$ 500,00 em "
                          "créditos, em 3 itens")
    assert t["triagem"] == "3.400,00 e crédito 500,00"


def test_misto_com_liquido_negativo_tambem_separa():
    """Credito maior que o debito: o liquido seria negativo."""
    res = conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN FICTICIO",
                         data_fim_periodo=date(2025, 12, 31),
                         lancamentos=[
                             lanc("Vr. compras conf. 860010 FORN", numero="c1",
                                  data=date(2025, 12, 11), credito="1961.28",
                                  saldo="-1961.28"),
                             lanc("DESPESA MISTERIOSA", numero="d1",
                                  data=date(2025, 12, 12), debito="200.00",
                                  saldo="-1761.28"),
                             lanc(PIX, numero="341018", data=date(2025, 12, 17),
                                  credito="598.40", saldo="-2359.68")]), CLF)
    t = _textos(res)
    _sem_negativo(t)
    assert t["placar"] == "Débitos sem destino R$ 200,00"
    assert t["placar_extra"] == "crédito sem destino R$ 598,40"


# --- so' debito: como sempre ------------------------------------------------------

def test_so_debito_continua_falta_alocar():
    res = conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN FICTICIO",
                         data_fim_periodo=date(2025, 12, 31),
                         lancamentos=[
                             lanc("Vr. compras conf. 860010 FORN", numero="c1",
                                  data=date(2025, 12, 11), credito="1961.28",
                                  saldo="-1961.28"),
                             lanc("DESPESA MISTERIOSA", numero="d1",
                                  data=date(2025, 12, 12), debito="200.00",
                                  saldo="-1761.28")]), CLF)
    t = _textos(res)
    assert t["veredito"].startswith("O motor não conseguiu alocar R$ 200,00 —")
    assert t["placar"] == "Falta alocar R$ 200,00"
    assert t["status_ponte"] == "Fecha — R$ 200,00 sem destino"
    assert t["balde"] == "Falta alocar R$ 200,00 em 1 item"
    assert t["triagem"] == "200,00"


# --- tela inteira (AppTest) -------------------------------------------------------

@pytest.mark.parametrize("arquivo", [MISTA], ids=lambda p: p.stem)
def test_tela_nao_mostra_real_negativo_no_veredito_placar_ponte_e_balde(arquivo):
    from streamlit.testing.v1 import AppTest
    main = Path(__file__).parent.parent / "app" / "main.py"
    at = AppTest.from_file(str(main), default_timeout=60).run()
    at.file_uploader[0].set_value(
        (arquivo.name, arquivo.read_bytes(), "application/vnd.ms-excel")).run()
    assert len(at.exception) == 0
    textos = ([str(m.label) + " " + str(m.value) for m in at.metric]
              + [str(c.value) for c in at.caption]
              + [str(e.label) for e in at.expander])
    assert not [t for t in textos if "R$ -" in t]


def test_frase_de_materialidade_some_com_diferenca_negativa():
    from app.materialidade import frase_materialidade
    from core.modelo import ItemRevisao, MotivoRevisao
    balde = [ItemRevisao(lancamentos=[lanc(PIX, numero=str(i), credito="100.00")],
                         motivo=MotivoRevisao.RECEBIMENTO) for i in range(7)]
    assert frase_materialidade(balde, D("-700.00")) is None

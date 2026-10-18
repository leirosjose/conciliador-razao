"""Alertas em duas classes: "Não decidido pelo
motor" e o corte_recuado registrado.

"Registrado pelo motor": o motor aplicou regra aprovada e a frase e' PROVA.
"Não decidido pelo motor": fato que nenhuma regra decide. Exibicao pura: o
core nao muda, nenhum achado nasce ou morre.
"""
import ast
from decimal import Decimal
from pathlib import Path

import pytest

from app.apresentacao import (NAO_DECIDIDO, REGISTRADO, _CLASSE_ALERTA,
                              alertas_nao_decididos, alertas_registrados,
                              classe_alerta, triagem_linhas)
from core.conferencia import conferir
from core.modelo import Achado, Nivel
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()
CORE = Path(__file__).parent.parent / "core"


def _codigos_alerta_do_core() -> set[str]:
    """Todo `Achado(nivel=Nivel.ALERTA, codigo=...)` de core/, inclusive o
    codigo escolhido por ternario (possivel_juros / _manual)."""
    codigos = set()
    for arquivo in CORE.glob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text())):
            if not (isinstance(no, ast.Call) and getattr(no.func, "id", None) == "Achado"):
                continue
            kw = {k.arg: k.value for k in no.keywords}
            nivel = kw.get("nivel")
            if not (isinstance(nivel, ast.Attribute) and nivel.attr == "ALERTA"):
                continue
            codigos |= {c.value for c in ast.walk(kw["codigo"])
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return codigos


def test_trava_todo_alerta_do_core_tem_classe_declarada():
    """Classificacao nunca fica implicita: codigo novo de ALERTA sem entrada
    no mapa derruba este teste (o default seguro e' NAO_DECIDIDO, mas a
    escolha tem que ser escrita)."""
    codigos = _codigos_alerta_do_core()
    assert len(codigos) >= 13                    # a trava enxerga o core
    assert codigos - set(_CLASSE_ALERTA) == set()


@pytest.mark.parametrize("codigo", ["casamento_por_desempate", "estorno_pareado",
                                    "corte_recuado"])
def test_regra_aplicada_e_registrada(codigo):
    assert classe_alerta(Achado(nivel=Nivel.ALERTA, codigo=codigo,
                                mensagem="m")) == REGISTRADO


@pytest.mark.parametrize("codigo", [
    "possivel_duplicidade", "possivel_duplicidade_emissao", "possivel_juros",
    "possivel_juros_manual", "possivel_desconto", "saldo_anterior_nao_detalhado",
    "transferencia_nao_detalhada", "conta_devedora", "self_check_saldo_corrente"])
def test_fato_sem_regra_e_nao_decidido(codigo):
    assert classe_alerta(Achado(nivel=Nivel.ALERTA, codigo=codigo,
                                mensagem="m")) == NAO_DECIDIDO


def _zerado(aberto, sem_nf):
    return Achado(nivel=Nivel.ALERTA, codigo="periodo_zerado_com_pendencia",
                  mensagem="m", valores={"aberto": D(aberto), "sem_nf": D(sem_nf)})


def test_periodo_zerado_que_bate_e_registrado_e_o_que_nao_bate_nao():
    assert classe_alerta(_zerado("1000.00", "1000.00")) == REGISTRADO
    assert classe_alerta(_zerado("1300.00", "300.00")) == NAO_DECIDIDO


def test_codigo_desconhecido_cai_no_lado_seguro():
    assert classe_alerta(Achado(nivel=Nivel.ALERTA, codigo="novo",
                                mensagem="m")) == NAO_DECIDIDO


def test_as_duas_listas_particionam_os_alertas():
    achados = [Achado(nivel=Nivel.ALERTA, codigo="estorno_pareado", mensagem="a"),
               Achado(nivel=Nivel.ALERTA, codigo="possivel_juros", mensagem="b"),
               Achado(nivel=Nivel.OK, codigo="self_check_saldo_final", mensagem="c")]
    assert [a.mensagem for a in alertas_registrados(achados)] == ["a"]
    assert [a.mensagem for a in alertas_nao_decididos(achados)] == ["b"]


# --- triagem: os numeros medidos na spec --------------------------------------


def test_conta_so_com_registrados_e_conferido_limpo():
    """Rank 3 (verde limpo, por ultimo na ordem) quando so' ha registrados:
    e' um caso comum. Golden + um par anulado: continua limpo."""
    from dataclasses import replace
    from tests.helpers import GOLDEN
    limpo = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    so_registrado = replace(limpo, achados=list(limpo.achados) + [
        Achado(nivel=Nivel.ALERTA, codigo="estorno_pareado", mensagem="par")])
    com_juros = replace(limpo, achados=list(limpo.achados) + [
        Achado(nivel=Nivel.ALERTA, codigo="possivel_juros", mensagem="j")])
    linhas = triagem_linhas([("a.xls", [com_juros], None),
                             ("b.xls", [so_registrado], None)])
    assert [l["Arquivo"] for l in linhas] == ["a.xls", "b.xls"]   # alerta antes
    assert linhas[1]["Achados"] == "—"
    assert linhas[0]["Achados"] == "1 alerta(s)"


# --- tela: nao decididos em caixa, registrados num expander fechado -----------

def _tela_com_as_duas_classes(monkeypatch):
    from datetime import date

    from streamlit.testing.v1 import AppTest

    from tests.fixtures import gerar_sinteticas as G
    from tests.test_app_ponte import MAIN
    E = "FORNECEDOR FICTICIO"
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("0.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", [
        (date(2025, 1, 2), 4001, f"Vr. compras conf. 5001 {E} LTDA", None, D("100.00")),
        (date(2025, 1, 3), 4002, f"Vr. compras conf. 5002 {E} LTDA", None, D("100.00")),
        (date(2025, 1, 4), 4003, f"Vr. compras conf. 5003 {E} LTDA", None, D("100.00")),
        # por valor, 2 candidatas de datas distintas -> FIFO (registrado)
        (date(2025, 1, 5), 4004, f"Pago conf. {E}", D("100.00"), None),
        # pelo numero, acima da compra -> possivel juros (nao decidido)
        (date(2025, 1, 6), 4005, "- PAGTO REF. NF.:  5003.1 - PARC.:FORN",
         D("102.46"), None),
    ])
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("classes.xlsx", G.montar_xlsx(),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert len(at.exception) == 0
    return at


def test_tela_separa_nao_decidido_de_registrado(monkeypatch):
    at = _tela_com_as_duas_classes(monkeypatch)
    infos = [i.value for i in at.info]
    assert any("juros" in t for t in infos)
    assert not any("desempate" in t for t in infos)
    (exp,) = [e for e in at.expander if e.label.startswith(REGISTRADO)]
    assert exp.label == f"{REGISTRADO} (1)"
    assert exp.proto.expanded is False
    assert any("desempate" in m.value for m in exp.markdown)


# --- Excel: todos continuam, com a coluna Classe pra filtro ---------------------

def test_excel_traz_todos_os_alertas_com_a_classe():
    from app.apresentacao import alertas_celulas
    celulas = alertas_celulas([
        Achado(nivel=Nivel.ALERTA, codigo="casamento_por_desempate",
               mensagem="desempate"),
        Achado(nivel=Nivel.ALERTA, codigo="possivel_juros", mensagem="juros")])
    assert [c["Classe"] for c in celulas] == [REGISTRADO, NAO_DECIDIDO]
    # a evidencia integral continua a ultima coluna; Tipo e NF/Lote
    # continuam as primeiras
    assert list(celulas[0])[:2] == ["Tipo", "NF/Lote"]
    assert list(celulas[0])[-2:] == ["Classe", "Evidencia"]



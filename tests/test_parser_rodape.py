"""Rotulos "SALDO ANTERIOR" e "Total da conta:" ABAIXO do total
da conta (composicao manual colada no rodape, como no golden) nao reescrevem a
conta ja fechada. Razao sintetica .xls no layout do Dominio; dados ficticios.
"""
from datetime import date
from decimal import Decimal

import xlwt

from app.pipeline import processar_excel
from core.modelo import Nivel
from parser.excel import ExcelParser
from tests.fixtures.gerar_sinteticas import (
    CNPJ, COL_SALDO, EMPRESA, PERIODO, _serial)

D = Decimal
COMPRAS = [(5, "Vr. compras conf. 1111 FORNECEDOR FICTICIO LTDA", "12345.67"),
           (6, "Vr. compras conf. 2222 FORNECEDOR FICTICIO LTDA", "1000.00")]


def _razao(caminho, rodape):
    """Conta com SALDO ANTERIOR 0,00 e 2 compras (13.345,67 no credito);
    `rodape`: (linhas abaixo do total, coluna, valor) escritos depois do total."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Razão")
    ws.write(0, 0, "Empresa:"); ws.write(0, 2, EMPRESA)
    ws.write(1, 0, "C.N.P.J.:"); ws.write(1, 2, CNPJ)
    ws.write(2, 0, "Período:"); ws.write(2, 2, PERIODO)
    ws.write(3, 0, "RAZÃO")
    ws.write(5, 0, "Data"); ws.write(5, 1, "Número"); ws.write(5, 2, "Histórico")
    ws.write(5, 7, "Cta.C.Part."); ws.write(5, 8, "Débito"); ws.write(5, 9, "Crédito")
    ws.write(5, COL_SALDO, "Saldo-Exercício")
    ws.write(6, 0, "Conta:"); ws.write(6, 1, 7001.0)
    ws.write(6, 2, "2.01.01.001.00"); ws.write(6, 5, "FORNECEDOR FICTICIO LTDA")
    ws.write(7, 2, "SALDO ANTERIOR"); ws.write(7, COL_SALDO, 0.0)
    r, saldo = 8, D("0.00")
    for i, (dia, hist, cred) in enumerate(COMPRAS):
        saldo -= D(cred)
        ws.write(r, 0, _serial(date(2025, 3, dia))); ws.write(r, 1, float(5000 + i))
        ws.write(r, 2, hist); ws.write(r, 7, 38.0)
        ws.write(r, 9, float(cred)); ws.write(r, COL_SALDO, float(saldo)); r += 1
    r += 1
    ws.write(r, 4, "Total da conta:"); ws.write(r, 8, 0.0); ws.write(r, 9, 13345.67)
    for (abaixo, coluna, valor) in rodape:
        ws.write(r + abaixo, coluna, valor)
    wb.save(str(caminho))


RODAPE = [(3, 2, "SALDO ANTERIOR"), (3, COL_SALDO, -500.0),
          (4, 4, "Total da conta:"), (4, 8, 0.0), (4, 9, 999.0)]


def _conta(caminho):
    (conta,) = ExcelParser().parse(caminho)
    return (conta.saldo_anterior, conta.total_debito_dominio,
            conta.total_credito_dominio)


def test_rotulos_depois_do_total_da_conta_nao_reescrevem_a_conta(tmp_path):
    caminho = tmp_path / "com_rodape.xls"
    _razao(caminho, RODAPE)
    assert _conta(caminho) == (D("0.00"), D("0.00"), D("13345.67"))
    (res,) = processar_excel(str(caminho)).resultados
    assert [a.codigo for a in res.achados if a.nivel is Nivel.ERRO] == []


def test_so_o_saldo_anterior_do_rodape_tambem_e_ignorado(tmp_path):
    caminho = tmp_path / "rodape_so_saldo.xls"
    _razao(caminho, RODAPE[:2])
    assert _conta(caminho) == (D("0.00"), D("0.00"), D("13345.67"))


def test_so_o_total_do_rodape_tambem_e_ignorado(tmp_path):
    caminho = tmp_path / "rodape_so_total.xls"
    _razao(caminho, RODAPE[2:])
    assert _conta(caminho) == (D("0.00"), D("0.00"), D("13345.67"))


def test_razao_sem_rodape_le_o_mesmo(tmp_path):
    """CONTROLE: o rodape nao muda nada do que ja era lido sem ele."""
    caminho = tmp_path / "sem_rodape.xls"
    _razao(caminho, [])
    assert _conta(caminho) == (D("0.00"), D("0.00"), D("13345.67"))

"""TETO DE ENTRADA (trilha U, G3): 5.000 lancamentos por conta e 100 contas por arquivo, recusados na casca (depois da leitura,
antes do motor); o ARQUIVO inteiro e recusado com a frase de fato e os outros arquivos do lote seguem. Arquivos sinteticos
gerados AQUI (ciclos da conta 7777 da sintetica_integra); nada de planilha real."""
import io
import re
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

from app.pipeline import ArquivoAcimaDoLimite, processar_excel
from parser.excel import ExcelParser
from tests.test_app_pagina_cortada import CAB, INTEGRA, MAIN, MIME, ZERO, xlsx_de_n_contas

CODIGO = 9001


def xlsx_com_lancamentos(n: int, codigo: int = CODIGO) -> bytes:
    """1 conta com exatamente n lancamentos (o bloco da conta 7777 repetido em ciclo)."""
    base = ExcelParser().parse(str(INTEGRA))[0]
    lancs = [(l.data, int(l.numero), l.historico, int(l.cta_part), l.debito, l.credito) for l in base.lancamentos]
    wb = openpyxl.Workbook()
    ws = wb.active
    for linha in (["Empresa:", None, "COMERCIAL FICTICIA LTDA"], ["C.N.P.J.:", None, "00.000.000/0000-00"],
                  ["Período:", None, "01/01/2024 - 31/12/2025"], ["RAZÃO"], [], CAB):
        ws.append(linha)
    ws.append(["Conta:", codigo, "2.01.01.001.00", None, None, "FORNECEDOR FICTICIO GRANDE LTDA"])
    ws.append([None, None, "SALDO ANTERIOR"] + [None] * 8 + [float(base.saldo_anterior)])
    saldo, td, tc = base.saldo_anterior, ZERO, ZERO
    for i in range(n):
        d, numero, hist, cta, deb, cre = lancs[i % len(lancs)]
        saldo, td, tc = saldo + deb - cre, td + deb, tc + cre
        ws.append([datetime(d.year, d.month, d.day), numero, hist, None, None, None, None, cta,
                   float(deb) if deb != ZERO else None, float(cre) if cre != ZERO else None, None, float(saldo)])
    ws.append([])
    ws.append([None, None, None, None, "Total da conta:", None, None, None, float(td), float(tc)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _arquivo(dados: bytes) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(dados)
    return Path(f.name)


def _tela(*arquivos):
    at = AppTest.from_file(str(MAIN), default_timeout=180).run()
    at.file_uploader[0].set_value([(nome, dados, MIME) for nome, dados in arquivos]).run()
    return at


def test_conta_com_5001_lancamentos_e_recusada_com_conta_e_contagem():
    with pytest.raises(ArquivoAcimaDoLimite) as erro:
        processar_excel(_arquivo(xlsx_com_lancamentos(5001)))
    assert erro.value.total_contas == 1
    assert erro.value.contas_acima == [(str(CODIGO), 5001)]


def test_conta_com_exatamente_5000_lancamentos_passa():
    resultados = processar_excel(_arquivo(xlsx_com_lancamentos(5000))).resultados
    assert len(resultados) == 1 and len(resultados[0].conta.lancamentos) == 5000


def test_101_contas_sao_recusadas_com_a_contagem():
    with pytest.raises(ArquivoAcimaDoLimite) as erro:
        processar_excel(_arquivo(xlsx_de_n_contas(101)))
    assert erro.value.total_contas == 101


def test_exatamente_100_contas_passam():
    assert len(processar_excel(_arquivo(xlsx_de_n_contas(100))).resultados) == 100


def test_lote_recusa_so_o_arquivo_acima_do_limite_e_os_outros_seguem():
    at = _tela(("integra.xls", INTEGRA.read_bytes()), ("grande.xlsx", xlsx_com_lancamentos(5001)))
    assert len(at.exception) == 0
    assert len(at.error) == 1
    frase = at.error[0].value
    assert "5.001" in frase and "5.000" in frase and "Nenhum resultado foi gerado" in frase and "grande.xlsx" in frase
    codigos = [re.search(r"Conta (\d+)", s.value).group(1) for s in at.subheader if "Conta " in s.value]
    assert codigos == ["7777"]
    triagem = next(m.value for m in at.markdown if "<table" in m.value and "Veredito" in m.value)
    assert triagem.count("<tr") - 1 == 2 and "Acima do limite" in triagem
    assert "Erro de leitura" not in triagem
    assert len(at.get("download_button")) == 1                # so o da integra; sem ZIP


def test_arquivo_unico_com_101_contas_e_recusado():
    at = _tela(("cem.xlsx", xlsx_de_n_contas(101)))
    assert len(at.exception) == 0 and len(at.subheader) == 0
    assert len(at.error) == 1 and "101" in at.error[0].value and "100" in at.error[0].value


def test_as_3_frases_e_o_rotulo_da_triagem():
    from app.apresentacao import (
        ACIMA_DO_LIMITE,
        arquivo_com_conta_grande_texto,
        arquivo_com_contas_demais_texto,
        arquivo_com_contas_grandes_texto,
    )
    assert arquivo_com_conta_grande_texto("a.xlsx", "9001", 5001, 5000) == (
        "'a.xlsx': a conta 9001 tem 5.001 lançamentos; o limite por conta é 5.000. "
        "Nenhum resultado foi gerado pra este arquivo.")
    assert arquivo_com_contas_grandes_texto("a.xlsx", 3, "9002", 12345, 5000) == (
        "'a.xlsx': 3 contas têm mais de 5.000 lançamentos (a maior, conta 9002, tem 12.345); "
        "o limite por conta é 5.000. Nenhum resultado foi gerado pra este arquivo.")
    assert arquivo_com_contas_demais_texto("a.xlsx", 101, 100) == (
        "'a.xlsx' tem 101 contas; o limite por arquivo é 100. Nenhum resultado foi gerado pra este arquivo.")
    assert ACIMA_DO_LIMITE == "⛔ Acima do limite"


def test_as_frases_passam_na_regra_de_tela():
    from app.apresentacao import (
        ACIMA_DO_LIMITE,
        arquivo_com_conta_grande_texto,
        arquivo_com_contas_demais_texto,
        arquivo_com_contas_grandes_texto,
    )
    from tests.test_regra_de_tela import _violacoes
    assert _violacoes([arquivo_com_conta_grande_texto("a.xlsx", "9001", 5001, 5000),
                       arquivo_com_contas_grandes_texto("a.xlsx", 3, "9002", 12345, 5000),
                       arquivo_com_contas_demais_texto("a.xlsx", 101, 100), ACIMA_DO_LIMITE]) == []


def test_processar_contas_nao_aplica_o_teto_do_upload():
    from app.pipeline import processar_contas

    contas = ExcelParser().parse(str(_arquivo(xlsx_com_lancamentos(5001))))
    resultado = processar_contas(contas)
    assert len(resultado.resultados) == 1
    assert len(resultado.resultados[0].conta.lancamentos) == 5001


def test_varias_contas_acima_vira_a_frase_com_a_maior():
    from app.apresentacao import FraseAcimaDoLimite
    from app.main import _frase_do_teto
    frase = _frase_do_teto("a.xlsx", ArquivoAcimaDoLimite(4, [("9001", 5001), ("9002", 9000)]))
    assert isinstance(frase, FraseAcimaDoLimite)
    assert frase == ("'a.xlsx': 2 contas têm mais de 5.000 lançamentos (a maior, conta 9002, tem 9.000); "
                     "o limite por conta é 5.000. Nenhum resultado foi gerado pra este arquivo.")


@pytest.fixture
def chamadas_do_motor(monkeypatch):
    """Conta quantas contas chegam ao motor (core.conferencia.conferir, como o pipeline o usa)."""
    import app.pipeline as pipeline
    chamadas = []
    original = pipeline.conferir

    def conta(conta_, *args, **kwargs):
        chamadas.append(conta_.codigo)
        return original(conta_, *args, **kwargs)
    monkeypatch.setattr(pipeline, "conferir", conta)
    return chamadas


@pytest.mark.parametrize("dados", [xlsx_com_lancamentos(5001), xlsx_de_n_contas(101)], ids=["lancamentos", "contas"])
def test_a_recusa_acontece_antes_do_motor(chamadas_do_motor, dados):
    with pytest.raises(ArquivoAcimaDoLimite):
        processar_excel(_arquivo(dados))
    assert chamadas_do_motor == []


def test_no_lote_o_recusado_nao_chega_ao_motor_e_o_bom_chega(chamadas_do_motor):
    at = _tela(("integra.xls", INTEGRA.read_bytes()), ("grande.xlsx", xlsx_com_lancamentos(5001)),
               ("cem.xlsx", xlsx_de_n_contas(101)))
    assert len(at.exception) == 0 and len(at.error) == 2
    assert set(chamadas_do_motor) == {"7777"}                   # so a conta do arquivo bom (a tela repete a chamada por rerun)
    assert not {"9001", "8001"} & set(chamadas_do_motor)
    chamadas_do_motor.clear()
    processar_excel(_arquivo(xlsx_de_n_contas(3)))
    assert len(chamadas_do_motor) == 3                         # o arquivo bom do mesmo tipo chama o motor 1 vez por conta

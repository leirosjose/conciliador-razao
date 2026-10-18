"""Substituto solto (U+D800 a U+DFFF), U+FFFE e U+FFFF saem do texto NA LEITURA, trocados por
espaco -- a mesma classe e a mesma troca que a planilha faz ao gravar (relatorio/excel.py, _NAO_REABRE). Vale pro
leitor de arquivo (parser/excel.py). So dado sintetico."""
import io
import os
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from parser.excel import ErroLeituraExcel, ExcelParser, _GradeXlsx, _id

RAIZ = Path(__file__).resolve().parents[1]
MAIN = RAIZ / "app" / "main.py"
FFFF, FFFE = "￿", "￾"
HIST = "TARIFA ADMINISTRATIVA SEM{c}PADRAO CONHECIDO"
HIST_LIMPO = "TARIFA ADMINISTRATIVA SEM PADRAO CONHECIDO"


def _xls(caminho: Path, *, historico=HIST_LIMPO, numero=5001.0, cta=38.0, nome="FORNECEDOR FICTICIO LTDA",
         classificacao="2.01.01.001.00", codigo=7001.0) -> Path:
    """.xls sintetico no layout do Dominio: 1 compra de 1.000,00 e 1 debito de 10,00. Os parametros sao as celulas
    do DEBITO (historico, numero, contrapartida) e da linha 'Conta:' (codigo, classificacao, nome)."""
    import xlwt
    from tests.fixtures.gerar_sinteticas import CNPJ, COL_SALDO, EMPRESA, PERIODO, _serial
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Razão")
    ws.write(0, 0, "Empresa:"); ws.write(0, 2, EMPRESA)
    ws.write(1, 0, "C.N.P.J.:"); ws.write(1, 2, CNPJ)
    ws.write(2, 0, "Período:"); ws.write(2, 2, PERIODO)
    ws.write(3, 0, "RAZÃO")
    for coluna, titulo in ((0, "Data"), (1, "Número"), (2, "Histórico"), (7, "Cta.C.Part."), (8, "Débito"),
                           (9, "Crédito"), (COL_SALDO, "Saldo-Exercício")):
        ws.write(5, coluna, titulo)
    ws.write(6, 0, "Conta:"); ws.write(6, 1, codigo); ws.write(6, 2, classificacao); ws.write(6, 5, nome)
    ws.write(7, 2, "SALDO ANTERIOR"); ws.write(7, COL_SALDO, 0.0)
    ws.write(8, 0, _serial(date(2025, 3, 1))); ws.write(8, 1, 5000.0)
    ws.write(8, 2, "Vr. compras conf. 1234 FORNECEDOR FICTICIO LTDA"); ws.write(8, 7, 38.0)
    ws.write(8, 9, 1000.0); ws.write(8, COL_SALDO, -1000.0)
    ws.write(9, 0, _serial(date(2025, 3, 2))); ws.write(9, 1, numero); ws.write(9, 2, historico); ws.write(9, 7, cta)
    ws.write(9, 8, 10.0); ws.write(9, COL_SALDO, -990.0)
    ws.write(11, 4, "Total da conta:"); ws.write(11, 8, 10.0); ws.write(11, 9, 1000.0)
    wb.save(str(caminho))
    return caminho


def _lida(caminho: Path):
    contas = ExcelParser().parse(caminho)
    assert len(contas) == 1 and len(contas[0].lancamentos) == 2
    return contas[0]


# --- leitor de arquivo, rota .xls (a unica por onde U+FFFF e U+FFFE chegam hoje) ---------------------------------

@pytest.mark.parametrize("c", [FFFF, FFFE])
def test_historico_do_xls_chega_com_espaco_no_lugar_do_codigo(tmp_path, c):
    conta = _lida(_xls(tmp_path / "h.xls", historico=f"TARIFA{c}LINHA COLADA"))
    assert conta.lancamentos[1].historico == "TARIFA LINHA COLADA"


@pytest.mark.parametrize("c", [FFFF, FFFE])
def test_limpa_antes_de_tirar_as_pontas(tmp_path, c):
    conta = _lida(_xls(tmp_path / "p.xls", historico=f"{c}TARIFA{c}"))
    assert conta.lancamentos[1].historico == "TARIFA"


@pytest.mark.parametrize("c", [FFFF, FFFE])
def test_numero_contrapartida_codigo_classificacao_e_nome_chegam_limpos(tmp_path, c):
    conta = _lida(_xls(tmp_path / "c.xls", numero=f"50{c}01", cta=f"3{c}8", codigo=f"70{c}01",
                       classificacao=f"2.01{c}01.001.00", nome=f"FORNECEDOR{c}FICTICIO LTDA"))
    debito = conta.lancamentos[1]
    assert (debito.numero, debito.cta_part) == ("50 01", "3 8")
    assert (conta.codigo, conta.classificacao, conta.nome) == ("70 01", "2.01 01.001.00", "FORNECEDOR FICTICIO LTDA")


def test_xls_com_substituto_solto_nos_bytes_continua_recusado(tmp_path):
    # trava do fato: o xlrd recusa o arquivo antes do nosso codigo; a limpeza nao muda essa recusa
    marca = "☃☃☃"
    caminho = _xls(tmp_path / "s.xls", historico=f"TARIFA{marca}X")
    bruto = caminho.read_bytes()
    alvo = marca.encode("utf-16-le")
    assert bruto.count(alvo) == 1
    caminho.write_bytes(bruto.replace(alvo, "☃".encode("utf-16-le") + b"\x00\xd8" + "☃".encode("utf-16-le")))
    with pytest.raises(ErroLeituraExcel) as erro:
        ExcelParser().parse(caminho)
    assert "não abriu nem após tentativa de reparo" in str(erro.value)


# --- rota .xlsx: nenhum arquivo .xlsx que abre traz a classe, entao a grade entra pronta ------------------------

def _grade_xlsx(*linhas):
    grade = object.__new__(_GradeXlsx)
    grade._rows = [list(l) for l in linhas]
    grade.nrows, grade.ncols = len(grade._rows), max(len(l) for l in grade._rows)
    return grade


@pytest.mark.parametrize("c", [FFFF, FFFE, "\ud800", "\udfff"])
def test_texto_da_grade_xlsx_e_identificador_saem_limpos(c):
    grade = _grade_xlsx([f"TARIFA{c}LINHA COLADA", f"{c}TARIFA{c}", f"50{c}01"])
    assert [grade.text(0, 0), grade.text(0, 1)] == ["TARIFA LINHA COLADA", "TARIFA"]
    assert _id(grade.valor(0, 2)) == "50 01"
    assert _id(f"{c}38{c}") == "38"


# --- controle: o que nao e da classe sai identico e a classe e exatamente a da planilha ------------------------

@pytest.mark.parametrize("texto", ["�", "﷐", "\U0001f600", "퟿", "", "\U0001fffe", "\U0010ffff",
                                   "Ação à vista", ""])
def test_o_que_nao_e_da_classe_sai_identico(texto):
    assert _grade_xlsx([f"A{texto}B"]).text(0, 0) == f"A{texto}B"
    assert _id(f"A{texto}B") == f"A{texto}B"


def test_a_classe_inteira_e_a_da_planilha_nem_um_codigo_a_mais_nem_a_menos():
    from relatorio.excel import _NAO_REABRE
    trocados = [n for n in range(0x110000) if _id(f"A{chr(n)}B") == "A B" and chr(n) != " "]
    assert len(trocados) == 2050
    assert trocados == list(range(0xD800, 0xE000)) + [0xFFFE, 0xFFFF]
    assert trocados == [n for n in range(0x110000) if _NAO_REABRE.fullmatch(chr(n))]
    # e nenhum outro codigo muda: fora da classe, o identificador sai como entrou
    assert all(_id(f"A{chr(n)}B") == f"A{chr(n)}B" for n in range(0x110000) if n not in set(trocados))
    grade = _grade_xlsx([f"A{chr(0xDFFF)}B", f"A{chr(0xD800)}B"])
    assert [grade.text(0, 0), grade.text(0, 1)] == ["A B", "A B"]


@pytest.mark.parametrize("c", [FFFF, FFFE])
def test_a_copia_fiel_do_arquivo_fica_crua(tmp_path, c):
    # a grade crua (materia-prima da copia fiel) nao passa pela limpeza: traz o texto do arquivo, com as pontas
    from parser.excel import grade_bruta
    historico, nome = f" TARIFA{c}LINHA COLADA{c} ", f"FORNECEDOR{c}FICTICIO LTDA"
    arquivo = _xls(tmp_path / "r.xls", historico=historico, nome=nome)
    textos = [v for linha in grade_bruta(arquivo.read_bytes()) for v in linha if isinstance(v, str)]
    assert [v for v in textos if "TARIFA" in v] == [historico]
    assert [v for v in textos if "FORNECEDOR" in v and "Vr." not in v] == [nome]
    conta = _lida(arquivo)
    assert (conta.lancamentos[1].historico, conta.nome) == ("TARIFA LINHA COLADA", "FORNECEDOR FICTICIO LTDA")


# --- a tela: U+FFFF/U+FFFE fora do item sem destino -------------------------------------------------------------

@pytest.mark.parametrize("c", [FFFF, FFFE])
def test_historico_integral_do_item_sem_destino_sem_o_codigo(monkeypatch, tmp_path, c):
    arquivo = _xls(tmp_path / "tela.xls", historico=HIST.format(c=c))
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value((arquivo.name, arquivo.read_bytes(), "application/vnd.ms-excel")).run()
    assert not at.exception
    integral = [m.value for m in at.markdown if "Histórico integral" in m.value]
    assert integral == [f"**Histórico integral:**\n<blockquote>{HIST_LIMPO}</blockquote>"]
    textos = ([m.value for m in at.markdown] + [x.value for x in at.caption] + [e.label for e in at.expander]
              + [s.value for s in at.subheader] + [str(v) for d in at.dataframe for v in d.value.values.flatten()])
    assert [t for t in textos if FFFF in t or FFFE in t] == []


# --- navegador real, opt-in (CONCILIADOR_TESTE_NAVEGADOR=1): 2 layouts x 2 temas -------------------------------

_ROTEIRO_DA_TELA = """
import runpy, sys
sys.path.insert(0, {raiz!r})
runpy.run_path({main!r}, run_name="__main__")
"""


@pytest.fixture(scope="module")
def navegador_limpeza():
    if os.environ.get("CONCILIADOR_TESTE_NAVEGADOR") != "1":
        pytest.skip("Chromium opt-in: CONCILIADOR_TESTE_NAVEGADOR=1")
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(scope="module", params=["upload"])
def tela_limpeza(request, navegador_limpeza, tmp_path_factory):
    """A tela de upload num servidor local (127.0.0.1, porta efemera). Derrubado pelo processo."""
    pasta = tmp_path_factory.mktemp(f"tela_limpeza_{request.param}")
    roteiro = pasta / "tela.py"
    roteiro.write_text(_ROTEIRO_DA_TELA.format(raiz=str(RAIZ), main=str(MAIN)), encoding="utf-8")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); porta = s.getsockname()[1]
    log = (pasta / "streamlit.log").open("w")
    proc = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", str(roteiro), "--server.address", "127.0.0.1",
        "--server.port", str(porta), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=RAIZ, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), stdout=log, stderr=subprocess.STDOUT)
    try:
        limite = time.monotonic() + 30
        while True:
            assert proc.poll() is None, "o servidor local terminou antes de abrir"
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=0.2):
                    break
            except OSError:
                assert time.monotonic() < limite, "o servidor local não abriu em 30 s"
                time.sleep(0.1)
        yield navegador_limpeza, f"http://127.0.0.1:{porta}", request.param
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=10)
        log.close()


@pytest.mark.parametrize("tema", ["light", "dark"])
@pytest.mark.parametrize("c", [FFFF, FFFE], ids=["U+FFFF", "U+FFFE"])
def test_chromium_o_quadradinho_some_do_historico_integral_e_a_planilha_traz_o_mesmo_texto(tela_limpeza, tmp_path, tema, c):
    import openpyxl
    from playwright.sync_api import expect
    browser, url, layout = tela_limpeza
    arquivo = _xls(tmp_path / "navegador.xls", historico=HIST.format(c=c))
    ctx = browser.new_context(color_scheme=tema, viewport={"width": 1280, "height": 1600}, locale="pt-BR",
                              accept_downloads=True)
    page = ctx.new_page()
    try:
        page.goto(url)
        page.get_by_role("heading", level=1).wait_for()
        assert page.get_by_role("tab").count() == 0
        page.set_input_files('input[type="file"]', str(arquivo))
        item = page.locator("details").filter(has=page.locator("summary").filter(has_text="Histórico não reconhecido"))
        expect(item).to_have_count(1)
        item.locator("summary").click()
        citacao = item.locator("blockquote")
        expect(citacao).to_have_text(HIST_LIMPO)                  # espera pela condicao, sem tempo fixo
        expect(page.locator('[data-testid="stApp"]')).to_have_attribute("data-test-script-state", "notRunning")
        na_pagina = page.evaluate("() => (document.body.innerText.match(/[\\uFFFE\\uFFFF]/g) || []).length")
        print("NAVEGADOR", layout, tema, "U+%04X" % ord(c), "codigos na pagina:", na_pagina, "| citacao:", citacao.inner_text())
        assert na_pagina == 0
        with page.expect_download() as baixada:
            page.locator('[data-testid="stDownloadButton"] button').first.click()
        planilha = openpyxl.load_workbook(io.BytesIO(Path(baixada.value.path()).read_bytes()))
        for aba in planilha:
            textos = [x.value for linha in aba for x in linha if isinstance(x.value, str)]
            assert HIST_LIMPO in textos, aba.title
            assert [t for t in textos if FFFF in t or FFFE in t] == [], aba.title
    finally:
        ctx.close()

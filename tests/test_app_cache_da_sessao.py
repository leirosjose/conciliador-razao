"""Contadores em memória, sessão isolada e fotografia da exportação."""
import os
import socket
import subprocess
import sys
import time
import zipfile
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

import app.main as main
import relatorio
from app.pipeline import processar_excel

RAIZ = Path(__file__).resolve().parents[1]
FIX = RAIZ / "tests/fixtures"
FIXO = datetime(2026, 10, 9, 12)


def foto(dados):
    wb = openpyxl.load_workbook(BytesIO(dados))
    return [(ws.title, list(ws.values)) for ws in wb]


@pytest.fixture
def sessao(monkeypatch):
    estado = {}
    monkeypatch.setattr(main.st, "session_state", estado)
    return estado


def entrada(nome="sintetica_integra.xls", chave="arquivo"):
    caminho = FIX / nome
    return main._EntradaLote(nome=nome, chave=chave, dados=caminho.read_bytes(),
                             resultados=processar_excel(caminho).resultados)


def test_upload_reutiliza_por_valor_e_invalida_bytes_nome_decisao(monkeypatch, sessao):
    chamadas = []
    def gerar(resultados, dados, nome):
        chamadas.append((deepcopy(resultados), dados, nome))
        return str(len(chamadas)).encode()
    monkeypatch.setattr(main, "gerar_excel", gerar)
    e = entrada()
    assert main._downloads_do_lote([e])[0][2] == b"1"
    assert main._downloads_do_lote([deepcopy(e)])[0][2] == b"1"
    e.dados += b"bytes diferentes, mesmo nome e resultado"
    assert main._downloads_do_lote([e])[0][2] == b"2"
    e.nome = "outro.xls"
    assert main._downloads_do_lote([e])[0][2] == b"3"
    e.resultados[0].decisoes.append("decisao sintetica")
    assert main._downloads_do_lote([e])[0][2] == b"4"
    # A assinatura guardada não pode compartilhar o mutável da tela.
    e.resultados[0].decisoes.clear()
    assert main._downloads_do_lote([e])[0][2] == b"5"
    assert len(chamadas) == 5


def test_sessoes_e_chaves_distintas_nao_compartilham_cache(monkeypatch, sessao):
    chamadas = []
    monkeypatch.setattr(main, "gerar_excel", lambda *a: chamadas.append(1) or b"xlsx")
    a = entrada(chave="A")
    b = entrada(chave="B")
    main._downloads_do_lote([a, b])
    main._downloads_do_lote([deepcopy(a), deepcopy(b)])
    assert len(chamadas) == 2
    monkeypatch.setattr(main.st, "session_state", {})
    main._downloads_do_lote([a, b])
    assert len(chamadas) == 4


def test_falha_nao_publica_assinatura_e_tenta_de_novo(monkeypatch, sessao):
    chamadas = []
    def gerar(*args):
        chamadas.append(1)
        if len(chamadas) in (1, 4):
            raise RuntimeError("falha sintetica")
        return str(len(chamadas)).encode()
    monkeypatch.setattr(main, "gerar_excel", gerar)
    e = entrada()
    falhas = []
    assert main._downloads_do_lote([e], falhas) == []
    assert falhas == [e]
    assert main._downloads_do_lote([e])[0][2] == b"2"
    assert main._downloads_do_lote([e])[0][2] == b"2"
    e.dados += b"nova entrada"
    assert main._downloads_do_lote([e])[0][2] == b"3"
    e.dados += b"entrada que falha"
    falhas = []
    assert main._downloads_do_lote([e], falhas) == []
    assert falhas == [e]
    assert main._downloads_do_lote([e])[0][2] == b"5"


def test_zip_invalida_conteudo_nome_ordem_e_sessao(monkeypatch, sessao):
    chamadas = []
    def gerar(arquivos):
        chamadas.append(arquivos)
        return str(len(chamadas)).encode()
    monkeypatch.setattr(main, "zip_relatorios", gerar)
    lote = [("A", "A.xlsx", b"A"), ("B", "B.xlsx", b"B")]
    assert main._zip_do_lote(lote) == b"1"
    assert main._zip_do_lote(deepcopy(lote)) == b"1"
    lote[0] = ("A", "A.xlsx", b"C")
    assert main._zip_do_lote(lote) == b"2"
    lote[0] = ("A", "renomeado.xlsx", b"C")
    assert main._zip_do_lote(lote) == b"3"
    lote.reverse()
    assert main._zip_do_lote(lote) == b"4"
    monkeypatch.setattr(main.st, "session_state", {})
    assert main._zip_do_lote(lote) == b"5"
    assert len(chamadas) == 5


def test_falha_do_zip_nao_fica_guardada(monkeypatch, sessao):
    chamadas = []
    def gerar(arquivos):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("falha sintetica de ZIP")
        return b"ZIP"
    monkeypatch.setattr(main, "zip_relatorios", gerar)
    lote = [("A", "A.xlsx", b"A")]
    with pytest.raises(RuntimeError, match="falha sintetica de ZIP"):
        main._zip_do_lote(lote)
    assert main._zip_do_lote(lote) == b"ZIP"
    assert main._zip_do_lote(lote) == b"ZIP"
    assert len(chamadas) == 2


def test_tirar_arquivo_soltar_cache_e_zip_reenviar_gera_so_ele(monkeypatch, sessao):
    chamadas = []
    monkeypatch.setattr(main, "gerar_excel", lambda *a: chamadas.append(a[2]) or b"xlsx")
    a, b = entrada(chave="A"), entrada(chave="B")
    sessao["outra::chave"] = {"sentinela": True}
    sessao["alocacoes::A"] = ["decisao sintetica"]
    main._zip_do_lote(main._downloads_do_lote([a,b]))
    assert len(chamadas) == 2 and "upload::excel::B" in sessao
    assert "exportacao::zip" in sessao
    main._downloads_do_lote([a])
    assert "upload::excel::B" not in sessao
    assert "exportacao::zip" not in sessao
    assert sessao["outra::chave"] == {"sentinela": True}
    assert sessao["alocacoes::A"] == ["decisao sintetica"]
    main._downloads_do_lote([a,b])
    assert len(chamadas) == 3
    main._downloads_do_lote([a,b])
    assert len(chamadas) == 3
    main._downloads_do_lote([])
    assert not any(k.startswith("upload::excel::") for k in sessao)


def test_tela_tira_b_e_esvazia_lote_sem_deixar_cache(monkeypatch):
    excels, zips = _contador(monkeypatch)
    uploads = [(n,(FIX/"sintetica_integra.xls").read_bytes(),"application/vnd.ms-excel")
               for n in ("A.xls","B.xls")]
    at = AppTest.from_file(str(RAIZ/"app/main.py"),default_timeout=60).run()
    at.file_uploader[0].set_value(uploads).run()
    assert len(excels) == 2
    at.file_uploader[0].set_value(uploads[:1]).run()
    assert "upload::excel::B.xls" not in at.session_state.filtered_state
    assert "exportacao::zip" not in at.session_state.filtered_state
    assert len(excels) == 2
    at.file_uploader[0].set_value(uploads).run()
    assert len(excels) == 3
    at.run()
    assert len(excels) == 3
    at.file_uploader[0].set_value([]).run()
    assert not any(k.startswith("upload::excel::") for k in at.session_state.filtered_state)
    assert "exportacao::zip" not in at.session_state.filtered_state
    assert len(at.get("download_button")) == 0
    at.file_uploader[0].set_value(uploads[:1]).run()
    assert len(excels) == 4 and len(at.exception) == 0


def _contador(monkeypatch):
    excels, zips = [], []
    original = relatorio.gerar_excel
    original_zip = relatorio.zip_relatorios
    def gerar(*a, **k):
        dados = original(*a, **dict(k, gerado_em=FIXO))
        excels.append((a[2], dados))
        return dados
    def pacote(arquivos):
        dados = original_zip(arquivos)
        zips.append(dados)
        return dados
    monkeypatch.setattr(relatorio, "gerar_excel", gerar)
    monkeypatch.setattr(relatorio, "zip_relatorios", pacote)
    return excels, zips


def _tela():
    at = AppTest.from_file(str(RAIZ / "app/main.py"), default_timeout=60).run()
    nomes = ["sintetica_integra.xls", "sintetica_integra.xlsx",
             "sintetica_corrompida.xls", "sintetica_adulterada.xls"]
    at.file_uploader[0].set_value([(n, (FIX / n).read_bytes(),
                                   "application/vnd.ms-excel") for n in nomes]).run()
    assert len(at.exception) == 0
    return at


def test_tres_reexecucoes_sem_decisao_nao_geram_excel_nem_zip(monkeypatch):
    excels, zips = _contador(monkeypatch)
    at = _tela()
    assert (len(excels), len(zips)) == (3, 1)
    for _ in range(3):
        at.run()
        assert len(at.exception) == 0
    assert (len(excels), len(zips)) == (3, 1)


def test_aplicar_so_regera_um_e_desfazer_restaura_excel(monkeypatch):
    excels, zips = _contador(monkeypatch)
    at = _tela()
    antes = {nome: foto(dados) for nome, dados in excels}
    with zipfile.ZipFile(BytesIO(zips[0])) as z:
        antes_zip = {nome: foto(z.read(nome)) for nome in z.namelist()}
    caixa = next(s for s in at.selectbox if s.label == "Alocar em")
    caixa.select(next(o for o in caixa.options if "não pertence" in o)).run()
    # Só escolher um destino não altera a decisão.
    assert (len(excels), len(zips)) == (3, 1)
    at.text_input[0].set_value("decisao sintetica da sessao")
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0
    assert (len(excels), len(zips)) == (4, 2)
    alterado = excels[-1][0]
    assert foto(excels[-1][1]) != antes[alterado]
    next(b for b in at.button if b.label == "Desfazer").click().run()
    assert len(at.exception) == 0
    assert (len(excels), len(zips)) == (5, 3)
    assert foto(excels[-1][1]) == antes[alterado]
    with zipfile.ZipFile(BytesIO(zips[-1])) as z:
        assert len(z.namelist()) == 3
        for nome in z.namelist():
            assert foto(z.read(nome)) == antes_zip[nome]


def test_falha_visivel_e_recuperacao_na_proxima_execucao(monkeypatch):
    excels, zips = _contador(monkeypatch)
    original = relatorio.gerar_excel
    falhar = [True]
    def gerar(*a, **k):
        if falhar[0] and a[2] == "sintetica_integra.xls":
            raise RuntimeError("falha sintetica de planilha")
        return original(*a, **k)
    monkeypatch.setattr(relatorio, "gerar_excel", gerar)
    at = _tela()
    assert any("a planilha deste arquivo não foi gerada" in e.value for e in at.error)
    assert len(excels) == 2
    falhar[0] = False
    at.run()
    assert len(at.exception) == 0
    assert not any("a planilha deste arquivo não foi gerada" in e.value for e in at.error)
    assert (len(excels), len(zips)) == (3, 2)


@pytest.fixture(scope="module")
def navegador_cache(tmp_path_factory):
    if os.environ.get("CONCILIADOR_TESTE_NAVEGADOR") != "1":
        pytest.skip("Chromium opt-in: CONCILIADOR_TESTE_NAVEGADOR=1")
    from playwright.sync_api import sync_playwright
    pasta = tmp_path_factory.mktemp("browser_cache")
    wrapper = pasta / "tela.py"
    # Relógio fixo só no harness: nenhuma célula é excluída da comparação.
    wrapper.write_text(
        "import sys\nfrom pathlib import Path\nfrom datetime import datetime\n"
        f"sys.path.insert(0, {str(RAIZ)!r})\n"
        "import relatorio\n"
        "if not hasattr(relatorio, '_cache_original'):\n"
        "    relatorio._cache_original = relatorio.gerar_excel\n"
        "def gerar(*a, **k):\n"
        "    return relatorio._cache_original(*a, **dict(k, gerado_em=datetime(2026,10,9,12)))\n"
        "relatorio.gerar_excel = gerar\n"
        f"exec(compile(Path({str(RAIZ / 'app/main.py')!r}).read_text(), "
        f"{str(RAIZ / 'app/main.py')!r}, 'exec'))\n")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    log = (pasta / "servidor.txt").open("w")
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(wrapper),
                             "--server.address", "127.0.0.1", "--server.port", str(porta),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        limite = time.monotonic() + 30
        while True:
            assert proc.poll() is None
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=.2):
                    break
            except OSError:
                assert time.monotonic() < limite
                time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                yield browser, f"http://127.0.0.1:{porta}"
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=10)
        log.close()


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_navegador_download_apos_aplicar_e_desfazer(navegador_cache, tmp_path, tema):
    from playwright.sync_api import expect
    browser, url = navegador_cache
    ctx = browser.new_context(color_scheme=tema, viewport={"width": 1280, "height": 1600},
                              locale="pt-BR", accept_downloads=True)
    page = ctx.new_page()
    try:
        page.goto(url)
        page.get_by_role("heading", level=1).wait_for()
        page.set_input_files('input[type="file"]', str(FIX / "sintetica_integra.xls"))
        botao = page.get_by_role("button", name="Baixar Excel", exact=False)
        expect(botao).to_have_count(1)
        def baixar():
            with page.expect_download() as dl:
                botao.click()
            d = dl.value
            assert d.suggested_filename == "sintetica_integra_conferencia.xlsx"
            return foto(Path(d.path()).read_bytes())
        antes = baixar()
        detalhe = page.locator("details").filter(has=page.locator("summary").filter(
            has_text="Estorno sem a operação correspondente")).last
        detalhe.locator("summary").click()
        expect(detalhe).to_have_attribute("open", "")
        detalhe.locator('[data-testid="stSelectbox"] input').click()
        page.get_by_role("option").filter(has_text="não pertence").first.click()
        page.locator('[data-testid="stTextInput"] input:visible').first.fill("decisao sintetica da sessao")
        page.get_by_role("button", name="Aplicar", exact=True).filter(visible=True).first.click()
        expect(page.get_by_role("button", name="Desfazer", exact=True)).to_have_count(1)
        assert baixar() != antes
        page.get_by_role("button", name="Desfazer", exact=True).click()
        expect(page.get_by_role("button", name="Desfazer", exact=True)).to_have_count(0)
        assert baixar() == antes
        expect(page.locator('[data-testid="stException"]')).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / f"cache_{tema}.png"))
    finally:
        ctx.close()

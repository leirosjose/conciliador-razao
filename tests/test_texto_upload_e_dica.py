"""Textos do upload e da dica: por AppTest e por Chromium real, opt-in e só sintético.

Rodar navegador com CONCILIADOR_TESTE_NAVEGADOR=1. A fixture sobe somente
uma instância local descartável desta cópia e a encerra; nunca usa .env.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).parent.parent
INTEGRA = RAIZ / "tests/fixtures/sintetica_integra.xls"


@pytest.mark.parametrize("n", [10, 11])
def test_limite_de_upload_com_acento(monkeypatch, n):
    at = AppTest.from_file(str(RAIZ / "app/main.py"), default_timeout=60).run()
    at.file_uploader[0].set_value([
        (f"sintetica_{i}.xls", INTEGRA.read_bytes(), "application/vnd.ms-excel")
        for i in range(n)]).run()
    assert len(at.exception) == 0
    if n == 11:
        assert [e.value for e in at.error] == [
            "Lote com 11 arquivos — o limite é 10 por vez; nenhum arquivo foi processado."]
        assert len(at.subheader) == 0
    else:
        assert len(at.error) == 0
        assert len(at.subheader) == 10


@pytest.fixture(scope="module")
def navegador_texto(tmp_path_factory):
    if os.environ.get("CONCILIADOR_TESTE_NAVEGADOR") != "1":
        pytest.skip("Chromium opt-in: CONCILIADOR_TESTE_NAVEGADOR=1")
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); porta = s.getsockname()[1]
    pasta = tmp_path_factory.mktemp("browser_texto")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    log = (pasta / "streamlit.log").open("w")
    proc = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "app/main.py",
        "--server.address", "127.0.0.1", "--server.port", str(porta),
        "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        limite = time.monotonic() + 30
        while True:
            assert proc.poll() is None, "fixture local terminou antes de abrir"
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() > limite:
                    pytest.fail("fixture local não abriu em 30 s")
                time.sleep(0.1)
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


@pytest.fixture(params=["light", "dark"])
def pagina_texto(navegador_texto, request, tmp_path):
    browser, url = navegador_texto
    # O tema da tela segue a preferência do navegador, não só --theme.base.
    ctx = browser.new_context(color_scheme=request.param,
                              viewport={"width": 1280, "height": 1600}, locale="pt-BR")
    page = ctx.new_page()
    try:
        page.goto(url)
        page.get_by_role("heading", level=1).wait_for()
        _estilos_prontos(page, request.param)
        yield page, request.param
    finally:
        (tmp_path / "pagina_final.txt").write_text(page.inner_text("body"))
        (tmp_path / "details_final.json").write_text(json.dumps(page.locator("details").evaluate_all("es => es.map(e=>({texto:e.querySelector('summary').innerText,open:e.open,visible:!!e.getBoundingClientRect().height}))"), indent=2))
        page.screenshot(path=str(tmp_path / "pagina_final.png"))
        ctx.close()


def _estilos_prontos(page, tema):
    # A presença das abas não garante que o Markdown de CSS já foi montado.
    # O marcador é do uploader no mesmo stylesheet, independente da cor de erro:
    # uma regressão de contraste continua chegando às asserções por valor.
    page.wait_for_function("""claro =>
      matchMedia('(prefers-color-scheme: light)').matches === claro &&
      [...document.querySelectorAll('style')].some(e => e.sheet && !e.disabled &&
        e.textContent.includes('stFileUploaderDropzoneInstructions'))""",
      arg=tema == "light", timeout=60000)


def test_dica_invisivel_e_aplicar_sem_enter(pagina_texto, tmp_path):
    from playwright.sync_api import expect
    page, tema = pagina_texto
    page.set_input_files('input[type="file"]', str(INTEGRA))
    page.get_by_text("Itens sem destino", exact=False).first.wait_for()
    # Uma caixa identificada pelo título; espera o estado persistido antes
    # de outro clique, evitando reexecuções concorrentes do abrir-todas.
    detalhe = page.locator('details').filter(
        has=page.locator('summary').filter(has_text='Estorno sem a operação correspondente')).last
    detalhe.locator('summary').click()
    expect(detalhe).to_have_attribute('open', '')
    caixa = detalhe.locator('[data-testid="stSelectbox"]')
    expect(caixa.locator('input')).to_be_visible()
    caixa.locator('input').click()
    page.get_by_role('option').filter(has_text='não pertence').first.click()
    campo = page.locator('[data-testid="stTextInput"] input:visible').first
    campo.fill("justificativa sintetica do upload")
    dica = page.locator('[data-testid="InputInstructions"]')
    expect(dica).to_have_count(1)
    visiveis = sum(dica.nth(i).is_visible() for i in range(dica.count()))
    print("dica", tema, "dica_DOM", dica.count(), "dica_visivel", visiveis)
    page.screenshot(path=str(tmp_path / f"dica_{tema}.png"))
    # Ação funciona sem Enter, inclusive no RED da dica.
    page.get_by_role('button', name='Aplicar', exact=True).filter(visible=True).first.click()
    expect(page.get_by_text('justificativa sintetica do upload', exact=False).first).to_be_visible()
    expect(page.get_by_role('button', name='Desfazer', exact=True).first).to_be_visible()
    assert visiveis == 0

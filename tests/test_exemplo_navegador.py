"""O exemplo do README pela tela, num navegador real (Playwright headless).

Opt-in: so roda com a URL do app no ar, por exemplo

    CONCILIADOR_URL=http://127.0.0.1:8501 pytest tests/test_exemplo_navegador.py

Sem a variavel, pula. Sobe exemplos/razao_exemplo_sem_par.xls pelo uploader e confere
na tela o resultado DECLARADO do exemplo (razao sem par: o motor nao fecha e mostra a
diferenca explicada pelo item sem destino). Serve tanto pro `streamlit run` quanto pro
container do compose.
"""
import os
import re
import time
from pathlib import Path

import pytest

URL = os.environ.get("CONCILIADOR_URL")
pytestmark = pytest.mark.skipif(not URL, reason="opt-in: defina CONCILIADOR_URL (ex.: http://127.0.0.1:8501)")

EXEMPLO = Path(__file__).resolve().parents[1] / "exemplos" / "razao_exemplo_sem_par.xls"

# Resultado declarado do exemplo (o mesmo do README).
DECLARADO = {
    "veredito": "Incompleto",
    "metricas": {
        "Saldo Domínio": "R$ 2.155,27",
        "Total das notas em aberto": "R$ 3.419,65",
        "Falta alocar": "R$ 1.264,38",
    },
    "itens_sem_destino": ["R$ 1.264,38"],
}

# item sem destino: "Número 123 · 18/03/2025 · Débito R$ 1.264,38 · motivo"
_ITEM_SEM_DESTINO = re.compile(r"^(?:Número|Lote) .* · (?:Débito|Crédito) (R\$ [\d.]+,\d{2})")

_LER_TELA = """() => ({
  metricas: Object.fromEntries([...document.querySelectorAll('[data-testid="stMetric"]')].map(m => [
    (m.querySelector('[data-testid="stMetricLabel"]') || {}).innerText,
    (m.querySelector('[data-testid="stMetricValue"]') || {}).innerText])),
  alertas: [...document.querySelectorAll('[data-testid="stAlert"]')].map(e => e.innerText.trim()),
  resumos: [...document.querySelectorAll('details summary')].map(e => e.innerText.replace(/^keyboard_arrow_\\w+\\s*/, '').trim()),
  excecoes: document.querySelectorAll('[data-testid="stException"]').length,
})"""


def _tela_assentada(pagina, limite=60):
    """Le a tela ate duas leituras seguidas iguais (o Streamlit desenha em partes)."""
    fim = time.monotonic() + limite
    anterior = None
    while time.monotonic() < fim:
        atual = pagina.evaluate(_LER_TELA)
        if atual["metricas"] and atual == anterior:
            return atual
        anterior = atual
        pagina.wait_for_timeout(500)
    return anterior


def test_exemplo_sem_par_mostra_na_tela_o_resultado_declarado():
    # com a URL definida, faltar o Playwright e erro de ambiente: falha, nao pula
    try:
        from playwright import sync_api as sync
    except ImportError as erro:
        pytest.fail(f"CONCILIADOR_URL definida, mas o Playwright nao esta instalado ({erro}). "
                    "Instale: pip install -r requirements-dev.txt && python -m playwright install chromium")
    with sync.sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            pagina = navegador.new_page(viewport={"width": 1280, "height": 1600}, locale="pt-BR")
            pagina.goto(URL)
            pagina.get_by_role("heading", level=1).wait_for(timeout=60000)
            pagina.set_input_files('input[type="file"]', str(EXEMPLO))
            pagina.locator('[data-testid="stMetric"]').first.wait_for(timeout=60000)
            tela = _tela_assentada(pagina)
        finally:
            navegador.close()
    itens = [m.group(1) for r in tela["resumos"] if (m := _ITEM_SEM_DESTINO.search(r))]
    assert tela["excecoes"] == 0
    assert any(DECLARADO["veredito"] in a for a in tela["alertas"]), tela["alertas"]
    assert tela["metricas"] == DECLARADO["metricas"]
    assert itens == DECLARADO["itens_sem_destino"]

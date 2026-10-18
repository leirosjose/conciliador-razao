"""Invariante de LUGAR, permanente.

Todo lancamento da razao termina em exatamente um lugar (composicao, balde,
anulado ou fora) e, na composicao, do lado certo. Roda no golden e nas
sinteticas (CI).
"""
from pathlib import Path

import pytest

from app.pipeline import processar_excel
from tests.helpers import GOLDEN, invariante_de_lugar

FIXTURES = Path(__file__).parent / "fixtures"
SINTETICAS = [FIXTURES / "sintetica_integra.xls",
              FIXTURES / "sintetica_integra.xlsx",
              FIXTURES / "sintetica_corrompida.xls"]


@pytest.mark.parametrize("caminho", [GOLDEN] + SINTETICAS,
                         ids=lambda p: p.name)
def test_invariante_de_lugar_no_golden_e_nas_sinteticas(caminho):
    for res in processar_excel(caminho).resultados:
        invariante_de_lugar(res)

from datetime import date
from pathlib import Path

from parser.excel import ExcelParser

FIXTURE = Path(__file__).parent / "fixtures" / "golden_sintetico.xls"


def test_extrai_fim_do_periodo():
    conta = ExcelParser().parse(FIXTURE)[0]
    assert conta.data_fim_periodo == date(2025, 4, 30)   # "01/01/2024 - 30/04/2025"

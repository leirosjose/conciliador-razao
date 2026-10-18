from decimal import Decimal
from pathlib import Path

from core.casamento import casar
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico

FIXTURE = Path(__file__).parent / "fixtures" / "golden_sintetico.xls"


def test_casa_ferramentas_ficticias_por_numero():
    conta = ExcelParser().parse(FIXTURE)[0]
    clf = ClassificadorHistorico()
    nfs = {nf.numero: nf for nf in casar([(l, clf.classificar(l)) for l in conta.lancamentos]).nfs}

    assert nfs["618204"].valor_compra == Decimal("4700.00")
    assert len(nfs["618204"].pagamentos) == 4
    assert nfs["274591"].valor_compra == Decimal("2400.03")
    assert len(nfs["274591"].pagamentos) == 4
    # 512309: pagamento sem compra no periodo
    assert nfs["512309"].valor_compra == Decimal("0.00")
    assert nfs["512309"].data_compra is None
    assert len(nfs["512309"].pagamentos) == 2


# --- a NF guarda as linhas de compra (evidencia pro corte por saldo zero)

def test_nf_guarda_as_linhas_de_compra_que_somam_o_valor():
    from core.casamento import casar
    from parser.historico import ClassificadorHistorico
    from tests.helpers import lanc

    c1 = lanc("Vr. compras conf. 5001 FORNECEDOR FICTICIO", numero="1",
              credito="600.00")
    c2 = lanc("Vr. compras conf. 5001 FORNECEDOR FICTICIO", numero="2",
              credito="400.00")
    clf = ClassificadorHistorico()
    (nf,) = casar([(l, clf.classificar(l)) for l in (c1, c2)]).nfs
    assert nf.compras == [c1, c2]
    assert nf.valor_compra == sum((l.credito for l in nf.compras), Decimal("0"))

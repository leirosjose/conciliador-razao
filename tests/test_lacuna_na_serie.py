"""Lacuna na serie ordinal.

NF com 2+ pagamentos casados POR NUMERO com ordinal declarado ("kª PARCELA" /
"Parcela k de M") -- as ancoras. Presentes = ordinais das ancoras + ordinais
de qualquer pagamento do razao com o MESMO valor de uma ancora que nao cite
OUTRA NF (casado ou no balde). Ausentes = 1..maior presente, menos os
presentes -> ALERTA de fato. Nao afirma que nao foi paga; nao move dinheiro.

Minimo de 2 ancoras: com 1, um caso medido da 1 falso positivo (so' a
"Parcela 3 de 3" declara ordinal; a 1a e a 2a foram pagas sem ordinal).
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()


def _compra(nf="810107", valor="804000.00", mes=6):
    return lanc(f"Vr. compras conf. {nf} FORN FICTICIO", numero=f"c{nf}",
                data=date(2025, mes, 10), credito=valor)


def _ordinal(k, mes, valor="56400.00", nf="810107", lote=None):
    sufixo = f" - NF {nf}" if nf else " - <BEM>"
    return lanc(f"Valor ref. a Pgto a FORN | {k}ª PARCELA{sufixo}",
                numero=lote or f"p{k}", data=date(2025, mes, 15), debito=valor)


def _lacunas(*lancs):
    res = casar([(l, CLF.classificar(l)) for l in lancs])
    return [a for a in res.achados if a.codigo == "lacuna_na_serie"]


def test_ordinais_1_2_sem_nf_e_4_a_8_pela_nf_acusam_a_3():
    """Um caso, sintetico."""
    (a,) = _lacunas(_compra(), _ordinal(1, 5, nf=None), _ordinal(2, 6, nf=None),
                    *[_ordinal(k, k + 4) for k in range(4, 9)])
    assert a.referencia == "810107"
    assert a.mensagem == "parcela 3 da série da NF 810107 não aparece neste razão"
    assert a.valores == {"maior_ordinal": D(8)}


def test_serie_completa_fica_calada_mesmo_com_valores_arredondados():
    """810106: 12.501,00 / 12.500,00 / 12.501,00, todas citando a NF."""
    assert _lacunas(_compra("810106", "37502.00", mes=1),
                    _ordinal(1, 2, "12501.00", "810106"),
                    _ordinal(2, 3, "12500.00", "810106"),
                    _ordinal(3, 4, "12501.00", "810106")) == []


def test_uma_ancora_so_nao_basta():
    """810119: so' a 3a declara ordinal -> nenhum alerta."""
    assert _lacunas(_compra("810119", "2799.87", mes=1),
                    lanc("Valor ref. a FORN NF 810119", numero="a",
                         data=date(2025, 2, 1), debito="923.94"),
                    lanc("Valor ref. a FORN NF 810119", numero="b",
                         data=date(2025, 3, 1), debito="923.97"),
                    _ordinal(3, 4, "951.96", "810119")) == []


def test_sem_os_ordinais_soltos_acusa_de_1_a_3():
    (a,) = _lacunas(_compra(), *[_ordinal(k, k + 4) for k in range(4, 9)])
    assert a.mensagem == ("parcelas 1, 2 e 3 da série da NF 810107 não aparecem "
                          "neste razão")


def test_ordinal_solto_de_outro_valor_nao_preenche_a_serie():
    (a,) = _lacunas(_compra(), _ordinal(1, 5, "9999.00", nf=None),
                    _ordinal(2, 6, nf=None),
                    *[_ordinal(k, k + 4) for k in range(4, 9)])
    assert "parcelas 1 e 3" in a.mensagem


def test_ordinal_que_cita_outra_nf_nao_preenche_a_serie():
    (a,) = _lacunas(_compra(), _compra("30000", "112800.00", mes=5),
                    _ordinal(1, 5, nf="30000"), _ordinal(2, 6, nf=None),
                    *[_ordinal(k, k + 4) for k in range(4, 9)])
    assert "parcelas 1 e 3" in a.mensagem


def test_lacuna_e_nao_decidido_pelo_motor():
    from app.apresentacao import NAO_DECIDIDO, classe_alerta
    (a,) = _lacunas(_compra(), *[_ordinal(k, k + 4) for k in range(4, 9)])
    assert classe_alerta(a) == NAO_DECIDIDO

"""Faixa calculada de parcelas em `_e_parcela`.

So' velocidade: o laco antigo (N = 2..NMAX) continua no core como
`_e_parcela_laco` e e' o ORACULO destes testes. A faixa so' pula os n que a
algebra prova que falham; quem decide continua sendo o mesmo teste por n.

Prova permanente: (1) a funcao concorda com o laco numa grade
deterministica + bordas; (2) o ResultadoConferencia INTEIRO (composicao,
balde, achados, ponte, corte) sai identico com o laco e com a faixa — no
golden sintetico e em sinteticas de
800 e 1.600 lancamentos.
"""
import random
from decimal import Decimal

import pytest

import core.casamento as cs
from core.conferencia import conferir
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN
from tests.test_ponte import COMPRA, _conta

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()
CENT = D("0.01")


# --- 1. a funcao ---------------------------------------------------------------

@pytest.mark.parametrize("w, compra", [
    ("0.01", "0.60"), ("0.01", "0.01"), ("0.02", "1.20"), ("0.02", "0.05"),
    ("100.00", "-200.00"), ("100.00", "0.00"),           # compra <= 0
    ("470.00", "4700.00"),                               # n*w exato (golden)
    ("240.03", "2400.03"), ("239.85", "2400.03"),        # arredondamento do golden
    ("100.00", "500.05"), ("100.00", "500.06"),          # residuo = n e n+1 centavos
    ("50.00", "100.00"), ("10.00", "600.00"),            # n = 2 e n = 60
    ("10.00", "610.00"),                                 # n = 61: fora
    ("1000.00", "999.99"), ("1000.00", "1000.01"),       # (a) na tolerancia
])
def test_faixa_concorda_com_o_laco_nas_bordas(w, compra):
    assert cs._e_parcela(D(w), D(compra)) == cs._e_parcela_laco(D(w), D(compra))


def test_faixa_concorda_com_o_laco_numa_grade_deterministica():
    rnd = random.Random(7)
    divergencias = []
    for _ in range(20000):
        w = D(rnd.randint(1, 500000)) / 100
        compra = D(rnd.randint(-100000, 5000000)) / 100
        if rnd.random() < 0.5:                 # perto de multiplo: o caso dificil
            n = rnd.randint(2, 61)
            compra = w * n + D(rnd.randint(-n - 2, n + 2)) / 100
        if cs._e_parcela(w, compra) != cs._e_parcela_laco(w, compra):
            divergencias.append((w, compra))
    assert divergencias == []


# --- 2. o resultado inteiro ----------------------------------------------------

def _com_laco(monkeypatch, conta):
    with monkeypatch.context() as m:
        m.setattr(cs, "_e_parcela", cs._e_parcela_laco)
        return conferir(conta, CLASSIFICADOR)


def _identico(monkeypatch, conta):
    antes = repr(_com_laco(monkeypatch, conta))
    depois = repr(conferir(conta, CLASSIFICADOR))
    assert depois == antes


def test_golden_identico_e_ao_centavo(monkeypatch):
    conta = ExcelParser().parse(GOLDEN)[0]
    _identico(monkeypatch, conta)
    res = conferir(conta, CLASSIFICADOR)
    abertos = {i.nf_numero: i.saldo_aberto for i in res.itens
               if i.saldo_aberto != D("0.00")}
    assert abertos == {"618204": D("2820.00"), "274591": D("1440.09")}
    assert res.totais_em_aberto.saldo_aberto == D("4260.09")


def _sintetica(n_lancamentos, semente):
    """NFs pagas em 1 a 10 parcelas com +-1 centavo de arredondamento, e 8%
    de pagamento sem par -- exercita (a), (c), desempate e balde."""
    rnd = random.Random(semente)
    linhas, nf = [], 10000
    while len(linhas) < n_lancamentos:
        nf += 1
        dia = 1 + nf % 27
        valor = D(rnd.randint(30000, 3000000)) / 100
        linhas.append((COMPRA.format(nf=nf), "0.00", str(valor), dia))
        k = rnd.choice([1, 1, 2, 3, 4, 6, 10])
        parcela = (valor / k).quantize(CENT)
        for j in range(rnd.randint(0, k)):
            p = parcela + D(rnd.choice([0, 0, 0, 1, -1])) / 100
            linhas.append(("Pago conf. FORNECEDOR FICTICIO", str(p), "0.00",
                           min(28, dia + j)))
        if rnd.random() < 0.08:
            linhas.append(("Pago conf. FORNECEDOR FICTICIO",
                           str(D(rnd.randint(1000, 90000)) / 100), "0.00", dia))
    linhas = linhas[:n_lancamentos]
    linhas.sort(key=lambda l: l[3])
    return _conta(linhas)


@pytest.mark.parametrize("n", [800, 1600])
def test_sintetica_grande_identica(monkeypatch, n):
    conta = _sintetica(n, semente=1)
    res = conferir(conta, CLASSIFICADOR)
    assert res.balde and res.achados             # o caso nao e' trivial
    _identico(monkeypatch, conta)

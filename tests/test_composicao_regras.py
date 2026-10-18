"""Sinteticos da composicao: regras que o golden nao exercita.
Conta construida na mao, sem I/O. So core.composicao (sem veredito)."""
from datetime import date
from decimal import Decimal

from core.composicao import compor
from core.modelo import NF, Lancamento, Origem


def _pag(valor, dia=1):
    return Lancamento(data=date(2025, 1, dia), numero="p", historico="pag", cta_part="x",
                      debito=Decimal(valor), credito=Decimal("0.00"), saldo_exercicio=Decimal("0.00"))


def test_retencao_abate_o_saldo_da_nf():
    # regra de negocio: saldo_NF = compra - pagamentos - retencoes
    nf = NF(numero="500", valor_compra=Decimal("1000.00"), data_compra=date(2025, 1, 1),
            pagamentos=[_pag("700.00")], retencoes=[_pag("100.00")])
    itens = compor([nf], saldo_anterior=Decimal("0.00"), data_referencia=date(2025, 1, 31))
    assert len(itens) == 1
    assert itens[0].saldo_aberto == Decimal("200.00")
    assert itens[0].total_retido == Decimal("100.00")


def test_idade_mede_contra_data_referencia_nao_today():
    nf = NF(numero="500", valor_compra=Decimal("100.00"), data_compra=date(2026, 1, 1))
    itens = compor([nf], saldo_anterior=Decimal("0.00"), data_referencia=date(2026, 4, 30))
    assert itens[0].idade_dias == (date(2026, 4, 30) - date(2026, 1, 1)).days   # 119


def test_saldo_anterior_nao_detalhado_vira_item():
    # paga 200 a uma NF sem compra; saldo anterior credor 500 -> 300 nao detalhado
    nf_previa = NF(numero="900", pagamentos=[_pag("200.00")])
    itens = compor([nf_previa], saldo_anterior=Decimal("-500.00"), data_referencia=None)
    sa = [i for i in itens if i.origem is Origem.SALDO_ANTERIOR]
    assert len(sa) == 1
    assert sa[0].saldo_aberto == Decimal("300.00")
    assert sa[0].nf_numero == "(anterior)"

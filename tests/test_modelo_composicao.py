from datetime import date
from decimal import Decimal

from core.classifica import Classificacao, Tipo
from core.modelo import NF, ComposicaoItem, Lancamento, Origem


def _pag(valor):
    return Lancamento(data=date(2025, 1, 1), numero="x", historico="pag", cta_part="x",
                      debito=Decimal(valor), credito=Decimal("0.00"), saldo_exercicio=Decimal("0.00"))


def test_nf_saldo_aberto_desconta_pagamentos_e_retencoes():
    nf = NF(numero="1", valor_compra=Decimal("1000.00"),
            pagamentos=[_pag("600.00")], retencoes=[_pag("100.00")])
    assert nf.total_quitado == Decimal("700.00")
    assert nf.saldo_aberto == Decimal("300.00")


def test_nf_sem_compra_tem_saldo_negativo_do_pago():
    nf = NF(numero="512309", pagamentos=[_pag("429.26")])  # valor_compra default 0.00
    assert nf.valor_compra == Decimal("0.00")
    assert nf.saldo_aberto == Decimal("-429.26")


def test_classificacao_e_composicao_item_constroem():
    c = Classificacao(Tipo.PAGAMENTO, nf_numero="618204", parcela=1)
    assert c.tipo is Tipo.PAGAMENTO
    item = ComposicaoItem(nf_numero="618204", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("4700.00"), total_pago=Decimal("1880.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("2820.00"))
    assert item.idade_dias is None

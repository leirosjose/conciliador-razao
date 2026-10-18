from datetime import date
from decimal import Decimal

from core.modelo import (
    ItemRevisao,
    Lancamento,
    MotivoRevisao,
    Nivel,
    NF,
    ResultadoCasamento,
)


def _pagamento(lote, valor):
    return Lancamento(
        data=date(2026, 2, 10), numero=lote, historico="PAGTO",
        cta_part="1.1.1", debito=Decimal(valor), credito=Decimal("0.00"),
        saldo_exercicio=Decimal("0.00"),
    )


def test_nivel_incompleto_existe_e_e_aditivo():
    assert Nivel.INCOMPLETO.value == "INCOMPLETO"
    # os niveis antigos ficam intactos
    assert {Nivel.OK, Nivel.ALERTA, Nivel.ERRO} <= set(Nivel)


def test_motivo_revisao_tem_dois_membros():
    assert MotivoRevisao.SEM_VINCULO.value == "SEM_VINCULO"
    assert MotivoRevisao.EMPATE.value == "EMPATE"


def test_item_revisao_guarda_pagamentos_motivo_e_candidatos():
    item = ItemRevisao(
        lancamentos=[_pagamento("F00001", "100.00")],
        motivo=MotivoRevisao.EMPATE,
        candidatos=["A", "B"],
        mensagem="revisar",
    )
    assert item.motivo is MotivoRevisao.EMPATE
    assert item.candidatos == ["A", "B"]
    assert item.lancamentos[0].numero == "F00001"


def test_resultado_casamento_separa_nfs_do_balde():
    res = ResultadoCasamento(nfs=[NF(numero="A")], balde=[])
    assert [n.numero for n in res.nfs] == ["A"]
    assert res.balde == []

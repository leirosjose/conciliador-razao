"""O item no lado oposto ao historico ganha nome pelo FATO
concreto -- "Compra lançada a débito", "Pagamento lançado a crédito" e os
equivalentes de retencao e baixa de adiantamento. Frase so' com fato (regra
de tela). Dados ficticios."""
import pytest

from app.apresentacao import (_sao_pagamentos, balde_celulas, balde_detalhes,
                              motivo_humano)
from app.materialidade import frase_contagem_motivos
from core.classifica import Tipo
from core.modelo import ItemRevisao, MotivoRevisao
from tests.helpers import lanc


def _item(tipo, **valor):
    return ItemRevisao(lancamentos=[lanc("FORN FICTICIO", numero="77", **valor)],
                       motivo=MotivoRevisao.LADO_INESPERADO, tipo_declarado=tipo,
                       identificador="x")


CASOS = [
    (Tipo.COMPRA, {"debito": "160.00"}, "Compra lançada a débito",
     "Histórico de compra com o valor no débito. Compra entra no crédito: o "
     "motor não soma este valor a nenhuma NF."),
    (Tipo.PAGAMENTO, {"credito": "160.00"}, "Pagamento lançado a crédito",
     "Histórico de pagamento com o valor no crédito. Pagamento entra no "
     "débito: o motor não abate este valor de nenhuma NF."),
    (Tipo.RETENCAO, {"credito": "160.00"}, "Retenção lançada a crédito",
     "Histórico de retenção com o valor no crédito. Retenção entra no "
     "débito: o motor não abate este valor de nenhuma NF."),
    (Tipo.BAIXA_ADIANTAMENTO, {"credito": "160.00"},
     "Baixa de adiantamento lançada a crédito",
     "Histórico de baixa de adiantamento com o valor no crédito. Baixa entra "
     "no débito: o motor não abate este valor de nenhuma NF."),
]


@pytest.mark.parametrize("tipo, valor, rotulo, frase", CASOS)
def test_rotulo_e_frase_pelo_tipo_declarado(tipo, valor, rotulo, frase):
    item = _item(tipo, **valor)
    assert motivo_humano(item) == frase
    assert balde_celulas([item])[0]["Motivo"] == rotulo
    assert rotulo in balde_detalhes([item])[0]["titulo"]
    assert frase_contagem_motivos([item]) == f"1 item: 1 {rotulo}"


def test_lado_inesperado_nao_e_chamado_de_pagamento_no_periodo_zerado():
    assert _sao_pagamentos([_item(Tipo.PAGAMENTO, credito="160.00")]) is False
    assert _sao_pagamentos([_item(Tipo.COMPRA, debito="160.00")]) is False


def test_sem_tipo_declarado_cai_na_mensagem_do_motor():
    item = ItemRevisao(lancamentos=[lanc(debito="1.00")],
                       motivo=MotivoRevisao.LADO_INESPERADO,
                       mensagem="COMPRA com valor no débito")
    assert motivo_humano(item) == "COMPRA com valor no débito"

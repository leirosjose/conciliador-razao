"""Rotulo POSSIVEL_DESCONTO: o terceiro lado do triangulo do residuo.

Residuo a MAIOR ja tinha nome (possivel_juros) e residuo a maior dentro da
tolerancia tambem (quitada com arredondamento). O residuo a MENOR pequeno numa
NF que ja recebeu quitacao ficava mudo — praxe de ERP le isso como desconto
obtido (pontualidade). E rotulo, nao casamento: o item continua onde esta, com o
mesmo valor, e o achado e ALERTA (nao derruba o verde).

O limite de 2% e TETO conservador, sujeito a calibracao pelo contador.
"""
from decimal import Decimal

import pytest

from core.modelo import ComposicaoItem, Nivel, Origem
from core.veredito import LIMITE_DESCONTO, self_check_composicao

D = Decimal


def _item(valor_compra, saldo_aberto, qtd_quitacoes,
          origem=Origem.COMPRA_PERIODO):
    """NF com o residuo desejado. total_pago e' o complemento (o rotulo olha
    valor_compra x saldo_aberto x qtd_quitacoes)."""
    return ComposicaoItem(
        nf_numero="1234", origem=origem,
        valor_compra=D(valor_compra),
        total_pago=D(valor_compra) - D(saldo_aberto),
        total_retido=D("0.00"),
        saldo_aberto=D(saldo_aberto),
        qtd_quitacoes=qtd_quitacoes, idade_dias=30)


def _achados(item, codigo):
    """Self-check com a composicao FECHANDO (alvo = total), pra isolar o rotulo."""
    achados = self_check_composicao([item], -item.saldo_aberto)
    return [a for a in achados if a.codigo == codigo]


def _desconto(item):
    return _achados(item, "possivel_desconto")


# --- o rotulo aparece --------------------------------------------------------

def test_desconto_de_dois_por_cento_exato_flaga():
    """Limite INCLUSIVO: 2,00% e o teto, e o teto conta como desconto."""
    achado = _desconto(_item("1000.00", "20.00", 1))[0]
    assert achado.nivel is Nivel.ALERTA
    assert "1234" in achado.mensagem
    assert achado.esperado == D("1000.00")        # compra
    assert achado.encontrado == D("980.00")       # quitado
    assert achado.valores["diferenca"] == D("20.00")
    assert achado.valores["percentual"] == D("2.00")


def test_desconto_diluido_em_varias_parcelas_flaga():
    """NF de 10.000,00 quitada em 5 x 1.960,00: residuo de 200,00 (2%) e MENOR
    que uma quitacao tipica -> desconto, nao parcela faltando."""
    assert len(_desconto(_item("10000.00", "200.00", 5))) == 1


def test_percentual_e_decimal_quantizado():
    """Unico ponto de divisao da regra: Decimal com quantize explicito."""
    pct = _desconto(_item("1000.00", "15.00", 1))[0].valores["percentual"]
    assert isinstance(pct, Decimal)
    assert pct == D("1.50")
    assert pct.as_tuple().exponent == -2


# --- o rotulo NAO aparece ----------------------------------------------------

def test_acima_do_limite_nao_flaga():
    """1 centavo acima do teto ja e parcial legitimo, nao desconto."""
    assert _desconto(_item("1000.00", "20.01", 1)) == []


def test_parcial_grande_nao_flaga():
    assert _desconto(_item("1000.00", "500.00", 1)) == []


def test_parcela_faltando_nao_vira_desconto():
    """Armadilha central: NF de 6.000,00 em 60 parcelas de 100,00 com 59 pagas
    deixa residuo de 1,67% — dentro do teto, mas do TAMANHO de uma quitacao.
    Falta parcela, nao houve desconto."""
    item = _item("6000.00", "100.00", 59)
    assert item.saldo_aberto <= LIMITE_DESCONTO * item.valor_compra   # passa no teto
    assert _desconto(item) == []                                      # e mesmo assim nao flaga


def test_residuo_dentro_da_tolerancia_de_centavos_nao_flaga():
    """Espelho do 'quitada com arredondamento': 0,02 em 4 quitacoes e o residuo
    que a propria tolerancia do casamento gera — chamar de desconto seria
    contradicao interna."""
    assert _desconto(_item("2400.03", "0.02", 4)) == []


def test_nf_sem_nenhuma_quitacao_nao_flaga():
    """NF intocada e simplesmente 'em aberto'. Sem quitacao nao ha o que
    descontar."""
    assert _desconto(_item("1000.00", "20.00", 0)) == []


def test_item_de_saldo_anterior_nao_flaga():
    item = ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                          valor_compra=D("0.00"), total_pago=D("980.00"),
                          total_retido=D("0.00"), saldo_aberto=D("20.00"),
                          qtd_quitacoes=1)
    assert _desconto(item) == []


def test_compra_negativa_nao_flaga():
    """Estorno (compra negativa) nao entra na conta de desconto — mesma trava
    do #26 no possivel_juros."""
    assert _desconto(_item("-1000.00", "-20.00", 1)) == []


# --- o vizinho continua funcionando -----------------------------------------

def test_juros_continua_flagando():
    """Regressao: residuo a MAIOR segue com o rotulo de sempre, e os dois
    rotulos sao mutuamente exclusivos (sinais opostos)."""
    item = _item("1000.00", "-20.00", 1)
    assert len(_achados(item, "possivel_juros")) == 1
    assert _desconto(item) == []


def test_desconto_nao_derruba_o_veredito():
    achados = self_check_composicao([_item("1000.00", "20.00", 1)], D("-20.00"))
    assert not any(a.nivel is Nivel.ERRO for a in achados)
    composicao = [a for a in achados if a.codigo == "self_check_composicao"]
    assert composicao[0].nivel is Nivel.OK


def test_golden_nao_ganha_rotulo_de_desconto():
    """Trava do caso dourado: os residuos do golden sao de 60% — parciais
    legitimos, nunca desconto."""
    from app.pipeline import processar_excel
    from tests.helpers import GOLDEN

    res = processar_excel(GOLDEN).resultados[0]
    assert [a for a in res.achados if a.codigo == "possivel_desconto"] == []


@pytest.mark.parametrize("valor,saldo,qtd", [
    ("1000.00", "20.00", 1),
    ("10000.00", "200.00", 5),
])
def test_composicao_e_saldo_do_item_nao_mudam_com_o_rotulo(valor, saldo, qtd):
    """O achado e informativo: nada entra ou sai, nada e recalculado."""
    item = _item(valor, saldo, qtd)
    antes = (item.valor_compra, item.saldo_aberto, item.total_pago)
    _desconto(item)
    assert (item.valor_compra, item.saldo_aberto, item.total_pago) == antes


def test_desconto_carrega_a_nf_em_campo_proprio():
    """A NF sai da prosa e vira dado (coluna NF/Lote da tabela de alertas)."""
    assert _desconto(_item("1000.00", "20.00", 1))[0].referencia == "1234"

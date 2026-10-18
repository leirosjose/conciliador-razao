"""POSSIVEL DUPLICIDADE DE EMISSAO.

2+ NFs da MESMA conta com o mesmo valor e a mesma data de emissao: nao e'
empate a resolver, e' duplicidade a confirmar com o cliente. ALERTA puro —
nao muda composicao, gap nem veredito.
"""
from datetime import date
from decimal import Decimal

from core.modelo import ComposicaoItem, Nivel, Origem
from core.veredito import duplicidade_de_emissao

D = Decimal


def _nf(numero, valor, dia=25, mes=9, origem=Origem.COMPRA_PERIODO, aberto=None):
    valor = D(valor)
    return ComposicaoItem(nf_numero=numero, origem=origem, valor_compra=valor,
                          total_pago=D("0.00"), total_retido=D("0.00"),
                          saldo_aberto=valor if aberto is None else D(aberto),
                          data_compra=date(2024, mes, dia))


def test_duas_nfs_mesmo_valor_e_mesma_data_alertam():
    """Um caso: 860003/860004, 468.000,00, 25/09/2024."""
    achados = duplicidade_de_emissao([_nf("860004", "468000.00"),
                                      _nf("860003", "468000.00")])
    assert len(achados) == 1
    a = achados[0]
    assert a.nivel is Nivel.ALERTA
    assert a.codigo == "possivel_duplicidade_emissao"
    assert a.referencia == "860003, 860004"          # ordenado, estavel
    assert a.encontrado == D("468000.00")
    assert a.valores["notas"] == D(2)


def test_mesmo_valor_em_datas_diferentes_nao_alerta():
    """Duas compras iguais em datas diferentes sao corriqueiras — o contador
    ja trata esse caso pela ordem cronologica."""
    assert duplicidade_de_emissao([_nf("1", "234000.00", dia=25),
                                   _nf("2", "234000.00", dia=26)]) == []


def test_mesma_data_com_valores_diferentes_nao_alerta():
    assert duplicidade_de_emissao([_nf("1", "234000.00"),
                                   _nf("2", "234000.01")]) == []


def test_nf_sozinha_nunca_alerta():
    assert duplicidade_de_emissao([_nf("1", "234000.00")]) == []


def test_saldo_anterior_fica_de_fora():
    """Sem compra na janela nao ha emissao pra comparar (trava do #26)."""
    itens = [_nf("(anterior)", "500.00", origem=Origem.SALDO_ANTERIOR),
             _nf("77", "500.00")]
    assert duplicidade_de_emissao(itens) == []


def test_compra_zero_ou_negativa_fica_de_fora():
    """Estorno nao e' emissao de nota."""
    assert duplicidade_de_emissao([_nf("1", "-100.00"), _nf("2", "-100.00")]) == []


def test_nf_sem_data_de_compra_fica_de_fora():
    sem_data = _nf("1", "500.00")
    sem_data.data_compra = None
    outra = _nf("2", "500.00")
    outra.data_compra = None
    assert duplicidade_de_emissao([sem_data, outra]) == []


def test_gemea_ja_quitada_conta_igual():
    """A duplicidade de emissao nao deixa de existir porque uma delas fechou —
    por isso a chamada leva `itens + quitadas`."""
    achados = duplicidade_de_emissao([_nf("860004", "468000.00"),
                                      _nf("860003", "468000.00", aberto="0.00")])
    assert len(achados) == 1
    assert achados[0].referencia == "860003, 860004"


def test_tres_gemeas_saem_num_achado_so():
    achados = duplicidade_de_emissao([_nf("3", "10.00"), _nf("1", "10.00"),
                                      _nf("2", "10.00")])
    assert len(achados) == 1
    assert achados[0].referencia == "1, 2, 3"
    assert achados[0].valores["notas"] == D(3)


def test_dois_grupos_distintos_dao_dois_achados():
    achados = duplicidade_de_emissao([_nf("1", "10.00"), _nf("2", "10.00"),
                                      _nf("3", "20.00", mes=10),
                                      _nf("4", "20.00", mes=10)])
    assert [a.referencia for a in achados] == ["1, 2", "3, 4"]


def test_frase_diz_mesma_data_no_razao_e_nao_de_emissao():
    """A data comparada e' a da NF no razao (lancamento da compra), que
    nao e' necessariamente a emissao. "Possivel duplicidade" fica."""
    from datetime import date
    from decimal import Decimal

    from core.modelo import ComposicaoItem, Origem
    from core.veredito import duplicidade_de_emissao
    itens = [ComposicaoItem(nf_numero=n, origem=Origem.COMPRA_PERIODO,
                            valor_compra=Decimal("100.00"),
                            total_pago=Decimal("0.00"),
                            total_retido=Decimal("0.00"),
                            saldo_aberto=Decimal("100.00"),
                            data_compra=date(2025, 1, 10)) for n in ("1001", "1002")]
    (a,) = duplicidade_de_emissao(itens)
    assert a.mensagem.startswith("possível duplicidade")
    assert a.mensagem.endswith("têm o mesmo valor e a mesma data no razão")
    assert "data de emissão" not in a.mensagem

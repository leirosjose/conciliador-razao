"""Baixa de adiantamento como QUITACAO: compensacao sem numerario
que reduz o saldo a pagar — mesma familia da retencao.
saldo_NF = compra − (pagamentos + retencoes + baixas).

Cascata IDENTICA a de pagamento: numero no historico -> Fase 1; senao valor ->
Fase 2. O saldo anterior entra como candidato SO por valor exato com
tolerancia de centavos (decisao 2 do spec): SEM regras de parcela/subconjunto
contra o agregado — parcela foi definida contra NF atomica. Baixa PARCIAL do
saldo anterior vai pro balde, para decisao de quem confere.

Na composicao a baixa aparece IDENTIFICADA (total_baixado), nao mascarada de
pagamento — evidencia visivel pra quem confere validar a interpretacao.
"""
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.composicao import compor
from core.modelo import MotivoRevisao, Origem
from tests.helpers import identidade_da_tabela, lanc

D = Decimal


def _compra(nf, valor, dia=1):
    return (lanc(f"Vr. compras conf. {nf} FORN", credito=valor, dia=dia),
            Classificacao(Tipo.COMPRA, nf_numero=nf))


def test_baixa_com_nf_quita_pela_fase1_identificada():
    baixa = lanc("BAIXA DE ADIANTAMENTO NF 333", debito="1000.00", dia=2)
    res = casar([_compra("333", "1000.00"),
                 (baixa, Classificacao(Tipo.BAIXA_ADIANTAMENTO, nf_numero="333"))])
    assert res.balde == []
    nf = res.nfs[0]
    assert nf.baixas == [baixa]
    assert nf.pagamentos == []                 # baixa NAO e mascarada de pagamento
    assert nf.saldo_aberto == D("0.00")        # quitacao: compra - baixa


def test_composicao_mostra_baixa_separada_do_pago():
    baixa = lanc("BAIXA DE ADIANTAMENTO NF 333", debito="400.00", dia=2)
    res = casar([_compra("333", "1000.00"),
                 (baixa, Classificacao(Tipo.BAIXA_ADIANTAMENTO, nf_numero="333"))])
    itens = compor(res.nfs, D("0.00"), None)
    item = itens[0]
    assert item.total_baixado == D("400.00")
    assert item.total_pago == D("0.00")
    assert item.saldo_aberto == D("600.00")


def test_baixa_sem_nf_casa_por_valor_com_nf_aberta():
    baixa = lanc("Valor ref. a BAIXA DE ADIANTAMENTO A FORN", debito="750.00", dia=2)
    res = casar([_compra("444", "750.00"),
                 (baixa, Classificacao(Tipo.BAIXA_ADIANTAMENTO))])
    assert res.balde == []
    assert res.nfs[0].baixas == [baixa]
    assert res.nfs[0].saldo_aberto == D("0.00")


def test_baixa_valor_exato_consome_saldo_anterior():
    """Um caso: baixa de 276.000,00 == |saldo anterior|, sem NF
    candidata no periodo -> consome o saldo anterior (regra do saldo anterior),
    IDENTIFICADA como baixa no item (anterior)."""
    baixa = lanc("Valor ref. a BAIXA DE ADIANTAMENTO A FORN", debito="276000.00")
    res = casar([(baixa, Classificacao(Tipo.BAIXA_ADIANTAMENTO))],
                saldo_anterior=D("-276000.00"))
    assert res.balde == []
    itens = compor(res.nfs, D("-276000.00"), None)
    anteriores = [i for i in itens if i.origem is Origem.SALDO_ANTERIOR]
    assert len(anteriores) == 1
    assert anteriores[0].total_baixado == D("276000.00")
    assert anteriores[0].total_pago == D("0.00")
    assert anteriores[0].saldo_aberto == D("0.00")     # nada 'nao detalhado'
    assert anteriores[0].valor_compra == D("276000.00")   # saldo trazido
    identidade_da_tabela(itens)                        # 276.000 − baixa 276.000 = 0


def test_baixa_parcial_do_saldo_anterior_vai_pro_balde():
    """Decisao 2: 138.000 e metade exata do saldo anterior, mas parcela foi
    definida contra NF atomica — contra o agregado NAO se aplica. Balde."""
    baixa = lanc("BAIXA DE ADIANTAMENTO A FORN", debito="138000.00")
    res = casar([(baixa, Classificacao(Tipo.BAIXA_ADIANTAMENTO))],
                saldo_anterior=D("-276000.00"))
    assert len(res.balde) == 1
    assert res.balde[0].motivo is MotivoRevisao.SEM_VINCULO


def test_empate_entre_nf_e_saldo_anterior_vai_pro_balde():
    baixa = lanc("BAIXA DE ADIANTAMENTO", debito="1000.00", dia=2)
    res = casar([_compra("555", "1000.00"),
                 (baixa, Classificacao(Tipo.BAIXA_ADIANTAMENTO))],
                saldo_anterior=D("-1000.00"))
    assert len(res.balde) == 1
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.EMPATE
    assert "555" in item.candidatos
    assert "(saldo anterior)" in item.candidatos
    assert res.nfs[0].baixas == []             # nunca chuta: ninguem recebe

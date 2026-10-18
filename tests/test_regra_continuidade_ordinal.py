"""Continuidade de serie ordinal: o item declara um ORDINAL e tem o
mesmo valor de uma serie ja casada POR NUMERO numa NF aberta, com aquele
ordinal ainda livre.

Diferente das outras regras de serie, ela NAO precisa do M de "parcela k de M":
o historico de um caso so' declara "1ª PARCELA". A ancora e a serie que ja
esta casada — e por isso ela tem que ser casada por NUMERO, deterministica:
apoiar sugestao em outra inferencia empilharia palpite sobre palpite.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.modelo import (CriterioSugestao, DestinoAlocacao, ItemRevisao,
                         MotivoRevisao, NF)
from core.regras_sugestao import continuidade_serie_ordinal
from core.sugestao import ContextoSugestao
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()

# o "ª" e' o de verdade (U+00AA): e assim que o Dominio exporta, e e' o que o
# classificador reconhece como ordinal
COM_NF = "Valor ref. a Pgto a FORN FICTICIO | INVESTIMENTOS {k}ª PARCELA - NF {nf}"
SEM_NF = "Valor ref. a Pgto a FORN FICTICIO | DESPESAS COM FINANCIAMENTOS {k}ª PARCELA - BITRENZAO"


def _serie(nf, ordinais, valor="56400.00", *, com_numero=True):
    """Anexa a NF os pagamentos da serie ja casada, um por ordinal."""
    for k in ordinais:
        historico = (COM_NF.format(k=k, nf=nf.numero) if com_numero
                     else SEM_NF.format(k=k))
        nf.pagamentos.append(lanc(historico, numero=f"L{k}",
                                  data=date(2025, 8, min(k + 10, 28)),
                                  debito=valor))
    return nf


def _nf_ancora(numero="810107", compra="804000.00", ordinais=(4, 5, 6, 7, 8),
               valor="56400.00", com_numero=True):
    nf = NF(numero=numero, valor_compra=D(compra), data_compra=date(2025, 6, 10))
    return _serie(nf, ordinais, valor, com_numero=com_numero)


def _item(k=1, valor="56400.00", lote="810114"):
    l = lanc(SEM_NF.format(k=k), numero=lote, data=date(2025, 5, 15), debito=valor)
    return ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       identificador=lote)


def _sugere(item, nfs, balde=None):
    balde = balde or [item]
    pares = [(l, CLF.classificar(l)) for i in balde for l in i.lancamentos]
    pares += [(l, CLF.classificar(l)) for nf in nfs for l in nf.pagamentos]
    return continuidade_serie_ordinal(item, ContextoSugestao.montar(balde, nfs, pares))


# --- o caso que a regra existe pra resolver -----------------------------------

def test_sugere_a_nf_que_ja_tem_a_serie_com_o_ordinal_livre():
    s = _sugere(_item(k=1), [_nf_ancora()])
    assert s is not None
    assert s.destino is DestinoAlocacao.LINHA_ABERTA
    assert s.alvo == "810107"
    assert s.criterio is CriterioSugestao.CONTINUIDADE_SERIE_ORDINAL


def test_evidencia_traz_a_serie_e_os_ordinais():
    """#34: numeros crus; a frase nasce na apresentacao. Sao os numeros que o
    contador refaz de cabeca antes de aceitar."""
    s = _sugere(_item(k=2), [_nf_ancora()])
    assert s.evidencia == {
        "parcela": D("56400.00"),
        "ordinal": D(2),
        "casadas": D(5),
        "primeiro_ordinal": D(4),
        "ultimo_ordinal": D(8),
        "saldo_aberto": D("522000.00"),
    }


# --- matriz de recusa: uma condicao por teste --------------------------------

def test_ancora_de_uma_parcela_so_nao_e_serie():
    assert _sugere(_item(), [_nf_ancora(ordinais=(4,))]) is None


def test_ancora_casada_por_valor_nao_serve():
    """Sem o numero da NF no historico, aquele pagamento nao foi ligado por
    prova — sugerir em cima dele seria palpite sobre palpite."""
    assert _sugere(_item(), [_nf_ancora(com_numero=False)]) is None


def test_ordinal_ja_casado_nao_se_sugere_de_novo():
    assert _sugere(_item(k=5), [_nf_ancora()]) is None


def test_duas_ancoras_do_mesmo_valor_calam_a_regra():
    outra = _nf_ancora(numero="21245", ordinais=(2, 3))
    assert _sugere(_item(k=1), [_nf_ancora(), outra]) is None


def test_um_centavo_de_diferenca_nao_e_a_mesma_serie():
    """Aqui o valor e' a ASSINATURA da serie, nao uma divisao que arredonda:
    sem tolerancia."""
    assert _sugere(_item(valor="56400.01"), [_nf_ancora()]) is None


def test_nao_sugere_o_que_estoura_o_saldo():
    quase_quitada = _nf_ancora(compra="282030.00")     # aberto 30,00
    assert _sugere(_item(), [quase_quitada]) is None


def test_item_de_credito_fica_fora():
    l = lanc(SEM_NF.format(k=1), numero="X", credito="56400.00")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       identificador="X")
    assert _sugere(item, [_nf_ancora()]) is None


def test_item_agregado_fica_fora():
    """Multi-NF: nao tem 'a' parcela pra comparar."""
    l1 = lanc(SEM_NF.format(k=1), numero="A", debito="56400.00")
    l2 = lanc(SEM_NF.format(k=2), numero="B", debito="56400.00")
    item = ItemRevisao(lancamentos=[l1, l2],
                       motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                       identificador="AB")
    assert _sugere(item, [_nf_ancora()]) is None


def test_item_sem_ordinal_declarado_fica_fora():
    l = lanc("Valor ref. a Pgto a FORN FICTICIO SEM ORDINAL",
             numero="Z", debito="56400.00")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       identificador="Z")
    assert _sugere(item, [_nf_ancora()]) is None


def test_nf_quitada_nao_e_ancora():
    quitada = _nf_ancora(compra="282000.00")           # aberto 0,00
    assert _sugere(_item(), [quitada]) is None


# --- as duas NAO-exigencias que a medicao mandou manter ----------------------

def test_buraco_na_sequencia_nao_impede_a_sugestao():
    """No caso a 3a parcela NAO existe na razao (casadas 4-8, no balde 1 e
    2). Exigir sequencia sem buraco mataria o unico caso que a regra pesca."""
    assert _sugere(_item(k=1), [_nf_ancora(ordinais=(4, 6, 8))]) is not None


def test_pagamento_anterior_a_compra_da_nf_nao_impede():
    """Um caso: a 1a parcela e' de 15/05 e a NF foi comprada em 10/06 —
    entrada/sinal. A regra propoe o destino e NAO opina sobre isso (a opiniao
    depende de criterio contabil)."""
    s = _sugere(_item(k=1), [_nf_ancora()])           # item 15/05, NF 10/06
    assert s is not None


def test_item_que_cita_uma_nf_nao_entra_na_regra():
    """Se o historico NOMEIA a NF, o destino nao e' inferencia: ou ele ja casou
    por numero (e nem esta no balde), ou a NF nao existe no periodo — e nesse
    caso a resposta nao e' "continue a serie de OUTRA nota". A guarda existe
    porque a regra le `clf.parcela` sem olhar o resto da classificacao."""
    l = lanc(COM_NF.format(k=1, nf="99999"), numero="Q", debito="56400.00")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       identificador="Q")
    assert _sugere(item, [_nf_ancora()]) is None

"""Trava de lado.

COMPRA com valor no debito, ou pagamento/retencao/baixa de adiantamento com
valor no credito, nunca entra numa NF: vai pro balde com motivo proprio
(LADO_INESPERADO) e o tipo que o historico declarou. Antes, a compra em debito
somava 0 ao valor da NF e a quitacao em credito entrava na NF sem quitar nada
-- o dinheiro sumia e o veredito acusava a composicao.
Dados ficticios.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.conferencia import conferir
from core.modelo import Conta, MotivoRevisao, Nivel
from core.sugestao import sugerir
from tests.helpers import invariante_de_lugar, lanc

D = Decimal


def _um_no_balde(res, l, tipo):
    (item,) = res.balde
    assert item.motivo is MotivoRevisao.LADO_INESPERADO
    assert item.lancamentos == [l]
    assert item.tipo_declarado is tipo
    assert item.candidatos == []
    return item


def test_compra_em_debito_vai_pro_balde_e_nao_cria_nf():
    l = lanc("Devolucao de compras conf. 5001", debito="160.00")
    res = casar([(l, Classificacao(Tipo.COMPRA, nf_numero="5001"))])
    _um_no_balde(res, l, Tipo.COMPRA)
    assert res.nfs == []


@pytest.mark.parametrize("tipo", [Tipo.PAGAMENTO, Tipo.RETENCAO,
                                  Tipo.BAIXA_ADIANTAMENTO])
def test_quitacao_em_credito_com_nf_vai_pro_balde(tipo):
    compra = lanc("Vr. compras conf. 5001", numero="c", credito="500.00")
    l = lanc("NF 5001", numero="q", credito="160.00")
    res = casar([(compra, Classificacao(Tipo.COMPRA, nf_numero="5001")),
                 (l, Classificacao(tipo, nf_numero="5001",
                                   nfs_citadas=("5001",)))])
    _um_no_balde(res, l, tipo)
    (nf,) = res.nfs
    assert nf.saldo_aberto == D("500.00")
    assert nf.qtd_quitacoes == 0


def test_pagamento_em_credito_sem_nf_nao_vai_pra_fase_2():
    """Fase 2 compara o DEBITO: um credito de pagamento casaria com NF de
    centavos (|V - n*0| <= n centavos). A trava vem antes."""
    compra = lanc("Vr. compras conf. 5001", numero="c", credito="0.50")
    l = lanc("Pago conf. FORN", numero="q", credito="160.00")
    res = casar([(compra, Classificacao(Tipo.COMPRA, nf_numero="5001")),
                 (l, Classificacao(Tipo.PAGAMENTO))])
    _um_no_balde(res, l, Tipo.PAGAMENTO)


def test_pagamento_multi_nf_em_credito_vai_pro_balde_da_trava():
    l = lanc("NFS 5001 E 5002", credito="160.00")
    res = casar([(l, Classificacao(Tipo.PAGAMENTO, nfs_citadas=("5001", "5002")))])
    _um_no_balde(res, l, Tipo.PAGAMENTO)


def test_lados_certos_nao_mudam_nada():
    compra = lanc("c", numero="c", credito="500.00")
    pgto = lanc("p", numero="p", debito="500.00")
    res = casar([(compra, Classificacao(Tipo.COMPRA, nf_numero="5001")),
                 (pgto, Classificacao(Tipo.PAGAMENTO, nf_numero="5001",
                                      nfs_citadas=("5001",)))])
    assert res.balde == []
    assert res.nfs[0].saldo_aberto == D("0.00")


def test_transferencia_continua_valendo_nos_dois_lados():
    cred = lanc("TRANSFERENCIA DE SALDOS", numero="t1", credito="300.00")
    deb = lanc("TRANSFERENCIA DE SALDOS", numero="t2", debito="300.00")
    res = casar([(cred, Classificacao(Tipo.TRANSFERENCIA_SALDO)),
                 (deb, Classificacao(Tipo.TRANSFERENCIA_SALDO))])
    assert all(i.motivo is not MotivoRevisao.LADO_INESPERADO for i in res.balde)


def test_lancamento_sem_valor_nao_cai_na_trava():
    l = lanc("Vr. compras conf. 5001")                 # 0 e 0: nada pra sumir
    res = casar([(l, Classificacao(Tipo.COMPRA, nf_numero="5001"))])
    assert res.balde == []


def test_sugestao_nao_propoe_destino_pro_lado_inesperado():
    compra = lanc("c", numero="c", credito="160.00")
    l = lanc("Pago conf. (Parcela 1 de 1)", numero="q", credito="160.00")
    clf = Classificacao(Tipo.PAGAMENTO, parcela=1, parcela_de=1,
                        valor_parcela=D("160.00"))
    pares = [(compra, Classificacao(Tipo.COMPRA, nf_numero="5001")), (l, clf)]
    res = casar(pares)
    sugerir(res.balde, res.nfs, pares)
    assert res.balde[0].sugestao is None


class _Clf:
    def __init__(self, tabela):
        self.tabela = tabela

    def classificar(self, l):
        return self.tabela[l.numero]


def _conta(*lancs, saldo_anterior="0.00"):
    """Conta com os totais do Dominio coerentes -- a leitura confere."""
    return Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                 data_fim_periodo=date(2025, 12, 31),
                 saldo_anterior=D(saldo_anterior), lancamentos=list(lancs),
                 total_debito_dominio=sum((l.debito for l in lancs), D("0.00")),
                 total_credito_dominio=sum((l.credito for l in lancs), D("0.00")))


def test_conferir_com_compra_em_debito_e_incompleto_e_nao_divergencia():
    """Um caso: a devolucao entrava como compra de valor 0 e o
    debito sumia -- DIVERGENCIA falsa. Agora a identidade gap == balde fecha."""
    compra = lanc("Vr. compras conf. 5001", numero="c", dia=2,
                  credito="500.00", saldo="-500.00")
    devol = lanc("Devolucao de compras conf. 5002", numero="d", dia=3,
                 debito="120.00", saldo="-380.00")
    conta = _conta(compra, devol)
    res = conferir(conta, _Clf({"c": Classificacao(Tipo.COMPRA, nf_numero="5001"),
                                "d": Classificacao(Tipo.COMPRA, nf_numero="5002")}))
    assert not any(a.nivel is Nivel.ERRO for a in res.achados)
    (inc,) = [a for a in res.achados if a.nivel is Nivel.INCOMPLETO]
    assert inc.esperado == inc.encontrado == D("120.00")
    assert [i.motivo for i in res.balde] == [MotivoRevisao.LADO_INESPERADO]
    assert res.ponte.saldo_apurado == res.ponte.saldo_dominio
    invariante_de_lugar(res)


def test_conferir_com_pagamento_em_credito_e_incompleto():
    """Um caso: compra lida como pagamento da NF, em credito."""
    l = lanc("Vr. compras conf. 197 FORN", numero="c", dia=2,
             credito="500.00", saldo="-500.00")
    conta = _conta(l)
    res = conferir(conta, _Clf({"c": Classificacao(Tipo.PAGAMENTO,
                                                   nf_numero="197",
                                                   nfs_citadas=("197",))}))
    assert not any(a.nivel is Nivel.ERRO for a in res.achados)
    assert [i.tipo_declarado for i in res.balde] == [Tipo.PAGAMENTO]
    invariante_de_lugar(res)

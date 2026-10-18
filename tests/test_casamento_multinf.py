"""Casamento um-pra-muitos: pagamento que cita 2+ NFs no historico
casa quando TODAS estao em aberto E a soma dos saldos == valor pago (TOL).
Cada NF e quitada INTEGRALMENTE via Alocacao (liquidacao one-to-many padrao de
ERP; sem rateio inventado). Qualquer condicao falhando -> balde
MULTI_NF_NAO_CONFERE dizendo O QUE falhou — nunca cai pra Fase 2 (casar por
valor contra OUTRA NF contradiria a declaracao do historico).
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.composicao import compor
from core.modelo import NF, Alocacao, MotivoRevisao, Nivel
from core.veredito import self_check_composicao
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal


def _compra(nf, valor):
    return (lanc(numero="c" + nf, data=date(2026, 1, 10), debito="0.00",
                 credito=valor, cta_part="1"),
            Classificacao(tipo=Tipo.COMPRA, nf_numero=nf))


def _pgto_multinf(lote, valor, nfs):
    return (lanc(numero=lote, data=date(2026, 2, 1), debito=valor,
                 credito="0.00", cta_part="1"),
            Classificacao(tipo=Tipo.PAGAMENTO, nf_numero=None,
                          nfs_citadas=tuple(nfs)))


def test_multinf_soma_exata_quita_todas_integralmente():
    res = casar([
        _compra("860012", "3000.00"),
        _compra("860005", "5000.00"),
        _pgto_multinf("P1", "8000.00", ["860012", "860005"]),
    ])
    assert res.balde == []
    por = {n.numero: n for n in res.nfs}
    assert por["860012"].saldo_aberto == D("0.00")
    assert por["860005"].saldo_aberto == D("0.00")
    assert por["860012"].alocacoes[0].valor == D("3000.00")     # o saldo DELA
    assert por["860005"].alocacoes[0].valor == D("5000.00")
    assert por["860012"].alocacoes[0].lancamento.numero == "P1"  # evidencia


def test_multinf_caso_compra_multilinha():
    # Um caso: 97.000,00 = NF 860013 (1193,06 + 81.426,14) + NF 860007 (14.380,80)
    l1 = lanc(numero="c1", data=date(2026, 1, 10), debito="0.00", credito="1193.06", cta_part="1")
    l2 = lanc(numero="c2", data=date(2026, 1, 12), debito="0.00", credito="81426.14", cta_part="1")
    res = casar([
        (l1, Classificacao(tipo=Tipo.COMPRA, nf_numero="860013")),
        (l2, Classificacao(tipo=Tipo.COMPRA, nf_numero="860013")),
        _compra("860007", "14380.80"),
        _pgto_multinf("P1", "97000.00", ["860013", "860007"]),
    ])
    assert res.balde == []
    assert all(n.saldo_aberto == D("0.00") for n in res.nfs)


def test_multinf_compara_contra_saldos_nao_contra_compras():
    # NF 111 ja teve retencao de 100 (Fase 1): saldo 900. 900 + 500 = 1.400.
    ret = (lanc(numero="r1", data=date(2026, 1, 20), debito="100.00", credito="0.00", cta_part="1"),
           Classificacao(tipo=Tipo.RETENCAO, nf_numero="111"))
    res = casar([
        _compra("111", "1000.00"),
        _compra("222", "500.00"),
        ret,
        _pgto_multinf("P1", "1400.00", ["111", "222"]),
    ])
    assert res.balde == []
    assert all(n.saldo_aberto == D("0.00") for n in res.nfs)


def test_multinf_nf_ausente_vai_pro_balde_com_evidencia():
    res = casar([
        _compra("860012", "3000.00"),
        _pgto_multinf("P1", "8000.00", ["860012", "99999"]),
    ])
    assert len(res.balde) == 1
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.MULTI_NF_NAO_CONFERE
    assert item.candidatos == ["860012", "99999"]
    assert "99999" in item.mensagem
    assert "em aberto" in item.mensagem
    # e NENHUMA NF recebe nada (nunca chuta parcial)
    assert {n.numero: n for n in res.nfs}["860012"].saldo_aberto == D("3000.00")


def test_multinf_soma_errada_vai_pro_balde_dizendo_a_soma():
    res = casar([
        _compra("A", "3000.00"),
        _compra("B", "5000.00"),
        _pgto_multinf("P1", "7000.00", ["A", "B"]),
    ])
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.MULTI_NF_NAO_CONFERE
    # A soma apurada e o pagamento vem em CAMPOS (a apresentacao formata
    # em BR no detalhe do motivo); a mensagem do core fica neutra
    assert item.valores["soma"] == Decimal("8000.00")
    assert item.valores["pagamento"] == Decimal("7000.00")
    assert "soma dos saldos das NFs citadas" in item.mensagem


def test_multinf_que_falha_mantem_identidade_do_incompleto():
    res = casar([
        _compra("A", "3000.00"),
        _compra("B", "5000.00"),
        _pgto_multinf("P1", "7000.00", ["A", "B"]),    # falha -> balde
    ])
    itens = compor(res.nfs, D("0.00"), None)
    # conta: creditos 8.000, debito 7.000 -> saldo final -1.000
    achados = self_check_composicao(itens, D("-1000.00"), tuple(res.balde))
    inc = [a for a in achados if a.nivel is Nivel.INCOMPLETO][0]
    assert inc.esperado == inc.encontrado == D("7000.00")


def test_multinf_segundo_pagamento_sobre_nf_quitada_falha_honesto():
    # ordem do arquivo: o primeiro quita; o segundo cita NF ja quitada -> balde
    res = casar([
        _compra("A", "300.00"),
        _compra("B", "700.00"),
        _pgto_multinf("P1", "1000.00", ["A", "B"]),
        _pgto_multinf("P2", "1000.00", ["A", "B"]),
    ])
    assert len(res.balde) == 1
    assert res.balde[0].lancamentos[0].numero == "P2"
    assert res.balde[0].motivo is MotivoRevisao.MULTI_NF_NAO_CONFERE


def test_multinf_residuo_de_tolerancia_conserva_o_dinheiro():
    # NFs 100,00 + 200,01 pagas com 300,00: soma dos saldos 300,01,
    # |soma - w| = 0,01 <= TOL -> casa. A ultima Alocacao absorve o residuo:
    # total alocado = 300,00 (conserva; nao conjura 1 centavo), e a composicao
    # FECHA (o item residual 0,01 casa com o saldo final -0,01), sem ERRO falso.
    res = casar([
        _compra("100", "100.00"),
        _compra("20001", "200.01"),
        _pgto_multinf("P1", "300.00", ["100", "20001"]),
    ])
    assert res.balde == []
    total_alocado = sum((a.valor for nf in res.nfs for a in nf.alocacoes), D("0.00"))
    assert total_alocado == D("300.00")                      # conserva (era 300.01)

    itens = compor(res.nfs, D("0.00"), None)
    # saldo final: creditos 300,01 - debito 300,00 = -0,01
    achados = self_check_composicao(itens, D("-0.01"), tuple(res.balde))
    assert not any(a.nivel is Nivel.ERRO for a in achados)   # fecha, sem vermelho


def test_compor_soma_alocacao_no_total_pago_e_na_data():
    # unidade da composicao: Alocacao parcial entra em total_pago e na data de
    # ultimo pagamento (mesmo que o casamento de hoje so aloque integral)
    nf = NF(numero="X", valor_compra=D("1000.00"), data_compra=date(2026, 1, 5))
    nf.alocacoes.append(Alocacao(
        lancamento=lanc(numero="P9", data=date(2026, 3, 1), debito="400.00", credito="0.00", cta_part="1"),
        valor=D("400.00")))
    item = compor([nf], D("0.00"), date(2026, 12, 31))[0]
    assert item.total_pago == D("400.00")
    assert item.saldo_aberto == D("600.00")
    assert item.data_ultima_quitacao == date(2026, 3, 1)


def test_lista_com_virgula_ou_barra_no_historico_quita_as_duas_nfs():
    """Ponta a ponta com o classificador real: 'PGTO NF 1111,
    2222' = 1.000,00 quita 1111 (300,00) e 2222 (700,00). Antes lia so a 1111:
    1111 em aberto -700,00 e 2222 em aberto 700,00."""
    clf = ClassificadorHistorico()
    for historico in ("PGTO NF 1111, 2222", "PGTO NF 1111/2222"):
        pgto = lanc(historico, numero="P1", data=date(2026, 2, 1),
                    debito="1000.00", credito="0.00", cta_part="1")
        res = casar([
            _compra("1111", "300.00"),
            _compra("2222", "700.00"),
            (pgto, clf.classificar(pgto)),
        ])
        assert res.balde == [], historico
        por = {n.numero: n for n in res.nfs}
        assert por["1111"].saldo_aberto == D("0.00"), historico
        assert por["2222"].saldo_aberto == D("0.00"), historico
        assert por["1111"].alocacoes[0].valor == D("300.00"), historico
        assert por["2222"].alocacoes[0].valor == D("700.00"), historico

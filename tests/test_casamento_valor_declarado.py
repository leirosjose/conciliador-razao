"""Casar pela SERIE DECLARADA x valor declarado.

Pagamento sem NF citada que a Fase 2 deixou SEM_VINCULO, com historico
"Valor de R$ X (Parcela k de M)": se M x X bate com o valor de compra de
EXATAMENTE 1 NF aberta, casa nela mesmo que o pago difira de X. A sobra nao vira
regra nova: a NF fica negativa e dispara o `possivel_juros` de sempre.

Travas: candidata unica; pago >= declarado; slot (NF, k, M) ainda livre. O
casamento sai MARCADO (achado + nota na linha), como o desempate.
Sem a variante "Y == NF" (medido: Y muda de significado conforme o template).
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.modelo import MotivoRevisao, RegraCasamento
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()

DECLARA = ("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ {v} "
           "(Parcela {k} de {m}). Despesa referente ao plano de conta 20.03.05")


def _compra(nf, valor, dia=17):
    return lanc(f"Vr. compras conf. {nf} FORN FICTICIO", numero=f"c{nf}",
                data=date(2025, 1, dia), credito=valor)


def _parcela(lote, k, m, pago, v="867,13", mes=2):
    return lanc(DECLARA.format(v=v, k=k, m=m), numero=lote,
                data=date(2025, mes, 24), debito=pago)


def _casar(*lancs):
    return casar([(l, CLF.classificar(l)) for l in lancs])


def _nf(res, numero):
    return next(n for n in res.nfs if n.numero == numero)


# --- o caso que a regra existe pra resolver (860008, sintetico) ---------------

def test_as_duas_parcelas_declaradas_casam_na_nf_cuja_compra_fecha_a_serie():
    res = _casar(_compra("860008", "1734.26"), _compra("860015", "18933.12", dia=8),
                 _parcela("860022", 1, 2, "881.83"),
                 _parcela("860023", 2, 2, "908.57", mes=4))
    assert res.balde == []
    nf = _nf(res, "860008")
    assert [l.numero for l in nf.pagamentos] == ["860022", "860023"]
    assert nf.saldo_aberto == D("-56.14")


def test_o_casamento_sai_marcado_por_lancamento():
    res = _casar(_compra("860008", "1734.26"),
                 _parcela("860022", 1, 2, "881.83"),
                 _parcela("860023", 2, 2, "908.57", mes=4))
    marcados = [a for a in res.achados
                if a.codigo == "casamento_por_valor_declarado"]
    assert [a.referencia for a in marcados] == ["860008", "860008"]
    assert marcados[0].valores == {"pagamento": D("881.83"),
                                   "declarado": D("867.13"),
                                   "diferenca": D("14.70")}
    assert [l.numero for l in marcados[1].lancamentos] == ["860023"]
    nf = _nf(res, "860008")
    assert [r.regra for r in nf.por_regra] == [RegraCasamento.VALOR_DECLARADO] * 2


def test_pago_igual_ao_declarado_continua_pela_fase_2_de_sempre():
    """2 x 867,13 = 1.734,26: a Fase 2 ja casa (parcela igual). A regra nem roda —
    nenhum achado novo."""
    res = _casar(_compra("860008", "1734.26"),
                 _parcela("860022", 1, 2, "867.13"))
    assert res.balde == []
    assert not [a for a in res.achados
                if a.codigo == "casamento_por_valor_declarado"]


# --- matriz de RECUSA ----------------------------------------------------------

def test_pago_menor_que_o_declarado_fica_no_balde():
    res = _casar(_compra("860008", "1734.26"),
                 _parcela("860022", 1, 2, "700.00"))
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO]


def test_duas_nfs_fecham_a_serie_fica_no_balde():
    res = _casar(_compra("860008", "1734.26"), _compra("860009", "1734.26", dia=18),
                 _parcela("860022", 1, 2, "881.83"))
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO]


def test_nenhuma_nf_fecha_a_serie_fica_no_balde():
    res = _casar(_compra("860008", "2600.00"),
                 _parcela("860022", 1, 2, "881.83"))
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO]


def test_slot_da_parcela_ja_ocupado_na_nf_fica_no_balde():
    """A mesma "parcela 1 de 2" casada duas vezes na mesma NF e' o alerta de
    duplicidade de serie — nao pode nascer de uma inferencia."""
    ja_casada = lanc(DECLARA.format(v="867,13", k=1, m=2) + " NF 860008",
                     numero="860021", data=date(2025, 2, 1), debito="867.13")
    res = _casar(_compra("860008", "1734.26"), ja_casada,
                 _parcela("860022", 1, 2, "881.83"))
    assert [l.numero for l in _nf(res, "860008").pagamentos] == ["860021"]
    assert [i.lancamentos[0].numero for i in res.balde] == ["860022"]


def test_nf_ja_quitada_nao_e_candidata():
    quitou = lanc("Pago conf. NF 860008", numero="860021",
                  data=date(2025, 1, 20), debito="1734.26")
    res = _casar(_compra("860008", "1734.26"), quitou,
                 _parcela("860022", 1, 2, "881.83"))
    assert [i.lancamentos[0].numero for i in res.balde] == ["860022"]


def test_total_do_documento_no_historico_nao_decide_destino():
    """Sem a variante "Y == NF": no template sem NF citada o "no valor de R$ Y"
    e' a propria parcela (6 de 6 no corpus). Y bater com uma NF nao casa."""
    l = lanc("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ 1200,00 "
             "(Parcela 1 de 2). Despesa referente ao plano de conta 20.03.05, "
             "efetuado em 22/01/2025 no valor de R$ 1.734,26",
             numero="860022", data=date(2025, 2, 24), debito="881.83")
    res = _casar(_compra("860008", "1734.26"), l)
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO]


def test_pagamento_que_cita_nf_nao_passa_pela_regra():
    """Fase 1 decide pelo numero; a regra so' ve o que a Fase 2 deixou sem vinculo."""
    l = lanc(DECLARA.format(v="867,13", k=1, m=2) + " Nº 860016",
             numero="860022", data=date(2025, 2, 24), debito="881.83")
    res = _casar(_compra("860008", "1734.26"), l)
    assert _nf(res, "860008").pagamentos == []
    assert [l.numero for l in _nf(res, "860016").pagamentos] == ["860022"]


# --- casca: frase, nota na linha, classe ---------------------------------------

def _conferido():
    from core.conferencia import conferir
    from core.modelo import Conta
    lancs = [_compra("860008", "1734.26"), _parcela("860022", 1, 2, "881.83"),
             _parcela("860023", 2, 2, "908.57", mes=4)]
    return conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE FICTICIO",
                          data_fim_periodo=date(2025, 12, 31),
                          lancamentos=lancs), CLF)


def test_frase_traz_pago_declarado_e_diferenca():
    from app.apresentacao import frase_achado
    a = next(a for a in _conferido().achados
             if a.codigo == "casamento_por_valor_declarado")
    frase = frase_achado(a)
    assert "lote 860022" in frase and "NF 860008" in frase
    assert "881,83" in frase and "867,13" in frase and "14,70" in frase


def test_linha_da_nf_leva_a_nota_do_casamento_por_regra():
    from app.apresentacao import notas_composicao_texto
    notas = notas_composicao_texto(_conferido().itens)
    assert "NF 860008: 2 quitações casadas pelo valor declarado da série" in notas


def test_casamento_pelo_valor_declarado_e_registrado_pelo_motor():
    from app.apresentacao import REGISTRADO, classe_alerta
    a = next(a for a in _conferido().achados
             if a.codigo == "casamento_por_valor_declarado")
    assert classe_alerta(a) == REGISTRADO

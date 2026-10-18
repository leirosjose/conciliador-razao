"""Desempate do EMPATE no passe 2b do casamento.

Regra contabil + praxe universal de ERP: baixa-se o titulo mais antigo primeiro.
Ordem completa: serie declarada > candidata unica ainda em aberto > data de
emissao mais antiga. Empate que sobrevive aos tres continua no BALDE — nunca se
chuta, nem se escolhe arbitrariamente.

O passe 2b roda DEPOIS de todos os casamentos inequivocos: e o que permite
enxergar quais titulos ja fecharam. Aplicar FIFO inline, na ordem do arquivo,
alocaria pagamento num titulo que ainda seria quitado depois — foi o que um
caso mostrou.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.composicao import compor
from core.modelo import CriterioDesempate, MotivoRevisao, Nivel
from tests.helpers import lanc

D = Decimal


def _compra(numero, valor, dia):
    return (lanc(f"Vr. compras conf. {numero}", numero=f"C{numero}",
                 data=date(2026, 1, dia), credito=valor),
            Classificacao(tipo=Tipo.COMPRA, nf_numero=numero))


def _pagamento(lote, valor, dia, *, parcela=None, parcela_de=None, nf=None):
    return (lanc("Valor ref. a PGTO A FORNECEDOR FICTICIO", numero=lote,
                 data=date(2026, 2, dia), debito=valor),
            Classificacao(tipo=Tipo.PAGAMENTO, nf_numero=nf, parcela=parcela,
                          parcela_de=parcela_de))


def _desempates(res):
    return [a for a in res.achados if a.codigo == "casamento_por_desempate"]


def _nf(res, numero):
    return next(nf for nf in res.nfs if nf.numero == numero)


# --- (a) a data resolve ------------------------------------------------------

def test_empate_resolve_na_nf_de_emissao_mais_antiga():
    """Duas NFs identicas em valor, emissoes distintas: o pagamento baixa a mais
    antiga (FIFO). Marcador de rastreabilidade acompanha."""
    res = casar([
        _compra("ANTIGA", "100.00", 10),
        _compra("NOVA", "100.00", 20),
        _pagamento("PAG1", "100.00", 5),
    ])
    assert _nf(res, "ANTIGA").total_pago == D("100.00")
    assert _nf(res, "NOVA").total_pago == D("0.00")
    assert res.balde == []
    achado = _desempates(res)[0]
    assert achado.nivel is Nivel.ALERTA
    assert "ANTIGA" in achado.mensagem and "PAG1" in achado.mensagem
    marca = _nf(res, "ANTIGA").desempates[0]
    assert marca.criterio is CriterioDesempate.DATA_MAIS_ANTIGA
    assert marca.candidatos == ("ANTIGA", "NOVA")


# --- (b) a serie declarada vence a data --------------------------------------

def test_serie_declarada_vence_a_data_mais_antiga():
    """'Parcela 1 de 5' de 200,00 declara uma NF de 1.000,00: o metadado do
    historico decide, mesmo que a outra candidata seja mais antiga. E casamento
    pela serie declarada — nao gera marcador de desempate."""
    res = casar([
        _compra("ANTIGA", "400.00", 10),          # 2 x 200,00
        _compra("NOVA", "1000.00", 20),           # 5 x 200,00
        _pagamento("PAG1", "200.00", 5, parcela=1, parcela_de=5),
    ])
    assert _nf(res, "NOVA").total_pago == D("200.00")
    assert _nf(res, "ANTIGA").total_pago == D("0.00")
    assert _desempates(res) == []
    assert _nf(res, "NOVA").desempates == []


# --- (c) empate total continua no balde (um caso em miniatura) ---------------------

def test_mesmo_valor_e_mesma_data_continua_no_balde():
    """Um caso: NF 40317 e 40318, ambas 234.000,00, ambas emitidas em
    25/09/2024. A data nao desempata -> revisao manual. NUNCA escolher."""
    res = casar([
        _compra("GEMEA-A", "234.00", 25),
        _compra("GEMEA-B", "234.00", 25),
        _pagamento("PAG1", "117.00", 5),
    ])
    assert _desempates(res) == []
    assert [i.motivo for i in res.balde] == [MotivoRevisao.EMPATE]
    assert sorted(res.balde[0].candidatos) == ["GEMEA-A", "GEMEA-B"]
    assert _nf(res, "GEMEA-A").total_pago == D("0.00")
    assert _nf(res, "GEMEA-B").total_pago == D("0.00")


# --- (d) candidata ja quitada sai do conjunto (um caso em miniatura) -------------

def test_candidata_quitada_no_proprio_passe_sai_do_conjunto():
    """Forma exata de um caso: a NF grande fecha ao centavo com as metades dela
    (casadas no 2a) e, quando o empate e julgado no 2b, ja nao esta em aberto —
    sobra uma candidata. Titulo quitado nao recebe baixa."""
    res = casar([
        _compra("FECHADA", "700.00", 10),         # mais antiga, 2 x 350,00
        _compra("ABERTA", "200.00", 20),          # 2 x 100,00
        _pagamento("PAG1", "350.00", 5),            # inequivoco -> FECHADA
        _pagamento("PAG2", "350.00", 6),            # inequivoco -> FECHADA (fecha)
        _pagamento("PAG3", "100.00", 7),            # empate: 7x100 = 700 / 2x100 = 200
    ])
    assert _nf(res, "FECHADA").saldo_aberto == D("0.00")
    assert _nf(res, "ABERTA").total_pago == D("100.00")
    assert res.balde == []
    assert _nf(res, "ABERTA").desempates[0].criterio is CriterioDesempate.UNICA_EM_ABERTO


# --- (e) candidata que nao comporta o pagamento sai --------------------------

def test_candidata_sem_saldo_para_o_pagamento_inteiro_sai_do_conjunto():
    """Alocar 100,00 numa NF com 40,00 em aberto estouraria o titulo pra negativo
    e fabricaria um 'possivel juros'. A elegivel e a que ainda comporta."""
    res = casar([
        _compra("PARCIAL", "100.00", 10),         # mais antiga, mas ja tem 60,00 pagos
        _compra("INTEIRA", "100.00", 20),
        _pagamento("PG", "60.00", 1, nf="PARCIAL"),   # por NUMERO, na Fase 1
        _pagamento("PAG1", "100.00", 5),
    ])
    assert _nf(res, "PARCIAL").saldo_aberto == D("40.00")     # intacta, nao negativa
    assert _nf(res, "INTEIRA").total_pago == D("100.00")
    assert _nf(res, "INTEIRA").desempates[0].criterio is CriterioDesempate.UNICA_EM_ABERTO


def test_todas_as_candidatas_quitadas_orienta_duplicidade_no_balde():
    """0 elegiveis: o balde diz o que o conferente precisa checar primeiro."""
    res = casar([
        _compra("FECHADA-A", "200.00", 10),
        _compra("FECHADA-B", "200.00", 20),
        _pagamento("PAG1", "200.00", 1, nf="FECHADA-A"),
        _pagamento("PAG2", "200.00", 2, nf="FECHADA-B"),
        _pagamento("PAG3", "100.00", 7),
    ])
    # as duas fecharam na Fase 1 -> nem entram em `abertas`; o pagamento fica sem
    # candidata alguma (SEM_VINCULO). O caso de 0 ELEGIVEIS exige que fechem no 2a:
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO]

    res2 = casar([
        _compra("FECHA-NO-2A", "200.00", 10),
        _compra("TAMBEM-FECHA", "400.00", 20),
        _pagamento("Q1", "200.00", 1),            # inequivoco -> FECHA-NO-2A
        _pagamento("Q2", "400.00", 2),            # inequivoco -> TAMBEM-FECHA
        _pagamento("Q3", "100.00", 7),            # 2x100=200 e 4x100=400: empate
    ])
    item = res2.balde[0]
    assert item.motivo is MotivoRevisao.EMPATE
    assert "já quitadas" in item.mensagem
    assert "duplicidade" in item.mensagem


# --- (f) empate que inclui o saldo anterior continua no balde ---------------

def test_empate_com_saldo_anterior_nao_e_desempatado():
    """O agregado '(saldo anterior)' nao tem data de emissao — nao se rankeia o
    que nao tem data. Conservador: continua revisao manual."""
    baixa = (lanc("Valor ref. a BAIXA DE ADIANTAMENTO A FORN", numero="B1",
                  data=date(2026, 2, 5), debito=D("100.00")),
             Classificacao(tipo=Tipo.BAIXA_ADIANTAMENTO))
    res = casar([_compra("UNICA", "100.00", 10), baixa],
                saldo_anterior=D("-100.00"))
    assert [i.motivo for i in res.balde] == [MotivoRevisao.EMPATE]
    assert "(saldo anterior)" in res.balde[0].candidatos
    assert _desempates(res) == []


# --- (g) o marcador chega na composicao -------------------------------------

def test_marcador_de_desempate_chega_no_item_da_composicao():
    res = casar([
        _compra("ANTIGA", "300.00", 10),
        _compra("NOVA", "300.00", 20),
        _pagamento("PAG1", "100.00", 5),
    ])
    itens = compor(res.nfs, D("0.00"), date(2026, 3, 31))
    item = next(i for i in itens if i.nf_numero == "ANTIGA")
    assert item.desempates == (CriterioDesempate.DATA_MAIS_ANTIGA,)
    assert next(i for i in itens if i.nf_numero == "NOVA").desempates == ()


# --- (h) condicao 1 da decisao de produto: igualdade estrita pre/pos ----------------

def test_empate_cedo_e_serie_declarada_depois_produzem_o_resultado_de_sempre():
    """TRAVA DE IGUALDADE (condicao 1 da decisao de produto): fixture com empate INSOLUVEL cedo
    no arquivo e casamento por serie declarada depois. Os valores esperados foram
    gravados rodando esta fixture contra o casamento ANTES do desempate — o teste passava
    antes da mudanca e tem que continuar passando depois.

    O que ele protege: a fila do 2a nao pode alterar o que o 2a decide, nem a
    ordem em que as ocorrencias de serie sao registradas (o 2a reserva o slot na
    posicao cronologica; o 2b promove no lugar)."""
    pares = [
        _compra("GEMEA-A", "500.00", 10),
        _compra("GEMEA-B", "500.00", 10),        # gemea: empate insoluvel
        _compra("MEIA", "320.00", 12),
        _compra("CHEIA", "800.00", 15),
        _pagamento("EMPATE-CEDO", "100.00", 5, parcela=1, parcela_de=5),
        _pagamento("SERIE-DEPOIS", "160.00", 20, parcela=2, parcela_de=5),
    ]
    res = casar(pares)

    # o empate cedo continua no balde, com os dois candidatos gemeos
    assert [i.motivo for i in res.balde] == [MotivoRevisao.EMPATE]
    assert res.balde[0].lancamentos[0].numero == "EMPATE-CEDO"
    # CHEIA tambem e candidata do pagamento de 100,00 (800 = 8 x 100); no 2b as
    # tres sao elegiveis e as duas gemeas empatam na data minima -> segue balde
    assert sorted(res.balde[0].candidatos) == ["CHEIA", "GEMEA-A", "GEMEA-B"]
    # a serie declarada depois casa na NF que a aritmetica aponta (5 x 160 = 800)
    assert _nf(res, "CHEIA").total_pago == D("160.00")
    assert _nf(res, "MEIA").total_pago == D("0.00")
    # nenhuma NF gemea recebeu nada, e nenhum desempate foi aplicado
    assert _nf(res, "GEMEA-A").total_pago == D("0.00")
    assert _nf(res, "GEMEA-B").total_pago == D("0.00")
    assert _desempates(res) == []


def test_duas_ocorrencias_da_mesma_serie_no_balde_alertam_na_ordem_do_arquivo():
    """A mesma (parcela k de M, valor) duas vezes, ambas em EMPATE insoluvel:
    o alerta de serie lista os lotes na ORDEM DO ARQUIVO. E o observavel do slot
    reservado no 2a (forma de um caso, lotes 319455 e 322117)."""
    res = casar([
        _compra("GEMEA-A", "500.00", 10),
        _compra("GEMEA-B", "500.00", 10),
        _pagamento("PRIMEIRO", "100.00", 5, parcela=5, parcela_de=5),
        _pagamento("SEGUNDO", "100.00", 25, parcela=5, parcela_de=5),
    ])
    dup = [a for a in res.achados if a.codigo == "possivel_duplicidade"]
    assert len(dup) == 1
    assert dup[0].mensagem.index("PRIMEIRO") < dup[0].mensagem.index("SEGUNDO")
    assert len(res.balde) == 2


def test_desempate_carrega_a_nf_escolhida_em_campo_proprio():
    """A referencia e' a NF que RECEBEU a quitacao decidida por regra --
    o lote continua no detalhe."""
    res = casar([
        _compra("ANTIGA", "100.00", 10),
        _compra("NOVA", "100.00", 20),
        _pagamento("PAG1", "100.00", 5),
    ])
    assert _desempates(res)[0].referencia == "ANTIGA"

from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.composicao import compor
from core.modelo import (
    ComposicaoItem,
    ItemRevisao,
    MotivoRevisao,
    Nivel,
    Origem,
)
from core.veredito import self_check_composicao
from tests.helpers import lanc

D = Decimal


def _compra(numero, valor):
    return (lanc(numero=numero, data=date(2026, 1, 10), debito=D("0.00"),
                 credito=D(valor), cta_part="1.1.1"),
            Classificacao(tipo=Tipo.COMPRA, nf_numero=numero))


def _pagamento_sem_numero(lote, valor):
    return (lanc(numero=lote, data=date(2026, 2, 10), debito=D(valor),
                 credito=D("0.00"), cta_part="1.1.1"),
            Classificacao(tipo=Tipo.PAGAMENTO, nf_numero=None))


def _duas_nfs_mesmo_valor_um_pagamento():
    return [
        _compra("A", "100.00"),
        _compra("B", "100.00"),
        _pagamento_sem_numero("P1", "100.00"),
    ]


def test_nf_em_4_parcelas_iguais_casa_por_valor():
    pares = [
        _compra("X", "400.00"),
        _pagamento_sem_numero("P1", "100.00"),
        _pagamento_sem_numero("P2", "100.00"),
        _pagamento_sem_numero("P3", "100.00"),
        _pagamento_sem_numero("P4", "100.00"),
    ]
    res = casar(pares)
    nf = {n.numero: n for n in res.nfs}["X"]
    assert res.balde == []
    assert len(nf.pagamentos) == 4
    assert nf.saldo_aberto == D("0.00")


def test_parcelas_iguais_com_sobra():
    pares = [
        _compra("Y", "500.00"),
        _pagamento_sem_numero("P1", "100.00"),
        _pagamento_sem_numero("P2", "100.00"),
        _pagamento_sem_numero("P3", "100.00"),
    ]
    res = casar(pares)
    nf = {n.numero: n for n in res.nfs}["Y"]
    assert res.balde == []
    assert len(nf.pagamentos) == 3
    assert nf.saldo_aberto == D("200.00")


def test_pagamento_sem_match_vai_pro_balde_sem_vinculo():
    pares = [_pagamento_sem_numero("F00001", "333.33")]
    res = casar(pares)
    assert res.nfs == []
    assert len(res.balde) == 1
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.SEM_VINCULO
    assert item.candidatos == []
    assert item.lancamentos[0].numero == "F00001"


def test_empate_vai_pro_balde_e_nenhuma_nf_recebe():
    res = casar(_duas_nfs_mesmo_valor_um_pagamento())
    por = {n.numero: n for n in res.nfs}
    assert len(res.balde) == 1
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.EMPATE
    assert sorted(item.candidatos) == ["A", "B"]
    assert len(por["A"].pagamentos) == 0
    assert len(por["B"].pagamentos) == 0


def test_pipeline_empate_veredito_incompleto():
    # 2 NFs de 100 + 1 pagamento de 100 -> empate -> balde; nenhuma NF recebe.
    # Conta: comprou 200 (2x credito 100), pagou 100 (1x debito 100) -> saldo final -100.
    res = casar(_duas_nfs_mesmo_valor_um_pagamento())
    itens = compor(res.nfs, saldo_anterior=D("0.00"), data_referencia=None)
    achados = self_check_composicao(itens, saldo_final=D("-100.00"), balde=res.balde)

    assert all(a.nivel is not Nivel.ERRO for a in achados)      # NAO da falso ERRO
    incompletos = [a for a in achados if a.nivel is Nivel.INCOMPLETO]
    assert len(incompletos) == 1
    inc = incompletos[0]
    assert inc.encontrado == D("100.00")                        # gap
    assert inc.esperado == D("100.00")                          # soma do balde
    assert inc.esperado == inc.encontrado                       # gap explicado pelo balde


def test_veredito_com_balde_nao_da_erro_e_marca_incompleto():
    # unidade: 1 item aberto de 100, saldo final -40, balde com pagamento de 60.
    # gap = 100 - 40 = 60 == soma do balde.
    item = ComposicaoItem(
        nf_numero="A", origem=Origem.COMPRA_PERIODO, valor_compra=D("100.00"),
        total_pago=D("0.00"), total_retido=D("0.00"), saldo_aberto=D("100.00"),
    )
    pagto = _pagamento_sem_numero("F00009", "60.00")[0]
    balde = [ItemRevisao(lancamentos=[pagto], motivo=MotivoRevisao.SEM_VINCULO)]
    achados = self_check_composicao([item], saldo_final=D("-40.00"), balde=balde)

    assert not any(a.nivel is Nivel.ERRO for a in achados)
    inc = [a for a in achados if a.nivel is Nivel.INCOMPLETO]
    assert len(inc) == 1
    assert inc[0].esperado == D("60.00")
    assert inc[0].encontrado == D("60.00")


def test_veredito_sem_balde_mantem_comportamento():
    # balde vazio (default) -> comportamento antigo: fecha -> OK, sem INCOMPLETO.
    item = ComposicaoItem(
        nf_numero="A", origem=Origem.COMPRA_PERIODO, valor_compra=D("100.00"),
        total_pago=D("0.00"), total_retido=D("0.00"), saldo_aberto=D("100.00"),
    )
    achados = self_check_composicao([item], saldo_final=D("-100.00"))
    status = [a for a in achados if a.codigo == "self_check_composicao"][0]
    assert status.nivel is Nivel.OK
    assert not any(a.nivel is Nivel.INCOMPLETO for a in achados)


# --- desempate por serie declarada: "Parcela k de M" -------------------------

def _pagamento_serie(lote, valor, k, m):
    return (lanc(numero=lote, data=date(2026, 2, 10), debito=D(valor),
                 credito=D("0.00"), cta_part="1.1.1"),
            Classificacao(tipo=Tipo.PAGAMENTO, nf_numero=None,
                          parcela=k, parcela_de=m))


def test_desempate_por_serie_atribui_a_unica_nf_que_fecha():
    """Um caso: 26.000 'de 5' empata entre 130.000 (5x26.000) e
    182.000 (7x26.000). A serie DECLARADA fecha so com a de 130.000 ->
    metadado + aritmetica decidem, nao heuristica."""
    res = casar([
        _compra("40317", "130000.00"),
        _compra("40318", "182000.00"),
        _pagamento_serie("P1", "26000.00", 2, 5),
    ])
    assert res.balde == []
    por = {n.numero: n for n in res.nfs}
    assert len(por["40317"].pagamentos) == 1
    assert por["40318"].pagamentos == []


def test_serie_que_fecha_com_duas_candidatas_continua_empate():
    # 100 'de 2': 2x100 = 200 fecha com A E B -> ambiguo continua -> balde
    res = casar([
        _compra("A", "200.00"),
        _compra("B", "200.00"),
        _pagamento_serie("P1", "100.00", 1, 2),
    ])
    assert len(res.balde) == 1
    assert res.balde[0].motivo is MotivoRevisao.EMPATE


def test_serie_que_nao_fecha_com_nenhuma_continua_empate():
    # 100 'de 3': 300 nao e o valor de nenhuma candidata -> empate continua
    res = casar([
        _compra("A", "200.00"),
        _compra("B", "200.00"),
        _pagamento_serie("P1", "100.00", 1, 3),
    ])
    assert len(res.balde) == 1
    assert res.balde[0].motivo is MotivoRevisao.EMPATE


# --- achado de possivel duplicidade: parcela k de M repetida -----------------

def test_parcela_da_serie_paga_duas_vezes_na_mesma_nf_sinaliza_duplicidade():
    """Um caso: duas 'Parcela 5 de 5' de 26.000. O dinheiro SAIU — a
    composicao nao muda; o achado ALERTA e pra investigacao (mesma filosofia
    do possivel juros)."""
    res = casar([
        _compra("40317", "130000.00"),
        _pagamento_serie("P1", "26000.00", 4, 5),
        _pagamento_serie("P2", "26000.00", 5, 5),
        _pagamento_serie("P3", "26000.00", 5, 5),
    ])
    assert res.balde == []                      # todas casam (candidata unica)
    dups = [a for a in res.achados if a.codigo == "possivel_duplicidade"]
    assert len(dups) == 1
    assert dups[0].nivel is Nivel.ALERTA
    assert "parcela 5 de 5" in dups[0].mensagem
    assert "40317" in dups[0].mensagem
    assert "2 vezes" in dups[0].mensagem
    assert "P2" in dups[0].mensagem and "P3" in dups[0].mensagem   # evidencia
    # composicao INALTERADA pelo achado: quitado = 3 x 26.000
    assert res.nfs[0].total_quitado == D("78000.00")


def test_parcelas_distintas_da_serie_nao_sinalizam():
    res = casar([
        _compra("X", "52000.00"),
        _pagamento_serie("P1", "26000.00", 1, 2),
        _pagamento_serie("P2", "26000.00", 2, 2),
    ])
    assert [a for a in res.achados if a.codigo == "possivel_duplicidade"] == []


def test_duplicidade_tambem_detectada_no_casamento_por_numero():
    # Fase 1: o numero liga direto; a serie repetida sinaliza do mesmo jeito
    l1 = lanc(numero="P1", data=date(2026, 2, 1), debito=D("100.00"), credito=D("0.00"), cta_part="1.1.1")
    l2 = lanc(numero="P2", data=date(2026, 2, 8), debito=D("100.00"), credito=D("0.00"), cta_part="1.1.1")
    res = casar([
        _compra("77", "400.00"),
        (l1, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="77",
                           parcela=3, parcela_de=4)),
        (l2, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="77",
                           parcela=3, parcela_de=4)),
    ])
    dups = [a for a in res.achados if a.codigo == "possivel_duplicidade"]
    assert len(dups) == 1
    assert "parcela 3 de 4" in dups[0].mensagem


# --- duplicidade VISIVEL no balde (decisao de produto) ------------------------
# Furo visto num caso: o detector so via series de pagamentos CASADOS; tudo que
# caia no balde era invisivel. Agora 2+ ocorrencias de (parcela k, de M,
# valor) com PELO MENOS UMA em revisao -> ALERTA apontando os lotes. Todas
# casadas em NFs DISTINTAS = N series legitimas (compras identicas), SEM
# alerta. NADA sai do balde; casamento intocado.

def test_duplicidade_com_as_duas_ocorrencias_no_balde():
    """Um caso: duas 'Parcela 5 de 5' de 26.000,00, ambas EMPATE entre
    duas NFs identicas — o balde fica como esta, mas o alerta agora sai."""
    res = casar([
        _compra("40317", "130000.00"),
        _compra("40318", "130000.00"),
        _pagamento_serie("319455", "26000.00", 5, 5),
        _pagamento_serie("322117", "26000.00", 5, 5),
    ])
    assert len(res.balde) == 2                       # os empates FICAM no balde
    assert all(i.motivo is MotivoRevisao.EMPATE for i in res.balde)
    dups = [a for a in res.achados if a.codigo == "possivel_duplicidade"]
    assert len(dups) == 1
    assert dups[0].nivel is Nivel.ALERTA
    assert "parcela 5 de 5" in dups[0].mensagem
    assert "2 vezes" in dups[0].mensagem
    assert "319455" in dups[0].mensagem and "322117" in dups[0].mensagem


def test_duplicidade_entre_pagamento_casado_por_numero_e_item_do_balde():
    l1 = lanc(numero="P1", data=date(2026, 2, 1), debito=D("26000.00"),
              credito=D("0.00"), cta_part="1.1.1")
    res = casar([
        _compra("40317", "130000.00"),
        _compra("40318", "130000.00"),
        (l1, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="40317",
                           parcela=5, parcela_de=5)),      # casa por NUMERO
        _pagamento_serie("322117", "26000.00", 5, 5),      # sem numero -> EMPATE
    ])
    assert len(res.balde) == 1
    dups = [a for a in res.achados if a.codigo == "possivel_duplicidade"]
    assert len(dups) == 1
    assert "P1" in dups[0].mensagem and "322117" in dups[0].mensagem


def test_series_identicas_casadas_em_nfs_distintas_nao_alertam():
    """Duas compras identicas, cada uma paga 1x a sua 'parcela 5 de 5' POR
    NUMERO: N series legitimas, cada NF paga 1 vez — conservador, sem alerta
    (decisao de produto; e o proprio padrao do caso de compras iguais)."""
    l1 = lanc(numero="P1", data=date(2026, 2, 1), debito=D("26000.00"),
              credito=D("0.00"), cta_part="1.1.1")
    l2 = lanc(numero="P2", data=date(2026, 3, 1), debito=D("26000.00"),
              credito=D("0.00"), cta_part="1.1.1")
    res = casar([
        _compra("40317", "130000.00"),
        _compra("40318", "130000.00"),
        (l1, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="40317",
                           parcela=5, parcela_de=5)),
        (l2, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="40318",
                           parcela=5, parcela_de=5)),
    ])
    assert res.balde == []
    assert [a for a in res.achados if a.codigo == "possivel_duplicidade"] == []


def test_parcela_sem_serie_declarada_nao_rastreia():
    # sem o M nao ha serie declarada -> sem base pra afirmar duplicidade
    l1 = lanc(numero="P1", data=date(2026, 2, 1), debito=D("100.00"), credito=D("0.00"), cta_part="1.1.1")
    l2 = lanc(numero="P2", data=date(2026, 2, 8), debito=D("100.00"), credito=D("0.00"), cta_part="1.1.1")
    res = casar([
        _compra("77", "400.00"),
        (l1, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="77", parcela=3)),
        (l2, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="77", parcela=3)),
    ])
    assert res.achados == []


# --- compras da mesma NF em multiplas linhas ---------------------------------

def test_compras_da_mesma_nf_em_duas_linhas_somam():
    """Um caso: NF 46873 = 386,71 + 45.234,13 em duas linhas de
    compra. A soma e provada ao centavo pelo proprio arquivo (pagamento de
    48.500,00 = 386,71 + 45.234,13 + 2.879,16). Sobrescrever perderia 386,71."""
    l1 = lanc(numero="1", data=date(2026, 1, 10), debito=D("0.00"), credito=D("386.71"), cta_part="1.1.1")
    l2 = lanc(numero="2", data=date(2026, 1, 12), debito=D("0.00"), credito=D("45234.13"), cta_part="1.1.1")
    res = casar([
        (l1, Classificacao(tipo=Tipo.COMPRA, nf_numero="46873")),
        (l2, Classificacao(tipo=Tipo.COMPRA, nf_numero="46873")),
    ])
    nf = res.nfs[0]
    assert nf.valor_compra == D("45620.84")          # soma, nao sobrescrita
    assert nf.data_compra == date(2026, 1, 10)       # data da PRIMEIRA linha


def test_duplicidade_carrega_os_lotes_em_campo_proprio():
    """Alerta de LANCAMENTO carrega os lotes (a coluna 'Tipo' ao lado diz
    que sao lotes, nao NFs)."""
    l1 = lanc(numero="P1", data=date(2026, 2, 1), debito=D("100.00"),
              credito=D("0.00"), cta_part="1.1.1")
    l2 = lanc(numero="P2", data=date(2026, 2, 8), debito=D("100.00"),
              credito=D("0.00"), cta_part="1.1.1")
    res = casar([
        _compra("77", "400.00"),
        (l1, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="77",
                           parcela=3, parcela_de=4)),
        (l2, Classificacao(tipo=Tipo.PAGAMENTO, nf_numero="77",
                           parcela=3, parcela_de=4)),
    ])
    (dup,) = [a for a in res.achados if a.codigo == "possivel_duplicidade"]
    assert dup.referencia == "P1, P2"

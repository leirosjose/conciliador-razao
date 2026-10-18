"""Corte por saldo zero: ONDE a razao pode ser cortada.

Se o saldo-exercicio impresso vale 0,00 na linha k, o saldo final e' a soma
do que vem depois -- partida dobrada. O corte usa o ULTIMO zero aproveitavel:
o zero e' recusado quando algo o CRUZA (NF, par de estorno ou item do balde
com lancamento dos dois lados) ou quando a conta do periodo zerado nao fecha.
Recusado o ultimo, recua pro anterior; sem nenhum, nao ha corte (o de hoje).
Cada caso de cruzamento tem a sua sintetica aqui.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.corte import localizar_corte
from core.modelo import (NF, ItemRevisao, Lancamento, MotivoRevisao, Nivel,
                         ResultadoCasamento)
from parser.historico import ClassificadorHistorico
from tests.test_ponte import COMPRA, ESTRANHO, PAGAMENTO_NF, _conta

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()
PAGO_CONF = "Pago conf. FORNECEDOR FICTICIO"
BAIXA = "BAIXA DE ADIANTAMENTO A FORN FORNECEDOR FICTICIO"
ESTORNO_BAIXA = "ESTORNO DE BAIXA DE ADIANTAMENTO FORNECEDOR FICTICIO"


def _corte(linhas, saldo_anterior="0.00", leitura_ok=True):
    conta = _conta(linhas, saldo_anterior=saldo_anterior)
    pares = [(l, CLASSIFICADOR.classificar(l)) for l in conta.lancamentos]
    resultado = casar(pares, conta.saldo_anterior)
    return localizar_corte(conta.lancamentos, conta.saldo_anterior,
                           resultado, leitura_ok)


def _recuado(achados):
    (a,) = achados
    assert a.codigo == "corte_recuado"
    assert a.nivel is Nivel.ALERTA
    return a


# --- sem cruzamento -----------------------------------------------------------

def test_razao_que_nunca_zera_nao_tem_corte():
    corte, achados = _corte([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2)])
    assert corte is None and achados == []


def test_corte_no_zero_sem_cruzamento():
    corte, achados = _corte([
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
        (PAGAMENTO_NF.format(nf="5001"), "1000.00", "0.00", 3),   # zera
        (COMPRA.format(nf="5002"), "0.00", "500.00", 5)])
    assert corte.indice == 1
    assert corte.lancamento.numero == "L2"
    assert achados == []


def test_corte_usa_o_ultimo_zero_e_lembra_os_anteriores():
    corte, achados = _corte([
        (COMPRA.format(nf="5001"), "0.00", "200.00", 2),
        (PAGAMENTO_NF.format(nf="5001"), "200.00", "0.00", 3),    # zera
        (COMPRA.format(nf="5002"), "0.00", "300.00", 4),
        (PAGAMENTO_NF.format(nf="5002"), "300.00", "0.00", 5),    # zera
        (COMPRA.format(nf="5003"), "0.00", "50.00", 6)])
    assert corte.indice == 3
    assert [l.numero for l in corte.zeros] == ["L2", "L4"]
    assert achados == []


def test_saldo_anterior_e_consumido_antes_do_zero_e_nao_cruza():
    corte, _ = _corte([
        (PAGAMENTO_NF.format(nf="4001"), "700.00", "0.00", 2),    # anterior zera
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 5)],
        saldo_anterior="-700.00")
    assert corte.indice == 0


# --- travas -------------------------------------------------------------------

def test_leitura_nao_conferida_nao_corta():
    """O zero impresso so' vale se o parsing fechou (inclui o saldo corrente
    linha a linha)."""
    corte, achados = _corte([
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
        (PAGAMENTO_NF.format(nf="5001"), "1000.00", "0.00", 3),
        (COMPRA.format(nf="5002"), "0.00", "500.00", 5)], leitura_ok=False)
    assert corte is None and achados == []


def test_nf_com_compra_antes_e_pagamento_depois_cruza():
    corte, achados = _corte([
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
        (ESTRANHO, "1000.00", "0.00", 3),                         # zera
        (PAGAMENTO_NF.format(nf="5001"), "1000.00", "0.00", 4),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 5)])
    assert corte is None
    assert "5001" in _recuado(achados).referencia


def test_pagamento_antes_da_emissao_cruza():
    corte, achados = _corte([
        (PAGAMENTO_NF.format(nf="5001"), "1000.00", "0.00", 2),
        (ESTRANHO, "0.00", "1000.00", 3),                         # zera
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 4),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 5)])
    assert corte is None
    assert "5001" in _recuado(achados).referencia


def test_quitacao_do_saldo_anterior_depois_do_zero_cruza():
    """NF sem compra no periodo consome o saldo anterior: ela vive "antes de
    tudo", e o pagamento dela depois do zero atravessa o corte."""
    corte, achados = _corte([
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
        (ESTRANHO, "1000.00", "0.00", 3),
        (ESTRANHO, "700.00", "0.00", 4),                          # zera
        (PAGAMENTO_NF.format(nf="4001"), "700.00", "0.00", 5),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 6)],
        saldo_anterior="-700.00")
    assert corte is None
    assert "4001" in _recuado(achados).referencia


def test_par_de_estorno_dividido_pelo_zero_cruza():
    corte, achados = _corte([
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
        (BAIXA, "300.00", "0.00", 3),
        (PAGO_CONF, "700.00", "0.00", 4),                         # zera
        (ESTORNO_BAIXA, "0.00", "300.00", 5),
        (COMPRA.format(nf="5002"), "0.00", "500.00", 6)])
    assert corte is None
    assert _recuado(achados).referencia == "L2, L4"            # os dois lotes


def _lanc(numero, debito, credito, saldo):
    return Lancamento(date(2026, 1, 2), numero, "x", "1.1.1", D(debito),
                      D(credito), D(saldo))


def test_item_do_balde_dividido_pelo_zero_cruza():
    """O motor de hoje so' poe UM lancamento por item; o corte nao pode
    depender disso."""
    l0, l1, l2 = (_lanc("L1", "100.00", "0.00", "100.00"),
                  _lanc("L2", "0.00", "100.00", "0.00"),           # zera
                  _lanc("L3", "50.00", "0.00", "50.00"))
    resultado = ResultadoCasamento(balde=[
        ItemRevisao([l0, l2], MotivoRevisao.SEM_VINCULO),
        ItemRevisao([l1], MotivoRevisao.NAO_CLASSIFICADO)])
    corte, achados = localizar_corte([l0, l1, l2], D("0.00"), resultado, True)
    assert corte is None
    assert "L1" in _recuado(achados).referencia


def test_conta_do_periodo_zerado_que_nao_fecha_recusa_o_zero():
    """Trava interna: Σ aberto das NFs do periodo zerado tem que ser o Σ(D−C)
    do balde de la. Aqui o debito que zera nao foi parar em lugar nenhum."""
    l0 = _lanc("L1", "0.00", "1000.00", "-1000.00")
    l1 = _lanc("L2", "1000.00", "0.00", "0.00")                    # zera
    l2 = _lanc("L3", "0.00", "50.00", "-50.00")
    nf = NF(numero="5001", valor_compra=D("1000.00"),
            data_compra=date(2026, 1, 2), compras=[l0])
    corte, achados = localizar_corte([l0, l1, l2], D("0.00"),
                                     ResultadoCasamento(nfs=[nf]), True)
    assert corte is None
    assert _recuado(achados).referencia is None


# --- recuo --------------------------------------------------------------------

def test_recua_pro_zero_anterior_sem_cruzamento():
    corte, achados = _corte([
        (COMPRA.format(nf="5000"), "0.00", "200.00", 2),
        (PAGAMENTO_NF.format(nf="5000"), "200.00", "0.00", 3),    # zera: serve
        (COMPRA.format(nf="5001"), "0.00", "1000.00", 4),
        (ESTRANHO, "1000.00", "0.00", 5),                         # zera: cruzado
        (PAGAMENTO_NF.format(nf="5001"), "1000.00", "0.00", 6),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 7)])
    assert corte.indice == 1
    assert [l.numero for l in corte.descartados] == ["L4"]
    recuado = _recuado(achados)
    assert "5001" in recuado.referencia
    # o zero recusado (05/01) e o zero de onde a composicao parte (03/01)
    assert "05/01/2026" in recuado.mensagem and "03/01/2026" in recuado.mensagem


# --- particao: o resultado do casamento dividido no corte ---------------------

from core.corte import particionar   # noqa: E402


def _particao(linhas, saldo_anterior="0.00"):
    conta = _conta(linhas, saldo_anterior=saldo_anterior)
    pares = [(l, CLASSIFICADOR.classificar(l)) for l in conta.lancamentos]
    resultado = casar(pares, conta.saldo_anterior)
    corte, _ = localizar_corte(conta.lancamentos, conta.saldo_anterior,
                               resultado, True)
    return resultado, particionar(resultado, conta.lancamentos, corte)


def _caso_sintetico():
    """Um caso em miniatura: duas NFs na abertura, um "Pago conf."
    que soma as duas e NAO casa com nenhuma (valor de nenhuma), o saldo zera,
    e depois uma NF nova fica em aberto."""
    return _particao([
        (COMPRA.format(nf="5001"), "0.00", "700.00", 2),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 2),
        (PAGO_CONF, "1000.00", "0.00", 5),                        # zera
        (COMPRA.format(nf="5003"), "0.00", "250.00", 9)])


def test_particao_manda_pro_periodo_zerado_o_que_ficou_antes_do_zero():
    resultado, p = _caso_sintetico()
    assert [nf.numero for nf in p.nfs_fechadas] == ["5001", "5002"]
    assert [i.lancamentos[0].numero for i in p.balde_fechado] == ["L3"]
    assert [nf.numero for nf in p.resultado.nfs] == ["5003"]
    assert p.resultado.balde == []
    # nada some: toda NF e todo item estao de um lado ou do outro
    assert len(p.nfs_fechadas) + len(p.resultado.nfs) == len(resultado.nfs)
    assert (len(p.balde_fechado) + len(p.resultado.balde)
            == len(resultado.balde))


def test_particao_mantem_todos_os_achados_do_casamento():
    resultado, p = _caso_sintetico()
    assert p.resultado.achados == resultado.achados


def test_cada_item_do_periodo_zerado_sabe_quando_o_saldo_zerou_depois_dele():
    _, p = _particao([
        (COMPRA.format(nf="5001"), "0.00", "200.00", 2),
        (ESTRANHO, "200.00", "0.00", 3),                          # zera em 03/01
        (COMPRA.format(nf="5002"), "0.00", "300.00", 4),
        (ESTRANHO, "300.00", "0.00", 6),                          # zera em 06/01
        (COMPRA.format(nf="5003"), "0.00", "50.00", 8)])
    # O ZERO (lancamento) e nao so' a data -- a frase precisa do lote
    zerou = p.zerou_em
    assert (zerou["5001"].data, zerou["5001"].numero) == (date(2026, 1, 3), "L2")
    assert (zerou["5002"].data, zerou["5002"].numero) == (date(2026, 1, 6), "L4")
    (b1, b2) = p.balde_fechado
    assert zerou[b1.identificador].numero == "L2"
    assert zerou[b2.identificador].numero == "L4"


def test_sem_corte_a_particao_e_o_resultado_inteiro():
    conta = _conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2)])
    pares = [(l, CLASSIFICADOR.classificar(l)) for l in conta.lancamentos]
    resultado = casar(pares, conta.saldo_anterior)
    p = particionar(resultado, conta.lancamentos, None)
    assert p.resultado is resultado
    assert p.nfs_fechadas == [] and p.balde_fechado == []


# --- ponta a ponta: o conferir com corte --------------------------------------

def _conferir_caso_sintetico(*alocacoes):
    from core.conferencia import conferir
    conta = _conta([
        (COMPRA.format(nf="5001"), "0.00", "700.00", 2),
        (COMPRA.format(nf="5002"), "0.00", "300.00", 2),
        (PAGO_CONF, "1000.00", "0.00", 5),                        # zera
        (COMPRA.format(nf="5003"), "0.00", "250.00", 9)])
    return conta, conferir(conta, CLASSIFICADOR, alocacoes)


def test_conferir_com_corte_compoe_so_o_pos_corte_e_fecha():
    _, res = _conferir_caso_sintetico()
    assert [(i.nf_numero, i.saldo_aberto) for i in res.itens] == [
        ("5003", D("250.00"))]
    assert res.balde == []
    check = next(a for a in res.achados if a.codigo == "self_check_composicao")
    assert check.nivel is Nivel.OK                 # era INCOMPLETO sem o corte
    fechado = res.fechado
    assert fechado.data == date(2026, 1, 5) and fechado.lote == "L3"
    assert [i.nf_numero for i in fechado.itens] == ["5001", "5002"]
    assert fechado.total_aberto == fechado.total_sem_nf == D("1000.00")
    (aviso,) = [a for a in res.achados
                if a.codigo == "periodo_zerado_com_pendencia"]
    assert aviso.nivel is Nivel.ALERTA
    p = res.ponte
    assert p.total_em_aberto_nf_a_nf == D("1250.00")
    assert p.total_compensado_saldo_zero == D("1000.00")
    assert p.total_em_aberto == p.saldo_apurado == p.saldo_dominio == D("250.00")


def test_conferir_sem_zero_e_o_de_sempre():
    from core.conferencia import conferir
    conta = _conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                    (PAGO_CONF, "300.00", "0.00", 5)])
    res = conferir(conta, CLASSIFICADOR)
    assert res.fechado is None
    assert len(res.balde) == 1
    assert res.ponte.total_compensado_saldo_zero == D("0.00")
    assert not [a for a in res.achados if a.codigo in
                ("periodo_zerado_com_pendencia", "corte_recuado")]


def test_decisao_fora_da_composicao_no_periodo_zerado_faz_o_corte_recuar():
    """A decisao "fora" entra na identidade do pos-corte, entao o item dela
    nunca pode ficar no periodo zerado: o zero a partir dele e' recusado."""
    from core.conferencia import conferir
    from core.modelo import AlocacaoManual, DestinoAlocacao
    conta, antes = _conferir_caso_sintetico()
    item = antes.fechado.balde[0]
    res = conferir(conta, CLASSIFICADOR, [AlocacaoManual(
        item_id=item.identificador, destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
        rotulo="pagamento de outra conta")])
    assert res.fechado is None
    assert [a.codigo for a in res.achados if a.codigo == "corte_recuado"] \
        == ["corte_recuado"]
    assert res.ponte.diferenca == D("0.00")



# --- o periodo zerado por BLOCO (a frase cita o zero de cada um) ---------

def _dois_blocos_com_pendencia():
    """Dois "Pago conf." que nao casam com nenhuma NF (valor de nenhuma), cada
    um zerando a conta: 03/01 fecha 5001+5002, 06/01 fecha 5003+5004."""
    from core.conferencia import conferir
    conta = _conta([
        (COMPRA.format(nf="5001"), "0.00", "610.00", 2),
        (COMPRA.format(nf="5002"), "0.00", "90.00", 2),
        (PAGO_CONF, "700.00", "0.00", 3),                         # zera 03/01
        (COMPRA.format(nf="5003"), "0.00", "250.00", 5),
        (COMPRA.format(nf="5004"), "0.00", "150.00", 5),
        (PAGO_CONF, "400.00", "0.00", 6),                         # zera 06/01
        (COMPRA.format(nf="5005"), "0.00", "50.00", 8)])
    return conferir(conta, CLASSIFICADOR)


def test_blocos_agrupam_a_pendencia_pelo_zero_que_a_fecha():
    res = _dois_blocos_com_pendencia()
    b1, b2 = res.fechado.blocos
    assert (b1.zero.data, b1.zero.numero) == (date(2026, 1, 3), "L3")
    assert [i.nf_numero for i in b1.itens] == ["5001", "5002"]
    assert [i.lancamentos[0].numero for i in b1.balde] == ["L3"]
    assert b1.total_aberto == b1.total_sem_nf == D("700.00") and b1.bate
    assert (b2.zero.data, b2.zero.numero) == (date(2026, 1, 6), "L6")
    assert b2.total_aberto == b2.total_sem_nf == D("400.00") and b2.bate
    assert b2.diferenca == D("0.00")


def test_um_alerta_por_bloco_citando_o_zero_dele():
    res = _dois_blocos_com_pendencia()
    avisos = [a for a in res.achados if a.codigo == "periodo_zerado_com_pendencia"]
    assert [a.mensagem for a in avisos] == [
        "o saldo da conta zerou em 03/01/2026 (lote L3)",
        "o saldo da conta zerou em 06/01/2026 (lote L6)"]
    assert [a.referencia for a in avisos] == ["L3", "L6"]
    assert [a.valores["sem_nf"] for a in avisos] == [D("700.00"), D("400.00")]
    assert [a.valores["notas"] for a in avisos] == [D("2"), D("2")]


def test_linha_do_saldo_anterior_pertence_ao_bloco_que_a_consome():
    _, p = _particao([
        (PAGAMENTO_NF.format(nf="4001"), "700.00", "0.00", 2),    # zera 02/01
        (COMPRA.format(nf="5001"), "0.00", "100.00", 3),
        (ESTRANHO, "100.00", "0.00", 4),                          # zera 04/01
        (COMPRA.format(nf="5002"), "0.00", "50.00", 6)],
        saldo_anterior="-700.00")
    from core.modelo import ALVO_ANTERIOR
    assert p.zerou_em[ALVO_ANTERIOR].numero == "L1"


# --- parcela repetida cujas ocorrencias foram pro periodo zerado -----

def test_alerta_de_parcela_repetida_diz_que_as_ocorrencias_estao_no_periodo_zerado():
    from core.corte import situar_duplicidade_no_corte
    from core.modelo import Achado, FechadoPorSaldoZero
    l1 = _lanc("L1", "100.00", "0.00", "100.00")
    l2 = _lanc("L2", "100.00", "0.00", "200.00")
    zero = _lanc("L3", "0.00", "200.00", "0.00")
    i1 = ItemRevisao([l1], MotivoRevisao.EMPATE, identificador="a")
    i2 = ItemRevisao([l2], MotivoRevisao.EMPATE, identificador="b")
    fechado = FechadoPorSaldoZero(data=zero.data, lote="L3", zeros=(zero,),
                                  balde=[i1, i2], zerou_em={"a": zero, "b": zero})
    alerta = Achado(Nivel.ALERTA, "possivel_duplicidade",
                    "possível duplicidade: parcela 5 de 5 paga 2 vezes (lotes "
                    "L1, L2); há ocorrência(s) no balde de revisão manual",
                    referencia="L1, L2")
    (a,) = situar_duplicidade_no_corte([alerta], fechado, [])
    assert a.mensagem == ("possível duplicidade: parcela 5 de 5 paga 2 vezes "
                          "(lotes L1, L2); as ocorrências sem destino estão no "
                          "período já zerado (a conta zerou em 02/01/2026)")
    assert a.nivel is Nivel.ALERTA and a.referencia == "L1, L2"
    # ocorrencia ainda no balde do pos-corte: a frase original continua certa
    (b,) = situar_duplicidade_no_corte([alerta], fechado, [i2])
    assert b.mensagem == alerta.mensagem
    # sem corte: nada muda
    assert situar_duplicidade_no_corte([alerta], None, []) == [alerta]

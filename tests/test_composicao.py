from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.composicao import compor, quitadas
from core.modelo import NF, ComposicaoItem, CriterioDesempate, Desempate, Nivel, Origem
from core.veredito import self_check_composicao
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN, identidade_da_tabela, lanc


def _compor_ferramentas_ficticias():
    conta = ExcelParser().parse(GOLDEN)[0]
    clf = ClassificadorHistorico()
    pares = [(l, clf.classificar(l)) for l in conta.lancamentos]
    nfs = casar(pares).nfs
    itens = compor(nfs, conta.saldo_anterior, conta.data_fim_periodo)
    return conta, itens


def test_golden_composicao_por_nf():
    _, itens = _compor_ferramentas_ficticias()
    por_nf = {i.nf_numero: i for i in itens}
    assert por_nf["618204"].saldo_aberto == Decimal("2820.00")
    assert por_nf["274591"].saldo_aberto == Decimal("1440.09")


def test_golden_composicao_total_e_itens():
    _, itens = _compor_ferramentas_ficticias()
    # nao_detalhado == 0 -> SEM item SALDO_ANTERIOR; exatamente 2 itens COMPRA_PERIODO
    assert len(itens) == 2
    assert all(i.origem is Origem.COMPRA_PERIODO for i in itens)
    total = sum((i.saldo_aberto for i in itens), Decimal("0.00"))
    assert total == Decimal("4260.09")


def test_golden_veredito_composicao_fecha():
    conta, itens = _compor_ferramentas_ficticias()
    saldo_final = conta.lancamentos[-1].saldo_exercicio          # -4260.09
    achados = self_check_composicao(itens, saldo_final)
    assert achados and all(a.nivel is Nivel.OK for a in achados)   # fecha; sem ERRO nem ALERTA


# --- veredito da composicao: divergencia e alerta (Task 7) ---

def _item(saldo):
    return ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("0.00"), total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal(saldo))


def test_divergencia_quando_soma_nao_bate_saldo_final():
    # soma itens = 100, mas saldo final = -150 -> divergencia (NUNCA forca a fechar)
    achados = self_check_composicao([_item("100.00")], saldo_final=Decimal("-150.00"))
    erro = [a for a in achados if a.codigo == "self_check_composicao"][0]
    assert erro.nivel is Nivel.ERRO
    assert erro.esperado == Decimal("150.00")
    assert erro.encontrado == Decimal("100.00")


def test_saldo_anterior_nao_detalhado_emite_alerta():
    itens = [ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                            valor_compra=Decimal("0.00"), total_pago=Decimal("0.00"),
                            total_retido=Decimal("0.00"), saldo_aberto=Decimal("300.00"))]
    achados = self_check_composicao(itens, saldo_final=Decimal("-300.00"))
    assert any(a.codigo == "saldo_anterior_nao_detalhado" and a.nivel is Nivel.ALERTA
               for a in achados)


# --- possivel juros: aberto negativo = pago > compra ----------------------------

def test_aberto_negativo_sinaliza_possivel_juros():
    """Um caso: 860014 = -4,38. NUNCA marca 'pago a mais' automatico
    — sinaliza possivel juros por atraso pra investigacao."""
    item = ComposicaoItem(nf_numero="860014", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("2000.00"),
                          total_pago=Decimal("2004.38"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-4.38"))
    achados = self_check_composicao([item], saldo_final=Decimal("4.38"))
    juros = [a for a in achados if a.codigo == "possivel_juros"]
    assert len(juros) == 1
    a = juros[0]
    assert a.nivel is Nivel.ALERTA
    assert "860014" in a.mensagem
    assert "juros" in a.mensagem
    assert "pago a mais" not in a.mensagem.lower()   # nunca acusa automatico
    assert a.esperado == Decimal("2000.00")          # compra
    assert a.encontrado == Decimal("2004.38")        # quitado
    # #34: a diferenca vem em CAMPO (a frase com moeda nasce na apresentacao);
    # a mensagem do core e neutra — nenhum Decimal cru embutido
    assert a.valores["diferenca"] == Decimal("4.38")
    assert "4.38" not in a.mensagem


def test_compra_negativa_nao_dispara_possivel_juros():
    """Estorno: COMPRA com valor NEGATIVO nao e 'juros por atraso' (nao ha
    pagamento; a identidade fecha). possivel_juros so quando valor_compra > 0."""
    item = ComposicaoItem(nf_numero="8001", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("-300.00"),
                          total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-300.00"))
    achados = self_check_composicao([item], saldo_final=Decimal("300.00"))
    assert [a for a in achados if a.codigo == "possivel_juros"] == []


def test_residuo_dentro_da_tolerancia_nao_e_juros():
    """Um caso, NF 860017: -0,02 veio de um casamento em 2
    parcelas que a PROPRIA tolerancia de centavos aceitou (2 quitacoes ->
    2 centavos). Alertar juros sobre esse residuo seria contradicao interna:
    e quitada com arredondamento, nao juros."""
    item = ComposicaoItem(nf_numero="860017", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1760.00"),
                          total_pago=Decimal("1760.02"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-0.02"),
                          qtd_quitacoes=2)
    achados = self_check_composicao([item], saldo_final=Decimal("0.02"))
    assert [a for a in achados if a.codigo == "possivel_juros"] == []
    assert item.quitada_com_arredondamento is True


def test_residuo_acima_da_tolerancia_continua_juros():
    # 2 quitacoes toleram 2 centavos; -0,03 ja nao e arredondamento
    item = ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("100.00"),
                          total_pago=Decimal("100.03"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-0.03"),
                          qtd_quitacoes=2)
    achados = self_check_composicao([item], saldo_final=Decimal("0.03"))
    assert len([a for a in achados if a.codigo == "possivel_juros"]) == 1
    assert item.quitada_com_arredondamento is False


def test_pagamento_unico_nao_ganha_tolerancia_de_dois_centavos():
    # 1 quitacao tolera 1 centavo: -0,02 com pagamento UNICO alerta
    item = ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("100.00"),
                          total_pago=Decimal("100.02"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-0.02"),
                          qtd_quitacoes=1)
    achados = self_check_composicao([item], saldo_final=Decimal("0.02"))
    assert len([a for a in achados if a.codigo == "possivel_juros"]) == 1


def test_compor_preenche_qtd_quitacoes():
    nf = NF(numero="10", valor_compra=Decimal("1000.00"),
            data_compra=date(2025, 1, 10),
            pagamentos=[lanc(historico="h", data=date(2025, 2, 1), debito="100.00"),
                        lanc(historico="h", data=date(2025, 3, 1), debito="100.00")],
            retencoes=[lanc(historico="h", data=date(2025, 3, 5), debito="50.00")],
            baixas=[lanc(historico="h", data=date(2025, 4, 1), debito="80.00")])
    item = compor([nf], Decimal("0.00"), date(2025, 12, 31))[0]
    assert item.qtd_quitacoes == 4


def test_aberto_positivo_nao_sinaliza_juros():
    achados = self_check_composicao([_item("100.00")],
                                    saldo_final=Decimal("-100.00"))
    assert [a for a in achados if a.codigo == "possivel_juros"] == []


def test_item_anterior_negativo_nao_e_juros():
    # excesso sobre o saldo anterior agregado tem OUTRO significado — fora
    # do achado de juros (que e por NF de compra)
    anterior = ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                              valor_compra=Decimal("0.00"),
                              total_pago=Decimal("500.00"),
                              total_retido=Decimal("0.00"),
                              saldo_aberto=Decimal("-500.00"))
    achados = self_check_composicao([anterior], saldo_final=Decimal("500.00"))
    assert [a for a in achados if a.codigo == "possivel_juros"] == []


# --- datas na composicao: o dado ja existe nos Lancamentos ligados ---------------


def test_item_de_compra_carrega_data_da_nf_e_do_ultimo_pagamento():
    # ultimo pagamento = max sobre pagamentos + retencoes + baixas (a familia
    # inteira de quitacao conta, nao so o numerario)
    nf = NF(numero="10", valor_compra=Decimal("1000.00"), data_compra=date(2025, 1, 10),
            pagamentos=[lanc(historico="h", data=date(2025, 2, 1), debito="100.00")],
            retencoes=[lanc(historico="h", data=date(2025, 3, 1), debito="50.00")],
            baixas=[lanc(historico="h", data=date(2025, 6, 15), debito="80.00")])
    item = compor([nf], Decimal("0.00"), date(2025, 12, 31))[0]
    assert item.data_compra == date(2025, 1, 10)
    assert item.data_ultima_quitacao == date(2025, 6, 15)


def test_item_sem_quitacao_nao_tem_ultimo_pagamento():
    nf = NF(numero="11", valor_compra=Decimal("500.00"), data_compra=date(2025, 5, 2))
    item = compor([nf], Decimal("0.00"), date(2025, 12, 31))[0]
    assert item.data_compra == date(2025, 5, 2)
    assert item.data_ultima_quitacao is None


def test_item_anterior_sem_data_de_compra_e_com_ultima_quitacao():
    # NF sem compra no periodo consome o saldo anterior: o item (anterior) nao
    # tem data de compra, mas registra quando foi mexido pela ultima vez
    nf = NF(numero="99", pagamentos=[lanc(historico="h", data=date(2025, 6, 1), debito="300.00")])
    itens = compor([nf], Decimal("-1000.00"), date(2025, 12, 31))
    anterior = itens[-1]
    assert anterior.nf_numero == "(anterior)"
    assert anterior.data_compra is None
    assert anterior.data_ultima_quitacao == date(2025, 6, 1)


# --- identidade da TABELA: compra − pago − retido − baixa − manual == aberto ---


def test_golden_fecha_a_identidade_da_tabela():
    _, itens = _compor_ferramentas_ficticias()
    identidade_da_tabela(itens)


def test_item_de_nf_carrega_o_valor_alocado_a_mao():
    # o VALOR, nao so a contagem: e o que a coluna "Alocado a mao" mostra
    nf = NF(numero="10", valor_compra=Decimal("1000.00"), data_compra=date(2025, 1, 10),
            manuais=[lanc(historico="h", data=date(2025, 2, 1), debito="300.00")])
    item = compor([nf], Decimal("0.00"), date(2025, 12, 31))[0]
    assert item.total_manual == Decimal("300.00")
    assert item.total_pago == Decimal("0.00")          # nao se mistura
    assert item.saldo_aberto == Decimal("700.00")
    identidade_da_tabela([item])


def test_item_anterior_mostra_o_saldo_trazido_como_compra():
    # a linha "(anterior)" so' fecha aos olhos se o "Valor compra" dela for o
    # que se devia no inicio do periodo: 1.000 − 300 pagos = 700 nao detalhado
    nf = NF(numero="99", pagamentos=[lanc(historico="h", data=date(2025, 6, 1),
                                          debito="300.00")])
    anterior = compor([nf], Decimal("-1000.00"), date(2025, 12, 31))[-1]
    assert anterior.nf_numero == "(anterior)"
    assert anterior.valor_compra == Decimal("1000.00")
    assert anterior.total_pago == Decimal("300.00")
    assert anterior.saldo_aberto == Decimal("700.00")
    identidade_da_tabela([anterior])


def test_item_anterior_separa_retencao_e_manual_do_pago():
    # cada familia no seu campo, como nas linhas de NF (antes retido e manual
    # iam somados dentro de total_pago SO' nesta linha)
    nf = NF(numero="99",
            pagamentos=[lanc(historico="h", data=date(2025, 6, 1), debito="300.00")],
            retencoes=[lanc(historico="h", data=date(2025, 6, 2), debito="50.00")],
            manuais=[lanc(historico="h", data=date(2025, 6, 3), debito="100.00")])
    anterior = compor([nf], Decimal("-1000.00"), date(2025, 12, 31))[-1]
    assert anterior.total_pago == Decimal("300.00")
    assert anterior.total_retido == Decimal("50.00")
    assert anterior.total_manual == Decimal("100.00")
    assert anterior.total_baixado == Decimal("0.00")
    assert anterior.saldo_aberto == Decimal("550.00")
    identidade_da_tabela([anterior])


def test_item_anterior_com_saldo_trazido_nao_dispara_juros_nem_desconto():
    # GUARDA: valor_compra > 0 na "(anterior)" nao pode ligar os alertas que sao
    # por NF de compra — juros (aberto negativo) e desconto (residuo pequeno a
    # menor). Passa pelo gate de origem do veredito, que esta spec nao toca.
    estourada = NF(numero="98", pagamentos=[lanc(historico="h", debito="1005.00")])
    itens = compor([estourada], Decimal("-1000.00"), date(2025, 12, 31))
    assert itens[-1].valor_compra == Decimal("1000.00")
    assert itens[-1].saldo_aberto == Decimal("-5.00")
    codigos = {a.codigo for a in self_check_composicao(itens, saldo_final=Decimal("5.00"))}
    assert not codigos & {"possivel_juros", "possivel_juros_manual", "possivel_desconto"}

    quase = NF(numero="97", pagamentos=[lanc(historico="h", debito="985.00")])
    itens = compor([quase], Decimal("-1000.00"), date(2025, 12, 31))
    assert itens[-1].saldo_aberto == Decimal("15.00")
    codigos = {a.codigo for a in self_check_composicao(itens, saldo_final=Decimal("-15.00"))}
    assert "possivel_desconto" not in codigos


# --- ultima quitacao conta a alocacao manual ---


def test_ultima_quitacao_conta_o_lancamento_alocado_a_mao():
    # a coluna responde "quando mexeu por ultimo": o que o contador alocou e um
    # movimento real sobre o titulo (precedente: a Alocacao multi-NF ja contava)
    nf = NF(numero="10", valor_compra=Decimal("1000.00"), data_compra=date(2025, 1, 10),
            pagamentos=[lanc(historico="h", data=date(2025, 2, 1), debito="100.00")],
            manuais=[lanc(historico="h", data=date(2025, 3, 1), debito="300.00")])
    item = compor([nf], Decimal("0.00"), date(2025, 12, 31))[0]
    assert item.data_ultima_quitacao == date(2025, 3, 1)


def test_item_anterior_ultima_quitacao_conta_a_alocacao_ao_anterior():
    nf = NF(numero="99",
            pagamentos=[lanc(historico="h", data=date(2025, 6, 1), debito="300.00")],
            manuais=[lanc(historico="h", data=date(2025, 7, 1), debito="100.00")])
    anterior = compor([nf], Decimal("-1000.00"), date(2025, 12, 31))[-1]
    assert anterior.data_ultima_quitacao == date(2025, 7, 1)


# --- NFs quitadas no periodo: a foto completa ---
# `quitadas()` e' canal PROPRIO: `compor()` continua devolvendo so' o que esta
# aberto (a identidade do gap e os self_checks leem de la e nao mudam).


def test_quitadas_lista_a_nf_com_compra_e_saldo_zero_com_os_campos_da_linha():
    nf = NF(numero="10", valor_compra=Decimal("1000.00"), data_compra=date(2025, 1, 10),
            pagamentos=[lanc(historico="h", data=date(2025, 2, 1), debito="600.00")],
            retencoes=[lanc(historico="h", data=date(2025, 2, 5), debito="400.00")])
    (item,) = quitadas([nf], date(2025, 12, 31))
    assert item.nf_numero == "10"
    assert item.origem is Origem.COMPRA_PERIODO
    assert item.valor_compra == Decimal("1000.00")
    assert item.total_pago == Decimal("600.00")
    assert item.total_retido == Decimal("400.00")
    assert item.saldo_aberto == Decimal("0.00")
    assert item.idade_dias == 355                        # mesma conta da linha aberta
    assert item.data_compra == date(2025, 1, 10)
    assert item.data_ultima_quitacao == date(2025, 2, 5)
    assert item.qtd_quitacoes == 2
    identidade_da_tabela([item])
    assert compor([nf], Decimal("0.00"), date(2025, 12, 31)) == []   # aberta: nao


def test_quitadas_exclui_aberta_sem_compra_residuo_na_tolerancia_e_cancelada():
    aberta = NF(numero="1", valor_compra=Decimal("100.00"), data_compra=date(2025, 1, 1))
    sem_compra = NF(numero="2", pagamentos=[lanc(historico="h", debito="50.00")])
    # residuo NEGATIVO dentro da tolerancia: saldo != 0 -> continua na composicao
    # com a nota de arredondamento, nao e' "quitada"
    residuo = NF(numero="3", valor_compra=Decimal("100.00"), data_compra=date(2025, 1, 1),
                 pagamentos=[lanc(historico="h", debito="100.01")])
    # compra liquida zero com saldo zero e' cancelamento, nao quitacao
    cancelada = NF(numero="4", valor_compra=Decimal("0.00"), data_compra=date(2025, 1, 1))
    assert quitadas([aberta, sem_compra, residuo, cancelada], date(2025, 12, 31)) == []
    assert [i.nf_numero for i in compor([aberta, sem_compra, residuo, cancelada],
                                        Decimal("-50.00"), date(2025, 12, 31))] == ["1", "3"]


def test_quitada_carrega_desempate_e_alocacao_manual():
    pago = lanc(historico="h", data=date(2025, 3, 1), debito="700.00")
    nf = NF(numero="10", valor_compra=Decimal("1000.00"), data_compra=date(2025, 1, 10),
            pagamentos=[pago],
            desempates=[Desempate(lancamento=pago,
                                  criterio=CriterioDesempate.DATA_MAIS_ANTIGA)],
            manuais=[lanc(historico="h", data=date(2025, 4, 1), debito="300.00")])
    (item,) = quitadas([nf], date(2025, 12, 31))
    assert item.desempates == (CriterioDesempate.DATA_MAIS_ANTIGA,)
    assert item.total_manual == Decimal("300.00")
    assert item.quitacoes_manuais == 1
    assert item.data_ultima_quitacao == date(2025, 4, 1)
    identidade_da_tabela([item])


def test_golden_nao_tem_quitadas():
    conta = ExcelParser().parse(GOLDEN)[0]
    clf = ClassificadorHistorico()
    nfs = casar([(l, clf.classificar(l)) for l in conta.lancamentos]).nfs
    assert quitadas(nfs, conta.data_fim_periodo) == []


# --- a referencia como DADO (a NF/lote sai da prosa e vira campo) -------------


def test_possivel_juros_carrega_a_nf_em_campo_proprio():
    item = ComposicaoItem(nf_numero="860014", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1000.00"),
                          total_pago=Decimal("1002.19"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-2.19"))
    (juros,) = [a for a in self_check_composicao([item], Decimal("2.19"))
                if a.codigo == "possivel_juros"]
    assert juros.referencia == "860014"


def test_juros_de_origem_manual_tambem_carrega_a_nf():
    item = ComposicaoItem(nf_numero="860006", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1000.00"),
                          total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"),
                          total_manual=Decimal("1200.00"),
                          saldo_aberto=Decimal("-200.00"),
                          quitacoes_manuais=1)
    (juros,) = [a for a in self_check_composicao([item], Decimal("200.00"))
                if a.codigo == "possivel_juros_manual"]
    assert juros.referencia == "860006"


def test_achado_da_conta_inteira_fica_sem_referencia():
    """Saldo anterior nao detalhado, conta devedora e o self-check nao falam de
    uma NF: referencia None (a coluna mostra travessao, ou some inteira)."""
    anterior = ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                              valor_compra=Decimal("500.00"),
                              total_pago=Decimal("0.00"),
                              total_retido=Decimal("0.00"),
                              saldo_aberto=Decimal("500.00"))
    achados = self_check_composicao([anterior], saldo_final=Decimal("-500.00"))
    por_codigo = {a.codigo: a for a in achados}
    assert por_codigo["saldo_anterior_nao_detalhado"].referencia is None
    assert por_codigo["self_check_composicao"].referencia is None

"""Ponte do saldo: o caminho entre o que se comprou e o saldo do Dominio.

A ponte e a identidade que ja existe (gap == Σ balde + Σ fora) ABERTA
em linhas. Duas invariantes, cobradas em todo cenario:

  topo: saldo_anterior + compras + transferencias − pago − retido − baixa −
        alocado_manual == total_em_aberto  (soma das NFs x soma da tabela)
  base: diferenca == residuo do self_check_composicao — a ponte nao tem juiz
        proprio; ela fecha exatamente quando a identidade fecha.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.conferencia import conferir
from core.modelo import AlocacaoManual, Conta, DestinoAlocacao, Lancamento, Nivel
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()

COMPRA = "Vr. compras conf. {nf} FORNECEDOR FICTICIO LTDA"
PAGAMENTO = "Valor ref. a Pgto a FORNECEDOR FICTICIO"
PAGAMENTO_NF = "- PAGTO REF. NF.:  {nf}.1 - PARC.:FORNECEDOR FICTICIO"
TRANSFERENCIA = ("TRANSFERENCIA DE SALDOS DE CONTAS DE UM MESMO FORNECEDOR "
                 "FORNECEDOR FICTICIO")
ESTRANHO = "lancamento sem padrao conhecido"


def _conta(linhas, saldo_anterior="0.00", erro_no_saldo_final="0.00"):
    """Conta sintetica COERENTE (saldo corrente e totais saem das linhas).
    `erro_no_saldo_final` desloca so' o saldo impresso da ULTIMA linha — o
    jeito de fabricar um residuo na identidade da composicao."""
    saldo = D(saldo_anterior)
    lancamentos = []
    for i, (historico, debito, credito, dia) in enumerate(linhas, start=1):
        saldo += D(debito) - D(credito)
        lancamentos.append(Lancamento(
            data=date(2026, 1, dia), numero=f"L{i}", historico=historico,
            cta_part="1.1.1", debito=D(debito), credito=D(credito),
            saldo_exercicio=saldo))
    lancamentos[-1].saldo_exercicio += D(erro_no_saldo_final)
    return Conta(
        codigo="9999", classificacao="2.01.01", nome="FORNECEDOR FICTICIO",
        data_fim_periodo=date(2026, 3, 31), saldo_anterior=D(saldo_anterior),
        lancamentos=lancamentos,
        total_debito_dominio=sum((l.debito for l in lancamentos), D("0.00")),
        total_credito_dominio=sum((l.credito for l in lancamentos), D("0.00")))


def _check(res):
    return next(a for a in res.achados if a.codigo == "self_check_composicao")


def invariantes_da_ponte(res) -> None:
    """As duas invariantes + a amarracao com o placar."""
    p = res.ponte
    topo = (p.saldo_anterior + p.total_compras + p.total_transferencias
            - p.total_pago - p.total_retido - p.total_baixa_adiantamento
            - p.total_alocado_manual)
    # o topo soma a razao INTEIRA e chega no aberto NF a NF; o
    # corte por saldo zero tira o periodo zerado numa linha propria, que e' o
    # liquido do balde de la == o aberto de la (trava do corte)
    assert topo == p.total_em_aberto_nf_a_nf
    assert (p.total_em_aberto_nf_a_nf - p.total_compensado_saldo_zero
            == p.total_em_aberto)
    fechado = res.fechado
    if fechado is not None:
        assert fechado.total_aberto == fechado.total_sem_nf \
            == p.total_compensado_saldo_zero
    else:
        assert p.total_compensado_saldo_zero == D("0.00")
    assert p.total_em_aberto == sum((i.saldo_aberto for i in res.itens),
                                    D("0.00"))
    assert p.saldo_apurado == (p.total_em_aberto - p.balde_debitos
                               + p.balde_creditos - p.total_fora_composicao)
    assert p.diferenca == p.saldo_apurado - p.saldo_dominio
    # o TOTAL de "EM ABERTO" da tabela e' sempre o "(=) Em aberto" da ponte
    # (as quitadas que a tabela junta valem 0,00)
    t = res.totais_tabela
    assert t.saldo_aberto == p.total_em_aberto
    _identidade_dos_totais(t, res.itens + res.quitadas)
    check = _check(res)
    # placar e ponte leem os MESMOS numeros
    assert p.total_em_aberto == check.valores["total"]
    assert p.saldo_dominio == check.valores["alvo"]
    # base: sem juiz proprio -- a diferenca E' o residuo do self_check
    residuo = check.valores.get("residuo",
                                D("0.00") if check.nivel is not Nivel.ERRO
                                else check.valores["gap"])
    if check.nivel is Nivel.ERRO:
        assert p.diferenca == residuo != D("0.00")
    else:
        assert abs(p.diferenca) <= D("0.01")


# --- golden ------------------------------------------------------------------

def test_golden_ponte_fecha_em_4260_09():
    res = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    p = res.ponte
    assert p.saldo_anterior == D("429.26")
    assert p.total_compras == D("7100.03")        # 4.700,00 + 2.400,03
    assert p.total_transferencias == D("0.00")
    # inclui os 2 x 214,63 que consumiram o saldo anterior (NF 512309)
    assert p.total_pago == D("3269.20")
    assert p.total_retido == D("0.00")
    assert p.total_baixa_adiantamento == D("0.00")
    assert p.total_alocado_manual == D("0.00")
    assert p.total_em_aberto == D("4260.09")
    assert p.balde_debitos == p.balde_creditos == D("0.00")
    assert p.total_fora_composicao == D("0.00")
    assert p.saldo_apurado == p.saldo_dominio == D("4260.09")
    assert p.diferenca == D("0.00")
    invariantes_da_ponte(res)


# --- cenarios sinteticos -----------------------------------------------------

def test_compra_da_mesma_nf_em_duas_linhas_soma_cada_lancamento_uma_vez():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "600.00", 2),
                           (COMPRA.format(nf="5001"), "0.00", "400.00", 3)]),
                   CLASSIFICADOR)
    assert res.ponte.total_compras == D("1000.00")
    assert res.ponte.total_em_aberto == D("1000.00")
    invariantes_da_ponte(res)


def test_saldo_anterior_nao_detalhado_entra_inteiro_e_sobra_em_aberto():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2)],
                          saldo_anterior="-700.00"), CLASSIFICADOR)
    p = res.ponte
    assert p.saldo_anterior == D("700.00")
    assert p.total_em_aberto == D("1700.00")      # 1.000 da NF + 700 do anterior
    assert p.saldo_apurado == p.saldo_dominio == D("1700.00")
    invariantes_da_ponte(res)


def test_pagamento_que_consome_o_saldo_anterior_conta_como_pago():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (PAGAMENTO_NF.format(nf="4001"), "700.00", "0.00", 5)],
                          saldo_anterior="-700.00"), CLASSIFICADOR)
    p = res.ponte
    assert p.total_pago == D("700.00")
    assert p.total_em_aberto == D("1000.00")
    invariantes_da_ponte(res)


def test_transferencia_recebida_tem_linha_propria_e_nao_e_compra():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (TRANSFERENCIA, "0.00", "250.00", 4)]), CLASSIFICADOR)
    p = res.ponte
    assert p.total_compras == D("1000.00")
    assert p.total_transferencias == D("250.00")
    assert p.total_em_aberto == D("1250.00")
    invariantes_da_ponte(res)


def test_balde_abre_em_debitos_e_creditos_brutos():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (PAGAMENTO, "300.00", "0.00", 5),
                           (ESTRANHO, "0.00", "80.00", 6)]), CLASSIFICADOR)
    p = res.ponte
    assert len(res.balde) == 2
    assert p.balde_debitos == D("300.00")
    assert p.balde_creditos == D("80.00")
    assert p.balde_liquido == D("220.00")         # o que o status da ponte cita
    assert p.total_em_aberto == D("1000.00")
    assert p.saldo_apurado == p.saldo_dominio == D("780.00")
    invariantes_da_ponte(res)


# --- alocacao manual: a ponte reage porque sai do mesmo conferir() -----------

def _com_balde():
    return _conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                   (PAGAMENTO, "300.00", "0.00", 5),
                   (ESTRANHO, "0.00", "80.00", 6)])


def _id(res, lote):
    return next(i.identificador for i in res.balde
                if i.lancamentos[0].numero == lote)


def test_alocacao_em_linha_aberta_move_do_balde_pro_alocado_a_mao():
    conta = _com_balde()
    antes = conferir(conta, CLASSIFICADOR)
    res = conferir(conta, CLASSIFICADOR, [AlocacaoManual(
        item_id=_id(antes, "L2"), destino=DestinoAlocacao.LINHA_ABERTA,
        alvo="5001")])
    p = res.ponte
    assert p.total_alocado_manual == D("300.00")
    assert p.balde_debitos == D("0.00")
    assert p.total_em_aberto == D("700.00")
    assert p.saldo_apurado == antes.ponte.saldo_apurado     # so' mudou de linha
    invariantes_da_ponte(res)


def test_compra_nova_entra_no_alocado_a_mao_com_sinal_e_nao_em_compras():
    conta = _com_balde()
    antes = conferir(conta, CLASSIFICADOR)
    res = conferir(conta, CLASSIFICADOR, [AlocacaoManual(
        item_id=_id(antes, "L3"), destino=DestinoAlocacao.COMPRA_NOVA)])
    p = res.ponte
    assert p.total_compras == D("1000.00")               # so' o que a razao trouxe
    assert p.total_alocado_manual == D("-80.00")         # credito: liquido negativo
    assert p.balde_creditos == D("0.00")
    invariantes_da_ponte(res)


def test_fora_da_composicao_tem_linha_propria_e_a_ponte_fecha():
    conta = _com_balde()
    antes = conferir(conta, CLASSIFICADOR)
    res = conferir(conta, CLASSIFICADOR, [AlocacaoManual(
        item_id=_id(antes, "L2"), destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
        rotulo="pagamento de outro fornecedor")])
    p = res.ponte
    assert p.total_fora_composicao == D("300.00")
    assert p.balde_debitos == D("0.00")
    assert p.saldo_apurado == p.saldo_dominio
    invariantes_da_ponte(res)


# --- os tres status, sempre os mesmos do self_check --------------------------

@pytest.mark.parametrize("erro, com_balde, nivel, diferenca", [
    ("0.00", True, Nivel.INCOMPLETO, "0.00"),    # fecha exato
    ("0.01", True, Nivel.INCOMPLETO, "0.01"),   # tolerado: 1 centavo, com balde
    ("5.00", True, Nivel.ERRO, "5.00"),         # divergencia atras do balde
    ("0.01", False, Nivel.ERRO, "0.01"),        # sem balde nao ha tolerancia
])
def test_ponte_e_veredito_nunca_divergem_de_status(erro, com_balde, nivel,
                                                   diferenca):
    linhas = [(COMPRA.format(nf="5001"), "0.00", "1000.00", 2)]
    if com_balde:
        linhas.append((PAGAMENTO, "300.00", "0.00", 5))
    res = conferir(_conta(linhas, erro_no_saldo_final=erro), CLASSIFICADOR)
    assert _check(res).nivel is nivel
    assert res.ponte.diferenca == D(diferenca)      # o valor SEMPRE impresso
    invariantes_da_ponte(res)


# --- sinteticas de CI: todo cenario fecha a ponte ----------------------------

@pytest.mark.parametrize("arquivo", ["sintetica_integra.xls",
                                     "sintetica_integra.xlsx"])
def test_ponte_fecha_em_todo_cenario_sintetico(arquivo):
    from app.pipeline import processar_excel
    caminho = GOLDEN.parent / arquivo
    resultados = processar_excel(caminho).resultados
    assert resultados
    for res in resultados:
        invariantes_da_ponte(res)


# --- totais da tabela (linha TOTAL) e o que fica fora dela -------------------

def _identidade_dos_totais(t, linhas=()):
    """Compra e pago do total sao so' das notas; o que as linhas
    sem nota tem nessas duas colunas volta pela soma delas."""
    devolvido = sum((i.valor_compra - i.total_pago for i in linhas
                     if not i.e_nota), D("0.00"))
    assert (t.valor_compra - t.total_pago - t.total_retido - t.total_baixado
            - t.total_manual + devolvido) == t.saldo_aberto


def test_golden_totais_da_tabela_e_saldo_anterior_fora_dela():
    """O golden e' o caso da nota: os 2 x 214,63 consumiram o saldo anterior
    inteiro, a linha "(saldo anterior)" zerou e nao aparece -- entao "Valor
    compra" e "Total pago" da tabela ficam 429,26 abaixo da ponte."""
    res = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    t = res.totais_tabela
    assert t.valor_compra == D("7100.03")
    assert t.total_pago == D("2839.94")           # 3.269,20 - 429,26
    assert t.saldo_aberto == res.ponte.total_em_aberto == D("4260.09")
    _identidade_dos_totais(t)
    assert t.compra_fora_da_tabela == D("429.26")
    assert t.pago_fora_da_tabela == D("429.26")


def test_totais_batem_com_a_ponte_quando_a_linha_do_anterior_aparece():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (PAGAMENTO_NF.format(nf="4001"), "200.00", "0.00", 5)],
                          saldo_anterior="-700.00"), CLASSIFICADOR)
    t = res.totais_tabela
    # so' a NF -- os 700 trazidos e os 200 pagos contra eles (o
    # pagamento cita uma NF de antes da janela) ficam na linha do anterior
    assert t.valor_compra == D("1000.00")
    assert t.total_pago == D("0.00")
    _identidade_dos_totais(t, res.itens + res.quitadas)
    assert t.compra_fora_da_tabela == t.pago_fora_da_tabela == D("0.00")


def test_totais_somam_as_quitadas_e_a_compra_nova_manual():
    conta = _conta([(COMPRA.format(nf="5001"), "0.00", "300.00", 2),
                    (PAGAMENTO_NF.format(nf="5001"), "300.00", "0.00", 4),
                    (COMPRA.format(nf="5002"), "0.00", "1000.00", 5),
                    (ESTRANHO, "0.00", "80.00", 6)])
    antes = conferir(conta, CLASSIFICADOR)
    res = conferir(conta, CLASSIFICADOR, [AlocacaoManual(
        item_id=_id(antes, "L4"), destino=DestinoAlocacao.COMPRA_NOVA)])
    t = res.totais_tabela
    assert len(res.quitadas) == 1                 # a 5001 fechou e esta na tabela
    assert t.valor_compra == D("1380.00")         # 300 + 1.000 + 80 da compra nova
    assert t.total_pago == D("300.00")
    _identidade_dos_totais(t)
    assert t.compra_fora_da_tabela == t.pago_fora_da_tabela == D("0.00")


# --- o total do recorte padrao da tela (so' EM ABERTO != 0) -------------------

def test_totais_em_aberto_somam_so_as_linhas_com_saldo():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "300.00", 2),
                           (PAGAMENTO_NF.format(nf="5001"), "300.00", "0.00", 4),
                           (COMPRA.format(nf="5002"), "0.00", "1000.00", 5),
                           (PAGAMENTO_NF.format(nf="5002"), "400.00", "0.00", 6)],
                          saldo_anterior="-50.00"), CLASSIFICADOR)
    assert [i.nf_numero for i in res.itens_em_aberto] == ["5002", "(anterior)"]
    t = res.totais_em_aberto
    assert t.valor_compra == D("1000.00")        # so' a NF, sem o trazido
    assert t.total_pago == D("400.00")
    assert t.saldo_aberto == res.ponte.total_em_aberto == D("650.00")
    _identidade_dos_totais(t, res.itens_em_aberto)
    # a tabela completa (com a 5001 quitada) continua no totais_tabela
    assert res.totais_tabela.valor_compra == D("1300.00")

"""Alocacao manual: o contador decide o que o motor nao decidiu.

Contrato: `(razao + alocacoes) -> resultado`, sempre do zero. A aplicacao roda
DEPOIS de todo o casamento automatico, entao `alocacoes=()` reproduz o
comportamento de hoje por construcao. Alocacao invalida e IGNORADA e vira erro
explicito: o item fica no balde e a identidade continua fechando.

Identidade sagrada: gap == Σ(D−C) do balde restante (+ decisoes fora da
composicao, que chegam no proximo commit).
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.conferencia import conferir
from core.modelo import (
    ALVO_ANTERIOR,
    AlocacaoManual,
    Conta,
    DestinoAlocacao,
    Lancamento,
    Nivel,
    Origem,
)
from parser.historico import ClassificadorHistorico
from tests.helpers import identidade_da_tabela

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()

COMPRA = "Vr. compras conf. {nf} FORNECEDOR FICTICIO LTDA"
PAGAMENTO = "Valor ref. a Pgto a FORNECEDOR FICTICIO"


def _conta(linhas, saldo_anterior="0.00"):
    """Conta sintetica COERENTE: saldo corrente e totais calculados a partir das
    linhas, pra que os self-checks de parsing passem e o teste fale so' da
    alocacao. `linhas` = (historico, debito, credito, dia)."""
    saldo = D(saldo_anterior)
    lancamentos = []
    for i, (historico, debito, credito, dia) in enumerate(linhas, start=1):
        saldo += D(debito) - D(credito)
        lancamentos.append(Lancamento(
            data=date(2026, 1, dia), numero=f"L{i}", historico=historico,
            cta_part="1.1.1", debito=D(debito), credito=D(credito),
            saldo_exercicio=saldo))
    return Conta(
        codigo="9999", classificacao="2.01.01", nome="FORNECEDOR FICTICIO",
        data_fim_periodo=date(2026, 3, 31), saldo_anterior=D(saldo_anterior),
        lancamentos=lancamentos,
        total_debito_dominio=sum((l.debito for l in lancamentos), D("0.00")),
        total_credito_dominio=sum((l.credito for l in lancamentos), D("0.00")))


def _uma_nf_aberta_e_um_pagamento_solto():
    """NF de 1.000,00 em aberto e um pagamento de 300,00 que nao casa com nada
    (300 nao e parcela de 1.000) -> fica no balde."""
    return _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                   (PAGAMENTO, "300.00", "0.00", 20)])


def _res(conta, *alocacoes):
    return conferir(conta, CLASSIFICADOR, alocacoes)


def _item_id(res, lote):
    return next(i.identificador for i in res.balde
                if i.lancamentos[0].numero == lote)


def _aberto(res, nf_numero):
    return next(i.saldo_aberto for i in res.itens if i.nf_numero == nf_numero)


def _identidade_fecha(res):
    """gap == Σ(D−C) do balde restante, ao centavo — e a identidade da TABELA
    em toda linha."""
    identidade_da_tabela(res.itens)
    check = next(a for a in res.achados if a.codigo == "self_check_composicao")
    assert check.nivel is not Nivel.ERRO
    if res.balde:
        assert check.esperado == check.encontrado
    return check


def _erros(res):
    return [(e.codigo, e.mensagem) for e in res.erros_alocacao]


# --- regressao pura ----------------------------------------------------------

def test_lista_vazia_reproduz_o_comportamento_de_hoje():
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    assert _res(conta) == conferir(conta, CLASSIFICADOR)
    res = _res(conta)
    assert len(res.balde) == 1
    assert res.decisoes == []
    assert res.erros_alocacao == []
    _identidade_fecha(res)


def test_golden_com_lista_vazia_continua_ao_centavo():
    """Trava do caso dourado: a assinatura nova nao pode mexer no que fecha."""
    from app.pipeline import processar_excel
    from tests.helpers import GOLDEN

    res = processar_excel(GOLDEN).resultados[0]
    abertos = {i.nf_numero: i.saldo_aberto for i in res.itens}
    assert abertos["618204"] == D("2820.00")
    assert abertos["274591"] == D("1440.09")
    assert sum(abertos.values()) == D("4260.09")
    assert res.decisoes == []


# --- LINHA_ABERTA: NF ---------------------------------------------------------

def test_alocacao_para_nf_aberta_move_valor_e_fecha_a_composicao():
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    antes = _res(conta)
    assert _aberto(antes, "7777") == D("1000.00")

    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    assert _aberto(depois, "7777") == D("700.00")
    assert depois.balde == []
    assert depois.erros_alocacao == []
    check = _identidade_fecha(depois)
    assert check.nivel is Nivel.OK          # composicao fecha com o saldo final


def test_alocacao_manual_marca_a_linha_da_composicao():
    """Rastreabilidade: alocacao manual nunca se confunde com
    casamento automatico."""
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    item = next(i for i in depois.itens if i.nf_numero == "7777")
    assert item.quitacoes_manuais == 1
    assert item.total_pago == D("0.00")      # nao se mistura com pagamento automatico
    assert item.total_manual == D("300.00")  # ... e o VALOR vai na coluna propria
    assert item.data_ultima_quitacao == date(2026, 1, 20)   # e a DATA conta

    decisao = depois.decisoes[0]
    assert decisao.destino is DestinoAlocacao.LINHA_ABERTA
    assert decisao.alvo == "7777"
    assert decisao.valor == D("300.00")
    assert decisao.item.lancamentos[0].historico == PAGAMENTO   # evidencia integral


def test_credito_alocado_em_nf_quitada_reabre_o_titulo():
    """Credito REABRE titulo — bloquear seria errado. O sinal resolve: o efeito
    e (debito − credito), entao credito aumenta o saldo em aberto."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Valor ref. a Pgto a FORN NF 7777", "1000.00", "0.00", 15),
                    ("Recebimento conf. ALGO QUE O MOTOR NAO RECONHECE",
                     "0.00", "250.00", 20)])
    antes = _res(conta)
    assert _erros(antes) == []
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L3"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    assert depois.erros_alocacao == []
    assert _aberto(depois, "7777") == D("250.00")     # reaberta
    reaberta = next(i for i in depois.itens if i.nf_numero == "7777")
    assert reaberta.total_manual == D("-250.00")     # credito: NEGATIVO na coluna
    _identidade_fecha(depois)


# --- LINHA_ABERTA: saldo anterior --------------------------------------------

def test_alocacao_para_o_saldo_anterior_consome_o_nao_detalhado():
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "500.00", 10),
                    (PAGAMENTO, "300.00", "0.00", 20)],
                   saldo_anterior="-1000.00")
    antes = _res(conta)
    assert _aberto(antes, "(anterior)") == D("1000.00")

    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo=ALVO_ANTERIOR))
    assert _aberto(depois, "(anterior)") == D("700.00")
    assert _aberto(depois, "7777") == D("500.00")     # intacta
    assert depois.balde == []
    anterior = next(i for i in depois.itens if i.nf_numero == ALVO_ANTERIOR)
    assert anterior.valor_compra == D("1000.00")      # saldo trazido
    assert anterior.total_manual == D("300.00")       # no campo proprio...
    assert anterior.total_pago == D("0.00")           # ... nunca dentro do pago
    _identidade_fecha(depois)


# --- erros: item fica no balde, identidade continua fechando -----------------

@pytest.mark.parametrize("alvo,codigo", [
    ("0000", "NF_INEXISTENTE"),
    ("", "ALVO_AUSENTE"),
])
def test_alvo_invalido_vira_erro_explicito_e_o_item_fica_no_balde(alvo, codigo):
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo=alvo))
    assert [c for c, _ in _erros(depois)] == [codigo]
    assert len(depois.balde) == 1                     # nao sumiu em silencio
    assert depois.decisoes == []
    _identidade_fecha(depois)


def test_nf_ja_quitada_recusa_debito():
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Valor ref. a Pgto a FORN NF 7777", "1000.00", "0.00", 15),
                    (PAGAMENTO, "300.00", "0.00", 20)])
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L3"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    codigo, mensagem = _erros(depois)[0]
    assert codigo == "NF_QUITADA"
    assert "7777" in mensagem
    assert len(depois.balde) == 1
    _identidade_fecha(depois)


def test_saldo_anterior_ja_detalhado_recusa_debito():
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "500.00", 10),
                    (PAGAMENTO, "300.00", "0.00", 20),
                    (PAGAMENTO, "300.00", "0.00", 25)],
                   saldo_anterior="-300.00")
    antes = _res(conta)
    primeira = AlocacaoManual(item_id=_item_id(antes, "L2"),
                              destino=DestinoAlocacao.LINHA_ABERTA,
                              alvo=ALVO_ANTERIOR)
    segunda = AlocacaoManual(item_id=_item_id(antes, "L3"),
                             destino=DestinoAlocacao.LINHA_ABERTA,
                             alvo=ALVO_ANTERIOR)
    depois = _res(conta, primeira, segunda)
    assert [c for c, _ in _erros(depois)] == ["ANTERIOR_QUITADO"]
    assert len(depois.decisoes) == 1                  # a primeira valeu
    assert len(depois.balde) == 1                     # a segunda ficou


def test_item_inexistente_vira_erro_explicito():
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    depois = _res(conta, AlocacaoManual(item_id="naoexiste00",
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    codigo, _ = _erros(depois)[0]
    assert codigo == "ITEM_INEXISTENTE"
    assert len(depois.balde) == 1


def test_duas_alocacoes_para_o_mesmo_item_recusam_a_segunda():
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    antes = _res(conta)
    item = _item_id(antes, "L2")
    depois = _res(conta,
                  AlocacaoManual(item_id=item,
                                 destino=DestinoAlocacao.LINHA_ABERTA, alvo="7777"),
                  AlocacaoManual(item_id=item,
                                 destino=DestinoAlocacao.LINHA_ABERTA, alvo="7777"))
    assert [c for c, _ in _erros(depois)] == ["ITEM_JA_ALOCADO"]
    assert _aberto(depois, "7777") == D("700.00")     # aplicada UMA vez so
    assert len(depois.decisoes) == 1


# --- COMPRA_NOVA --------------------------------------------------------------

def _credito_no_balde():
    """NF de 1.000,00 aberta e um CREDITO de 250,00 que o motor nao reconhece.

    O exemplo era a transferencia de saldos, que passou a ter padrao
    proprio (decisao de produto). Trocado pelo RECEBIMENTO PIX, que continua sem
    padrao por decisao de produto ("tem subjetividade neste tipo de
    operacao", analise humana) — o que estes testes precisam e' um credito que
    o motor nao reconhece, e esse papel agora e' do PIX."""
    return _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                   ("Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO",
                    "0.00", "250.00", 20)])


def test_compra_nova_vira_linha_propria_da_composicao():
    conta = _credito_no_balde()
    antes = _res(conta)
    assert len(antes.balde) == 1

    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.COMPRA_NOVA,
                                        rotulo="NF 12345 nao lancada"))
    assert depois.erros_alocacao == []
    linha = next(i for i in depois.itens if i.origem is Origem.ALOCACAO_MANUAL)
    assert linha.nf_numero == "NF 12345 nao lancada"
    assert linha.valor_compra == D("250.00")
    assert linha.saldo_aberto == D("250.00")
    assert linha.data_compra == date(2026, 1, 20)      # data do proprio lancamento
    assert depois.balde == []
    check = _identidade_fecha(depois)
    assert check.nivel is Nivel.OK


def test_compra_nova_sem_rotulo_se_identifica_pelo_lote():
    conta = _credito_no_balde()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.COMPRA_NOVA))
    linha = next(i for i in depois.itens if i.origem is Origem.ALOCACAO_MANUAL)
    assert "L2" in linha.nf_numero


def test_debito_nao_pode_virar_compra_nova():
    """Geraria linha de composicao com valor de compra NEGATIVO. Debito vai pra
    linha aberta ou pra fora da composicao."""
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.COMPRA_NOVA,
                                        rotulo="tentativa"))
    codigo, mensagem = _erros(depois)[0]
    assert codigo == "DESTINO_INCOMPATIVEL"
    assert "débito" in mensagem
    assert len(depois.balde) == 1
    assert not any(i.origem is Origem.ALOCACAO_MANUAL for i in depois.itens)
    _identidade_fecha(depois)


def test_linha_criada_a_mao_pode_receber_pagamento_a_mao():
    """Composicao dos destinos: cria a NF que faltava e quita ela — o caso de
    'a NF nao esta na razao, mas o pagamento esta'."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO",
                     "0.00", "250.00", 20),
                    (PAGAMENTO, "150.00", "0.00", 25)])
    antes = _res(conta)
    nova = AlocacaoManual(item_id=_item_id(antes, "L2"),
                          destino=DestinoAlocacao.COMPRA_NOVA, rotulo="NF 999")
    quita = AlocacaoManual(item_id=_item_id(antes, "L3"),
                           destino=DestinoAlocacao.LINHA_ABERTA, alvo="NF 999")
    depois = _res(conta, nova, quita)
    assert depois.erros_alocacao == []
    assert _aberto(depois, "NF 999") == D("100.00")
    assert depois.balde == []
    _identidade_fecha(depois)


# --- FORA_DA_COMPOSICAO -------------------------------------------------------

def test_fora_da_composicao_registra_decisao_e_deixa_ressalva():
    conta = _credito_no_balde()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(
        item_id=_item_id(antes, "L2"),
        destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
        rotulo="lancamento e de outra conta do mesmo fornecedor"))

    assert depois.balde == []
    assert depois.erros_alocacao == []
    assert not any(i.origem is Origem.ALOCACAO_MANUAL for i in depois.itens)
    decisao = depois.decisoes[0]
    assert decisao.destino is DestinoAlocacao.FORA_DA_COMPOSICAO
    assert decisao.rotulo.startswith("lancamento e de outra conta")
    assert decisao.valor == D("-250.00")

    # a composicao passa a diferir do Dominio EXATAMENTE pelo que saiu
    ressalva = next(a for a in depois.achados
                    if a.codigo == "composicao_com_ressalva")
    assert ressalva.nivel is Nivel.INCOMPLETO
    assert ressalva.encontrado == D("-250.00")
    assert ressalva.valores["itens"] == 1
    # e a identidade generalizada continua exata
    check = next(a for a in depois.achados if a.codigo == "self_check_composicao")
    assert check.esperado == check.encontrado
    assert check.nivel is not Nivel.ERRO


def test_fora_da_composicao_exige_justificativa():
    """O rotulo vai pro cliente na secao de decisoes: decisao sem motivo nao
    serve de entrega."""
    conta = _credito_no_balde()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(
        item_id=_item_id(antes, "L2"),
        destino=DestinoAlocacao.FORA_DA_COMPOSICAO))
    codigo, _ = _erros(depois)[0]
    assert codigo == "ROTULO_OBRIGATORIO"
    assert len(depois.balde) == 1
    assert depois.decisoes == []


def test_sem_itens_fora_nao_ha_ressalva():
    conta = _uma_nf_aberta_e_um_pagamento_solto()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L2"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    assert not any(a.codigo == "composicao_com_ressalva" for a in depois.achados)


def test_balde_e_ressalva_convivem_na_mesma_identidade():
    """Um item fora, outro ainda no balde: gap == balde + fora, ao centavo."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO",
                     "0.00", "250.00", 20),
                    (PAGAMENTO, "300.00", "0.00", 25)])
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(
        item_id=_item_id(antes, "L2"),
        destino=DestinoAlocacao.FORA_DA_COMPOSICAO, rotulo="outra conta"))
    assert len(depois.balde) == 1
    check = next(a for a in depois.achados if a.codigo == "self_check_composicao")
    assert check.nivel is Nivel.INCOMPLETO
    assert check.esperado == check.encontrado         # balde + fora == gap


# --- juros de ORIGEM MANUAL ---------------------------------------------------

def _nf_com_saldo_pequeno_e_um_pagamento_grande():
    """NF de 1.000,00 com 900,00 ja pagos por numero (100,00 em aberto) e um
    pagamento solto de 300,00 no balde: alocar estoura o titulo em 200,00."""
    return _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                   ("Valor ref. a Pgto a FORN NF 7777", "900.00", "0.00", 15),
                   (PAGAMENTO, "300.00", "0.00", 20)])


def test_estouro_por_alocacao_manual_alerta_com_origem_manual():
    """Forma de um caso (174.200,00 na NF 41592, que tem 174.000,00 em
    aberto): o estouro PASSA e alerta — mas nunca se confunde com juros que o
    motor detectou sozinho."""
    conta = _nf_com_saldo_pequeno_e_um_pagamento_grande()
    antes = _res(conta)
    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L3"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    assert depois.erros_alocacao == []
    assert _aberto(depois, "7777") == D("-200.00")

    codigos = [a.codigo for a in depois.achados]
    assert "possivel_juros_manual" in codigos
    assert "possivel_juros" not in codigos          # nunca os dois, nunca o errado
    achado = next(a for a in depois.achados if a.codigo == "possivel_juros_manual")
    assert achado.nivel is Nivel.ALERTA
    assert achado.valores["diferenca"] == D("200.00")
    assert "7777" in achado.mensagem


def test_juros_detectado_pelo_motor_continua_com_o_codigo_de_sempre():
    """Regressao: sem alocacao manual na NF, o alerta e o automatico."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Valor ref. a Pgto a FORN NF 7777", "1200.00", "0.00", 15)])
    res = _res(conta)
    codigos = [a.codigo for a in res.achados]
    assert "possivel_juros" in codigos
    assert "possivel_juros_manual" not in codigos


# --- determinismo -------------------------------------------------------------

def test_desfazer_e_identico_a_rodar_sem_a_alocacao():
    """Desfazer nao 'reverte' nada: o motor reroda do zero com a lista menor."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    (COMPRA.format(nf="8888"), "0.00", "2000.00", 11),
                    (PAGAMENTO, "300.00", "0.00", 20),
                    (PAGAMENTO, "700.00", "0.00", 21)],
                   saldo_anterior="0.00")
    antes = _res(conta)
    a1 = AlocacaoManual(item_id=_item_id(antes, "L3"),
                        destino=DestinoAlocacao.LINHA_ABERTA, alvo="7777")
    a2 = AlocacaoManual(item_id=_item_id(antes, "L4"),
                        destino=DestinoAlocacao.LINHA_ABERTA, alvo="8888")

    com_as_duas = _res(conta, a1, a2)
    desfeita = _res(conta, a1)
    assert desfeita == _res(conta, a1)                # deterministico
    assert _aberto(com_as_duas, "8888") == D("1300.00")
    assert _aberto(desfeita, "8888") == D("2000.00")
    assert len(desfeita.balde) == 1
    _identidade_fecha(desfeita)


def test_desfazer_a_alocacao_que_criou_a_linha_degrada_a_que_dependia_dela():
    """CASCATA DO DESFAZER: a alocacao B quita a linha que a alocacao A criou.
    Desfazer A (rerodar sem ela) tem que degradar B pra NF_INEXISTENTE, com o
    item de B DE VOLTA ao balde — sem crash, sem silencio, identidade fechando.

    E o risco proprio do modelo "reroda do zero": nada reverte nada, entao a
    dependencia entre alocacoes so aparece na reexecucao."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO",
                     "0.00", "250.00", 20),
                    (PAGAMENTO, "150.00", "0.00", 25)])
    antes = _res(conta)
    cria = AlocacaoManual(item_id=_item_id(antes, "L2"),
                          destino=DestinoAlocacao.COMPRA_NOVA, rotulo="NF 999")
    quita = AlocacaoManual(item_id=_item_id(antes, "L3"),
                           destino=DestinoAlocacao.LINHA_ABERTA, alvo="NF 999")

    com_as_duas = _res(conta, cria, quita)
    assert com_as_duas.erros_alocacao == []
    assert com_as_duas.balde == []

    # desfaz A: B perde o alvo
    sem_a = _res(conta, quita)
    codigo, mensagem = _erros(sem_a)[0]
    assert codigo == "NF_INEXISTENTE"
    assert "NF 999" in mensagem
    assert [i.lancamentos[0].numero for i in sem_a.balde] == ["L2", "L3"]
    assert sem_a.decisoes == []
    assert not any(i.origem is Origem.ALOCACAO_MANUAL for i in sem_a.itens)
    _identidade_fecha(sem_a)

    # e o estado degradado e o MESMO de nunca ter alocado nada (fora o erro)
    assert ([i.saldo_aberto for i in sem_a.itens]
            == [i.saldo_aberto for i in antes.itens])


def test_desfazer_pode_tambem_reabilitar_a_alocacao_seguinte():
    """O espelho da cascata: A quitava a NF inteira e B era recusada por
    NF_QUITADA; sem A, B passa a valer. O motor nao guarda memoria de erro —
    cada execucao julga do zero."""
    # valores que o motor NAO casa sozinho (1.200 e 600 nao sao parcela de
    # 1.000): os dois ficam no balde e so a mao os move
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    (PAGAMENTO, "1200.00", "0.00", 20),
                    (PAGAMENTO, "600.00", "0.00", 25)])
    antes = _res(conta)
    a = AlocacaoManual(item_id=_item_id(antes, "L2"),
                       destino=DestinoAlocacao.LINHA_ABERTA, alvo="7777")
    b = AlocacaoManual(item_id=_item_id(antes, "L3"),
                       destino=DestinoAlocacao.LINHA_ABERTA, alvo="7777")

    com_as_duas = _res(conta, a, b)
    assert [c for c, _ in _erros(com_as_duas)] == ["NF_QUITADA"]

    sem_a = _res(conta, b)
    assert sem_a.erros_alocacao == []
    assert _aberto(sem_a, "7777") == D("400.00")
    assert [i.lancamentos[0].numero for i in sem_a.balde] == ["L2"]
    _identidade_fecha(sem_a)


def test_ordem_das_alocacoes_nao_muda_o_resultado_quando_sao_independentes():
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    (COMPRA.format(nf="8888"), "0.00", "2000.00", 11),
                    (PAGAMENTO, "300.00", "0.00", 20),
                    (PAGAMENTO, "700.00", "0.00", 21)])
    antes = _res(conta)
    a1 = AlocacaoManual(item_id=_item_id(antes, "L3"),
                        destino=DestinoAlocacao.LINHA_ABERTA, alvo="7777")
    a2 = AlocacaoManual(item_id=_item_id(antes, "L4"),
                        destino=DestinoAlocacao.LINHA_ABERTA, alvo="8888")
    direta = _res(conta, a1, a2)
    invertida = _res(conta, a2, a1)
    assert {i.nf_numero: i.saldo_aberto for i in direta.itens} == \
           {i.nf_numero: i.saldo_aberto for i in invertida.itens}


# --- as quitadas sao canal proprio do resultado --------------------

def test_conferir_devolve_as_quitadas_separadas_da_composicao():
    conta = _conta([(COMPRA.format(nf="8888"), "0.00", "500.00", 5),
                    ("Valor ref. a Pgto a FORN NF 8888", "500.00", "0.00", 8),
                    (COMPRA.format(nf="7777"), "0.00", "1000.00", 10)])
    res = _res(conta)
    assert [i.nf_numero for i in res.itens] == ["7777"]          # so' o aberto
    (quitada,) = res.quitadas
    assert quitada.nf_numero == "8888"
    assert quitada.saldo_aberto == D("0.00")
    assert quitada.total_pago == D("500.00")
    _identidade_fecha(res)


def test_alocacao_ate_zero_move_a_nf_das_abertas_para_as_quitadas():
    """A NF que o contador quita a mao ate zero sai da composicao e entra nas
    quitadas COM a marca (total_manual, quitacoes_manuais): a foto completa
    conta a decisao dele do mesmo jeito que a tabela aberta contava."""
    # A 8888 fica em aberto so' pra o saldo nunca zerar -- sem ela, o
    # debito de 300,00 zeraria a conta e o corte por saldo zero tiraria a 7777
    # da composicao ANTES da alocacao (o cenario aqui e' a alocacao)
    conta = _conta([(COMPRA.format(nf="8888"), "0.00", "50.00", 5),
                    (COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Valor ref. a Pgto a FORN NF 7777", "700.00", "0.00", 15),
                    ("Debito de ALGO QUE O MOTOR NAO RECONHECE", "300.00", "0.00", 20)])
    antes = _res(conta)
    assert _aberto(antes, "7777") == D("300.00")
    assert antes.quitadas == []

    depois = _res(conta, AlocacaoManual(item_id=_item_id(antes, "L4"),
                                        destino=DestinoAlocacao.LINHA_ABERTA,
                                        alvo="7777"))
    assert depois.erros_alocacao == []
    assert [i.nf_numero for i in depois.itens] == ["8888"]      # a 7777 saiu
    (quitada,) = depois.quitadas
    assert quitada.nf_numero == "7777"
    assert quitada.total_pago == D("700.00")
    assert quitada.total_manual == D("300.00")
    assert quitada.quitacoes_manuais == 1
    assert quitada.data_ultima_quitacao == date(2026, 1, 20)
    check = _identidade_fecha(depois)
    assert check.nivel is Nivel.OK


def test_linha_criada_a_mao_e_quitada_a_mao_aparece_nas_quitadas():
    """A perna que um teste de mutacao revelou descoberta: `aplicar()` muta as
    NFs compartilhadas, entao ler as quitadas de `resultado.nfs` em vez de
    `manual.nfs` so' erra pra NF que NAO existia antes das alocacoes — a linha
    criada a mao. Criada e quitada ate zero, ela tem que estar na foto completa
    com a origem e a marca."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO",
                     "0.00", "250.00", 20),
                    ("Debito de ALGO QUE O MOTOR NAO RECONHECE", "250.00", "0.00", 25)])
    antes = _res(conta)
    nova = AlocacaoManual(item_id=_item_id(antes, "L2"),
                          destino=DestinoAlocacao.COMPRA_NOVA, rotulo="NF 999")
    quita = AlocacaoManual(item_id=_item_id(antes, "L3"),
                           destino=DestinoAlocacao.LINHA_ABERTA, alvo="NF 999")
    depois = _res(conta, nova, quita)
    assert depois.erros_alocacao == []
    assert [i.nf_numero for i in depois.itens] == ["7777"]       # a criada fechou
    (quitada,) = depois.quitadas
    assert quitada.nf_numero == "NF 999"
    assert quitada.origem is Origem.ALOCACAO_MANUAL
    assert quitada.valor_compra == D("250.00")
    assert quitada.total_manual == D("250.00")
    assert quitada.saldo_aberto == D("0.00")
    _identidade_fecha(depois)


# === o nome de uma linha nova nao pode ser de outra linha ========
# O alvo de uma linha e o NOME dela: duas com o mesmo nome e a alocacao seguinte
# cai na primeira (a NF da razao vem antes da criada), nao na escolhida.

INTEGRA = Path(__file__).parent / "fixtures" / "sintetica_integra.xls"


def _cenario_integra(nome):
    """Na sintetica_integra: cria uma compra nova com `nome` a partir do credito do
    balde e, SE a linha existir no seletor, aplica nela o debito do balde.
    Devolve (base, depois_da_compra, depois_do_debito, opcao_da_linha_criada)."""
    from app.destinos import opcoes_de_alocacao
    from app.pipeline import processar_excel
    base = processar_excel(str(INTEGRA)).resultados[0]
    codigo = base.conta.codigo
    credito = next(i for i in base.balde if i.lancamentos[0].credito > 0)
    debito = next(i for i in base.balde if i.lancamentos[0].debito > 0)
    compra = AlocacaoManual(item_id=credito.identificador,
                            destino=DestinoAlocacao.COMPRA_NOVA, rotulo=nome)
    r1 = processar_excel(str(INTEGRA), {codigo: [compra]}).resultados[0]
    criada = next((o for o in opcoes_de_alocacao(r1.itens, debito.lancamentos[0].debito)
                   if "criada nesta sessão" in o.rotulo), None)
    if criada is None:
        return base, r1, r1, None
    no_debito = AlocacaoManual(item_id=debito.identificador, destino=criada.destino,
                               alvo=criada.alvo)
    r2 = processar_excel(str(INTEGRA), {codigo: [compra, no_debito]}).resultados[0]
    return base, r1, r2, criada


def _linhas_da_razao(res):
    return sorted((i.nf_numero, str(i.saldo_aberto)) for i in res.itens
                  if i.origem is Origem.COMPRA_PERIODO)


def test_compra_nova_com_o_nome_de_uma_nf_da_razao_e_recusada_e_a_nf_fica_intacta():
    from app.pipeline import processar_excel
    nf = next(i for i in processar_excel(str(INTEGRA)).resultados[0].itens
              if i.origem is Origem.COMPRA_PERIODO and i.saldo_aberto > 0)
    base, r1, r2, criada = _cenario_integra(nf.nf_numero)
    assert [e.codigo for e in r1.erros_alocacao] == ["NOME_EM_USO"]
    assert criada is None                                   # a linha nao foi criada
    assert not any(i.origem is Origem.ALOCACAO_MANUAL for i in r2.itens)
    assert _linhas_da_razao(r2) == _linhas_da_razao(base)   # nenhum valor desviado
    assert len(r2.balde) == len(base.balde)                 # o item segue no balde
    identidade_da_tabela(r2.itens)


def test_a_mensagem_do_erro_cita_o_nome_e_diz_o_fato():
    from app.pipeline import processar_excel
    nf = next(i for i in processar_excel(str(INTEGRA)).resultados[0].itens
              if i.origem is Origem.COMPRA_PERIODO and i.saldo_aberto > 0)
    _, r1, _, _ = _cenario_integra(nf.nf_numero)
    (erro,) = r1.erros_alocacao
    assert erro.mensagem == (f"o nome {nf.nf_numero} já é de uma linha desta conta; "
                             f"a alocação ficou sem efeito")


@pytest.mark.parametrize("nome", [ALVO_ANTERIOR, "(alocação manual: saldo anterior)"])
def test_nomes_reservados_do_saldo_anterior_nao_viram_nome_de_linha_nova(nome):
    base, r1, r2, criada = _cenario_integra(nome)
    assert [e.codigo for e in r1.erros_alocacao] == ["NOME_EM_USO"]
    assert criada is None


def test_nome_livre_e_aceito_e_o_debito_cai_na_linha_criada():
    """CONTROLE: o caminho de sempre."""
    base, r1, r2, criada = _cenario_integra("LINHA NOVA X")
    assert r1.erros_alocacao == [] and criada is not None
    assert r2.erros_alocacao == []
    criadas = [(i.nf_numero, str(i.saldo_aberto)) for i in r2.itens
               if i.origem is Origem.ALOCACAO_MANUAL]
    assert criadas == [("LINHA NOVA X", "100.00")]
    assert _linhas_da_razao(r2) == _linhas_da_razao(base)   # NF da razao intacta


def test_nome_em_branco_usa_o_padrao_do_lote_e_e_aceito():
    """CONTROLE: sem nome, '(manual: lote N)'."""
    base, r1, r2, criada = _cenario_integra("")
    assert r1.erros_alocacao == [] and criada is not None
    assert [i.nf_numero for i in r2.itens
            if i.origem is Origem.ALOCACAO_MANUAL][0].startswith("(manual: lote")
    assert _linhas_da_razao(r2) == _linhas_da_razao(base)


def test_duas_compras_novas_com_o_mesmo_nome_a_segunda_e_recusada():
    """linha criada x linha criada: o nome tambem e' unico entre as criadas."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("TARIFA A", "0.00", "250.00", 20),
                    ("TARIFA B", "0.00", "300.00", 21)])
    antes = _res(conta)
    ids = [i.identificador for i in antes.balde]
    assert len(ids) == 2
    depois = _res(conta,
                  AlocacaoManual(item_id=ids[0], destino=DestinoAlocacao.COMPRA_NOVA,
                                 rotulo="LINHA X"),
                  AlocacaoManual(item_id=ids[1], destino=DestinoAlocacao.COMPRA_NOVA,
                                 rotulo="LINHA X"))
    assert [e.codigo for e in depois.erros_alocacao] == ["NOME_EM_USO"]
    assert len([i for i in depois.itens if i.origem is Origem.ALOCACAO_MANUAL]) == 1
    assert len(depois.balde) == 1                           # o 2o item segue no balde
    _identidade_fecha(depois)


def test_o_nome_padrao_do_lote_tambem_nao_pode_repetir_um_nome_em_uso():
    """O nome que vale e' o FINAL: sem rotulo, '(manual: lote N)' entra na mesma
    checagem. Aqui o 1o item toma o nome padrao do 2o."""
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("TARIFA A", "0.00", "250.00", 20),
                    ("TARIFA B", "0.00", "300.00", 21)])
    antes = _res(conta)
    por_lote = {i.lancamentos[0].numero: i.identificador for i in antes.balde}
    assert set(por_lote) == {"L2", "L3"}
    depois = _res(conta,
                  AlocacaoManual(item_id=por_lote["L2"], destino=DestinoAlocacao.COMPRA_NOVA,
                                 rotulo="(manual: lote L3)"),
                  AlocacaoManual(item_id=por_lote["L3"], destino=DestinoAlocacao.COMPRA_NOVA))
    assert [e.codigo for e in depois.erros_alocacao] == ["NOME_EM_USO"]
    assert [i.nf_numero for i in depois.itens
            if i.origem is Origem.ALOCACAO_MANUAL] == ["(manual: lote L3)"]


def test_nome_repetido_em_minuscula_tambem_e_recusado_e_nomes_que_so_diferem_na_caixa_sao_outros():
    conta = _conta([(COMPRA.format(nf="7777"), "0.00", "1000.00", 10),
                    ("TARIFA A", "0.00", "250.00", 20),
                    ("TARIFA B", "0.00", "300.00", 21)])
    ids = [i.identificador for i in _res(conta).balde]

    def com(r1, r2):
        return _res(conta,
                    AlocacaoManual(item_id=ids[0], destino=DestinoAlocacao.COMPRA_NOVA, rotulo=r1),
                    AlocacaoManual(item_id=ids[1], destino=DestinoAlocacao.COMPRA_NOVA, rotulo=r2))
    assert [e.codigo for e in com("linha x", "linha x").erros_alocacao] == ["NOME_EM_USO"]
    # o alvo da alocacao e' comparado EXATO: "Linha X" e "LINHA X" sao dois nomes
    assert com("Linha X", "LINHA X").erros_alocacao == []

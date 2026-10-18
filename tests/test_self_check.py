"""Self-check de parsing da razao.

Golden: tests/fixtures/golden_sintetico.xls (empresa e fornecedor ficticios).
Prova que a gente LE a razao certo ANTES de interpretar qualquer coisa.

Os 3 checks oficiais (golden do self-check, NAO mexer):
  1. soma dos debitos lidos   == "Total da conta" debito  == 3269.20
  2. soma dos creditos lidos  == "Total da conta" credito == 7100.03
  3. saldo recalculado (saldo_anterior + Sdeb - Scred) == saldo da
     ultima linha de lancamento == -4260.09

4o check (robustez extra, decisao de produto): saldo corrente linha-a-linha.
Sinaliza com ALERTA, NUNCA com ERRO. No Excel nada rejeita o parse
(rejeicao e portao de PDF).
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.modelo import Conta, ItemRevisao, Lancamento, MotivoRevisao, Nivel
from core.veredito import self_check_composicao, self_check_parsing
from parser.excel import ExcelParser

FIXTURE = Path(__file__).parent / "fixtures" / "golden_sintetico.xls"


@pytest.fixture
def contas():
    return ExcelParser().parse(FIXTURE)


# --- parsing: estrutura lida do arquivo ------------------------------------

def test_parse_estrutura_basica(contas):
    assert len(contas) == 1
    c = contas[0]
    assert c.codigo == "5218"
    assert c.classificacao == "2.01.01.03.500"
    assert c.nome == "FERRAMENTAS FICTICIAS COMERCIO SA"
    assert c.saldo_anterior == Decimal("-429.26")        # negativo = credor
    assert len(c.lancamentos) == 12
    assert c.total_debito_dominio == Decimal("3269.20")
    assert c.total_credito_dominio == Decimal("7100.03")


def test_parse_mapeia_colunas_certas(contas):
    # prova que debito/credito/cta_part/saldo nao trocaram de coluna,
    # que celula vazia vira 0.00, e que historico e' lido CRU (sem regex de NF)
    c = contas[0]
    primeiro = c.lancamentos[0]                            # L10: pagamento
    assert primeiro.debito == Decimal("214.63")
    assert primeiro.credito == Decimal("0.00")
    assert primeiro.saldo_exercicio == Decimal("-214.63")
    assert primeiro.cta_part == "7311"
    assert primeiro.historico.startswith("- PAGTO REF. NF.:")
    assert isinstance(primeiro.data, date)                 # serial convertido, nao float cru

    compra = c.lancamentos[2]                              # L12: primeira compra (credito)
    assert compra.credito == Decimal("4700.00")
    assert compra.debito == Decimal("0.00")


# --- os 3 self-checks oficiais ---------------------------------------------

def test_self_check_soma_debitos(contas):
    c = contas[0]
    soma = sum((l.debito for l in c.lancamentos), Decimal("0"))
    assert soma == Decimal("3269.20")
    assert soma == c.total_debito_dominio


def test_self_check_soma_creditos(contas):
    c = contas[0]
    soma = sum((l.credito for l in c.lancamentos), Decimal("0"))
    assert soma == Decimal("7100.03")
    assert soma == c.total_credito_dominio


def test_self_check_saldo_recalculado(contas):
    c = contas[0]
    deb = sum((l.debito for l in c.lancamentos), Decimal("0"))
    cred = sum((l.credito for l in c.lancamentos), Decimal("0"))
    recalc = c.saldo_anterior + deb - cred
    assert recalc == Decimal("-4260.09")
    assert recalc == c.lancamentos[-1].saldo_exercicio


# --- veredito: golden limpo passa tudo verde -------------------------------

def test_veredito_golden_tudo_ok(contas):
    achados = self_check_parsing(contas[0])
    codigos = {a.codigo for a in achados}
    assert {
        "self_check_total_debito",
        "self_check_total_credito",
        "self_check_saldo_final",
        "self_check_saldo_corrente",
    } <= codigos
    assert {a.nivel for a in achados} == {Nivel.OK}        # nada de ERRO nem ALERTA no golden


# --- 4o check: linha-a-linha sinaliza ALERTA, nunca ERRO -------------------

def test_quarto_check_saldo_corrente_alerta_sem_erro():
    # saldo intermediario quebrado de proposito; totais e saldo final
    # permanecem corretos -> os 3 oficiais passam (sem ERRO), mas o passo
    # a passo flagra a inconsistencia como ALERTA.
    lancs = [
        Lancamento(data=date(2025, 1, 1), numero="1", historico="credito 100",
                   cta_part="x", debito=Decimal("0.00"), credito=Decimal("100.00"),
                   saldo_exercicio=Decimal("-50.00")),    # ERRADO: deveria ser -100.00
        Lancamento(data=date(2025, 1, 2), numero="2", historico="nada",
                   cta_part="x", debito=Decimal("0.00"), credito=Decimal("0.00"),
                   saldo_exercicio=Decimal("-100.00")),   # final correto
    ]
    conta = Conta(codigo="9999", classificacao="t", nome="TESTE",
                  saldo_anterior=Decimal("0.00"), lancamentos=lancs,
                  total_debito_dominio=Decimal("0.00"),
                  total_credito_dominio=Decimal("100.00"))

    achados = self_check_parsing(conta)
    niveis = [a.nivel for a in achados]
    assert Nivel.ERRO not in niveis                        # Excel nunca rejeita
    assert Nivel.ALERTA in niveis                          # passo a passo sinaliza
    alertas = [a for a in achados if a.nivel is Nivel.ALERTA]
    assert all(a.codigo == "self_check_saldo_corrente" for a in alertas)


def test_mensagem_do_saldo_corrente_cita_o_lote_e_nao_um_indice_de_linha():
    """A mensagem dizia "linha 2": era o indice 0-based do lancamento (contando a
    ancora), que nao e' a linha da planilha. O lote identifica a linha."""
    lancs = [
        Lancamento(data=date(2025, 1, 1), numero="5002", historico="credito 100",
                   cta_part="x", debito=Decimal("0.00"), credito=Decimal("100.00"),
                   saldo_exercicio=Decimal("-50.00")),    # ERRADO: deveria ser -100.00
        Lancamento(data=date(2025, 1, 2), numero="5003", historico="nada",
                   cta_part="x", debito=Decimal("0.00"), credito=Decimal("0.00"),
                   saldo_exercicio=Decimal("-100.00")),
    ]
    conta = Conta(codigo="9999", classificacao="t", nome="TESTE",
                  saldo_anterior=Decimal("0.00"), lancamentos=lancs,
                  total_debito_dominio=Decimal("0.00"),
                  total_credito_dominio=Decimal("100.00"))
    mensagens = [a.mensagem for a in self_check_parsing(conta)
                 if a.nivel is Nivel.ALERTA]
    # o saldo errado desloca a conta inteira: a 1a linha e a seguinte acusam
    assert mensagens == ["saldo corrente do lote 5002 não fecha",
                         "saldo corrente do lote 5003 não fecha"]
    assert not any("linha" in m for m in mensagens)


# --- self_check_composicao: a identidade gap == soma(D-C) do balde e' CONFERIDA
#     Balde que NAO explica o gap -> ERRO, nunca amarelo falso.

def _item_balde(debito="0.00", credito="0.00"):
    l = Lancamento(date(2025, 1, 1), "b", "x", "1",
                   Decimal(debito), Decimal(credito), Decimal("0.00"))
    return ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO)


def test_balde_que_nao_explica_o_gap_vira_erro():
    # gap = 0 - 500 = -500; balde soma so +100 -> sobra 600 sem explicacao.
    # hoje passa como INCOMPLETO amarelo saudavel; tem que virar ERRO.
    achados = self_check_composicao([], Decimal("-500.00"),
                                    (_item_balde(debito="100.00"),))
    erros = [a for a in achados
             if a.codigo == "self_check_composicao" and a.nivel is Nivel.ERRO]
    assert len(erros) == 1
    assert erros[0].esperado == Decimal("100.00")          # o que o balde explica
    assert erros[0].encontrado == Decimal("-500.00")       # o gap real
    assert not any(a.nivel is Nivel.INCOMPLETO for a in achados)  # nao mente amarelo


def test_balde_dentro_da_tolerancia_segue_incompleto():
    # gap -500 e balde soma -500 -> bate; INCOMPLETO como sempre
    # (guarda contra a Task 2 virar ERRO agressivo demais).
    achados = self_check_composicao([], Decimal("-500.00"),
                                    (_item_balde(credito="500.00"),))
    assert any(a.nivel is Nivel.INCOMPLETO for a in achados)
    assert not any(a.codigo == "self_check_composicao" and a.nivel is Nivel.ERRO
                   for a in achados)


# --- reconciliacao e alertas por item, separados (mesmo output) --------------

def _composicoes_de_campo():
    from app.pipeline import processar_excel
    from tests.helpers import GOLDEN
    sinteticas = GOLDEN.parent / "sintetica_integra.xls"
    return [processar_excel(c).resultados[0] for c in (GOLDEN, sinteticas)]


def test_self_check_composicao_e_reconciliar_mais_alertas_por_item():
    from core.veredito import alertas_por_item, reconciliar, self_check_composicao
    for res in _composicoes_de_campo():
        saldo, balde = res.conta.saldo_final, tuple(res.balde)
        assert (self_check_composicao(res.itens, saldo, balde)
                == reconciliar(res.itens, saldo, balde)
                + alertas_por_item(res.itens))
        assert all(a.codigo == "self_check_composicao" or
                   a.codigo in ("conta_devedora", "composicao_com_ressalva")
                   for a in reconciliar(res.itens, saldo, balde))


def test_alertas_do_periodo_zerado_nao_pedem_razao_anterior():
    """Pro corte por saldo zero: o anterior e a transferencia ja se compensaram
    no agregado; juros e desconto da NF continuam."""
    from core.modelo import ComposicaoItem, Origem
    from core.veredito import alertas_por_item
    anterior = ComposicaoItem("(anterior)", Origem.SALDO_ANTERIOR,
                              Decimal("500.00"), Decimal("0.00"),
                              Decimal("0.00"), Decimal("500.00"))
    juros = ComposicaoItem("5001", Origem.COMPRA_PERIODO, Decimal("1000.00"),
                           Decimal("1100.00"), Decimal("0.00"),
                           Decimal("-100.00"), qtd_quitacoes=1)
    com = [a.codigo for a in alertas_por_item([anterior, juros])]
    sem = [a.codigo for a in alertas_por_item([anterior, juros],
                                              nao_detalhados=False)]
    assert com == ["saldo_anterior_nao_detalhado", "possivel_juros"]
    assert sem == ["possivel_juros"]


@pytest.mark.parametrize("lado,palavra,total", [
    ("debito", "débitos", Decimal("18150.00")),
    ("credito", "créditos", Decimal("13250.00")),
])
@pytest.mark.parametrize("erro", [False, True], ids=["OK", "ERRO"])
def test_texto_exato_totais_core_e_valores(lado, palavra, total, erro):
    from dataclasses import replace
    c = ExcelParser().parse(Path(__file__).parent / "fixtures" / "sintetica_integra.xls")[0]
    esperado = total + Decimal("1000.00") if erro else total
    c = replace(c, **{f"total_{lado}_dominio": esperado})
    a = next(a for a in self_check_parsing(c) if a.codigo == f"self_check_total_{lado}")
    trecho = "NÃO confere" if erro else "confere"
    assert a.mensagem == f"soma dos {palavra} {trecho} com 'Total da conta'"
    assert a.nivel is (Nivel.ERRO if erro else Nivel.OK)
    assert a.esperado == esperado
    assert a.encontrado == total
    assert a.conta == "7777"

"""Orquestrador do core (conferir) + fonte unica do saldo final.

conferir(conta, classificador) encadeia classifica -> casar -> compor ->
self_check_parsing + self_check_composicao e devolve um ResultadoConferencia
(o bundle que a casca de UI renderiza). E client-agnostic: recebe o
classificador por parametro; o core NAO importa parser/.

Conta.saldo_final passa a ser a UNICA definicao de "qual e o saldo final"
(antes vivia escondida dentro de veredito._check_saldo_final). Uma fonte,
dois consumidores (o self-check e a tela).
"""
from datetime import date
from decimal import Decimal

from core.classifica import Classificacao, Tipo
from core.conferencia import conferir
from core.modelo import (
    Conta,
    Lancamento,
    Nivel,
    Origem,
    ResultadoConferencia,
)
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN as FIXTURE

# --- Conta.saldo_final: fonte unica de "qual e o saldo final" ---

def test_saldo_final_e_saldo_exercicio_da_ultima_linha():
    l1 = Lancamento(date(2025, 1, 1), "1", "h", "x",
                    Decimal("0.00"), Decimal("100.00"), Decimal("-100.00"))
    l2 = Lancamento(date(2025, 1, 2), "2", "h", "x",
                    Decimal("30.00"), Decimal("0.00"), Decimal("-70.00"))
    conta = Conta(codigo="C", classificacao="", nome="N", lancamentos=[l1, l2])
    assert conta.saldo_final == Decimal("-70.00")


def test_saldo_final_sem_lancamentos_cai_no_saldo_anterior():
    conta = Conta(codigo="C", classificacao="", nome="N",
                  saldo_anterior=Decimal("-500.00"))
    assert conta.saldo_final == Decimal("-500.00")


# --- conferir() reproduz o golden sintetico ao centavo ---

def _conferir_golden() -> ResultadoConferencia:
    conta = ExcelParser().parse(FIXTURE)[0]
    return conferir(conta, ClassificadorHistorico())


def test_conferir_reproduz_composicao_golden():
    res = _conferir_golden()
    por_nf = {i.nf_numero: i for i in res.itens}
    assert por_nf["618204"].saldo_aberto == Decimal("2820.00")
    assert por_nf["274591"].saldo_aberto == Decimal("1440.09")
    assert len(res.itens) == 2
    assert all(i.origem is Origem.COMPRA_PERIODO for i in res.itens)
    total = sum((i.saldo_aberto for i in res.itens), Decimal("0.00"))
    assert total == Decimal("4260.09")


def test_conferir_golden_veredito_fecha_sem_balde():
    res = _conferir_golden()
    assert res.balde == []
    # FECHA = nenhum ERRO nem INCOMPLETO entre TODOS os achados (parsing + composicao)
    assert not any(a.nivel is Nivel.ERRO for a in res.achados)
    assert not any(a.nivel is Nivel.INCOMPLETO for a in res.achados)
    comp = [a for a in res.achados if a.codigo == "self_check_composicao"]
    assert len(comp) == 1 and comp[0].nivel is Nivel.OK


def test_conferir_carrega_a_conta_no_resultado():
    res = _conferir_golden()
    assert res.conta.saldo_final == Decimal("-4260.09")


# --- client-agnostic: classificador injetado, core nao importa parser/ ---

class _ClassificadorNulo:
    """Tudo OUTRO: nenhuma compra/pagamento reconhecido."""
    def classificar(self, lanc) -> Classificacao:
        return Classificacao(Tipo.OUTRO)


def test_conferir_aceita_classificador_injetado():
    conta = ExcelParser().parse(FIXTURE)[0]
    res = conferir(conta, _ClassificadorNulo())
    # sem classificacao nenhuma compra e reconhecida -> nenhum item COMPRA_PERIODO
    assert all(i.origem is not Origem.COMPRA_PERIODO for i in res.itens)


# --- achados do casamento chegam na tela --------------------------

class _ClassificadorSerieFixa:
    """Toda linha de credito e compra da NF 9; todo debito e 'parcela 1 de 1'
    da NF 9 — forca a duplicidade pra provar que conferir() PROPAGA o achado."""
    def classificar(self, lanc) -> Classificacao:
        if lanc.credito > Decimal("0.00"):
            return Classificacao(Tipo.COMPRA, nf_numero="9")
        return Classificacao(Tipo.PAGAMENTO, nf_numero="9",
                             parcela=1, parcela_de=1)


def test_conferir_propaga_achados_do_casamento():
    lancs = [
        Lancamento(date(2025, 1, 1), "c1", "compra", "x",
                   Decimal("0.00"), Decimal("300.00"), Decimal("-300.00")),
        Lancamento(date(2025, 2, 1), "p1", "pgto", "x",
                   Decimal("100.00"), Decimal("0.00"), Decimal("-200.00")),
        Lancamento(date(2025, 3, 1), "p2", "pgto", "x",
                   Decimal("100.00"), Decimal("0.00"), Decimal("-100.00")),
    ]
    conta = Conta(codigo="C", classificacao="", nome="N", lancamentos=lancs)
    res = conferir(conta, _ClassificadorSerieFixa())
    assert any(a.codigo == "possivel_duplicidade" for a in res.achados)


# --- conta devedora: sinal do gap honesto + achado proprio ---

def test_conta_devedora_gap_com_sinal_certo_e_alerta():
    # pagamento (debito) sem compra -> conta DEVEDORA (saldo final POSITIVO).
    # o gap tem que sair +1.000,00 (== soma do balde), nao -1.000,00 (o abs
    # invertia o sinal); e a conta ganha um ALERTA proprio de saldo devedor.
    lanc = Lancamento(date(2025, 1, 10), "1", "TARIFA SEM PADRAO CONHECIDO", "x",
                      Decimal("1000.00"), Decimal("0.00"), Decimal("1000.00"))
    conta = Conta(codigo="7777", classificacao="", nome="FORN DEVEDOR",
                  lancamentos=[lanc])
    res = conferir(conta, _ClassificadorNulo())
    assert conta.saldo_final == Decimal("1000.00")            # devedora

    comp = [a for a in res.achados if a.codigo == "self_check_composicao"][0]
    soma_balde = sum((l.debito - l.credito
                      for it in res.balde for l in it.lancamentos), Decimal("0.00"))
    assert comp.encontrado == Decimal("1000.00")             # gap com sinal certo
    assert comp.encontrado == soma_balde                     # identidade fecha

    dev = [a for a in res.achados if a.codigo == "conta_devedora"]
    assert len(dev) == 1
    assert dev[0].nivel is Nivel.ALERTA
    assert dev[0].encontrado == Decimal("1000.00")


def test_conferir_expoe_as_nfs_do_pos_corte_e_do_periodo_zerado():
    """As NFs que o motor reconstruiu ficam no resultado -- e' de
    onde a invariante de lugar le em que linha cada lancamento terminou. Sao
    as MESMAS que a ponte recebe: pos-corte + periodo zerado."""
    res = _conferir_golden()
    assert sorted(nf.numero for nf in res.nfs) == ["274591", "512309", "618204"]
    por_numero = {nf.numero: nf for nf in res.nfs}
    assert por_numero["618204"].saldo_aberto == Decimal("2820.00")
    assert por_numero["512309"].data_compra is None     # NF anterior ao periodo

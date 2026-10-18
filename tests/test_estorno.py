"""Estorno x baixa: pareamento automatico (CASA), com prova propria.

Uma baixa lancada por engano e depois estornada e um par que se anula. O motor
fecha o par sozinho -- liquido zero, nada entra na composicao, o gap nao muda e
o balde encolhe de dois em dois.

Prova (nao inferencia): o historico DECLARA o que reverte, os valores sao
identicos e opostos, a contrapartida e a mesma e o estorno vem depois.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.casamento import casar
from core.classifica import Tipo
from core.conferencia import conferir
from core.modelo import Conta, ItemRevisao, MotivoRevisao, Nivel
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()

BAIXA = "Valor ref. a BAIXA DE ADIANTAMENTO - FORN FICTICIO"
ESTORNO = "Valor ref. estorno de  BAIXA DE ADIANTAMENTO indevida - FORN FICTICIO"
ESTORNO_GENERICO = "Valor ref. estorno de lancamento indevido - FORN FICTICIO"


def _casa(*lancamentos):
    return casar([(l, CLF.classificar(l)) for l in lancamentos])


def _motivos(balde):
    return [i.motivo for i in balde]


# --- roteamento no casamento -----------------------------------------------

def test_estorno_vai_pro_balde_com_motivo_proprio():
    """Chamar de "historico nao reconhecido" um historico que o motor acabou de
    reconhecer E classificar seria mentira na cara do conferente."""
    r = _casa(lanc(ESTORNO, numero="1", dia=5, credito="731.47"))
    assert _motivos(r.balde) == [MotivoRevisao.ESTORNO_SEM_PAR]
    assert "COMPRA" not in r.balde[0].mensagem
    assert "nao reconhecido" not in r.balde[0].mensagem


def test_estorno_generico_tambem_e_estorno_sem_par():
    r = _casa(lanc(ESTORNO_GENERICO, numero="1", dia=5, credito="500.00"))
    assert _motivos(r.balde) == [MotivoRevisao.ESTORNO_SEM_PAR]


def test_o_lancamento_do_estorno_chega_integro_ao_balde():
    """O historico e a evidencia: nunca some, nunca e truncado."""
    r = _casa(lanc(ESTORNO, numero="879102", dia=5, credito="731.47"))
    (l,) = r.balde[0].lancamentos
    assert l.historico == ESTORNO
    assert l.credito == D("731.47")


# --- pareamento: a matriz de RECUSA ----------------------------------------
# Um teste por condicao que impede o par. A regra so' fecha com TODAS
# satisfeitas: qualquer falha, ou 2+ candidatos, e os dois ficam no balde.

def _par(baixa_hist=BAIXA, estorno_hist=ESTORNO, valor="731.47",
         estorno_valor=None, dia_baixa=5, dia_estorno=20,
         cta_baixa="38", cta_estorno="38", estorno_no_debito=False):
    baixa = lanc(baixa_hist, numero="879101", dia=dia_baixa, debito=valor,
                 cta_part=cta_baixa)
    v = estorno_valor or valor
    estorno = lanc(estorno_hist, numero="879102", dia=dia_estorno,
                   cta_part=cta_estorno,
                   **({"debito": v} if estorno_no_debito else {"credito": v}))
    return baixa, estorno


def test_par_perfeito_sai_do_balde_junto():
    r = _casa(*_par())
    assert r.balde == []
    pareados = [a for a in r.achados if a.codigo == "estorno_pareado"]
    assert len(pareados) == 1
    assert pareados[0].nivel is Nivel.ALERTA
    # Os dois lotes do par viram DADO (coluna NF/Lote), na ordem em que
    # aconteceram: operacao, depois estorno
    assert pareados[0].referencia == "879101, 879102"


@pytest.mark.parametrize("kw,porque", [
    ({"estorno_valor": "731.48"}, "1 centavo de diferenca nao e estorno"),
    ({"estorno_no_debito": True}, "dois debitos: nada se anula"),
    ({"cta_estorno": "10"}, "contrapartida diferente: outra porta"),
    ({"dia_estorno": 1}, "estorno ANTES da baixa: nao se reverte o futuro"),
    ({"estorno_hist": ESTORNO_GENERICO}, "sem declaracao nao ha prova"),
    ({"baixa_hist": "Valor ref. a Pgto a FORN FICTICIO"},
     "parceiro de outro tipo: o estorno declara baixa, nao pagamento"),
])
def test_condicao_que_falha_mantem_os_dois_no_balde(kw, porque):
    r = _casa(*_par(**kw))
    assert len(r.balde) == 2, porque
    assert not [a for a in r.achados if a.codigo == "estorno_pareado"]


def test_duas_baixas_identicas_nao_desempatam():
    """2+ candidatos = ambiguo. Escolher uma seria chutar qual foi estornada."""
    baixa1 = lanc(BAIXA, numero="1", dia=5, debito="731.47", cta_part="38")
    baixa2 = lanc(BAIXA, numero="2", dia=6, debito="731.47", cta_part="38")
    estorno = lanc(ESTORNO, numero="3", dia=20, credito="731.47", cta_part="38")
    r = _casa(baixa1, baixa2, estorno)
    assert len(r.balde) == 3
    assert not [a for a in r.achados if a.codigo == "estorno_pareado"]


def test_dois_estornos_pra_uma_baixa_nao_pareiam():
    baixa = lanc(BAIXA, numero="1", dia=5, debito="731.47", cta_part="38")
    e1 = lanc(ESTORNO, numero="2", dia=20, credito="731.47", cta_part="38")
    e2 = lanc(ESTORNO, numero="3", dia=21, credito="731.47", cta_part="38")
    r = _casa(baixa, e1, e2)
    assert len(r.balde) == 3
    assert not [a for a in r.achados if a.codigo == "estorno_pareado"]


def test_parceiro_ja_conciliado_com_nf_nao_e_desfeito():
    """A baixa que casou por NUMERO ja esta na composicao. Desfazer isso seria
    mexer em dinheiro ja conciliado: o estorno fica sozinho no balde e o
    conferente decide."""
    compra = lanc("Vr. compras conf. 12345 FORN FICTICIO", numero="1", dia=1,
                  credito="731.47")
    baixa = lanc("Valor ref. a BAIXA DE ADIANTAMENTO NF 12345", numero="2",
                 dia=5, debito="731.47", cta_part="38")
    estorno = lanc(ESTORNO, numero="3", dia=20, credito="731.47", cta_part="38")
    r = _casa(compra, baixa, estorno)
    assert _motivos(r.balde) == [MotivoRevisao.ESTORNO_SEM_PAR]
    assert not [a for a in r.achados if a.codigo == "estorno_pareado"]


def test_o_par_nao_entra_em_nf_nenhuma():
    """Liquido zero: nenhum dos dois entra em NF, entao a composicao nao muda."""
    r = _casa(*_par())
    assert all(nf.qtd_quitacoes == 0 for nf in r.nfs)


def test_achado_carrega_a_evidencia_integral_dos_dois():
    """O par nao deixa linha na composicao: o achado e a UNICA resposta a
    "cade a baixa de 731,47?" — lotes, datas, valor e os DOIS historicos."""
    r = _casa(*_par())
    (achado,) = [a for a in r.achados if a.codigo == "estorno_pareado"]
    assert achado.valores["valor"] == D("731.47")
    assert [l.numero for l in achado.lancamentos] == ["879101", "879102"]
    assert [l.historico for l in achado.lancamentos] == [BAIXA, ESTORNO]


def test_estorno_no_MESMO_dia_da_baixa_nao_pareia():
    """Escolha explicita, nao acidente: no mesmo dia nada ordena os dois, e
    ordem inventada seria chute. O par fica no balde e o conferente decide —
    conservador, como o resto do motor."""
    baixa, estorno = _par(dia_baixa=5, dia_estorno=5)
    r = _casa(baixa, estorno)
    assert len(r.balde) == 2
    assert not [a for a in r.achados if a.codigo == "estorno_pareado"]


def test_item_com_dois_lancamentos_nao_pareia():
    """Condicao 0: item agregado (o um-pra-muitos) nao tem "o" valor nem
    "a" contrapartida pra comparar."""
    from core.estorno import parear

    baixa, estorno = _par()
    agregado = ItemRevisao(lancamentos=[baixa, baixa],
                           motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE)
    item_estorno = ItemRevisao(lancamentos=[estorno],
                               motivo=MotivoRevisao.ESTORNO_SEM_PAR)
    pares = [(l, CLF.classificar(l)) for l in (baixa, estorno)]
    restante, achados = parear([agregado, item_estorno], pares)
    assert len(restante) == 2
    assert achados == []


# --- cobertura de CI do caminho CASA ------------------------------------------
# A fixture sintetica cobre o ESTORNO_SEM_PAR (o estorno dela e de
# 500,00 contra uma baixa de 3.000,00, valores diferentes), mas nao o par
# FECHANDO. Sem este teste, o pareamento automatico do estorno nao teria prova no CI.

def _conta_com_par():
    """Uma razao minima com o par: compra em aberto, baixa indevida, estorno.
    Passa pelo classificador e pelo casamento de verdade — nada de mock."""
    return Conta(
        codigo="9000", classificacao="1.1", nome="FORNECEDOR TESTE FICTICIO",
        data_fim_periodo=date(2025, 12, 31),
        saldo_anterior=D("0.00"),
        # os totais do Dominio fecham com os lancamentos: sem eles o
        # self_check de PARSING acusa erro e mascara o que este teste mede
        total_debito_dominio=D("731.47"),
        total_credito_dominio=D("2731.47"),
        lancamentos=[
            lanc("Vr. compras conf. 12345 FORNECEDOR TESTE",
                 numero="100", dia=1, credito="2000.00", saldo="-2000.00"),
            lanc(BAIXA, numero="879101", dia=5, debito="731.47",
                 cta_part="38", saldo="-1268.53"),
            lanc(ESTORNO, numero="879102", dia=20, credito="731.47",
                 cta_part="38", saldo="-2000.00"),
        ],
    )


def test_ponta_a_ponta_o_par_fecha_e_o_gap_nao_muda():
    """Prova de CI da regra CASA: classificador -> casar -> pareamento ->
    composicao -> veredito, sem arquivo e sem dado real."""
    res = conferir(_conta_com_par(), CLF)

    assert res.balde == []
    (par,) = [a for a in res.achados if a.codigo == "estorno_pareado"]
    assert par.nivel is Nivel.ALERTA
    assert [l.numero for l in par.lancamentos] == ["879101", "879102"]

    # o par nao tocou na composicao: a NF continua aberta pelo valor cheio
    (nf,) = [i for i in res.itens if i.nf_numero == "12345"]
    assert nf.saldo_aberto == D("2000.00")
    assert nf.qtd_quitacoes == 0

    # e a conta FECHA: sem balde, o veredito nao tem por que ficar incompleto
    assert not any(a.nivel is Nivel.ERRO for a in res.achados)
    assert not any(a.nivel is Nivel.INCOMPLETO for a in res.achados)


def test_ponta_a_ponta_sem_o_estorno_a_baixa_fica_no_balde():
    """O contraste que prova que e o PAREAMENTO agindo, e nao a baixa sumindo
    por outro caminho."""
    conta = _conta_com_par()
    conta.lancamentos = conta.lancamentos[:2]          # tira o estorno
    conta.total_credito_dominio = D("2000.00")         # ... e os totais o seguem
    res = conferir(conta, CLF)

    assert len(res.balde) == 1
    assert res.balde[0].lancamentos[0].numero == "879101"
    assert not [a for a in res.achados if a.codigo == "estorno_pareado"]

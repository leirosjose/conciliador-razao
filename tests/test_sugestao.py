"""Sugestao de destino: o canal pelo qual o motor PROPOE sem casar.

O que estes testes travam: uma sugestao e inerte. Ela nao altera composicao,
veredito, gap nem balde -- so' oferece um destino provavel com a evidencia que
o sustenta, pra o contador confirmar em um clique.
"""
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from core.classifica import Tipo
from core.conferencia import conferir
from core.modelo import (
    AlocacaoManual,
    Conta,
    CriterioSugestao,
    DestinoAlocacao,
    ItemRevisao,
    Lancamento,
    MotivoRevisao,
    Sugestao,
)
from core.sugestao import REGRAS, ContextoSugestao, sugerir
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal


def _sugestao(**kw):
    base = dict(destino=DestinoAlocacao.LINHA_ABERTA,
                criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO,
                alvo="43806")
    return Sugestao(**{**base, **kw})


# --- Modelo (commit 1) --------------------------------------------------------

def test_item_do_balde_nasce_sem_sugestao():
    """Default inerte: todo item que existe hoje continua sem sugestao, e a
    tela segue com o seletor em branco pra ele."""
    item = ItemRevisao(lancamentos=[], motivo=MotivoRevisao.SEM_VINCULO)
    assert item.sugestao is None


def test_sugestao_exige_criterio():
    """Sugestao sem porque nao existe: o criterio e o que vira frase de
    evidencia na tela e na planilha."""
    with pytest.raises(TypeError):
        Sugestao(destino=DestinoAlocacao.LINHA_ABERTA, alvo="43806")


def test_sugestao_e_imutavel():
    """Frozen pelo mesmo motivo da AlocacaoManual: a sugestao circula
    entre core, tela e planilha e nao pode ser reescrita por engano no meio."""
    with pytest.raises(FrozenInstanceError):
        _sugestao().alvo = "outra"


def test_sugestao_sem_evidencia_nem_candidatos_tem_defaults_vazios():
    s = _sugestao()
    assert s.evidencia == {}
    assert s.candidatos == ()


def test_evidencia_guarda_decimal_cru_nunca_texto_formatado():
    """Padrao #34: o core entrega numeros; a frase com R$ nasce na
    apresentacao. Evidencia com string ja formatada seria moeda no core."""
    s = _sugestao(evidencia={"parcela_declarada": D("541.37"),
                             "valor_compra": D("1082.74")})
    assert all(isinstance(v, Decimal) for v in s.evidencia.values())
    assert s.evidencia["valor_compra"] == D("1082.74")


# --- Seam (commit 2) ----------------------------------------------------------

def _item(lote="1", motivo=MotivoRevisao.SEM_VINCULO):
    lanc = Lancamento(data=date(2025, 1, 1), numero=lote, historico="h",
                      cta_part="10", debito=D("100.00"), credito=D("0.00"),
                      saldo_exercicio=D("0.00"))
    return ItemRevisao(lancamentos=[lanc], motivo=motivo, identificador=lote)


def test_sugerir_sem_regra_nenhuma_e_inerte():
    """A trava do canal: com REGRAS vazia (o estado inicial), rodar `sugerir`
    sobre o balde inteiro nao anota nada. E o que garante que o commit do seam
    nao mexe em nenhum numero contabil."""
    balde = [_item("1"), _item("2")]
    sugerir(balde, [], regras=())
    assert [i.sugestao for i in balde] == [None, None]


def test_regra_anota_o_item_que_ela_escolheu():
    balde = [_item("1"), _item("2")]

    def so_o_lote_2(item, ctx):
        return _sugestao(alvo="43806") if item.identificador == "2" else None

    sugerir(balde, [], regras=(so_o_lote_2,))
    assert balde[0].sugestao is None
    assert balde[1].sugestao.alvo == "43806"


def test_primeira_regra_que_casa_vence():
    """Uma sugestao por item: a ORDEM em REGRAS e a decisao explicita de
    prioridade, nao o acaso de qual regra rodou por ultimo."""
    balde = [_item("1")]
    primeira = lambda item, ctx: _sugestao(alvo="PRIMEIRA")      # noqa: E731
    segunda = lambda item, ctx: _sugestao(alvo="SEGUNDA")        # noqa: E731

    sugerir(balde, [], regras=(primeira, segunda))
    assert balde[0].sugestao.alvo == "PRIMEIRA"


def test_regra_que_devolve_none_cede_a_vez_pra_proxima():
    balde = [_item("1")]
    nada = lambda item, ctx: None                                # noqa: E731
    alguma = lambda item, ctx: _sugestao(alvo="43806")           # noqa: E731

    sugerir(balde, [], regras=(nada, alguma))
    assert balde[0].sugestao.alvo == "43806"


def test_registro_de_regras_e_a_ordem_de_prioridade():
    """MAIS PROXIMO DA TELA GANHA: C compara contra o saldo (o numero que o
    contador ve na composicao), D contra o valor de compra (uma reconstrucao).
    A E vem por ULTIMO: C e D leem a serie que o PROPRIO item declara
    ("k de M"); a E infere a partir do que ja foi casado em outros lancamentos.
    Havendo resposta das duas, ganha a que se apoia no que o item diz de si."""
    from core.regras_sugestao import continuidade_serie_ordinal, serie_x_saldo_remanescente, serie_x_valor_declarado
    assert REGRAS == (serie_x_saldo_remanescente, serie_x_valor_declarado,
                      continuidade_serie_ordinal)


def test_omitir_regras_consulta_o_REGRAS_do_momento(monkeypatch):
    """REGRAS tem que ser o registro UNICO: default de funcao e avaliado na
    definicao, entao `regras=REGRAS` na assinatura congelaria a tupla vazia
    inicial e as regras de C e D nunca rodariam — em silencio."""
    balde = [_item("1")]
    monkeypatch.setattr("core.sugestao.REGRAS",
                        (lambda item, ctx: _sugestao(alvo="43806"),))
    sugerir(balde, [])
    assert balde[0].sugestao.alvo == "43806"


# --- Lugar na cadeia: DEPOIS da alocacao manual (commit 2) --------------------

def _conta_com_balde():
    """Uma compra e um lancamento de historico irreconhecivel (-> balde)."""
    return Conta(
        codigo="9000", classificacao="1.1", nome="FORNECEDOR TESTE",
        data_fim_periodo=date(2025, 12, 31),
        lancamentos=[
            lanc("Vr. compras conf. 12345 FORNECEDOR TESTE",
                 numero="1", dia=5, credito="1000.00", saldo="-1000.00"),
            lanc("Valor ref. a coisa que o classificador nao conhece",
                 numero="2", dia=10, debito="300.00", saldo="-700.00"),
        ],
    )


def _espiao(registro):
    def espiao(balde, nfs, pares=(), regras=None):
        registro.append(([i.identificador for i in balde],
                         {nf.numero: nf.saldo_aberto for nf in nfs}))
    return espiao


def test_sugerir_roda_depois_da_alocacao_manual(monkeypatch):
    """A ordem na cadeia e o coracao do commit: `sugerir` enxerga o balde que
    SOBROU e o saldo que as decisoes do contador ja deixaram. Rodar antes
    sugeriria destino pra item que ja saiu, e ofereceria NF que ele acabou de
    quitar."""
    registro = []
    monkeypatch.setattr("core.conferencia.sugerir", _espiao(registro))
    conta = _conta_com_balde()
    res = conferir(conta, ClassificadorHistorico())
    (ids_sem_alocacao, _), = registro
    assert len(ids_sem_alocacao) == 1                      # o item esta no balde

    registro.clear()
    conferir(conta, ClassificadorHistorico(),
             [AlocacaoManual(item_id=res.balde[0].identificador,
                             destino=DestinoAlocacao.LINHA_ABERTA, alvo="12345")])
    (ids_pos_alocacao, saldos), = registro
    assert ids_pos_alocacao == []                          # ja saiu do balde
    assert saldos["12345"] == D("700.00")                    # e o saldo ja e o novo


def test_item_alocado_nao_recebe_sugestao():
    """Consequencia da ordem, sem espiao: quem saiu do balde nao volta pela
    porta da sugestao."""
    conta = _conta_com_balde()
    res = conferir(conta, ClassificadorHistorico())
    novo = conferir(conta, ClassificadorHistorico(),
                    [AlocacaoManual(item_id=res.balde[0].identificador,
                                    destino=DestinoAlocacao.LINHA_ABERTA,
                                    alvo="12345")])
    assert novo.balde == []
    assert all(d.item.sugestao is None for d in novo.decisoes)


# --- Rastro da sugestao aceita (commit 3) -------------------------------------

def _aloca(conta, item_id, **kw):
    return conferir(conta, ClassificadorHistorico(),
                    [AlocacaoManual(item_id=item_id,
                                    destino=DestinoAlocacao.LINHA_ABERTA,
                                    alvo="12345", **kw)])


def test_alocacao_sem_criterio_e_o_default_de_sempre():
    """A decisao propria do contador nao ganha origem: origem so se declara
    quando existe. E as AlocacaoManual ja guardadas na sessao continuam
    validas — campo novo, com default."""
    conta = _conta_com_balde()
    res = conferir(conta, ClassificadorHistorico())
    novo = _aloca(conta, res.balde[0].identificador)
    assert novo.decisoes[0].criterio_sugerido is None


def test_criterio_aceito_atravessa_ate_a_decisao():
    """O rastro que vai pro cliente: esta linha da composicao existe porque o
    contador ACEITOU uma proposta do motor, e a planilha diz qual."""
    conta = _conta_com_balde()
    res = conferir(conta, ClassificadorHistorico())
    novo = _aloca(conta, res.balde[0].identificador,
                  criterio_sugerido=CriterioSugestao.SERIE_X_VALOR_DECLARADO)
    assert (novo.decisoes[0].criterio_sugerido
            is CriterioSugestao.SERIE_X_VALOR_DECLARADO)


def test_criterio_sugerido_nao_muda_nada_na_composicao():
    """Metadado de rastreabilidade, nao regra: o core nao valida e nao decide
    nada com ele. Mesma alocacao com e sem criterio -> mesma composicao."""
    conta = _conta_com_balde()
    res = conferir(conta, ClassificadorHistorico())
    ident = res.balde[0].identificador
    sem = _aloca(conta, ident)
    com = _aloca(conta, ident,
                 criterio_sugerido=CriterioSugestao.SERIE_X_SALDO_REMANESCENTE)
    assert ([(i.nf_numero, i.saldo_aberto) for i in com.itens]
            == [(i.nf_numero, i.saldo_aberto) for i in sem.itens])
    assert com.erros_alocacao == sem.erros_alocacao == []


# --- ContextoSugestao -----------------------------------------------------------
# O contrato inicial -- Regra = (item, nfs) -- nao bastava: ItemRevisao NAO
# carrega a Classificacao, e as regras precisam do que o historico DECLAROU
# (o M de "Parcela k de M" na regra C, o valor da parcela na D). O core nao pode
# reclassificar, entao a classificacao vem de fora.

def test_contexto_devolve_a_classificacao_do_lancamento():
    conta = _conta_com_balde()
    clf = ClassificadorHistorico()
    pares = [(l, clf.classificar(l)) for l in conta.lancamentos]
    ctx = ContextoSugestao.montar([], [], pares)
    compra, solto = conta.lancamentos
    assert ctx.classificacao(compra).nf_numero == "12345"
    assert ctx.classificacao(solto).tipo is Tipo.OUTRO


def test_contexto_nao_conhece_lancamento_de_fora():
    ctx = ContextoSugestao.montar([], [], [])
    assert ctx.classificacao(lanc("x")) is None


def test_declarada_devolve_o_par_do_item_de_um_lancamento():
    conta = _conta_com_balde()
    clf = ClassificadorHistorico()
    pares = [(l, clf.classificar(l)) for l in conta.lancamentos]
    item = ItemRevisao(lancamentos=[conta.lancamentos[1]],
                       motivo=MotivoRevisao.NAO_CLASSIFICADO)
    ctx = ContextoSugestao.montar([item], [], pares)
    l, c = ctx.declarada(item)
    assert l is conta.lancamentos[1]
    assert c.tipo is Tipo.OUTRO


def test_declarada_recusa_item_agregado():
    """Item com 2+ lancamentos (o um-pra-muitos) nao tem "a" parcela nem
    "o" valor pra regra nenhuma comparar."""
    a, b = lanc("x", numero="1"), lanc("y", numero="2")
    ctx = ContextoSugestao.montar([], [], [(a, None), (b, None)])
    assert ctx.declarada(ItemRevisao(lancamentos=[a, b],
                                     motivo=MotivoRevisao.SEM_VINCULO)) is None


def test_contexto_enxerga_o_balde_inteiro_e_as_nfs():
    """A regra precisa do balde pra contar ocorrencias da mesma serie."""
    i1, i2 = _item("1"), _item("2")
    ctx = ContextoSugestao.montar([i1, i2], [], [])
    assert ctx.balde == (i1, i2)
    assert ctx.nfs == ()

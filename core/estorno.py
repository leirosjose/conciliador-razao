"""Pareamento de ESTORNO com a operacao que ele reverte. Core puro.

Uma baixa lancada por engano e depois estornada e um par que se anula: liquido
zero, nada entra na composicao. Hoje os dois caem no balde separados e o
conferente gasta duas leituras pra descobrir que um cancela o outro.

E a UNICA regra que CASA fora do casamento, e cabe no criterio (prova por exclusao, nao
inferencia) porque nada aqui e adivinhado: o proprio historico DECLARA a
operacao revertida, os valores sao identicos e opostos, a contrapartida e a
mesma e o estorno vem depois. E o par nao afirma quitacao nenhuma — o risco que
faz CASA ser caro (o cliente receber uma composicao afirmando uma quitacao que
ninguem provou) nao existe aqui.

Roda no fim de `casar()`, ANTES de `aplicar`: pareamento e decisao AUTOMATICA, e
nenhuma decisao automatica enxerga alocacao manual. Rodar depois
faria o par depender da ordem dos cliques do contador.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from core.classifica import Classificacao, Tipo
from core.modelo import Achado, ItemRevisao, Lancamento, Nivel

ZERO = Decimal("0.00")


def _unico(item: ItemRevisao) -> Lancamento | None:
    """O lancamento do item, se ele tiver exatamente UM.

    Item agregado (o um-pra-muitos) nao tem "o" valor nem "a"
    contrapartida pra comparar — nao pareia."""
    return item.lancamentos[0] if len(item.lancamentos) == 1 else None


def _liquido(lanc: Lancamento) -> Decimal:
    return lanc.debito - lanc.credito


def _anulam(a: Lancamento, b: Lancamento) -> bool:
    """Valores identicos e opostos, ao centavo e SEM tolerancia.

    Estorno reverte o valor exato: um centavo de diferenca e outra coisa (juros,
    desconto, arredondamento) e outra coisa vai pro balde, onde o conferente a
    ve. A soma dos liquidos cobre os dois requisitos de uma vez -- mesmo modulo
    e sinais opostos -- e o `!= ZERO` barra o par degenerado de dois zeros."""
    return _liquido(a) != ZERO and _liquido(a) + _liquido(b) == ZERO


def parear(balde: Sequence[ItemRevisao],
           pares: Sequence[tuple[Lancamento, Classificacao]],
           ) -> tuple[list[ItemRevisao], list[Achado]]:
    """Devolve (balde SEM os pares anulados, um achado por par).

    `pares` sao os (lancamento, classificacao) que `casar()` ja tem em maos: e
    de la que vem o tipo do parceiro, que o ItemRevisao nao carrega.
    """
    clf_de = {id(lanc): clf for lanc, clf in pares}

    def _classificacao(item: ItemRevisao) -> Classificacao | None:
        lanc = _unico(item)
        return clf_de.get(id(lanc)) if lanc is not None else None

    # candidatos por estorno: quem satisfaz TODAS as condicoes
    candidatos: dict[int, list[int]] = {}
    for i, estorno in enumerate(balde):
        clf = _classificacao(estorno)
        # Sem declaracao do que reverte NAO ha prova, e quem decide e o
        # conferente: estorno generico nunca pareia. A checagem de tipo la
        # embaixo ja garantiria isso sozinha (nenhum parceiro tem tipo None),
        # mas a REGRA fica dita aqui, onde se procura por ela — e nao como
        # efeito colateral de uma comparacao tres niveis adentro.
        if clf is None or clf.tipo is not Tipo.ESTORNO or clf.estorna is None:
            continue
        l_estorno = _unico(estorno)
        achados_i = []
        for j, parceiro in enumerate(balde):
            if i == j:
                continue
            clf_p = _classificacao(parceiro)
            l_parceiro = _unico(parceiro)
            if clf_p is None or clf_p.tipo is not clf.estorna:
                continue
            if l_parceiro.cta_part != l_estorno.cta_part:
                continue
            if not _anulam(l_estorno, l_parceiro):
                continue
            # nao se reverte o que ainda nao aconteceu. ESTRITAMENTE posterior:
            # no mesmo dia nada ordena os dois, e ordem inventada seria chute
            if l_parceiro.data >= l_estorno.data:
                continue
            achados_i.append(j)
        if achados_i:
            candidatos[i] = achados_i

    # unicidade MUTUA: o estorno so' pode ter um candidato, E esse candidato so'
    # pode ter sido apontado por um estorno. Duas baixas identicas, ou dois
    # estornos pra a mesma baixa, sao ambiguidade -- e ambiguidade fica no balde.
    apontado_por: dict[int, list[int]] = {}
    for i, js in candidatos.items():
        for j in js:
            apontado_por.setdefault(j, []).append(i)

    achados: list[Achado] = []
    pareados: set[int] = set()
    for i, js in candidatos.items():
        if len(js) != 1:
            continue
        (j,) = js
        if len(apontado_por[j]) != 1:
            continue
        pareados.update((i, j))
        l_estorno, l_parceiro = _unico(balde[i]), _unico(balde[j])
        achados.append(Achado(
            nivel=Nivel.ALERTA,
            codigo="estorno_pareado",
            mensagem=(f"par anulado: lote {l_parceiro.numero} estornado pelo "
                      f"lote {l_estorno.numero}"),
            # os dois lotes do par, na ordem em que aconteceram
            referencia=f"{l_parceiro.numero}, {l_estorno.numero}",
            valores={"valor": abs(_liquido(l_parceiro))},
            # a EVIDENCIA integral, na ordem em que aconteceu (operacao, depois
            # estorno): o par nao deixa linha na composicao, entao este achado e
            # a unica resposta a "cade a baixa?"
            lancamentos=(l_parceiro, l_estorno),
        ))

    restante = [item for k, item in enumerate(balde) if k not in pareados]
    return restante, achados

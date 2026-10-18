"""Sugestao de destino pros itens que sobraram no balde. Core puro.

O motor NUNCA chuta -- mas com a alocacao manual da tela ele pode PROPOR. A fronteira:

- prova por exclusao aritmetica -> CASA (o casamento resolve, o item sai do
  balde e entra na composicao marcado);
- inferencia forte, sem prova de unicidade -> SUGERE (este modulo): o item
  CONTINUA no balde, o gap continua o mesmo, e a tela pre-seleciona o destino
  provavel pra o contador confirmar em um clique.

Inferencia forte nao vira casamento so por ser convincente: o preco de errar um
CASA e o cliente receber uma composicao afirmando uma quitacao que ninguem
provou. O preco de errar um SUGERE e um clique.

Uma regra pura por criterio, registrada em REGRAS. A ORDEM da tupla e a
prioridade: a primeira que casar vence, e as demais nem sao consultadas --
duas regras discordando sobre o mesmo item e ambiguidade que o motor nao
resolve sozinho.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from core.classifica import Classificacao
from core.modelo import NF, ItemRevisao, Lancamento, MotivoRevisao, Sugestao
from core.regras_sugestao import continuidade_serie_ordinal, serie_x_saldo_remanescente, serie_x_valor_declarado


@dataclass(frozen=True)
class ContextoSugestao:
    """Tudo que uma regra pode olhar. Read-only de proposito: regra nao muta
    nada — le e devolve uma Sugestao ou None.

    Existe porque `ItemRevisao` NAO carrega a Classificacao (so' lancamentos,
    motivo, candidatos, mensagem, id e valores), e as regras precisam do que o
    historico DECLAROU: o M de "Parcela k de M", o valor declarado da
    parcela. O core nao pode reclassificar — nao importa `parser/` —
    entao a classificacao vem de fora, como em `core/estorno.py`.
    """
    nfs: tuple[NF, ...]                 # estado APOS casar + aplicar
    balde: tuple[ItemRevisao, ...]      # o que sobrou, incluindo o proprio item
    classificacoes: dict[int, Classificacao]      # id(lancamento) -> Classificacao

    @classmethod
    def montar(cls, balde, nfs, pares) -> "ContextoSugestao":
        return cls(nfs=tuple(nfs), balde=tuple(balde),
                   classificacoes={id(lanc): clf for lanc, clf in pares})

    def classificacao(self, lanc: Lancamento) -> Classificacao | None:
        return self.classificacoes.get(id(lanc))

    def declarada(self, item: ItemRevisao) -> tuple[Lancamento, Classificacao] | None:
        """(lancamento, classificacao) de um item de UM lancamento so'.

        None pra item agregado (o um-pra-muitos): ele nao tem "a"
        parcela nem "o" valor pra regra nenhuma comparar. Helper aqui, e nao
        em cada regra, porque toda regra comeca por esta mesma pergunta."""
        if len(item.lancamentos) != 1:
            return None
        lanc = item.lancamentos[0]
        clf = self.classificacao(lanc)
        return None if clf is None else (lanc, clf)


# Contrato de uma regra: le o item e o contexto, devolve o destino provavel ou
# None quando nao tem prova nenhuma pra oferecer. Pura: sem estado, sem I/O,
# sem enxergar a tela.
Regra = Callable[[ItemRevisao, ContextoSugestao], "Sugestao | None"]

# O registro. A ORDEM e a prioridade: a primeira que casar vence, e as demais
# nem sao consultadas.
# (As letras C, D e E sao as regras de CriterioSugestao, em core/modelo.py.)
#
# Criterio de precedencia: MAIS PROXIMO DA TELA GANHA. A regra C compara
# contra o SALDO, que e o numero que o contador tem diante dos olhos na
# composicao; a D compara contra o valor de COMPRA, que e uma reconstrucao.
# Quando as duas tem resposta pro mesmo item, ganha a que fala do que esta na
# tela.
# Nao ha regra de qual parcela absorve a diferenca de uma divisao que nao fecha
# redonda, nem limite do que e' arredondamento: isso e' definido pelo fornecedor
# ao gerar as parcelas, e no final pagamentos e notas tem de bater. Consequencias:
# (1) a regra DIVISAO_EXATA continua DORMENTE — sem definicao, nao ha o que
#     implementar;
# (2) a ancora por serie destas regras se sustenta: e' com 2+ parcelas ja pagas
#     que C e E reconhecem a divisao. A E ja exige exatamente isso ("duas
#     parcelas e' o minimo: uma so' nao e' serie").
#
# A regra E entra POR ULTIMO: C e D falam de uma serie DECLARADA inteira
# ("k de M"), que e' afirmacao do proprio historico do item; a E infere a partir
# do que ja foi casado em OUTROS lancamentos. Havendo resposta das duas, ganha a
# que se apoia no que o item declara de si.
REGRAS: tuple[Regra, ...] = (serie_x_saldo_remanescente,
                             serie_x_valor_declarado,
                             continuidade_serie_ordinal)


def sugerir(balde: Sequence[ItemRevisao], nfs: list[NF],
            pares: Sequence[tuple[Lancamento, Classificacao]] = (),
            regras: "tuple[Regra, ...] | None" = None) -> None:
    """Anota `item.sugestao` com a PRIMEIRA regra que casar, item a item.

    `regras` e parametro (caindo em REGRAS quando omitido) porque e assim que o
    canal se testa inteiro sem depender de nenhuma regra real -- e como cada
    regra nova se testa isolada, sem as outras no caminho.

    O default e None, e nao `REGRAS` direto: default de funcao e avaliado UMA
    vez, na definicao, entao `regras=REGRAS` congelaria a tupla daquele
    instante e REGRAS deixaria de ser o registro unico (trocar o modulo nao
    teria efeito nenhum, em silencio).

    Anota em vez de devolver lista nova pelo mesmo motivo que `casar()` ja
    preenche `identificador` no fim: o item do balde e a unidade de identidade
    da tela (a alocacao manual o reencontra pelo id) e duplica-lo criaria duas
    verdades sobre o mesmo lancamento.
    """
    ctx = ContextoSugestao.montar(balde, nfs, pares)
    for item in balde:
        # o motor nao sabe o que um lancamento no lado oposto ao
        # historico e' -- nao ha destino provavel pra propor
        if item.motivo is MotivoRevisao.LADO_INESPERADO:
            continue
        for regra in (REGRAS if regras is None else regras):
            sugestao = regra(item, ctx)
            if sugestao is not None:
                item.sugestao = sugestao
                break

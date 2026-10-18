"""Materialidade do balde: dos N itens em revisao manual, quais POUCOS
respondem pela maior parte do gap — o conferente ataca esses primeiro.

Camada de APRESENTACAO, nao de contabilidade: e' ajuda de LEITURA sobre
numeros que o core ja fechou. Nao altera composicao, casamento nem veredito;
nenhum item entra ou sai do balde por causa daqui. Por isso vive em app/ e
NUNCA no core.

Modulo PROPRIO, e nao dentro de app/apresentacao.py, por uma razao: aquele
modulo declara "SEM aritmetica de dinheiro" e a regra vale a pena manter
crispa. As UNICAS contas desta camada (somar os maiores e dividir pelo gap)
ficam aqui, isoladas e nomeadas. Decimal ate a borda; a formatacao BR so na
frase. A dependencia e' de mao unica: materialidade -> apresentacao.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.apresentacao import balde_celulas, balde_lancamentos, moeda_br, pct_br
from core.modelo import ItemRevisao

ZERO = Decimal("0.00")
DECIMO = Decimal("0.1")

MAX_ITENS = 5           # "os N maiores" -- lista que cabe num olhar
MINIMO_PRA_FRASE = 3    # com 1 ou 2 itens a propria lista ja e o resumo

# A frase mora AQUI (constante), como _CONTEXTO_INCOMPLETO na apresentacao:
# o teste confere o NUMERO e delega o texto a este modulo.
_FRASE = ("Os {n} maiores itens respondem por R$ {soma} da diferença de "
          "R$ {total} ({pct}%)")


@dataclass(frozen=True)
class Materialidade:
    """`itens` sao as linhas do balde (as MESMAS da planilha, ja ordenadas por
    valor), da maior pra menor.

    `soma` e o quanto esses itens RESPONDEM do gap, e nao a soma da coluna
    Valor: cada linha entra pela sua CONTRIBUICAO (debito - credito), que e a
    mesma identidade com que o veredito explica o INCOMPLETO (gap == Σ(D-C) do
    balde). Um credito de 500,00 no balde REDUZ o gap em 500,00; soma-lo como
    +500 dizia que 4 itens de um gap de 2.650,00 "explicavam" 4.150,00 (156,6%)
    — numero que so podia estar errado. Com a contribuicao, o balde INTEIRO da
    exatamente 100% por construcao.

    `percentual` e o peso da soma sobre o TAMANHO do gap (abs): conta devedora
    deixa o gap negativo e um percentual negativo nao diria nada."""
    itens: tuple[dict, ...]
    soma: Decimal
    gap: Decimal | None
    percentual: Decimal | None
    total: int              # quantas linhas ha no balde inteiro


def resumo_materialidade(balde: list[ItemRevisao],
                         gap: Decimal | None) -> Materialidade:
    # a ORDEM e por valor (o maior primeiro: e o maior pedaco de TRABALHO);
    # a CONTA e por contribuicao (o quanto cada um move o gap). As duas listas
    # saem da MESMA ordenacao, entao linha N <-> lancamento N.
    linhas = balde_celulas(balde, por_valor=True)
    lancamentos = balde_lancamentos(balde, por_valor=True)
    maiores = tuple(linhas[:MAX_ITENS])
    soma = sum((l.debito - l.credito for l in lancamentos[:MAX_ITENS]), ZERO)
    percentual = ((soma / abs(gap) * 100).quantize(DECIMO, rounding=ROUND_HALF_UP)
                  if gap else None)
    return Materialidade(itens=maiores, soma=soma, gap=gap,
                         percentual=percentual, total=len(linhas))


def _pct_br(percentual: Decimal) -> str:
    return pct_br(percentual)      # formatador BR mora na apresentacao


def frase_materialidade(balde: list[ItemRevisao],
                        gap: Decimal | None) -> str | None:
    """A linha que vai acima do balde (tela e Excel). None quando nao ha o que
    resumir: menos de 3 itens, sem gap (composicao que fecha), ou balde que
    cabe inteiro nos N maiores.
    Um SUBCONJUNTO pode passar de 100% quando o resto do balde puxa pro outro
    lado (os 3 maiores debitos podem exceder um gap que creditos reduzem) —
    e' informacao verdadeira, nao defeito: o balde inteiro fecha em 100%."""
    resumo = resumo_materialidade(balde, gap)
    if resumo.total < MINIMO_PRA_FRASE or resumo.percentual is None:
        return None
    # a frase fala de "R$ X da diferenca de R$ Y" -- com diferenca ou
    # soma negativas (credito pesando mais) ela imprimiria R$ negativo, que a
    # tela nunca mostra. A lista dos maiores continua; a frase sai.
    if resumo.gap < ZERO or resumo.soma < ZERO:
        return None
    # "os N maiores" com N = o balde inteiro so' repete o total --
    # a frase so' diz algo quando ha itens fora dos N
    if resumo.total <= len(resumo.itens):
        return None
    return _FRASE.format(n=len(resumo.itens), soma=moeda_br(resumo.soma),
                         total=moeda_br(resumo.gap),
                         pct=_pct_br(resumo.percentual))


def contagem_por_motivo(balde: list[ItemRevisao]) -> list[tuple[str, int]]:
    """(rotulo do motivo, quantas linhas), do mais frequente pro menos —
    empate resolve em ordem alfabetica pra sair sempre igual. Conta os MESMOS
    rotulos que a tabela mostra (balde_celulas), nunca uma taxonomia paralela."""
    contagem = Counter(linha["Motivo"] for linha in balde_celulas(balde))
    return sorted(contagem.items(), key=lambda par: (-par[1], par[0]))


def frase_sugestoes(balde: list[ItemRevisao]) -> str | None:
    """'6 dos 9 itens tem destino sugerido pelo motor'. None quando nao ha
    sugestao nenhuma -- linha dizendo "zero" e ruido, mesma regra da
    materialidade. Contagem pura: nao le valor, nao muda nada."""
    sugeridos = sum(1 for i in balde if i.sugestao is not None)
    if not sugeridos:
        return None
    total = len(balde)
    return (f"{sugeridos} d{'os' if total > 1 else 'e'} {total} "
            f"{'itens' if total > 1 else 'item'} "
            f"{'têm' if sugeridos > 1 else 'tem'} destino sugerido "
            f"pelo motor")


def frase_contagem_motivos(balde: list[ItemRevisao]) -> str | None:
    """'9 itens: 4 Empate, 3 Sem NF, 2 Nao reconhecido'. None se o balde e vazio."""
    pares = contagem_por_motivo(balde)
    if not pares:
        return None
    total = sum(quantas for _, quantas in pares)
    return (f"{total} {'itens' if total > 1 else 'item'}: "
            + ", ".join(f"{quantas} {rotulo}" for rotulo, quantas in pares))

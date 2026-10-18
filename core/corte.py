"""Corte por saldo zero: ONDE a razao pode ser cortada.

Core puro, zero I/O. Se o saldo-exercicio IMPRESSO vale 0,00 na linha k, entao
saldo anterior + Σ(D−C) das linhas 1..k = 0, e o saldo final e' exatamente o
que vem depois de k. A composicao do saldo final so' depende do pos-corte.
E' partida dobrada, nao regra contabil.

Limite: zero AGREGADO nao prova quitacao NF a NF. Por isso este modulo so'
diz ONDE cortar; o que ficou antes vira informacao em canal proprio (nunca
"quitada") -- isso e' a particao, noutro passo.

O corte usa o ULTIMO zero aproveitavel. Um zero e' RECUSADO quando:
  - algo o CRUZA: NF, par de estorno ou item do balde com lancamento dos dois
    lados. NF sem compra no periodo (consome o saldo anterior) vive "antes de
    tudo", entao quitacao dela depois do zero cruza;
  - a conta do periodo zerado nao fecha ao centavo (Σ aberto das NFs de la ==
    Σ(D−C) do balde de la). Sem cruzamento isso e' aritmetica e sempre fecha;
    a trava existe pra que um erro de particao nunca vire composicao.
Recusado o ultimo, RECUA pro anterior; sem nenhum, nao ha corte -- o
comportamento de sempre. Recuar ou desistir gera ALERTA `corte_recuado`.
Leitura nao conferida (algum self-check de parsing nao-OK) nao corta: o zero
impresso so' vale se a razao foi lida certo.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Sequence

from core.modelo import (
    ALVO_ANTERIOR,
    NF,
    Achado,
    DecisaoManual,
    DestinoAlocacao,
    FechadoPorSaldoZero,
    ItemRevisao,
    Lancamento,
    Nivel,
    ResultadoCasamento,
)

ZERO = Decimal("0.00")
ANTES_DE_TUDO = -1      # posicao do saldo anterior


@dataclass(frozen=True)
class Corte:
    """O zero escolhido: `indice` na lista de lancamentos da conta. `zeros` sao
    todos os zeros ate ele (inclusive) -- a leitura "zerou em" da tela;
    `descartados`, os zeros posteriores que foram recusados."""
    indice: int
    lancamento: Lancamento
    zeros: tuple[Lancamento, ...] = ()
    descartados: tuple[Lancamento, ...] = ()


@dataclass(frozen=True)
class _Grupo:
    """O que tem que ficar INTEIRO de um lado do corte, e o que pesa na conta
    do periodo zerado (aberto de NF, liquido de balde)."""
    referencia: str
    posicoes: tuple[int, ...]
    aberto: Decimal = ZERO          # NF: compra − quitado (+ o anterior que ela consome)
    balde: Decimal = ZERO           # item do balde: Σ(D−C)


def _data(lanc: Lancamento) -> str:
    return lanc.data.strftime("%d/%m/%Y")


def _posicoes_nf(nf: NF, pos: dict[int, int]) -> list[int]:
    lancs = (nf.compras + nf.pagamentos + nf.retencoes + nf.baixas
             + nf.manuais + [a.lancamento for a in nf.alocacoes])
    posicoes = [pos[id(l)] for l in lancs]
    if nf.data_compra is None:
        posicoes.append(ANTES_DE_TUDO)
    return posicoes


def _grupos(resultado: ResultadoCasamento, pos: dict[int, int],
            decisoes: Sequence[DecisaoManual] = ()) -> list[_Grupo]:
    grupos: list[_Grupo] = []
    # decisao "fora da composicao" do contador: ela entra na identidade
    # do pos-corte, entao nunca pode ficar no periodo zerado -- todo zero a
    # partir do item e' cruzado ("depois de tudo" como a outra ponta)
    depois_de_tudo = len(pos)
    for d in decisoes:
        if d.destino is DestinoAlocacao.FORA_DA_COMPOSICAO:
            grupos.append(_Grupo(
                ", ".join(l.numero for l in d.item.lancamentos),
                tuple(pos[id(l)] for l in d.item.lancamentos)
                + (depois_de_tudo,)))
    for nf in resultado.nfs:
        grupos.append(_Grupo(nf.numero, tuple(_posicoes_nf(nf, pos)),
                             aberto=nf.valor_compra - nf.total_quitado))
    for item in resultado.balde:
        grupos.append(_Grupo(
            ", ".join(l.numero for l in item.lancamentos),
            tuple(pos[id(l)] for l in item.lancamentos),
            balde=sum((l.debito - l.credito for l in item.lancamentos), ZERO)))
    for achado in resultado.achados:
        # par de estorno: saiu do balde, mas os dois lados tem que ficar
        # juntos; liquido zero, nao pesa na conta
        if achado.codigo == "estorno_pareado" and achado.lancamentos:
            grupos.append(_Grupo(
                achado.referencia or "",
                tuple(pos[id(l)] for l in achado.lancamentos)))
    return grupos


def _cruzam(grupos: list[_Grupo], z: int) -> list[str]:
    return [g.referencia for g in grupos
            if min(g.posicoes) <= z < max(g.posicoes)]


def _fecha(grupos: list[_Grupo], z: int, saldo_anterior: Decimal) -> bool:
    fechados = [g for g in grupos if max(g.posicoes) <= z]
    # abs como compor()/nao_detalhado: o anterior entra como o a-pagar trazido
    aberto = abs(saldo_anterior) + sum((g.aberto for g in fechados), ZERO)
    return aberto == sum((g.balde for g in fechados), ZERO)


def localizar_corte(lancamentos: Sequence[Lancamento], saldo_anterior: Decimal,
                    resultado: ResultadoCasamento, leitura_ok: bool,
                    decisoes: Sequence[DecisaoManual] = (),
                    ) -> tuple[Corte | None, list[Achado]]:
    """(corte ou None, achados). `resultado` e' o casamento da razao INTEIRA
    JA COM as decisoes do contador aplicadas: o corte particiona o que existe,
    nunca o refaz. Uma alocacao que liga os dois lados de um zero (credito
    depois dele reabrindo NF de antes) e' cruzamento como outro qualquer --
    a decisao do contador faz o corte recuar, nunca e' recusada por ele."""
    zeros = [i for i, l in enumerate(lancamentos) if l.saldo_exercicio == ZERO]
    if not leitura_ok or not zeros:
        return None, []
    pos = {id(l): i for i, l in enumerate(lancamentos)}
    grupos = _grupos(resultado, pos, decisoes)

    escolhido: int | None = None
    motivo_ultimo: tuple[list[str], bool] | None = None   # (cruzam, fecha) do ultimo
    for z in reversed(zeros):
        cruzam = _cruzam(grupos, z)
        fecha = not cruzam and _fecha(grupos, z, saldo_anterior)
        if motivo_ultimo is None:
            motivo_ultimo = (cruzam, fecha)
        if not cruzam and fecha:
            escolhido = z
            break

    corte = None
    if escolhido is not None:
        corte = Corte(
            indice=escolhido, lancamento=lancamentos[escolhido],
            zeros=tuple(lancamentos[z] for z in zeros if z <= escolhido),
            descartados=tuple(lancamentos[z] for z in zeros if z > escolhido))
    if escolhido == zeros[-1]:
        return corte, []

    # o ULTIMO zero foi recusado: diz qual, por que e de onde se partiu
    ultimo = lancamentos[zeros[-1]]
    cruzam, _ = motivo_ultimo
    porque = ("há lançamentos dos dois lados desse ponto" if cruzam
              else "a conta do período zerado não fecha")
    destino = (f"a composição parte do zero de {_data(corte.lancamento)} "
               f"(lote {corte.lancamento.numero})" if corte
               else "a composição considera a razão inteira")
    return corte, [Achado(
        nivel=Nivel.ALERTA,
        codigo="corte_recuado",
        mensagem=(f"o saldo zerou em {_data(ultimo)} (lote {ultimo.numero}), "
                  f"mas {porque}; {destino}"),
        referencia=", ".join(cruzam) if cruzam else None,
    )]


@dataclass
class Particao:
    """O casamento da razao INTEIRA dividido no corte. `resultado` e' o
    pos-corte (vai pra alocacao, composicao e reconciliacao) e carrega TODOS
    os achados do casamento: duplicidade, desempate e estorno do periodo
    zerado continuam alertando. O resto e' o periodo zerado.
    `zerou_em`: numero da NF / identificador do item / ALVO_ANTERIOR -> o
    LANCAMENTO do primeiro zero depois dele (data E lote: a frase cita os
    dois). E' a leitura "zerou em" da tela, e o que agrupa a pendencia por
    bloco."""
    resultado: ResultadoCasamento
    nfs_fechadas: list[NF] = field(default_factory=list)
    balde_fechado: list[ItemRevisao] = field(default_factory=list)
    zerou_em: dict[str, Lancamento] = field(default_factory=dict)


def particionar(resultado: ResultadoCasamento,
                lancamentos: Sequence[Lancamento],
                corte: Corte | None) -> Particao:
    """Sem corte, a particao e' o resultado inteiro (o de sempre). Com corte,
    um grupo vai inteiro pro periodo zerado quando o ULTIMO lancamento dele
    esta ate o zero -- localizar_corte ja garantiu que nada cruza."""
    if corte is None:
        return Particao(resultado=resultado)
    pos = {id(l): i for i, l in enumerate(lancamentos)}
    zeros = [pos[id(l)] for l in corte.zeros]

    def _zerou(ultima: int) -> Lancamento:
        return lancamentos[next(z for z in zeros if z >= ultima)]

    nfs_pos, nfs_fech, zerou = [], [], {}
    # a linha "(saldo anterior)" agrega as NFs sem compra: o bloco dela e' o
    # da ULTIMA quitacao que a consumiu (sem nenhuma, o primeiro zero)
    ultima_do_anterior = ANTES_DE_TUDO
    for nf in resultado.nfs:
        ultima = max(_posicoes_nf(nf, pos))
        if ultima <= corte.indice:
            nfs_fech.append(nf)
            zerou[nf.numero] = _zerou(ultima)
            if nf.data_compra is None:
                ultima_do_anterior = max(ultima_do_anterior, ultima)
        else:
            nfs_pos.append(nf)
    zerou[ALVO_ANTERIOR] = _zerou(ultima_do_anterior)
    balde_pos, balde_fech = [], []
    for item in resultado.balde:
        ultima = max(pos[id(l)] for l in item.lancamentos)
        if ultima <= corte.indice:
            balde_fech.append(item)
            zerou[item.identificador] = _zerou(ultima)
        else:
            balde_pos.append(item)
    return Particao(
        resultado=ResultadoCasamento(nfs=nfs_pos, balde=balde_pos,
                                     achados=resultado.achados),
        nfs_fechadas=nfs_fech, balde_fechado=balde_fech, zerou_em=zerou)


def alerta_periodo_zerado(fechado: FechadoPorSaldoZero | None) -> list[Achado]:
    """D2: o que ficou no periodo zerado e' INFORMACAO, nao divergencia --
    ALERTA, que aparece na tela, na planilha e na triagem sem derrubar o
    verde. UM POR BLOCO com pendencia: a frase cita o zero que fechou
    AQUELES itens, nao o ultimo zero do corte. Numeros crus."""
    if fechado is None:
        return []
    return [Achado(
        nivel=Nivel.ALERTA,
        codigo="periodo_zerado_com_pendencia",
        # texto NEUTRO e curto: a frase com os dois R$ nasce na
        # apresentacao, a partir de `valores`
        mensagem=(f"o saldo da conta zerou em "
                  f"{bloco.zero.data.strftime('%d/%m/%Y')} "
                  f"(lote {bloco.zero.numero})"),
        referencia=bloco.zero.numero,
        encontrado=bloco.total_aberto,
        valores={"aberto": bloco.total_aberto,
                 "sem_nf": bloco.total_sem_nf,
                 "notas": Decimal(len(bloco.itens)),
                 "itens": Decimal(len(bloco.balde))},
    ) for bloco in fechado.blocos]


_NO_BALDE = "; há ocorrência(s) no balde de revisão manual"


def situar_duplicidade_no_corte(achados: Sequence[Achado],
                                fechado: FechadoPorSaldoZero | None,
                                balde_pos: Sequence[ItemRevisao]) -> list[Achado]:
    """O alerta de parcela repetida nasce no casamento,
    que nao conhece o corte, e diz "ha ocorrencia(s) no balde". Quando as
    ocorrencias sem destino foram TODAS pro periodo zerado, isso deixou de ser
    verdade: a frase passa a dizer onde elas estao (fato). Numero e nivel do
    alerta nao mudam; so' o texto."""
    if fechado is None or not fechado.balde:
        return list(achados)
    no_fechado = {l.numero: item for item in fechado.balde
                  for l in item.lancamentos}
    no_pos = {l.numero for item in balde_pos for l in item.lancamentos}
    saida = []
    for a in achados:
        lotes = set((a.referencia or "").split(", "))
        if (a.codigo == "possivel_duplicidade" and a.mensagem.endswith(_NO_BALDE)
                and lotes & set(no_fechado) and not lotes & no_pos):
            zero = max((fechado.zerou_em[no_fechado[l].identificador]
                        for l in lotes & set(no_fechado)),
                       key=lambda z: z.data)
            a = replace(a, mensagem=(
                a.mensagem[:-len(_NO_BALDE)]
                + f"; as ocorrências sem destino estão no período já zerado "
                  f"(a conta zerou em {zero.data.strftime('%d/%m/%Y')})"))
        saida.append(a)
    return saida

"""Ponte do saldo: saldo anterior + compras -> saldo do Dominio.

Core puro, zero I/O, NUNCA forca a fechar. A ponte e' a identidade que o
self_check_composicao ja confere (gap == Σ(D−C) do balde + Σ fora) aberta em
linhas -- por isso nao tem juiz proprio: a diferenca dela E' o residuo do
self_check, e o status que a tela imprime e' o do veredito.

Le as NFs DEPOIS de `aplicar` (todas: abertas, quitadas e as sem compra que
consumiram o saldo anterior), entao reage a alocacao manual sem codigo de
reatividade -- a tela ja reroda conferir() a cada decisao.

Topo fecha por construcao com a composicao (compor() soma as mesmas familias
de quitacao); o teste cobra os dois caminhos mesmo assim.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from core.modelo import (NF, ComposicaoItem, DecisaoManual, DestinoAlocacao,
                         ItemRevisao, PonteSaldo, TotaisComposicao)

ZERO = Decimal("0.00")


def _soma(valores) -> Decimal:
    return sum(valores, ZERO)


def montar_ponte(nfs: Sequence[NF], itens: Sequence[ComposicaoItem],
                 balde: Sequence[ItemRevisao],
                 decisoes: Sequence[DecisaoManual],
                 saldo_anterior: Decimal, saldo_final: Decimal,
                 itens_fechados: Sequence[ComposicaoItem] = (),
                 balde_fechado: Sequence[ItemRevisao] = ()) -> PonteSaldo:
    """`nfs` sao TODAS (pos-corte + periodo zerado): o topo soma a razao
    inteira. `itens`/`balde` sao o pos-corte; `itens_fechados`/`balde_fechado`,
    o que o corte por saldo zero tirou -- vazios sem corte."""
    com_compra = [nf for nf in nfs if nf.data_compra is not None]
    # D3: o que o contador decidiu fica TODO na linha "alocado a mao", pelo
    # liquido -- inclusive a compra nova (credito, entra negativo). "Compras
    # do periodo" continua sendo so' o que a razao trouxe como compra.
    na_composicao = [d for d in decisoes
                     if d.destino is not DestinoAlocacao.FORA_DA_COMPOSICAO]
    fora = [d for d in decisoes
            if d.destino is DestinoAlocacao.FORA_DA_COMPOSICAO]
    lancs_balde = [l for item in balde for l in item.lancamentos]

    total_em_aberto = _soma(i.saldo_aberto for i in itens)
    total_fechado = _soma(i.saldo_aberto for i in itens_fechados)
    balde_debitos = _soma(l.debito for l in lancs_balde)
    balde_creditos = _soma(l.credito for l in lancs_balde)
    total_fora = _soma(d.valor for d in fora)
    return PonteSaldo(
        # abs como compor()/nao_detalhado: o mesmo numero da linha da tabela
        saldo_anterior=abs(saldo_anterior),
        total_compras=_soma(nf.valor_compra for nf in com_compra
                            if not nf.transferencia
                            and not nf.criada_manualmente),
        total_transferencias=_soma(nf.valor_compra for nf in com_compra
                                   if nf.transferencia),
        total_pago=_soma(nf.total_pago for nf in nfs),
        total_retido=_soma(nf.total_retido for nf in nfs),
        total_baixa_adiantamento=_soma(nf.total_baixado for nf in nfs),
        total_alocado_manual=_soma(d.valor for d in na_composicao),
        total_em_aberto_nf_a_nf=total_em_aberto + total_fechado,
        # pelo LIQUIDO do balde do periodo zerado: e' o que compensa o aberto
        # de la (a trava do corte garante a igualdade ao centavo)
        total_compensado_saldo_zero=_soma(
            l.debito - l.credito for item in balde_fechado
            for l in item.lancamentos),
        total_em_aberto=total_em_aberto,
        balde_debitos=balde_debitos,
        balde_creditos=balde_creditos,
        total_fora_composicao=total_fora,
        saldo_apurado=(total_em_aberto - balde_debitos + balde_creditos
                       - total_fora),
        saldo_dominio=-saldo_final,
    )


def totalizar(linhas: Sequence[ComposicaoItem], nfs: Sequence[NF],
              ponte: PonteSaldo,
              itens_fechados: Sequence[ComposicaoItem] = ()) -> TotaisComposicao:
    """A linha TOTAL de `linhas` (o que a tabela mostra: itens + quitadas) e o
    quanto da ponte fica FORA dela. "Valor compra" e "Total pago" do total
    somam so' as notas. A "entrada" que a coluna "Valor compra"
    deveria somar e' o trazido + compras + transferencias + compra nova
    manual (que a ponte guarda dentro do alocado a mao, D3). O que o corte
    por saldo zero tirou da tabela esta na secao propria, entao
    nao conta como "fora da tabela" -- a nota so' fala do anterior quitado."""
    # o "fora da tabela" (saldo anterior pago no periodo) e' medido sobre
    # TODAS as linhas, como sempre; os totais da linha TOTAL, so' sobre as
    # notas -- o valor das linhas sem nota mora em EM ABERTO
    valor_compra = _soma(i.valor_compra for i in linhas)
    total_pago = _soma(i.total_pago for i in linhas)
    notas = [i for i in linhas if i.e_nota]
    compra_nova = _soma(nf.valor_compra for nf in nfs if nf.criada_manualmente)
    entrada = (ponte.saldo_anterior + ponte.total_compras
               + ponte.total_transferencias + compra_nova)
    return TotaisComposicao(
        valor_compra=_soma(i.valor_compra for i in notas),
        total_pago=_soma(i.total_pago for i in notas),
        total_retido=_soma(i.total_retido for i in linhas),
        total_baixado=_soma(i.total_baixado for i in linhas),
        total_manual=_soma(i.total_manual for i in linhas),
        saldo_aberto=_soma(i.saldo_aberto for i in linhas),
        compra_fora_da_tabela=(entrada - valor_compra
                               - _soma(i.valor_compra for i in itens_fechados)),
        pago_fora_da_tabela=(ponte.total_pago - total_pago
                             - _soma(i.total_pago for i in itens_fechados)),
    )

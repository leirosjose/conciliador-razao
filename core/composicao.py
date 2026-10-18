"""Composicao do saldo por NF. Core puro, NUNCA forca a fechar.

COMPRA_PERIODO: um item por NF com compra no periodo e saldo em aberto.
SALDO_ANTERIOR: pagamentos a NFs sem compra consomem |saldo_anterior|; o resto
(nao detalhado), se != 0, vira um item proprio -- assim Σ saldo_aberto de TODOS
os itens reproduz |saldo_final| por construcao (e o veredito confere).

Idade mede contra data_referencia (fim do periodo do arquivo), NUNCA date.today().
Retencao: NF.retencoes ja entra no saldo via NF.saldo_aberto (saldo = compra -
pagamentos - retencoes).

Identidade da TABELA: em todo item, valor_compra - total_pago -
total_retido - total_baixado - total_manual == saldo_aberto. Cada familia de
quitacao vai no seu campo -- na linha de NF e na "(anterior)" igualmente -- e
o "Valor compra" da "(anterior)" e o saldo TRAZIDO (|saldo_anterior|): o que se
devia no inicio, menos o que o periodo quitou, e o que sobrou nao detalhado.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.modelo import ALVO_ANTERIOR, NF, ComposicaoItem, Origem

ZERO = Decimal("0.00")


def _ultima_quitacao(nf: NF) -> date | None:
    """Data do ultimo movimento que quitou a NF (pagamento, retencao, baixa,
    alocacao de pagamento multi-NF e alocacao manual -- a familia inteira).
    None se nada quitou. A coluna responde "quando mexeu por ultimo"."""
    datas = [l.data for l in nf.pagamentos + nf.retencoes + nf.baixas + nf.manuais]
    datas += [a.lancamento.data for a in nf.alocacoes]
    return max(datas, default=None)


def _pagamento_antes_da_emissao(nf: NF) -> date | None:
    """O primeiro pagamento casado (numerario ou parte de multi-NF) com
    data ANTERIOR a emissao. Comparacao de datas, sem dinheiro. So' em nota de
    verdade: transferencia e pago a maior nao tem emissao; alocacao manual e'
    decisao do contador, nao casamento do motor."""
    if nf.data_compra is None or nf.transferencia or nf.pago_a_maior:
        return None
    datas = [l.data for l in nf.pagamentos if l.data < nf.data_compra]
    datas += [a.lancamento.data for a in nf.alocacoes
              if a.lancamento.data < nf.data_compra]
    return min(datas, default=None)


def _item_de_nf(nf: NF, data_referencia: date | None) -> ComposicaoItem:
    """A linha de uma NF com compra no periodo -- a MESMA pra composicao (aberta)
    e pra secao de quitadas: um construtor so', pra que a quitada
    carregue tudo que a aberta carrega (idade, ultima quitacao, desempates,
    alocacao manual) e a identidade da tabela valha nas duas."""
    idade = ((data_referencia - nf.data_compra).days
             if data_referencia is not None else None)
    return ComposicaoItem(
        nf_numero=nf.numero,
        origem=(Origem.ALOCACAO_MANUAL if nf.criada_manualmente
                else Origem.TRANSFERENCIA_SALDO if nf.transferencia
                else Origem.PAGO_A_MAIOR if nf.pago_a_maior
                else Origem.COMPRA_PERIODO),
        valor_compra=nf.valor_compra,
        total_pago=nf.total_pago,             # familia de quitacao:
        total_retido=nf.total_retido,         # fonte unica na NF
        total_baixado=nf.total_baixado,
        total_manual=nf.total_manual,         # o valor, nao so a contagem
        saldo_aberto=nf.saldo_aberto,
        idade_dias=idade,
        data_compra=nf.data_compra,
        data_ultima_quitacao=_ultima_quitacao(nf),
        qtd_quitacoes=nf.qtd_quitacoes,
        # rastreabilidade: quais quitacoes desta NF vieram de
        # desempate, e por qual criterio -- a nota nasce na apresentacao
        desempates=tuple(d.criterio for d in nf.desempates),
        por_regra=tuple(r.regra for r in nf.por_regra),
        quitacoes_manuais=len(nf.manuais),
        pagamento_antes_da_emissao=_pagamento_antes_da_emissao(nf),
    )


def quitadas(nfs: list[NF], data_referencia: date | None) -> list[ComposicaoItem]:
    """NFs do periodo que FECHARAM: compra no periodo (ou linha
    criada a mao), saldo ZERO e compra positiva. Canal PROPRIO -- `compor()`
    continua devolvendo so' o que esta aberto, e a identidade do gap e os
    self_checks leem de la. Fora daqui, de proposito: residuo negativo dentro
    da tolerancia (saldo != 0, fica na composicao com a nota de arredondamento)
    e compra liquida zero ou negativa (cancelamento/estorno, nao quitacao)."""
    return [_item_de_nf(nf, data_referencia) for nf in nfs
            if nf.data_compra is not None
            and nf.saldo_aberto == ZERO
            and nf.valor_compra > ZERO]


def nao_detalhado(nfs: list[NF], saldo_anterior: Decimal) -> Decimal:
    """Quanto do saldo anterior NAO foi detalhado por lancamentos do periodo.

    Fonte UNICA da formula: compor() monta o item "(anterior)" com ela e a
    alocacao manual valida com ela o destino "(anterior)". Escrever a mesma conta
    nos dois lugares e como o numero comeca a divergir."""
    consumido = sum((nf.total_pago + nf.total_retido + nf.total_baixado
                     + nf.total_manual
                     for nf in nfs if nf.data_compra is None), ZERO)
    return abs(saldo_anterior) - consumido


def compor(nfs: list[NF], saldo_anterior: Decimal,
           data_referencia: date | None) -> list[ComposicaoItem]:
    itens: list[ComposicaoItem] = []
    # consumo do saldo anterior por NFs sem compra no periodo, UMA familia por
    # acumulador: a "(anterior)" mostra cada uma na sua coluna, como a
    # linha de NF -- nada se soma dentro de "pago"
    pagos_sem_compra = ZERO      # pagamentos em numerario (+ multi-NF)
    retidos_sem_compra = ZERO    # retencoes ligadas a NF sem compra
    baixas_sem_compra = ZERO     # baixas de adiantamento sem NF no periodo (identificadas)
    manual_sem_compra = ZERO     # alocado a mao contra o saldo anterior, pelo liquido
    manuais_sem_compra = 0       # ... e quantas quitacoes foram
    ultima_quitacao_anterior: date | None = None   # ultimo movimento sobre o saldo anterior

    for nf in nfs:
        if nf.data_compra is not None:                  # compra no periodo
            if nf.saldo_aberto != ZERO:                   # quitada: ver quitadas()
                itens.append(_item_de_nf(nf, data_referencia))
        else:                                            # sem compra -> consome saldo anterior
            # NF sem compra nunca tem alocacao (Fase 1.5 so aloca a NF com compra
            # aberta), entao total_pago aqui == soma dos pagamentos em numerario
            pagos_sem_compra += nf.total_pago
            retidos_sem_compra += nf.total_retido
            baixas_sem_compra += nf.total_baixado
            manual_sem_compra += nf.total_manual
            manuais_sem_compra += len(nf.manuais)
            quitacao = _ultima_quitacao(nf)
            if quitacao is not None and (ultima_quitacao_anterior is None
                                         or quitacao > ultima_quitacao_anterior):
                ultima_quitacao_anterior = quitacao

    # o item (anterior) aparece quando sobra saldo NAO detalhado OU quando uma
    # BAIXA consumiu o anterior (evidencia identificada, mesmo com resto 0,00 --
    # e' o que quem confere valida). Pagamento consumindo o anterior ate zerar segue o
    # comportamento de sempre (golden): sem resto, sem item.
    resto = nao_detalhado(nfs, saldo_anterior)           # fonte unica da formula
    if resto != ZERO or baixas_sem_compra != ZERO or manuais_sem_compra:
        itens.append(ComposicaoItem(
            nf_numero=ALVO_ANTERIOR,
            origem=Origem.SALDO_ANTERIOR,
            valor_compra=abs(saldo_anterior),            # saldo TRAZIDO; abs como nao_detalhado
            total_pago=pagos_sem_compra,
            total_retido=retidos_sem_compra,
            total_baixado=baixas_sem_compra,
            total_manual=manual_sem_compra,
            saldo_aberto=resto,
            idade_dias=None,
            data_compra=None,                            # anterior a janela do arquivo
            data_ultima_quitacao=ultima_quitacao_anterior,
            quitacoes_manuais=manuais_sem_compra,
        ))
    return itens

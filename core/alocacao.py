"""Alocacao MANUAL: o contador decide o que o motor nao decidiu.

Core puro, zero I/O, sem estado. Roda ESTRITAMENTE DEPOIS de todo o casamento
automatico — nenhuma decisao automatica enxerga alocacao manual, entao
`alocacoes=()` reproduz o comportamento de sempre POR CONSTRUCAO (e a monotonia
do balde continua valendo: ele so encolhe).

As alocacoes sao aplicadas NA ORDEM da lista (a ordem em que o contador
decidiu): cada uma enxerga o estado deixada pela anterior. Desfazer nao reverte
nada — o motor reroda do zero com a lista menor.

Alocacao invalida e IGNORADA e vira ErroAlocacao: o item CONTINUA no balde,
entao a identidade (gap == Σ do balde) segue fechando e o veredito segue
honesto. Erro de alocacao nao e divergencia contabil e nao entra no veredito.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from core.composicao import nao_detalhado
from core.modelo import (
    ALVO_ANTERIOR,
    AlocacaoManual,
    DecisaoManual,
    DestinoAlocacao,
    ErroAlocacao,
    ItemRevisao,
    NF,
    ResultadoCasamento,
)

ZERO = Decimal("0.00")

# NF-fantasma que recebe as quitacoes alocadas ao saldo anterior: sem
# data_compra, entao compor() a trata como "sem compra no periodo" e ela consome
# o nao detalhado, exatamente como a baixa de adiantamento ja fazia.
NF_ANTERIOR_MANUAL = "(alocação manual: saldo anterior)"

_MENSAGENS = {
    # regra de tela: FATO, nunca instrucao -- o erro diz o que aconteceu
    # e que a alocacao ficou sem efeito; o botao Desfazer esta ao lado
    "ITEM_INEXISTENTE": "este item não está mais entre os itens sem destino — o arquivo ou o "
                        "motor mudou; a alocação ficou sem efeito",
    "ITEM_JA_ALOCADO": "já há uma alocação para este item; esta ficou sem "
                       "efeito",
    "NF_INEXISTENTE": "NF {alvo} não existe nesta conta",
    "NF_QUITADA": "NF {alvo} já está quitada; a alocação ficou sem efeito",
    "ANTERIOR_QUITADO": "o saldo anterior já está todo detalhado",
    "ALVO_AUSENTE": "nenhuma linha de destino escolhida",
    "ROTULO_OBRIGATORIO": "falta a justificativa de por que este lançamento "
                          "não pertence à composição",
    "DESTINO_INCOMPATIVEL": "lançamento de débito não vira compra nova: só "
                            "linha aberta ou fora da composição",
    "NOME_EM_USO": "o nome {alvo} já é de uma linha desta conta; a alocação "
                   "ficou sem efeito",
}


@dataclass
class ResultadoAlocacao:
    """Saida de `aplicar`: as NFs (com as quitacoes manuais anexadas), o balde
    que SOBROU, as decisoes aplicadas e os erros do que nao pode ser aplicado."""
    nfs: list[NF] = field(default_factory=list)
    balde: list[ItemRevisao] = field(default_factory=list)
    decisoes: list[DecisaoManual] = field(default_factory=list)
    erros: list[ErroAlocacao] = field(default_factory=list)


def _liquido(item: ItemRevisao) -> Decimal:
    """O que o item pesa: Σ(debito − credito). Positivo QUITA um titulo,
    negativo REABRE."""
    return sum((l.debito - l.credito for l in item.lancamentos), ZERO)


def _rotulo_padrao(item: ItemRevisao) -> str:
    """Nome da linha nova quando o contador nao deu um: o LOTE, que e o numero
    com que ele acha o lancamento no Dominio."""
    return f"(manual: lote {item.lancamentos[0].numero})"


def _erro(alocacao: AlocacaoManual, codigo: str, **campos) -> ErroAlocacao:
    return ErroAlocacao(alocacao=alocacao, codigo=codigo,
                        mensagem=_MENSAGENS[codigo].format(**campos))


def aplicar(resultado: ResultadoCasamento,
            alocacoes: Sequence[AlocacaoManual] = (),
            saldo_anterior: Decimal = ZERO) -> ResultadoAlocacao:
    nfs = list(resultado.nfs)
    balde = list(resultado.balde)
    decisoes: list[DecisaoManual] = []
    erros: list[ErroAlocacao] = []
    aplicados: set[str] = set()

    def _nf_anterior() -> NF:
        for nf in nfs:
            if nf.numero == NF_ANTERIOR_MANUAL:
                return nf
        nova = NF(numero=NF_ANTERIOR_MANUAL)      # sem data_compra: vai pro anterior
        nfs.append(nova)
        return nova

    for alocacao in alocacoes:
        if alocacao.item_id in aplicados:
            erros.append(_erro(alocacao, "ITEM_JA_ALOCADO"))
            continue
        item = next((i for i in balde
                     if i.identificador == alocacao.item_id), None)
        if item is None:
            erros.append(_erro(alocacao, "ITEM_INEXISTENTE"))
            continue

        liquido = _liquido(item)
        if alocacao.destino is DestinoAlocacao.LINHA_ABERTA:
            if not alocacao.alvo:
                erros.append(_erro(alocacao, "ALVO_AUSENTE"))
                continue
            if alocacao.alvo == ALVO_ANTERIOR:
                # so' bloqueia quando o lancamento QUITA: credito reabre saldo
                # anterior e e' lancamento legitimo
                if nao_detalhado(nfs, saldo_anterior) <= ZERO and liquido > ZERO:
                    erros.append(_erro(alocacao, "ANTERIOR_QUITADO"))
                    continue
                destino = _nf_anterior()
            else:
                destino = next((nf for nf in nfs
                                if nf.numero == alocacao.alvo
                                and nf.data_compra is not None), None)
                if destino is None:
                    erros.append(_erro(alocacao, "NF_INEXISTENTE",
                                       alvo=alocacao.alvo))
                    continue
                # idem: credito REABRE titulo quitado, e legitimo
                if destino.saldo_aberto <= ZERO and liquido > ZERO:
                    erros.append(_erro(alocacao, "NF_QUITADA", alvo=alocacao.alvo))
                    continue
            destino.manuais.extend(item.lancamentos)

        elif alocacao.destino is DestinoAlocacao.COMPRA_NOVA:
            # debito liquido geraria linha de composicao com valor de compra
            # NEGATIVO -- nao e "compra nova", e outra coisa
            if liquido > ZERO:
                erros.append(_erro(alocacao, "DESTINO_INCOMPATIVEL"))
                continue
            nome = alocacao.rotulo or _rotulo_padrao(item)
            # o alvo de uma linha e' o NOME dela -- dois com o
            # mesmo nome e a alocacao seguinte cai na primeira, nao na escolhida
            if (nome in (ALVO_ANTERIOR, NF_ANTERIOR_MANUAL)
                    or any(nf.numero == nome for nf in nfs)):
                erros.append(_erro(alocacao, "NOME_EM_USO", alvo=nome))
                continue
            nfs.append(NF(
                numero=nome,
                valor_compra=-liquido,            # credito liquido vira a compra
                data_compra=item.lancamentos[0].data,
                criada_manualmente=True,
                # evidencia de onde a linha veio (o corte por saldo zero
                # precisa saber de que lado do zero ela caiu)
                compras=list(item.lancamentos),
            ))

        else:                                     # FORA_DA_COMPOSICAO
            # o rotulo vai pro cliente na secao de decisoes: decisao sem motivo
            # nao serve de entrega
            if not alocacao.rotulo.strip():
                erros.append(_erro(alocacao, "ROTULO_OBRIGATORIO"))
                continue

        balde.remove(item)
        aplicados.add(alocacao.item_id)
        decisoes.append(DecisaoManual(item=item, destino=alocacao.destino,
                                      alvo=alocacao.alvo, rotulo=alocacao.rotulo,
                                      criterio_sugerido=alocacao.criterio_sugerido))

    return ResultadoAlocacao(nfs=nfs, balde=balde, decisoes=decisoes, erros=erros)

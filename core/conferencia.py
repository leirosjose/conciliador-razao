"""Orquestrador do core: confere UMA conta e devolve o bundle que a casca de UI
renderiza. Puro, zero I/O, NUNCA calcula dinheiro -- so encadeia o core na ordem
certa e agrega o que ele produziu.

Client-agnostic: recebe o classificador por PARAMETRO. O regex per-cliente vive
em parser/historico.py (FORA do core); este modulo NAO importa parser/ -- so
depende do contrato `Classificador` (qualquer objeto com .classificar).

Cadeia: classifica cada lancamento -> casar (NFs + balde) -> corte por saldo
zero (particiona, nunca refaz o casamento) -> alocacao manual -> compor
(itens) -> self_check_parsing + reconciliacao + alertas. saldo_final vem de
Conta.saldo_final (fonte unica), nao recalculado aqui.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol, Sequence

from core.alocacao import aplicar
from core.casamento import casar
from core.classifica import Classificacao
from core.composicao import compor
from core.composicao import quitadas as nfs_quitadas
from core.corte import alerta_periodo_zerado, localizar_corte, particionar, situar_duplicidade_no_corte
from core.modelo import (
    AlocacaoManual,
    Conta,
    DestinoAlocacao,
    FechadoPorSaldoZero,
    Lancamento,
    Nivel,
    ResultadoCasamento,
    ResultadoConferencia,
)
from core.ponte import montar_ponte, totalizar
from core.sugestao import sugerir
from core.veredito import alertas_por_item, compra_repetida, duplicidade_de_emissao, reconciliar, self_check_parsing

ZERO = Decimal("0.00")


class Classificador(Protocol):
    """Contrato do classificador injetado (impl. concreta vive no parser)."""
    def classificar(self, lanc: Lancamento) -> Classificacao: ...


def conferir(conta: Conta, classificador: Classificador,
             alocacoes: Sequence[AlocacaoManual] = ()) -> ResultadoConferencia:
    """`alocacoes` sao as decisoes MANUAIS do contador, aplicadas depois
    de todo o casamento automatico. Sem elas (o default), a saida e identica a
    de sempre — o motor nao guarda estado: (razao + alocacoes) -> resultado."""
    pares = [(l, classificador.classificar(l)) for l in conta.lancamentos]
    resultado = casar(pares, conta.saldo_anterior)
    parsing = self_check_parsing(conta)
    manual = aplicar(resultado, alocacoes, conta.saldo_anterior)
    # corte por saldo zero, DEPOIS das decisoes do contador -- uma
    # alocacao que liga os dois lados de um zero e' cruzamento e faz o corte
    # recuar (a decisao dele vale; o corte se ajusta). O casamento rodou na
    # razao INTEIRA e os achados dele valem pro periodo zerado tambem; aqui so'
    # se divide o que existe. Sem corte, `pos` e' o de sempre. Com corte, o
    # saldo anterior esta todo no periodo zerado.
    decidido = ResultadoCasamento(nfs=manual.nfs, balde=manual.balde,
                                  achados=resultado.achados)
    corte, achados_corte = localizar_corte(
        conta.lancamentos, conta.saldo_anterior, decidido,
        leitura_ok=all(a.nivel is Nivel.OK for a in parsing),
        decisoes=manual.decisoes)
    particao = particionar(decidido, conta.lancamentos, corte)
    pos = particao.resultado
    anterior_pos = conta.saldo_anterior if corte is None else ZERO
    # propor destino pro que SOBROU no balde do pos-corte. Depois de
    # `aplicar` de proposito -- a sugestao le o estado que as decisoes do
    # contador ja deixaram, e item alocado leva a sua embora sem codigo de
    # limpeza. Nao entra em `compor` nem nos self_checks: sugestao nao move
    # dinheiro.
    sugerir(pos.balde, pos.nfs, pares)
    itens = compor(pos.nfs, anterior_pos, conta.data_fim_periodo)
    # das NFs DEPOIS das alocacoes -- a NF que o contador
    # quitou a mao ate zero sai de `itens` e entra aqui, com a marca. As
    # que fecharam NF a NF no periodo zerado tambem (essas sao quitacao provada)
    quitadas = (nfs_quitadas(pos.nfs, conta.data_fim_periodo)
                + nfs_quitadas(particao.nfs_fechadas, conta.data_fim_periodo))
    fechado = None
    if corte is not None:
        fechado = FechadoPorSaldoZero(
            data=corte.lancamento.data, lote=corte.lancamento.numero,
            zeros=corte.zeros,
            itens=compor(particao.nfs_fechadas, conta.saldo_anterior,
                         conta.data_fim_periodo),
            balde=particao.balde_fechado, zerou_em=particao.zerou_em)
    itens_fechados = fechado.itens if fechado else []
    fora = tuple(d for d in manual.decisoes
                 if d.destino is DestinoAlocacao.FORA_DA_COMPOSICAO)
    achados = (parsing
               + reconciliar(itens, conta.saldo_final, tuple(pos.balde), fora)
               + alertas_por_item(itens)
               # juros/desconto do periodo zerado continuam alertando; o
               # pedido de razao anterior nao (o saldo final nao depende dele)
               + alertas_por_item(itens_fechados, nao_detalhados=False)
               # NFs gemeas — mesmo valor, mesma data de
               # emissao. AQUI porque este e o unico ponto que ve as abertas E
               # as quitadas: a gemea pode ja ter fechado e a duplicidade
               # continua existindo. E as do periodo zerado (uma gemea pode
               # estar la). ALERTA; nao entra em identidade nenhuma.
               + duplicidade_de_emissao(itens + quitadas + itens_fechados)
               # NF lancada 2+ vezes com o mesmo valor. Le as LINHAS de
               # compra (NF.compras), entao recebe as NFs, nao os itens -- as
               # dos dois lados do corte. ALERTA; composicao intacta.
               + compra_repetida(pos.nfs + particao.nfs_fechadas)
               # sinalizacoes do casamento; a de parcela repetida
               # diz onde as ocorrencias estao depois do corte
               + situar_duplicidade_no_corte(resultado.achados, fechado, pos.balde)
               + achados_corte + alerta_periodo_zerado(fechado))
    # dos MESMOS nfs/itens/balde/decisoes que o self_check le -- a ponte
    # e' a identidade dele aberta em linhas, nao uma segunda conta. O topo soma
    # a razao INTEIRA (pos-corte + periodo zerado).
    ponte = montar_ponte(pos.nfs + particao.nfs_fechadas, itens, pos.balde,
                         manual.decisoes, conta.saldo_anterior, conta.saldo_final,
                         itens_fechados, particao.balde_fechado)
    resultado_final = ResultadoConferencia(
        conta=conta,
        itens=itens,
        quitadas=quitadas,
        balde=pos.balde,
        achados=achados,
        decisoes=manual.decisoes,
        erros_alocacao=manual.erros,
        ponte=ponte,
        # a linha TOTAL soma o que a tabela MOSTRA (itens + quitadas)
        totais_tabela=totalizar(itens + quitadas,
                                pos.nfs + particao.nfs_fechadas, ponte,
                                itens_fechados),
        fechado=fechado,
        nfs=pos.nfs + particao.nfs_fechadas,
    )
    # o total do recorte padrao da tela (so' EM ABERTO != 0), do MESMO
    # recorte que a tela le (ResultadoConferencia.itens_em_aberto)
    resultado_final.totais_em_aberto = totalizar(
        resultado_final.itens_em_aberto, pos.nfs + particao.nfs_fechadas, ponte,
        itens_fechados)
    return resultado_final

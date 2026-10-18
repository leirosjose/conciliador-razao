"""Casca de orquestracao: escolhe o parser e o classificador (config de app) e
chama o core. SEM logica contabil, SEM money math -- so fiacao. O nucleo da
ordem (classifica -> casar -> compor -> veredito) vive em core.conferencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from typing import Mapping, Sequence

from core.conferencia import conferir
from core.modelo import AlocacaoManual, Conta, ResultadoConferencia
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico


# Tetos da ENTRADA por upload (o modo banco tem os proprios limites e nao passa por aqui): acima deles o arquivo
# inteiro e recusado depois da leitura e antes do motor -- e' o motor que custa tempo e memoria no servidor.
MAX_LANCAMENTOS_POR_CONTA = 5000
MAX_CONTAS_POR_ARQUIVO = 100


class ArquivoAcimaDoLimite(Exception):
    """Arquivo lido que passa de um teto de entrada; so carrega os fatos (a frase nasce na apresentacao)."""
    def __init__(self, total_contas: int, contas_acima: list[tuple[str, int]]):
        super().__init__("arquivo acima do limite de entrada")
        self.total_contas = total_contas
        self.contas_acima = contas_acima


def chaves_das_contas(contas) -> list[str]:
    """Chave de estado de cada conta do arquivo: o codigo; repetido
    ganha _2, _3... na ordem do arquivo. Fonte unica pra tela e pipeline."""
    from relatorio.nomes import nomes_sem_colisao
    return nomes_sem_colisao([c.codigo for c in contas])


@dataclass
class ResultadoProcessamento:
    """O que a tela recebe: os resultados do motor + metadados da LEITURA.
    arquivo_reparado e' rastro PROGRAMATICO do reparo BIFF (testes/diagnostico);
    a UI nao avisa mais — o rastro humano e' o logging.info do parser.
    Fiacao, zero logica."""
    resultados: list[ResultadoConferencia] = field(default_factory=list)
    arquivo_reparado: bool = False
    rotulo_numero: str = "Lote"


def processar_excel(
        source,
        alocacoes_por_conta: Mapping[str, Sequence[AlocacaoManual]] | None = None,
        nome: str | None = None,
) -> ResultadoProcessamento:
    """source = caminho de um .xls do Dominio. Devolve um ResultadoConferencia
    por conta de fornecedor (o golden tem 1; o formato suporta N), mais a
    anotacao de reparo da leitura.

    `alocacoes_por_conta` sao as decisoes manuais do contador, pela CHAVE
    da conta (`chaves_das_contas`: o codigo; o codigo repetido no arquivo ganha
    _2, _3...) — uma razao traz N contas e cada uma tem seu balde. Sem elas, saida
    identica a de sempre. Caminho unico de proposito: a tela renderiza estes
    resultados e a exportacao usa os MESMOS, entao o Excel nunca diverge do que
    esta na tela."""
    parser = ExcelParser()
    contas = parser.parse(source, nome=nome)   # nome do upload nas mensagens
    _confere_tetos_de_entrada(contas)
    resultado = processar_contas(contas, alocacoes_por_conta)
    resultado.arquivo_reparado = parser.reparado
    resultado.rotulo_numero = parser.rotulo_numero
    return resultado


def _confere_tetos_de_entrada(contas: Sequence[Conta]) -> None:
    """Conta so' o que a leitura trouxe; a de contas vem primeiro (e' a mais barata)."""
    if len(contas) > MAX_CONTAS_POR_ARQUIVO:
        raise ArquivoAcimaDoLimite(len(contas), [])
    acima = [(c.codigo, len(c.lancamentos)) for c in contas if len(c.lancamentos) > MAX_LANCAMENTOS_POR_CONTA]
    if acima:
        raise ArquivoAcimaDoLimite(len(contas), acima)


def processar_contas(
        contas: Sequence[Conta],
        alocacoes_por_conta: Mapping[str, Sequence[AlocacaoManual]] | None = None,
) -> ResultadoProcessamento:
    """Caminho único das Contas já lidas até o core, sem I/O ou conta de dinheiro."""
    alocacoes = alocacoes_por_conta or {}
    # classificador da própria conta; código repetido ganha _2.
    chaves = chaves_das_contas(contas)
    return ResultadoProcessamento(
        resultados=[conferir(conta, ClassificadorHistorico(nome_conta=conta.nome),
                             alocacoes.get(chave, ()))
                    for conta, chave in zip(contas, chaves)],
    )

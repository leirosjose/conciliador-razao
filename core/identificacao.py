"""Identificador estavel de item do balde. Core puro, zero I/O.

O contador aloca um item do balde pela tela e o id volta pro motor na execucao
seguinte. O id precisa sobreviver a EVOLUCAO DO MOTOR: deriva do CONTEUDO DA
RAZAO (campos do lancamento) mais o ordinal da chave NA ORDEM DA RAZAO, nunca da
posicao na lista do balde. Ja aconteceu: a ordem do balde mudou (empates
foram pro fim, no passe 2b) sem que uma virgula da razao mudasse.

`hashlib`, NUNCA o `hash()` embutido — este e randomizado por PYTHONHASHSEED e
daria id diferente a cada processo, quebrando a alocacao entre reruns.
"""
from __future__ import annotations

import hashlib
from typing import Sequence

from core.modelo import Lancamento

TAMANHO = 12                 # hex suficiente pra uma razao; id e' de sessao, nao de banco


def _chave(lanc: Lancamento) -> str:
    """Os campos que IDENTIFICAM a linha na razao. Dinheiro entra com 2 casas
    fixas: Decimal('100.0') e Decimal('100.00') sao a mesma linha e nao podem
    gerar ids diferentes por representacao."""
    return "|".join((lanc.data.isoformat(), lanc.numero,
                     f"{lanc.debito:.2f}", f"{lanc.credito:.2f}",
                     lanc.cta_part, lanc.historico))


def _digest(bruto: str) -> str:
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:TAMANHO]


def ids_da_razao(lancamentos: Sequence[Lancamento]) -> list[str]:
    """Um id por lancamento, NA ORDEM DA RAZAO. Linhas identicas (mesma chave)
    sao desempatadas pelo ordinal de ocorrencia — sao itens distintos e nao
    podem colidir."""
    vistos: dict[str, int] = {}
    ids: list[str] = []
    for lanc in lancamentos:
        chave = _chave(lanc)
        ordinal = vistos.get(chave, 0)
        vistos[chave] = ordinal + 1
        ids.append(_digest(f"{chave}|#{ordinal}"))
    return ids


def id_item(ids: Sequence[str]) -> str:
    """Id do ITEM do balde a partir dos ids dos lancamentos dele. Item de um
    lancamento so (o caso de hoje) herda o id dele — sem hash de hash."""
    if len(ids) == 1:
        return ids[0]
    return _digest("|".join(ids))

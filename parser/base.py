"""Interface UNICA do parser, source-agnostic: qualquer fonte -> list[Conta].

excel.py e' a implementacao; outra fonte entraria atras DESTA mesma interface.
O core contabil nao sabe de onde veio nem pra onde vai.

O retorno e' list[Conta] (cada Conta CONTEM seus
Lancamento), porque o self-check precisa de dado nivel-conta (saldo anterior,
'Total da conta'). Mesmo espirito: fonte -> objetos de dominio, nao celulas.
"""
from __future__ import annotations

from typing import Protocol

from core.modelo import Conta


class RazaoParser(Protocol):
    def parse(self, source) -> list[Conta]:
        """Le a razao de `source` (caminho de arquivo) e devolve as contas."""
        ...

"""Modelo de classificacao de lancamento (core puro, SEM regex).

O regex da FIRMA vive em parser/historico.py e PRODUZ estes objetos; o core
os CONSOME. RETENCAO e BAIXA_ADIANTAMENTO sao a mesma familia de quitacao
sem numerario: saldo_NF = compra - (pagamentos + retencoes + baixas).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Tipo(Enum):
    COMPRA = "COMPRA"
    PAGAMENTO = "PAGAMENTO"
    RETENCAO = "RETENCAO"
    BAIXA_ADIANTAMENTO = "BAIXA_ADIANTAMENTO"   # compensacao de adiantamento (quitacao)
    ESTORNO = "ESTORNO"         # reverte uma operacao ANTERIOR da propria conta
    # saldo migrando entre contas contabeis
    # do MESMO fornecedor — matriz e filial cadastradas separadamente. Nao e'
    # compra nem pagamento: o DEBITO quita como baixa, o CREDITO e saldo
    # chegando de um razao que nao esta neste arquivo.
    TRANSFERENCIA_SALDO = "TRANSFERENCIA_SALDO"
    # credito do fornecedor que nao e' compra ("Recebimento conf.").
    # So' o NOME muda: o destino continua o balde.
    RECEBIMENTO = "RECEBIMENTO"
    OUTRO = "OUTRO"


@dataclass
class Classificacao:
    tipo: Tipo
    nf_numero: str | None = None        # 1 NF distinta citada; 2+ -> None (ambiguo)
    nfs_citadas: tuple[str, ...] = ()   # TODAS as citadas, na ordem (insumo
                                        # do casamento um-pra-muitos)
    parcela: int | None = None          # o k de "Parcela k de M" / "kª PARCELA"
    parcela_de: int | None = None       # o M declarado (desempate por serie)
    # SO em Tipo.ESTORNO — que operacao o historico declara reverter. E a
    # PROVA que o pareamento exige (core/estorno.py): sem declaracao nao ha
    # par, e quem decide e o conferente.
    estorna: Tipo | None = None
    # o valor que o historico DECLARA pra a parcela ("Valor de
    # R$ 541,37 (Parcela 1 de 2)"), que pode diferir do pago quando ha juros.
    # None quando o historico nao declara ou declara de forma ambigua — nunca
    # 0.00, que seria um valor afirmando ser zero.
    valor_parcela: Decimal | None = None

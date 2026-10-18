"""Opcoes do seletor "Alocar em..." da alocacao manual.

Camada de APRESENTACAO: ordena e rotula o que o contador ve no seletor. NAO
decide nada — quem valida destino, recusa NF quitada e barra debito em compra
nova e o core (core/alocacao.py). Aqui so' se escolhe a ORDEM em que as opcoes
aparecem e o texto de cada uma.

Modulo PROPRIO, e nao dentro de app/apresentacao.py, pelo mesmo motivo da
materialidade: aquele modulo declara "SEM aritmetica de dinheiro" e a
regra vale a pena manter crispa. A UNICA conta desta camada — a distancia entre
o valor do item e o saldo de cada linha, que da a ordem — fica aqui, isolada e
nomeada. A dependencia e' de mao unica: destinos -> apresentacao.

Ordem pensada pra quem procura: casamento exato de valor no topo, depois
proximidade, depois a mais antiga (habito de FIFO). Ordenar NAO e regra de
negocio: nada muda na composicao por causa desta lista.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.apresentacao import ROTULO_ANTERIOR, data_br, moeda_br, nome_de_linha
from core.modelo import ComposicaoItem, DestinoAlocacao, Origem

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Opcao:
    """Uma opcao do seletor. `destino` e `alvo` vao direto pra AlocacaoManual —
    a tela nao monta nada, so' repassa (casca sem regra)."""
    destino: DestinoAlocacao
    alvo: str
    rotulo: str
    pede_rotulo: bool = False          # a tela mostra o campo de texto
    rotulo_obrigatorio: bool = False   # ... e o core recusa sem ele
    sugerida: bool = False             # e a proposta do motor


def _rotulo_linha(item: ComposicaoItem) -> str:
    if item.origem is Origem.SALDO_ANTERIOR:
        # o MESMO nome da tabela: duas telas nao podem chamar a mesma
        # linha de coisas diferentes
        return (f"{ROTULO_ANTERIOR} · não detalhado "
                f"{moeda_br(item.saldo_aberto)}")
    if item.origem is Origem.TRANSFERENCIA_SALDO:
        # quem escolhe precisa saber que esta linha nao
        # e' uma nota — e' saldo que chegou da conta-irma, e o detalhe NF a NF
        # nao esta neste arquivo. A DATA e' a da chegada, nao de uma emissao.
        return (f"{item.nf_numero} · saldo transferido "
                f"{moeda_br(item.saldo_aberto)} · chegou "
                f"{data_br(item.data_compra)}")
    fim = (" · criada nesta sessão" if item.origem is Origem.ALOCACAO_MANUAL
           else f" · NF no razão {data_br(item.data_compra)}")
    return (f"{nome_de_linha(item.nf_numero)} · em aberto "
            f"{moeda_br(item.saldo_aberto)}{fim}")


def _distancia(item: ComposicaoItem, quantia: Decimal) -> Decimal:
    """Quao perto o saldo desta linha esta do valor do item. `quantia` chega em
    modulo: credito procura linha do mesmo TAMANHO, nao do mesmo sinal."""
    return abs(item.saldo_aberto - quantia)


def _chave_ordem(item: ComposicaoItem, quantia: Decimal):
    # sem data (o "(anterior)") vai pro fim do desempate, nao pro topo
    return (_distancia(item, quantia),
            item.data_compra or date.max,
            item.nf_numero)


def _e_a_sugerida(item: ComposicaoItem, sugestao) -> bool:
    return (sugestao is not None
            and sugestao.destino is DestinoAlocacao.LINHA_ABERTA
            and sugestao.alvo == item.nf_numero)


def opcoes_de_alocacao(itens: list[ComposicaoItem],
                       valor_do_item: Decimal,
                       sugestao=None) -> list[Opcao]:
    """As linhas ABERTAS da composicao (NFs, linhas criadas na sessao e o saldo
    anterior nao detalhado), ordenadas por proximidade, mais as duas opcoes que
    nao apontam pra linha nenhuma.

    `sugestao` apenas MARCA a opcao correspondente — a ordem nao muda. A
    proposta do motor frequentemente NAO e a linha mais proxima (num caso: um
    pagamento de 553,12 sugerido pra uma NF com 1.082,74 em aberto, porque o
    historico declara 2 x 541,37), e reordenar por ela brigaria com a razao de
    ser da ordem atual: quem procura a linha a mao procura por valor."""
    quantia = abs(valor_do_item)
    abertas = [i for i in itens if i.saldo_aberto > ZERO]
    abertas.sort(key=lambda i: _chave_ordem(i, quantia))
    opcoes = [Opcao(destino=DestinoAlocacao.LINHA_ABERTA,
                    alvo=i.nf_numero,
                    rotulo=(f"★ sugerida · {_rotulo_linha(i)}"
                            if _e_a_sugerida(i, sugestao) else _rotulo_linha(i)),
                    sugerida=_e_a_sugerida(i, sugestao))
              for i in abertas]
    opcoes.append(Opcao(destino=DestinoAlocacao.COMPRA_NOVA, alvo="",
                        rotulo="— compra em aberto nova",
                        pede_rotulo=True))
    opcoes.append(Opcao(destino=DestinoAlocacao.FORA_DA_COMPOSICAO, alvo="",
                        rotulo="— não pertence à composição",
                        pede_rotulo=True, rotulo_obrigatorio=True))
    return opcoes


def indice_sugerido(opcoes: list[Opcao]) -> int | None:
    """A posicao da opcao sugerida na lista JA ORDENADA — e o que vai no
    `index=` do selectbox. None quando nao ha sugestao, ou quando a linha
    sugerida nao esta mais na lista (outra alocacao ja a quitou): o seletor
    volta a ficar em branco, nunca pre-seleciona a errada."""
    return next((i for i, o in enumerate(opcoes) if o.sugerida), None)

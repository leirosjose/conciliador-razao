"""As REGRAS de sugestao. Core puro; o seam vive em `core/sugestao.py`.

Cada regra e uma funcao pura `(item, ContextoSugestao) -> Sugestao | None`,
registrada em `core.sugestao.REGRAS`. Nenhuma delas casa nada: o item continua
no balde, o gap nao muda, e o contador confirma na tela em um clique.

A fronteira com o casamento e estrutural, nao convencional: `sugerir()` roda
DEPOIS de `casar()`, entao so' ve o que sobrou no balde. Tudo que uma regra
CASA resolveu (a serie declarada, o desempate do passe 2b) ja saiu de
circulacao antes de qualquer regra daqui rodar.
"""
from __future__ import annotations

from decimal import Decimal

from core.modelo import NF, CriterioSugestao, DestinoAlocacao, ItemRevisao, Sugestao

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")


def _tol_parcela(m: int) -> Decimal:
    """A MESMA convencao de centavos do casamento (`_tol_parcela`): erro
    de arredondamento acumula ate ~M centavos numa NF dividida em M parcelas.
    As duas falam da mesma serie — divergir aqui seria a serie fechar num
    modulo e nao no outro."""
    return m * CENTAVO


def _abertas(ctx) -> list[NF]:
    """As linhas da composicao que ainda tem saldo. `saldo_aberto > ZERO` e,
    para ESTA regra, redundante com a aritmetica (um total positivo nunca casa
    com saldo zero ou negativo) — fica porque diz a regra onde se procura por
    ela, e porque a proxima regra a usar este helper pode nao ter essa sorte.
    Medido por mutacao: afrouxa-lo nao derruba teste nenhum hoje."""
    return [nf for nf in ctx.nfs
            if nf.data_compra is not None and nf.saldo_aberto > ZERO]


def serie_x_saldo_remanescente(item: ItemRevisao, ctx) -> Sugestao | None:
    """"Parcela k de M" cujo M x parcela bate com o SALDO REMANESCENTE de
    exatamente uma NF aberta.

    Momento do saldo: o saldo lido aqui e o de AGORA —
    depois de todo o casamento automatico E das alocacoes manuais desta execucao.
    Isso vale porque a regra SUGERE: um humano confere antes de qualquer coisa
    entrar na composicao. A consequencia e deliberada — se o saldo do alvo
    mudar, a aritmetica que sustentava a proposta expira e a regra para de
    sugerir, em vez de apontar pra um alvo em movimento.
    """
    declarada = ctx.declarada(item)          # item de UM lancamento so'
    if declarada is None:
        return None
    lanc, clf = declarada
    # `debito <= ZERO` tambem e redundante hoje (parcela zero daria total zero,
    # e nenhuma linha ABERTA tem saldo zero pra casar com ele) — mesma razao de
    # ficar: e a regra dita, nao deduzida de tres niveis de aritmetica adiante.
    if not clf.parcela_de or lanc.debito <= ZERO:
        return None

    m = clf.parcela_de
    total = m * lanc.debito
    fecham = [nf for nf in _abertas(ctx)
              if abs(nf.saldo_aberto - total) <= _tol_parcela(m)]
    if len(fecham) != 1:                     # 0 = sem prova; 2+ = ambiguidade
        return None

    escolhida = fecham[0]
    # a Fase 2 ja apurou quais NFs comportam este pagamento (EMPATE). Apontar
    # pra fora dessa lista seria contradizer a analise do proprio motor sem
    # evidencia nova. Item SEM candidatos apurados (SEM_VINCULO) nao tem
    # analise anterior pra contradizer.
    if item.candidatos and escolhida.numero not in item.candidatos:
        return None

    evidencia = {
        "parcela_declarada": lanc.debito,
        "parcelas": Decimal(m),
        # o saldo VAI na evidencia de proposito: e ele que torna legivel o
        # sumico da sugestao quando a conta muda
        "saldo_remanescente": escolhida.saldo_aberto,
    }
    # A MESMA parcela declarada duas vezes e a duplicidade que o casamento ja
    # alerta no painel. O contador precisa ve-la ONDE DECIDE, na caixinha —
    # um alerta a tres secoes de distancia nao chega na hora do clique.
    # So' o CONTADOR entra aqui (numero); a ressalva em texto nasce na
    # apresentacao, e o alerta do painel continua existindo.
    ocorrencias = _ocorrencias_da_serie(item, lanc, clf, ctx)
    if ocorrencias >= 2:
        evidencia["ocorrencias_da_serie"] = Decimal(ocorrencias)

    return Sugestao(
        destino=DestinoAlocacao.LINHA_ABERTA,
        alvo=escolhida.numero,
        criterio=CriterioSugestao.SERIE_X_SALDO_REMANESCENTE,
        evidencia=evidencia,
        candidatos=tuple(nf.numero for nf in _abertas(ctx)),
    )


def serie_x_valor_declarado(item: ItemRevisao, ctx) -> Sugestao | None:
    """"Parcela k de M" cujo M x VALOR DECLARADO bate com o valor de COMPRA de
    exatamente uma NF aberta.

    Contra o valor de COMPRA, e nao contra o saldo (que e a regra C): a serie
    declarada foi definida contra a NOTA quando ela foi emitida, nao contra o
    que sobrou dela depois — mesma semantica do desempate por serie.

    O valor PAGO difere do declarado quando ha juros de atraso. A diferenca vai
    na evidencia, explicita: e o numero que o contador confere antes de aceitar,
    e aceitar pode estourar o titulo (o `possivel_juros_manual` cobre,
    com a origem manual visivel).
    """
    declarada = ctx.declarada(item)
    if declarada is None:
        return None
    lanc, clf = declarada
    if not clf.parcela_de or clf.valor_parcela is None or lanc.debito <= ZERO:
        return None

    m = clf.parcela_de
    total = m * clf.valor_parcela
    fecham = [nf for nf in _abertas(ctx)
              if abs(nf.valor_compra - total) <= _tol_parcela(m)]
    if len(fecham) != 1:
        return None

    escolhida = fecham[0]
    if item.candidatos and escolhida.numero not in item.candidatos:
        return None

    return Sugestao(
        destino=DestinoAlocacao.LINHA_ABERTA,
        alvo=escolhida.numero,
        criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO,
        evidencia={
            "parcela_declarada": clf.valor_parcela,
            "parcelas": Decimal(m),
            "valor_compra": escolhida.valor_compra,
            "pago": lanc.debito,
            # explicita, nao deduzida: e o que o contador confere
            "diferenca": lanc.debito - clf.valor_parcela,
        },
        candidatos=tuple(nf.numero for nf in _abertas(ctx)),
    )


def _ancoras_ordinais(ctx, valor: Decimal) -> list[tuple[NF, dict[int, Decimal]]]:
    """NFs ABERTAS com uma serie de parcelas de `valor` ja casada POR NUMERO e
    com ordinal DECLARADO. Devolve (NF, {ordinal: valor}).

    "Por numero" e' o que faz a ancora valer: o pagamento so' entra na serie se
    o historico dele CITA a NF (prova), nunca se ele foi casado por valor ou por
    desempate — sugerir em cima de outra inferencia empilharia palpite sobre
    palpite. Duas parcelas e' o minimo: uma so' nao e' serie."""
    ancoras: list[tuple[NF, dict[int, Decimal]]] = []
    for nf in _abertas(ctx):
        ordinais: dict[int, Decimal] = {}
        for pago in nf.pagamentos:
            clf = ctx.classificacao(pago)
            if (clf is not None and clf.parcela
                    and clf.nf_numero == nf.numero
                    and pago.debito == valor):
                ordinais[clf.parcela] = pago.debito
        if len(ordinais) >= 2:
            ancoras.append((nf, ordinais))
    return ancoras


def continuidade_serie_ordinal(item: ItemRevisao, ctx) -> Sugestao | None:
    """Pagamento sem NF que declara um ORDINAL e CONTINUA uma serie ja casada
    por numero numa NF aberta, com aquele ordinal ainda livre.

    Diferente de C e D, nao precisa do M de "parcela k de M": um caso tipico so'
    declara "1ª PARCELA". Quem faz o papel do M e' a serie que ja esta casada.

    Duas coisas que a MEDICAO mandou NAO exigir:
    cadencia sem buraco — num caso medido a 3a parcela nao existe na razao — e
    ordem de data: a 1a parcela e' anterior a compra da NF (entrada/sinal). A
    regra propoe o DESTINO e nao opina sobre pagamento pre-emissao (isso e'
    outro aviso).

    Momento do saldo: estado FINAL, como C e D — vale
    porque SUGERE, e um humano confere antes de qualquer coisa entrar."""
    declarada = ctx.declarada(item)
    if declarada is None:
        return None
    lanc, clf = declarada
    if not clf.parcela or clf.nf_numero or lanc.debito <= ZERO:
        return None

    candidatas = [(nf, ordinais) for nf, ordinais in _ancoras_ordinais(ctx, lanc.debito)
                  if clf.parcela not in ordinais          # o ordinal tem que estar LIVRE
                  and nf.saldo_aberto >= lanc.debito]     # e nao pode estourar
    if len(candidatas) != 1:
        return None

    escolhida, ordinais = candidatas[0]
    if item.candidatos and escolhida.numero not in item.candidatos:
        return None

    return Sugestao(
        destino=DestinoAlocacao.LINHA_ABERTA,
        alvo=escolhida.numero,
        criterio=CriterioSugestao.CONTINUIDADE_SERIE_ORDINAL,
        evidencia={
            "parcela": lanc.debito,
            "ordinal": Decimal(clf.parcela),
            "casadas": Decimal(len(ordinais)),
            "primeiro_ordinal": Decimal(min(ordinais)),
            "ultimo_ordinal": Decimal(max(ordinais)),
            "saldo_aberto": escolhida.saldo_aberto,
        },
        candidatos=tuple(nf.numero for nf in _abertas(ctx)),
    )


def _ocorrencias_da_serie(item, lanc, clf, ctx) -> int:
    """Quantos itens do balde declaram a MESMA (parcela k de M, valor).

    A chave inclui o VALOR pelo mesmo motivo da duplicidade de parcela: series homonimas de
    compras diferentes nao sao conflito — "parcela 1 de 2" de 500,00 e de
    3.000,00 sao duas series legitimas."""
    chave = (clf.parcela, clf.parcela_de, lanc.debito)
    total = 0
    for outro in ctx.balde:
        declarada = ctx.declarada(outro)
        if declarada is None:
            continue
        l, c = declarada
        if (c.parcela, c.parcela_de, l.debito) == chave:
            total += 1
    return total

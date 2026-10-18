"""Self-check de PARSING. Prova que lemos a razao certo ANTES de
interpretar qualquer coisa.

3 checks OFICIAIS (golden do self-check, intactos):
  - self_check_total_debito : soma dos debitos  == 'Total da conta' debito
  - self_check_total_credito: soma dos creditos == 'Total da conta' credito
  - self_check_saldo_final  : saldo_anterior + Sdeb - Scred == saldo da ult. linha
Divergencia em qualquer um = ERRO (parser leu errado).

4o check (robustez extra): self_check_saldo_corrente -- saldo corrente
linha-a-linha. Divergencia = ALERTA, NUNCA ERRO.

No Excel nada REJEITA o parse: reporta. Rejeicao e' portao de PDF.
Nada e' forcado a fechar; quando nao bate, REPORTA a divergencia.

+ self_check_composicao -- Σ saldo_aberto(itens) == |saldo_final|?
Bate = composicao fecha; nao bate = ERRO (divergencia, nunca forca a fechar).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from core.modelo import (Achado, ComposicaoItem, Conta, DecisaoManual,
                         ItemRevisao, NF, Nivel, Origem)

ZERO = Decimal("0")
TOL = Decimal("0.01")        # tolerancia de centavos p/ conferir a identidade do balde
CEM = Decimal("100")
CENTESIMO = Decimal("0.01")  # casas do percentual do rotulo de desconto

# Teto do residuo que ainda se le como DESCONTO OBTIDO. 2% e a ordem de
# grandeza do desconto financeiro de pontualidade em contas a pagar; acima disso
# a diferenca deixa de ser desconto e e parcial legitimo, que ja tem tratamento.
# Nao ha percentual de desconto definido pelo escritorio: o desconto se descobre
# perguntando ao cliente. Entao 2% permanece como corte
# descobre o desconto perguntando ao cliente. Entao 2% permanece como corte
# CONSERVADOR NOSSO — heuristica de exibicao, sujeita a revisao, nunca regra
# contabil. Nada na composicao depende dele: e' rotulo.
LIMITE_DESCONTO = Decimal("0.02")


def self_check_parsing(conta: Conta) -> list[Achado]:
    """Roda os 4 checks e devolve um Achado por check (OK quando passa)."""
    achados: list[Achado] = [
        _check_total_debito(conta),
        _check_total_credito(conta),
        _check_saldo_final(conta),
    ]
    achados.extend(_check_saldo_corrente(conta))
    return achados


def _check_total_lado(conta: Conta, extrai, total_dominio: Decimal,
                      codigo: str, nome: str) -> Achado:
    """Confere Σ de um lado (debito ou credito) contra o 'Total da conta' do
    Dominio -- corpo unico dos dois self-checks de total."""
    soma = sum((extrai(l) for l in conta.lancamentos), ZERO)
    ok = soma == total_dominio
    return Achado(
        nivel=Nivel.OK if ok else Nivel.ERRO,
        codigo=codigo,
        mensagem=(f"soma dos {nome} confere com 'Total da conta'" if ok
                  else f"soma dos {nome} NÃO confere com 'Total da conta'"),
        esperado=total_dominio,
        encontrado=soma,
        conta=conta.codigo,
    )


def _check_total_debito(conta: Conta) -> Achado:
    return _check_total_lado(conta, lambda l: l.debito,
                             conta.total_debito_dominio,
                             "self_check_total_debito", "débitos")


def _check_total_credito(conta: Conta) -> Achado:
    return _check_total_lado(conta, lambda l: l.credito,
                             conta.total_credito_dominio,
                             "self_check_total_credito", "créditos")


def _check_saldo_final(conta: Conta) -> Achado:
    deb = sum((l.debito for l in conta.lancamentos), ZERO)
    cred = sum((l.credito for l in conta.lancamentos), ZERO)
    recalc = conta.saldo_anterior + deb - cred
    impresso = conta.saldo_final          # fonte unica (a regra saiu daqui p/ Conta)
    ok = recalc == impresso
    return Achado(
        nivel=Nivel.OK if ok else Nivel.ERRO,
        codigo="self_check_saldo_final",
        mensagem=("saldo recalculado confere com a última linha" if ok
                  else "saldo recalculado NÃO confere com a última linha"),
        esperado=impresso,
        encontrado=recalc,
        conta=conta.codigo,
    )


def _check_saldo_corrente(conta: Conta) -> list[Achado]:
    """Passo a passo: pra cada lancamento, a variação do saldo impresso
    (saldo_n - saldo_{n-1}) tem que igualar debito_n - credito_n. Se nao bate,
    algum valor da linha foi lido errado -> ALERTA (sinaliza, nao rejeita)."""
    achados: list[Achado] = []
    anterior = conta.saldo_anterior
    for l in conta.lancamentos:
        delta_real = l.saldo_exercicio - anterior
        delta_esperado = l.debito - l.credito
        if delta_real != delta_esperado:
            achados.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="self_check_saldo_corrente",
                mensagem=f"saldo corrente do lote {l.numero} não fecha",
                esperado=delta_esperado,
                encontrado=delta_real,
                conta=conta.codigo,
            ))
        anterior = l.saldo_exercicio

    if not achados:
        achados.append(Achado(
            nivel=Nivel.OK,
            codigo="self_check_saldo_corrente",
            mensagem="saldo corrente fecha linha a linha",
            conta=conta.codigo,
        ))
    return achados


def _e_possivel_desconto(i: ComposicaoItem) -> bool:
    """Residuo A MENOR pequeno numa NF que JA recebeu quitacao.

    Cinco condicoes, todas necessarias:
    1. compra do periodo com valor positivo (estorno e o item do saldo anterior
       ficam fora, mesma trava do #26 no juros);
    2. houve pelo menos uma quitacao — NF intocada e 'em aberto', nao desconto;
    3. o residuo passa da tolerancia de centavos do casamento — abaixo dela e
       arredondamento (espelho de `quitada_com_arredondamento`);
    4. o residuo cabe no teto de desconto;
    5. o residuo e MENOR que a quitacao media. Sem isso, NF de 6.000,00 em 60
       parcelas de 100,00 com 59 pagas (residuo de 1,67%) viraria 'desconto'
       quando o que houve foi parcela faltando. Comparacao por multiplicacao:
       residuo * qtd < total quitado — sem divisao, sem arredondamento.
    """
    if i.origem is not Origem.COMPRA_PERIODO or i.valor_compra <= ZERO:
        return False
    if i.qtd_quitacoes < 1 or i.saldo_aberto <= ZERO:
        return False
    if i.saldo_aberto <= i.qtd_quitacoes * TOL:
        return False
    if i.saldo_aberto > LIMITE_DESCONTO * i.valor_compra:
        return False
    return i.saldo_aberto * i.qtd_quitacoes < (i.valor_compra - i.saldo_aberto)


def duplicidade_de_emissao(itens: list[ComposicaoItem]) -> list[Achado]:
    """2+ NFs da MESMA conta com o mesmo valor E a mesma data de emissao.

    Regra de negocio: duas notas identicas nao sao um
    empate a resolver — sao uma duplicidade a CONFIRMAR, e uma delas pode
    precisar ser estornada. O motor ja nao vinculava (EMPATE); o que faltava
    era NOMEAR o padrao e dizer a acao.

    Familia PROPRIA, fora dos self_checks: eles respondem "lemos e compusemos
    certo?"; este responde "ha algo estranho no que lemos?".

    Recebe abertas + quitadas: a gemea pode ja ter fechado e a
    duplicidade continua existindo. ALERTA puro — nao muda composicao, gap,
    veredito nem o balde.

    Sem tolerancia, de proposito: aqui (valor, data) e a ASSINATURA da
    duplicidade, nao uma divisao que arredonda. Mesmo valor em datas
    DIFERENTES sao duas compras iguais, caso corriqueiro tratado pelo
    desempate por ordem cronologica.
    """
    grupos: dict[tuple[Decimal, object], list[str]] = {}
    for i in itens:
        # sem compra na janela nao ha emissao pra comparar: o "(anterior)" e o
        # estorno ficam fora (mesma trava do #26 no juros)
        if i.origem is not Origem.COMPRA_PERIODO or i.valor_compra <= ZERO:
            continue
        if i.data_compra is None:
            continue
        grupos.setdefault((i.valor_compra, i.data_compra), []).append(i.nf_numero)

    achados: list[Achado] = []
    # ordenado pela CHAVE, e os numeros dentro do grupo tambem: o mesmo arquivo
    # gera sempre os mesmos alertas na mesma ordem (diff so' muda com o dado)
    for (valor, data), numeros in sorted(grupos.items()):
        if len(numeros) < 2:
            continue
        nfs = sorted(numeros)
        achados.append(Achado(
            nivel=Nivel.ALERTA,
            codigo="possivel_duplicidade_emissao",
            # a data comparada e' a do RAZAO (lancamento da compra), nao
            # necessariamente a emissao -- a frase diz o que o motor viu
            mensagem=(f"possível duplicidade na emissão: as NFs "
                      f"{', '.join(nfs)} têm o mesmo valor e a mesma data "
                      f"no razão"),
            referencia=", ".join(nfs),       # a coluna NF/Lote
            encontrado=valor,
            valores={"notas": Decimal(len(nfs))},
            # a DATA nao cabe em `valores` (so' Decimal); vai na frase, que a
            # apresentacao monta a partir do proprio item — aqui fica o numero
        ))
    return achados


def compra_repetida(nfs: list[NF]) -> list[Achado]:
    """NF com 2+ linhas de COMPRA de valor IDENTICO (num caso: varias
    NFs lancadas duas vezes, lotes diferentes, e pagas uma vez).

    ALERTA puro, fato que nenhuma regra decide: a composicao NAO tira a copia
    (seria forcar a composicao) -- a NF continua somando as linhas, como a
    razao mostra. Nota dividida em linhas de valores DIFERENTES e' o caso de
    campo legitimo (5 nas reais antigas) e nao dispara. Recebe as NFs de
    todos os lados do corte: a copia continua sendo copia no periodo zerado.
    Sem tolerancia: a assinatura e' o valor exato.
    """
    achados: list[Achado] = []
    for nf in sorted(nfs, key=lambda n: n.numero):
        if nf.transferencia:
            continue
        por_valor: dict[Decimal, list] = {}
        for l in nf.compras:
            por_valor.setdefault(l.credito, []).append(l)
        for valor, linhas in sorted(por_valor.items()):
            if len(linhas) < 2 or valor <= ZERO:
                continue
            achados.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="possivel_compra_repetida",
                mensagem=(f"NF {nf.numero} lançada {len(linhas)} vezes com o "
                          f"mesmo valor (lotes "
                          f"{', '.join(l.numero for l in linhas)})"),
                referencia=nf.numero,
                valores={"valor": valor, "vezes": Decimal(len(linhas))},
                # as linhas sao a evidencia: lotes e datas vao pra frase
                lancamentos=tuple(linhas),
            ))
    return achados


def reconciliar(itens: list[ComposicaoItem], saldo_final: Decimal,
                balde: tuple[ItemRevisao, ...] = (),
                fora: tuple[DecisaoManual, ...] = ()) -> list[Achado]:
    """Reconciliacao da composicao.

    gap = Σ saldo_aberto(itens) - |saldo_final|.
    - balde vazio: gap == 0 -> OK; senao ERRO (divergencia,
      NUNCA forca a fechar -- reporta esperado/encontrado).
    - balde != []: NAO da ERRO. Status INCOMPLETO -- o gap e explicado pelo balde
      (itens em revisao manual), nao e divergencia contabil. Identidade saudavel:
      gap == Σ pagamentos no balde.
    - `fora` sao as decisoes de NAO-COMPOSICAO do contador. A identidade
      generaliza pra gap == Σ balde + Σ fora, e o que ficou fora vira RESSALVA:
      a composicao passa a diferir do Dominio exatamente por esse valor, o que e
      coisa a resolver com o cliente (reclassificacao), nao conferencia
      concluida. Por isso amarelo, nunca verde.
    SO' a reconciliacao -- os alertas por NF vivem em alertas_por_item,
    porque o corte por saldo zero reconcilia o pos-corte mas continua
    alertando sobre o periodo zerado."""
    total = sum((i.saldo_aberto for i in itens), Decimal("0.00"))
    # o alvo da composicao e o a-pagar COM sinal (-saldo_final): credor
    # (saldo_final < 0) da o mesmo abs de sempre -- golden intacto; devedor
    # (saldo_final > 0) mantem o sinal, senao o abs dobra o sinal e quebra a
    # identidade gap == soma(D-C) do balde.
    alvo = -saldo_final
    gap = total - alvo
    achados: list[Achado] = []
    # os tres numeros do PLACAR da tela, sempre presentes no achado da
    # reconciliacao: a apresentacao le daqui e nao refaz conta nenhuma.
    # 'residuo' continua exclusivo do ramo de ERRO (a frase de tela depende disso).
    numeros = {"total": total, "alvo": alvo, "gap": gap}

    if saldo_final > ZERO:
        # conta com saldo devedor: o fornecedor tem pagamentos acima das compras
        # registradas na janela. Texto NEUTRO (sem moeda) -- a frase com R$
        # nasce na apresentacao. ALERTA nao derruba o verde do veredito.
        # o diagnostico diz o que a conta E' + as causas comuns.
        # O sistema nao escolhe entre
        # elas -- lista o que o conferente vai procurar.
        achados.append(Achado(
            nivel=Nivel.ALERTA,
            codigo="conta_devedora",
            mensagem=("conta devedora: há mais pagamentos (débitos) que "
                      "provisões (créditos). Causas comuns: parcelas pagas "
                      "com juros, pagamentos sem nota fiscal, ou notas ainda "
                      "não contabilizadas"),
            encontrado=saldo_final,
        ))

    soma_fora = sum((d.valor for d in fora), Decimal("0.00"))
    if soma_fora != ZERO:
        achados.append(Achado(
            nivel=Nivel.INCOMPLETO,
            codigo="composicao_com_ressalva",
            mensagem=("itens declarados fora da composição: a composição "
                      "difere do saldo do Domínio por este valor"),
            encontrado=soma_fora,
            valores={"itens": Decimal(len(fora))},
        ))

    if balde or fora:
        # identidade cobre o balde INTEIRO, todos os motivos: cada debito no
        # balde deixou de quitar (infla o aberto), cada credito deixou de
        # abrir item (reduz) -> gap saudavel == Σ(debitos - creditos).
        # o que o contador tirou da composicao pesa igual e entra na conta.
        soma_balde = sum((l.debito - l.credito
                          for item in balde for l in item.lancamentos),
                         Decimal("0.00")) + soma_fora
        residuo = gap - soma_balde
        if abs(residuo) <= TOL:
            # identidade fecha: o balde explica o gap -> INCOMPLETO
            achados.append(Achado(
                nivel=Nivel.INCOMPLETO,
                codigo="self_check_composicao",
                mensagem=(f"{len(balde)} item(ns) em revisão respondem pela diferença"
                          if balde else
                          "a diferença é explicada pelas decisões de "
                          "não-composição"),
                esperado=soma_balde,
                encontrado=gap,
                valores=dict(numeros),
            ))
        else:
            # identidade NAO fecha: divergencia real escondida atras do balde
            #. Vira ERRO (nao INCOMPLETO, senao a tela mentiria que
            # "os itens explicam exatamente"); a mensagem decompoe os numeros.
            achados.append(Achado(
                nivel=Nivel.ERRO,
                codigo="self_check_composicao",
                mensagem="divergência não explicada pelo balde",
                esperado=soma_balde,
                encontrado=gap,
                valores={**numeros, "residuo": residuo},
            ))
    else:
        ok = total == alvo
        achados.append(Achado(
            nivel=Nivel.OK if ok else Nivel.ERRO,
            codigo="self_check_composicao",
            mensagem=("composição fecha com o saldo final" if ok
                      else "composição NÃO fecha com o saldo final"),
            esperado=alvo,
            encontrado=total,
            valores=dict(numeros),
        ))
    return achados


def alertas_por_item(itens: list[ComposicaoItem],
                     nao_detalhados: bool = True) -> list[Achado]:
    """Os alertas de UMA linha da composicao: saldo anterior e transferencia
    nao detalhados, possivel juros, possivel desconto. Sinalizam, nao rejeitam.

    `nao_detalhados=False` pro periodo zerado pelo corte. Ali o saldo
    anterior e a transferencia ja se compensaram no agregado, e "puxar a razao
    anterior" nao muda o saldo final. Juros e desconto continuam: sao fato da
    NF, nao do saldo."""
    achados: list[Achado] = []
    for i in itens:
        if i.origem is Origem.SALDO_ANTERIOR and i.saldo_aberto > Decimal("0.00"):
            if not nao_detalhados:
                continue
            achados.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="saldo_anterior_nao_detalhado",
                mensagem="saldo anterior sem detalhe de notas neste razão",
                encontrado=i.saldo_aberto,
            ))
        elif (i.origem is Origem.TRANSFERENCIA_SALDO
              and i.saldo_aberto > Decimal("0.00")):
            if not nao_detalhados:
                continue
            # saldo que chegou da conta-irma
            # (matriz/filial). IRMAO do saldo_anterior_nao_detalhado, e pela
            # mesma razao da regra do saldo anterior: valor em aberto legitimo
            # cuja composicao NF a NF vive fora da janela deste arquivo.
            # Sinaliza, nao erra — e nao entra em identidade nenhuma.
            achados.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="transferencia_nao_detalhada",
                mensagem=("saldo transferido de outra conta do mesmo "
                          "fornecedor (matriz/filial), sem detalhe de notas "
                          "neste razão"),
                referencia=i.nf_numero,          # o lote esta no nome
                encontrado=i.saldo_aberto,
            ))
        elif (i.origem in (Origem.COMPRA_PERIODO, Origem.ALOCACAO_MANUAL)
              and i.valor_compra > Decimal("0.00")
              and i.saldo_aberto < Decimal("0.00")
              and not i.quitada_com_arredondamento):
            # compra NEGATIVA (estorno) nao e juros -- so alerta com compra > 0
            # pago > compra ALEM da tolerancia de centavos do casamento:
            # possivel juros por atraso. Residuo que a
            # propria tolerancia gerou NAO alerta — vira nota
            # informativa na composicao. NUNCA acusa "pago a mais" automatico.
            # estouro vindo de ALOCACAO MANUAL ganha codigo PROPRIO. Codigo,
            # e nao um flag dentro do achado, porque ele atravessa tela, export,
            # filtros e testes — em qualquer canal a origem fica evidente sem
            # ninguem precisar inspecionar campo.
            manual = i.quitacoes_manuais > 0
            quitado = i.valor_compra - i.saldo_aberto
            achados.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="possivel_juros_manual" if manual else "possivel_juros",
                mensagem=(f"possível juros por atraso na NF {i.nf_numero}"
                          + (", após alocação manual" if manual else "")),
                referencia=i.nf_numero,          # a NF como DADO
                esperado=i.valor_compra,
                encontrado=quitado,
                valores={"diferenca": -i.saldo_aberto},
            ))
        elif _e_possivel_desconto(i):
            # o outro lado do triangulo: quitacoes somam MENOS que a
            # compra por uma diferenca pequena. ROTULO — o item continua onde
            # esta, com o mesmo valor. A faixa cobre tambem IRRF (1,5%) e ISS
            # (2%), por isso a frase de tela oferece as duas leituras.
            achados.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="possivel_desconto",
                mensagem=f"possível desconto obtido na NF {i.nf_numero}",
                referencia=i.nf_numero,
                esperado=i.valor_compra,
                encontrado=i.valor_compra - i.saldo_aberto,
                valores={
                    "diferenca": i.saldo_aberto,
                    # UNICO ponto de divisao da regra, com quantize explicito
                    "percentual": (i.saldo_aberto / i.valor_compra * CEM
                                   ).quantize(CENTESIMO, rounding=ROUND_HALF_UP),
                },
            ))
    return achados


def self_check_composicao(itens: list[ComposicaoItem], saldo_final: Decimal,
                          balde: tuple[ItemRevisao, ...] = (),
                          fora: tuple[DecisaoManual, ...] = ()) -> list[Achado]:
    """Reconciliacao + alertas por item, na ordem de sempre. O
    contrato que os testes conhecem; o conferir com corte
    chama as duas partes separadas."""
    return (reconciliar(itens, saldo_final, balde, fora)
            + alertas_por_item(itens))

"""Casamento pagamento <-> NF. Core puro, nunca chuta.

Fase 1 (por NUMERO, deterministico): o numero no historico liga o pagamento a NF
-- resolve ate parcela desigual, porque o numero liga, nao o valor.
Fase 1.5 (um-pra-muitos): pagamento que CITA 2+ NFs casa quando todas
estao em aberto e a soma dos saldos == valor pago (TOL) -- liquidacao
one-to-many padrao de ERP, cada NF quitada integralmente via Alocacao. Falhou
-> balde com a evidencia; NUNCA cai pra Fase 2 (casar por valor contra outra
NF contradiria a declaracao do historico).
Fase 2 (por VALOR, conservador): pagamentos SEM numero (`soltos`) contra NFs
abertas. So o INEQUIVOCO casa: pagamento unico = NF, ou 1 de N parcelas iguais.
Empate (2+ candidatas) ou sem candidata -> BALDE de revisao manual (nunca chuta).

Alem dos 3 criterios de negocio, entram praticas consolidadas de liquidacao
(praxe de ERP; quem valida e' o RESULTADO na conferencia). Subset-sum geral e parcelas
DESIGUAIS por valor seguem FORA.
"""
from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal

from core.classifica import Classificacao, Tipo
from core.estorno import parear
from core.identificacao import id_item, ids_da_razao
from core.modelo import (
    NF,
    Achado,
    Alocacao,
    CasamentoPorRegra,
    CriterioDesempate,
    Desempate,
    ItemRevisao,
    Lancamento,
    MotivoRevisao,
    Nivel,
    RegraCasamento,
    ResultadoCasamento,
)

ZERO = Decimal("0.00")
TOL = Decimal("0.01")        # tolerancia p/ pagamento unico = NF (criterio a)
NMAX = 60                    # guarda de sanidade p/ parcelas iguais (criterio c)

# texto do criterio na EVIDENCIA do achado (nao e moeda; a frase com R$ nasce na
# apresentacao, padrao #34)
_TEXTO_CRITERIO = {
    CriterioDesempate.UNICA_EM_ABERTO: "única candidata ainda em aberto",
    CriterioDesempate.DATA_MAIS_ANTIGA: "título mais antigo em aberto (FIFO por data)",
}


def _tol_parcela(n: int) -> Decimal:
    # erro de arredondamento acumula ate ~n centavos numa NF dividida em n parcelas
    return n * Decimal("0.01")


def _comporta(nf: NF, w: Decimal) -> bool:
    """A NF ainda tem saldo pra receber o pagamento INTEIRO? (passe 2b)

    Titulo ja quitado nao recebe baixa, e titulo com saldo menor que o pagamento
    nao e estourado pra negativo — seria fabricar um 'possivel juros'. Tolerancia
    = a convencao de centavos do casamento: 1 centavo por quitacao ja feita mais
    1 pela que entra."""
    return nf.saldo_aberto + (nf.qtd_quitacoes + 1) * TOL >= w


def _e_parcela(w: Decimal, valor_compra: Decimal) -> bool:
    """O pagamento de valor `w` e parcela valida de uma NF de `valor_compra`?
    (a) pagamento unico = NF; (c) 1 de N parcelas iguais (N em [2, NMAX]).

    So' velocidade: com w > 0,01, |V - n*w| <= n*0,01 equivale a
    V/(w+0,01) <= n <= V/(w-0,01) -- so' os n DESSA faixa podem passar, e cada
    um passa pelo MESMO teste do laco. A folga de +-1 garante que arredondamento
    na divisao nunca tira um n valido. Bordas (w <= 0,01, compra <= 0) voltam
    ao laco inteiro. Oraculo: tests/test_casamento_faixa.py."""
    if abs(w - valor_compra) <= TOL:                     # (a)
        return True
    if w <= TOL or valor_compra <= ZERO:
        return _e_parcela_laco(w, valor_compra)
    lo = max(2, math.ceil(valor_compra / (w + TOL)) - 1)
    hi = min(NMAX, math.floor(valor_compra / (w - TOL)) + 1)
    return any(abs(valor_compra - n * w) <= _tol_parcela(n)   # (c)
               for n in range(lo, hi + 1))


def _e_parcela_laco(w: Decimal, valor_compra: Decimal) -> bool:
    """A definicao original, N = 2..NMAX um por um: as bordas de _e_parcela
    caem aqui, e os testes a usam como oraculo de equivalencia."""
    if abs(w - valor_compra) <= TOL:                     # (a)
        return True
    for n in range(2, NMAX + 1):                         # (c)
        if abs(valor_compra - n * w) <= _tol_parcela(n):
            return True
    return False


def _por_valor_declarado(w: Decimal, clf: Classificacao, abertas: list[NF],
                         series_pagas: dict) -> NF | None:
    """A NF que a SERIE DECLARADA aponta, ou None.

    "Valor de R$ X (Parcela k de M)": M x X fecha (tolerancia de centavos da
    serie, a mesma do casamento por valor) com o valor de COMPRA de exatamente 1 NF aberta --
    a serie foi definida contra a NOTA quando ela foi emitida. O pago pode
    passar de X (juros de atraso): a sobra deixa a NF negativa e quem a nomeia
    e' o `possivel_juros` de sempre, nunca esta regra.

    Travas: pago >= X (pago menor nao casa por aqui); candidata unica; o slot
    (NF, k, M) ainda livre -- a mesma parcela casada 2x na mesma NF e' o alerta
    de duplicidade de parcela, nao pode nascer de uma inferencia. O "no valor de
    R$ Y" do historico NAO entra: medido, Y e' o valor da NF quando a NF ja esta
    citada e a propria parcela quando nao esta."""
    if (clf.tipo is not Tipo.PAGAMENTO or not clf.parcela or not clf.parcela_de
            or clf.valor_parcela is None or w < clf.valor_parcela):
        return None
    total = clf.parcela_de * clf.valor_parcela
    fecham = [nf for nf in abertas
              if abs(nf.valor_compra - total) <= _tol_parcela(clf.parcela_de)]
    if len(fecham) != 1:
        return None
    if (fecham[0].numero, clf.parcela, clf.parcela_de) in series_pagas:
        return None
    return fecham[0]


# o lado em que cada tipo NAO pode ter valor. Transferencia de saldo
# vale nos dois; estorno, recebimento e outro ja vao pro balde.
_QUITACOES = (Tipo.PAGAMENTO, Tipo.RETENCAO, Tipo.BAIXA_ADIANTAMENTO)


def _lado_inesperado(lanc: Lancamento, clf: Classificacao) -> bool:
    """Compra com valor no debito, ou quitacao com valor no credito.
    Lancamento sem valor (0 e 0) nao cai: nao ha dinheiro pra sumir."""
    if clf.tipo is Tipo.COMPRA:
        return lanc.debito > ZERO
    return clf.tipo in _QUITACOES and lanc.credito > ZERO


def _lista(itens: list) -> str:
    """'3' / '1 e 3' / '1, 2 e 3' -- texto neutro da mensagem do core."""
    textos = [str(n) for n in itens]
    return textos[0] if len(textos) == 1 else ", ".join(textos[:-1]) + " e " + textos[-1]


def lacunas_de_serie(nfs: list[NF],
                     pares: list[tuple[Lancamento, Classificacao]]) -> list[Achado]:
    """Ordinal que falta numa serie de parcelas. FATO, nunca afirma
    que nao foi paga; nao move dinheiro.

    Ancoras: pagamentos casados na NF que CITAM a NF e declaram ordinal -- 2+,
    senao nao ha serie (com 1, um caso com a NF 52904 daria falso positivo: so' a 3a
    declara ordinal). Presentes: o ordinal das ancoras e o de qualquer
    pagamento do razao com ordinal, mesmo valor de uma ancora e sem citar
    OUTRA NF -- casado ou no balde, ele esta no razao. Ausentes: de 1 ate o
    maior presente."""
    clf_de = {id(l): c for l, c in pares}
    achados: list[Achado] = []
    for nf in nfs:
        if nf.data_compra is None:
            continue
        ancoras = [(clf_de[id(p)].parcela, p.debito) for p in nf.pagamentos
                   if id(p) in clf_de and clf_de[id(p)].parcela
                   and clf_de[id(p)].nf_numero == nf.numero]
        presentes = {k for k, _ in ancoras}
        if len(presentes) < 2:
            continue
        valores = {v for _, v in ancoras}
        for l, c in pares:
            if (c.tipo is Tipo.PAGAMENTO and c.parcela and l.debito in valores
                    and c.nfs_citadas in ((), (nf.numero,))):
                presentes.add(c.parcela)
        topo = max(presentes)
        ausentes = sorted(set(range(1, topo + 1)) - presentes)
        if not ausentes:
            continue
        um = len(ausentes) == 1
        achados.append(Achado(
            nivel=Nivel.ALERTA,
            codigo="lacuna_na_serie",
            mensagem=(f"{'parcela' if um else 'parcelas'} {_lista(ausentes)} "
                      f"da série da NF {nf.numero} "
                      f"{'não aparece' if um else 'não aparecem'} neste razão"),
            referencia=nf.numero,
            valores={"maior_ordinal": Decimal(topo)},
        ))
    return achados


MIN_ANCORAS = 2     # com 1, a regra decidiria com UMA prova so'


def _ancoras_ordinais(nf: NF, w: Decimal, clf_de: dict) -> dict[int, Lancamento]:
    """{ordinal: pagamento} das parcelas casadas na NF que CITAM a NF, declaram
    ordinal e tem o valor `w` (+-TOL). So' a citacao vale como prova."""
    ancoras: dict[int, Lancamento] = {}
    for p in nf.pagamentos:
        c = clf_de.get(id(p))
        if (c is not None and c.parcela and c.nf_numero == nf.numero
                and abs(p.debito - w) <= TOL):
            ancoras[c.parcela] = p
    return ancoras


def _cronologia_ok(k: int, data, outros: dict[int, Lancamento]) -> bool:
    """Ordinal menor <=> data anterior, contra cada parcela ja na serie.
    Mesma data com ordinal diferente nao prova ordem nenhuma -> recusa."""
    return all(p.data != data and (j < k) == (p.data < data)
               for j, p in outros.items())


def _por_serie_ordinal(balde: list[ItemRevisao], abertas: list[NF],
                       clf_de: dict) -> list[tuple[ItemRevisao, NF, int]]:
    """Os itens SEM_VINCULO do balde que continuam uma serie ordinal.

    Candidato: um lancamento, PAGAMENTO, ordinal declarado, nenhuma NF citada.
    NF candidata: aberta, 2+ ancoras do mesmo valor, ordinal livre, cronologia
    coerente com as ancoras, comporta o pagamento. Candidata unica ->
    proposta. Depois, G2: o MESMO ordinal da MESMA NF pedido por 2+ propostas
    -> nenhuma casa; e G1 de novo entre as propostas da mesma NF.

    Por que pos-passe e nao inline na Fase 2: a disputa so' existe vendo
    TODAS as propostas -- inline, a primeira na ordem do arquivo levava o
    ordinal e empurrava a verdadeira pro balde (medido na spec)."""
    propostas: list[tuple[ItemRevisao, NF, int, Lancamento]] = []
    for item in balde:
        if item.motivo is not MotivoRevisao.SEM_VINCULO or len(item.lancamentos) != 1:
            continue
        lanc = item.lancamentos[0]
        c = clf_de.get(id(lanc))
        if (c is None or c.tipo is not Tipo.PAGAMENTO or not c.parcela
                or c.nfs_citadas or lanc.debito <= ZERO):
            continue
        cands = []
        for nf in abertas:
            ancoras = _ancoras_ordinais(nf, lanc.debito, clf_de)
            if (len(ancoras) >= MIN_ANCORAS and c.parcela not in ancoras
                    and nf.saldo_aberto >= lanc.debito
                    and _cronologia_ok(c.parcela, lanc.data, ancoras)):
                cands.append(nf)
        if len(cands) == 1:
            propostas.append((item, cands[0], c.parcela, lanc))

    pedidos: dict[tuple[str, int], int] = {}
    for _, nf, k, _ in propostas:
        pedidos[(nf.numero, k)] = pedidos.get((nf.numero, k), 0) + 1
    sem_disputa = [p for p in propostas if pedidos[(p[1].numero, p[2])] == 1]
    aceitas = []
    for item, nf, k, lanc in sem_disputa:
        irmas = {k2: l2 for _, nf2, k2, l2 in sem_disputa
                 if nf2 is nf and l2 is not lanc}
        if _cronologia_ok(k, lanc.data, irmas):
            aceitas.append((item, nf, k))
    return aceitas


def casar(pares: list[tuple[Lancamento, Classificacao]],
          saldo_anterior: Decimal = ZERO) -> ResultadoCasamento:
    """`saldo_anterior` habilita o candidato extra da BAIXA na Fase 2 (SO por
    valor exato). Default 0.00 = sem candidato novo --
    comportamento identico ao anterior (golden intacto)."""
    nfs: dict[str, NF] = {}
    soltos: list[tuple[Lancamento, Classificacao]] = []  # quitacoes sem numero -> Fase 2
    multinfs: list[tuple[Lancamento, Classificacao]] = []  # citam 2+ NFs -> Fase 1.5
    balde: list[ItemRevisao] = []
    # (nf, k, M) -> pagamentos alocados com a serie DECLARADA; 2+ na mesma
    # chave = possivel duplicidade. So rastreia com k E M conhecidos.
    series_pagas: dict[tuple[str, int, int], list[Lancamento]] = {}
    # (k, M, valor) -> TODA ocorrencia de pagamento com serie declarada,
    # casada (carrega a NF) OU em revisao (None). Fecha um furo do detector:
    # o balde era invisivel a ele — duas "Parcela 5
    # de 5" identicas, ambas EMPATE, nao alertavam. So gera achado: NADA sai
    # do balde e o casamento nao muda.
    ocorrencias_serie: dict[tuple[int, int, Decimal],
                            list[tuple[Lancamento, str | None]]] = {}

    def _nf(numero: str) -> NF:
        if numero not in nfs:
            nfs[numero] = NF(numero=numero)
        return nfs[numero]

    def _registra_serie(nf_numero: str, clf: Classificacao, lanc: Lancamento) -> None:
        if clf.parcela is not None and clf.parcela_de is not None:
            series_pagas.setdefault(
                (nf_numero, clf.parcela, clf.parcela_de), []).append(lanc)
            ocorrencias_serie.setdefault(
                (clf.parcela, clf.parcela_de, lanc.debito), []).append((lanc, nf_numero))

    def _registra_serie_em_revisao(clf: Classificacao, lanc: Lancamento) -> None:
        """Pagamento com 'parcela k de M' declarada que caiu no BALDE: entra
        no rastreio de duplicidade como ocorrencia sem NF (a revisao manual
        decide o vinculo; a repeticao da serie ja e sinal por si)."""
        if (clf.tipo is Tipo.PAGAMENTO and clf.parcela is not None
                and clf.parcela_de is not None):
            ocorrencias_serie.setdefault(
                (clf.parcela, clf.parcela_de, lanc.debito), []).append((lanc, None))

    def _promove_serie(nf_numero: str, clf: Classificacao, lanc: Lancamento) -> None:
        """Empate que o passe 2b CASOU. O 2a ja reservou o slot em
        ocorrencias_serie na posicao cronologica; aqui a ocorrencia e promovida
        NO LUGAR ((lanc, None) -> (lanc, nf)) em vez de reentrar no fim — assim a
        ordem dos lotes na mensagem de duplicidade fica identica a de antes da
        mudanca (igualdade estrita, nao equivalencia)."""
        if clf.parcela is None or clf.parcela_de is None:
            return
        series_pagas.setdefault(
            (nf_numero, clf.parcela, clf.parcela_de), []).append(lanc)
        ocorrencias = ocorrencias_serie.get(
            (clf.parcela, clf.parcela_de, lanc.debito), [])
        for i, (registrado, _) in enumerate(ocorrencias):
            if registrado is lanc:
                ocorrencias[i] = (lanc, nf_numero)
                break

    # --- citacao de NF sem compra que estoura o saldo anterior ---
    # NF citada sem compra no periodo e' NF anterior a janela (regra do saldo anterior) --
    # enquanto o saldo anterior comporta. O conjunto das NFs COM compra e' da
    # razao INTEIRA (a compra pode vir depois do pagamento no arquivo). Na
    # ordem do arquivo, as citacoes sem compra somam; a partir da que passa de
    # |saldo anterior|, a citacao nao pode ser NF anterior (e' numero de
    # boleto/documento) e, SE ha candidata por valor (o teste estatico
    # do 2a), o pagamento perde o numero e vai pra Fase 2. Sem candidata, a
    # citacao fica: nada a ganhar trocando um destino por balde.
    compras_da_razao: dict[str, Decimal] = {}
    for lanc, clf in pares:
        if (clf.tipo is Tipo.COMPRA and clf.nf_numero
                and not _lado_inesperado(lanc, clf)):
            compras_da_razao[clf.nf_numero] = (
                compras_da_razao.get(clf.nf_numero, ZERO) + lanc.credito)
    citado_sem_nota = ZERO
    sem_citacao: dict[int, str] = {}      # id(lanc) -> numero que ele citava

    # --- Fase 1: por NUMERO ---
    for lanc, clf in pares:
        if clf.tipo is Tipo.OUTRO:
            # historico sem padrao reconhecido: NUNCA some em silencio --
            # vai pro balde com o historico integral como evidencia
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.NAO_CLASSIFICADO,
                candidatos=[],
                mensagem=f"histórico não reconhecido: {lanc.historico}",
            ))
            continue
        if clf.tipo is Tipo.RECEBIMENTO:
            # recebimento do fornecedor: decidir se concilia tem subjetividade, entao vai
            # para o balde para ser analisado. Credito ganha motivo
            # PROPRIO; debito nunca e' dinheiro voltando -> nao reconhecido.
            if lanc.credito > ZERO:
                balde.append(ItemRevisao(
                    lancamentos=[lanc],
                    motivo=MotivoRevisao.RECEBIMENTO,
                    candidatos=[],
                    mensagem="recebimento do fornecedor sem NF",
                ))
            else:
                balde.append(ItemRevisao(
                    lancamentos=[lanc],
                    motivo=MotivoRevisao.NAO_CLASSIFICADO,
                    candidatos=[],
                    mensagem=f"histórico não reconhecido: {lanc.historico}",
                ))
            continue
        if clf.tipo is Tipo.ESTORNO:
            # reconhecido, mas nao e quitacao -- nao entra em nenhuma NF.
            # Vai pro balde com motivo PROPRIO; o pareamento (core/estorno.py)
            # roda no fim desta funcao e tira daqui o que fechar par. O nome do
            # motivo descreve o que SOBREVIVE.
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.ESTORNO_SEM_PAR,
                candidatos=[],
                mensagem="estorno sem a operação correspondente no balde",
            ))
            continue
        if clf.tipo is Tipo.TRANSFERENCIA_SALDO and lanc.credito > ZERO:
            # lado CREDITO: saldo CHEGANDO da conta
            # irma (matriz/filial). Nao e' baixa e nao quita nada: vira LINHA
            # PROPRIA da composicao, em aberto, com a data em que chegou aqui.
            # O detalhe NF a NF esta no razao da outra conta, que nao temos --
            # e' a regra do saldo anterior com outra origem:
            # sinaliza, nao erra.
            #
            # O LOTE vai no nome: duas transferencias no mesmo periodo
            # colidiriam num nome fixo, e o lote e' o que o conferente usa pra
            # achar o lancamento no Dominio.
            #
            # NF citada NAO e' consumida aqui de proposito: somar o credito ao
            # valor_compra de uma nota existente inflaria silenciosamente o
            # valor dela. Citacao so' resolve o lado DEBITO, que quita.
            nf = _nf(f"(transferência lote {lanc.numero})")
            nf.valor_compra += lanc.credito
            nf.compras.append(lanc)
            nf.data_compra = lanc.data
            nf.transferencia = True
            continue
        if _lado_inesperado(lanc, clf):
            # o valor esta no lado oposto ao do tipo. Entrar numa NF
            # somaria 0 a ela (compra em debito) ou a quitaria de nada
            # (quitacao em credito): o dinheiro sumiria e o veredito acusaria
            # a composicao. Vai pro balde ANTES de qualquer uso do numero, da
            # Fase 1.5 e da Fase 2 (que compara o debito: um credito casaria
            # com NF de centavos).
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.LADO_INESPERADO,
                candidatos=[],
                mensagem=(f"{clf.tipo.value} com valor no "
                          f"{'débito' if clf.tipo is Tipo.COMPRA else 'crédito'}"),
                tipo_declarado=clf.tipo,
            ))
            continue
        if (clf.tipo is Tipo.PAGAMENTO and clf.nf_numero is not None
                and clf.nf_numero not in compras_da_razao):
            citado_sem_nota += lanc.debito
            if (citado_sem_nota > abs(saldo_anterior) + TOL
                    and any(_e_parcela(lanc.debito, v)
                            for v in compras_da_razao.values())):
                sem_citacao[id(lanc)] = clf.nf_numero
                clf = replace(clf, nf_numero=None, nfs_citadas=())
        if clf.nf_numero is None:
            if clf.tipo is Tipo.PAGAMENTO and len(clf.nfs_citadas) >= 2:
                multinfs.append((lanc, clf))             # declara as NFs -> Fase 1.5
            elif clf.tipo in (Tipo.PAGAMENTO, Tipo.RETENCAO,
                              Tipo.BAIXA_ADIANTAMENTO,
                              # transferencia em DEBITO e' quitacao sem
                              # numerario ("baixa normal") — mesma
                              # cascata conservadora: so' o inequivoco casa.
                              Tipo.TRANSFERENCIA_SALDO):
                soltos.append((lanc, clf))               # quitacao sem numero -> Fase 2
            else:
                # COMPRA cujo padrao nao capturou o numero: NUNCA some em
                # silencio -- vai pro balde com o historico integral
                balde.append(ItemRevisao(
                    lancamentos=[lanc],
                    motivo=MotivoRevisao.NAO_CLASSIFICADO,
                    candidatos=[],
                    mensagem=f"COMPRA sem número de NF no histórico: {lanc.historico}",
                ))
            continue
        nf = _nf(clf.nf_numero)
        if clf.tipo is Tipo.COMPRA:
            # a mesma NF pode vir em N linhas de compra: SOMA --
            # sobrescrever perderia valor; a data e a da primeira linha
            nf.valor_compra += lanc.credito
            nf.compras.append(lanc)
            if nf.data_compra is None:
                nf.data_compra = lanc.data
        elif clf.tipo is Tipo.PAGAMENTO:
            nf.pagamentos.append(lanc)
            _registra_serie(nf.numero, clf, lanc)
        elif clf.tipo is Tipo.RETENCAO:
            nf.retencoes.append(lanc)
        elif clf.tipo in (Tipo.BAIXA_ADIANTAMENTO, Tipo.TRANSFERENCIA_SALDO):
            # familia de quitacao SEM NUMERARIO: a transferencia em debito e' a
            # "baixa normal". Vai na coluna de baixa,
            # IDENTIFICADA -- nunca mascarada de pagamento.
            nf.baixas.append(lanc)

    # casados por inferencia declarada e sobras de multi-NF
    achados_por_regra: list[Achado] = []

    # --- Fase 1.5: um-pra-muitos por NFs CITADAS ---
    # Aritmetica sobre SALDOS (retencao ja abatida), na ordem do arquivo:
    # um segundo multi-NF citando NF ja quitada falha a checagem e vai pro
    # balde, honesto. Nada aqui e' rateio: valor alocado == saldo da NF.
    for lanc, clf in multinfs:
        w = lanc.debito
        citadas = {n: nfs.get(n) for n in clf.nfs_citadas}
        fora = [n for n, nf in citadas.items()
                if nf is None or nf.data_compra is None or nf.saldo_aberto <= ZERO]
        if fora:
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                candidatos=list(clf.nfs_citadas),
                mensagem=(f"NF(s) citada(s) {', '.join(fora)} não está(ão) "
                          f"em aberto na conta"),
            ))
            _registra_serie_em_revisao(clf, lanc)
            continue
        soma = sum((nf.saldo_aberto for nf in citadas.values()), ZERO)
        if w - soma > TOL:
            # o historico CITA as NFs e o pago passa da soma. Cada
            # citada recebe o saldo dela (a mesma Alocacao do caso exato) e a
            # sobra vira linha PROPRIA, visivel, fora do balde -- sem rotulo:
            # juros, adiantamento ou outro titulo, o motor nao decide. So' NF
            # citada recebe; pago < soma segue no balde, abaixo.
            for nf in citadas.values():
                saldo = nf.saldo_aberto
                nf.alocacoes.append(Alocacao(lancamento=lanc, valor=saldo))
            sobra = w - soma
            linha = _nf(f"(pago a maior lote {lanc.numero})")
            linha.data_compra = lanc.data       # a data do lancamento, como a
            linha.pago_a_maior = True           # transferencia
            linha.alocacoes.append(Alocacao(lancamento=lanc, valor=sobra))
            achados_por_regra.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="pago_a_maior",
                mensagem=(f"pago a maior no lote {lanc.numero}, que cita as "
                          f"NFs {_lista(list(citadas))}"),
                referencia=linha.numero,
                valores={"pagamento": w, "soma": soma, "sobra": sobra},
                lancamentos=(lanc,),
            ))
            continue
        if abs(soma - w) > TOL:
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                candidatos=list(clf.nfs_citadas),
                mensagem=("soma dos saldos das NFs citadas não confere "
                          "com o pagamento"),
                valores={"soma": soma, "pagamento": w},
            ))
            _registra_serie_em_revisao(clf, lanc)
            continue
        # conserva o dinheiro: as N-1 primeiras recebem seu saldo; a ULTIMA
        # absorve a diferenca de ate TOL (valor = w - soma das demais). Sem isso
        # o casamento aceitava 1 centavo de tolerancia mas alocava soma > w,
        # conjurando o centavo e virando ERRO falso na composicao.
        # Match exato (soma == w): a ultima recebe seu proprio saldo -- igual ao
        # de antes.
        alvos = list(citadas.values())
        acumulado = ZERO
        for nf in alvos[:-1]:
            saldo = nf.saldo_aberto          # LER antes do append: saldo_aberto e
            nf.alocacoes.append(Alocacao(lancamento=lanc, valor=saldo))  # property
            acumulado += saldo               # (cai a 0 apos alocar) -> capturar aqui
        alvos[-1].alocacoes.append(Alocacao(lancamento=lanc, valor=w - acumulado))

    # --- Fase 2: por VALOR (conservador, nunca chuta) ---
    # Passe 2a (abaixo): decide o INEQUIVOCO — identico ao de sempre; nenhuma
    # decisao dele le saldo (candidatos sobre valor_compra ESTATICO, `abertas`
    # fotografado aqui, `anterior_alvo` estatico) -> ordem-independente.
    # Passe 2b: julga a fila de empates DEPOIS que os inequivocos ja
    # quitaram o que tinham. So toca o que hoje e 100% balde -> o balde so encolhe.
    abertas = [nf for nf in nfs.values()
               if nf.data_compra is not None and nf.saldo_aberto > ZERO]
    anterior_alvo = abs(saldo_anterior)

    def _destino(nf: NF, tipo: Tipo) -> list[Lancamento]:
        if tipo in (Tipo.BAIXA_ADIANTAMENTO, Tipo.TRANSFERENCIA_SALDO):
            return nf.baixas          # quitacao sem numerario, identificada
        if tipo is Tipo.RETENCAO:
            return nf.retencoes
        return nf.pagamentos

    # empates que a serie declarada nao resolveu -> julgados no passe 2b
    empatados: list[tuple[Lancamento, Classificacao, list[NF], bool]] = []

    for lanc, clf in soltos:
        tipo = clf.tipo
        w = lanc.debito
        candidatos = [nf for nf in abertas if _e_parcela(w, nf.valor_compra)]
        # SO a baixa enxerga o saldo anterior, e SO por valor EXATO (tolerancia
        # de centavos): parcela foi definida contra NF atomica -- contra o
        # agregado NAO se aplica. Baixa parcial -> balde -> decisao de quem confere.
        casa_anterior = (tipo is Tipo.BAIXA_ADIANTAMENTO
                         and anterior_alvo > ZERO
                         and abs(w - anterior_alvo) <= TOL)
        total = len(candidatos) + (1 if casa_anterior else 0)
        if total == 1:
            if casa_anterior:
                # quitacao SEM compra no periodo: a regra 3 da composicao
                # consome |saldo_anterior|, identificada como baixa
                _nf("(baixa de adiantamento)").baixas.append(lanc)
            else:
                _destino(candidatos[0], tipo).append(lanc)   # inequivoco -> liga
                if tipo is Tipo.PAGAMENTO:
                    _registra_serie(candidatos[0].numero, clf, lanc)
        elif total >= 2:
            # --- desempate por serie DECLARADA: "Parcela k de M" ---
            # M x parcela == valor de compra de EXATAMENTE UMA candidata ->
            # aloca nela (metadado declarado + aritmetica; o candidato
            # "(saldo anterior)" nao tem valor de compra e fica fora da
            # checagem). 0 ou 2+ fechando -> ambiguo continua -> balde.
            if clf.parcela_de:
                serie = [nf for nf in candidatos
                         if abs(clf.parcela_de * w - nf.valor_compra)
                         <= _tol_parcela(clf.parcela_de)]
                if len(serie) == 1:
                    _destino(serie[0], tipo).append(lanc)
                    if tipo is Tipo.PAGAMENTO:
                        _registra_serie(serie[0].numero, clf, lanc)
                    continue
            # a serie nao resolveu: entra na fila do 2b em vez de ir direto pro
            # balde. O slot da serie e RESERVADO aqui, na posicao cronologica de
            # sempre; casando no 2b, `_promove_serie` troca no lugar.
            empatados.append((lanc, clf, candidatos, casa_anterior))
            _registra_serie_em_revisao(clf, lanc)
        else:
            # o que o valor PAGO nao achou, a serie DECLARADA pode
            declarada = _por_valor_declarado(w, clf, abertas, series_pagas)
            if declarada is not None:
                declarada.pagamentos.append(lanc)
                declarada.por_regra.append(CasamentoPorRegra(
                    lancamento=lanc, regra=RegraCasamento.VALOR_DECLARADO))
                _registra_serie(declarada.numero, clf, lanc)
                achados_por_regra.append(Achado(
                    nivel=Nivel.ALERTA,
                    codigo="casamento_por_valor_declarado",
                    mensagem=(f"casamento pelo valor declarado: lote "
                              f"{lanc.numero} alocado na NF {declarada.numero} "
                              f"— parcela {clf.parcela} de {clf.parcela_de} "
                              f"declarada no histórico"),
                    referencia=declarada.numero,
                    valores={"pagamento": w, "declarado": clf.valor_parcela,
                             "diferenca": w - clf.valor_parcela},
                    lancamentos=(lanc,),
                ))
                continue
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.SEM_VINCULO,
                candidatos=[],
                mensagem=f"pagamento (lote {lanc.numero}) sem NF correspondente",
                valores={"pagamento": w},
                nf_citada=sem_citacao.get(id(lanc)),
            ))
            _registra_serie_em_revisao(clf, lanc)

    # --- continuidade de serie ordinal (pos-passe da Fase 2) ---
    clf_de = {id(l): c for l, c in pares}
    for item, nf, k in _por_serie_ordinal(balde, abertas, clf_de):
        lanc = item.lancamentos[0]
        if nf.saldo_aberto < lanc.debito:      # comporta, na ordem em que entra
            continue
        balde.remove(item)
        nf.pagamentos.append(lanc)
        nf.por_regra.append(CasamentoPorRegra(lancamento=lanc,
                                              regra=RegraCasamento.SERIE_ORDINAL))
        clf = clf_de[id(lanc)]
        # sai do rastreio "em revisao" e entra como casada (mesma troca no
        # lugar do passe 2b -- a ordem dos lotes na duplicidade nao muda)
        _promove_serie(nf.numero, clf, lanc)
        ancoras = _ancoras_ordinais(nf, lanc.debito, clf_de)
        achados_por_regra.append(Achado(
            nivel=Nivel.ALERTA,
            codigo="casamento_por_serie_ordinal",
            mensagem=(f"casamento pela série de parcelas: lote {lanc.numero} "
                      f"({k}ª parcela) alocado na NF {nf.numero} — a série "
                      f"tem {len(ancoras)} parcelas que citam a NF"),
            referencia=nf.numero,
            valores={"pagamento": lanc.debito, "ordinal": Decimal(k),
                     "ancoras": Decimal(len(ancoras))},
            lancamentos=(lanc,),
        ))

    # --- Passe 2b: desempate do EMPATE ---
    # Regra de negocio + praxe de ERP: baixa-se o titulo mais antigo primeiro. Roda
    # com o estado FINAL do 2a — e o que permite ver quais titulos ja fecharam.
    # Ordem do arquivo (cronologica) = deterministico.
    achados_desempate: list[Achado] = []
    for lanc, clf, candidatos, casa_anterior in empatados:
        w = lanc.debito
        nomes = [nf.numero for nf in candidatos]
        if casa_anterior:
            nomes.append("(saldo anterior)")
        escolhida: NF | None = None
        criterio: CriterioDesempate | None = None
        elegiveis: list[NF] = []
        # o agregado "(saldo anterior)" nao tem data de emissao: nao se rankeia o
        # que nao tem data -> empate que o inclui continua revisao manual
        if not casa_anterior:
            elegiveis = [nf for nf in candidatos if _comporta(nf, w)]
            if len(elegiveis) == 1:
                escolhida, criterio = elegiveis[0], CriterioDesempate.UNICA_EM_ABERTO
            elif len(elegiveis) >= 2:
                mais_antiga = min(nf.data_compra for nf in elegiveis)
                primeiras = [nf for nf in elegiveis if nf.data_compra == mais_antiga]
                if len(primeiras) == 1:   # 2+ na mesma data: NUNCA escolher
                    escolhida, criterio = primeiras[0], CriterioDesempate.DATA_MAIS_ANTIGA

        if escolhida is None:
            quitadas = not casa_anterior and not elegiveis
            balde.append(ItemRevisao(
                lancamentos=[lanc],
                motivo=MotivoRevisao.EMPATE,
                candidatos=nomes,
                mensagem=(f"pagamento (lote {lanc.numero}) casa com "
                          f"{len(nomes)} candidatas, todas já quitadas — "
                          f"possível pagamento em duplicidade"
                          if quitadas else
                          f"pagamento (lote {lanc.numero}) casa com "
                          f"{len(nomes)} candidatos"),
                valores={"pagamento": w},
            ))
            continue

        _destino(escolhida, clf.tipo).append(lanc)
        escolhida.desempates.append(
            Desempate(lancamento=lanc, criterio=criterio, candidatos=tuple(nomes)))
        if clf.tipo is Tipo.PAGAMENTO:
            _promove_serie(escolhida.numero, clf, lanc)
        achados_desempate.append(Achado(
            nivel=Nivel.ALERTA,
            codigo="casamento_por_desempate",
            mensagem=(f"casamento por desempate: lote {lanc.numero} alocado na "
                      f"NF {escolhida.numero} — {_TEXTO_CRITERIO[criterio]} "
                      f"entre {len(nomes)} candidatas"),
            # a NF que RECEBEU a quitacao decidida por regra (o lote fica
            # no detalhe) -- e a linha da composicao que o conferente vai olhar
            referencia=escolhida.numero,
            valores={"pagamento": w},
        ))

    # --- o que perdeu a citacao e CASOU fica registrado ---
    for nf in nfs.values():
        for lanc in nf.pagamentos:
            citado = sem_citacao.get(id(lanc))
            if citado is None:
                continue
            achados_por_regra.append(Achado(
                nivel=Nivel.ALERTA,
                codigo="casamento_por_valor_citacao_sem_nota",
                mensagem=(f"casamento pelo valor: lote {lanc.numero} cita a NF "
                          f"{citado}, que não tem compra nesta razão, e as "
                          f"citações desse tipo já passavam do saldo "
                          f"anterior; alocado na NF {nf.numero}"),
                referencia=nf.numero,
                valores={"pagamento": lanc.debito},
                lancamentos=(lanc,),
            ))

    # --- sinalizacoes do casamento: serie declarada paga 2+ vezes ---
    # O dinheiro saiu (a composicao NAO muda); o achado e' pra investigacao.
    achados = [
        Achado(
            nivel=Nivel.ALERTA,
            codigo="possivel_duplicidade",
            mensagem=(f"possível duplicidade: parcela {k} de {m} da NF {n} "
                      f"paga {len(lancs)} vezes "
                      f"(lotes {', '.join(l.numero for l in lancs)})"),
            referencia=", ".join(l.numero for l in lancs),      # os lotes
        )
        for (n, k, m), lancs in series_pagas.items() if len(lancs) >= 2
    ]
    # --- a MESMA (parcela k de M, valor) 2+ vezes com pelo
    # menos uma ocorrencia NO BALDE -> alerta (antes o balde era invisivel).
    # Todas casadas: mesma NF ja alertou acima; NFs distintas = N series
    # legitimas de compras identicas -> silencio, conservador.
    achados += [
        Achado(
            nivel=Nivel.ALERTA,
            codigo="possivel_duplicidade",
            mensagem=(f"possível duplicidade: parcela {k} de {m} "
                      f"paga {len(occs)} vezes (lotes "
                      f"{', '.join(l.numero for l, _ in occs)}); há "
                      f"ocorrência(s) no balde de revisão manual"),
            referencia=", ".join(l.numero for l, _ in occs),    # os lotes
            valores={"valor": valor},
        )
        for (k, m, valor), occs in ocorrencias_serie.items()
        if len(occs) >= 2 and any(nf is None for _, nf in occs)
    ]
    achados += achados_desempate
    achados += achados_por_regra
    achados += lacunas_de_serie(list(nfs.values()), pares)
    # --- pares anulados: estorno x operacao revertida ---
    # Ultima fase do casamento AUTOMATICO, antes de qualquer alocacao manual.
    # So' encolhe o balde, e sempre de dois em dois com soma zero -- o gap nao
    # muda e a identidade segue fechando por construcao.
    balde, achados_estorno = parear(balde, pares)
    achados += achados_estorno
    # --- id estavel de cada item do balde ---
    # Derivado da ORDEM DA RAZAO (nao da ordem do balde, que muda quando o motor
    # evolui). E o que a alocacao manual usa pra reencontrar o item.
    id_por_lancamento = {id(lanc): identificador
                         for (lanc, _), identificador
                         in zip(pares, ids_da_razao([l for l, _ in pares]))}
    for item in balde:
        item.identificador = id_item([id_por_lancamento[id(l)]
                                      for l in item.lancamentos])
    return ResultadoCasamento(nfs=list(nfs.values()), balde=balde, achados=achados)

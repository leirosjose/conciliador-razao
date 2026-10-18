"""Modelos de dominio puros (zero I/O).

Lancamento, Conta, Achado, NF, ComposicaoItem, Origem e os resultados do motor.
Dinheiro e' SEMPRE Decimal, NUNCA float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from core.classifica import Tipo


class Nivel(Enum):
    """Severidade de um Achado. ERRO so' nos 3 self-checks oficiais;
    ALERTA e' robustez extra (ex.: saldo corrente linha-a-linha).
    INCOMPLETO e' status do veredito da composicao quando ha balde de revisao:
    o gap e' explicado pelo balde, nao e' divergencia contabil."""
    OK = "OK"
    ALERTA = "ALERTA"
    ERRO = "ERRO"
    INCOMPLETO = "INCOMPLETO"


@dataclass
class Lancamento:
    """Uma linha de lancamento da razao. Valores monetarios em Decimal."""
    data: date
    numero: str                 # numero/lote do Dominio (identificador, nao quantia)
    historico: str              # texto CRU; a regex de NF/classificacao vive em parser/historico.py
    cta_part: str               # conta de contrapartida (Cta.C.Part.)
    debito: Decimal
    credito: Decimal
    saldo_exercicio: Decimal    # saldo corrente impresso (col 12), COM sinal


@dataclass
class Conta:
    """Um fornecedor (bloco 'Conta:' ... 'Total da conta:') com seus lancamentos.

    saldo_anterior e total_*_dominio sao COM sinal/valor como vem do Dominio --
    sao a 'verdade' impressa contra a qual o self-check compara.
    """
    codigo: str
    classificacao: str
    nome: str
    data_fim_periodo: date | None = None             # fim do periodo do arquivo (base da idade)
    saldo_anterior: Decimal = Decimal("0.00")        # negativo = credor (a pagar)
    lancamentos: list[Lancamento] = field(default_factory=list)
    total_debito_dominio: Decimal = Decimal("0.00")
    total_credito_dominio: Decimal = Decimal("0.00")

    @property
    def saldo_final(self) -> Decimal:
        """A UNICA definicao de 'qual e o saldo final': o saldo corrente impresso
        na ultima linha; sem lancamentos, e o proprio saldo anterior. Consumido
        pelo self_check_saldo_final E pela conferencia/tela -- uma fonte, N
        consumidores (nao reescrever esta regra noutro lugar)."""
        return (self.lancamentos[-1].saldo_exercicio if self.lancamentos
                else self.saldo_anterior)


@dataclass
class Achado:
    """Resultado de uma verificacao. esperado/encontrado guardam os numeros
    pra o relatorio mostrar a divergencia ao centavo.

    a mensagem do core e' texto NEUTRO (fallback de exibicao) — a frase
    com moeda formatada nasce na apresentacao. Numeros que nao cabem em
    esperado/encontrado vao em `valores` (ex.: residuo da divergencia,
    diferenca do possivel juros)."""
    nivel: Nivel
    codigo: str
    mensagem: str
    esperado: Decimal | None = None
    encontrado: Decimal | None = None
    conta: str | None = None        # codigo da conta de referencia
    # A QUE o achado se refere -- numero de NF, lote(s), ou None quando e'
    # da CONTA inteira. Dado, nao prosa: a apresentacao poe numa COLUNA em vez
    # de o leitor garimpar dentro da frase (continuacao do #34). Guarda o
    # identificador CRU; que TIPO de coisa ele e' quem diz e' o codigo do
    # achado. Nasce onde o achado nasce -- nada aqui e' derivado da mensagem.
    referencia: str | None = None
    valores: dict[str, Decimal] = field(default_factory=dict)
    # evidencia INTEGRAL, quando o achado e a unica prova do que aconteceu.
    # O par de estorno nao deixa linha na composicao (liquido zero), entao a
    # resposta a "cade a baixa?" mora aqui -- lote, data, valor e o historico
    # inteiro dos lancamentos. `valores` so' aceita Decimal; texto vem daqui.
    lancamentos: tuple["Lancamento", ...] = ()


class Origem(Enum):
    """De onde vem o saldo em aberto de um item da composicao."""
    COMPRA_PERIODO = "COMPRA_PERIODO"      # NF comprada dentro do periodo do arquivo
    SALDO_ANTERIOR = "SALDO_ANTERIOR"      # parte do saldo anterior nao detalhada
    ALOCACAO_MANUAL = "ALOCACAO_MANUAL"    # linha criada pelo contador
    # saldo que CHEGOU de outra conta contabil do mesmo
    # fornecedor (matriz/filial). Em aberto legitimo, mas o detalhe NF a NF
    # vive no razao da conta-irma, que nao esta neste arquivo.
    TRANSFERENCIA_SALDO = "TRANSFERENCIA_SALDO"
    # a sobra de um pagamento que CITA NFs e passa da soma delas. Nao
    # e' nota: linha propria, EM ABERTO negativo, sem rotulo (juros,
    # adiantamento ou outro titulo — quem decide nao e' o motor).
    PAGO_A_MAIOR = "PAGO_A_MAIOR"


@dataclass
class Alocacao:
    """Quitacao ALOCADA de um pagamento que cobre N NFs (um-pra-muitos):
    o Lancamento e a evidencia; `valor` e a parte que quitou ESTA NF (o saldo
    dela no momento do casamento — aritmetica, nunca rateio inventado).
    Anexar o mesmo Lancamento nas N listas de pagamentos dobraria o dinheiro."""
    lancamento: Lancamento
    valor: Decimal


class CriterioDesempate(Enum):
    """Como o passe 2b do casamento decidiu um EMPATE que a serie declarada nao
    resolveu. Os dois criterios sao regra de negocio + praxe de ERP (baixa-se o
    titulo mais antigo primeiro) — NUNCA chute: sobrando 2+ elegiveis de mesma
    data, nada e escolhido e o item continua no balde."""
    UNICA_EM_ABERTO = "UNICA_EM_ABERTO"     # so uma candidata ainda comportava o pagamento
    # FIFO por data de emissao: com duas compras de mesmo valor e datas diferentes,
    # a parcela sem NF segue a ordem cronologica entre as compras e os pagamentos
    # das parcelas sequenciais. A condicao "datas diferentes" e' a guarda que ja
    # existia: 2+ na MESMA data nunca escolhe.
    DATA_MAIS_ANTIGA = "DATA_MAIS_ANTIGA"   # FIFO: emissao mais antiga entre as elegiveis


@dataclass
class Desempate:
    """Rastreabilidade de um casamento decidido por REGRA, nao por unicidade:
    qual lancamento, por qual criterio, contra quais candidatas. O conferente
    precisa saber que ali a maquina escolheu."""
    lancamento: Lancamento
    criterio: CriterioDesempate
    candidatos: tuple[str, ...] = ()


class RegraCasamento(Enum):
    """Casamento decidido por INFERENCIA sobre o que o historico declara,
    sem o numero da NF e sem o valor pago bater. Irmao do desempate: o
    conferente precisa saber que ali o motor ligou por regra, e nao por
    unicidade de valor. Sai marcado (achado + nota na linha)."""
    # "Valor de R$ X (Parcela k de M)" e M x X == compra de UMA NF aberta
    VALOR_DECLARADO = "VALOR_DECLARADO"
    # "kª PARCELA" sem NF continua a serie que 2+ parcelas CITANDO a NF
    # ja tem, com guardas de cronologia e de disputa
    SERIE_ORDINAL = "SERIE_ORDINAL"


@dataclass
class CasamentoPorRegra:
    """Rastreabilidade do casamento por inferencia: qual lancamento, por
    qual regra. Vive na NF que recebeu, como o Desempate."""
    lancamento: Lancamento
    regra: RegraCasamento


@dataclass
class NF:
    """Nota fiscal reconstruida: a compra (se houver no periodo) e os lancamentos
    que a quitam (pagamentos + retencoes + baixas de adiantamento), ligados pelo
    numero. Baixa e retencao sao a mesma familia: quitacao sem numerario."""
    numero: str
    valor_compra: Decimal = Decimal("0.00")          # 0.00 se sem compra no periodo
    data_compra: date | None = None
    pagamentos: list[Lancamento] = field(default_factory=list)
    retencoes: list[Lancamento] = field(default_factory=list)
    baixas: list[Lancamento] = field(default_factory=list)
    alocacoes: list[Alocacao] = field(default_factory=list)   # pagamento multi-NF
    desempates: list[Desempate] = field(default_factory=list)  # casados por regra
    por_regra: list[CasamentoPorRegra] = field(default_factory=list)  # inferencia declarada
    manuais: list[Lancamento] = field(default_factory=list)    # alocados a mao
    # as LINHAS de compra (credito) que formam valor_compra -- evidencia,
    # nao conta: valor_compra continua sendo a soma. O corte por saldo zero
    # precisa saber de que lado do zero a compra caiu.
    compras: list[Lancamento] = field(default_factory=list)
    criada_manualmente: bool = False       # linha que NAO veio da razao
    # esta "NF" e' na verdade um saldo transferido da conta-irma. Flag, e
    # nao deducao pelo nome: o nome e' rotulo e pode mudar; o que a linha E'
    # nao pode depender de parsing de string.
    transferencia: bool = False
    # esta "NF" e' a sobra de um pagamento multi-NF (flag pelo mesmo
    # motivo da transferencia: o que a linha E' nao depende do nome)
    pago_a_maior: bool = False

    # familia de quitacao: fonte UNICA. compor() e total_quitado
    # consomem daqui; adicionar uma familia nova = mais uma property, nao editar
    # varios somatorios espalhados.
    @property
    def total_pago(self) -> Decimal:
        # pagamento em numerario + alocacao de pagamento multi-NF (Fase 1.5)
        return (sum((l.debito for l in self.pagamentos), Decimal("0.00"))
                + sum((a.valor for a in self.alocacoes), Decimal("0.00")))

    @property
    def total_retido(self) -> Decimal:
        return sum((l.debito for l in self.retencoes), Decimal("0.00"))

    @property
    def total_baixado(self) -> Decimal:
        return sum((l.debito for l in self.baixas), Decimal("0.00"))

    @property
    def total_manual(self) -> Decimal:
        """Alocacao manual pelo LIQUIDO: debito quita, credito reabre. Um
        caminho so pros dois lados — o sinal resolve, sem mexer em valor_compra."""
        return sum((l.debito - l.credito for l in self.manuais), Decimal("0.00"))

    @property
    def qtd_quitacoes(self) -> int:
        return (len(self.pagamentos) + len(self.retencoes)
                + len(self.baixas) + len(self.alocacoes) + len(self.manuais))

    @property
    def total_quitado(self) -> Decimal:
        return (self.total_pago + self.total_retido + self.total_baixado
                + self.total_manual)

    @property
    def saldo_aberto(self) -> Decimal:
        return self.valor_compra - self.total_quitado


@dataclass
class ComposicaoItem:
    """Uma linha da composicao do saldo: quanto de uma NF (ou do saldo anterior)
    esta em aberto, com a idade da compra. A baixa de adiantamento aparece
    IDENTIFICADA (total_baixado), nunca mascarada de pagamento."""
    nf_numero: str
    origem: Origem
    valor_compra: Decimal
    total_pago: Decimal
    total_retido: Decimal
    saldo_aberto: Decimal
    total_baixado: Decimal = Decimal("0.00")
    # o VALOR alocado a mao, pelo liquido (credito reabre -> negativo). So' a
    # contagem (quitacoes_manuais) nao bastava: a coluna "Total pago" nao
    # tinha como mostrar o que o contador alocou. Identidade da TABELA, em todo
    # item: valor_compra - total_pago - total_retido - total_baixado -
    # total_manual == saldo_aberto (a casca nao faz conta; o teste confere).
    total_manual: Decimal = Decimal("0.00")
    idade_dias: int | None = None        # contra data_fim_periodo; None se sem data_compra
    data_compra: date | None = None      # None no item (anterior) e em NF sem compra
    data_ultima_quitacao: date | None = None   # max da familia inteira (inclui manuais); None se nada
    qtd_quitacoes: int = 0               # pgtos + retencoes + baixas + alocacoes + manuais ligados
    desempates: tuple[CriterioDesempate, ...] = ()   # quitacoes casadas por regra
    por_regra: tuple[RegraCasamento, ...] = ()       # casadas por inferencia declarada
    quitacoes_manuais: int = 0           # quitacoes alocadas pelo contador
    # data do PRIMEIRO pagamento casado antes da emissao da NF.
    # Fato pra linha; nao muda destino nem rotula adiantamento.
    pagamento_antes_da_emissao: date | None = None

    @property
    def e_nota(self) -> bool:
        """A linha e' uma NOTA: compra do periodo ou compra nova a mao.
        Saldo anterior, transferencia e pago a maior do lote sao linhas do
        motor -- nao entram nos totais de "Valor compra" e "Total pago"
       ; o valor delas fica em EM ABERTO. Fonte unica da regra."""
        return self.origem in (Origem.COMPRA_PERIODO, Origem.ALOCACAO_MANUAL)

    @property
    def quitada_com_arredondamento(self) -> bool:
        """Aberto NEGATIVO cujo residuo cabe na tolerancia de centavos das
        parcelas (1 centavo por quitacao — a MESMA regra do casamento):
        o casamento aceitou dentro dela; alertar juros sobre esse residuo
        seria contradicao interna. Fonte unica — veredito (suprime o alerta)
        e apresentacao (nota informativa) consomem daqui."""
        return (self.saldo_aberto < Decimal("0.00")
                and -self.saldo_aberto <= self.qtd_quitacoes * Decimal("0.01"))


class MotivoRevisao(Enum):
    """Por que um lancamento foi pro balde de revisao manual (nunca chuta)."""
    SEM_VINCULO = "SEM_VINCULO"            # nenhuma NF candidata por valor
    EMPATE = "EMPATE"                      # 2+ candidatos -> ambiguo
    NAO_CLASSIFICADO = "NAO_CLASSIFICADO"  # historico sem padrao reconhecido
    ESTORNO_SEM_PAR = "ESTORNO_SEM_PAR"    # estorno reconhecido, sem a operacao
                                           # correspondente no balde
    MULTI_NF_NAO_CONFERE = "MULTI_NF_NAO_CONFERE"  # cita 2+ NFs; condicao do
                                                   # um-pra-muitos falhou
    # credito reconhecido como recebimento do fornecedor. Fica no
    # balde: decidir se e' recebimento tem subjetividade, fica com quem confere
    RECEBIMENTO = "RECEBIMENTO"
    # historico de compra com o valor no DEBITO, ou de quitacao
    # (pagamento, retencao, baixa) com o valor no CREDITO. Nunca entra numa NF:
    # antes somava 0 a ela e o dinheiro sumia. O tipo que o
    # historico declarou vai em ItemRevisao.tipo_declarado.
    LADO_INESPERADO = "LADO_INESPERADO"


@dataclass
class ItemRevisao:
    """Um pagamento (ou conjunto) que NAO casou de forma inequivoca e foi
    encaminhado a revisao manual. Canal proprio, separado de OK/ALERTA/ERRO."""
    lancamentos: list[Lancamento]
    motivo: MotivoRevisao
    candidatos: list[str] = field(default_factory=list)   # numeros das NFs no empate ([] se sem vinculo)
    mensagem: str = ""
    # id ESTAVEL derivado do conteudo da razao: e por ele que a alocacao
    # manual da tela reencontra o item na execucao seguinte. Preenchido por casar();
    # a regra vive em core/identificacao.py.
    identificador: str = ""
    valores: dict[str, Decimal] = field(default_factory=dict)  # numeros da
    # mensagem: a apresentacao formata (ex.: soma/pagamento do multi-NF)
    # destino PROVAVEL proposto pelo motor. Inerte — o item continua no
    # balde e o gap nao muda; a tela pre-seleciona e o contador confirma.
    sugestao: "Sugestao | None" = None
    # SO' em LADO_INESPERADO -- o tipo que o historico declarou
    # (COMPRA, PAGAMENTO, RETENCAO ou BAIXA_ADIANTAMENTO). E' o que a tela
    # nomeia ("Compra lançada a débito"...); o lado o lancamento ja diz.
    tipo_declarado: "Tipo | None" = None
    # SO' em SEM_VINCULO -- o numero que o historico citava e a
    # regra da citacao sem nota tirou (sem compra na razao, citacoes ja acima do saldo anterior)
    nf_citada: str | None = None


class DestinoAlocacao(Enum):
    """Pra onde o CONTADOR mandou um item do balde. O motor nao decide
    nada aqui: recebe a decisao pronta e refaz a composicao do zero."""
    LINHA_ABERTA = "LINHA_ABERTA"              # NF em aberto OU a linha "(anterior)"
    COMPRA_NOVA = "COMPRA_NOVA"                # vira linha propria da composicao
    FORA_DA_COMPOSICAO = "FORA_DA_COMPOSICAO"  # sai do balde com justificativa


# rotulo da linha de saldo anterior: alvo valido de alocacao e nome do item que
# compor() ja produz. Um nome so, nos dois lados.
ALVO_ANTERIOR = "(anterior)"


class CriterioSugestao(Enum):
    """Por que o motor SUGERE um destino sem ter prova de exclusao.

    A fronteira: prova por exclusao aritmetica CASA (o item sai do
    balde); inferencia forte apenas SUGERE (o item FICA no balde e o contador
    confirma em um clique). O preco de errar um casamento e o cliente receber
    uma composicao afirmando uma quitacao que ninguem provou.

    Nos comentarios e testes das regras de sugestao, as letras sao: C = serie
    declarada x saldo remanescente; D = serie declarada x valor de compra;
    E = continuidade da serie ordinal."""
    SERIE_X_SALDO_REMANESCENTE = "SERIE_X_SALDO_REMANESCENTE"   # regra C
    SERIE_X_VALOR_DECLARADO = "SERIE_X_VALOR_DECLARADO"         # regra D
    CONTINUIDADE_SERIE_ORDINAL = "CONTINUIDADE_SERIE_ORDINAL"   # regra E


@dataclass(frozen=True)
class Sugestao:
    """Destino PROVAVEL de um item do balde, com a evidencia que o sustenta.

    NAO e casamento: o item continua no balde, o gap continua o mesmo e o
    veredito continua INCOMPLETO pelo mesmo valor. O que muda e o TRABALHO do
    contador — em vez de escolher entre N linhas, ele confere uma proposta.

    `frozen` pelo mesmo motivo da AlocacaoManual: circula entre core, tela e
    planilha e nao pode ser reescrita no meio do caminho."""
    destino: DestinoAlocacao
    criterio: CriterioSugestao          # sem porque nao ha sugestao
    alvo: str = ""                      # numero da NF ou ALVO_ANTERIOR
    # numeros CRUS: a frase com R$ nasce na apresentacao, nunca aqui
    evidencia: dict[str, Decimal] = field(default_factory=dict)
    candidatos: tuple[str, ...] = ()    # o que mais foi considerado e descartado


@dataclass(frozen=True)
class AlocacaoManual:
    """Decisao do contador sobre UM item do balde. `frozen` de proposito: vive
    no estado de sessao da tela e nao pode ser mutada por engano."""
    item_id: str                       # ItemRevisao.identificador (estavel)
    destino: DestinoAlocacao
    alvo: str = ""                     # numero da NF ou ALVO_ANTERIOR (LINHA_ABERTA)
    rotulo: str = ""                   # nome da linha nova / justificativa do fora
    # preenchido quando o contador CONFIRMOU a proposta do motor (a tela
    # compara a opcao escolhida com a sugestao no clique). Escolha propria dele
    # fica None -- origem so se declara quando existe. Metadado de
    # rastreabilidade: o core nao valida e nao decide nada com ele.
    criterio_sugerido: CriterioSugestao | None = None


@dataclass
class DecisaoManual:
    """Uma alocacao APLICADA: o item que saiu do balde, pra onde foi e a
    evidencia integral. Fonte unica da secao de decisoes do Excel."""
    item: ItemRevisao
    destino: DestinoAlocacao
    alvo: str = ""
    rotulo: str = ""
    criterio_sugerido: CriterioSugestao | None = None   # proposta aceita

    @property
    def valor(self) -> Decimal:
        """O que o item pesa na identidade: Σ(debito − credito)."""
        return sum((l.debito - l.credito for l in self.item.lancamentos),
                   Decimal("0.00"))


@dataclass
class ErroAlocacao:
    """Alocacao que NAO pode ser aplicada. O item continua no balde (a
    identidade segue fechando) e a tela mostra isto colado na alocacao."""
    alocacao: AlocacaoManual
    codigo: str
    mensagem: str


@dataclass
class ResultadoCasamento:
    """Saida de `casar`: as NFs reconstruidas (entram na composicao), o balde
    de revisao manual (saida separada, nao entra na composicao) e as
    sinalizacoes que SO o casamento sabe produzir (possivel duplicidade
    de parcela — ALERTA, nunca altera a composicao)."""
    nfs: list[NF] = field(default_factory=list)
    balde: list[ItemRevisao] = field(default_factory=list)
    achados: list[Achado] = field(default_factory=list)


@dataclass(frozen=True)
class PonteSaldo:
    """O caminho do saldo anterior + compras ate o saldo do Dominio.

    E' a identidade do gap (gap == Σ balde + Σ fora) ABERTA em linhas
    -- nenhum numero de regra novo, so' os totais do que o motor ja produziu.
    Convencao "a pagar" positivo, a mesma do alvo do self_check (-saldo_final).

    SEM juiz proprio: `diferenca` e' o residuo do self_check_composicao e o
    status (OK / tolerado / DIVERGE) e' o do veredito. Numeros crus: o
    operador de exibicao, o rotulo e a moeda nascem na apresentacao.
    `frozen` pelo mesmo motivo da Sugestao: circula ate a tela e a planilha."""
    saldo_anterior: Decimal              # |saldo_anterior|, o MESMO da linha "(saldo anterior)"
    total_compras: Decimal               # so' o que a razao trouxe como compra
    total_transferencias: Decimal        # credito vindo da conta-irma
    total_pago: Decimal                  # numerario + multi-NF, inclui o que quitou o anterior
    total_retido: Decimal
    total_baixa_adiantamento: Decimal    # inclui transferencia em debito (quita como baixa)
    total_alocado_manual: Decimal        # liquido D-C do que o contador poe NA composicao
    # o topo soma a razao INTEIRA e chega no aberto NF a NF; o que
    # o corte por saldo zero tirou da composicao sai numa linha propria, pelo
    # liquido do balde do periodo zerado (== o aberto de la: trava do corte)
    total_em_aberto_nf_a_nf: Decimal
    total_compensado_saldo_zero: Decimal
    total_em_aberto: Decimal             # Σ saldo_aberto da composicao
    balde_debitos: Decimal               # bruto, do balde que SOBROU (pos-corte)
    balde_creditos: Decimal
    total_fora_composicao: Decimal       # liquido D-C das decisoes "fora"
    saldo_apurado: Decimal
    saldo_dominio: Decimal               # -conta.saldo_final

    @property
    def diferenca(self) -> Decimal:
        return self.saldo_apurado - self.saldo_dominio

    @property
    def balde_liquido(self) -> Decimal:
        """O que o balde ainda pesa no saldo (D−C) -- o "R$ X ainda no balde"
        do status da ponte. Mesma soma da identidade do self_check."""
        return self.balde_debitos - self.balde_creditos


@dataclass(frozen=True)
class TotaisComposicao:
    """A linha TOTAL da tabela de composicao: soma de cada coluna
    monetaria sobre o que a tabela MOSTRA (itens + quitadas).
    Dinheiro, entao nasce no core -- a casca so' formata.

    `valor_compra` e `total_pago` somam SO as notas (ComposicaoItem.
    e_nota); as linhas do motor (saldo anterior, transferencia, pago a maior)
    ficam fora deles e entram so' em `saldo_aberto`. Por isso a identidade da
    tabela so' vale nos totais quando nao ha linha sem nota.

    Os totais de "Valor compra" e "Total pago" nem sempre batem com as linhas
    da ponte: quando pagamento consome o saldo anterior inteiro, a linha
    "(saldo anterior)" zera e some da tabela, e com ela o trazido e o pago.
    Os dois `*_fora_da_tabela` sao essa diferenca, medida (ponte − coluna);
    a nota da tela so' aparece quando um deles nao e' zero."""
    valor_compra: Decimal
    total_pago: Decimal
    total_retido: Decimal
    total_baixado: Decimal
    total_manual: Decimal
    saldo_aberto: Decimal
    compra_fora_da_tabela: Decimal = Decimal("0.00")
    pago_fora_da_tabela: Decimal = Decimal("0.00")


@dataclass
class BlocoZerado:
    """O que ficou PENDENTE entre dois zeros do saldo: as NFs com saldo
    NF a NF e os lancamentos sem NF que o `zero` fechou. Soma e diferenca
    nascem aqui (core), a tela so' le."""
    zero: "Lancamento"
    itens: list[ComposicaoItem] = field(default_factory=list)
    balde: list[ItemRevisao] = field(default_factory=list)

    @property
    def total_aberto(self) -> Decimal:
        return sum((i.saldo_aberto for i in self.itens), Decimal("0.00"))

    @property
    def total_sem_nf(self) -> Decimal:
        return sum((l.debito - l.credito for item in self.balde
                    for l in item.lancamentos), Decimal("0.00"))

    @property
    def diferenca(self) -> Decimal:
        return self.total_sem_nf - self.total_aberto

    @property
    def bate(self) -> bool:
        """O sem NF do bloco cobre EXATAMENTE as NFs do bloco. Pode nao bater
        mesmo com o total do periodo batendo: uma NF comprada num bloco e
        paga em parte no seguinte conta no bloco do ultimo lancamento."""
        return self.diferenca == Decimal("0.00")


@dataclass
class FechadoPorSaldoZero:
    """O periodo que o corte por saldo zero tirou da composicao.

    O saldo-exercicio zerou em `data` (lote `lote`): tudo ate ali se compensa
    no AGREGADO e o saldo final nao depende disso. Zero agregado NAO prova
    quitacao NF a NF -- por isso `itens` (NFs com saldo NF a NF e a linha do
    saldo anterior) e `balde` (lancamentos sem NF) ficam aqui como
    INFORMACAO, nunca como "quitada" e nunca como fila de decisao.
    Identidade propria, garantida pela trava do corte: total_aberto ==
    total_sem_nf."""
    data: date
    lote: str
    zeros: tuple[Lancamento, ...] = ()    # todas as vezes que zerou ate o corte
    itens: list[ComposicaoItem] = field(default_factory=list)
    balde: list[ItemRevisao] = field(default_factory=list)
    # NF / identificador do item / ALVO_ANTERIOR -> o lancamento do zero que o
    # fecha (data E lote)
    zerou_em: dict[str, Lancamento] = field(default_factory=dict)

    @property
    def total_aberto(self) -> Decimal:
        return sum((i.saldo_aberto for i in self.itens), Decimal("0.00"))

    @property
    def total_sem_nf(self) -> Decimal:
        return sum((l.debito - l.credito for item in self.balde
                    for l in item.lancamentos), Decimal("0.00"))

    @property
    def tem_conteudo(self) -> bool:
        """A secao da tela aparece quando ha o que mostrar (D3: nada some)."""
        return bool(self.itens or self.balde)

    @property
    def blocos(self) -> list[BlocoZerado]:
        """A pendencia agrupada pelo zero que a fechou, na ordem da razao.
        So' blocos com pendencia: NF com saldo NF a NF ou lancamento sem NF."""
        por_zero: dict[int, BlocoZerado] = {}
        for i in self.itens:
            if i.saldo_aberto == Decimal("0.00"):
                continue
            zero = self.zerou_em[i.nf_numero]
            por_zero.setdefault(id(zero), BlocoZerado(zero)).itens.append(i)
        for item in self.balde:
            zero = self.zerou_em[item.identificador]
            por_zero.setdefault(id(zero), BlocoZerado(zero)).balde.append(item)
        ordem = {id(z): k for k, z in enumerate(self.zeros)}
        return sorted(por_zero.values(), key=lambda b: ordem[id(b.zero)])

    @property
    def tem_pendencia(self) -> bool:
        """Ha o que AVISAR: NF com saldo NF a NF ou lancamento sem NF. A linha
        do saldo anterior zerada (uma baixa identificada) e' evidencia,
        aparece na secao, mas nao e' pendencia."""
        return bool(self.balde) or any(i.saldo_aberto != Decimal("0.00")
                                       for i in self.itens)


@dataclass
class ResultadoConferencia:
    """Bundle que a casca de UI renderiza, devolvido por core.conferencia.conferir:
    a conta conferida, a composicao do saldo (itens), o balde de revisao manual e
    os achados (self-check de parsing + composicao) numa lista so. SEM logica --
    so agrega o que o core ja produziu."""
    conta: Conta
    itens: list[ComposicaoItem] = field(default_factory=list)
    balde: list[ItemRevisao] = field(default_factory=list)
    achados: list[Achado] = field(default_factory=list)
    # as NFs do periodo que FECHARAM, em canal proprio -- a foto
    # completa pro conferente (prova de que fecharam). `itens` continua sendo
    # so' o que esta aberto; identidade e self_checks leem de `itens`.
    quitadas: list[ComposicaoItem] = field(default_factory=list)
    # o que o CONTADOR decidiu nesta execucao, e o que nao pode ser aplicado.
    # Canal proprio: erro de alocacao nao e divergencia contabil e nao entra no
    # veredito -- a tela mostra colado na alocacao, com o botao desfazer.
    decisoes: list[DecisaoManual] = field(default_factory=list)
    erros_alocacao: list[ErroAlocacao] = field(default_factory=list)
    # a ponte do saldo. None so' em resultado montado a mao (testes de
    # casca); conferir() sempre preenche.
    ponte: PonteSaldo | None = None
    totais_tabela: TotaisComposicao | None = None
    # o TOTAL do que a tela mostra POR PADRAO -- so' as linhas com EM
    # ABERTO != 0 (itens_em_aberto). Dinheiro, entao nasce no core.
    totais_em_aberto: TotaisComposicao | None = None
    # o periodo que o corte por saldo zero tirou da composicao.
    # None quando nao houve corte (razao que nunca zera, leitura nao conferida
    # ou todo zero cruzado).
    fechado: FechadoPorSaldoZero | None = None
    # as NFs reconstruidas -- pos-corte + periodo zerado, as MESMAS
    # que a ponte recebe. Evidencia, nao conta nova: e' de onde se le em que
    # linha cada lancamento terminou (a invariante de lugar). Vazio so' em
    # resultado montado a mao (testes de casca).
    nfs: list[NF] = field(default_factory=list)

    @property
    def itens_em_aberto(self) -> list[ComposicaoItem]:
        """As linhas da composicao com EM ABERTO != 0: o que a tela
        mostra por padrao. Fonte UNICA do recorte -- os totais_em_aberto sao
        a soma exatamente disto; a tela nao refaz o filtro."""
        return [i for i in self.itens if i.saldo_aberto != Decimal("0.00")]

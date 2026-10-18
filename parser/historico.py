"""Reconhecimento de historico da FIRMA (regex). VIVE FORA DO CORE.

O historico da razao e escrito pela equipe do escritorio no Dominio — o vocabulario
e finito e DA FIRMA, nao de cada cliente (antes havia um classificador
por cliente). Biblioteca DECLARATIVA ordenada: mais especifico primeiro, o
primeiro padrao que casa decide o TIPO; padrao novo = 1 linha em PADROES.
TUDO compila com re.IGNORECASE — "ESTORNO DE BAIXA" maiusculo nao escapa.

Extracao de NF: pelo grupo nomeado (?P<nf>...) do proprio padrao quando ha, ou
pelo MARCADOR de NF no historico (extrai_nf=True): "NF 31478", "NFS: 4126",
"Nº 39605", "NF-62831", com continuacoes "E <num>" ("AS NF 48217 E 48218").
1 NF distinta -> nf_numero preenchido (Fase 1 do casamento); 2+ -> None
(ambiguo: cascata por valor/balde decide — nunca chuta). "codigo 6140" nao e
marcador; "plano de conta 20.03.05" e datas nao extraem (numeros de 2 digitos
ou sem marcador). Compra e marcador exigem 3+ digitos (antes a
compra exigia 4+, assimetria registrada sem motivo).

Sem padrao casado -> Tipo.OUTRO (vai pro balde NAO_CLASSIFICADO do
casamento; nunca some em silencio).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from core.classifica import Classificacao, Tipo

# marcador de NF + numero(s); continuacoes "E <num>" fazem parte do match.
# o "N" abre palavra -- sem a trava, o "nf" de "conf. 197" virava
# "NF 197" (centenas de historicos de compra; mordia quando a compra falhava).
_MARCADOR_NF = re.compile(
    r"(?<![A-Za-z])N(?:FS?|º)\.?\s*(?:[-.:]\s*)?(\d{3,}(?!\d|\.\d{3})(?:\s+E\s+(?:N(?:FS?|º)\.?\s*(?:[-.:]\s*)?)?\d{3,})*)",
    re.IGNORECASE)
# LISTA de NFs com ", " e "/" alem do " E " -- SO' no pagamento.
# Retencao/baixa/transferencia citando 2+ NFs cai na Fase 2 por valor
# (o destino delas e' decisao em aberto): ate' la' elas leem so' o " E " de hoje.
# " E <num>" fica como hoje. So' depois de ", " ou
# "/" o numero nao pode vir colado a digito, a ",digito" (valor "150,00") nem
# a ".ddd" (milhar "125.000"); ".2"/".12" (parcela) passa. Na duvida a lista
# nao continua -- e' o comportamento de hoje. "NF 1234/1" segue 1 NF.
_MARCADOR_NF_LISTA = re.compile(
    r"(?<![A-Za-z])N(?:FS?|º)\.?\s*(?:[-.:]\s*)?(\d{3,}(?!\d|\.\d{3})(?:\s+E\s+(?:N(?:FS?|º)\.?\s*(?:[-.:]\s*)?)?\d{3,}|\s*[,/]\s*(?:N(?:FS?|º)\.?\s*(?:[-.:]\s*)?)?\d{3,}(?!\d|,\d|\.\d{3}))*)",
    re.IGNORECASE)
# antes do "N" so' LETRA ASCII barra o marcador; '-', '_',
# digito e letra acentuada nao ("PAG-NF 1001", "1NF 1001" e "co-nf. 197" leem NF).
_NUMERO = re.compile(r"\d{3,}")
# "(Parcela 3 de 5)" ou "7ª PARCELA" -> k; o M ("de 5") e' metadado DECLARADO
# que alimenta o desempate por serie -- captura, nao heuristica
_PARCELA = re.compile(r"Parcela\s+(\d+)\s+de\s+(\d+)|(\d+)ª\s+PARCELA", re.IGNORECASE)

# o VALOR que o historico declara pra a parcela. Unico ponto do
# sistema onde dinheiro nasce de TEXTO LIVRE, entao a captura e ANCORADA:
# casa o valor e o marcador de parcela como UMA coisa so'.
#
# Por que ancorar, e nao pegar "o primeiro R$" ou "o ultimo": o template da
# firma tem DUAS casas de dinheiro com significados diferentes --
#
#   Valor de R$ 271,05 (Parcela 3 de 3). Referente a NF ... no valor de R$ 845,17
#             ^ a PARCELA                                              ^ o TOTAL do documento
#
# e elas DIVERGEM na maioria dos historicos medidos que declaram parcela.
# Divergir e o normal, nao o suspeito: 271,05 e a terceira parcela de
# uma NF de 845,17 dividida em tres parcelas desiguais. So' o valor colado ao
# marcador e a parcela.
#
# Milhar em grupos de 3 e centavos OBRIGATORIOS: "R$ 636" nao casa, porque nao
# capturar e melhor que ler um texto truncado como 636,00.
_VALOR_PARCELA = re.compile(
    r"Valor\s+de\s+R\$\s*(?P<valor>\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})"
    r"\s*\(\s*Parcela\s+\d+\s+de\s+\d+\s*\)", re.IGNORECASE)


def _decimal_br(texto: str) -> Decimal:
    """'3.587,26' -> Decimal('3587.26'). NUNCA passa por float."""
    return Decimal(texto.replace(".", "").replace(",", "."))


def _valor_declarado(historico: str) -> Decimal | None:
    """O valor da parcela declarado no historico, ou None.

    None quando o padrao ancorado casa 2+ vezes com valores DIFERENTES: o texto
    esta ambiguo e sem valor nao ha sugestao. Repetir o MESMO valor
    nao e ambiguidade."""
    achados = {m.group("valor") for m in _VALOR_PARCELA.finditer(historico)}
    if len(achados) != 1:
        return None
    return _decimal_br(achados.pop())


@dataclass(frozen=True)
class Padrao:
    """Um item da biblioteca: o regex decide o TIPO; extrai_nf=True busca a NF
    pelo marcador no historico inteiro (alem dos grupos nomeados do regex).
    `estorna` so' vale em Tipo.ESTORNO: diz que operacao aquele estorno reverte
    -- e a declaracao que o pareamento usa como prova."""
    regex: re.Pattern
    tipo: Tipo
    extrai_nf: bool = False
    estorna: Tipo | None = None


PADROES: list[Padrao] = [
    # estorno ANTES de baixa: "estorno de BAIXA DE ADIANTAMENTO" nunca e baixa.
    # O DECLARADO vem antes do generico, senao o \bestorno\b engoliria a
    # declaracao e o par perderia sua prova.
    Padrao(re.compile(r"\bestorno\b.*\bBAIXA\s+DE\s+ADIANTAMENTO\b", re.IGNORECASE),
           Tipo.ESTORNO, estorna=Tipo.BAIXA_ADIANTAMENTO),
    Padrao(re.compile(r"\bestorno\b", re.IGNORECASE), Tipo.ESTORNO),
    Padrao(re.compile(r"BAIXA\s+DE\s+ADIANTAMENTO", re.IGNORECASE),
           Tipo.BAIXA_ADIANTAMENTO, extrai_nf=True),
    # saldo entre contas do MESMO fornecedor
    # (matriz/filial). DEPOIS do \bestorno\b — "ESTORNO DE TRANSFERENCIA DE
    # SALDOS" e' estorno, a mesma precedencia da baixa de adiantamento. ANTES do
    # marcador de NF e do verbo de pagamento: e' o padrao mais especifico, e
    # "PGTO ... TRANSFERENCIA DE SALDOS" nao pode virar pagamento generico.
    # "SALDOS?" cobre o singular; SEM \btransferencia\b solto, senao
    # "TRANSFERENCIA BANCARIA" entraria — o padrao descreve saldo
    # migrando entre contas, nao qualquer transferencia. O E com acento e'
    # alternativa explicita: o arquivo do Dominio traz as duas grafias.
    Padrao(re.compile(r"TRANSFER[EÊ]NCIA\s+DE\s+SALDOS?\b", re.IGNORECASE),
           Tipo.TRANSFERENCIA_SALDO, extrai_nf=True),
    # "Recebimento conf. RECEBIMENTO PIX ..." -- credito do
    # fornecedor que nao e' compra. Depois do \bestorno\b (estorno de
    # recebimento e' estorno) e ANTES do marcador de NF: um recebimento que
    # citasse NF nao pode virar pagamento. O destino continua o balde;
    # so' o nome do motivo muda.
    Padrao(re.compile(r"\brecebimento\b", re.IGNORECASE), Tipo.RECEBIMENTO),
    # retencao MANTEM extracao de NF (senao a Fase 1 perde retencao vinculada).
    # Vocabulario COMPLETO da ordem que os ERPs geram: INSS/IRRF/ISS/
    # COFINS/PIS/CSLL. ISSQN e alternativa PROPRIA — \bISS\b nao a alcanca.
    Padrao(re.compile(r"\b(?:IRRF|CSLL|INSS|ISSQN|ISS|PIS|COFINS)\b", re.IGNORECASE),
           Tipo.RETENCAO, extrai_nf=True),
    # NF de 3+ digitos (era 4+). Ha NF de 3 digitos de
    # verdade; com 4+ a compra caia no marcador e virava pagamento em credito
    Padrao(re.compile(r"compras\s+conf\..*?\b(?P<nf>\d{3,})\b", re.IGNORECASE),
           Tipo.COMPRA),
    # compra em outro template de importacao, "valor ref <NF>
    # <FORNECEDOR>". Sem "a" e sem ponto: nao colide com o
    # "Valor ref. a" do extrato. Em debito, a trava de lado do core
    Padrao(re.compile(r"^\s*valor\s+ref\s+(?P<nf>\d{3,})\b", re.IGNORECASE),
           Tipo.COMPRA),
    # formato "PAGTO REF. NF.: NNN.P" antes do marcador generico (preserva a parcela).
    # NF com 3+ digitos, como o marcador e a compra ("1.234.2"
    # lia NF 1, parcela 234)
    Padrao(re.compile(r"PAGTO\s+REF\.\s*NF\.:\s*(?P<nf>\d{3,})\.(?P<parcela>\d+)",
                      re.IGNORECASE), Tipo.PAGAMENTO),
    # NF citada num debito de fornecedor = pagamento referenciando a NF
    Padrao(_MARCADOR_NF, Tipo.PAGAMENTO, extrai_nf=True),
    # verbo de pagamento sem NF citada -> cascata por valor (Fase 2).
    # "PAYMENT" e' o mesmo verbo em outro template de campo ("Pago
    # <fornecedor> PAYMENT <CNPJ>"), que ia pro balde como OUTRO enquanto o
    # irmao "... Pagamento de contas para <CNPJ>" casava. O CNPJ nao tem
    # marcador de NF e nao vira NF; "REPAYMENT" nao casa (\b).
    # verbos do extrato bancario --
    # "BOLETO PAGO <X>", "Pago <X>" sem "conf.", "PAGAMENTOS <X>",
    # "LIQUIDACAO BOLETO <CNPJ> <X>", "PIX QR-CODE". PIX solto NAO: "PIX
    # ENVIADO <pessoa>" nao e' pagamento a fornecedor. Credito com o verbo
    # cai na trava de lado do core.
    Padrao(re.compile(r"\b(?:pago|pgto|pagamentos?|payment"
                      r"|liquida[cç][aã]o\s+(?:de\s+)?boleto"
                      r"|pix\s+qr[- ]?code)\b",
                      re.IGNORECASE), Tipo.PAGAMENTO),
    # quitacao GENERICA (ULTIMO da biblioteca, o fallback e o OUTRO
    # implicito): "Valor ref. a <razao social> - <CNPJ de 14 digitos>".
    # Debito em conta de fornecedor reduz obrigacao (partida dobrada) --
    # pagamento, devolucao ou abatimento tem o MESMO efeito na composicao.
    # Sem numero: a Fase 2 decide, e ela so casa o inequivoco.
    Padrao(re.compile(r"Valor\s+ref\.\s*a\s+.+-\s*\d{14}\b", re.IGNORECASE),
           Tipo.PAGAMENTO),
]


def _nfs_citadas(historico: str,
                 marcador: re.Pattern = _MARCADOR_NF) -> list[str]:
    """Numeros de NF citados via marcador, na ordem, sem repeticao."""
    vistos: list[str] = []
    for m in marcador.finditer(historico):
        for n in _NUMERO.findall(m.group(1)):
            if n not in vistos:
                vistos.append(n)
    return vistos


def _extrair(padrao: Padrao, m: re.Match,
             historico: str) -> tuple[str | None, tuple[str, ...],
                                      int | None, int | None]:
    grupos = m.groupdict()
    nf = grupos.get("nf")
    citadas: tuple[str, ...] = (nf,) if nf else ()
    if padrao.extrai_nf:
        nfs = _nfs_citadas(historico, _MARCADOR_NF_LISTA
                           if padrao.tipo is Tipo.PAGAMENTO else _MARCADOR_NF)
        citadas = tuple(nfs)
        nf = nfs[0] if len(nfs) == 1 else None    # 2+ distintas -> ambiguo
    parcela = int(grupos["parcela"]) if grupos.get("parcela") else None
    parcela_de = None
    mp = _PARCELA.search(historico)
    if mp:
        if parcela is None:
            parcela = int(mp.group(1) or mp.group(3))
        parcela_de = int(mp.group(2)) if mp.group(2) else None
    return nf, citadas, parcela, parcela_de


# "Valor ref. a <X>" SEM CNPJ (o generico exige CNPJ). Ultimo
# recurso, fora da biblioteca porque depende do LADO do lancamento e do NOME da
# conta, que o regex sozinho nao ve.
_VALOR_REF_A = re.compile(r"^\s*Valor\s+ref\.\s*a\s+(?P<x>.+)$", re.IGNORECASE)
# forma juridica e preposicao nao identificam ninguem: "DO", "LTDA" e "CIA"
# estao no nome de meio mundo
_NAO_E_NOME = frozenset("LTDA SA DE DA DO DOS DAS E EM COM IND CIA COMPANHIA "
                        "EIRELI EPP ME MEI".split())


def _palavras_de_nome(texto: str) -> list[str]:
    """Palavras de 3+ letras, sem acento, maiusculas, fora forma juridica e
    preposicao. So' letras: "LTDA73052" -> "LTDA"; "TRANSPORTE-X" -> 2."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode(
        "ascii", "ignore").decode().upper()
    return [p for p in re.findall(r"[A-Z]+", sem_acento)
            if len(p) >= 3 and p not in _NAO_E_NOME]


def cita_o_nome(texto: str, nome_conta: str) -> bool:
    """O texto tem uma palavra do nome da conta? Uma COMECA com a outra: o
    historico do extrato trunca o nome ("<FORNECEDOR> DO", "<FORN> CIMEN")."""
    alvo = _palavras_de_nome(nome_conta)
    return any(a.startswith(p) or p.startswith(a)
               for p in _palavras_de_nome(texto) for a in alvo)


class ClassificadorHistorico:
    """Classificador UNICO da firma: biblioteca de padroes ordenada.

    `nome_conta`: o nome da conta do fornecedor, pra trava de nome do
    "Valor ref. a <X>" sem CNPJ. Sem ele (scripts), essa trava fica desligada -- o
    comportamento de antes."""

    def __init__(self, nome_conta: str | None = None) -> None:
        self.nome_conta = nome_conta

    def classificar(self, lanc) -> Classificacao:
        h = lanc.historico or ""
        for padrao in PADROES:
            m = padrao.regex.search(h)
            if m:
                nf, citadas, parcela, parcela_de = _extrair(padrao, m, h)
                return Classificacao(padrao.tipo, nf_numero=nf,
                                     nfs_citadas=citadas, parcela=parcela,
                                     parcela_de=parcela_de,
                                     estorna=padrao.estorna,
                                     valor_parcela=_valor_declarado(h))
        if self._valor_ref_da_conta(lanc, h):
            return Classificacao(Tipo.PAGAMENTO)
        return Classificacao(Tipo.OUTRO)

    def _valor_ref_da_conta(self, lanc, h: str) -> bool:
        """DEBITO "Valor ref. a <X>" em que X cita o nome da conta ->
        pagamento sem numero (a Fase 2 so' casa o inequivoco). So' debito: um
        credito viraria "pagamento lancado a credito", e o historico nao diz
        que e' pagamento. A trava barra "Valor ref. a <outra empresa ou
        pessoa>" -- sem ela, qualquer debito iria pra Fase 2 (medido: ate 7,5% de
        coincidencia como "1 de N parcelas")."""
        if not self.nome_conta or lanc.debito <= 0:
            return False
        m = _VALOR_REF_A.search(h)
        return m is not None and cita_o_nome(m.group("x"), self.nome_conta)

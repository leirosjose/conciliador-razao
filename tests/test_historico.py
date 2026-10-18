"""Classificador UNICO da firma: o historico e escrito pela equipe
do escritorio no Dominio — vocabulario finito DA FIRMA, nao de cada cliente.
Biblioteca declarativa ordenada (mais especifico primeiro), IGNORECASE.

Os historicos de exemplo seguem a estrutura dos historicos do Dominio (nomes de fornecedor FICTICIOS;
o que o teste valida e o PADRAO, nao o nome) + o formato "NF-<num>".
"""
import time
from decimal import Decimal

import pytest

from core.classifica import Tipo
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

CLASSIFICADOR = ClassificadorHistorico()


def _clf(hist):
    return CLASSIFICADOR.classificar(lanc(hist, numero="x"))


# --- biblioteca de padroes: um exemplo REAL por padrao -----------------------

@pytest.mark.parametrize("historico,tipo,nf", [
    # FERRAMENTAS FICTICIAS (golden) — compatibilidade total
    ("- PAGTO REF. NF.:  618204.1 - PARC.:FERRAMENTAS FICTICIAS COMERCIO S.A.",
     Tipo.PAGAMENTO, "618204"),
    ("Compras conf. NF Vr. compras conf. 274591 FERRAMENTAS FICTICIAS COMERCIO SA ",
     Tipo.COMPRA, "274591"),
    # exemplo A (nomes ficticios)
    ("Valor ref. a METALFICTICIA ''MF'' NF 860003", Tipo.PAGAMENTO, "860003"),
    ("Pago conf. METALFICTICIA MF NFS: 3209 MANUTENCAO DE EQUIPAMENTO",
     Tipo.PAGAMENTO, "3209"),
    ("Valor ref. a Pgto a METALFICTICIA ''MF'' | 7ª PARCELA - NF 860009",
     Tipo.PAGAMENTO, "860009"),
    ("Valor ref. a BAIXA DE ADIANTAMENTO A FORN -  FORNECEDOR FICTICIO A ",
     Tipo.BAIXA_ADIANTAMENTO, None),
    ("Vr. compras conf. 3209 FORNECEDOR FICTICIO A E CIA LTDA ", Tipo.COMPRA, "3209"),
    # exemplo B (nomes ficticios)
    ("Pago conf. NF 860019 VEICULOS FICTICIA LTDA MANUTENCAO DE EQUIPAMENTO",
     Tipo.PAGAMENTO, "860019"),
    # formato "NF-<num>" (vocabulario da firma)
    ("Valor ref. a FORNECEDOR QUALQUER NF-860026", Tipo.PAGAMENTO, "860026"),
])
def test_biblioteca_reconhece_vocabulario_da_firma(historico, tipo, nf):
    c = _clf(historico)
    assert c.tipo is tipo
    assert c.nf_numero == nf


def test_duas_nfs_citadas_preenche_lista_e_nf_numero_fica_none():
    """2+ NFs distintas: nf_numero None (ambiguo pra Fase 1), mas a LISTA vai
    inteira em nfs_citadas — e o insumo do um-pra-muitos."""
    c = _clf("Valor ref. a PGTO REF. AS NF 860005 E 860006")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero is None
    assert c.nfs_citadas == ("860005", "860006")


def test_uma_nf_citada_tambem_aparece_na_lista():
    c = _clf("Valor ref. a FORNECEDOR QUALQUER NF-860026")
    assert c.nf_numero == "860026"
    assert c.nfs_citadas == ("860026",)


def test_ferramentas_ficticias_extrai_parcela():
    c = _clf("- PAGTO REF. NF.:  618204.1 - PARC.:FERRAMENTAS FICTICIAS COMERCIO S.A.")
    assert c.parcela == 1


@pytest.mark.parametrize("historico", [
    "PAGTO REF. NF.: 1.234.2",     # milhar com ponto lido como NF 1, parcela 234
    "PAGTO REF. NF.: 12.3",        # NF de 1-2 digitos: abaixo do minimo da firma
])
def test_formato_ferramentas_ficticias_exige_nf_de_3_digitos(historico):
    """O padrao FERRAMENTAS FICTICIAS sem minimo lia "1.234.2" como NF "1";
    o minimo de 3 digitos ja vale pro marcador e pra compra. Sem casar
    o padrao, nenhum outro reconhece "PAGTO" -> OUTRO, sem NF."""
    c = _clf(historico)
    assert c.tipo is Tipo.OUTRO
    assert c.nf_numero is None
    assert c.nfs_citadas == ()


@pytest.mark.parametrize("historico,nf,parcela", [
    ("PAGTO REF. NF.: 618204.1", "618204", 1),     # golden
    ("PAGTO REF. NF.: 274591.4", "274591", 4),     # golden
    ("PAGTO REF. NF.: 1234.12", "1234", 12),
    ("PAGTO REF. NF.: 123.45", "123", 45),         # 3 digitos: o minimo
])
def test_formato_ferramentas_ficticias_com_nf_de_3_ou_mais_digitos_continua_com_parcela(historico, nf, parcela):
    c = _clf(historico)
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero == nf
    assert c.nfs_citadas == (nf,)
    assert c.parcela == parcela


def test_parcela_ordinal_extraida():
    c = _clf("Valor ref. a Pgto a METALFICTICIA ''MF'' | 7ª PARCELA - NF 860009")
    assert c.parcela == 7
    assert c.parcela_de is None            # ordinal nao declara o total M


def test_parcela_de_m_extrai_a_serie_completa():
    """O 'de M' e metadado DECLARADO no historico — insumo do desempate por
    serie."""
    c = _clf("Valor ref. a PGTO A FICTICIA | Valor de R$ 26.000,00 "
             "(Parcela 2 de 5). Referente a compra de MATERIAL")
    assert c.parcela == 2
    assert c.parcela_de == 5


# --- quitacao generica: "Valor ref. a <razao social> - CNPJ" ---

def test_quitacao_generica_por_razao_social_e_cnpj():
    """Debito em conta de fornecedor reduz obrigacao (partida dobrada) —
    pagamento, devolucao ou abatimento tem o MESMO efeito na composicao.
    Sem numero: a Fase 2 decide (so casa inequivoco; risco contido)."""
    c = _clf("Valor ref. a EMPRESA FICTICIA DE METAIS LTDA - 00000000000000")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero is None


def test_quitacao_generica_nao_engole_a_baixa():
    # o padrao e o ULTIMO da biblioteca: os especificos casam antes
    c = _clf("Valor ref. a BAIXA DE ADIANTAMENTO A FORN - 00000000000000")
    assert c.tipo is Tipo.BAIXA_ADIANTAMENTO


def test_sem_cnpj_de_14_digitos_continua_outro():
    """O que este teste guarda e' a QUITACAO GENERICA: sem o CNPJ de 14 digitos
    o ultimo padrao nao casa. O exemplo original era a transferencia de saldos,
    que hoje tem padrao PROPRIO (decisao de produto) — trocado por um
    historico que continua sem regra nenhuma, senao o teste passaria a provar
    outra coisa."""
    c = _clf("Valor ref. a FORNECEDOR SEM CNPJ NO HISTORICO")
    assert c.tipo is Tipo.OUTRO


# --- armadilhas reais --------------------------------------------------------

def test_extrai_nf_do_marcador_nao_do_codigo():
    c = _clf("Valor ref. a PGTO A METALFICTICIA ''MF'' | Valor de R$ 8.334,00 "
             "(Parcela 1 de 3). Referente a NF DE ENTRADA de codigo 6140 - "
             "Nº 860007, emitida em 14/01/2025 no valor de R$ 25.000,00")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero == "860007"      # o marcador e' o "Nº"; "codigo" nao e' marcador
    assert c.parcela == 1


def test_plano_de_conta_e_data_nao_viram_nf():
    c = _clf("Valor ref. a PGTO A METALFICTICIA ''MF'' | Valor de R$ 26.000,00 "
             "(Parcela 3 de 5). Despesa referente ao plano de conta 20.03.05 - "
             "MANUTENCAO DE EQUIPAMENTO, efetuado em 26/09/2024 no valor de R$ 26.000,00")
    assert c.tipo is Tipo.PAGAMENTO    # verbo de pagamento, sem NF citada
    assert c.nf_numero is None
    assert c.parcela == 3


def test_multiplas_nfs_citadas_fica_sem_numero():
    """2+ NFs distintas numa linha -> ambiguo pra Fase 1; nf_numero=None manda
    pra cascata por valor (normalmente balde)."""
    c = _clf("Valor ref. a VEICULOS FICTICIA LTDA NF 860020 E NFS: 860008")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero is None


@pytest.mark.parametrize("historico", [
    "PGTO NF 1111, 2222",
    "PGTO NF 1111/2222",
    "PGTO NF 1111 E 2222",           # controle: a forma que ja funcionava
])
def test_lista_de_nfs_no_pagamento_vira_2_nfs_citadas(historico):
    """Virgula e barra continuam a lista como o " E "; antes
    liam so a 1a NF e o pagamento inteiro caia nela (saldo negativo)."""
    c = _clf(historico)
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero is None
    assert c.nfs_citadas == ("1111", "2222")


def test_lista_de_nfs_aceita_parcela_na_ultima():
    c = _clf("PGTO NF 3001, 3002.2")
    assert c.nfs_citadas == ("3001", "3002")


@pytest.mark.parametrize("historico,nf", [
    ("PGTO NF 1234/1", "1234"),              # NF/parcela: 1-2 digitos nao continuam
    ("PGTO NF 1234/12", "1234"),
    ("PGTO NF 1111, 150,00", "1111"),        # valor depois da virgula
    ("PGTO NF 1111, 125.000,00", "1111"),    # milhar depois da virgula
    ("PGTO NF 1111, 2222,5", "1111"),        # \d do lookahead: sem ele le "222" por retrocesso
])
def test_lista_de_nfs_nao_confunde_parcela_nem_valor_com_nf(historico, nf):
    c = _clf(historico)
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero == nf
    assert c.nfs_citadas == (nf,)


@pytest.mark.parametrize("historico,tipo", [
    ("PGTO NF 001.234", Tipo.PAGAMENTO),
    ("PGTO NF 123.456", Tipo.PAGAMENTO),
    ("PGTO NF 12345.678", Tipo.PAGAMENTO),   # sem o \d no lookahead volta a ler "123"
    ("IRRF S/ NF 001.234", Tipo.RETENCAO),   # o marcador e' o mesmo da retencao
    ("IRRF S/ NF 12345.678", Tipo.RETENCAO),
])
def test_nf_seguida_de_milhar_com_ponto_nao_vira_nf_curta(historico, tipo):
    """Antes, "NF 001.234" lia a NF "001" (e "123.456" lia "123"); o
    ponto-milhar nao e' parcela de 3 digitos. Sem numero, o historico segue o
    caminho do pagamento/retencao sem NF (Fase 2 por valor)."""
    c = _clf(historico)
    assert c.tipo is tipo
    assert c.nf_numero is None
    assert c.nfs_citadas == ()


@pytest.mark.parametrize("historico", [
    "PGTO NF 001.234 NF 5678",
    "PGTO NF 12345.678 NF 5678",
])
def test_milhar_pontuado_nao_vira_nf_nem_quando_outra_nf_vem_depois(historico):
    """O marcador de LISTA (usado na extracao do pagamento) tem a mesma trava:
    so' a NF 5678 e' citada; "001" / "123" / "12345" nao entram na lista."""
    c = _clf(historico)
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero == "5678"
    assert c.nfs_citadas == ("5678",)


@pytest.mark.parametrize("historico,nf,parcela", [
    ("PGTO NF 1234.1", "1234", None),
    ("PAGTO REF. NF.: 618204.1 - PARC.:", "618204", 1),   # formato golden
    ("PGTO NF 1234/1", "1234", None),
    ("PGTO NF 1234, 150,00", "1234", None),
    ("PGTO NF 1234.12", "1234", None),       # parcela de 2 digitos com ponto
    ("PGTO NF 1234,5", "1234", None),
])
def test_nf_com_parcela_curta_ou_valor_continua_lida_como_antes(historico, nf, parcela):
    c = _clf(historico)
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero == nf
    assert c.nfs_citadas == (nf,)
    assert c.parcela == parcela


@pytest.mark.parametrize("historico", ["PGTO NF 1234 E 5678", "PGTO NF 1111, 2222"])
def test_lista_de_nfs_continua_lida_como_antes(historico):
    c = _clf(historico)
    assert c.nf_numero is None
    assert len(c.nfs_citadas) == 2


def test_lista_com_virgula_so_vale_no_pagamento_retencao_le_so_a_primeira():
    """A lista por virgula vale SO no pagamento: retencao citando 2+ NFs por virgula segue na 1a
    NF citada (o destino da multi-NF em retencao e pergunta em aberto ao contador)."""
    c = _clf("IRRF S/ NF 1001, 1002")
    assert c.tipo is Tipo.RETENCAO
    assert c.nf_numero == "1001"
    assert c.nfs_citadas == ("1001",)


# --- marcador de NF sem retrocesso quadratico -----------------
# `\s*[-.:]?\s*` tinha dois `\s*` ambiguos em volta do separador opcional: "NF"
# + N espacos sem numero custava O(N^2) (32.000 espacos = 3,9 s numa celula, ate
# 15 s depois de " E NF"). Folga de 1 s: antes da correcao eram 4 a 15 s.

@pytest.mark.parametrize("historico,tipo,nf,citadas", [
    ("PGTO NF", Tipo.PAGAMENTO, None, ()),
    ("IRRF S/ NF", Tipo.RETENCAO, None, ()),
    ("PGTO NF 1234 E NF", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("IRRF NF 1234 E NF", Tipo.RETENCAO, "1234", ("1234",)),
    ("PGTO NF 1111, NF", Tipo.PAGAMENTO, "1111", ("1111",)),
    ("PGTO NF 1111/NF", Tipo.PAGAMENTO, "1111", ("1111",)),
])
def test_marcador_de_nf_com_muito_espaco_nao_trava(historico, tipo, nf, citadas):
    inicio = time.perf_counter()
    c = _clf(historico + " " * 32000)
    assert time.perf_counter() - inicio < 1.0
    assert c.tipo is tipo
    assert c.nf_numero == nf
    assert c.nfs_citadas == citadas


@pytest.mark.parametrize("historico,tipo,nf,citadas", [
    ("NF 1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NF.1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NF. 1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NF-1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NF - 1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NF: 1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NF.: 1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("NFS: 3209", Tipo.PAGAMENTO, "3209", ("3209",)),
    ("N\u00ba 860007", Tipo.PAGAMENTO, "860007", ("860007",)),
    ("N\u00ba. 860007", Tipo.PAGAMENTO, "860007", ("860007",)),
    ("NF  .  1234", Tipo.PAGAMENTO, "1234", ("1234",)),
    ("AS NF 860005 E 860006", Tipo.PAGAMENTO, None, ("860005", "860006")),
    ("NF 1234 E NF 5678", Tipo.PAGAMENTO, None, ("1234", "5678")),
    ("NF 1234 E NF.: 5678", Tipo.PAGAMENTO, None, ("1234", "5678")),
    ("conf. 197", Tipo.OUTRO, None, ()),
    ("NF12", Tipo.OUTRO, None, ()),
    ("NF :- 1234", Tipo.OUTRO, None, ()),
])
def test_marcador_de_nf_le_as_mesmas_formas_de_antes(historico, tipo, nf, citadas):
    """CONTROLE do R13: o marcador novo tem de ler exatamente o que o antigo lia."""
    c = _clf(historico)
    assert (c.tipo, c.nf_numero, c.nfs_citadas) == (tipo, nf, citadas)


def test_estorno_nunca_casa_como_baixa_mesmo_maiusculo():
    """Trava: biblioteca inteira IGNORECASE — 'ESTORNO DE
    BAIXA' maiusculo nao pode escapar e casar como baixa.

    A intencao da armadilha agora esta EXPLICITA. Antes ela morava no
    `is Tipo.OUTRO`, que dizia "nao reconheci"; hoje o motor reconhece o
    estorno (e o que ele reverte) e o que a trava garante e outra coisa —
    reconhecer NUNCA pode virar quitacao."""
    c = _clf("VALOR REF. ESTORNO DE  BAIXA DE ADIANTAMENTO INDEVIDA - VEICULOS FICTICIA")
    assert c.tipo is Tipo.ESTORNO
    assert c.tipo is not Tipo.BAIXA_ADIANTAMENTO
    assert c.estorna is Tipo.BAIXA_ADIANTAMENTO


def test_retencao_extrai_nf_pelo_marcador():
    """Retencao MANTEM extracao de NF (mesma logica de marcador
    do padrao de pagamento) — senao a Fase 1 perde retencoes vinculadas."""
    c = _clf("IRRF RETIDO S/ NF 12345")
    assert c.tipo is Tipo.RETENCAO
    assert c.nf_numero == "12345"


# --- vocabulario de retencao -------------------------------------------
# ERPs geram retencao na ordem INSS/IRRF/ISS/COFINS/PIS/CSLL; a biblioteca cobria
# so IRRF/CSLL/INSS. Padrao novo = 1 linha declarativa + armadilha.

@pytest.mark.parametrize("historico,nf", [
    ("ISS RETIDO S/ NF 12345", "12345"),
    ("ISSQN RETIDO S/ NF 12345", "12345"),      # \bISS\b nao alcanca ISSQN
    ("PIS RETIDO S/ NF 12345", "12345"),
    ("COFINS RETIDO S/ NF 12345", "12345"),
    ("Valor ref. a RETENCAO DE ISS - FORNECEDOR FICTICIO", None),
])
def test_retencao_cobre_o_vocabulario_tributario_completo(historico, nf):
    c = _clf(historico)
    assert c.tipo is Tipo.RETENCAO
    assert c.nf_numero == nf


@pytest.mark.parametrize("historico", [
    "Valor ref. a COMISSAO SOBRE VENDAS - FORNECEDOR FICTICIO",       # ISS em comISSao
    "Valor ref. a NOTA DE EMISSAO PROPRIA - FORNECEDOR FICTICIO",     # ISS em emISSao
    "Recebimento conf. RECEBIMENTO PIX 00000000000000 FORN FICTICIO",  # PIX nao e PIS
    "Valor ref. a PISO INDUSTRIAL - FORNECEDOR FICTICIO",             # PIS em PISo
])
def test_armadilha_token_tributario_dentro_de_palavra_nao_vira_retencao(historico):
    assert _clf(historico).tipo is not Tipo.RETENCAO


def test_estorno_de_retencao_nunca_vira_retencao():
    """'estorno' e o PRIMEIRO padrao da biblioteca: estorno de retencao nunca
    entra como quitacao (mesma trava do estorno de baixa).

    Vira ESTORNO GENERICO — a firma nao tem padrao declarando estorno de
    retencao, entao `estorna` fica None e ele nunca pareia. Sem declaracao nao
    ha prova, e quem decide e o conferente."""
    c = _clf("Valor ref. estorno de ISS retido indevidamente - FORN FICTICIO")
    assert c.tipo is Tipo.ESTORNO
    assert c.tipo is not Tipo.RETENCAO
    assert c.estorna is None


def test_o_recebimento_de_campo_e_reconhecido_e_o_destino_nao_muda():
    """Medido: os 3 tipos de 'Nao reconhecido' eram estorno, transferencia
    entre contas e recebimento. Sairam, nessa ordem, o ESTORNO, a
    TRANSFERENCIA DE SALDOS e o RECEBIMENTO.

    No recebimento: antes, um item do balde (lote 341018, C 598,40), motivo
    NAO_CLASSIFICADO. Depois: o mesmo item, no MESMO balde, motivo
    RECEBIMENTO -- a decisao de produto manda ficar no balde ("tem
    subjetividade"); so' o vocabulario mudou. A lista de nao reconhecidos
    ficou vazia."""
    assert _clf("Recebimento conf.   RECEBIMENTO PIX 00000000000000 "
                "FORN FICTICIO").tipo is Tipo.RECEBIMENTO


def test_pagamento_sem_nf_por_verbo():
    c = _clf("Valor ref. a Pagamento efetuado pelo Fundo Fixo de Fulano Ficticio")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero is None


def test_nao_reconhecido_vai_para_outro():
    """Fallback da biblioteca: historico sem NENHUM padrao -> OUTRO (e balde,
    nunca sumir em silencio). O exemplo era a transferencia de saldos, hoje
    reconhecida; trocado por um historico realmente sem padrao."""
    c = _clf("LANCAMENTO DE AJUSTE SEM DESCRICAO CONHECIDA")
    assert c.tipo is Tipo.OUTRO
    assert c.nf_numero is None


# --- estorno declarativo ----------------------------------------
# O estorno DECLARA o que reverte, e e essa declaracao que o core usa como prova
# pra parear. Padrao novo = 1 linha na biblioteca; o especifico vem antes do
# generico, senao "\bestorno\b" engoliria a declaracao.

def test_estorno_de_baixa_declara_o_que_reverte():
    c = _clf("Valor ref. estorno de  BAIXA DE ADIANTAMENTO indevida - FORN FICTICIO")
    assert c.tipo is Tipo.ESTORNO
    assert c.estorna is Tipo.BAIXA_ADIANTAMENTO


def test_estorno_sem_declaracao_conhecida_fica_generico():
    """Reconhecido como estorno, mas sem dizer o que reverte: nao pareia."""
    c = _clf("Valor ref. estorno de lancamento indevido - FORN FICTICIO")
    assert c.tipo is Tipo.ESTORNO
    assert c.estorna is None


def test_baixa_de_verdade_continua_baixa():
    """A trava pelo outro lado: o padrao de estorno nao pode roubar a baixa
    legitima, que e a que o casamento precisa pra consumir o saldo anterior."""
    c = _clf("Valor ref. a BAIXA DE ADIANTAMENTO A FORN - FORN FICTICIO")
    assert c.tipo is Tipo.BAIXA_ADIANTAMENTO
    assert c.estorna is None


def test_lancamento_comum_nao_ganha_estorna():
    assert _clf("Valor ref. a Pgto a FORN FICTICIO NF 12345").estorna is None


# --- valor DECLARADO da parcela ---------------------------------
# O unico ponto do sistema onde dinheiro nasce de TEXTO LIVRE. Ancoragem
# ESTRUTURAL: captura-se so' o valor sintaticamente ligado ao "(Parcela k de
# M)". Medido em 18 historicos que declaram parcela: 11 tem uma SEGUNDA
# ocorrencia de R$ com valor diferente (o total do documento), e divergir dela
# e o NORMAL — a parcela 3 de 3 vale 300,00 numa NF de 300,00.

_DECLARA = ("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ {v} "
            "(Parcela {k} de {m}). Despesa referente ao plano de conta 20.03.05")


def test_captura_o_valor_ancorado_no_marcador_de_parcela():
    c = _clf(_DECLARA.format(v="867,13", k=1, m=2))
    assert c.valor_parcela == Decimal("867.13")
    assert (c.parcela, c.parcela_de) == (1, 2)


def test_captura_valor_com_separador_de_milhar():
    c = _clf(_DECLARA.format(v="5.820,86", k=3, m=3))
    assert c.valor_parcela == Decimal("5820.86")


def test_valor_e_decimal_nunca_float():
    """Decimal, nunca float — e aqui a regra pesa mais que em qualquer lugar:
    este e o unico ponto onde dinheiro nasce de texto."""
    v = _clf(_DECLARA.format(v="1.234.567,89", k=1, m=2)).valor_parcela
    assert isinstance(v, Decimal)
    assert v == Decimal("1234567.89")


def test_o_total_do_documento_no_fim_NAO_e_capturado():
    """A armadilha central. O template tem duas casas: a parcela,
    colada no marcador, e o total do documento, no fim. Capturar a ultima daria
    1866,58 no lugar de 634,64 — e a regra apontaria pra NF errada."""
    c = _clf("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ 634,64 "
             "(Parcela 3 de 3). Referente a NF DE ENTRADA de codigo 5841 - "
             "N 860024, emitida em 31/10/2024 no valor de R$ 1866,58")
    assert c.valor_parcela == Decimal("634.64")


def test_valor_sem_marcador_de_parcela_nao_e_capturado():
    """Sem ancora nao ha o que capturar: um R$ solto no historico pode ser
    qualquer coisa."""
    assert _clf("Valor ref. a Pgto de R$ 867,13 a FORN FICTICIO").valor_parcela is None


def test_ordinal_sem_valor_declarado_fica_none():
    """"7 PARCELA - NF 860009" declara a parcela mas nao o valor dela."""
    c = _clf("Valor ref. a Pgto a FORN FICTICIO | 7ª PARCELA - NF 860009")
    assert c.parcela == 7
    assert c.valor_parcela is None


def test_duas_capturas_ancoradas_divergentes_viram_none():
    """A regra de divergencia, aplicada onde ela vale: se o proprio
    padrao ANCORADO casa 2+ vezes com valores diferentes, o texto esta ambiguo.
    Nao captura — e sem valor nao ha sugestao."""
    c = _clf("PGTO A FORN FICTICIO | Valor de R$ 100,00 (Parcela 1 de 2) e "
             "Valor de R$ 200,00 (Parcela 1 de 2)")
    assert c.tipo is Tipo.PAGAMENTO          # o historico E reconhecido...
    assert c.valor_parcela is None           # ... e mesmo assim nao captura


def test_duas_capturas_ancoradas_IGUAIS_capturam():
    """Repeticao do MESMO valor nao e ambiguidade."""
    c = _clf("PGTO A FORN FICTICIO | Valor de R$ 100,00 (Parcela 1 de 2) e "
             "Valor de R$ 100,00 (Parcela 1 de 2)")
    assert c.valor_parcela == Decimal("100.00")


def test_valor_sem_centavos_nao_casa():
    """Nao capturar e melhor que capturar errado: exigir ,NN evita ler
    "R$ 636" como 636,00 quando o texto pode estar truncado."""
    c = _clf("PGTO A FORN FICTICIO | Valor de R$ 636 (Parcela 1 de 2)")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.valor_parcela is None


def test_milhar_malformado_nao_casa():
    c = _clf("PGTO A FORN FICTICIO | Valor de R$ 1.2345,00 (Parcela 1 de 2)")
    assert c.tipo is Tipo.PAGAMENTO
    assert c.valor_parcela is None


def test_historico_irreconhecivel_nao_extrai_nada():
    """Comportamento de sempre, agora explicito: o fallback Tipo.OUTRO devolve
    uma Classificacao NUA — sem NF, sem parcela, sem valor. E o que faz um
    historico sem verbo nenhum nao ter valor_parcela, mesmo declarando um. Se
    este teste cair, o fallback passou a extrair e as armadilhas acima deixaram
    de provar o que dizem provar."""
    c = _clf("Valor de R$ 100,00 (Parcela 1 de 2) sem verbo reconhecido")
    assert c.tipo is Tipo.OUTRO
    assert (c.valor_parcela, c.parcela, c.parcela_de) == (None, None, None)


def test_lancamento_sem_parcela_nenhuma_nao_tem_valor():
    assert _clf("Valor ref. a FORN FICTICIO LTDA NF 860021").valor_parcela is None


# --- TRANSFERENCIA DE SALDOS (decisao de produto) ------
# "Pode considerar como baixa normal. Isso acontece quando o fornecedor tem
# matriz e filial e no momento do cadastro sao criadas contas contabeis
# diferentes do mesmo fornecedor sendo matriz e filial."

def test_transferencia_de_saldos_tem_tipo_proprio():
    """O historico de um caso (lote 322087, credito de 2.900,00)."""
    c = _clf("Valor ref. a TRANSFERENCIA DE SALDOS DE CONTAS DE UM MESMO FORNECEDOR")
    assert c.tipo is Tipo.TRANSFERENCIA_SALDO


def test_transferencia_de_saldo_no_singular_tambem_casa():
    assert _clf("TRANSFERENCIA DE SALDO ENTRE CONTAS").tipo is Tipo.TRANSFERENCIA_SALDO


def test_transferencia_de_saldos_em_minusculas_casa():
    """A biblioteca inteira e IGNORECASE — a armadilha e nao esquecer aqui."""
    assert _clf("transferencia de saldos").tipo is Tipo.TRANSFERENCIA_SALDO


def test_transferencia_com_acento_casa():
    assert _clf("TRANSFERÊNCIA DE SALDOS").tipo is Tipo.TRANSFERENCIA_SALDO


def test_transferencia_BANCARIA_nao_e_transferencia_de_saldo():
    """Armadilha central: "transferencia" sozinha nao basta. O caso descrito
    e' saldo migrando entre contas do MESMO fornecedor."""
    assert _clf("TRANSFERENCIA BANCARIA PARA FORNECEDOR").tipo is not Tipo.TRANSFERENCIA_SALDO


def test_estorno_de_transferencia_de_saldos_e_ESTORNO():
    """Mesma precedencia que a baixa de adiantamento ja tem: o \\bestorno\\b
    vem antes, senao o par perderia sua prova."""
    c = _clf("ESTORNO DE TRANSFERENCIA DE SALDOS DE CONTAS")
    assert c.tipo is Tipo.ESTORNO


def test_transferencia_que_cita_NF_carrega_o_numero():
    """extrai_nf=True: citando a NF, a Fase 1 resolve deterministicamente."""
    c = _clf("TRANSFERENCIA DE SALDOS ref. NF 860026")
    assert c.tipo is Tipo.TRANSFERENCIA_SALDO
    assert c.nf_numero == "860026"


def test_transferencia_vem_antes_do_verbo_de_pagamento():
    """"PGTO ... TRANSFERENCIA DE SALDOS" e transferencia, nao pagamento
    generico — o padrao especifico tem que ganhar do verbo."""
    c = _clf("PGTO TRANSFERENCIA DE SALDOS DE CONTAS DE UM MESMO FORNECEDOR")
    assert c.tipo is Tipo.TRANSFERENCIA_SALDO


# --- "PAYMENT" e' verbo de pagamento (template de um caso, anonimizado) ------

# o template, com a razao social e o CNPJ trocados por fachada (CNPJ zerado,
# o unico permitido)
PAYMENT_DE_CAMPO = "Pago FORNECEDOR FICTICIO DE COMBUSTIVEL  PAYMENT 00000000000000"


def test_payment_e_pagamento_sem_nf_e_o_cnpj_nao_vira_nf():
    """Armadilha 1: o CNPJ de 14 digitos colado ao PAYMENT nao tem marcador de
    NF -- fica de fora, e a Fase 2 decide por valor (so' o inequivoco casa)."""
    c = _clf(PAYMENT_DE_CAMPO)
    assert c.tipo is Tipo.PAGAMENTO
    assert c.nf_numero is None
    assert c.nfs_citadas == ()


def test_payment_e_o_irmao_que_ja_casava_tem_o_mesmo_tipo():
    """A diferenca entre os 13 que iam pro balde e os que casavam era so' a
    palavra do meio do texto."""
    irmao = ("Pago FORNECEDOR FICTICIO DE COMBUSTIVEL  Pagamento de contas "
             "para 00000000000000")
    assert _clf(irmao).tipo is _clf(PAYMENT_DE_CAMPO).tipo is Tipo.PAGAMENTO


@pytest.mark.parametrize("historico,tipo,nf", [
    # armadilha 2: estorno vem ANTES na biblioteca
    ("ESTORNO PAYMENT 00000000000000", Tipo.ESTORNO, None),
    # armadilha 3: NF citada e' extraida pelo marcador, que vem antes
    ("PAYMENT REF NF 4321 FORNECEDOR FICTICIO", Tipo.PAGAMENTO, "4321"),
    # armadilha 4: palavra DENTRO de palavra nao e' o verbo
    ("REPAYMENT FORNECEDOR FICTICIO", Tipo.OUTRO, None),
    # armadilha 5: caixa nao importa (biblioteca inteira e' IGNORECASE)
    ("Pago fornecedor ficticio payment 00000000000000", Tipo.PAGAMENTO, None),
])
def test_payment_armadilhas(historico, tipo, nf):
    c = _clf(historico)
    assert c.tipo is tipo
    assert c.nf_numero == nf


# --- COMPRA aceita NF de 3+ digitos -----------------------------------
# A "assimetria 4+/3+" entre compra e marcador nao tinha motivo. Apareceram
# NFs de 3 digitos de verdade (num caso 12, noutro 1): a compra caia no
# marcador -- que casava o "nf" de "conf." -- e virava pagamento em credito.

@pytest.mark.parametrize("historico,nf", [
    (" Vr. compras conf. 197 FORNECEDOR FICTICIO DO NORDESTE ", "197"),
    ("Compras conf. NF Vr. compras conf. 913 FORNECEDOR FICTICIO", "913"),
    ("Compras conf. NF Vr. compras conf. 860044 FORNECEDOR FICTICIO", "860044"),
])
def test_compra_com_nf_de_3_ou_mais_digitos(historico, nf):
    c = _clf(historico)
    assert (c.tipo, c.nf_numero) == (Tipo.COMPRA, nf)


def test_compra_com_numero_de_2_digitos_nao_vira_nf():
    c = _clf(" Vr. compras conf. 12 FORNECEDOR FICTICIO ")
    assert not (c.tipo is Tipo.COMPRA and c.nf_numero == "12")


# --- marcador de NF so' com "N" no inicio de palavra ------------------
# O marcador casava o "nf" de "co-nf." (309 historicos de um corpus). So'
# mordia quando o padrao de compra falhava antes, mas qualquer "conf. <n>"
# num historico que nao e' compra virava "NF <n>".

def test_conf_seguido_de_numero_nao_e_nf():
    c = _clf("Pago conf. 4321 FORNECEDOR FICTICIO")
    assert c.tipo is Tipo.PAGAMENTO
    assert (c.nf_numero, c.nfs_citadas) == (None, ())


@pytest.mark.parametrize("historico,nf", [
    ("Valor ref. a Pgto a FORN FICTICIO | NF 3998", "3998"),
    ("Pago  F00001 - FORN FICTICIO - NF-860043 - MATERIAL NF 860043", "860043"),
    ("PGTO A FORN FICTICIO NFS:860014", "860014"),
    ("Referente a NF DE ENTRADA de codigo 6140 - Nº 860007", "860007"),
    ("PGTO TITULO FORN FICTICIO (PARCELA 1 DE 1) NF 7443", "7443"),
])
def test_marcador_continua_casando_nf_no_inicio_de_palavra(historico, nf):
    assert _clf(historico).nf_numero == nf


def test_letra_colada_antes_do_marcador_nao_e_nf():
    assert _clf("Pago conf. FORN FICTICIOANF 4321").nf_numero is None


# --- verbos de banco como pagamento sem NF ----------------------------

@pytest.mark.parametrize("historico", [
    "Valor ref. a BOLETO PAGO FORNECEDOR FICTICIO",
    "Pago  FORNECEDOR FICTICIO DISTRIBUIDORA S.A",
    "Valor ref. a PAGAMENTOS FORNECEDOR FICTICIO",
    "Valor ref. a LIQUIDACAO BOLETO 00000000000000 FORNECEDOR FICTICIO",
    "Valor ref. a Sispag PIX QR-CODE",
])
def test_verbo_de_banco_e_pagamento_sem_nf(historico):
    c = _clf(historico)
    assert (c.tipo, c.nf_numero) == (Tipo.PAGAMENTO, None)


def test_pix_solto_nao_e_verbo_de_pagamento():
    assert _clf("Valor ref. a PIX ENVIADO PESSOA FICTICIA | MATERIAL").tipo \
        is Tipo.OUTRO


# --- "Valor ref. a <X>" sem CNPJ, com trava de nome -------------------
# Ultimo recurso, so' em DEBITO e so' quando X tem palavra do nome da conta.
# Muda a decisao anterior (CNPJ obrigatorio), com aprovacao.

NOME = "FORNECEDORA FICTICIA DO NORDESTE IND. E COM. L"


def _clf_conta(hist, nome=NOME, **valor):
    return ClassificadorHistorico(nome_conta=nome).classificar(
        lanc(hist, numero="x", **({"debito": "10.00"} | valor)))


@pytest.mark.parametrize("historico", [
    "Valor ref. a FORNECEDORA FICTICIA DO NORDESTE INDUSTRIA E COMERCIO LTDA",
    "Valor ref. a FORNECEDORA FICT",              # truncado no extrato
    "Valor ref. a NORDESTE",
])
def test_valor_ref_com_o_nome_da_conta_e_pagamento_sem_nf(historico):
    c = _clf_conta(historico)
    assert (c.tipo, c.nf_numero) == (Tipo.PAGAMENTO, None)


@pytest.mark.parametrize("historico", [
    "Valor ref. a OUTRA COMPANHIA FICTICIO SA",
    "Valor ref. a PIX ENVIADO PESSOA INVENTADA | MATERIAL",
    "Valor ref. a DO E COM FICTICIO LTDA",                 # so' palavra de forma juridica
])
def test_valor_ref_sem_o_nome_da_conta_continua_nao_reconhecido(historico):
    assert _clf_conta(historico).tipo is Tipo.OUTRO


def test_valor_ref_em_credito_continua_nao_reconhecido():
    c = _clf_conta("Valor ref. a FORNECEDORA FICTICIA", debito="0.00",
                   credito="10.00")
    assert c.tipo is Tipo.OUTRO


def test_sem_nome_da_conta_a_regra_do_nome_fica_desligada():
    assert _clf_conta("Valor ref. a FORNECEDORA FICTICIA", nome=None).tipo \
        is Tipo.OUTRO
    assert _clf("Valor ref. a FORNECEDORA FICTICIA").tipo is Tipo.OUTRO


def test_quitacao_generica_com_cnpj_continua_igual():
    c = _clf_conta("Valor ref. a OUTRA EMPRESA - 00000000000000")
    assert c.tipo is Tipo.PAGAMENTO


# --- compra "valor ref <NF> <FORNECEDOR>" -----------------------------

def test_compra_valor_ref_com_numero():
    c = CLASSIFICADOR.classificar(lanc("valor ref 9876543 FORNECEDOR FICTICIO SA ",
                               numero="x", credito="100.00"))
    assert (c.tipo, c.nf_numero) == (Tipo.COMPRA, "9876543")


def test_valor_ref_ponto_a_continua_outra_coisa():
    """Sem "a" e sem ponto: o "Valor ref. a" do extrato nao vira compra."""
    c = CLASSIFICADOR.classificar(lanc("Valor ref. a 9876543 FORNECEDOR", numero="x",
                               debito="100.00"))
    assert c.tipo is not Tipo.COMPRA

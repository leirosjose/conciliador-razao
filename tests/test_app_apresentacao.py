"""Camada de apresentacao (app/apresentacao.py): helpers PUROS que traduzem o
que o core devolve para linhas/labels de tela. Sem streamlit, sem money math --
testaveis sem subir a UI.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.modelo import (
    ALVO_ANTERIOR,
    Achado,
    ComposicaoItem,
    Conta,
    ItemRevisao,
    Lancamento,
    MotivoRevisao,
    Nivel,
    Origem,
    ResultadoConferencia,
)
import app.apresentacao as apresentacao
from app.apresentacao import (
    DIVERGENCIA,
    FECHA,
    INCOMPLETO,
    alertas,
    alertas_celulas,
    frase_achado,
    frases_alertas,
    balde_celulas,
    balde_detalhes,
    composicao_linhas,
    contexto_incompleto,
    data_br,
    divergencias,
    markdown_seguro,
    moeda_br,
    nome_de_linha,
    motivo_humano,
    notas_composicao,
    notas_composicao_texto,
    status_conta,
    triagem_linhas,
)
from tests.helpers import de_moeda_br, identidade_das_linhas


# --- moeda_br: Decimal -> padrao BR 1.234,56 ---

def test_moeda_br_milhar_e_centavo():
    assert moeda_br(Decimal("1234.56")) == "1.234,56"


def test_moeda_br_milhao():
    assert moeda_br(Decimal("1000000.00")) == "1.000.000,00"


def test_moeda_br_centena_sem_milhar():
    assert moeda_br(Decimal("214.63")) == "214,63"


def test_moeda_br_negativo():
    assert moeda_br(Decimal("-4260.09")) == "-4.260,09"


def test_moeda_br_zero():
    assert moeda_br(Decimal("0.00")) == "0,00"


# --- status_conta: reduz Nivel a severidade de tela ---

def _ach(nivel, codigo="x"):
    return Achado(nivel=nivel, codigo=codigo, mensagem="m")


def test_status_fecha_quando_tudo_ok():
    assert status_conta([_ach(Nivel.OK), _ach(Nivel.OK)])[0] == FECHA


def test_status_alerta_nao_derruba_o_verde():
    assert status_conta([_ach(Nivel.OK), _ach(Nivel.ALERTA)])[0] == FECHA


def test_status_incompleto_quando_ha_balde():
    assert status_conta([_ach(Nivel.OK), _ach(Nivel.INCOMPLETO)])[0] == INCOMPLETO


def test_status_divergencia_quando_ha_erro():
    assert status_conta([_ach(Nivel.OK), _ach(Nivel.ERRO)])[0] == DIVERGENCIA


def test_status_erro_vence_incompleto():
    assert status_conta([_ach(Nivel.INCOMPLETO), _ach(Nivel.ERRO)])[0] == DIVERGENCIA


# --- composicao_linhas: ordena mais antiga no topo, formata BR ---

def _item(nf, saldo, idade, compra="0.00", pago="0.00"):
    return ComposicaoItem(nf_numero=nf, origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal(compra), total_pago=Decimal(pago),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal(saldo),
                          idade_dias=idade)


def test_composicao_ordena_mais_antiga_no_topo():
    itens = [_item("274591", "1440.09", 118), _item("618204", "2820.00", 140)]
    linhas = composicao_linhas(itens)
    assert [l["NF"] for l in linhas] == ["618204", "274591"]   # idade 140 antes de 118


def test_composicao_formata_valores_br():
    linhas = composicao_linhas([_item("618204", "2820.00", 140,
                                       compra="4700.00", pago="1880.00")])
    assert linhas[0]["Valor compra"] == "4.700,00"
    assert linhas[0]["Total pago"] == "1.880,00"
    assert linhas[0]["EM ABERTO"] == "2.820,00"
    assert linhas[0]["Idade (dias)"] == "140"   # string de exibicao (coluna homogenea)


def test_composicao_saldo_anterior_sem_idade_vai_pro_fim():
    anterior = ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                              valor_compra=Decimal("0.00"), total_pago=Decimal("0.00"),
                              total_retido=Decimal("0.00"), saldo_aberto=Decimal("300.00"),
                              idade_dias=None)
    linhas = composicao_linhas([anterior, _item("618204", "2820.00", 140)])
    assert linhas[-1]["NF"] == "(saldo anterior)"     # rotulo de exibicao
    assert linhas[-1]["Idade (dias)"] == "—"


def test_composicao_mostra_baixa_identificada_em_coluna_propria():
    """Baixa de adiantamento NAO e mascarada de pagamento -- coluna
    propria, evidencia pra conferencia do contador validar a interpretacao."""
    item = ComposicaoItem(nf_numero="777", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1000.00"), total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("600.00"),
                          total_baixado=Decimal("400.00"), idade_dias=10)
    linhas = composicao_linhas([item])
    assert linhas[0]["Baixa adiant."] == "400,00"
    assert linhas[0]["Total pago"] == "0,00"
    assert linhas[0]["EM ABERTO"] == "600,00"


# --- datas na composicao: dd/mm/aaaa, "—" quando nao ha ---

def test_data_br_formata_e_trata_none():
    assert data_br(date(2026, 5, 31)) == "31/05/2026"
    assert data_br(None) == "—"


def test_composicao_mostra_data_nf_e_ultimo_pagamento():
    item = ComposicaoItem(nf_numero="810101", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("19343.67"), total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("19343.67"),
                          idade_dias=30, data_compra=date(2026, 2, 3),
                          data_ultima_quitacao=date(2026, 5, 20))
    linhas = composicao_linhas([item])
    assert linhas[0]["Data NF"] == "03/02/2026"
    assert linhas[0]["Última quitação"] == "20/05/2026"


def test_composicao_datas_ausentes_mostram_travessao():
    anterior = ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                              valor_compra=Decimal("0.00"), total_pago=Decimal("0.00"),
                              total_retido=Decimal("0.00"), saldo_aberto=Decimal("300.00"),
                              idade_dias=None)
    linhas = composicao_linhas([anterior])
    # a data da NF NAO SE APLICA a linha que nao e' nota -> vazia;
    # a ultima quitacao se aplica e esta ausente -> travessao
    assert linhas[0]["Data NF"] == ""
    assert linhas[0]["Última quitação"] == "—"


# --- balde_celulas: as colunas do balde (hoje so' o Excel as usa; na tela a
# caixinha por item substituiu a tabela), SEM aritmetica ---

def _pag(lote, valor):
    return Lancamento(date(2025, 1, 1), lote, "h", "x",
                      Decimal(valor), Decimal("0.00"), Decimal("0.00"))


def test_balde_mostra_lote_valor_e_motivo():
    item = ItemRevisao(lancamentos=[_pag("L9", "500.00")],
                       motivo=MotivoRevisao.SEM_VINCULO, candidatos=[], mensagem="m")
    linhas = balde_celulas([item])
    assert len(linhas) == 1
    assert linhas[0]["Lote"] == "L9"
    assert linhas[0]["Valor"] == Decimal("500.00")
    assert "Sem" in linhas[0]["Motivo"]


def test_balde_lancamento_zero_mostra_lado_zero():
    """Lancamento 0,00 nos dois lados: nem Debito nem Credito -- 'Zero'
    e nao 'Credito' por default de `debito != 0`."""
    zero = Lancamento(date(2025, 1, 1), "L0", "h", "x",
                      Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
    item = ItemRevisao(lancamentos=[zero], motivo=MotivoRevisao.SEM_VINCULO,
                       candidatos=[], mensagem="m")
    linhas = balde_celulas([item])
    assert linhas[0]["Lado"] == "Zero"
    assert linhas[0]["Valor"] == Decimal("0.00")


def test_balde_empate_lista_candidatos():
    item = ItemRevisao(lancamentos=[_pag("L9", "380.00")],
                       motivo=MotivoRevisao.EMPATE, candidatos=["1", "2"], mensagem="m")
    linhas = balde_celulas([item])
    assert linhas[0]["NFs candidatas"] == "1, 2"


def test_balde_mostra_lado_e_historico_como_evidencia():
    """Balde carrega os dois lados (debito E credito) e o historico
    integral -- e' a evidencia da revisao manual. Leitura de campo, sem soma."""
    debito = Lancamento(date(2025, 1, 1), "L1", "DEBITO MISTERIOSO", "x",
                        Decimal("100.00"), Decimal("0.00"), Decimal("0.00"))
    credito = Lancamento(date(2025, 1, 2), "L2", "RECEBIMENTO PIX 123", "x",
                         Decimal("0.00"), Decimal("897.60"), Decimal("0.00"))
    linhas = balde_celulas([
        ItemRevisao(lancamentos=[debito], motivo=MotivoRevisao.NAO_CLASSIFICADO,
                    candidatos=[], mensagem="m"),
        ItemRevisao(lancamentos=[credito], motivo=MotivoRevisao.NAO_CLASSIFICADO,
                    candidatos=[], mensagem="m"),
    ])
    # lado por EXTENSO — "D"/"C" seco e taquigrafia de contador e o
    # usuario-alvo e colaborador sem experiencia contabil
    assert linhas[0]["Lado"] == "Débito"
    assert linhas[0]["Valor"] == Decimal("100.00")
    assert linhas[0]["Histórico"] == "DEBITO MISTERIOSO"
    # rotulo CURTO na tabela — a frase completa vive na expansao
    assert linhas[0]["Motivo"] == "Não reconhecido"
    assert linhas[1]["Lado"] == "Crédito"
    assert linhas[1]["Valor"] == Decimal("897.60")


# --- rotulo honesto de baixa parcial ------------------------------------------

def test_notas_composicao_rotula_baixa_parcial_sem_falar_de_parcela():
    """Um caso: baixa cobriu metade exata da NF. Literatura contabil
    trata baixa como total OU parcial — o rotulo e 'baixa parcial de
    adiantamento', nunca 'parcela 1 de 2'."""
    item = ComposicaoItem(nf_numero="810101", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("19343.67"),
                          total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("9671.84"),
                          total_baixado=Decimal("9671.83"), idade_dias=10)
    notas = notas_composicao([item])
    # dados/estrutura, nao a frase inteira: a NF, os dois valores
    # formatados e a INTENCAO (baixa parcial, nunca 'parcela')
    assert len(notas) == 1
    assert "810101" in notas[0]
    assert "9.671,83" in notas[0] and "19.343,67" in notas[0]
    assert "baixa parcial" in notas[0]
    assert "parcela" not in notas[0].lower()


def test_notas_composicao_informa_quitada_com_arredondamento():
    """Residuo negativo dentro da tolerancia nao alerta juros — vira
    nota informativa (a NF esta quitada; o resto e arredondamento)."""
    item = ComposicaoItem(nf_numero="810102", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("31971.30"),
                          total_pago=Decimal("31971.32"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("-0.02"),
                          qtd_quitacoes=2, idade_dias=48)
    notas = notas_composicao([item])
    assert len(notas) == 1
    assert "810102" in notas[0]
    assert "0,02" in notas[0]
    assert "arredondamento" in notas[0]


def test_notas_composicao_marca_quitacao_casada_por_desempate():
    """Casamento decidido por REGRA (nao por unicidade) aparece na linha da
    NF — o conferente precisa saber onde a maquina escolheu. Plural correto e o
    criterio por extenso."""
    from core.modelo import CriterioDesempate

    uma = ComposicaoItem(nf_numero="810103", origem=Origem.COMPRA_PERIODO,
                         valor_compra=Decimal("13314.60"),
                         total_pago=Decimal("6657.30"),
                         total_retido=Decimal("0.00"),
                         saldo_aberto=Decimal("6657.30"), qtd_quitacoes=1,
                         idade_dias=20,
                         desempates=(CriterioDesempate.UNICA_EM_ABERTO,))
    nota = notas_composicao([uma])[0]
    assert "810103" in nota
    assert "1 quitação casada" in nota
    assert "única candidata ainda em aberto" in nota

    duas = ComposicaoItem(nf_numero="500", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("300.00"),
                          total_pago=Decimal("200.00"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("100.00"), qtd_quitacoes=2,
                          idade_dias=20,
                          desempates=(CriterioDesempate.DATA_MAIS_ANTIGA,) * 2)
    nota = notas_composicao([duas])[0]
    assert "2 quitações casadas" in nota
    assert "título mais antigo em aberto" in nota


def test_notas_composicao_separa_os_criterios_de_desempate():
    """Criterios distintos na mesma NF viram notas distintas — nao se soma peixe
    com laranja na contagem."""
    from core.modelo import CriterioDesempate

    item = ComposicaoItem(nf_numero="77", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("300.00"),
                          total_pago=Decimal("300.00"),
                          total_retido=Decimal("0.00"),
                          saldo_aberto=Decimal("0.00"), qtd_quitacoes=3,
                          idade_dias=20,
                          desempates=(CriterioDesempate.DATA_MAIS_ANTIGA,
                                      CriterioDesempate.UNICA_EM_ABERTO,
                                      CriterioDesempate.DATA_MAIS_ANTIGA))
    notas = notas_composicao([item])
    assert len(notas) == 2
    assert "2 quitações casadas" in notas[0] and "mais antigo" in notas[0]
    assert "1 quitação casada" in notas[1] and "única candidata" in notas[1]


def test_notas_composicao_ignora_item_sem_baixa_e_so_explica_o_anterior():
    sem_baixa = ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                               valor_compra=Decimal("100.00"),
                               total_pago=Decimal("0.00"),
                               total_retido=Decimal("0.00"),
                               saldo_aberto=Decimal("100.00"), idade_dias=5)
    anterior = ComposicaoItem(nf_numero=ALVO_ANTERIOR, origem=Origem.SALDO_ANTERIOR,
                              valor_compra=Decimal("300.00"),
                              total_pago=Decimal("0.00"),
                              total_retido=Decimal("0.00"),
                              saldo_aberto=Decimal("0.00"),
                              total_baixado=Decimal("300.00"), idade_dias=None)
    # a nota de BAIXA PARCIAL nao vale pra nenhum dos dois (ela e' de
    # COMPRA_PERIODO com saldo em aberto); a unica nota e' a que EXPLICA a
    # linha agregada
    notas = notas_composicao_texto([sem_baixa, anterior])
    assert len(notas) == 1
    assert notas[0].startswith("(saldo anterior): R$ 300,00 de saldo trazido")
    assert not any("baixa parcial" in n for n in notas)


# --- motivo em linguagem de gente: diagnostico + acao, por item ---

def test_motivo_humano_empate_lista_candidatas_e_pede_escolha():
    item = ItemRevisao(lancamentos=[_pag("L9", "1000.00")],
                       motivo=MotivoRevisao.EMPATE,
                       candidatos=["4444", "5555"], mensagem="m")
    texto = motivo_humano(item)
    assert "4444, 5555" in texto
    # regra de tela: o texto mostra FATO, nunca instrucao
    assert "o motor não escolhe entre elas" in texto


def test_motivo_humano_sem_vinculo_orienta_verificacao():
    item = ItemRevisao(lancamentos=[_pag("L9", "500.00")],
                       motivo=MotivoRevisao.SEM_VINCULO, candidatos=[], mensagem="m")
    texto = motivo_humano(item)
    assert "sem número de NF no histórico" in texto
    # regra de tela: o texto mostra FATO, nunca instrucao
    assert "valor compatível nesta conta" in texto


def test_motivo_humano_nao_classificado_pede_reporte():
    item = ItemRevisao(lancamentos=[_pag("L9", "400.00")],
                       motivo=MotivoRevisao.NAO_CLASSIFICADO, candidatos=[], mensagem="m")
    texto = motivo_humano(item)
    assert "não reconhecido pelos padrões" in texto
    # regra de tela: o texto mostra FATO, nunca instrucao
    assert "virar padrão novo" not in texto


def _cred(lote, valor):
    """Credito na conta do FORNECEDOR — o lado por onde volta dinheiro."""
    return Lancamento(date(2025, 1, 1), lote, "h", "x",
                      Decimal("0.00"), Decimal(valor), Decimal("0.00"))


def test_motivo_humano_credito_nao_classificado_levanta_devolucao():
    """Orientacao do contador: credito nao reconhecido na conta do
    fornecedor pode ser devolucao em dinheiro — mercadoria devolvida sem troca.
    LEITURA oferecida, nao afirmada: o contador disse que ha subjetividade e que o
    item continua no balde pra analise humana."""
    item = ItemRevisao(lancamentos=[_cred("L9", "897.60")],
                       motivo=MotivoRevisao.NAO_CLASSIFICADO, candidatos=[],
                       mensagem="m")
    texto = motivo_humano(item)
    assert "não reconhecido pelos padrões" in texto      # o motivo continua la
    assert "possível devolução em dinheiro" in texto
    assert "mercadoria devolvida sem troca" in texto


def test_motivo_humano_debito_nao_classificado_nao_fala_de_devolucao():
    """A leitura e' do LADO: debito e' saida de dinheiro, nunca devolucao."""
    item = ItemRevisao(lancamentos=[_pag("L9", "897.60")],
                       motivo=MotivoRevisao.NAO_CLASSIFICADO, candidatos=[],
                       mensagem="m")
    assert "devolucao" not in motivo_humano(item)


def test_motivo_humano_multi_nf_nao_confere_mostra_nfs_e_detalhe():
    item = ItemRevisao(
        lancamentos=[_pag("L1", "7000.00")],
        motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
        candidatos=["810104", "810105"],
        mensagem="soma dos saldos das NFs citadas = 8000.00, pagamento = 7000.00")
    texto = motivo_humano(item)
    assert "810104, 810105" in texto
    assert "soma dos saldos das NFs citadas = 8000.00" in texto
    # regra de tela: o texto mostra FATO, nunca instrucao
    assert "outra conta ou período" not in texto


def test_motivo_humano_sem_texto_cai_na_mensagem_do_motor(monkeypatch):
    """Motivo futuro sem texto mapeado NUNCA vira tela em branco: cai na
    mensagem tecnica do motor (fallback visivel)."""
    monkeypatch.delitem(apresentacao._MOTIVOS, MotivoRevisao.EMPATE)
    item = ItemRevisao(lancamentos=[_pag("L9", "1.00")],
                       motivo=MotivoRevisao.EMPATE, candidatos=[],
                       mensagem="mensagem tecnica do motor")
    assert motivo_humano(item) == "mensagem tecnica do motor"


def test_balde_detalhes_titulo_motivo_e_historico_integral():
    historico = "Valor ref. a PGTO GIGANTE COM HISTÓRICO ENORME QUE NÃO CABE NA COLUNA " * 3
    lanc = Lancamento(date(2025, 1, 1), "L7", historico.strip(), "x",
                      Decimal("3000.00"), Decimal("0.00"), Decimal("0.00"))
    item = ItemRevisao(lancamentos=[lanc],
                       motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                       candidatos=["1", "2"], mensagem="soma = X, pagamento = Y")
    detalhes = balde_detalhes([item])
    assert len(detalhes) == 1
    assert "3.000,00" in detalhes[0]["titulo"]
    assert detalhes[0]["motivo"] == motivo_humano(item)
    assert detalhes[0]["historico"] == historico.strip()     # INTEGRAL, sem cortar


def test_todo_item_do_balde_tem_expansao_na_ordem_da_tabela():
    """O conferente processa caixinha por caixinha — TODO item volta a
    ter expansao, na mesma ordem cronologica da tabela (linha N <-> caixa N),
    com a orientacao do motivo PARAMETRIZADA dentro."""
    sem_vinculo = ItemRevisao(lancamentos=[_pag_em("L1", "100.00", date(2025, 1, 5))],
                              motivo=MotivoRevisao.SEM_VINCULO, candidatos=[],
                              mensagem="m")
    multi = ItemRevisao(lancamentos=[_pag_em("L2", "200.00", date(2025, 2, 5))],
                        motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                        candidatos=["1", "2"], mensagem="soma = X, pagamento = Y")
    detalhes = balde_detalhes([multi, sem_vinculo])   # insercao fora de ordem
    assert len(detalhes) == 2                         # UM por item, sempre
    assert "05/01/2025" in detalhes[0]["titulo"]      # cronologica
    assert detalhes[0]["motivo"] == motivo_humano(sem_vinculo)
    assert "15/02/2025" not in detalhes[1]["titulo"]  # sanidade de data


def test_expansao_multinf_carrega_o_detalhe_da_soma_apurada():
    multi = ItemRevisao(lancamentos=[_pag_em("L2", "200.00", date(2025, 2, 5))],
                        motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                        candidatos=["1", "2"],
                        mensagem="soma dos saldos das NFs citadas = 300.00, pagamento = 200.00")
    det = balde_detalhes([multi])[0]
    assert "soma dos saldos das NFs citadas = 300.00" in det["motivo"]


def test_titulo_da_expansao_legivel_por_leigo():
    """Lote/data/lado/valor/motivo no titulo; historico integral dentro.
    O cifrao continua escapado para nao formar LaTeX."""
    # nome de fornecedor sintetico
    hist = ('Valor ref. a FORNECEDOR "XYZ" PAGAMENTO REFERENTE AS NF 810104 E '
            '810105 DESPESA DO PLANO DE CONTA')
    lanc = Lancamento(date(2024, 11, 14), "311814", hist, "8",
                      Decimal("101400.00"), Decimal("0.00"), Decimal("0.00"))
    det = balde_detalhes([ItemRevisao(
        lancamentos=[lanc], motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
        candidatos=["810104", "810105"], mensagem="soma = X, pagamento = Y")])[0]
    assert det["titulo"].startswith("Lote 311814 · 14/11/2024 · Débito R\\$ 101.400,00")
    assert "Soma das NFs não confere" in det["titulo"]
    assert "Valor ref. a FORNECEDOR" not in det["titulo"]
    assert det["historico"] == hist
    assert "…" not in det["titulo"]
    assert "311814" in det["titulo"]
    assert "· D ·" not in det["titulo"]                  # nada de D/C seco


# --- escape de Markdown em texto dinamico -------------------------------------

def test_markdown_seguro_escapa_cifrao_e_enfases():
    assert markdown_seguro("R$ 26.000,00 e R$ 130.000,00") == \
        "R\\$ 26.000,00 e R\\$ 130.000,00"
    assert markdown_seguro("*enfase* _italico_ `código` ~risco~") == \
        "\\*enfase\\* \\_italico\\_ \\`código\\` \\~risco\\~"
    # barra existente e escapada PRIMEIRO (senao escaparia os escapes)
    assert markdown_seguro("a\\FICTICIA") == "a\\\\FICTICIA"


def test_markdown_seguro_neutraliza_link_e_imagem():
    """[texto](url) e ![](url) sao os piores casos: link/imagem VIVOS no
    expander/st.markdown (imagem auto-carrega URL externa). Escapar [ ] mata os
    dois (ambos exigem [); ( ) NAO se escapa -- backslasharia parentese
    legitimo e '\\(' ainda vira delimitador de math."""
    # o endereco de dentro tambem deixa de virar link (caractere sem largura depois de "http:")
    assert markdown_seguro("[clique](http://evil.com)") == \
        "\\[clique\\](http:\u2060//evil.com)"
    assert markdown_seguro("![](http://evil.com/pixel.png)") == \
        "\\!\\[\\](http:\u2060//evil.com/pixel.png)"
    # parentese legitimo NAO leva backslash (texto financeiro e cheio deles)
    assert markdown_seguro("(9.671,82 de 19.343,67)") == "(9.671,82 de 19.343,67)"


def test_markdown_seguro_normaliza_quebras_de_linha():
    """Historico multilinha nao pode escapar do blockquote '> ' do st.markdown
    -- \\n / \\r viram espaco."""
    assert markdown_seguro("linha 1\nlinha 2\r\nlinha 3\rlinha 4") == \
        "linha 1 linha 2 linha 3 linha 4"


def test_titulo_conta_escapa_nome_e_arquivo():
    """O cabecalho da conta traz nome de fornecedor (celula) e nome de arquivo
    (upload) -- fonte externa, escapa no ponto de montagem."""
    from app.apresentacao import titulo_conta
    conta = Conta(codigo="8888", classificacao="", nome="FORN FICTICIO _X_ [Y] LTDA")
    t = titulo_conta(conta)
    assert "\\_X\\_" in t
    assert "\\[Y\\]" in t
    # em lote, o nome do arquivo tambem entra escapado
    t2 = titulo_conta(conta, arquivo="razao_*_[x].xls")
    assert "razao\\_\\*\\_\\[x\\].xls" in t2


def test_titulo_com_dois_cifroes_renderiza_literal():
    """Um caso: o empate de 78.000 tem 'Valor de R$
    78.000,00' DENTRO do historico — com o R$ do valor do item, formam par
    $...$ e o renderizador vira LaTeX. Escapados, os dois ficam literais."""
    hist = ("Valor ref. a PGTO A FORNECEDOR ''XYZ'' | Valor de R$ 78.000,00 "
            "(Parcela 3 de 5). Despesa referente ao plano de conta")
    lanc = Lancamento(date(2024, 12, 1), "L1", hist, "8",
                      Decimal("78000.00"), Decimal("0.00"), Decimal("0.00"))
    det = balde_detalhes([ItemRevisao(lancamentos=[lanc],
                                      motivo=MotivoRevisao.EMPATE,
                                      candidatos=["810104", "810105"],
                                      mensagem="m")])[0]
    assert det["titulo"].count("\\$") == 1       # historico integral fica dentro
    assert det["historico"] == hist
    assert "R$ " not in det["titulo"]            # nenhum cifrao cru sobrou


def test_historico_com_enfases_nao_vira_formatacao():
    lanc = Lancamento(date(2024, 12, 1), "L1", "PGTO *URGENTE* conta_velha", "8",
                      Decimal("10.00"), Decimal("0.00"), Decimal("0.00"))
    det = balde_detalhes([ItemRevisao(lancamentos=[lanc],
                                      motivo=MotivoRevisao.SEM_VINCULO,
                                      candidatos=[], mensagem="m")])[0]
    assert "URGENTE" not in det["titulo"]
    assert "conta_velha" not in det["titulo"]
    # o campo historico (evidencia) segue CRU; quem injeta em markdown escapa
    assert det["historico"] == "PGTO *URGENTE* conta_velha"


def test_localizacao_dentro_da_expansao_explica_o_lote():
    lanc = Lancamento(date(2024, 11, 14), "311814", "h", "8",
                      Decimal("33800.00"), Decimal("0.00"), Decimal("0.00"))
    det = balde_detalhes([ItemRevisao(
        lancamentos=[lanc], motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
        candidatos=[], mensagem="m")])[0]
    assert "Lote 311814" in det["localizacao"]
    assert "número do lançamento no Domínio" not in det["localizacao"]
    assert "Débito" in det["localizacao"]                # por extenso, sempre
    assert "Contrapartida" in det["localizacao"]
    assert "Cta.C.Part.): 8" in det["localizacao"]       # a contrapartida vive aqui


def test_contexto_incompleto_traduz_o_gap():
    achados = [Achado(Nivel.INCOMPLETO, "self_check_composicao", "m",
                      esperado=Decimal("3650.00"), encontrado=Decimal("3650.00"))]
    texto = contexto_incompleto(achados)
    # a frase exata mora numa constante do modulo -- referencia unica
    # o "R$" entrou no {valor} (com credito no balde a frase vira
    # "um crédito de R$ X"); sem ponte, o texto de sempre
    assert texto == apresentacao.markdown_seguro(
        apresentacao._CONTEXTO_INCOMPLETO.format(valor="R$ 3.650,00"))


def test_contexto_incompleto_none_sem_balde():
    assert contexto_incompleto([Achado(Nivel.OK, "ok", "m")]) is None


# --- data e ordem cronologica no balde ----------------------------------------

def _pag_em(lote, valor, dia, cta="8"):
    return Lancamento(dia, lote, "h", cta,
                      Decimal(valor), Decimal("0.00"), Decimal("0.00"))


def _balde_fora_de_ordem():
    # insercao NAO cronologica: mar/2025 antes de jan/2025
    return [
        ItemRevisao(lancamentos=[_pag_em("L2", "200.00", date(2025, 3, 15))],
                    motivo=MotivoRevisao.SEM_VINCULO, candidatos=[], mensagem="m"),
        ItemRevisao(lancamentos=[_pag_em("L1", "100.00", date(2025, 1, 5), cta="38")],
                    motivo=MotivoRevisao.NAO_CLASSIFICADO, candidatos=[], mensagem="m"),
    ]


def test_balde_tem_coluna_data_entre_lote_e_lado():
    linhas = balde_celulas(_balde_fora_de_ordem())
    assert list(linhas[0].keys())[:3] == ["Lote", "Data", "Lado"]
    assert linhas[0]["Data"] == date(2025, 1, 5)


def test_balde_tem_coluna_contrapartida():
    # a contrapartida sai da expansao e entra na TABELA —
    # era o unico dado por item que so vivia atras de clique
    linhas = balde_celulas(_balde_fora_de_ordem())
    assert linhas[0]["Contrapartida"] == "38"
    assert linhas[1]["Contrapartida"] == "8"


def test_balde_ordenado_por_data_crescente():
    """Conferente trabalha em ordem cronologica, como se le um razao — a
    ordem de insercao/valor nao ajuda a cruzar com o extrato."""
    linhas = balde_celulas(_balde_fora_de_ordem())
    assert [l["Lote"] for l in linhas] == ["L1", "L2"]


def test_motivos_da_tabela_sao_curtos():
    """Celula de tabela carrega rotulo curto; o texto longo
    autoexplicativo continua na expansao — nao duplica frase em celula."""
    esperados = {
        MotivoRevisao.EMPATE: "Empate",
        MotivoRevisao.SEM_VINCULO: "Sem NF",
        MotivoRevisao.MULTI_NF_NAO_CONFERE: "Soma não confere",
        MotivoRevisao.NAO_CLASSIFICADO: "Não reconhecido",
    }
    for motivo, rotulo in esperados.items():
        item = ItemRevisao(lancamentos=[_pag("L1", "1.00")], motivo=motivo,
                           candidatos=[], mensagem="m")
        assert balde_celulas([item])[0]["Motivo"] == rotulo


def test_balde_detalhes_segue_a_mesma_ordem_com_data_e_contrapartida():
    """Expansoes em ordem cronologica (a mesma da tabela); titulo carrega a
    data e a localizacao carrega lote + Cta.C.Part."""
    def _multi(lote, valor, dia, cta):
        return ItemRevisao(lancamentos=[_pag_em(lote, valor, dia, cta=cta)],
                           motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
                           candidatos=["1", "2"], mensagem="m")
    detalhes = balde_detalhes([_multi("L2", "200.00", date(2025, 3, 15), "8"),
                               _multi("L1", "100.00", date(2025, 1, 5), "38")])
    assert "05/01/2025" in detalhes[0]["titulo"]         # jan vem primeiro
    assert "L1" in detalhes[0]["localizacao"]
    assert "Cta.C.Part.): 38" in detalhes[0]["localizacao"]   # contrapartida na localizacao
    assert "15/03/2025" in detalhes[1]["titulo"]


# --- painel de triagem do lote ------------------------------------------------

def _res(codigo, nome, achados, balde=()):
    return ResultadoConferencia(
        conta=Conta(codigo=codigo, classificacao="", nome=nome),
        itens=[], balde=list(balde), achados=achados)


def _res_fecha(codigo="100", nome="FORNECEDOR VERDE"):
    return _res(codigo, nome, [_ach(Nivel.OK)])


def _res_incompleto(codigo="200", nome="FORNECEDOR AMARELO"):
    achados = [Achado(Nivel.INCOMPLETO, "self_check_composicao", "m",
                      esperado=Decimal("3650.00"), encontrado=Decimal("3650.00"))]
    balde = [ItemRevisao(lancamentos=[_pag("L1", "10.00")],
                         motivo=MotivoRevisao.SEM_VINCULO, candidatos=[],
                         mensagem="m")]
    return _res(codigo, nome, achados, balde)


def _res_divergencia(codigo="300", nome="FORNECEDOR VERMELHO"):
    return _res(codigo, nome, [_ach(Nivel.ERRO)])


def test_triagem_uma_linha_por_conta_com_os_campos_da_decisao():
    linhas = triagem_linhas([("a.xls", [_res_incompleto()], None)])
    assert len(linhas) == 1
    l = linhas[0]
    assert l["Arquivo"] == "a.xls"
    assert l["Conta"] == "200"
    assert l["Fornecedor"] == "FORNECEDOR AMARELO"
    assert "Incompleto" in l["Veredito"]
    assert l["Falta alocar"] == "3.650,00"      # o mesmo nome do placar
    assert l["Itens sem destino"] == "1"


def test_triagem_ordena_problemas_primeiro():
    """Tela de decisao: vermelho/erro no topo, amarelo depois, verde por
    ultimo — o conferente varre e ignora os verdes."""
    linhas = triagem_linhas([
        ("a.xls", [_res_fecha()], None),
        ("b.xls", [_res_incompleto()], None),
        ("c.xls", None, "'c.xls' não abriu. Re-exporte a razão."),
        ("d.xls", [_res_divergencia()], None),
    ])
    vereditos = [l["Veredito"] for l in linhas]
    assert "Erro de leitura" in vereditos[0] or "Divergência" in vereditos[0]
    assert "Erro de leitura" in vereditos[1] or "Divergência" in vereditos[1]
    assert "Incompleto" in vereditos[2]
    assert "Conferido" in vereditos[3]          # a palavra da conta


def test_triagem_arquivo_com_erro_vira_linha_sem_repetir_a_mensagem():
    linhas = triagem_linhas([("ruim.xls", None, "'ruim.xls' não abriu. Re-exporte.")])
    l = linhas[0]
    assert l["Arquivo"] == "ruim.xls"
    assert l["Conta"] == "—"
    assert "Erro de leitura" in l["Veredito"]
    assert l["Achados"] == "—"


def test_triagem_arquivo_sem_conta_nao_some_vira_linha():
    """Arquivo valido mas SEM nenhuma conta (resultados=[] e sem erro): nao
    pode sumir da triagem no meio do lote -- vira linha propria com aviso
    claro."""
    linhas = triagem_linhas([("vazio.xlsx", [], None)])
    assert len(linhas) == 1
    l = linhas[0]
    assert l["Arquivo"] == "vazio.xlsx"
    assert l["Conta"] == "—"
    assert "Sem contas" in l["Veredito"]
    assert "nenhuma conta" in l["Achados"].lower()


def test_triagem_fecha_com_alerta_fica_acima_do_fecha_limpo():
    com_alerta = _res("110", "COM ALERTA",
                      [_ach(Nivel.OK), _ach(Nivel.ALERTA, "possivel_juros")])
    linhas = triagem_linhas([
        ("a.xls", [_res_fecha()], None),
        ("b.xls", [com_alerta], None),
    ])
    assert linhas[0]["Conta"] == "110"
    assert linhas[0]["Achados"] == "1 alerta(s)"
    assert linhas[1]["Achados"] == "—"


# --- divergencias: so ERRO, esperado/encontrado BR ---

def test_divergencias_filtra_erro_e_formata():
    achados = [Achado(Nivel.OK, "ok", "m"),
               Achado(Nivel.ERRO, "self_check_composicao", "não fecha",
                      esperado=Decimal("150.00"), encontrado=Decimal("100.00"))]
    divs = divergencias(achados)
    assert len(divs) == 1
    assert divs[0]["Esperado"] == "150,00"
    assert divs[0]["Encontrado"] == "100,00"


def test_divergencias_vazio_quando_so_ok_e_alerta():
    achados = [Achado(Nivel.OK, "ok", "m"), Achado(Nivel.ALERTA, "al", "m")]
    assert divergencias(achados) == []


# "NF" na frente so' de numero de nota (so digitos); o nome livre
# digitado pelo operador e o rotulo do motor saem como estao.

@pytest.mark.parametrize("nome,esperado", [
    ("1234", "NF 1234"),
    ("998877", "NF 998877"),
    ("LINHA NOVA X", "LINHA NOVA X"),
    ("NF 5678", "NF 5678"),                       # o operador ja digitou o "NF"
    ("LINHA9", "LINHA9"),                         # letras + digito: nome livre
    ("1234 NOVA", "1234 NOVA"),                   # comeca por digito, nao e' so digito
    ("(manual: lote 5002)", "(manual: lote 5002)"),
    ("(transferencia lote 5001)", "(transferencia lote 5001)"),
    ("(anterior)", "(anterior)"),
])
def test_nome_de_linha_so_poe_nf_em_numero_de_nota(nome, esperado):
    assert nome_de_linha(nome) == esperado


def test_seletor_de_destino_nao_afirma_nf_para_linha_criada_com_nome_livre():
    from app.destinos import opcoes_de_alocacao
    from core.modelo import DestinoAlocacao
    item = ComposicaoItem(
        nf_numero="LINHA NOVA X", origem=Origem.ALOCACAO_MANUAL,
        valor_compra=Decimal("100.00"), total_pago=Decimal("0.00"),
        total_retido=Decimal("0.00"), saldo_aberto=Decimal("100.00"),
        data_compra=date(2025, 1, 10))
    rotulos = [o.rotulo for o in opcoes_de_alocacao([item], Decimal("50.00"))
               if o.destino is DestinoAlocacao.LINHA_ABERTA]
    assert rotulos == ["LINHA NOVA X · em aberto 100,00 · criada nesta sessão"]


# codigo interno snake_case nao e' fato legivel -- as verificacoes
# de leitura/fechamento tem nome na tela (divergencias) e no Excel (Tipo).
_ROTULOS_DAS_VERIFICACOES = {
    "self_check_saldo_corrente": "Saldo da linha não confere",
    "self_check_total_debito": "Total de débitos",
    "self_check_total_credito": "Total de créditos",
    "self_check_saldo_final": "Saldo final",
    "self_check_composicao": "Composição x saldo final",
}


@pytest.mark.parametrize("codigo,rotulo", sorted(_ROTULOS_DAS_VERIFICACOES.items()))
def test_divergencia_mostra_o_nome_da_verificacao_e_nao_o_codigo(codigo, rotulo):
    achados = [Achado(Nivel.ERRO, codigo, "não fecha",
                      esperado=Decimal("150.00"), encontrado=Decimal("100.00"),
                      valores={"residuo": Decimal("0.00")})]
    (linha,) = divergencias(achados)
    assert linha["Verificação"] == rotulo
    assert "self_check_" not in " ".join(linha.values())


@pytest.mark.parametrize("codigo,rotulo", sorted(_ROTULOS_DAS_VERIFICACOES.items()))
def test_alerta_na_planilha_mostra_o_nome_da_verificacao(codigo, rotulo):
    (linha,) = alertas_celulas([Achado(
        Nivel.ALERTA, codigo, "saldo corrente do lote 5002 não fecha",
        esperado=Decimal("-100.00"), encontrado=Decimal("-50.00"))])
    assert linha["Tipo"] == rotulo


def test_verificacao_sem_nome_cadastrado_segue_com_o_codigo():
    """CONTROLE: o fallback nao mudou -- codigo novo aparece como veio."""
    (linha,) = divergencias([Achado(Nivel.ERRO, "verificacao_nova", "m",
                                    esperado=Decimal("1.00"), encontrado=Decimal("2.00"))])
    assert linha["Verificação"] == "verificacao_nova"


# --- alertas: so ALERTA (nota secundaria, nao erro nem balde) ---

def test_alertas_pega_so_alerta():
    achados = [Achado(Nivel.OK, "ok", "m"),
               Achado(Nivel.ALERTA, "saldo_anterior_nao_detalhado", "puxar razão")]
    al = alertas(achados)
    assert len(al) == 1
    assert al[0].codigo == "saldo_anterior_nao_detalhado"


# --- o core devolve NUMEROS; a frase de exibicao nasce AQUI -------------
# Padrao _CONTEXTO_INCOMPLETO: a frase mora na apresentacao, o core
# entrega codigo + campos (esperado/encontrado/valores). Sem template ou sem
# os valores necessarios -> a.mensagem crua (fallback VISIVEL, nunca em branco).

D = Decimal


def test_frase_achado_possivel_juros_formata_moeda_br():
    """Os numeros continuam iguais e ganham a ORIENTACAO do contador
    — juros vai pra conta de despesa, nao amortiza a compra."""
    a = Achado(Nivel.ALERTA, "possivel_juros",
               "possível juros por atraso na NF 810118",
               esperado=D("2202.51"), encontrado=D("2209.08"),
               valores={"diferenca": D("6.57")})
    assert frase_achado(a) == (
        "possível juros por atraso na NF 810118: quitado R$ 2.209,08 "
        "sobre compra R$ 2.202,51 (diferença R$ 6,57) — juros é despesa em "
        "conta específica, não abatimento do valor da compra (fornecedor)")


def test_frase_achado_possivel_juros_manual_tem_a_mesma_orientacao():
    """O estouro vindo de alocacao manual tem codigo PROPRIO e precisa
    da MESMA orientacao contabil: e o mesmo juros, so' muda a origem."""
    a = Achado(Nivel.ALERTA, "possivel_juros_manual",
               "possível juros por atraso na NF 810118, após alocação manual",
               esperado=D("2202.51"), encontrado=D("2209.08"),
               valores={"diferenca": D("6.57")})
    frase = frase_achado(a)
    assert "após alocação manual" in frase
    assert ("juros é despesa em conta específica, não abatimento do valor "
            "da compra (fornecedor)") in frase


def test_frase_achado_casamento_por_desempate_traz_o_valor_em_moeda_br():
    """O core devolve a evidencia (lote, NF, criterio) e o numero cru; o
    R$ formatado nasce aqui."""
    a = Achado(Nivel.ALERTA, "casamento_por_desempate",
               "casamento por desempate: lote 376043 alocado na NF 810103 — "
               "única candidata ainda em aberto entre 2 candidatas",
               valores={"pagamento": D("6657.30")})
    assert frase_achado(a) == (
        "casamento por desempate: lote 376043 alocado na NF 810103 — "
        "única candidata ainda em aberto entre 2 candidatas (R$ 6.657,30)")


def test_frase_achado_possivel_desconto_oferece_as_duas_leituras():
    """A faixa de 2% e tambem a de IRRF/ISS — a frase nao AFIRMA desconto,
    oferece as duas leituras pro conferente decidir."""
    a = Achado(Nivel.ALERTA, "possivel_desconto",
               "possível desconto obtido na NF 1234",
               esperado=D("1000.00"), encontrado=D("980.00"),
               valores={"diferenca": D("20.00"), "percentual": D("2.00")})
    frase = frase_achado(a)
    assert frase == ("possível desconto obtido na NF 1234: quitado R$ 980,00 "
                     "de R$ 1.000,00 (falta R$ 20,00, 2,00% — possível desconto "
                     "concedido ou retenção não lançada).")


def test_frase_achado_saldo_anterior_em_formato_br():
    a = Achado(Nivel.ALERTA, "saldo_anterior_nao_detalhado",
               "saldo anterior não detalhado, puxar razão anterior",
               encontrado=D("12635.07"))
    assert frase_achado(a) == ("saldo anterior de R$ 12.635,07 sem detalhe de "
                               "notas neste razão")


def test_frase_achado_conta_devedora():
    """O texto e' o do contador — diz o QUE e' (mais
    debitos que creditos) e as CAUSAS COMUNS, em vez do 'revisar' generico."""
    a = Achado(Nivel.ALERTA, "conta_devedora", "conta com saldo devedor",
               encontrado=D("1234.50"))
    frase = frase_achado(a)
    assert "R$ 1.234,50" in frase
    assert "mais pagamentos (débitos) que provisões (créditos)" in frase
    assert "parcelas pagas com juros" in frase
    assert "pagamentos sem nota fiscal" in frase
    assert "notas ainda não contabilizadas" in frase


def test_frase_achado_divergencia_usa_residuo_do_core():
    # o residuo vem do CORE (valores) — a apresentacao nunca subtrai dinheiro
    a = Achado(Nivel.ERRO, "self_check_composicao",
               "divergência não explicada pelo balde",
               esperado=D("1000.00"), encontrado=D("1500.00"),
               valores={"residuo": D("500.00")})
    frase = frase_achado(a)
    assert "diferença de R$ 1.500,00" in frase
    assert "os itens sem destino explicam R$ 1.000,00" in frase
    assert "divergência não explicada pelos itens sem destino" in frase
    assert "sobra R$ 500,00 sem explicação" in frase


def test_frase_achado_duplicidade_da_rota_balde_mostra_valor_br():
    a = Achado(Nivel.ALERTA, "possivel_duplicidade",
               "possível duplicidade: parcela 5 de 5 paga 2 vezes (lotes "
               "319455, 322117); há ocorrência(s) no balde de revisão manual",
               valores={"valor": D("26000.00")})
    frase = frase_achado(a)
    assert frase.startswith("possível duplicidade: parcela 5 de 5")
    assert "R$ 26.000,00" in frase
    assert "26000.00" not in frase


def test_frase_achado_sem_template_ou_sem_valores_cai_na_mensagem():
    desconhecido = Achado(Nivel.ALERTA, "codigo_novo", "mensagem tecnica crua")
    assert frase_achado(desconhecido) == "mensagem tecnica crua"
    # codigo conhecido mas SEM os numeros (ex.: achado sintetico de teste):
    # fallback pra mensagem, nunca frase pela metade nem excecao
    sem_valores = Achado(Nivel.ALERTA, "possivel_juros",
                         "pagamento R$ 150,00 sobre compra R$ 100,00 (NF 1111)")
    assert frase_achado(sem_valores) == \
        "pagamento R$ 150,00 sobre compra R$ 100,00 (NF 1111)"


def test_frases_alertas_formata_so_os_alertas():
    achados = [
        Achado(Nivel.OK, "ok", "tudo certo"),
        Achado(Nivel.ALERTA, "saldo_anterior_nao_detalhado",
               "saldo anterior não detalhado, puxar razão anterior",
               encontrado=D("300.00")),
        Achado(Nivel.ERRO, "self_check_composicao", "divergencia"),
    ]
    frases = frases_alertas(achados)
    assert frases == ["saldo anterior de R$ 300,00 sem detalhe de notas neste razão"]


def test_motivo_humano_multi_nf_formata_soma_e_pagamento_do_core():
    item = ItemRevisao(
        lancamentos=[],
        motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE,
        candidatos=["810104", "810105"],
        mensagem="soma dos saldos das NFs citadas não confere com o pagamento",
        valores={"soma": D("156000.00"), "pagamento": D("101400.00")})
    texto = motivo_humano(item)
    assert "R$ 156.000,00" in texto
    assert "R$ 101.400,00" in texto
    assert "156000.00" not in texto


# --- o valor alocado a mao em coluna propria ---

def test_composicao_mostra_alocado_a_mao_em_coluna_propria():
    """Regressao de um bug de campo: o que o contador alocou aparece como
    VALOR, na coluna propria — e "Total pago" continua so' com o que o motor
    casou (nao se mistura). A coluna fica entre a baixa e o EM ABERTO: a
    linha se le como uma conta."""
    item = ComposicaoItem(nf_numero="7777", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1000.00"), total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("700.00"),
                          total_manual=Decimal("300.00"), idade_dias=10,
                          quitacoes_manuais=1)
    linhas = composicao_linhas([item])
    assert linhas[0]["Alocado à mão"] == "300,00"
    assert linhas[0]["Total pago"] == "0,00"
    assert linhas[0]["EM ABERTO"] == "700,00"
    colunas = list(linhas[0])
    assert (colunas.index("Baixa adiant.") < colunas.index("Alocado à mão")
            < colunas.index("EM ABERTO"))


def test_composicao_credito_alocado_a_mao_sai_negativo():
    """Credito alocado REABRE o titulo: o sinal vai junto, sem coluna extra."""
    item = ComposicaoItem(nf_numero="7777", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1000.00"), total_pago=Decimal("1000.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("250.00"),
                          total_manual=Decimal("-250.00"), idade_dias=10,
                          quitacoes_manuais=1)
    assert composicao_linhas([item])[0]["Alocado à mão"] == "-250,00"


# --- retencao em coluna propria e a identidade da tabela em TEXTO ---

# "Pago antes da NF no razao" fica entre as duas datas de quitacao e a idade
COLUNAS_FINAIS = ["NF", "Data NF", "Valor compra", "Total pago", "Retido",
                  "Baixa adiant.", "Alocado à mão", "EM ABERTO", "Última quitação",
                  "Pago antes da NF no razão", "Idade (dias)"]


def test_composicao_mostra_retido_em_coluna_propria():
    """O manual prometia a retencao dentro de "Total pago" e nunca foi assim
    (18f556e). Coluna propria: IRRF/ISS/INSS ligados a NF sao quitacao sem
    numerario, e o conferente ve quanto foi."""
    item = ComposicaoItem(nf_numero="5555", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("1000.00"), total_pago=Decimal("500.00"),
                          total_retido=Decimal("15.00"), saldo_aberto=Decimal("485.00"),
                          idade_dias=10)
    linhas = composicao_linhas([item])
    assert linhas[0]["Retido"] == "15,00"
    assert linhas[0]["Total pago"] == "500,00"
    assert linhas[0]["EM ABERTO"] == "485,00"


def test_composicao_tem_o_conjunto_final_de_colunas_na_ordem():
    """A familia de quitacao na ordem da identidade e EM ABERTO logo
    depois de tudo que se subtrai dele."""
    item = ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("0.00"), total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("0.00"))
    assert list(composicao_linhas([item])[0]) == COLUNAS_FINAIS


def test_de_moeda_br_desfaz_moeda_br():
    for v in ("0.00", "15.00", "1234.56", "-1100.00", "1234567.89"):
        assert de_moeda_br(moeda_br(Decimal(v))) == Decimal(v)


def test_linhas_de_texto_fecham_a_identidade_da_tabela():
    """A conta que o conferente faz de olho na tela, com a familia inteira:
    compra − pago − retido − baixa − alocado == EM ABERTO, linha a linha."""
    itens = [
        ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                       valor_compra=Decimal("1000.00"), total_pago=Decimal("500.00"),
                       total_retido=Decimal("15.00"), total_baixado=Decimal("100.00"),
                       total_manual=Decimal("300.00"), saldo_aberto=Decimal("85.00"),
                       idade_dias=10),
        ComposicaoItem(nf_numero="2", origem=Origem.COMPRA_PERIODO,
                       valor_compra=Decimal("1000.00"), total_pago=Decimal("1000.00"),
                       total_retido=Decimal("0.00"), total_manual=Decimal("-250.00"),
                       saldo_aberto=Decimal("250.00"), idade_dias=5),
        ComposicaoItem(nf_numero="(anterior)", origem=Origem.SALDO_ANTERIOR,
                       valor_compra=Decimal("10000.00"), total_pago=Decimal("0.00"),
                       total_retido=Decimal("0.00"), total_baixado=Decimal("10000.00"),
                       saldo_aberto=Decimal("0.00")),
    ]
    identidade_das_linhas(composicao_linhas(itens))


# --- a foto completa numa tabela SO' ---

def test_itens_da_tabela_junta_aberto_e_quitado_na_ordem_de_idade():
    """Decisao de campo: as quitadas voltam pra tabela da composicao, com
    EM ABERTO 0,00, na MESMA ordenacao por idade -- nao ha mais secao separada.
    O canal do core (itens x quitadas) fica; quem junta e' a apresentacao."""
    from app.apresentacao import itens_da_tabela

    class _Res:
        itens = [_item("ABERTA", "100.00", 50)]
        quitadas = [_item("VELHA", "0.00", 900), _item("NOVA", "0.00", 10)]

    linhas = composicao_linhas(itens_da_tabela(_Res()))
    assert [l["NF"] for l in linhas] == ["VELHA", "ABERTA", "NOVA"]   # so idade
    assert [l["EM ABERTO"] for l in linhas] == ["0,00", "100,00", "0,00"]


def test_itens_da_tabela_sem_quitadas_e_so_a_composicao():
    from app.apresentacao import itens_da_tabela

    class _Res:
        itens = [_item("1", "100.00", 5)]
        quitadas = []

    assert [i.nf_numero for i in itens_da_tabela(_Res())] == ["1"]


# --- a linha do saldo anterior se explica sozinha ---

def _anterior(compra="10000.00", baixado="10000.00", aberto="0.00"):
    return ComposicaoItem(nf_numero=ALVO_ANTERIOR, origem=Origem.SALDO_ANTERIOR,
                          valor_compra=Decimal(compra),
                          total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"),
                          total_baixado=Decimal(baixado),
                          saldo_aberto=Decimal(aberto))


def test_linha_do_saldo_anterior_se_identifica_no_rotulo():
    """Quem confere precisou PERGUNTAR o que era a linha. O rotulo de exibicao diz."""
    linhas = composicao_linhas([_anterior()])
    assert linhas[0]["NF"] == "(saldo anterior)"


def test_nota_explica_a_linha_do_saldo_anterior_com_os_dois_numeros():
    """Trazido e sem detalhe, ambos LIDOS de campo — o que o periodo quitou
    continua nas colunas do meio (nenhuma soma nasce aqui)."""
    (nota,) = notas_composicao_texto([_anterior(aberto="2500.00")])
    assert nota == ("(saldo anterior): R$ 10.000,00 de saldo trazido do período "
                    "anterior; R$ 2.500,00 ainda sem detalhe")


def test_sem_linha_de_saldo_anterior_nao_ha_nota():
    item = ComposicaoItem(nf_numero="1", origem=Origem.COMPRA_PERIODO,
                          valor_compra=Decimal("100.00"), total_pago=Decimal("0.00"),
                          total_retido=Decimal("0.00"), saldo_aberto=Decimal("100.00"),
                          idade_dias=5)
    assert notas_composicao_texto([item]) == []


# === "sem numero de NF no historico" era falso quando o historico CITA ===

_FRASE_SEM_VINCULO_SEM_CITACAO = ("Pagamento sem número de NF no histórico e sem NF em "
                                  "aberto de valor compatível nesta conta.")


def _item_sem_vinculo(historico, valor):
    """O item que o motor REAL devolve: 5001 = 500,00 quitada por 'PGTO NF 5001' e
    depois o pagamento do teste, que nao acha NF em aberto."""
    from core.casamento import casar
    from core.classifica import Classificacao, Tipo
    from parser.historico import ClassificadorHistorico
    from tests.helpers import lanc
    compra = (lanc("Vr. compras conf. 5001", numero="c", dia=1, credito="500.00"),
              Classificacao(Tipo.COMPRA, nf_numero="5001"))
    quitacao = (lanc("PGTO NF 5001", numero="p1", dia=5, debito="500.00"),
                Classificacao(Tipo.PAGAMENTO, nf_numero="5001", nfs_citadas=("5001",)))
    l = lanc(historico, numero="p2", dia=9, debito=valor)
    res = casar([compra, quitacao, (l, ClassificadorHistorico().classificar(l))],
                saldo_anterior=Decimal("0.00"))
    (item,) = [i for i in res.balde if i.motivo is MotivoRevisao.SEM_VINCULO]
    return item


def test_pagamento_que_cita_nf_sem_compra_diz_que_o_historico_cita():
    item = _item_sem_vinculo("PGTO NF 9999", "500.00")
    assert motivo_humano(item) == (
        "Pagamento cita a NF 9999, que não tem compra nesta conta no período do "
        "arquivo, e não há NF em aberto de valor compatível.")


def test_pagamento_sem_nf_citada_segue_com_a_frase_de_hoje():
    """CONTROLE."""
    item = _item_sem_vinculo("PGTO FORNECEDOR", "777.00")
    assert motivo_humano(item) == _FRASE_SEM_VINCULO_SEM_CITACAO


def test_celula_do_excel_e_titulo_do_item_citado_seguem_como_eram():
    """Decisao de produto: a celula 'Sem NF' e o titulo 'Sem NF correspondente' ficam."""
    item = _item_sem_vinculo("PGTO NF 9999", "500.00")
    assert balde_celulas([item])[0]["Motivo"] == "Sem NF"
    assert apresentacao._MOTIVOS[MotivoRevisao.SEM_VINCULO].titulo == "Sem NF correspondente"

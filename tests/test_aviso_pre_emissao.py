"""Aviso de pagamento anterior a emissao da NF."""
from datetime import date
from decimal import Decimal

import pytest

from app.apresentacao import (ContextoAvisos, avisos_do_item,
                              aviso_pre_emissao, balde_celulas,
                              balde_detalhes, contexto_de_avisos,
                              datas_de_emissao, ressalva_gemeas)
from core.modelo import (ComposicaoItem, CriterioSugestao, DestinoAlocacao,
                         ItemRevisao, Lancamento, MotivoRevisao, Origem,
                         ResultadoConferencia, Conta, Sugestao)

D = Decimal


def _pag(lote, valor, dia, mes=5):
    return Lancamento(date(2025, mes, dia), lote, "1a PARCELA", "x",
                      D(valor), D("0.00"), D("0.00"))


def _item(lanc, **kw):
    kw.setdefault("motivo", MotivoRevisao.SEM_VINCULO)
    kw.setdefault("candidatos", [])
    return ItemRevisao(lancamentos=[lanc], mensagem="m", **kw)


DATAS = ContextoAvisos(datas_nf={"41592": date(2025, 6, 10)})


def test_pagamento_anterior_a_emissao_avisa_em_palavras():
    """Um caso medido: a 1a parcela (15/05) precede a compra (10/06)."""
    item = _item(_pag("324122", "18800.00", 15), candidatos=["41592"])
    aviso = aviso_pre_emissao(item.lancamentos[0], item, DATAS)
    assert "15/05/2025" in aviso
    assert "ANTERIOR à data no razão da NF 41592 (10/06/2025)" in aviso
    assert "adiantamento" in aviso
    assert "processo de conciliação" in aviso


def test_pagamento_posterior_nao_avisa_nada():
    item = _item(_pag("999", "18800.00", 15, mes=7), candidatos=["41592"])
    assert aviso_pre_emissao(item.lancamentos[0], item, DATAS) == ""


def test_credito_nunca_avisa():
    """Credito nao e' pagamento — o aviso e' sobre pagamento."""
    cred = Lancamento(date(2025, 5, 15), "L1", "h", "x",
                      D("0.00"), D("100.00"), D("0.00"))
    assert aviso_pre_emissao(cred, _item(cred, candidatos=["41592"]), DATAS) == ""


def test_a_nf_avisada_e_a_SUGERIDA_quando_ha_sugestao():
    """A sugerida tem precedencia sobre as candidatas: e' a que o conferente
    esta prestes a aceitar."""
    item = _item(_pag("324122", "18800.00", 15), candidatos=["999", "41592"],
                 motivo=MotivoRevisao.EMPATE)
    item.sugestao = Sugestao(destino=DestinoAlocacao.LINHA_ABERTA, alvo="41592",
                             criterio=CriterioSugestao.CONTINUIDADE_SERIE_ORDINAL)
    # a descartada tambem e' posterior ao pagamento: se a precedencia cair, ela
    # aparece no aviso (foi assim que a mutacao pegou o teste fraco)
    datas = ContextoAvisos(datas_nf={**DATAS.datas_nf,
                                     "999": date(2025, 6, 30)})
    aviso = aviso_pre_emissao(item.lancamentos[0], item, datas)
    assert "NF 41592" in aviso
    assert "999" not in aviso


def test_duas_candidatas_posteriores_saem_as_duas():
    item = _item(_pag("L1", "100.00", 15), candidatos=["41592", "30000"],
                 motivo=MotivoRevisao.EMPATE)
    datas = ContextoAvisos(datas_nf={**DATAS.datas_nf,
                                     "30000": date(2025, 6, 20)})
    aviso = aviso_pre_emissao(item.lancamentos[0], item, datas)
    assert "das NFs 41592 (10/06/2025), 30000 (20/06/2025)" in aviso


def test_nf_sem_data_de_compra_nao_avisa():
    """Sem data nao ha comparacao — o "(anterior)" e a NF sem compra na janela
    ficam de fora em silencio, nunca com aviso inventado."""
    item = _item(_pag("L1", "100.00", 15), candidatos=["(anterior)"])
    assert aviso_pre_emissao(item.lancamentos[0], item, DATAS) == ""


def _res_com(item):
    conta = Conta(codigo="1", classificacao="c", nome="n")
    aberto = ComposicaoItem(nf_numero="41592", origem=Origem.COMPRA_PERIODO,
                            valor_compra=D("268000.00"), total_pago=D("0.00"),
                            total_retido=D("0.00"), saldo_aberto=D("268000.00"),
                            data_compra=date(2025, 6, 10))
    return ResultadoConferencia(conta=conta, itens=[aberto], balde=[item])


def test_datas_de_emissao_le_abertas_e_quitadas():
    """O item do balde pode citar uma NF que ja FECHOU; o aviso vale igual."""
    res = _res_com(_item(_pag("L1", "1.00", 15)))
    res.quitadas = [ComposicaoItem(nf_numero="70000", origem=Origem.COMPRA_PERIODO,
                                   valor_compra=D("10.00"), total_pago=D("10.00"),
                                   total_retido=D("0.00"), saldo_aberto=D("0.00"),
                                   data_compra=date(2025, 7, 1))]
    assert datas_de_emissao(res) == {"41592": date(2025, 6, 10),
                                     "70000": date(2025, 7, 1)}


def test_caixinha_do_balde_carrega_o_aviso():
    item = _item(_pag("324122", "18800.00", 15), candidatos=["41592"])
    det = balde_detalhes([item], contexto_de_avisos(_res_com(item)))[0]
    assert "ANTERIOR à data no razão da NF 41592" in det["aviso"]


def test_caixinha_sem_datas_nao_quebra():
    """Chamada legada (sem o mapa) continua valida — aviso vazio, nunca erro."""
    item = _item(_pag("324122", "18800.00", 15), candidatos=["41592"])
    assert balde_detalhes([item])[0]["aviso"] == ""


def test_planilha_junta_aviso_na_celula_da_sugestao():
    """A planilha nao ganha coluna nova. O aviso vai onde o
    conferente le o que fazer com o item."""
    item = _item(_pag("324122", "18800.00", 15), candidatos=["41592"])
    linha = balde_celulas([item], ctx=contexto_de_avisos(_res_com(item)))[0]
    assert "ANTERIOR à data no razão da NF 41592" in linha["Sugestão do motor"]


# --- os itens do balde apontam pro achado das gemeas ---

GEMEAS = ContextoAvisos(gemeas={"40317": ("40317", "40318"),
                                "40318": ("40317", "40318")})


def test_item_que_disputa_as_duas_gemeas_ganha_a_ressalva():
    """Um caso: 26.000,00 em EMPATE entre duas NFs gemeas."""
    item = _item(_pag("L1", "26000.00", 15), candidatos=["40317", "40318"],
                 motivo=MotivoRevisao.EMPATE)
    texto = ressalva_gemeas(item, GEMEAS)
    assert "40317, 40318" in texto
    assert "duplicidade na emissão" in texto
    # regra de tela: o texto mostra FATO, nunca instrucao
    assert "pode não haver o que decidir aqui" in texto


def test_item_que_cita_uma_gemea_so_nao_ganha_ressalva():
    """Ele nao vive o dilema — ja tem destino. O alerta do painel basta."""
    item = _item(_pag("L1", "26000.00", 15), candidatos=["40317"])
    assert ressalva_gemeas(item, GEMEAS) == ""


def test_item_sem_gemeas_no_contexto_nao_ganha_ressalva():
    item = _item(_pag("L1", "26000.00", 15), candidatos=["40317", "40318"])
    assert ressalva_gemeas(item, ContextoAvisos()) == ""


def test_a_ressalva_NAO_se_cala_por_haver_sugestao():
    """A proposta pode estar apontando pra uma nota que
    nao deveria existir. Num caso medido, a regra serie x saldo sugere 40317 pros quatro
    pagamentos de 26.000,00. Se a ressalva
    respeitasse a precedencia da sugerida (como o aviso de pre-emissao faz),
    justamente eles ficariam sem ela."""
    item = _item(_pag("L1", "26000.00", 15), candidatos=["40317", "40318"],
                 motivo=MotivoRevisao.EMPATE)
    item.sugestao = Sugestao(destino=DestinoAlocacao.LINHA_ABERTA, alvo="40317",
                             criterio=CriterioSugestao.SERIE_X_SALDO_REMANESCENTE)
    assert "40317, 40318" in ressalva_gemeas(item, GEMEAS)


def test_contexto_de_avisos_le_as_gemeas_do_ACHADO():
    """Fonte UNICA: quem detecta duplicidade e' o core. A casca aponta pro
    MESMO achado que o painel mostra, nunca redetecta."""
    from core.modelo import Achado, Nivel
    res = _res_com(_item(_pag("L1", "1.00", 15)))
    res.achados = [Achado(Nivel.ALERTA, "possivel_duplicidade_emissao",
                          "m", referencia="40317, 40318")]
    ctx = contexto_de_avisos(res)
    assert ctx.gemeas == {"40317": ("40317", "40318"),
                          "40318": ("40317", "40318")}


def test_os_dois_avisos_convivem_na_mesma_frase():
    """Pagamento pre-emissao E gemeas: um canal so', os dois textos."""
    ctx = ContextoAvisos(datas_nf={"40317": date(2025, 6, 10),
                                   "40318": date(2025, 6, 10)},
                         gemeas=GEMEAS.gemeas)
    item = _item(_pag("L1", "26000.00", 15), candidatos=["40317", "40318"],
                 motivo=MotivoRevisao.EMPATE)
    texto = avisos_do_item(item.lancamentos[0], item, ctx)
    assert "ANTERIOR à data no razão" in texto
    assert "duplicidade na emissão" in texto


def test_sem_contexto_nenhum_aviso_e_nada_quebra():
    item = _item(_pag("L1", "26000.00", 15), candidatos=["40317", "40318"])
    assert avisos_do_item(item.lancamentos[0], item, None) == ""

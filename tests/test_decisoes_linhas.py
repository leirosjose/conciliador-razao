"""Consumer da tela com fixture exclusivamente sintetica."""
from dataclasses import replace
from pathlib import Path

import pytest

from app.apresentacao import decisao_texto, decisoes_linhas
from app.pipeline import processar_excel
from core.modelo import (
    ALVO_ANTERIOR,
    AlocacaoManual,
    DestinoAlocacao,
    ErroAlocacao,
    FechadoPorSaldoZero,
    ItemRevisao,
)

SINTETICA = Path(__file__).parent / "fixtures" / "sintetica_integra.xls"
FORA = DestinoAlocacao.FORA_DA_COMPOSICAO
ABERTA = DestinoAlocacao.LINHA_ABERTA
NOVA = DestinoAlocacao.COMPRA_NOVA
CAMPOS_3014 = {"lote": "3014", "data": "03/02/2025",
               "lado": "Crédito", "valor": "500,00"}


def _resultado(alocacoes=()):
    resultados = processar_excel(SINTETICA, {"7777": alocacoes}).resultados
    return next(r for r in resultados if r.conta.codigo == "7777")


@pytest.fixture(scope="module")
def base():
    return _resultado()


def _item(base, lote):
    return next(i for i in base.balde if i.lancamentos[0].numero == lote)


def _recusa(base, lote, destino, codigo, *, alvo="", rotulo=""):
    a = AlocacaoManual(_item(base, lote).identificador, destino,
                       alvo=alvo, rotulo=rotulo)
    res = _resultado([a])
    assert [e.codigo for e in res.erros_alocacao] == [codigo]
    linha, = decisoes_linhas([a], res)
    assert linha["indice"] == 0
    assert linha["erro"] == res.erros_alocacao[0].mensagem
    assert any(i.identificador == a.item_id for i in res.balde)
    return linha


def _campos(linha):
    return {k: linha[k] for k in CAMPOS_3014}


def test_recusa_preserva_dados_do_balde(base):
    linha = _recusa(base, "3014", FORA, "ROTULO_OBRIGATORIO")
    assert linha["lote"] == "3014"
    assert _campos(linha) == CAMPOS_3014
    assert linha["erro"] == (
        "falta a justificativa de por que este lançamento não pertence à composição"
    )
    assert decisao_texto(linha) == (
        "3014 · 03/02/2025 · Crédito 500,00  →  fora da composição"
    )


def test_item_ja_alocado_busca_na_decisao_aplicada(base):
    item_id = _item(base, "3014").identificador
    alocacoes = [AlocacaoManual(item_id, FORA, rotulo="a"),
                 AlocacaoManual(item_id, FORA, rotulo="b")]
    res = _resultado(alocacoes)
    assert [e.codigo for e in res.erros_alocacao] == ["ITEM_JA_ALOCADO"]
    assert not any(i.identificador == item_id for i in res.balde)
    assert res.decisoes[0].item.identificador == item_id
    linhas = decisoes_linhas(alocacoes, res)
    assert [l["indice"] for l in linhas] == [0, 1]
    assert linhas[1]["lote"] == "3014"
    assert _campos(linhas[1]) == CAMPOS_3014
    assert linhas[1]["erro"] == res.erros_alocacao[0].mensagem
    assert decisao_texto(linhas[1]) == (
        '3014 · 03/02/2025 · Crédito 500,00  →  fora da composição "b"'
    )


def test_item_inexistente_mostra_fato():
    a = AlocacaoManual("id-sintetico-inexistente", FORA, rotulo="x")
    res = _resultado([a])
    assert [e.codigo for e in res.erros_alocacao] == ["ITEM_INEXISTENTE"]
    linha, = decisoes_linhas([a], res)
    assert linha["indice"] == 0
    assert linha["erro"] == res.erros_alocacao[0].mensagem
    assert decisao_texto(linha) == (
        'lançamento não encontrado nesta conferência  →  fora da composição "x"'
    )


def test_alvo_ausente_nao_mostra_seta(base):
    linha = _recusa(base, "3014", ABERTA, "ALVO_AUSENTE")
    assert linha["destino"] == ""
    assert linha["erro"] == "nenhuma linha de destino escolhida"
    assert "→" not in decisao_texto(linha)
    assert decisao_texto(linha) == "3014 · 03/02/2025 · Crédito 500,00"
    assert _campos(linha) == CAMPOS_3014


def test_linha_aplicada_identica(base):
    a = AlocacaoManual(_item(base, "3014").identificador, FORA, rotulo="teste")
    res = _resultado([a])
    assert res.erros_alocacao == []
    linha, = decisoes_linhas([a], res)
    assert linha == dict(CAMPOS_3014, indice=0,
                         destino='fora da composição "teste"', erro=None)
    assert decisao_texto(linha) == (
        '3014 · 03/02/2025 · Crédito 500,00  →  fora da composição "teste"'
    )


@pytest.mark.parametrize("lote,destino,codigo,alvo,rotulo,campos,destino_texto", [
    ("3014", ABERTA, "NF_INEXISTENTE", "999999", "", CAMPOS_3014, "NF 999999"),
    ("3016", ABERTA, "NF_QUITADA", "4444", "",
     {"lote": "3016", "data": "01/04/2025", "lado": "Débito", "valor": "400,00"},
     "NF 4444"),
    ("3016", ABERTA, "ANTERIOR_QUITADO", ALVO_ANTERIOR, "",
     {"lote": "3016", "data": "01/04/2025", "lado": "Débito", "valor": "400,00"},
     ALVO_ANTERIOR),
    ("3016", NOVA, "DESTINO_INCOMPATIVEL", "", "teste",
     {"lote": "3016", "data": "01/04/2025", "lado": "Débito", "valor": "400,00"},
     'compra nova "teste"'),
    ("3014", NOVA, "NOME_EM_USO", "", "1111", CAMPOS_3014, 'compra nova "1111"'),
])
def test_outros_codigos_preservam_dados_e_destino(
        base, lote, destino, codigo, alvo, rotulo, campos, destino_texto):
    linha = _recusa(base, lote, destino, codigo, alvo=alvo, rotulo=rotulo)
    assert linha["destino"] == destino_texto
    assert _campos(linha) == campos


def test_item_com_dois_lancamentos_mostra_o_primeiro(base):
    primeiro = _item(base, "3014").lancamentos[0]
    segundo = _item(base, "3016").lancamentos[0]
    original = _item(base, "3014")
    item = ItemRevisao(lancamentos=[primeiro, segundo], motivo=original.motivo,
                       identificador="grupo-sintetico")
    a = AlocacaoManual(item.identificador, FORA)
    erro = ErroAlocacao(a, "ROTULO_OBRIGATORIO", "justificativa ausente")
    res = replace(base, balde=[item], decisoes=[], erros_alocacao=[erro])
    linha, = decisoes_linhas([a], res)
    assert _campos(linha) == CAMPOS_3014


def _resultado_recusado_sem_item_ativo(base, fechado=None):
    item = _item(base, "3014")
    a = AlocacaoManual(item.identificador, FORA)
    erro = ErroAlocacao(
        a, "ROTULO_OBRIGATORIO",
        "falta a justificativa de por que este lançamento não pertence à composição",
    )
    res = replace(base,
                  balde=[i for i in base.balde if i.identificador != a.item_id],
                  decisoes=[], erros_alocacao=[erro], fechado=fechado)
    return a, res


def test_erro_sem_item_localizado_nao_afirma_item_inexistente(base):
    a, res = _resultado_recusado_sem_item_ativo(base)
    linha, = decisoes_linhas([a], res)
    texto = decisao_texto(linha)
    assert "lançamento não encontrado nesta conferência" not in texto
    assert texto == "— · — · — —  →  fora da composição"
    assert _campos(linha) == dict.fromkeys(CAMPOS_3014, "—")
    assert linha["indice"] == 0
    assert linha["erro"] == res.erros_alocacao[0].mensagem


def test_recusa_busca_item_no_balde_do_periodo_zerado(base):
    item = _item(base, "3014")
    l = item.lancamentos[0]
    fechado = FechadoPorSaldoZero(data=l.data, lote=l.numero, balde=[item])
    a, res = _resultado_recusado_sem_item_ativo(base, fechado)
    linha, = decisoes_linhas([a], res)
    assert _campos(linha) == CAMPOS_3014
    assert decisao_texto(linha) == (
        "3014 · 03/02/2025 · Crédito 500,00  →  fora da composição"
    )
    assert linha["indice"] == 0
    assert linha["erro"] == res.erros_alocacao[0].mensagem

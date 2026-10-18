"""Contagem de sugestoes nas duas triagens.

A sugestao tem que ser visivel ANTES de o conferente abrir a caixinha do item:
na triagem do balde (quanto do balde ja vem proposto) e na triagem do lote
(qual conta fecha rapido). Contagem pura -- nao muda nada no core.
"""
from app.apresentacao import triagem_linhas
from app.materialidade import frase_sugestoes
from core.modelo import (Achado, Conta, CriterioSugestao, DestinoAlocacao,
                         ItemRevisao, MotivoRevisao, Nivel, ResultadoConferencia,
                         Sugestao)
from tests.helpers import lanc

SUGESTAO = Sugestao(destino=DestinoAlocacao.LINHA_ABERTA, alvo="810108",
                    criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO)


def _item(com_sugestao=False, lote="1"):
    return ItemRevisao(lancamentos=[lanc("h", numero=lote, debito="10.00")],
                       motivo=MotivoRevisao.SEM_VINCULO, identificador=lote,
                       sugestao=SUGESTAO if com_sugestao else None)


# --- triagem DENTRO do balde --------------------------------------------------

def test_frase_diz_quantos_itens_ja_vem_propostos():
    balde = [_item(True, "1"), _item(True, "2"), _item(False, "3")]
    assert frase_sugestoes(balde) == ("2 dos 3 itens têm destino sugerido "
                                      "pelo motor")


def test_frase_no_singular_quando_e_um_so():
    assert frase_sugestoes([_item(True), _item(False, "2")]) == (
        "1 dos 2 itens tem destino sugerido pelo motor")


def test_sem_sugestao_nenhuma_a_frase_nao_aparece():
    """Linha a mais que diz 'zero' e ruido: a triagem so fala quando ha o que
    dizer (mesma regra de frase_materialidade)."""
    assert frase_sugestoes([_item(), _item(False, "2")]) is None


def test_balde_vazio_nao_tem_frase():
    assert frase_sugestoes([]) is None


# --- triagem do LOTE ----------------------------------------------------------

def _res(balde):
    return ResultadoConferencia(
        conta=Conta(codigo="7000", classificacao="1", nome="F"),
        balde=balde,
        achados=[Achado(nivel=Nivel.OK, codigo="self_check_composicao",
                        mensagem="ok")])


def test_coluna_do_lote_conta_as_sugestoes_da_conta():
    """O conferente varre a triagem e ve onde o trabalho ja vem mastigado."""
    (linha,) = triagem_linhas([("r.xls", [_res([_item(True), _item(True, "2"),
                                                _item(False, "3")])], None)])
    assert linha["Itens sem destino"] == "3"
    assert linha["Sugeridos"] == "2"


def test_conta_sem_sugestao_mostra_travessao_nao_zero():
    """Coluna homogenea de texto, no mesmo padrao das outras (Gap, Achados):
    ausencia e travessao, nao um zero que compete com o olho."""
    (linha,) = triagem_linhas([("r.xls", [_res([_item()])], None)])
    assert linha["Sugeridos"] == "—"


def test_arquivo_que_falhou_na_leitura_continua_com_travessao():
    (linha,) = triagem_linhas([("r.xls", None, "arquivo ilegivel")])
    assert linha["Sugeridos"] == "—"

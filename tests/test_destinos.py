"""Opcoes do seletor "Alocar em...".

APRESENTACAO: ordena e rotula o que o contador ve. Nao decide nada — quem
valida destino e o core (core/alocacao.py). Ordem pensada pra quem procura:
casamento exato de valor no topo, depois proximidade, depois data.
"""
from datetime import date
from decimal import Decimal

from app.destinos import indice_sugerido, opcoes_de_alocacao
from core.modelo import (ALVO_ANTERIOR, ComposicaoItem, CriterioSugestao,
                         DestinoAlocacao, Origem, Sugestao)

D = Decimal


def _item(nf, aberto, dia=10, origem=Origem.COMPRA_PERIODO, compra=None):
    return ComposicaoItem(
        nf_numero=nf, origem=origem,
        valor_compra=D(compra if compra is not None else aberto),
        total_pago=D("0.00"), total_retido=D("0.00"),
        saldo_aberto=D(aberto),
        data_compra=date(2026, 1, dia) if origem is not Origem.SALDO_ANTERIOR else None)


def _linhas(opcoes):
    return [o for o in opcoes if o.destino is DestinoAlocacao.LINHA_ABERTA]


def test_casamento_exato_de_valor_vem_no_topo():
    opcoes = opcoes_de_alocacao(
        [_item("111", "5000.00"), _item("222", "300.00"), _item("333", "900.00")],
        D("300.00"))
    assert [o.alvo for o in _linhas(opcoes)] == ["222", "333", "111"]


def test_empate_de_proximidade_desempata_pela_mais_antiga():
    opcoes = opcoes_de_alocacao(
        [_item("NOVA", "400.00", dia=20), _item("ANTIGA", "400.00", dia=5)],
        D("400.00"))
    assert [o.alvo for o in _linhas(opcoes)] == ["ANTIGA", "NOVA"]


def test_rotulo_traz_saldo_em_aberto_e_data():
    (opcao,) = _linhas(opcoes_de_alocacao([_item("860006", "348000.00", dia=25)],
                                          D("348400.00")))
    assert "860006" in opcao.rotulo
    assert "348.000,00" in opcao.rotulo
    assert "25/01/2026" in opcao.rotulo


def test_saldo_anterior_participa_da_ordenacao_como_linha_aberta():
    """Pra efeito de decisao, o saldo anterior nao detalhado e mais uma linha
    aberta — e num caso medido e o destino certo."""
    opcoes = opcoes_de_alocacao(
        [_item("111", "18000.00"), _item("(anterior)", "8423.38",
                                        origem=Origem.SALDO_ANTERIOR)],
        D("8400.00"))
    primeira = _linhas(opcoes)[0]
    assert primeira.alvo == "(anterior)"
    assert "não detalhado" in primeira.rotulo
    assert "8.423,38" in primeira.rotulo


def test_linha_quitada_nao_aparece():
    opcoes = opcoes_de_alocacao([_item("QUITADA", "0.00", compra="500.00"),
                                 _item("NEGATIVA", "-20.00", compra="500.00"),
                                 _item("ABERTA", "500.00")], D("100.00"))
    assert [o.alvo for o in _linhas(opcoes)] == ["ABERTA"]


def test_linha_criada_na_sessao_se_identifica_no_rotulo():
    (opcao,) = _linhas(opcoes_de_alocacao(
        [_item("NF 999", "250.00", origem=Origem.ALOCACAO_MANUAL)], D("100.00")))
    assert "criada nesta sessão" in opcao.rotulo


def test_as_duas_opcoes_especiais_vem_por_ultimo_e_pedem_rotulo():
    opcoes = opcoes_de_alocacao([_item("111", "500.00")], D("100.00"))
    nova, fora = opcoes[-2], opcoes[-1]
    assert nova.destino is DestinoAlocacao.COMPRA_NOVA
    assert nova.pede_rotulo and not nova.rotulo_obrigatorio
    assert fora.destino is DestinoAlocacao.FORA_DA_COMPOSICAO
    assert fora.pede_rotulo and fora.rotulo_obrigatorio
    assert nova.alvo == "" and fora.alvo == ""


def test_sem_linha_aberta_restam_so_as_especiais():
    opcoes = opcoes_de_alocacao([], D("100.00"))
    assert [o.destino for o in opcoes] == [DestinoAlocacao.COMPRA_NOVA,
                                           DestinoAlocacao.FORA_DA_COMPOSICAO]


def test_proximidade_usa_a_quantia_do_item_com_qualquer_sinal():
    """Item de CREDITO (liquido negativo) procura linha do mesmo TAMANHO —
    senao um credito de 250,00 ficaria a 500,00 de distancia de um saldo de
    250,00 e a ordem sairia invertida."""
    opcoes = opcoes_de_alocacao([_item("LONGE", "5000.00"),
                                 _item("PERTO", "250.00")], D("-250.00"))
    assert [o.alvo for o in _linhas(opcoes)] == ["PERTO", "LONGE"]


# === pre-selecao da sugestao =================================================
# A sugestao e MARCADA e pre-selecionada onde ja estava. A ordem NAO muda: ela
# frequentemente nao e a linha mais proxima (ex.: pagamento de 881,83
# sugerido pra NF com 1.734,26 em aberto), e reordenar brigaria com a razao de
# ser da ordem atual -- quem procura a mao procura por valor.

def _sugestao(alvo, destino=DestinoAlocacao.LINHA_ABERTA):
    return Sugestao(destino=destino, alvo=alvo,
                    criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO)


def test_sugestao_marca_a_opcao_correspondente():
    opcoes = opcoes_de_alocacao([_item("111", "500.00"), _item("222", "900.00")],
                                D("500.00"), _sugestao("222"))
    marcadas = [o.alvo for o in opcoes if o.sugerida]
    assert marcadas == ["222"]


def test_sem_sugestao_nenhuma_opcao_vem_marcada():
    opcoes = opcoes_de_alocacao([_item("111", "500.00")], D("500.00"))
    assert not any(o.sugerida for o in opcoes)
    assert indice_sugerido(opcoes) is None


def test_indice_sugerido_aponta_pra_posicao_na_lista_ORDENADA():
    """O index do selectbox e posicional: tem que ser calculado sobre a lista
    ja ordenada, senao a tela pre-seleciona a linha errada."""
    opcoes = opcoes_de_alocacao(
        [_item("LONGE", "9000.00"), _item("PERTO", "500.00")],
        D("500.00"), _sugestao("LONGE"))
    assert [o.alvo for o in _linhas(opcoes)] == ["PERTO", "LONGE"]
    assert opcoes[indice_sugerido(opcoes)].alvo == "LONGE"


def test_a_ordem_nao_muda_por_causa_da_sugestao():
    itens = [_item("111", "5000.00"), _item("222", "300.00")]
    sem = [o.rotulo for o in opcoes_de_alocacao(itens, D("300.00"))]
    com = [o.alvo for o in opcoes_de_alocacao(itens, D("300.00"),
                                              _sugestao("111"))]
    assert com[:2] == ["222", "111"]
    assert len(sem) == len(com) + 0


def test_sugestao_pra_linha_que_nao_esta_na_lista_nao_preseleciona_nada():
    """Blindagem: a sugestao foi calculada sobre o estado do motor, e a lista
    so' traz linhas ABERTAS. Se a linha sumiu (outra alocacao a quitou), o
    seletor volta a ficar em branco -- nunca IndexError, nunca a errada."""
    opcoes = opcoes_de_alocacao([_item("111", "500.00")], D("500.00"),
                                _sugestao("SUMIU"))
    assert not any(o.sugerida for o in opcoes)
    assert indice_sugerido(opcoes) is None


def test_sugestao_pro_saldo_anterior_marca_a_linha_anterior():
    opcoes = opcoes_de_alocacao(
        [_item("111", "500.00"), _item(ALVO_ANTERIOR, "800.00",
                                       origem=Origem.SALDO_ANTERIOR)],
        D("800.00"), _sugestao(ALVO_ANTERIOR))
    assert opcoes[indice_sugerido(opcoes)].alvo == ALVO_ANTERIOR


def test_rotulo_da_opcao_sugerida_se_identifica_no_dropdown():
    """O rotulo e a chave do seletor: aberto o dropdown, a proposta do motor
    tem que se distinguir das outras linhas."""
    opcoes = opcoes_de_alocacao([_item("111", "500.00"), _item("222", "900.00")],
                                D("500.00"), _sugestao("222"))
    (sugerida,) = [o for o in opcoes if o.sugerida]
    outras = [o.rotulo for o in _linhas(opcoes) if not o.sugerida]
    assert sugerida.rotulo != f"NF 222 · em aberto 900,00 · emitida 10/01/2026"
    assert all("sugerid" not in r for r in outras)

"""Fluxo de ALOCACAO MANUAL na tela, via AppTest.

Roda app/main.py de verdade, sem browser: escolhe destino, aplica, confere que
a composicao mudou, e desfaz. A fixture e a SINTETICA (tem balde; o golden
fecha sozinho e nao tem o que alocar).

O que este arquivo protege e a FIACAO: estado por arquivo+conta, callback de
on_click, key estavel por item, e o caminho tela -> motor -> tela. A regra de
alocacao em si e testada no core (tests/test_alocacao_manual.py).
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.helpers import identidade_das_linhas

MAIN = Path(__file__).parent.parent / "app" / "main.py"
SINTETICA = Path(__file__).parent / "fixtures" / "sintetica_integra.xls"
MIME = "application/vnd.ms-excel"


def _tela():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sintetica_integra.xls", SINTETICA.read_bytes(), MIME)).run()
    return at


@pytest.fixture(scope="module")
def tela():
    return _tela()


def _placar(at):
    """Os TRES numeros do topo, na ordem em que a tela os poe."""
    return [m.value for m in at.metric]


def _linha_de_trabalho(at):
    """A linha pequena abaixo do placar: itens em revisao (+ decididos)."""
    return next(str(c.value) for c in at.caption if "em revisão" in str(c.value))


def _caixinhas_do_balde(at):
    """Os expanders do BALDE (um por item), pela key propria ("cx::"). A
    ponte e o periodo zerado tambem viraram expanders e nao sao caixinha de
    decisao -- filtrar pela key e nao por exclusao de rotulo."""
    return [e for e in at.expander if "cx::" in e.proto.id]


def _itens_em_revisao(at):
    return _linha_de_trabalho(at)


def test_placar_segue_o_fluxo_mental_do_contador(tela):
    """O contador COMPOE ate bater com o Dominio. Os rotulos dizem o alvo,
    onde ele esta e o que falta -- 'Composicao / Dominio (a pagar) / Delta' nao
    dizia nenhuma das tres coisas. A contagem de itens sai do placar e vira
    linha pequena: como metrica ela truncava ('0 em revisao · 5 d...')."""
    assert len(tela.exception) == 0
    rotulos = [m.label for m in tela.metric]
    # a sintetica tem balde MISTO (D 3.400,00 / C 500,00). Antes:
    # "Falta alocar" com o liquido 2.900,00. Depois: os debitos no placar e o
    # credito na linha pequena -- nunca liquido
    assert rotulos == ["Saldo Domínio", "Total das notas em aberto",
                       "Débitos sem destino"]
    assert "crédito sem destino R\\$ 500,00" in _linha_de_trabalho(tela)
    assert all(m.value.startswith("R$ ") for m in tela.metric)
    assert "em revisão" in _linha_de_trabalho(tela)


def test_tela_abre_com_controle_por_item(tela):
    assert len(tela.exception) == 0
    # um seletor por item do balde, todos com as duas opcoes especiais
    assert len(tela.selectbox) == len(_caixinhas_do_balde(tela))
    # AppTest devolve as opcoes ja passadas pelo format_func (texto)
    rotulos = tela.selectbox[0].options
    assert rotulos[-2] == "— compra em aberto nova"
    assert rotulos[-1] == "— não pertence à composição"


def test_caixinhas_do_balde_comecam_fechadas(tela):
    """Decisao de campo de quem confere: REVERTE o default aberto de antes. Com o
    balde inteiro aberto a pagina vira uma parede; o rotulo ja traz valor,
    data, motivo e o inicio do historico — o bastante pra escolher qual abrir.
    (Antes abria porque a tabela HTML acima repetia tudo; sem ela, o rotulo e'
    a varredura.)"""
    caixinhas = _caixinhas_do_balde(tela)
    assert caixinhas
    assert all(e.proto.expanded is False for e in caixinhas)


def test_balde_nao_repete_a_tabela_html(tela):
    """A mesma informacao aparecia duas vezes: tabela HTML em cima, caixinhas
    embaixo. Fica so' a caixinha (que tem historico integral E o seletor)."""
    assert not any("tabela-balde" in str(m.value) for m in tela.markdown)


def test_aplicar_alocacao_move_o_item_e_mexe_no_placar():
    at = _tela()
    antes_itens = _itens_em_revisao(at)
    antes_delta = _placar(at)[2]              # "Falta alocar"

    # primeira opcao do primeiro item = a linha aberta mais proxima em valor
    at.selectbox[0].select_index(0).run()
    aplicar = next(b for b in at.button if b.label == "Aplicar")
    aplicar.click().run()

    assert len(at.exception) == 0
    assert _itens_em_revisao(at) != antes_itens          # o balde encolheu
    assert _placar(at)[2] != antes_delta                 # e o delta andou
    assert any("Decisões desta sessão" in h.value for h in at.markdown)


def test_desfazer_devolve_o_item_ao_balde():
    at = _tela()
    antes_itens = _itens_em_revisao(at)
    at.selectbox[0].select_index(0).run()
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert _itens_em_revisao(at) != antes_itens

    next(b for b in at.button if b.label == "Desfazer").click().run()
    assert len(at.exception) == 0
    assert _itens_em_revisao(at) == antes_itens          # voltou ao estado inicial
    assert not any("Decisões desta sessão" in h.value for h in at.markdown)


def test_nao_pertence_sem_justificativa_mostra_o_erro_do_core():
    """A tela nao valida: monta a alocacao e o motor recusa. O erro aparece na
    linha da decisao, onde esta o botao de desfazer."""
    at = _tela()
    ultima = len(at.selectbox[0].options) - 1           # "nao pertence"
    at.selectbox[0].select_index(ultima).run()
    next(b for b in at.button if b.label == "Aplicar").click().run()

    assert len(at.exception) == 0
    textos = " ".join(str(m.value) for m in at.markdown)
    # regra de tela: o texto mostra FATO, nunca instrucao
    assert "falta a justificativa de por que este lançamento" in textos
    assert any(b.label == "Desfazer" for b in at.button)


def test_estado_e_por_arquivo_e_conta():
    at = _tela()
    at.selectbox[0].select_index(0).run()
    next(b for b in at.button if b.label == "Aplicar").click().run()
    chaves = [k for k in at.session_state.filtered_state if k.startswith("aloc::")]
    assert len(chaves) == 1
    assert chaves[0].startswith("aloc::sintetica_integra.xls::")
    assert chaves[0].endswith("::7777")                 # codigo da conta sintetica


# === sugestao pre-selecionada na tela ========================================
# O motor nao produz sugestao nenhuma (REGRAS vazia), entao estes
# testes injetam uma regra falsa em core.sugestao.REGRAS: o que se testa aqui e
# a FIACAO da tela (pre-selecao, evidencia visivel, carimbo no clique), nao o
# criterio.

@pytest.fixture
def tela_com_sugestao(monkeypatch):
    """Sugere a PRIMEIRA linha aberta da composicao pra todo item do balde."""
    from core.modelo import CriterioSugestao, DestinoAlocacao, Sugestao

    def regra_falsa(item, ctx):
        abertas = [nf for nf in ctx.nfs
                   if nf.data_compra is not None and nf.saldo_aberto > 0]
        if not abertas:
            return None
        return Sugestao(destino=DestinoAlocacao.LINHA_ABERTA,
                        alvo=abertas[0].numero,
                        criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO,
                        evidencia={})

    monkeypatch.setattr("core.sugestao.REGRAS", (regra_falsa,))
    return _tela()


def _alocacoes(at):
    chave = next(k for k in at.session_state.filtered_state
                 if k.startswith("aloc::"))
    return at.session_state[chave]


def test_seletor_ja_vem_com_a_sugestao_escolhida(tela_com_sugestao):
    """O ganho na tela: o contador confere uma proposta em vez de
    escolher entre N linhas."""
    seletor = tela_com_sugestao.selectbox[0]
    assert seletor.value is not None
    assert "sugerida" in seletor.value


def test_sem_sugestao_o_seletor_continua_em_branco(tela):
    """Regressao: item sem proposta nao ganha escolha por default —
    pre-selecionar sem motivo seria o motor chutando pela tela."""
    assert tela.selectbox[0].value is None


def test_evidencia_da_sugestao_aparece_na_caixinha(tela_com_sugestao):
    """A regra falsa nao traz evidencia, entao a frase cai no FALLBACK — e o
    fallback tambem tem que chegar a tela, com o destino nomeado. Frase pela
    metade ou caixinha muda seriam o pior resultado possivel."""
    at = tela_com_sugestao
    alvo = at.selectbox[0].value.split("·")[1].strip()      # "NF 1001 ..."
    numero = alvo.split()[1]
    legendas = [str(c.value) for c in at.caption]
    assert any("destino provável" in c and numero in c for c in legendas)


def test_frase_da_sugestao_aparece_no_painel_de_triagem(tela_com_sugestao):
    """Visivel ANTES de abrir a caixinha: a triagem do balde diz quanto do
    trabalho ja vem proposto."""
    legendas = [str(c.value) for c in tela_com_sugestao.caption]
    assert any("destino sugerido pelo motor" in c for c in legendas)


def test_aceitar_a_sugestao_carimba_o_criterio(tela_com_sugestao):
    from core.modelo import CriterioSugestao

    at = tela_com_sugestao
    next(b for b in at.button if b.label == "Aplicar").click().run()
    (alocacao,) = _alocacoes(at)
    assert alocacao.criterio_sugerido is CriterioSugestao.SERIE_X_VALOR_DECLARADO


def test_escolher_outro_destino_nao_carimba_nada(tela_com_sugestao):
    """Origem so se declara quando existe: o contador que recusa a proposta e
    escolhe outra linha nao pode aparecer no relatorio como tendo aceitado."""
    at = tela_com_sugestao
    ultima = len(at.selectbox[0].options) - 1           # "nao pertence"
    at.selectbox[0].select_index(ultima).run()
    at.text_input[0].set_value("não e desta conta").run()
    next(b for b in at.button if b.label == "Aplicar").click().run()
    (alocacao,) = _alocacoes(at)
    assert alocacao.criterio_sugerido is None


# === o valor alocado chega a TABELA da tela ==================================

def _linha_da_nf(at, nf):
    df = at.dataframe[0].value                # a composicao e o 1o dataframe
    # NF negativa ganha marca na celula; com alerta de
    # juros, a marca e' "(possivel juros)"
    return df[df["NF"].isin([nf, f"{nf} (pago a maior)",
                             f"{nf} (possível juros)"])].iloc[0]


def test_alocar_reflete_na_coluna_alocado_a_mao_da_tela():
    """Regressao de um bug de campo: o contador aloca e a TABELA mostra o
    valor — na coluna propria, com "Total pago" intacto (nao se mistura)
    e a ultima quitacao andando pra data do lancamento alocado."""
    at = _tela()
    antes = _linha_da_nf(at, "1111")
    assert antes["Alocado à mão"] == "0,00"
    assert antes["Total pago"] == "1.200,00"
    assert antes["Última quitação"] == "01/04/2024"

    at.selectbox[0].select_index(0).run()          # lote 3013 (3.000,00) -> NF 1111
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0
    depois = _linha_da_nf(at, "1111")
    assert depois["NF"] == "1111 (possível juros)"     # -1.100,00
    assert depois["Alocado à mão"] == "3.000,00"
    assert depois["Total pago"] == "1.200,00"
    assert depois["EM ABERTO"] == "-1.100,00"
    assert depois["Última quitação"] == "15/01/2025"


def test_tabela_da_tela_fecha_a_identidade_em_toda_linha_antes_e_depois_de_alocar():
    """O invariante que faltou, na superficie onde o contador olha: a
    retencao da NF 3333 (150,00) e a baixa do anterior (10.000,00) fecham a
    linha ANTES; o alocado na NF 1111 fecha DEPOIS, inclusive negativa."""
    at = _tela()
    assert _linha_da_nf(at, "3333")["Retido"] == "150,00"
    identidade_das_linhas(at.dataframe[0].value.to_dict("records"))

    at.selectbox[0].select_index(0).run()
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0
    assert _linha_da_nf(at, "1111")["EM ABERTO"] == "-1.100,00"
    identidade_das_linhas(at.dataframe[0].value.to_dict("records"))


# === a foto completa numa tabela SO' =========================================

def test_quitadas_entram_na_tabela_da_composicao_ordenadas_por_idade(tela):
    """Decisao de campo (REVERTE a secao propria das quitadas): uma tabela so',
    com as quitadas em EM ABERTO 0,00 e a ordenacao unica por idade."""
    assert not any("NFs quitadas" in e.label for e in tela.expander)
    # as quitadas ficam atras do toggle -- liga pra ver a foto completa
    next(t for t in tela.toggle
         if t.label.startswith("Mostrar notas quitadas")).set_value(True).run()
    df = tela.dataframe[0].value
    # a linha "(transferencia lote 3015)" entra na tabela pela
    # idade (303 dias), entre 5555 e 6666 -- o credito de 250,00 da
    # transferencia de saldos deixou de ser "nao reconhecido" e virou linha
    # da composicao (decisao do contador).
    assert list(df["NF"]) == ["1111", "2222", "3333", "4444", "5555",
                              "(transferência lote 3015)", "6666",
                              "(saldo anterior)"]
    # so' idade: 670, 609, 517, 456, 456, 303, 233
    abertos = dict(zip(df["NF"], df["EM ABERTO"]))
    assert [abertos[nf] for nf in ("2222", "4444", "5555")] == ["0,00"] * 3
    assert abertos["1111"] == "1.900,00"
    identidade_das_linhas(df.to_dict("records"))       # em TODA linha, tambem nas quitadas


# === a expansao de cada caixinha sobrevive ao rerun ==========================
# Bug de campo: alocar um item reabria as caixinhas dos outros. Causa: o
# `expanded` era CONSTANTE e o expander nao tinha key, entao o estado so' vivia
# no browser, preso a identidade (rotulo + posicao) -- alocar encolhe a lista,
# as posicoes deslizam e todas remontam com o default.

def _caixinha_por_valor(at, valor):
    return next(e for e in _caixinhas_do_balde(at) if valor in e.label)


def _chave_da_caixinha(at, valor):
    """A key do expander. `Block.key` do AppTest devolve sempre None (limitacao
    pra containers), mas o proto.id e' "$$ID-<hash>-<key do usuario>"."""
    return _caixinha_por_valor(at, valor).proto.id.split("-", 2)[2]


def test_cada_caixinha_do_balde_tem_key_estavel_por_item():
    at = _tela()
    chaves = [e.proto.id.split("-", 2)[2] for e in _caixinhas_do_balde(at)]
    assert all(k.startswith("cx::") for k in chaves), \
        "caixinha sem key própria: o estado não sobrevive ao rerun"
    assert len(set(chaves)) == len(chaves)
    # a key nao pode depender da POSICAO: rerodar a mesma tela devolve as mesmas
    assert [e.proto.id.split("-", 2)[2] for e in _caixinhas_do_balde(_tela())] == chaves
    # e cada uma tem estado PROPRIO no servidor -- e ele que sobrevive ao rerun
    assert set(chaves) <= set(at.session_state.filtered_state)


def test_expansao_sobrevive_ao_rerun():
    at = _tela()
    chave = _chave_da_caixinha(at, "500,00")
    padrao = _caixinha_por_valor(at, "500,00").proto.expanded
    at.session_state[chave] = not padrao
    at.run()
    assert _caixinha_por_valor(at, "500,00").proto.expanded is (not padrao)


def test_alocar_um_item_nao_muda_a_key_dos_outros():
    """A MECANICA do bug: a identidade da caixinha nao pode depender da POSICAO.
    Alocar remove um item e desloca os demais -- se a identidade deslizar junto,
    o navegador remonta tudo com o default e a expansao do usuario se perde.
    Presa ao item_id, ela nao desliza.

    O comportamento fim-a-fim (fechar uma caixinha, alocar outra item, a
    fechada continuar fechada) NAO da pra afirmar aqui: o AppTest nao carrega
    estado de CONTAINER entre interacoes de widget (o valor volta ao default no
    rerun seguinte, com ou sem o bug). A prova e' o A/B no navegador -- e o que
    este teste tranca e a causa raiz: sem key propria e
    estavel, ele cai."""
    at = _tela()
    antes = {e.label: e.proto.id.split("-", 2)[2] for e in _caixinhas_do_balde(at)}
    rotulo_alocado = _caixinha_por_valor(at, "3.000,00").label

    at.selectbox[0].select_index(0).run()          # aloca o item de 3.000,00
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0

    depois = {e.label: e.proto.id.split("-", 2)[2] for e in _caixinhas_do_balde(at)}
    assert rotulo_alocado not in depois            # o item alocado saiu
    assert depois == {r: k for r, k in antes.items() if r != rotulo_alocado}

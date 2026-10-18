"""Testes da NOTA ADITIVA. So sintetico; falhas INJETADAS (declaradas).

Nada aqui le arquivo real ou banco."""
import io
import logging
import zipfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.main import _downloads_do_lote, _EntradaLote
from app.pipeline import processar_excel
from relatorio import zip_relatorios

RAIZ = Path(__file__).parent.parent
MAIN = RAIZ / "app" / "main.py"
FIXTURES = RAIZ / "tests" / "fixtures"
INTEGRA = (FIXTURES / "sintetica_integra.xls").read_bytes()
GOLDEN = (FIXTURES / "golden_sintetico.xls").read_bytes()
MIME = "application/vnd.ms-excel"

# as 4 frases PROVISORIAS (a escolha final e decisao de produto; o codigo segue com estas)
def frase_arquivo(nome):      # nome ja escapado como o markdown da tela o devolve
    return (f"Erro inesperado gerando a planilha de '{nome}'; a planilha deste arquivo "
            f"não foi gerada. A conferência dele está na tela.")


FRASE_CLIQUE = "Erro inesperado ao executar a ação; a ação não foi concluída."
FRASE_TELA = "Erro inesperado ao montar a tela; a tela não foi desenhada por inteiro."


def _injeta_falha_de_planilha(monkeypatch, *, nome_com="FALHA"):
    """A tela importa de `relatorio` a CADA execucao: trocar o atributo ali, ANTES de rodar, injeta
    a falha."""
    import relatorio
    import relatorio.excel
    original = relatorio.gerar_excel

    def gerar_excel_falho(resultados, dados, nome_origem, *a, **k):
        if nome_com in nome_origem:
            raise RuntimeError("falha injetada")
        return original(resultados, dados, nome_origem, *a, **k)

    for modulo in (relatorio, relatorio.excel):
        monkeypatch.setattr(modulo, "gerar_excel", gerar_excel_falho)


def _injeta_falha_de_planilha_na_camada_pura(monkeypatch, *, nome_com="FALHA"):
    """Fora do AppTest o modulo `app.main` ja foi importado: ele guarda o NOME `gerar_excel`; trocar
    `relatorio.gerar_excel` ali nao alcanca. A troca tem de ser em `app.main`."""
    import app.main as principal
    original = principal.gerar_excel

    def gerar_excel_falho(resultados, dados, nome_origem, *a, **k):
        if nome_com in nome_origem:
            raise RuntimeError("falha injetada")
        return original(resultados, dados, nome_origem, *a, **k)

    monkeypatch.setattr(principal, "gerar_excel", gerar_excel_falho)


def _tela_com(arquivos):
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([(n, b, MIME) for n, b in arquivos]).run()
    return at


def _titulos_de_conta(at):
    return [s.value for s in at.subheader if "Conta " in s.value]


def _botoes(at):
    return [b.label for b in at.sidebar.get("download_button")]


LOTE = [("boa_1.xls", INTEGRA), ("exporta_FALHA.xls", INTEGRA), ("golden_sintetico.xls", GOLDEN)]


# --- modo arquivo (AppTest: fiacao e texto) -------------------------------------------------------

def test_lote_com_uma_planilha_que_falha_mostra_as_3_contas_e_as_2_boas(monkeypatch):
    _injeta_falha_de_planilha(monkeypatch)
    at = _tela_com(LOTE)
    assert len(at.exception) == 0
    assert len(_titulos_de_conta(at)) == 3
    rotulos = _botoes(at)
    assert len(rotulos) == 3 and "ZIP" in rotulos[0]          # ZIP + 2
    assert not any("FALHA" in r for r in rotulos)
    assert len(at.sidebar.error) == 0                      # o fato fica na PAGINA, nao na barra
    assert [e.value for e in at.main.error] == [frase_arquivo("exporta\\_FALHA.xls")]


def test_arquivo_unico_que_falha_mostra_a_conta_e_o_fato(monkeypatch):
    _injeta_falha_de_planilha(monkeypatch)
    at = _tela_com([("exporta_FALHA.xls", INTEGRA)])
    assert len(at.exception) == 0
    assert len(_titulos_de_conta(at)) == 1
    assert _botoes(at) == []
    assert len(at.sidebar.error) == 0                      # o fato fica na PAGINA, nao na barra
    assert [e.value for e in at.main.error] == [frase_arquivo("exporta\\_FALHA.xls")]


def test_lote_em_que_todas_falham_mostra_3_fatos_e_nenhum_botao(monkeypatch):
    _injeta_falha_de_planilha(monkeypatch, nome_com="")        # "" esta em qualquer nome
    at = _tela_com(LOTE)
    assert len(at.exception) == 0
    assert len(_titulos_de_conta(at)) == 3
    assert _botoes(at) == []
    assert len(at.sidebar.error) == 0
    assert [e.value for e in at.main.error] == [
        frase_arquivo("boa\\_1.xls"), frase_arquivo("exporta\\_FALHA.xls"),
        frase_arquivo("golden\\_sintetico.xls")]


def test_controle_sem_falha_nao_ganha_texto_novo():
    at = _tela_com([("boa_1.xls", INTEGRA), ("golden_sintetico.xls", GOLDEN)])
    assert len(at.exception) == 0 and len(at.error) == 0
    assert len(_titulos_de_conta(at)) == 2
    assert len(_botoes(at)) == 3


def test_o_registro_do_servidor_tem_o_hash_do_arquivo_e_o_tipo_nunca_o_nome(monkeypatch, caplog):
    import hashlib
    _injeta_falha_de_planilha(monkeypatch)
    with caplog.at_level(logging.ERROR):
        _tela_com(LOTE)
    achados = [r for r in caplog.records if "planilha do arquivo" in r.getMessage()]
    assert len(achados) == 1 and achados[0].exc_info is None                 # sem excecao anexada
    assert achados[0].getMessage().splitlines()[0] == (
        f"erro inesperado gerando a planilha do arquivo {hashlib.sha256(INTEGRA).hexdigest()[:8]}")
    assert "RuntimeError em " in achados[0].getMessage()
    assert "exporta_FALHA" not in caplog.text and "falha injetada" not in caplog.text


# --- camada pura (o que o AppTest nao entrega: os bytes) -----------------------------------------

def _entrada(nome, dados):
    caminho = FIXTURES / ("golden_sintetico.xls" if dados is GOLDEN else "sintetica_integra.xls")
    return _EntradaLote(nome=nome, resultados=processar_excel(caminho).resultados, dados=dados)


def test_downloads_segue_com_os_bons_devolve_as_falhas_e_o_zip_reabre(monkeypatch):
    from openpyxl import load_workbook
    _injeta_falha_de_planilha_na_camada_pura(monkeypatch)
    lote = [_entrada(n, b) for n, b in LOTE]
    falhas = []
    downloads = _downloads_do_lote(lote, falhas)
    assert [d[0] for d in downloads] == ["boa_1.xls", "golden_sintetico.xls"]
    assert falhas == [lote[1]]
    pacote = zip_relatorios([(nome, dados) for _, nome, dados in downloads])
    with zipfile.ZipFile(io.BytesIO(pacote)) as z:
        assert z.namelist() == ["boa_1_conferencia.xlsx", "golden_sintetico_conferencia.xlsx"]
        for nome in z.namelist():
            assert load_workbook(io.BytesIO(z.read(nome))).sheetnames       # a planilha REABRE


def test_chamada_sem_o_argumento_novo_segue_devolvendo_so_a_lista(monkeypatch):
    _injeta_falha_de_planilha_na_camada_pura(monkeypatch)
    lote = [_entrada(n, b) for n, b in LOTE]
    assert [d[0] for d in _downloads_do_lote(lote)] == ["boa_1.xls", "golden_sintetico.xls"]


# --- erro ao montar a tela ------------------------------------------------------------------------

def test_erro_no_desenho_da_conta_mostra_so_a_frase_em_portugues(monkeypatch):
    import app.apresentacao as ap

    def titulo_que_falha(*a, **k):
        raise RuntimeError("falha injetada no desenho")

    monkeypatch.setattr(ap, "titulo_conta", titulo_que_falha)
    at = _tela_com([("boa_1.xls", INTEGRA)])
    assert len(at.exception) == 0
    assert [e.value for e in at.error] == [FRASE_TELA]
    assert not any("This app has encountered" in str(m.value) for m in at.markdown)


def test_excecao_do_fragmento_ja_mostrada_pelo_streamlit_nao_vira_uma_2a_caixa(monkeypatch):
    """FragmentHandledException e `Exception` e o Streamlit ja desenhou o erro do fragmento: o `try` do corpo a deixa
    passar. Sem a clausula `except FragmentHandledException: raise`, o corpo desenharia a frase dele POR CIMA (caixa dupla)."""
    from streamlit.errors import FragmentHandledException

    import app.apresentacao as ap

    def titulo_que_ja_foi_mostrado(*a, **k):
        raise FragmentHandledException(RuntimeError("ja mostrado pelo Streamlit"))

    monkeypatch.setattr(ap, "titulo_conta", titulo_que_ja_foi_mostrado)
    at = _tela_com([("boa_1.xls", INTEGRA)])
    assert [e.value for e in at.error] == []                        # nenhuma caixa nossa por cima
    assert len(at.exception) == 0


def test_erro_no_clique_de_aplicar_mostra_so_a_frase_do_clique_e_a_tela_inteira(monkeypatch):
    import core.modelo as modelo

    class AlocacaoQueFalha:
        def __init__(self, *a, **k):
            raise RuntimeError("falha injetada no clique")

    # a troca vale DEPOIS de o botao existir? NAO: o clique usa os nomes do script que desenhou o botao.
    # Por isso a troca fica ANTES da 1a execucao: nada chama AlocacaoManual ate o clique.
    monkeypatch.setattr(modelo, "AlocacaoManual", AlocacaoQueFalha)
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([("sintetica_integra.xls", INTEGRA, MIME)]).run()
    antes = _titulos_de_conta(at)
    at.selectbox[0].select_index(0).run()
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0
    assert [e.value for e in at.error] == [FRASE_CLIQUE]
    assert [e.value for x in at.expander for e in x.error] == [FRASE_CLIQUE]    # A1: NO ITEM do clique, nao no topo
    assert _titulos_de_conta(at) == antes and len(antes) == 1       # a tela esta INTEIRA
    assert not any("Decisões desta sessão" in str(m.value) for m in at.markdown)   # a decisao NAO entrou
    at.run()                                                         # a frase vale por 1 execucao
    assert len(at.error) == 0


def test_os_2_cliques_fora_do_corpo_estao_protegidos():
    import app.main as m
    for funcao in (m._aplicar_alocacao, m._desfazer_alocacao):
        assert hasattr(funcao, "__wrapped__"), funcao.__name__


def test_controle_de_fluxo_do_streamlit_nao_e_engolido():
    """st.rerun()/st.stop() levantam excecao de CONTROLE (BaseException); o 'except Exception' do corpo nao a pega."""
    from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException
    assert not issubclass(RerunException, Exception) and not issubclass(StopException, Exception)


# --- regra de tela ------------------------------------------------------------------------------------

def test_as_3_frases_passam_na_regra_de_tela_e_o_verificador_acusa_um_controle():
    from tests.test_regra_de_tela import _violacoes
    assert _violacoes(["Confira o arquivo e fale com a Fulana Ficticia."])          # controle POSITIVO
    for frase in (frase_arquivo("x.xls"), FRASE_CLIQUE, FRASE_TELA):
        assert _violacoes([frase]) == [], frase


# --- a frase da acao fica NO LUGAR da acao; cada uma das 4 acoes tem teste de comportamento ---

def _plana(no):
    """Elementos da tela na ORDEM em que aparecem (AppTest: arvore de blocos achatada)."""
    for _, filho in sorted(no.children.items()):
        if hasattr(filho, "children") and filho.children:
            yield from _plana(filho)
        else:
            yield filho


def test_desfazer_com_erro_mostra_a_frase_logo_abaixo_do_titulo_das_decisoes(monkeypatch):
    from app.main import AlocacaoManual  # noqa: F401 (o app ja importa)
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([("sintetica_integra.xls", INTEGRA, MIME)]).run()
    at.selectbox[0].select_index(0).run()
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert any("Decisões desta sessão (1)" in m.value for m in at.markdown)
    chave = next(k for k in at.session_state.filtered_state if "::" in k and isinstance(at.session_state[k], list)
                 and at.session_state[k] and type(at.session_state[k][0]).__name__ == "AlocacaoManual")
    at.session_state[chave] = tuple(at.session_state[chave])               # `del` numa tupla levanta TypeError no clique
    next(b for b in at.button if b.label == "Desfazer").click().run()
    assert len(at.exception) == 0
    assert [e.value for e in at.error] == [FRASE_CLIQUE]
    ordem = [(getattr(x, "type", ""), str(getattr(x, "value", ""))) for x in _plana(at.main)]
    i_titulo = next(i for i, (t, v) in enumerate(ordem) if "Decisões desta sessão (1)" in v)
    assert ordem[i_titulo + 1] == ("error", FRASE_CLIQUE)                  # LOGO ABAIXO do titulo das decisoes


def test_se_o_ponto_da_acao_nao_foi_desenhado_a_frase_cai_no_topo_uma_vez(monkeypatch):
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.session_state["erro::acao"] = "item::que-nao-existe"
    at.run()
    assert [e.value for e in at.error] == [FRASE_CLIQUE]
    at.run()
    assert len(at.error) == 0                                              # vale por 1 execucao

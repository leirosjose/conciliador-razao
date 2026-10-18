"""NOME NUNCA VIRA LINK. O escape da tela (markdown_seguro) devolve o texto ja sem gatilho de link:
um caractere sem largura (U+2060) depois de '<', '&', 'http(s):' antes de '//', 'www' antes de '.' e '@'. Vale pra todo
texto que varia e vai pra markdown: titulo da conta, nome do cliente no resultado e na legenda "Fonte", caixas de erro,
titulo e legenda do item sem destino, e o rotulo do botao de baixar. So dado sintetico e fonte de teste."""
import io
import re
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

from app.apresentacao import markdown_seguro, sem_link_automatico
from tests.test_parser_limpeza import _xls

RAIZ = Path(__file__).resolve().parents[1]
MAIN = RAIZ / "app" / "main.py"
MIME = "application/vnd.ms-excel"
WJ = "\u2060"
# gatilho de link SEM o caractere logo depois: e o que nao pode sobrar num texto que o markdown desenha
GATILHO_VIVO = re.compile(r"(?i)(<|&|https?:(?=//)|www(?=\.)|@)(?!\u2060)")


def _vivos(textos):
    return [t for t in textos if GATILHO_VIVO.search(t)]


# --- o escape (RED 1 a 3 da spec) ---------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("www.exemplo.invalid", f"www{WJ}.exemplo.invalid"),
    ("WWW.FICTICIA.INVALID LTDA", f"WWW{WJ}.FICTICIA.INVALID LTDA"),
    ("contato@exemplo.invalid", f"contato@{WJ}exemplo.invalid"),
    ("http://exemplo.invalid/a_b", f"http:{WJ}//exemplo.invalid/a\\_b"),
    ("AT&T <FILIAL>", f"AT&{WJ}T <{WJ}FILIAL>"),
    ("www&period;exemplo.invalid", f"www&{WJ}period;exemplo.invalid"),
])
def test_markdown_seguro_ja_devolve_o_texto_sem_gatilho_de_link(texto, esperado):
    assert markdown_seguro(texto) == esperado


def test_titulo_da_conta_no_lote_pelo_arquivo_e_pelo_fornecedor():
    from app.apresentacao import titulo_conta
    from core.modelo import Conta

    conta = Conta(codigo="7777", classificacao="",
                  nome="WWW.FICTICIA.INVALID & CIA contato@ficticia.invalid LTDA")
    assert _vivos([titulo_conta(conta, arquivo="www.ficticia.invalid&contato@ficticia.invalid (1).xls")]) == []
    assert _vivos([titulo_conta(conta)]) == []


# --- 1 caractere por gatilho: quem ja chama a protecao antes do escape nao ganha 2 --------------------------------

@pytest.mark.parametrize("texto,n", [("www.exemplo.invalid", 1), ("https://exemplo.invalid", 1), ("a&b <c> d@e", 3)])
def test_guarda_um_caractere_por_gatilho(texto, n):
    # GUARDA (passa antes e depois): so distingue a mudanca feita com e sem o "nao repete o caractere"
    assert markdown_seguro(sem_link_automatico(texto)).count(WJ) == n


@pytest.mark.parametrize("texto", ["a&b", "<c>", "d@e.invalid", "www.x.invalid", "http://x.invalid", "A&B <C> www.d.invalid e@f"])
def test_a_protecao_aplicada_duas_vezes_da_o_mesmo_que_uma(texto):
    uma = sem_link_automatico(texto)
    assert sem_link_automatico(uma) == uma
    assert markdown_seguro(markdown_seguro(texto)).count(WJ) == uma.count(WJ)


@pytest.mark.parametrize("texto,esperado", [
    ("FORNECEDOR FICTICIO LTDA", "FORNECEDOR FICTICIO LTDA"), ("R$ 10,00 e R$ 20,00", "R\\$ 10,00 e R\\$ 20,00"),
    ("nome_com_sublinhado", "nome\\_com\\_sublinhado"), ("qz17.com.br", "qz17.com.br"), ("ftp://x.invalid", "ftp://x.invalid"),
    ("C:\\FICTICIA\\arq.xlsx", "C:\\\\FICTICIA\\\\arq.xlsx"), ("", "")])
def test_guarda_texto_sem_gatilho_sai_como_saia(texto, esperado):
    assert markdown_seguro(texto) == esperado


# --- a tela (AppTest): os lugares onde o nome aparece, os 4 da medicao e os 2 da auditoria ------------------------

def _hostil(tmp_path, arquivo="h.xls", **campos):
    """Bytes de um .xls sintetico; `campos` sao os do auxiliar (nome = o do fornecedor, numero, cta...)."""
    return _xls(tmp_path / arquivo, **campos).read_bytes()


def _tela(monkeypatch, arquivos):
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([(n, d, MIME) for n, d in arquivos]).run()
    assert not at.exception
    return at


def _desenhados_em_markdown(at):
    """Os textos que o markdown desenha e que levam dado do arquivo ou da fonte. Ficam de fora os blocos de HTML
    proprio (triagem, historico, estilos), que nao passam pelo markdown, e as opcoes de seletor (texto puro)."""
    botoes = [b.label for b in at.get("download_button")] + [b.label for b in at.button]
    marc = [m.value for m in at.markdown if not re.search(r"<(table|blockquote|style|div|i|span)\b", m.value)]
    return (marc + [x.value for x in at.caption] + [e.label for e in at.expander] + [s.value for s in at.subheader]
            + [e.value for e in at.error] + [w.value for w in at.warning] + [s.label for s in at.selectbox] + botoes)


def test_rotulo_do_botao_de_baixar_sem_amp_escrito(monkeypatch, tmp_path):
    at = _tela(monkeypatch, [("a&b.xlsx", _hostil(tmp_path))])
    rotulos = [b.label for b in at.sidebar.get("download_button")]
    assert rotulos == [f"📊 Baixar Excel — a&{WJ}b.xlsx → a&{WJ}b\\_conferencia.xlsx"]


def test_titulo_da_conta_no_lote_item_sem_destino_e_caixa_de_erro(monkeypatch, tmp_path):
    dados = _hostil(tmp_path, nome="WWW.FICTICIA.INVALID LTDA", numero="www.num9.invalid", cta="x@cta9.invalid")
    at = _tela(monkeypatch, [("www.exemplo.invalid.xls", dados), ("contato@exemplo.invalid (1).xls", dados),
                             ("nao@excel.invalid (1).xls", b"nao e excel")])
    assert sorted(s.value for s in at.subheader) == sorted([
        f"📄 www{WJ}.exemplo.invalid.xls — Conta 7001 — WWW{WJ}.FICTICIA.INVALID LTDA",
        f"📄 contato@{WJ}exemplo.invalid (1).xls — Conta 7001 — WWW{WJ}.FICTICIA.INVALID LTDA"])
    assert [e.value for e in at.error] == [f"'nao@{WJ}excel.invalid (1).xls' não abriu nem após tentativa de reparo."]
    # o titulo FECHADO do item sem destino (numero) e a legenda de dentro (numero e contrapartida)
    assert [e.label for e in at.expander if "cx::" in e.proto.id] == [
        f"Número www{WJ}.num9.invalid · 02/03/2025 · Débito R\\$ 10,00 · Histórico não reconhecido"] * 2
    assert [x.value for x in at.caption if "Contrapartida" in x.value] == [
        f"Número www{WJ}.num9.invalid · Débito · Contrapartida (Cta.C.Part.): x@{WJ}cta9.invalid"] * 2
    assert _vivos(_desenhados_em_markdown(at)) == []


def test_caixa_de_erro_da_planilha_do_arquivo(monkeypatch, tmp_path):
    from tests.test_app_falha_parcial_de_planilha import _injeta_falha_de_planilha, frase_arquivo
    _injeta_falha_de_planilha(monkeypatch)
    at = _tela(monkeypatch, [("www.FALHA.invalid.xls", _hostil(tmp_path)), ("boa.xls", _hostil(tmp_path))])
    assert [e.value for e in at.main.error] == [markdown_seguro(frase_arquivo("www.FALHA.invalid.xls"))]
    assert f"'www{WJ}.FALHA.invalid.xls'" in at.main.error[0].value
    assert _vivos(_desenhados_em_markdown(at)) == []


def _botoes_de_baixar(monkeypatch):
    """Lista viva de (rotulo, nome entregue, bytes) de cada botao de baixar que a tela desenha."""
    import streamlit
    vistos, original = [], streamlit.download_button

    def gravador(label, *a, **k):
        vistos.append((label, k.get("file_name"), k.get("data")))
        return original(label, *a, **k)
    monkeypatch.setattr(streamlit, "download_button", gravador)
    return vistos


def test_guarda_o_caractere_nao_vaza_pra_chave_nem_pro_nome_entregue(monkeypatch, tmp_path):
    # GUARDA (ja e assim): chave de widget, estado da sessao e o nome do arquivo entregue ficam crus
    dados = _hostil(tmp_path, nome="SILVA & CIA FICTICIA <LTDA>", numero="www.num9.invalid")
    entregues = _botoes_de_baixar(monkeypatch)
    at = _tela(monkeypatch, [("a&b www.exemplo.invalid.xls", dados), ("c@d.invalid (1).xls", dados)])
    chaves = [str(k) for k in at.session_state.filtered_state] + [str(getattr(w, "key", "")) for w in list(at.button) + list(at.selectbox) + list(at.get("download_button"))]
    assert chaves and [k for k in chaves if WJ in k] == []
    assert any("a&b www.exemplo.invalid.xls" in k for k in chaves)
    opcoes = [o for s in at.selectbox for o in s.options]
    assert [o for o in opcoes if WJ in o] == []
    # o nome entregue (file_name do botao) e o do arquivo, sem escape e sem o caractere
    assert [nome for _, nome, _ in entregues if nome != "conferencias.zip"] == [
        "a&b www.exemplo.invalid_conferencia.xlsx", "c@d.invalid (1)_conferencia.xlsx"]


# --- texto DIGITADO (ou colado) num campo da tela: o caractere sem largura sai na entrada -------------------------

def _xls_dois_creditos(caminho, nome="SILVA & CIA FICTICIA LTDA"):
    """.xls sintetico: 1 compra de 1.000,00 e 2 creditos sem padrao conhecido (50,00 e 60,00), que ficam sem destino."""
    import xlwt

    from tests.fixtures.gerar_sinteticas import CNPJ, COL_SALDO, EMPRESA, PERIODO, _serial
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Razão")
    ws.write(0, 0, "Empresa:"); ws.write(0, 2, EMPRESA)
    ws.write(1, 0, "C.N.P.J.:"); ws.write(1, 2, CNPJ)
    ws.write(2, 0, "Período:"); ws.write(2, 2, PERIODO)
    ws.write(3, 0, "RAZÃO")
    for coluna, titulo in ((0, "Data"), (1, "Número"), (2, "Histórico"), (7, "Cta.C.Part."), (8, "Débito"),
                           (9, "Crédito"), (COL_SALDO, "Saldo-Exercício")):
        ws.write(5, coluna, titulo)
    ws.write(6, 0, "Conta:"); ws.write(6, 1, 7001.0); ws.write(6, 2, "2.01.01.001.00"); ws.write(6, 5, nome)
    ws.write(7, 2, "SALDO ANTERIOR"); ws.write(7, COL_SALDO, 0.0)
    for i, (numero, historico, valor, saldo) in enumerate([
            (5000.0, "Vr. compras conf. 1234 FORNECEDOR FICTICIO LTDA", 1000.0, -1000.0),
            (5001.0, "TARIFA ADMINISTRATIVA SEM PADRAO CONHECIDO A", 50.0, -1050.0),
            (5002.0, "TARIFA ADMINISTRATIVA SEM PADRAO CONHECIDO B", 60.0, -1110.0)]):
        ws.write(8 + i, 0, _serial(date(2025, 3, 1 + i))); ws.write(8 + i, 1, numero); ws.write(8 + i, 2, historico)
        ws.write(8 + i, 7, 38.0); ws.write(8 + i, 9, valor); ws.write(8 + i, COL_SALDO, saldo)
    ws.write(12, 4, "Total da conta:"); ws.write(12, 8, 0.0); ws.write(12, 9, 1110.0)
    wb.save(str(caminho))
    return caminho


def _decidir(at, indice, trecho_do_destino, texto):
    """No item sem destino de numero `indice`: escolhe o destino, cola `texto` no campo e aplica."""
    seletor = [s for s in at.selectbox if s.label == "Alocar em"][indice]
    seletor.set_value(next(o for o in seletor.options if trecho_do_destino in o.lower())).run()
    widget = seletor.key.removeprefix("destino::")
    at.text_input(key=f"rotulo::{widget}").set_value(texto).run()
    at.button(key=f"aplicar::{widget}").click().run()
    assert not at.exception
    return at


def test_texto_digitado_so_tira_o_caractere_sem_largura():
    from app.apresentacao import texto_digitado
    assert texto_digitado(markdown_seguro("SILVA & CIA <B> c@d www.e.invalid http://f.invalid")) == (
        "SILVA & CIA <B> c@d www.e.invalid http://f.invalid")
    assert texto_digitado(f" a{WJ}{WJ} b ") == " a b "             # so o caractere sai: espaco e ponta ficam
    assert texto_digitado("a\u200b b") == "a\u200b b"              # so o U+2060
    assert texto_digitado("") == "" == texto_digitado(None)


def test_justificativa_colada_da_tela_chega_sem_o_caractere_a_planilha(monkeypatch, tmp_path):
    entregues = _botoes_de_baixar(monkeypatch)
    at = _tela(monkeypatch, [("r.xls", _xls_dois_creditos(tmp_path / "r.xls").read_bytes())])
    colado = next(s.value for s in at.subheader if "SILVA" in s.value)     # o titulo, como a tela desenha
    assert colado == f"Conta 7001 — SILVA &{WJ} CIA FICTICIA LTDA"
    _decidir(at, 0, "não pertence", colado)
    planilha = openpyxl.load_workbook(io.BytesIO(entregues[-1][2]))
    textos = [c.value for aba in planilha for linha in aba for c in linha if isinstance(c.value, str)]
    assert [t for t in textos if WJ in t] == []
    assert "Conta 7001 — SILVA & CIA FICTICIA LTDA" in textos                       # a justificativa, numa celula so dela


def test_nome_de_linha_colado_igual_a_um_que_existe_e_recusado(monkeypatch, tmp_path):
    def recusas(segundo_nome):
        at = _tela(monkeypatch, [("r.xls", _xls_dois_creditos(tmp_path / "r.xls").read_bytes())])
        _decidir(at, 0, "nova", "SILVA & CIA")
        _decidir(at, 0, "nova", segundo_nome)                              # o que era o 2o item agora e o 1o
        return ([m.value.replace(WJ, "") for m in at.markdown if "já é de uma linha desta conta" in m.value],
                len([s for s in at.selectbox if s.label == "Alocar em"]))
    hoje = ([":red[o nome SILVA & CIA já é de uma linha desta conta; a alocação ficou sem efeito]"], 1)
    assert recusas("SILVA & CIA") == hoje                                  # digitado: recusa, 1 item segue sem destino
    assert recusas(f"SILVA &{WJ} CIA") == hoje                             # colado da tela: a mesma recusa


def test_todo_campo_de_texto_do_produto_entrega_o_valor_pela_mesma_funcao():
    """Inventario estatico de app/: cada campo de texto (text_input, text_area, chat_input) ou e lido direto por
    texto_digitado(...), ou e lido depois pela chave, e a leitura dessa chave passa por texto_digitado(...)."""
    import ast
    campos, lidos_pela_chave, fora = [], [], []
    for arquivo in sorted((RAIZ / "app").glob("*.py")):
        fonte_do_arquivo = arquivo.read_text(encoding="utf-8")
        arvore = ast.parse(fonte_do_arquivo)
        pais = {filho: pai for pai in ast.walk(arvore) for filho in ast.iter_child_nodes(pai)}
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)):
                continue
            if isinstance(no.func, ast.Name) or no.func.attr not in ("text_input", "text_area", "chat_input"):
                continue
            chave = next((ast.get_source_segment(fonte_do_arquivo, k.value) for k in no.keywords if k.arg == "key"), "")
            campos.append(f"{arquivo.name}: {chave}")
            pai = pais[no]
            if isinstance(pai, ast.Call) and getattr(pai.func, "id", "") == "texto_digitado":
                continue                                                    # lido direto pela funcao
            prefixo = re.match(r'f?"([a-z_:]+::)', chave)
            if isinstance(pai, ast.Expr) and prefixo:
                lidos_pela_chave.append(prefixo.group(1))
                leituras = [ast.get_source_segment(fonte_do_arquivo, c) for c in ast.walk(arvore)
                            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "texto_digitado"]
                if any("session_state" in l and prefixo.group(1) in l for l in leituras):
                    continue
            fora.append(f"{arquivo.name}:{no.lineno}")
    assert campos == ['main.py: f"rotulo::{widget}"']
    assert lidos_pela_chave == ["rotulo::"] and fora == []

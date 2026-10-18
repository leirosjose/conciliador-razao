"""TRAVA: todo texto que a tela entrega a um
elemento que RENDERIZA markdown passa por markdown_seguro.

Dois "R$" na mesma frase viram par de delimitadores LaTeX no Streamlit: o
trecho entre eles sai em fonte de formula e os cifroes somem. A frase do topo
("Saldo de R$ X = ... e R$ Y de saldo anterior") quebrou assim num caso,
e o AppTest nao pegou -- ele ve a FONTE markdown, nao o render.

Regra, checada no AST de app/main.py: o primeiro argumento de
success/info/warning/error/markdown/caption/expander/toggle/subheader/title e'
  - constante de texto sem "$" cru, ou
  - markdown_seguro(...), ou
  - md_ja_escapado(...) -- marcador explicito de texto escapado por partes, ou
  - f-string cujos valores sao todos markdown_seguro(...)/len(...) e cujas
    partes fixas nao tem "$" cru, ou
  - soma / `or` / ternario de pecas que obedecem a regra.
"""
import ast
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).parent.parent
MAIN = RAIZ / "app" / "main.py"

RENDERIZAM_MARKDOWN = {"success", "info", "warning", "error", "markdown",
                       "caption", "expander", "toggle", "subheader", "title"}
ESCAPADORES = {"markdown_seguro", "md_ja_escapado"}
_CIFRAO_CRU = re.compile(r"(?<!\\)\$")


def _nome_chamado(no) -> str | None:
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Name):
        return no.func.id
    return None


def _seguro(no) -> bool:
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return not _CIFRAO_CRU.search(no.value)
    if _nome_chamado(no) in ESCAPADORES:
        return True
    if isinstance(no, ast.JoinedStr):
        for parte in no.values:
            if isinstance(parte, ast.Constant):
                if _CIFRAO_CRU.search(parte.value):
                    return False
            elif isinstance(parte, ast.FormattedValue):
                if _nome_chamado(parte.value) not in ESCAPADORES | {"len"}:
                    return False
        return True
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
        return _seguro(no.left) and _seguro(no.right)
    if isinstance(no, ast.BoolOp):
        return all(_seguro(v) for v in no.values)
    if isinstance(no, ast.IfExp):
        return _seguro(no.body) and _seguro(no.orelse)
    return False


def _violacoes(fonte: str) -> list[str]:
    achados = []
    for no in ast.walk(ast.parse(fonte)):
        if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and no.func.attr in RENDERIZAM_MARKDOWN and no.args
                and not _seguro(no.args[0])):
            achados.append(f"linha {no.lineno}: "
                           f"{ast.unparse(no.args[0])[:90]}")
    return achados


def test_todo_texto_que_vira_markdown_na_tela_passa_por_markdown_seguro():
    assert _violacoes(MAIN.read_text()) == []


def test_a_trava_pega_o_que_deve_pegar():
    ruim = '''
st.success(resposta_conferido(res))
st.caption(f"Ressalva: R$ {valor} fora")
st.markdown(det["motivo"])
st.expander(titulo_ponte(res))
'''
    bom = '''
st.success(markdown_seguro(resposta_conferido(res)))
st.caption(markdown_seguro(f"Ressalva: R$ {valor} fora"))
st.markdown(md_ja_escapado(det["motivo"]))
st.markdown(f"#### Decisoes ({len(linhas)})")
st.markdown("**Historico:**\\n> " + markdown_seguro(h))
st.caption("Nenhuma.")
'''
    assert len(_violacoes(ruim)) == 4
    assert _violacoes(bom) == []


def test_resposta_com_dois_valores_chega_escapada_na_tela(monkeypatch):
    """O caso exato: duas notas + saldo anterior, dois "R$"."""
    from datetime import date
    from decimal import Decimal as D
    from tests.fixtures import gerar_sinteticas as G
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("-700.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", [
        (date(2025, 1, 2), 4001, "Vr. compras conf. 5001 FORNECEDOR FICTICIO LTDA",
         None, D("1000.00")),
        (date(2025, 1, 9), 4002, "Vr. compras conf. 5002 FORNECEDOR FICTICIO LTDA",
         None, D("500.00")),
    ])
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("dois_valores.xlsx", G.montar_xlsx(),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert len(at.exception) == 0
    (verde,) = at.success
    assert verde.value.count("R\\$") == 2
    assert not _CIFRAO_CRU.search(verde.value)


# === linha em branco no TEXTO nao quebra a tabela HTML ==========================
# A tabela de leitura e' HTML dentro de markdown. Linha em branco encerra o
# bloco HTML (CommonMark, tipo 6) e o resto da celula sai como markdown VIVO:
# imagem externa carregada, negrito. Os dois sinks passam por _celula_html:
# o historico do periodo zerado e a triagem do lote (nome da conta / arquivo).

import pytest  # noqa: E402

from app.apresentacao import tabela_html, tabela_triagem  # noqa: E402

_LINHA_EM_BRANCO = re.compile(r"\n[ \t]*\n")   # linha so de espaco tambem e' em branco
_INJECAO = "![rastreio](http://exemplo.invalid/p.png) **NEGRITO**"
_QUEBRAS = ["\n\n", "\r\n\r\n", "\r\r", "\n \n", "  ", "\x0b\x0b"]


@pytest.mark.parametrize("quebra", _QUEBRAS)
def test_historico_com_linha_em_branco_nao_quebra_a_tabela_html(quebra):
    historico = f"Pago conf. FORNECEDOR{quebra}{_INJECAO}"
    html = tabela_html([{"Lote": "5002", "Valor": "1.000,00", "Histórico": historico}])
    assert not _LINHA_EM_BRANCO.search(html)
    assert not any(c in html for c in "\r \x0b")
    assert f"Pago conf. FORNECEDOR {_INJECAO}" in re.sub(r"\s+", " ", html)


@pytest.mark.parametrize("quebra", _QUEBRAS)
def test_nome_com_linha_em_branco_nao_quebra_a_triagem_do_lote(quebra):
    nome = f"FORNECEDOR{quebra}{_INJECAO}"
    html = tabela_triagem([{
        "Arquivo": f"arq{quebra}{_INJECAO}.xls", "Fornecedor": nome,
        "Falta alocar": "0,00", "Itens sem destino": 0, "Sugeridos": 0,
        "Achados": "nenhum"}])
    assert not _LINHA_EM_BRANCO.search(html)
    assert not any(c in html for c in "\r \x0b")


def test_texto_de_uma_linha_so_sai_igual_a_antes():
    """CONTROLE: sem quebra de linha o escape e o cifrao seguem como estavam."""
    html = tabela_html([{"Lote": "1", "Valor": "1,00",
                         "Histórico": "R$ 10 & <b>x</b> R$ 20"}])
    assert "R&#36; 10 &amp; &lt;b&gt;x&lt;/b&gt; R&#36; 20" in html


# === o historico citado e' TEXTO LITERAL, nao markdown vivo ======================
# Em markdown o Streamlit faz titulo ("# ..."), link automatico (URL, www.,
# e-mail), emoji (":x:") e icone a partir do dado do arquivo; nenhum escape
# desliga o link automatico. A citacao do "Historico integral" e' HTML escapado.

_HOSTIL = ("# TARIFA https://exemplo.invalid/pagar www.exemplo.invalid "
           "fulano@exemplo.invalid :x: :material/home: $1$ e $2$ <b>B</b> fim")


def _historicos_citados(monkeypatch, historicos):
    """Sobe um razao sintetico com um debito sem destino por historico e devolve
    o markdown (fonte + flag de HTML) das citacoes "Historico integral"."""
    from datetime import date
    from decimal import Decimal as D
    from tests.fixtures import gerar_sinteticas as G
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("0.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", [
        (date(2025, 1, 2), 4001, "Vr. compras conf. 5001 FORNECEDOR FICTICIO LTDA",
         None, D("1000.00"))] + [
        (date(2025, 1, 9 + i), 4002 + i, h, D("10.00"), None)
        for i, h in enumerate(historicos)])
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("citacao.xlsx", G.montar_xlsx(),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert len(at.exception) == 0
    return [m for m in at.markdown if "Histórico integral" in m.value]


def test_historico_citado_chega_como_html_escapado_e_nao_como_markdown(monkeypatch):
    citacoes = _historicos_citados(monkeypatch, [_HOSTIL, "TARIFA BANCARIA DOC 123 fim"])
    assert len(citacoes) == 2
    hostil, comum = citacoes
    assert hostil.value == (
        "**Histórico integral:**\n<blockquote># TARIFA https://exemplo.invalid/pagar "
        "www.exemplo.invalid fulano@exemplo.invalid :x: :material/home: "
        "&#36;1&#36; e &#36;2&#36; &lt;b&gt;B&lt;/b&gt; fim</blockquote>")
    assert comum.value == ("**Histórico integral:**\n"
                           "<blockquote>TARIFA BANCARIA DOC 123 fim</blockquote>")
    assert "\n> " not in hostil.value          # nenhuma citacao markdown (que viraria titulo)
    assert hostil.proto.allow_html and comum.proto.allow_html   # sem a flag o HTML sairia como texto


def test_historico_citado_com_linha_em_branco_continua_um_bloco_so(monkeypatch):
    (citacao,) = _historicos_citados(
        monkeypatch, [f"Pago conf. FORNECEDOR\n\n{_INJECAO}"])
    assert not _LINHA_EM_BRANCO.search(citacao.value)
    assert re.sub(r"\s+", " ", citacao.value).endswith(
        f"Pago conf. FORNECEDOR {_INJECAO}</blockquote>")


def test_historico_html_e_texto_literal_com_a_mesma_celula_da_tabela_de_leitura():
    from app.apresentacao import _celula_html, historico_html
    texto = 'R$ 1 & <i>x</i>\n\n![a](http://exemplo.invalid/a.png)'
    assert historico_html(texto) == f"<blockquote>{_celula_html(texto)}</blockquote>"

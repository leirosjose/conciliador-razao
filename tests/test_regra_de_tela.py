"""REGRA DE TELA (premissa fixa): a tela, o Excel e as mensagens de
erro MOSTRAM FATOS. Nunca dao instrucao ao usuario nem citam pessoa.

Duas camadas, as mesmas regras (termos de instrucao + forma de citar pessoa):
  1. ESTATICA: todo literal de texto de app/, relatorio/, core/ e parser/
     (docstring e comentario nao contam: nao chegam ao usuario). Pega frase
     que nenhuma fixture renderiza hoje.
  2. RENDERIZADA: o que a tela e a planilha mostram de fato pra o golden, a
     sintetica do balde, um periodo zerado e um erro de alocacao.
Rotulos de CONTROLE da propria tela (botao, toggle) nao sao instrucao: ficam,
e a excecao e' explicita aqui embaixo.
"""
import ast
import io
import re
from pathlib import Path

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).parent.parent
MAIN = RAIZ / "app" / "main.py"
FIXTURES = Path(__file__).parent / "fixtures"

# imperativo / orientacao ao usuario, e o papel como destinatario
TERMOS_PROIBIDOS = [
    "puxe", "puxar", "confira", "conferir", "verifique", "verificar",
    "procure", "procurar", "consulte", "consultar", "fale com", "falar com",
    "chame", "chamar", "revise", "revisar", "desfaca", "escolha",
    "explique", "use", "confirme", "confirmar", "analisar", "classifique",
    "divida", "envie", "re-exporte", "tente", "reporte", "deve ser",
    "nada a fazer", "atencao", "indique", "reportar",
    "descrever", "selecione", "marque", "clique", "digite", "informe",
    "contador",
]
_PROIBIDO = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in TERMOS_PROIBIDOS) + r")\b",
    re.IGNORECASE)

# citar pessoa, sem lista de nomes: frase que ENCAMINHA a alguem ("fale com a ...",
# "pergunte ao ...", "peca a ...", "consulte o ...", "encaminhe para ...") ou que
# ATRIBUI a alguem com nome proprio ("segundo a Fulana", "Conforme o Beltrano"), em qualquer caixa.
# Vale pra qualquer nome: quem cita pessoa usa uma dessas formas. Documento ou sistema
# depois da locucao nao e' pessoa ("conforme o Excel exportado", "bate com o Dominio" sao fatos).
_ENCAMINHA = re.compile(
    r"\b(?:fale|falar|pergunte|perguntar|peca|pedir|consulte|consultar|encaminhe|encaminhar|"
    r"avise|avisar|ligue|ligar)\s+(?:com|a|ao|aos|as|o|os|para|pra)\b", re.IGNORECASE)
NAO_PESSOA = ("Dominio", "Excel", "Relatorio", "Planilha", "Razao", "Sistema", "Arquivo",
              "Extrato", "Balancete", "Lote", "Nota")
_ATRIBUI = re.compile(r"\b(?i:segundo|conforme|de acordo com)\s+(?i:o|a)\s+"
                      r"(?!(?:" + "|".join(NAO_PESSOA) + r")\b)[A-Z][a-z]+")

# rotulos de CONTROLE: botao/toggle/acao da propria tela -- nomeiam o que o
# controle faz, nao dizem ao usuario o que fazer
CONTROLES = {
    "Desfazer", "Aplicar", "Mostrar todas as linhas", "Escolher arquivos",
}
_CONTROLE_PREFIXOS = ("Mostrar notas quitadas", "Baixar Excel", "Baixar todos")


def _e_controle(texto: str) -> bool:
    return texto in CONTROLES or texto.startswith(_CONTROLE_PREFIXOS)


def _sem_acento(texto: str) -> str:
    """A tela ganhou acentuacao; a lista de termos e' sem acento -- compara
    as duas formas normalizadas, senao "Atenção" escaparia de "atencao"."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", texto)
                   if not unicodedata.combining(c))


def _proibido(texto: str) -> bool:
    t = _sem_acento(texto)
    return bool(_PROIBIDO.search(t) or _ENCAMINHA.search(t) or _ATRIBUI.search(t))


def _violacoes(textos):
    return sorted({t for t in textos
                   if t and not _e_controle(t) and _proibido(t)})


# --- 1. estatica ----------------------------------------------------------------

def _literais(arquivo: Path):
    arvore = ast.parse(arquivo.read_text())
    docstrings = {
        id(n.body[0].value) for n in ast.walk(arvore)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef))
        and n.body and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(arvore):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings):
            yield f"{arquivo.relative_to(RAIZ)}:{n.lineno}", n.value


@pytest.mark.parametrize("pasta", ["app", "relatorio", "core", "parser"])
def test_nenhum_literal_exibivel_da_instrucao_nem_cita_pessoa(pasta):
    achados = [f"{onde}: {texto!r}"
               for arquivo in sorted((RAIZ / pasta).glob("*.py"))
               for onde, texto in _literais(arquivo)
               if not _e_controle(texto) and _proibido(texto)
               # chave interna de widget, nao texto exibido
               and not texto.endswith("::")]
    assert achados == []


def _frases_de_alocacao() -> list[str]:
    """As frases de erro do core/alocacao.py como a tela as mostra: cada valor
    de `_MENSAGENS` com os campos {..} preenchidos. Le o dicionario na hora da
    chamada (e nao o texto do arquivo), entao pega tambem valor que nao seja
    literal no fonte."""
    from string import Formatter

    from core import alocacao
    frases = []
    for texto in alocacao._MENSAGENS.values():
        campos = {nome: "123" for _, nome, _, _ in Formatter().parse(texto)
                  if nome}
        frases.append(texto.format(**campos))
    return frases


def test_mensagens_de_erro_da_alocacao_so_mostram_fatos():
    """O dicionario `_MENSAGENS` do core (erro de
    alocacao recusada, mostrado na tela) tem trava propria, nao so' a
    varredura de literais."""
    frases = _frases_de_alocacao()
    assert len(frases) >= 9          # nao passa por vazio
    assert _violacoes(frases) == []


def test_frase_do_item_inexistente_so_mostra_fato():
    from app.apresentacao import decisao_texto

    frase = decisao_texto({"lote": "—", "data": "—", "lado": "—",
                           "valor": "—", "destino": "", "item_ausente": True})
    assert frase == "lançamento não encontrado nesta conferência"
    assert _violacoes([frase]) == []


def test_a_varredura_das_mensagens_da_alocacao_pega_instrucao_e_pessoa(
        monkeypatch):
    from core import alocacao
    monkeypatch.setitem(alocacao._MENSAGENS, "NF_QUITADA",
                        "NF {alvo} ja esta quitada; confira com a Fulana Ficticia")
    monkeypatch.setitem(alocacao._MENSAGENS, "ALVO_AUSENTE",
                        "escolha uma linha de destino")
    assert _violacoes(_frases_de_alocacao()) == [
        "NF 123 ja esta quitada; confira com a Fulana Ficticia",
        "escolha uma linha de destino"]


def test_a_lista_pega_o_que_deve_pegar():
    """Trava da propria trava: termo proibido em frase de verdade e' achado;
    fato e rotulo de controle passam."""
    assert _violacoes(["saldo anterior nao detalhado, puxar razao anterior",
                       "Confirmar com o cliente se houve desconto",
                       "fale com a Fulana Ficticia"]) == [
        "Confirmar com o cliente se houve desconto",
        "fale com a Fulana Ficticia",
        "saldo anterior nao detalhado, puxar razao anterior"]
    assert _violacoes(["Atenção: confira"]) == ["Atenção: confira"]   # com acento
    # opcao de lista suspensa tambem e' texto exibido; "descrever" e' ordem
    assert _violacoes(["Outro (descrever na coluna Observação)",
                       "Outro (detalhe na coluna Observação)"]) == [
        "Outro (descrever na coluna Observação)"]
    assert _violacoes(["Saldo anterior de R$ 700,00 sem detalhe de notas",
                       "Conferido. Saldo de R$ 4.260,09",
                       "Conferencia de Razao de Fornecedores",
                       "Desfazer", "Mostrar notas quitadas (4)"]) == []


def test_citar_pessoa_e_regra_generica_com_nomes_inventados():
    """A regra de pessoa nao depende de lista de nomes: encaminhar a alguem ou
    atribuir a alguem e' achado com qualquer nome (aqui, inventados); fato com o
    nome do sistema passa."""
    citam = ["fale com a Fulana Ficticia", "pergunte ao Beltrano Ficticio sobre o saldo",
             "peça à Ciclana Ficticia o extrato", "segundo a Fulana Ficticia, o saldo fecha",
             "conforme o Beltrano Ficticio, a nota foi paga",
             # no comeco da frase, com maiuscula
             "Segundo a Fulana Ficticia, o saldo fecha", "Conforme o Beltrano Ficticio, a nota foi paga",
             "De acordo com a Ciclana Ficticia, o saldo fecha"]
    assert _violacoes(citam) == sorted(citam)
    fatos = ["Composição fechada — bate com o Domínio ao centavo",
             "Saldo Domínio R$ 2.155,27", "de acordo com o Domínio, o saldo final e 0,00",
             # documento/sistema depois da locucao nao e pessoa
             "A composicao esta conforme o Excel exportado.", "segundo o Relatorio de Compras",
             "Conforme a Planilha de conferencia", "De acordo com o Sistema, o lote foi gravado"]
    assert _violacoes(fatos) == []


# --- 2. renderizada -------------------------------------------------------------

def _textos_da_tela(at) -> list[str]:
    textos = []
    for colecao in (at.markdown, at.caption, at.info, at.warning, at.error,
                    at.success, at.title, at.subheader):
        textos += [e.value for e in colecao]
    textos += [e.label for e in at.expander]
    textos += [t.label for t in at.toggle]
    textos += [b.label for b in at.button]
    for s in at.selectbox:
        textos += [s.label, s.placeholder or ""] + [str(o) for o in s.options]
    textos += [t.label for t in at.tabs]
    for campo in at.text_input:
        textos += [campo.label, campo.proto.placeholder or "", campo.proto.help or ""]
    textos += [d.label for d in at.date_input]
    textos += [m.label for m in at.metric]
    for s in at.multiselect:
        textos += [s.label, s.placeholder or ""] + [str(o) for o in s.options]
    for d in at.dataframe:
        df = d.value
        textos += [str(c) for c in df.columns]
        textos += [str(v) for v in df.astype(str).values.ravel()]
    return textos


def _subir(nome, dados, mime="application/vnd.ms-excel"):
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value((nome, dados, mime)).run()
    assert len(at.exception) == 0
    return at


def test_tela_do_golden_so_mostra_fatos():
    at = _subir("golden_sintetico.xls", (FIXTURES / "golden_sintetico.xls").read_bytes())
    assert _violacoes(_textos_da_tela(at)) == []


def test_tela_da_sintetica_com_balde_sugestao_e_erro_de_alocacao():
    """Balde (motivos, sugestoes, avisos) + a mensagem de ERRO do core de uma
    alocacao recusada (fora da composicao sem justificativa)."""
    at = _subir("sintetica_integra.xls",
                (FIXTURES / "sintetica_integra.xls").read_bytes())
    assert _violacoes(_textos_da_tela(at)) == []
    seletor = at.selectbox[0]
    seletor.select(seletor.options[-1]).run()        # "— nao pertence ..."
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0
    assert _violacoes(_textos_da_tela(at)) == []


def test_tela_do_periodo_zerado_que_bate_e_que_nao_bate(monkeypatch):
    from tests.test_app_corte import _xlsx_que_zera
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    at = _subir("zera.xlsx", _xlsx_que_zera(monkeypatch), xlsx)
    assert _violacoes(_textos_da_tela(at)) == []


def test_planilha_so_mostra_fatos(monkeypatch, tmp_path):
    from app.pipeline import processar_excel
    from relatorio.excel import gerar_excel
    from tests.test_app_corte import _xlsx_que_zera
    zera = tmp_path / "zera.xlsx"
    zera.write_bytes(_xlsx_que_zera(monkeypatch))
    textos = []
    for caminho in (FIXTURES / "golden_sintetico.xls",
                    FIXTURES / "sintetica_integra.xls", zera):
        dados = gerar_excel(processar_excel(caminho).resultados,
                            caminho.read_bytes(), caminho.name)
        ws = openpyxl.load_workbook(io.BytesIO(dados))["Conferência"]
        textos += [c.value for linha in ws.iter_rows() for c in linha
                   if isinstance(c.value, str)]
        # as opcoes da lista suspensa nao sao celula -- vivem na validacao
        for dv in ws.data_validations.dataValidation:
            textos += dv.formula1.strip('"').split(",")
    assert _violacoes(textos) == []


def test_cinco_termos_novos_sao_travados():
    frases = [f"{termo} uma opção" for termo in ("selecione", "marque", "clique", "digite", "informe")]
    assert _violacoes(frases) == sorted(frases)

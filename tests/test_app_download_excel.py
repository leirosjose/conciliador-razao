"""Exportacao EXCEL na tela: botao 'Baixar Excel' por arquivo
PROCESSADO + 'Baixar todos (ZIP)' quando ha 2+; quem falhou no parse (ou veio
sem conta) NAO gera planilha nem entra no ZIP — a triagem ja mostra o erro.

O AppTest de 1.58 nao expoe os BYTES do download (ficam no media manager);
o conteudo e' provado na camada pura (_downloads_do_lote + testes de
relatorio/); aqui a fiacao: quais botoes existem e com qual rotulo.
"""
import io
import zipfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.main import _EntradaLote, _downloads_do_lote
from app.pipeline import processar_excel
from relatorio import zip_relatorios

MAIN = Path(__file__).parent.parent / "app" / "main.py"
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden_sintetico.xls"


def _xls(nome):
    return (nome, (FIXTURES / nome).read_bytes(), "application/vnd.ms-excel")


def _botoes_download(at):
    # a exportacao vive na SIDEBAR ("Exportar"); a pagina
    # principal nao tem botao de download
    return list(at.sidebar.get("download_button"))


def _entrada_do_golden(nome="golden_sintetico.xls"):
    return _EntradaLote(nome=nome, resultados=processar_excel(GOLDEN).resultados,
                        dados=GOLDEN.read_bytes())


# --- camada pura: quem entra e quem fica fora ---------------------------------

def test_downloads_do_lote_so_dos_processados():
    lote = [
        _entrada_do_golden(),
        _EntradaLote(nome="quebrado.xls", erro="nao abriu"),
        _EntradaLote(nome="sem_conta.xlsx", resultados=[]),
    ]
    downloads = _downloads_do_lote(lote)
    assert [(d[0], d[1]) for d in downloads] == [("golden_sintetico.xls",
                                                  "golden_sintetico_conferencia.xlsx")]
    assert downloads[0][2].startswith(b"PK")          # container do .xlsx


def test_downloads_do_lote_sanitiza_o_nome_do_arquivo():
    lote = [_entrada_do_golden('raz?o*.xls')]
    assert _downloads_do_lote(lote)[0][1] == "raz_o__conferencia.xlsx"


def test_zip_leva_um_xlsx_por_arquivo_com_nome_sem_colisao():
    downloads = _downloads_do_lote([_entrada_do_golden(), _entrada_do_golden()])
    pacote = zip_relatorios([(nome, dados) for _, nome, dados in downloads])
    with zipfile.ZipFile(io.BytesIO(pacote)) as z:
        assert z.namelist() == ["golden_sintetico_conferencia.xlsx",
                                "golden_sintetico_conferencia_2.xlsx"]
        assert z.read(z.namelist()[0]).startswith(b"PK")


# --- fiacao na tela ------------------------------------------------------------

def test_upload_unico_tem_um_botao_excel_e_nenhum_zip():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([_xls("golden_sintetico.xls")]).run()
    assert len(at.exception) == 0
    botoes = _botoes_download(at)
    assert len(botoes) == 1
    assert "Baixar Excel" in botoes[0].label
    assert "golden\\_sintetico.xls" in botoes[0].label      # nome escapado no markdown
    assert "ZIP" not in botoes[0].label
    assert list(at.main.get("download_button")) == []   # principal LIMPA


def test_lote_tem_botao_por_processado_e_zip_sem_o_que_falhou():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([
        _xls("golden_sintetico.xls"),
        _xls("sintetica_adulterada.xls"),           # gate rejeita: fica FORA
        _xls("sintetica_integra.xls"),
    ]).run()
    assert len(at.exception) == 0
    rotulos = [b.label for b in _botoes_download(at)]
    assert len(rotulos) == 3                        # 2 planilhas + 1 ZIP
    assert sum("Baixar Excel" in r for r in rotulos) == 2
    assert "ZIP" in rotulos[0]                      # ZIP no TOPO da secao
    assert not any("adulterada" in r for r in rotulos)
    assert list(at.main.get("download_button")) == []


def test_botoes_seguem_a_ordem_da_triagem():
    """Problema primeiro, como na triagem: a corrompida (amarela) vem antes
    do golden (verde), independente da ordem do upload."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([
        _xls("golden_sintetico.xls"),                      # verde (upload primeiro)
        _xls("sintetica_corrompida.xls"),           # amarela
    ]).run()
    assert len(at.exception) == 0
    rotulos = [b.label for b in _botoes_download(at)]
    assert len(rotulos) == 3
    assert "ZIP" in rotulos[0]
    assert "corrompida" in rotulos[1]               # amarela primeiro
    assert "golden" in rotulos[2]

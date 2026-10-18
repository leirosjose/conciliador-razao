"""Nome entregue ASCII; nomes originais permanecem dentro da planilha."""
import zipfile
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from relatorio.nomes import nome_excel
from relatorio.pacote import zip_relatorios
from tests.test_app_pagina_cortada import _tela, xlsx_de_n_contas

# Os 14 casos medidos, incluindo família de cinco codepoints.
# NFD explícito: cedilha U+0327 e til U+0303, não dois literais NFC iguais.
CASOS = [
    ('razao simples.xlsx', 'razao simples_conferencia.xlsx'),
    ('Conciliação março.xlsx', 'Conciliacao marco_conferencia.xlsx'),
    ('ÁÉÍÓÚ ÀÈ ÂÊÔ ÃÕ Ç áéíóú àè âêô ãõ ç ü.xlsx',
     'AEIOU AE AEO AO C aeiou ae aeo ao c u_conferencia.xlsx'),
    ('1ª via nº 5 §2° ½.xlsx', '1a via no 5 _2_ 1_2_conferencia.xlsx'),
    ('ã.xlsx', 'a_conferencia.xlsx'),
    ('Concilia\u0063\u0327\u0061\u0303o NFD.xlsx', 'Conciliacao NFD_conferencia.xlsx'),
    ('São João – açaí.xlsx', 'Sao Joao _ acai_conferencia.xlsx'),
    ('a&b c@d www.e.invalid f&g.xlsx', 'a&b c@d www.e.invalid f&g_conferencia.xlsx'),
    ('razão № 5 ™ € “aspas”.xlsx', 'razao No 5 TM _ _aspas__conferencia.xlsx'),
    ('会計報告.xlsx', '_____conferencia.xlsx'),
    ('😀.xlsx', '__conferencia.xlsx'),
    ('relatório 😀 2025.xlsx', 'relatorio _ 2025_conferencia.xlsx'),
    ('—.xlsx', '__conferencia.xlsx'),
    ('Ærø ßtraße Łódź ñandú.xlsx', '_r_ _tra_e _odz nandu_conferencia.xlsx'),
    ('\U0001f468\u200d\U0001f469\u200d\U0001f467.xlsx', '______conferencia.xlsx'),
]


def test_nome_com_acento_fica_ascii():
    assert nome_excel('Conciliação março.xlsx') == 'Conciliacao marco_conferencia.xlsx'


def test_nfc_nfd_distintos_dao_o_mesmo_ascii():
    nfc, nfd = 'Raz\u00e3o.xls', 'Raza\u0303o.xls'
    assert nfc != nfd
    assert nome_excel(nfc) == nome_excel(nfd) == 'Razao_conferencia.xlsx'


def test_travessao_vira_sublinhado():
    assert nome_excel('São João – açaí.xlsx') == 'Sao Joao _ acai_conferencia.xlsx'


def test_compatibilidade_e_caractere_sem_ascii():
    assert nome_excel('会計.xlsx') == '___conferencia.xlsx'
    assert nome_excel('1ª via nº 5.xlsx') == '1a via no 5_conferencia.xlsx'


@pytest.mark.parametrize('origem,esperado', CASOS)
def test_quatorze_casos_explicitos(origem, esperado):
    assert nome_excel(origem) == esperado
    assert nome_excel(origem).isascii()


def test_zip_numera_so_os_membros_e_preserva_bytes():
    origens = ['razão.xlsx', 'razao.xlsx', 'RAZÃO.xlsx']
    nomes = [nome_excel(n) for n in origens]
    assert nomes == ['razao_conferencia.xlsx', 'razao_conferencia.xlsx', 'RAZAO_conferencia.xlsx']
    with zipfile.ZipFile(BytesIO(zip_relatorios(list(zip(nomes,[b'A',b'B',b'C']))))) as z:
        assert z.namelist() == ['razao_conferencia.xlsx','razao_conferencia_2.xlsx','RAZAO_conferencia_3.xlsx']
        assert [z.read(n) for n in z.namelist()] == [b'A',b'B',b'C']


def test_apptest_rotulo_e_download_do_lote():
    from app.main import _downloads_do_lote, _EntradaLote
    from app.pipeline import processar_excel
    at = _tela(('Conciliação março.xlsx', xlsx_de_n_contas(1)))
    assert len(at.exception) == 0
    assert at.get('download_button')[0].label.endswith('→ Conciliacao marco\\_conferencia.xlsx')
    fix = Path(__file__).parent/'fixtures/sintetica_integra.xls'
    entrada = _EntradaLote(nome='Conciliação março.xls', resultados=processar_excel(fix).resultados,
                           dados=fix.read_bytes(), chave='nomes')
    origem, nome, dados = _downloads_do_lote([entrada])[0]
    assert origem == 'Conciliação março.xls' and nome == 'Conciliacao marco_conferencia.xlsx'
    wb=openpyxl.load_workbook(BytesIO(dados))
    assert any('Conciliação março.xls' in c.value for ws in wb for row in ws for c in row if isinstance(c.value,str))


# R1: estas sete formas introduzem barra no NFKD. Antes de separar pasta
# perderiam o começo; depois da limpeza deixariam barra proibida.
@pytest.mark.parametrize('codigo,ascii_limpo', [
    ('\uff0f','_'), ('\uff3c','_'), ('\ufe68','_'), ('\u2100','a_c'),
    ('\u2101','a_s'), ('\u2105','c_o'), ('\u2106','c_u')])
def test_prefixo_acentuado_nao_se_perde_no_upload(codigo,ascii_limpo):
    assert nome_excel(f'Á{codigo}B.xlsx') == f'A{ascii_limpo}B_conferencia.xlsx'
    nome = nome_excel(f'Á{codigo}B.xlsx')
    assert not any(c in '<>:"/\\|?*' or ord(c)<32 for c in nome)


def test_decompor_antes_da_limpeza_e_depois_da_extensao():
    assert nome_excel('x＊y？.xlsx') == 'x_y__conferencia.xlsx'
    assert nome_excel('Á．xlsx') == 'A.xlsx_conferencia.xlsx'


@pytest.mark.parametrize('acento',['\u00b4','\u00a8','\u00af','\u00b8','\u02dc','\u0301'])
def test_acento_solto_cai_no_nome_padrao(acento):
    assert nome_excel(acento+'.xlsx') == 'razao_conferencia.xlsx'


def test_guarda_ascii_composto_sufixo_e_compatibilidade():
    assert nome_excel('razão_conferencia_conferencia.xlsx') == 'razao_conferencia.xlsx'
    assert nome_excel('ﬁnal ㎏ Ⅻ.xlsx') == 'final kg XII_conferencia.xlsx'
    assert nome_excel('C:\\FICTICIA\\área.xlsx') == 'area_conferencia.xlsx'

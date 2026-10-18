"""Nome entregue ASCII; nomes originais permanecem dentro da planilha."""
from io import BytesIO
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
import zipfile

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
    from app.main import _EntradaLote, _downloads_do_lote
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


@pytest.fixture(scope='module')
def navegador_nomes(tmp_path_factory):
    if os.environ.get('CONCILIADOR_TESTE_NAVEGADOR') != '1':
        pytest.skip('Chromium opt-in: CONCILIADOR_TESTE_NAVEGADOR=1')
    from playwright.sync_api import sync_playwright
    import urllib.request
    raiz=Path(__file__).resolve().parents[1];pasta=tmp_path_factory.mktemp('browser_nomes')
    processos=[];logs=[];urls={}
    try:
        for fonte in (False,):
            wrapper=pasta/f'tela_{fonte}.py'
            wrapper.write_text(f'''import sys
sys.path.insert(0,{str(raiz)!r})
from pathlib import Path
from datetime import datetime
import streamlit as st
import relatorio
if not hasattr(relatorio,'_excel_original'):
    relatorio._excel_original=relatorio.gerar_excel
def excel(*a,**k):return relatorio._excel_original(*a,**dict(k,gerado_em=datetime(2026,10,12,12)))
relatorio.gerar_excel=excel
st.session_state['marca::n']=st.session_state.get('marca::n',0)+1
st.html(f'<i id="marca-inicio" data-n="{{st.session_state["marca::n"]}}" style="display:none"></i>')
exec(compile(Path({str(raiz/'app/main.py')!r}).read_text(),{str(raiz/'app/main.py')!r},'exec'))
st.html(f'<i id="marca-fim" data-n="{{st.session_state["marca::n"]}}" style="display:none"></i>')
''')
            with socket.socket() as s:s.bind(('127.0.0.1',0));porta=s.getsockname()[1]
            log=(pasta/f'servidor_{fonte}.txt').open('w');logs.append(log)
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
            proc=subprocess.Popen([sys.executable,'-m','streamlit','run',str(wrapper),'--server.address','127.0.0.1',
                '--server.port',str(porta),'--server.headless','true','--browser.gatherUsageStats','false'],
                cwd=raiz,env=env,stdout=log,stderr=subprocess.STDOUT);processos.append(proc)
            url=f'http://127.0.0.1:{porta}';urls[fonte]=url;limite=time.monotonic()+30
            while True:
                assert proc.poll() is None
                try:
                    if urllib.request.urlopen(url+'/_stcore/health',timeout=.3).read()==b'ok':break
                except Exception:assert time.monotonic()<limite;time.sleep(.1)
        with sync_playwright() as pw:
            nav=pw.chromium.launch()
            try:yield nav,urls
            finally:nav.close()
    finally:
        for proc in processos:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
        for log in logs:log.close()


@pytest.mark.parametrize('tema',['light','dark'])
@pytest.mark.parametrize('fonte',[False],ids=['upload'])
def test_navegador_nome_recebido_rotulo_zip(navegador_nomes,tmp_path,tema,fonte):
    from playwright.sync_api import expect
    nav,urls=navegador_nomes;ctx=nav.new_context(color_scheme=tema,viewport={'width':1280,'height':1000},accept_downloads=True)
    page=ctx.new_page();erros=[];page.on('pageerror',lambda e:erros.append(str(e)));medidas=[]
    def n():return int(page.locator('#marca-fim').get_attribute('data-n'))
    def fim(minimo=1):
        page.wait_for_function('m=>{const a=document.querySelector("#marca-inicio"),b=document.querySelector("#marca-fim");return a&&b&&Number(a.dataset.n)>=m&&a.dataset.n===b.dataset.n}',arg=minimo,timeout=60000)
    def enviar(arquivos):
        page.goto(urls[fonte]);expect(page.locator('input[type=file]')).to_have_count(1);fim();execucao=n()
        page.set_input_files('input[type=file]',[{'name':name,'mimeType':'application/octet-stream','buffer':xlsx_de_n_contas(1)} for name in arquivos]);fim(execucao+1)
        expect(page.locator('[data-testid=stException]')).to_have_count(0)
    def botoes():return page.locator('[data-testid=stSidebar] [data-testid=stDownloadButton] button')
    def baixar(botao,esperado,origem=None):
        with page.expect_download() as d:botao.click()
        dl=d.value;recebido=dl.suggested_filename;rotulo=botao.inner_text()
        medidas.append({'rotulo':rotulo,'recebido':recebido,'esperado':esperado})
        (tmp_path/'medidas.json').write_text(json.dumps(medidas,ensure_ascii=False,indent=2))
        assert recebido==esperado and recebido.isascii()
        # O rotulo INTEIRO e '📊 Baixar Excel — origem → nome entregue', a menos do caractere sem largura (U+2060)
        # que a tela poe depois de cada gatilho de link ('&', '<', '@', 'http(s):' antes de '//', 'www' antes de '.'),
        # na origem e no nome entregue. Nada mais pode diferir.
        sem=rotulo.replace('\u2060','')
        assert '\u2060' not in recebido and sem.startswith('📊 Baixar Excel — ') and sem.endswith(' → '+recebido)
        if origem is not None:assert sem==f'📊 Baixar Excel — {origem} → {recebido}'
        assert rotulo==re.sub(r'(?i)(<|&|https?:(?=//)|www(?=\.)|@)',lambda m:m.group(1)+'\u2060',sem)
        dados=Path(dl.path()).read_bytes()
        return dados
    try:
        for origem,esperado in CASOS:
            enviar([origem]);dados=baixar(botoes().first,esperado,origem)
            wb=openpyxl.load_workbook(BytesIO(dados))
            import unicodedata
            original=unicodedata.normalize('NFC',origem)
            assert any(original in c.value for ws in wb for row in ws for c in row if isinstance(c.value,str))
        origens=['razão.xlsx','razao.xlsx','RAZÃO.xlsx','Conciliação março.xlsx','会計報告.xlsx','😀.xlsx','—.xlsx']
        enviar(origens);nomes=[];planilhas=[]
        for i in range(1,botoes().count()):
            rotulo=botoes().nth(i).inner_text();origem=rotulo.split(' — ',1)[1].rsplit(' → ',1)[0]
            esperado=({'razão.xlsx':'razao_conferencia.xlsx','razao.xlsx':'razao_conferencia.xlsx','RAZÃO.xlsx':'RAZAO_conferencia.xlsx',
                'Conciliação março.xlsx':'Conciliacao marco_conferencia.xlsx','会計報告.xlsx':'_____conferencia.xlsx','😀.xlsx':'__conferencia.xlsx','—.xlsx':'__conferencia.xlsx'})[origem]
            planilhas.append(baixar(botoes().nth(i),esperado));nomes.append(esperado)
        from relatorio.nomes import nomes_sem_colisao
        with page.expect_download() as d:botoes().first.click()
        assert d.value.suggested_filename=='conferencias.zip'
        with zipfile.ZipFile(d.value.path()) as z:
            assert z.namelist()==nomes_sem_colisao(nomes)
            assert all(x.isascii() for x in z.namelist())
            for nome,dados in zip(z.namelist(),planilhas):assert z.read(nome)==dados
            (tmp_path/'zip.json').write_text(json.dumps(z.namelist(),indent=2))
        assert not erros;page.screenshot(path=str(tmp_path/'fim.png'))
    finally:ctx.close()

"""L4: fatos da triagem/exportação, destinos desenhados e escape dos nomes."""
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.apresentacao import FraseAcimaDoLimite, triagem_linhas
from tests.test_app_pagina_cortada import INTEGRA, _tela, xlsx_de_n_contas

FIX = INTEGRA.parent


def triagem(at):
    return next(m.value for m in at.markdown if '<table' in m.value and 'Veredito' in m.value)


def test_erro_e_teto_tem_travessao_sem_repetir_fato():
    linhas = triagem_linhas([('ruim.xls', None, 'ruim.xls: fato sintetico'),
                            ('grande.xlsx', None, FraseAcimaDoLimite('101 contas: limite 100'))])
    assert [l['Achados'] for l in linhas] == ['—', '—']
    assert {l['Veredito'] for l in linhas} == {'⛔ Erro de leitura', '⛔ Acima do limite'}


def test_duas_linhas_de_resumo_na_sidebar():
    at = _tela(('a.xls', INTEGRA.read_bytes()), ('b.xls', INTEGRA.read_bytes()),
               ('ruim.xls', (FIX/'sintetica_adulterada.xls').read_bytes()),
               ('vazia.xlsx', xlsx_de_n_contas(0)))
    assert len(at.exception) == 0
    captions = [c.value for c in at.sidebar.caption]
    assert captions == ['4 arquivos recebidos · 2 lidos · 1 com erro de leitura · 1 sem contas',
                        '2 arquivos no ZIP']
    assert 'soma dos débitos NÃO confere' not in triagem(at)
    assert len(at.error) == 1


def test_links_por_identidade_e_indices_originais_em_nome_duplicado():
    at = _tela(('mesmo.xls', INTEGRA.read_bytes()), ('mesmo.xls', INTEGRA.read_bytes()))
    assert len(at.exception) == 0
    assert re.findall(r'href="#(conta-\d+-\d+)"', triagem(at)) == [
        'conta-0-0', 'conta-0-0', 'conta-1-0', 'conta-1-0']
    assert [s.proto.anchor for s in at.subheader] == ['titulo-conta-0-0', 'titulo-conta-1-0']


def test_rotulo_mostra_nome_entregue_com_escape():
    at = _tela(('sintetica_integra.xls', INTEGRA.read_bytes()))
    assert at.get('download_button')[0].label == (
        '📊 Baixar Excel — sintetica\\_integra.xls → sintetica\\_integra\\_conferencia.xlsx')


def test_janelas_so_linkam_contas_desenhadas_sem_mudar_indices():
    at = _tela(('doze.xlsx', xlsx_de_n_contas(12)))
    html = triagem(at)
    assert html.count('<tr>') == 13
    assert set(re.findall(r'href="#(conta-\d+-\d+)"', html)) == {f'conta-0-{i}' for i in range(10)}
    next(s for s in at.selectbox if s.label == 'Contas na tela').select(
        'Contas 11 a 12 de 12 deste arquivo').run()
    assert len(at.exception) == 0
    assert set(re.findall(r'href="#(conta-\d+-\d+)"', triagem(at))) == {'conta-0-10', 'conta-0-11'}
    assert [s.proto.anchor for s in at.subheader] == ['titulo-conta-0-10', 'titulo-conta-0-11']


def test_resumo_singular_zeros_zip_e_acima_do_limite():
    from app.apresentacao import resumo_envio_texto
    assert resumo_envio_texto(6,4,1,1,4) == [
        '6 arquivos recebidos · 4 lidos · 1 com erro de leitura · 1 sem contas', '4 arquivos no ZIP']
    assert resumo_envio_texto(1,1,0,0,1) == ['1 arquivo recebido · 1 lido']
    assert resumo_envio_texto(0,0,0,0,0) == []
    assert resumo_envio_texto(3,1,0,1,1,acima_do_limite=1) == [
        '3 arquivos recebidos · 1 lido · 1 acima do limite · 1 sem contas']


def test_recusado_nao_vira_erro_de_leitura_nem_arquivo_do_zip():
    at = _tela(('a.xls', INTEGRA.read_bytes()), ('b.xls', INTEGRA.read_bytes()),
               ('recusado.xlsx', xlsx_de_n_contas(101)))
    assert len(at.exception) == 0
    assert [c.value for c in at.sidebar.caption] == [
        '3 arquivos recebidos · 2 lidos · 1 acima do limite', '2 arquivos no ZIP']
    html = triagem(at)
    assert '101 contas' not in html and 'Acima do limite' in html
    assert html.count('<a href=') == 4
    assert len(at.get('download_button')) == 3


def test_lote_so_com_erro_ainda_mostra_resumo_sem_zip():
    dados = (FIX/'sintetica_adulterada.xls').read_bytes()
    at = _tela(('a.xls',dados), ('b.xls',dados))
    assert len(at.exception) == 0
    assert [c.value for c in at.sidebar.caption] == ['2 arquivos recebidos · 2 com erro de leitura']
    assert len(at.get('download_button')) == 0
    assert '<a href=' not in triagem(at)


def test_nome_hostil_e_destino_de_ancora_hostil_nao_viram_html():
    from app.apresentacao import tabela_triagem
    nome = '<img src=x onerror=alert(1)>.xls'
    linha = triagem_linhas([(nome, None, 'fato')])[0]
    linha['Conta'] = '<script>ruim</script>'
    html = tabela_triagem([linha], ancoras=['conta-0-0'])
    assert '<img' not in html and '<script' not in html and '&lt;img' in html
    html = tabela_triagem([linha], ancoras=['conta-0-0" onclick="alert(1)'])
    assert '<a href=' not in html and 'onclick=' not in html


def test_falha_de_planilha_nao_entra_no_numero_do_zip(monkeypatch):
    import relatorio
    original = relatorio.gerar_excel
    def gerar(*a, **k):
        if a[2] == 'falha.xls':
            raise RuntimeError('falha sintetica')
        return original(*a, **k)
    monkeypatch.setattr(relatorio, 'gerar_excel', gerar)
    at = _tela(*[(n, INTEGRA.read_bytes()) for n in ('a.xls','b.xls','falha.xls')])
    assert len(at.exception) == 0
    assert [c.value for c in at.sidebar.caption] == ['3 arquivos recebidos · 3 lidos', '2 arquivos no ZIP']
    assert len(at.get('download_button')) == 3
    assert any('a planilha deste arquivo não foi gerada' in e.value for e in at.error)


def test_janela_do_lote_repartida_preserva_links_das_duas_entradas():
    at = _tela(('a.xlsx',xlsx_de_n_contas(12)), ('b.xlsx',xlsx_de_n_contas(1,9001)))
    ids = set(re.findall(r'href="#(conta-\d+-\d+)"', triagem(at)))
    assert ids == {*(f'conta-0-{i}' for i in range(5)), 'conta-1-0'}
    next(s for s in at.selectbox if s.label.startswith('Contas na tela')).select(
        'Contas 6 a 10 de 12 deste arquivo').run()
    ids = set(re.findall(r'href="#(conta-\d+-\d+)"', triagem(at)))
    assert ids == {*(f'conta-0-{i}' for i in range(5,10)), 'conta-1-0'}


@pytest.fixture(scope='module')
def navegador_triagem(tmp_path_factory):
    if os.environ.get('CONCILIADOR_TESTE_NAVEGADOR') != '1':
        pytest.skip('Chromium opt-in: CONCILIADOR_TESTE_NAVEGADOR=1')
    import urllib.request

    from playwright.sync_api import sync_playwright
    raiz=Path(__file__).resolve().parents[1]
    pasta=tmp_path_factory.mktemp('browser_triagem')
    wrapper=pasta/'tela.py'
    wrapper.write_text(
        f'import sys\nsys.path.insert(0,{str(raiz)!r})\n'
        'from pathlib import Path\nimport streamlit as st\nimport relatorio\nfrom datetime import datetime\n'
        'if not hasattr(relatorio,"_excel_original"):\n    relatorio._excel_original=relatorio.gerar_excel\n'
        'def gerar(*a,**k):\n    return relatorio._excel_original(*a,**dict(k,gerado_em=datetime(2026,10,9,12)))\n'
        'relatorio.gerar_excel=gerar\n'
        'st.session_state["marca::execucoes"]=st.session_state.get("marca::execucoes",0)+1\n'
        'st.markdown(f\'<i id="triagem-contador" data-n="{st.session_state["marca::execucoes"]}" style="display:none"></i>\',unsafe_allow_html=True)\n'
        f'exec(compile(Path({str(raiz/"app/main.py")!r}).read_text(),{str(raiz/"app/main.py")!r},"exec"))\n'
        'st.markdown(f\'<i id="triagem-fim" data-n="{st.session_state["marca::execucoes"]}" style="display:none"></i>\',unsafe_allow_html=True)\n')
    processos=[]; logs=[]; urls={}
    try:
        for fonte in (False,):
            with socket.socket() as s:
                s.bind(('127.0.0.1',0));porta=s.getsockname()[1]
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
            log=(pasta/f'servidor_{fonte}.txt').open('w');logs.append(log)
            proc=subprocess.Popen([sys.executable,'-m','streamlit','run',str(wrapper),
                '--server.address','127.0.0.1','--server.port',str(porta),'--server.headless','true',
                '--browser.gatherUsageStats','false'],cwd=raiz,env=env,stdout=log,stderr=subprocess.STDOUT)
            processos.append(proc);url=f'http://127.0.0.1:{porta}';urls[fonte]=url
            limite=time.monotonic()+30
            while True:
                assert proc.poll() is None
                try:
                    if urllib.request.urlopen(url+'/_stcore/health',timeout=.5).read()==b'ok':break
                except Exception:
                    assert time.monotonic()<limite;time.sleep(.1)
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
def test_navegador_ancora_resumo_alturas_e_janela(navegador_triagem,tmp_path,tema):
    from playwright.sync_api import expect
    nav,urls=navegador_triagem
    ctx=nav.new_context(color_scheme=tema,viewport={'width':1280,'height':900},locale='pt-BR',accept_downloads=True)
    page=ctx.new_page();erros=[]
    page.on('pageerror',lambda e:erros.append(str(e)))
    medidas={}
    execucao=0
    def assenta(reexecuta=True):
        nonlocal execucao
        minimo=execucao+1 if reexecuta else 1
        page.wait_for_function('''(minimo) => {const i=document.querySelector('#triagem-contador'),f=document.querySelector('#triagem-fim');
            return i && f && Number(i.dataset.n)>=minimo && i.dataset.n===f.dataset.n;}''',arg=minimo,timeout=60000)
        execucao=int(page.locator('#triagem-fim').get_attribute('data-n'))
    def enviar(arquivos):
        page.goto(urls[False]);page.get_by_role('heading',level=1).wait_for()
        assenta(False)
        page.set_input_files('input[type="file"]',[{'name':n,'mimeType':'application/octet-stream','buffer':b} for n,b in arquivos])
        assenta();expect(page.locator('[data-testid="stException"]')).to_have_count(0)
    def botoes():
        return page.locator('[data-testid="stSidebar"] [data-testid="stDownloadButton"] button')
    try:
        enviar([('dez.xlsx',xlsx_de_n_contas(10))])
        link=page.locator('a[href="#conta-0-7"]').first
        expect(link).to_have_count(1)
        n=page.locator('#triagem-contador').get_attribute('data-n')
        link.click();assenta(False)
        expect(page.locator('#titulo-conta-0-7')).to_be_in_viewport()
        assert page.locator('#triagem-contador').get_attribute('data-n')==n
        rolagem=page.evaluate('Math.max(scrollY,document.querySelector("[data-testid=stMain]").scrollTop)')
        assert rolagem>0 and page.url.endswith('#conta-0-7') and len(ctx.pages)==1
        medidas['ancora']={'rolagem':rolagem,'execucoes_antes':n,'execucoes_depois':n}
        enviar([('doze.xlsx',xlsx_de_n_contas(12))])
        assert page.locator('a[href="#conta-0-10"]').count()==0
        page.get_by_role('combobox',name='Contas na tela').click()
        page.get_by_role('option',name='Contas 11 a 12 de 12 deste arquivo',exact=True).click();assenta()
        expect(page.locator('#titulo-conta-0-10')).to_have_count(1)
        assert page.locator('a[href="#conta-0-0"]').count()==0
        expect(page.locator('table.triagem a[href="#conta-0-10"]')).to_have_count(2)
        enviar([('sintetica_integra.xls',INTEGRA.read_bytes()),('b.xls',INTEGRA.read_bytes()),
                ('ruim.xls',(FIX/'sintetica_adulterada.xls').read_bytes()),('vazia.xlsx',xlsx_de_n_contas(0))])
        sidebar=page.locator('[data-testid="stSidebar"]')
        expect(sidebar.get_by_text('4 arquivos recebidos · 2 lidos · 1 com erro de leitura · 1 sem contas',exact=True)).to_have_count(1)
        expect(sidebar.get_by_text('2 arquivos no ZIP',exact=True)).to_have_count(1)
        expect(page.get_by_text('o arquivo veio corrompido',exact=False)).to_have_count(1)
        assert 'o arquivo veio corrompido' not in page.locator('table.triagem').inner_text()
        assert 'ZIP' in botoes().first.inner_text()
        medidas['botoes_upload']=botoes().evaluate_all('(bs)=>bs.map(b=>({texto:b.innerText,altura:b.getBoundingClientRect().height,largura:b.getBoundingClientRect().width,corte:b.scrollHeight>b.clientHeight+2}))')
        assert not any(b['corte'] for b in medidas['botoes_upload'])
        assert sidebar.evaluate('(e)=>e.scrollWidth-e.clientWidth')<=6
        page.screenshot(path=str(tmp_path/f'triagem_{tema}_resumo.png'))
        assert not erros and not page.locator('[data-testid="stException"]').count()
        (tmp_path/f'medidas_{tema}.json').write_text(json.dumps(medidas,ensure_ascii=False,indent=2))
    finally:ctx.close()


def test_link_usa_posicao_original_quando_triagem_reordena():
    from io import BytesIO

    import openpyxl
    wb=openpyxl.load_workbook(BytesIO(xlsx_de_n_contas(2)))
    linhas=[r for r in wb.active if r[0].value=='Conta:']
    linhas[0][1].value=8002;linhas[1][1].value=8001
    buf=BytesIO();wb.save(buf)
    at=_tela(('inverso.xlsx',buf.getvalue()))
    html=triagem(at)
    assert re.findall(r'href="#(conta-\d+-\d+)"',html)==[
        'conta-0-1','conta-0-1','conta-0-0','conta-0-0']
    assert [s.proto.anchor for s in at.subheader]==['titulo-conta-0-1','titulo-conta-0-0']


def test_um_arquivo_nao_tem_resumo_de_lote():
    at=_tela(('unico.xls',INTEGRA.read_bytes()))
    assert len(at.exception)==0
    assert not any(re.search(r'arquivos? recebidos?',c.value) for c in at.caption)

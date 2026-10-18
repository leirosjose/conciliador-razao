"""Um clique rola; montagem posterior não volta à conta já visitada."""
import json
import re
import time

import pytest

from tests.test_app_pagina_cortada import xlsx_de_n_contas
from tests.test_texto_triagem_e_exportacao import navegador_triagem


def assenta(page, minimo=1):
    page.wait_for_function('''(minimo) => {
        const i=document.querySelector('#triagem-contador'),f=document.querySelector('#triagem-fim');
        return i && f && Number(i.dataset.n)>=minimo && i.dataset.n===f.dataset.n;
    }''',arg=minimo,timeout=60000)
    # Inclui a rolagem adiada pelo Streamlit e a animação da aba.
    time.sleep(.8)


def topo(page):
    page.evaluate('document.querySelector("[data-testid=stMain]").scrollTop=0; window.scrollTo(0,0)')
    time.sleep(.2)


def foto(page):
    return page.evaluate('''() => ({hash: location.hash,
        scroll: Math.max(scrollY, document.querySelector('[data-testid=stMain]').scrollTop),
        execucoes: document.querySelector('#triagem-contador').dataset.n,
        chamadas: window.l4Rolagens || []})''')


@pytest.mark.parametrize('tema', ['light', 'dark'])
@pytest.mark.parametrize('n,pos,fonte', [(11,1,False),(75,5,False)],
                         ids=['minima11','setenta75'])
def test_ancora_nao_pula_apos_janela_ou_aba(navegador_triagem,tmp_path,tema,n,pos,fonte):
    from playwright.sync_api import expect
    nav,urls=navegador_triagem
    ctx=nav.new_context(color_scheme=tema,viewport={'width':1280,'height':900},locale='pt-BR')
    ctx.add_init_script('''window.l4Rolagens=[];
        const original=Element.prototype.scrollIntoView;
        Element.prototype.scrollIntoView=function(...args) {
            window.l4Rolagens.push({id:this.id,hash:location.hash,pilha:new Error().stack});
            return original.apply(this,args);
        };''')
    page=ctx.new_page();erros=[];page.on('pageerror',lambda e:erros.append(str(e)))
    medidas={}
    def enviar():
        page.goto(urls[fonte]);page.get_by_role('heading',level=1).wait_for();assenta(page)
        execucao=int(foto(page)['execucoes'])
        page.set_input_files('input[type=file]',{'name':'contas.xlsx','mimeType':'application/octet-stream',
                                              'buffer':xlsx_de_n_contas(n)})
        expect(page.locator('table.triagem')).to_be_visible(timeout=60000);assenta(page,execucao+1)
        expect(page.locator('[data-testid=stException]')).to_have_count(0)
    def redesenhar():
        if n>10:
            seletor=page.get_by_role('combobox',name='Contas na tela')
            execucao=int(foto(page)['execucoes'])
            seletor.click();page.get_by_role('option',name=f'Contas 11 a {min(20,n)} de {n} deste arquivo',exact=True).click()
            expect(page.get_by_role('heading',name=re.compile(r'Conta 8011\b'))).to_be_visible(timeout=60000)
            expect(page.locator('table.triagem a[href="#conta-0-0"]')).to_have_count(0);assenta(page,execucao+1)
            execucao=int(foto(page)['execucoes'])
            seletor.click();page.get_by_role('option',name=f'Contas 1 a 10 de {n} deste arquivo',exact=True).click()
            expect(page.get_by_role('heading',name=re.compile(r'Conta 8001\b'))).to_be_visible(timeout=60000)
            expect(page.locator('table.triagem a[href="#conta-0-0"]')).to_have_count(2);assenta(page,execucao+1)
    try:
        enviar();redesenhar();controle=foto(page)
        medidas['sem_clique']=controle
        if n>10:
            seletor=page.get_by_role('combobox',name='Contas na tela')
            expect(seletor).to_be_in_viewport()
        enviar();antes=foto(page)
        page.locator(f'table.triagem a[href="#conta-0-{pos}"]').first.click();assenta(page)
        clique=foto(page);medidas['antes']=antes;medidas['clique']=clique
        titulo=page.get_by_role('heading',name=re.compile(rf'Conta {8001+pos}\b'))
        expect(titulo).to_be_in_viewport()
        assert clique['scroll']>100 and clique['execucoes']==antes['execucoes']
        redesenhar();depois=foto(page);medidas['depois']=depois
        if n>10:
            seletor=page.get_by_role('combobox',name='Contas na tela')
            rect=seletor.bounding_box();medidas['seletor_y']=rect['y']
            (tmp_path/'medidas.json').write_text(json.dumps(medidas,indent=2))
            assert rect['y']>=0,medidas
            expect(seletor).to_be_in_viewport()
        assert not erros and page.locator('[data-testid=stException]').count()==0
    except Exception:
        (tmp_path/'estado_falha.txt').write_text(page.locator('body').inner_text())
        (tmp_path/'inputs_falha.json').write_text(json.dumps(page.get_by_role('combobox').evaluate_all('(es)=>es.map(e=>e.outerHTML)'),indent=2))
        page.screenshot(path=str(tmp_path/'falha.png'))
        raise
    finally:ctx.close()


@pytest.mark.parametrize('tema',['light','dark'])
@pytest.mark.parametrize('fonte',[False],ids=['upload'])
def test_resumo_sem_planilha_visivel(navegador_triagem,tmp_path,tema,fonte):
    from playwright.sync_api import expect

    from tests.test_texto_triagem_e_exportacao import FIX
    nav,urls=navegador_triagem
    ctx=nav.new_context(color_scheme=tema,viewport={'width':1280,'height':900})
    page=ctx.new_page()
    try:
        page.goto(urls[fonte]);page.get_by_role('heading',level=1).wait_for()
        assenta(page);execucao=int(foto(page)['execucoes'])
        dados=(FIX/'sintetica_adulterada.xls').read_bytes()
        page.set_input_files('input[type=file]',[{'name':n,'mimeType':'application/octet-stream','buffer':dados} for n in ('a.xls','b.xls')])
        resumo=page.get_by_text('2 arquivos recebidos · 2 com erro de leitura',exact=True)
        expect(resumo).to_have_count(1,timeout=60000);assenta(page,execucao+1)
        expect(page.locator('[data-testid=stDownloadButton]')).to_have_count(0)
        caixa=resumo.bounding_box();altura=caixa['height'] if caixa else 0
        assert altura>0
        expect(resumo).to_be_visible()
        page.screenshot(path=str(tmp_path/'resumo.png'))
    finally:ctx.close()


@pytest.mark.parametrize('tema',['light','dark'])
def test_entidades_no_rotulo_igual_nome_baixado(navegador_triagem,tmp_path,tema):
    from playwright.sync_api import expect
    nav,urls=navegador_triagem
    ctx=nav.new_context(color_scheme=tema,viewport={'width':1280,'height':900},accept_downloads=True)
    page=ctx.new_page()
    try:
        page.goto(urls[False]);page.get_by_role('heading',level=1).wait_for()
        nome='a&amp;b &lt;c&gt; &#58; &copy; <d> e@f www.g.invalid.xlsx'
        page.set_input_files('input[type=file]',{'name':nome,'mimeType':'application/octet-stream','buffer':xlsx_de_n_contas(1)})
        botao=page.locator('[data-testid=stDownloadButton] button')
        expect(botao).to_have_count(1,timeout=60000)
        with page.expect_download() as d:botao.click()
        baixado=d.value.suggested_filename
        # o rotulo e IGUAL ao nome enviado e ao nome entregue, a menos do caractere sem largura (U+2060)
        # que a tela poe depois de cada gatilho de link ('&', '<', '@', 'www' antes de '.'; 'http://' nao cabe em
        # nome de arquivo: o navegador troca a barra). Nada mais pode diferir.
        rotulo=botao.inner_text();sem=rotulo.replace('\u2060','')
        assert '\u2060' not in baixado and '\u2060' not in nome
        assert sem==f'📊 Baixar Excel — {nome} → {baixado}'
        assert baixado=='a&amp;b &lt;c&gt; &#58; &copy; _d_ e@f www.g.invalid_conferencia.xlsx'
        assert rotulo==re.sub(r'(?i)(<|&|https?:(?=//)|www(?=\.)|@)',lambda m:m.group(1)+'\u2060',sem)
        assert rotulo.count('\u2060')==15
        (tmp_path/'nome.json').write_text(json.dumps({'rotulo':rotulo,'entregue':baixado}))
    finally:ctx.close()

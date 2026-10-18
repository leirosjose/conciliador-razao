"""Smoke test da TELA (Streamlit) via AppTest: roda app/main.py de verdade, sem
browser, injeta o upload do golden sintetico e trava 2.820/1.440,09/4.260,09 NA
TELA contra regressao. Precisa do streamlit (requirements.txt).

E o checkpoint visual virado teste: se a tela parar de reproduzir o
golden (veredito, composicao, balde/divergencias), isto pega.
"""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

MAIN = Path(__file__).parent.parent / "app" / "main.py"
SINTETICA_XLS = Path(__file__).parent / "fixtures" / "sintetica_integra.xls"
MIME_XLS = "application/vnd.ms-excel"
FIXTURE = Path(__file__).parent / "fixtures" / "golden_sintetico.xls"


@pytest.fixture(scope="module")
def tela_inicial():
    return AppTest.from_file(str(MAIN), default_timeout=60).run()


@pytest.fixture(scope="module")
def tela_golden():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("golden_sintetico.xls", FIXTURE.read_bytes(), "application/vnd.ms-excel")
    ).run()
    return at


def _caixinhas_do_balde(at):
    """Os expanders do BALDE (um por item), pela key propria ("cx::"). A
    ponte e o periodo zerado tambem viraram expanders e nao sao caixinha de
    decisao -- filtrar pela key e nao por exclusao de rotulo."""
    return [e for e in at.expander if "cx::" in e.proto.id]


# --- Zona 1: a tela boota ---

def test_zona1_boota_sem_excecao(tela_inicial):
    assert len(tela_inicial.exception) == 0
    assert tela_inicial.title[0].value == "Conferência de Razão de Fornecedores"
    assert len(tela_inicial.radio) == 0          # PDF fora desta versao: sem seletor, so Excel
    assert len(tela_inicial.file_uploader) == 1


# --- Zona 2: veredito FECHA (verde), sem INCOMPLETO nem DIVERGENCIA ---

def test_veredito_fecha_verde(tela_golden):
    assert len(tela_golden.exception) == 0
    assert len(tela_golden.success) == 1
    # o verde e' a RESPOSTA ("quanto e do que"), nao "Fecha: a
    # composicao bate..." -- usuario-alvo sem experiencia contabil
    # a fonte markdown chega com o cifrao escapado (senao 2 R$ = LaTeX)
    assert tela_golden.success[0].value.startswith(
        "Conferido. Saldo de R\\$ 4.260,09")
    assert len(tela_golden.warning) == 0
    assert len(tela_golden.error) == 0


def test_cabecalho_da_conta(tela_golden):
    assert tela_golden.subheader[0].value == \
        "Conta 5218 — FERRAMENTAS FICTICIAS COMERCIO SA"


# --- Zona 3: composicao com o golden, mais antiga no topo ---

def test_composicao_golden_na_tela(tela_golden):
    df = tela_golden.dataframe[0].value
    assert list(df["NF"]) == ["618204", "274591"]          # idade 140 antes de 118
    em_aberto = dict(zip(df["NF"], df["EM ABERTO"]))
    assert em_aberto["618204"] == "2.820,00"
    assert em_aberto["274591"] == "1.440,09"


def test_saldo_final_assinado_na_tela(tela_golden):
    # o sinal do Dominio vira palavra (credor = a pagar)
    assert "Saldo no Domínio: R\\$ 4.260,09 a pagar" in [c.value for c in tela_golden.caption]


# --- Zona 4: balde e divergencias separados e vazios no golden ---

def test_balde_e_divergencias_vazios_no_golden(tela_golden):
    caps = [c.value for c in tela_golden.caption]
    assert "Nenhum item sem destino." in caps     # balde sem itens
    assert any("Nenhuma" in c for c in caps)      # sem divergencias


# --- Arquivo corrompido do Dominio: reparo SILENCIOSO na tela ---

def test_arquivo_reparado_processa_sem_aviso_na_tela():
    """Pro colaborador, arquivo reparado com self-check verde E' arquivo
    normal — nenhuma mensagem azul. O rastro tecnico vive no log do parser
    (tests/test_reparo_xls.py); o gate de self-check segue INTOCADO: reparo
    nao confiavel continua rejeitado com o ErroLeituraExcel amigavel."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    corrompida = FIXTURE.parent / "sintetica_corrompida.xls"
    at.file_uploader[0].set_value(
        ("sintetica_corrompida.xls", corrompida.read_bytes(), "application/vnd.ms-excel")
    ).run()
    assert len(at.exception) == 0
    assert len(at.warning) == 1                   # processou: veredito amarelo
    assert not any("reparado" in i.value for i in at.info)


# --- Balde autoexplicativo: contexto do INCOMPLETO + expansoes ---

def test_incompleto_mostra_contexto_do_gap_e_uma_caixinha_por_item():
    """Com balde, a tela traduz o amarelo (qual gap e quem o explica) e TODO
    item tem sua caixinha na ordem da tabela (o conferente processa
    item a item), com titulo legivel por leigo e orientacao dentro."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    corrompida = FIXTURE.parent / "sintetica_corrompida.xls"
    at.file_uploader[0].set_value(
        ("sintetica_corrompida.xls", corrompida.read_bytes(), "application/vnd.ms-excel")
    ).run()
    assert len(at.exception) == 0
    caps = [c.value for c in at.caption]
    # o VALOR do gap chega FORMATADO e escapado; a frase exata do contexto e
    # testada no teste de apresentacao, via constante compartilhada
    # O credito de 250,00 (transferencia de saldos) saiu do balde
    # e virou linha da composicao (resposta do contador)
    # gap 2.650,00 -> 2.900,00 pelo mesmo motivo
    # balde MISTO (D 3.400,00 / C 500,00) -- a frase traz os dois
    # lados em vez do liquido 2.900,00
    assert any("R\\$ 3.400,00 em débitos e R\\$ 500,00 em créditos" in c
               for c in caps)
    assert all("número do lançamento no Domínio" not in c for c in caps)
    assert any(c.startswith("Número 3014 · Crédito · ") for c in caps)
    caixinhas = _caixinhas_do_balde(at)
    # 4 -> 3. O credito de 250,00 (transferencia de saldos) saiu
    # do balde e virou linha da composicao (resposta do contador)
    assert len(caixinhas) == 3                    # UMA caixinha por lancamento
    assert all(e.label.startswith("Número ") for e in caixinhas)     # titulo p/ leigo


# --- Lote de razoes: upload multiplo com falha isolada -------------------------

def _xls(nome):
    return (nome, (FIXTURE.parent / nome).read_bytes(), "application/vnd.ms-excel")


def test_lote_misto_isola_a_falha_e_processa_os_demais():
    """valido + adulterado (gate rejeita) + valido: o lote NAO cai; o arquivo
    ruim vira erro isolado com a mensagem amigavel existente."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value([
        ("golden_sintetico.xls", FIXTURE.read_bytes(), "application/vnd.ms-excel"),
        _xls("sintetica_adulterada.xls"),
        _xls("sintetica_integra.xls"),
    ]).run()
    assert len(at.exception) == 0
    subs = " ".join(s.value for s in at.subheader)
    assert "5218" in subs                     # golden processou
    assert "7777" in subs                     # sintetica integra processou
    # cabecalho diz de qual arquivo veio, com o nome ESCAPADO: o
    # '_' do nome de arquivo vira '\_' na fonte do markdown (renderiza igual)
    assert "golden\\_sintetico.xls" in subs
    erros = " ".join(e.value for e in at.error)
    assert "sintetica\\_adulterada.xls" in erros   # nome escapado no erro
    assert "reparo não é confiável" in erros     # o fato, sem instrucao
    # triagem no topo: 1 linha por conta + 1 pro arquivo com erro, problema
    # primeiro (o erro de leitura abre a lista)
    # tabela HTML de leitura (quebra linha, sem rolagem lateral)
    (triagem,) = [m.value for m in at.markdown
                  if 'class="tabela-leitura triagem' in m.value]
    assert triagem.count("<tr>") == 1 + 3          # cabecalho + 3 linhas
    primeira = triagem.split("<tbody>")[1].split("</tr>")[0]
    assert "Erro de leitura" in primeira


def test_conta_unica_sem_erro_nao_mostra_triagem(tela_golden):
    """1 arquivo / 1 conta: a tela fica IGUAL a de sempre — triagem de 1
    linha seria redundante com o veredito logo abaixo."""
    df0 = tela_golden.dataframe[0].value
    assert "Arquivo" not in df0.columns       # primeira tabela e a composicao


def test_lote_acima_do_limite_nao_processa_nenhum():
    """Acima de MAX_ARQUIVOS_POR_LOTE: pede pra dividir e processa NADA —
    nunca 'so os 10 primeiros' em silencio."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    bytes_ok = (FIXTURE.parent / "sintetica_integra.xls").read_bytes()
    at.file_uploader[0].set_value([
        (f"razao_{i:02d}.xls", bytes_ok, "application/vnd.ms-excel")
        for i in range(11)
    ]).run()
    assert len(at.exception) == 0
    assert len(at.subheader) == 0             # NENHUMA conta processada
    assert len(at.error) == 1
    assert "10" in at.error[0].value          # diz o limite
    assert "nenhum arquivo foi processado" in at.error[0].value  # fato


# --- Erro de leitura na tela: mensagem amigavel com o arquivo, sem stack cru ---

def test_arquivo_sem_conta_avisa_em_vez_de_ficar_vazia():
    """Arquivo .xlsx valido mas SEM linha 'Conta:' -> zero contas. A tela nao
    pode ficar em branco em silencio: aviso claro pra conferir a
    exportacao do Dominio."""
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Período:", "", "01/01/2024 - 30/04/2025"])
    ws.append(["Data", "Número", "Histórico"])      # cabecalho, mas nenhuma 'Conta:'
    buf = io.BytesIO()
    wb.save(buf)

    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sem_conta.xlsx", buf.getvalue(),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ).run()
    assert len(at.exception) == 0                    # a tela nunca quebra
    assert any("Nenhuma conta" in w.value for w in at.warning)


def test_upload_ilegivel_mostra_erro_amigavel_com_o_nome_do_arquivo():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("lixo.xls", b"isto nao e um arquivo excel", "application/vnd.ms-excel")
    ).run()
    assert len(at.exception) == 0                 # a tela nunca quebra
    assert len(at.error) == 1
    msg = at.error[0].value
    assert "lixo.xls" in msg                      # diz QUAL arquivo
    assert "não abriu" in msg                     # o fato, sem instrucao
    assert "Traceback" not in msg                 # nunca stack trace cru


# --- escape de markdown COMPLETO e centralizado ---

_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_alerta_e_balde() -> bytes:
    """Sintetica .xlsx: compra 100 (NF 1111) SUPERPAGA por 150 -> alerta
    possivel_juros com TRES R$ (o caso LaTeX); mais um debito OUTRO cujo
    historico carrega um link markdown -> vai pro balde e aparece no expander.
    Nome do fornecedor com _ e [ ] pra o subheader. Totais batem (self-check
    verde): deb 200, cred 100, saldo final +100."""
    import datetime
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for row in [
        ["Período:", "", "01/01/2024 - 30/04/2025"],
        ["Conta:", "8888", "2.01.01", None, None, "FORN FICTICIO _X_ [Y] LTDA"],
        ["Data", "Número", "Histórico", None, None, None, None,
         "Cta.C.Part.", "Débito", "Crédito", None, None, "Saldo-Exercício"],
        [None, None, "SALDO ANTERIOR", None, None, None, None,
         None, None, None, None, None, 0],
        [datetime.datetime(2025, 1, 10), "c1", "Vr. compras conf. 1111 FORN",
         None, None, None, None, "1001", 0, 100, None, None, -100],
        [datetime.datetime(2025, 2, 1), "p1", "PGTO NF 1111",
         None, None, None, None, "1002", 150, 0, None, None, 50],
        [datetime.datetime(2025, 3, 1), "m1",
         "revisar [clique](http://evil.com) urgente",
         None, None, None, None, "1003", 50, 0, None, None, 100],
        [None, None, None, None, "Total da conta:", None, None,
         None, 200, 100],
    ]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_alerta_com_multiplos_rs_vai_escapado_pro_st_info():
    """possivel_juros tem tres R$ na mesma linha -> par vira LaTeX. O st.info
    recebe o R$ escapado."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("alerta.xlsx", _xlsx_alerta_e_balde(), _MIME_XLSX)).run()
    assert len(at.exception) == 0
    infos = " ".join(i.value for i in at.info)
    assert "possível juros" in infos                       # o alerta apareceu
    assert "R\\$" in infos                                 # cifrao escapado
    assert "R$ 150.00 sobre compra R$" not in infos        # nunca o par cru de LaTeX


def test_link_no_historico_do_balde_morre_no_expander():
    """[clique](url) no historico nao vira link vivo no titulo do expander do
    balde -- escapa no ponto de montagem."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("alerta.xlsx", _xlsx_alerta_e_balde(), _MIME_XLSX)).run()
    assert len(at.exception) == 0
    labels = " ".join(e.label for e in at.expander)
    assert "[clique]" not in labels
    assert any("[clique](http://evil.com)" in m.value for m in at.markdown)
    assert not any('<a href="http://evil.com"' in m.value for m in at.markdown)
    assert "[clique](http://evil.com)" not in labels       # nunca o link cru


def test_erro_de_leitura_escapa_nome_de_arquivo_no_st_error():
    """Nome de upload com * [ ] nao vira markdown vivo no st.error."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("ruim_*_[x].xls", b"isto nao e um arquivo excel",
         "application/vnd.ms-excel")).run()
    assert len(at.exception) == 0
    erros = " ".join(e.value for e in at.error)
    assert "ruim\\_\\*\\_\\[x\\].xls" in erros


def test_tempfile_nao_vaza_se_o_write_do_upload_falha(monkeypatch):
    """Se o write do upload falhar, o tempfile criado NAO vaza -- e criado e
    escrito DENTRO do try cujo finally faz o unlink."""
    import os
    import tempfile

    from app.main import _processar_upload_excel

    criados = []
    real = tempfile.NamedTemporaryFile

    def _rastreia(*a, **k):
        f = real(*a, **k)
        criados.append(f.name)
        return f

    monkeypatch.setattr("app.main.tempfile.NamedTemporaryFile", _rastreia)

    class _UploadRuim:
        name = "razao.xls"

        def getbuffer(self):
            raise OSError("disco cheio")

    with pytest.raises(OSError):
        _processar_upload_excel(_UploadRuim())
    assert criados                                       # o tempfile foi criado
    assert not any(os.path.exists(p) for p in criados)   # e limpo, nao vazou


def test_sinks_de_dado_externo_permanecem_escapados():
    """Varredura (grep assertivo): os sinks de markdown que recebem dado externo
    em main.py nao podem voltar ao cru -- trava a CLASSE contra regressao."""
    src = MAIN.read_text()
    assert "st.info(a.mensagem" not in src                 # #8 -> markdown_seguro
    assert "st.error(entrada.erro)" not in src             # #10 -> markdown_seguro
    assert "st.subheader(titulo)" not in src               # #9 -> titulo_conta
    assert "titulo_conta" in src                           # cabecalho usa o helper


# --- Materialidade na tela: o que pesa, e quantos de cada motivo --

def test_balde_mostra_materialidade_e_contagem_por_motivo():
    """Acima do balde, duas linhas de triagem: quanto os maiores itens pesam
    sobre o gap e quantos itens ha de cada motivo. A ORDEM da tela nao muda
    (cronologica); a materialidade so aponta onde comecar."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    corrompida = FIXTURE.parent / "sintetica_corrompida.xls"
    at.file_uploader[0].set_value(
        ("sintetica_corrompida.xls", corrompida.read_bytes(), "application/vnd.ms-excel")
    ).run()
    assert len(at.exception) == 0
    caps = [c.value for c in at.caption]
    # 3 itens cabem inteiros nos "5 maiores" -- a frase so' repetiria
    # o total; fica so' a contagem por motivo
    assert not any("maiores itens respondem por" in c for c in caps)
    # O credito de 250,00 (transferencia de saldos) saiu do balde
    # e virou linha da composicao (resposta do contador)
    assert any("3 itens: 1 Estorno sem par, 1 Não reconhecido, 1 Sem NF" in c
               for c in caps)


def test_golden_sem_balde_nao_mostra_materialidade(tela_golden):
    caps = [c.value for c in tela_golden.caption]
    assert not any("maiores itens" in c for c in caps)


# --- a composicao e' UMA tabela (sem secao de quitadas) ---

def test_nao_ha_secao_separada_de_quitadas(tela_golden):
    assert not any("NFs quitadas" in e.label for e in tela_golden.expander)
    assert not any("NFs quitadas" in str(c.value) for c in tela_golden.caption)


# --- a palavra "gap" nao existe pro usuario ---

def _textos_renderizados(at):
    """TODO texto que a tela mostra: prosa, rotulos de metrica, cabecalhos de
    tabela, titulos de caixinha e as caixas de veredito."""
    textos = []
    for elementos in (at.markdown, at.caption, at.success, at.warning, at.error,
                      at.info, at.subheader, at.title):
        textos += [str(e.value) for e in elementos]
    for m in at.metric:
        textos += [m.label, str(m.value)]
    for e in at.expander:
        textos.append(e.label)
    for df in at.dataframe:
        textos += [str(c) for c in df.value.columns]
        textos += [str(v) for linha in df.value.values for v in linha]
    return textos


def test_a_palavra_gap_nao_aparece_na_tela(tela_golden):
    """O usuario nunca le 'gap' — o nome interno pode ficar no codigo."""
    achados = [t for t in _textos_renderizados(tela_golden)
               if re.search(r"\bgaps?\b", t, re.I)]
    assert achados == []


def test_a_palavra_gap_nao_aparece_na_tela_com_balde():
    """A conta AMARELA e onde a palavra mais aparecia (veredito, materialidade,
    divergencias, triagem)."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sintetica_integra.xls", SINTETICA_XLS.read_bytes(), MIME_XLS)).run()
    achados = [t for t in _textos_renderizados(at)
               if re.search(r"\bgaps?\b", t, re.I)]
    assert achados == []


# --- prosa que se le uma vez nao fica na tela ---

_PROSA_CORTADA = (
    "Não ficam salvas",                    # legenda das decisoes da sessao
    "precisa de conferência humana",       # legenda do balde
    "Erros reais",                         # legenda das divergencias
    "Varra o resumo",                      # legenda da triagem
    "NFs mais antigas no topo",            # subtitulo da composicao
)


def test_a_tela_nao_carrega_prosa_de_leitura_unica():
    """Premissa: CONTADOR, todo dia. Texto que ele le uma vez e nunca mais
    precisa nao ocupa espaco permanente — vive no manual. Fica o que e DADO
    (numeros, notas do item, evidencia) e o que e ACAO."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sintetica_integra.xls", SINTETICA_XLS.read_bytes(), MIME_XLS)).run()
    textos = " ".join(_textos_renderizados(at))
    assert [p for p in _PROSA_CORTADA if p in textos] == []


# === "Erro inesperado" na tela diz o fato; o detalhe vai pro log ===

def test_erro_inesperado_no_lote_nao_mostra_classe_nem_texto_cru_e_loga_o_detalhe(
        monkeypatch, caplog):
    import logging

    from app import main

    class _Upload:
        name = "razao.xls"

        def getbuffer(self):
            return b"qualquer coisa"

    def _explode(*a, **k):
        raise RuntimeError("falha em /tmp/y_interno")

    monkeypatch.setattr(main, "processar_excel", _explode)
    monkeypatch.setattr(main.st, "session_state", {})
    with caplog.at_level(logging.ERROR, logger="app.main"):
        (entrada,) = main._processar_lote([_Upload()])
    assert entrada.resultados is None
    assert entrada.erro == ("Erro inesperado processando 'razao.xls'; nenhum "
                            "resultado foi gerado pra este arquivo.")
    assert "RuntimeError" not in entrada.erro and "/tmp/y_interno" not in entrada.erro
    (registro,) = [r for r in caplog.records if r.name == "app.main"]
    assert registro.levelname == "ERROR"
    import hashlib
    assert registro.getMessage().splitlines()[0] == ("erro inesperado processando o arquivo "
                                                     + hashlib.sha256(b"qualquer coisa").hexdigest()[:8])
    assert "razao.xls" not in caplog.text                                  # nunca o nome do arquivo
    assert "RuntimeError" in caplog.text and "/tmp/y_interno" not in caplog.text    # o TIPO sim; a mensagem nao
    assert "Traceback" not in caplog.text and registro.exc_info is None


def test_erro_de_leitura_amigavel_segue_na_tela_e_nao_vai_pro_log_de_erro(
        monkeypatch, caplog, tmp_path):
    """CONTROLE: ErroLeituraExcel ja e' frase pra humano -- continua na tela
    como veio e nao e' tratado como erro inesperado."""
    import logging

    from app import main

    class _Upload:
        name = "lixo.xls"

        def getbuffer(self):
            return b"isto nao e um arquivo excel"

    monkeypatch.setattr(main.st, "session_state", {})
    with caplog.at_level(logging.ERROR, logger="app.main"):
        (entrada,) = main._processar_lote([_Upload()])
    assert entrada.erro.startswith("'lixo.xls' não abriu nem após tentativa de reparo")
    assert not [r for r in caplog.records if r.name == "app.main"]


# === o rastro tecnico chega ao log do servico, com data/hora ====
# O projeto nao configurava logging: o INFO de reparo (e as outras linhas de log sem
# data) nao chegavam ao log. A casca poe UM handler com data/hora nos loggers
# "app" e "parser"; o Streamlit reexecuta o script a cada interacao, entao ha
# guarda contra duplicar.

_LINHA_COM_DATA = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} (INFO|WARNING|ERROR) (app|parser)[\w.]*: ")


def _handlers(nome):
    import logging
    return list(logging.getLogger(nome).handlers)


def _handler_unico(nome):
    handlers = _handlers(nome)
    assert len(handlers) == 1, f"logger {nome!r}: {len(handlers)} handlers (esperado 1)"
    return handlers[0]


def test_loggers_app_e_parser_tem_um_handler_so_mesmo_com_o_script_reexecutado():
    import importlib
    import logging

    import app.main
    for _ in range(2):                       # o Streamlit reexecuta o script a cada clique
        importlib.reload(app.main)
    for nome in ("app", "parser"):
        handlers = _handlers(nome)
        assert len(handlers) == 1, nome
        assert logging.getLogger(nome).level == logging.INFO
        assert "%(asctime)s" in handlers[0].formatter._fmt


def test_reparo_de_arquivo_chega_ao_log_do_servico_com_data_e_hora(monkeypatch):
    import io

    import app.main
    from app.pipeline import processar_excel

    handler = _handler_unico("parser")
    saida = io.StringIO()
    monkeypatch.setattr(handler, "stream", saida)
    processar_excel(Path(__file__).parent / "fixtures" / "sintetica_corrompida.xls",
                    nome="reparado.xls")
    linhas = saida.getvalue().splitlines()
    assert len(linhas) == 1
    assert _LINHA_COM_DATA.match(linhas[0])
    import hashlib
    h = hashlib.sha256((Path(__file__).parent / "fixtures" / "sintetica_corrompida.xls").read_bytes()).hexdigest()[:8]
    assert linhas[0][24:] == (f"INFO parser.excel: arquivo {h}: reparado na leitura "
                              "(BOUNDSHEET do exportador do Dominio)")      # hash dos bytes, nunca o nome


def test_erro_inesperado_chega_ao_log_do_servico_com_data_hora_e_traceback(monkeypatch):
    import io

    from app import main

    handler = _handler_unico("app")
    saida = io.StringIO()
    monkeypatch.setattr(handler, "stream", saida)

    class _Upload:
        name = "falha.xls"

        def getbuffer(self):
            return b"x"

    monkeypatch.setattr(main, "processar_excel",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("detalhe interno")))
    monkeypatch.setattr(main.st, "session_state", {})
    main._processar_lote([_Upload()])
    texto = saida.getvalue()
    assert _LINHA_COM_DATA.match(texto.splitlines()[0])
    import hashlib
    assert f"ERROR app.main: erro inesperado processando o arquivo {hashlib.sha256(b'x').hexdigest()[:8]}" in texto
    assert "falha.xls" not in texto                                      # nunca o nome do arquivo
    assert "RuntimeError em " in texto and "app/main.py" in texto        # o TIPO e o lugar do codigo
    assert "Traceback" not in texto and "detalhe interno" not in texto   # nunca a mensagem da excecao


def test_processar_arquivo_integro_nao_escreve_nada_no_log_de_servico(monkeypatch):
    """CONTROLE: arquivo normal (sem reparo, sem erro) nao gera linha no log."""
    import io

    import app.main
    from app.pipeline import processar_excel

    handler = _handler_unico("parser")
    saida = io.StringIO()
    monkeypatch.setattr(handler, "stream", saida)
    processar_excel(FIXTURE, nome="golden_sintetico.xls")
    assert saida.getvalue() == ""


def test_handler_do_log_de_servico_escreve_em_stderr_nao_em_stdout(monkeypatch):
    """O servico captura o stderr do processo (iniciar.bat -> logs\\*.log): o
    handler que a casca cria tem que escrever la, nao no stdout. Os outros testes
    trocam o stream por StringIO, entao este recria o handler (sem o que ja
    existia) e olha o stream que a PRODUCAO escolhe."""
    import importlib
    import logging
    import sys

    import app.main
    for nome in ("app", "parser"):
        monkeypatch.setattr(logging.getLogger(nome), "handlers", [])
    importlib.reload(app.main)
    for nome in ("app", "parser"):
        (handler,) = logging.getLogger(nome).handlers
        assert handler.stream is sys.stderr, nome
        assert handler.stream is not sys.stdout, nome

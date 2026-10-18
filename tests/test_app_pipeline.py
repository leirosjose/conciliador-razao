"""Casca de orquestracao (app/pipeline.py): escolhe parser + classificador e
chama o core. So fiacao -- sem logica contabil. Prova que o caminho de dados
da TELA (parser -> conferir) reproduz o golden, sem subir o Streamlit.
"""
from decimal import Decimal
from pathlib import Path

from app.pipeline import processar_excel
from core.modelo import Nivel

FIXTURE = Path(__file__).parent / "fixtures" / "golden_sintetico.xls"
FIXTURE_CORROMPIDA = Path(__file__).parent / "fixtures" / "sintetica_corrompida.xls"


def test_processar_excel_devolve_uma_conta_da_ferramentas_ficticias():
    proc = processar_excel(FIXTURE)
    assert len(proc.resultados) == 1
    assert proc.arquivo_reparado is False       # golden integro: rota normal


def test_processar_excel_anota_reparo_da_leitura():
    # rastro PROGRAMATICO: a tela nao avisa mais; testes e diagnostico
    # leem daqui, e o rastro humano e' o logging.info do parser
    proc = processar_excel(FIXTURE_CORROMPIDA)
    assert proc.arquivo_reparado is True
    assert len(proc.resultados) == 1


def test_alocacao_da_tela_chega_ao_motor_pela_conta_certa():
    """A chave e o CODIGO da conta — uma razao traz N contas, cada uma com
    seu balde. Conta sem alocacao continua com a saida de sempre."""
    from core.modelo import AlocacaoManual, DestinoAlocacao

    antes = processar_excel(FIXTURE_CORROMPIDA).resultados[0]
    item = antes.balde[0]
    codigo = antes.conta.codigo

    depois = processar_excel(FIXTURE_CORROMPIDA, {codigo: [AlocacaoManual(
        item_id=item.identificador,
        destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
        rotulo="conferido com o cliente")]}).resultados[0]
    assert len(depois.balde) == len(antes.balde) - 1
    assert depois.decisoes[0].rotulo == "conferido com o cliente"

    # conta que nao esta no dicionario nao e afetada
    outra = processar_excel(FIXTURE_CORROMPIDA,
                            {"conta-que-nao-existe": []}).resultados[0]
    assert len(outra.balde) == len(antes.balde)
    assert outra.decisoes == []


def test_processar_excel_reproduz_o_golden():
    res = processar_excel(FIXTURE).resultados[0]
    por_nf = {i.nf_numero: i for i in res.itens}
    assert por_nf["618204"].saldo_aberto == Decimal("2820.00")
    assert por_nf["274591"].saldo_aberto == Decimal("1440.09")
    total = sum((i.saldo_aberto for i in res.itens), Decimal("0.00"))
    assert total == Decimal("4260.09")
    # veredito FECHA pelo caminho da tela
    assert not any(a.nivel is Nivel.ERRO for a in res.achados)
    assert not any(a.nivel is Nivel.INCOMPLETO for a in res.achados)
    assert res.balde == []


# === o nome do upload vai por parametro, o temporario e curto

FIXTURES = Path(__file__).parent / "fixtures"


def test_processar_excel_com_nome_cita_o_nome_do_upload_na_mensagem():
    import pytest

    from parser.excel import ErroLeituraExcel
    with pytest.raises(ErroLeituraExcel) as exc:
        processar_excel(FIXTURES / "sintetica_adulterada.xls", nome="Fornecedor_X.xls")
    assert str(exc.value).startswith("'Fornecedor_X.xls': o arquivo veio corrompido")


class _Upload:
    def __init__(self, nome, conteudo):
        self.name, self._conteudo = nome, conteudo

    def getbuffer(self):
        return self._conteudo


def test_upload_adulterado_e_citado_pelo_nome_do_upload_nao_pelo_temporario():
    """O que a tela mostra: nome do upload, sem o `tmpXXXX_` do temporario."""
    import pytest

    from app.main import _processar_upload_excel
    from parser.excel import ErroLeituraExcel
    conteudo = (FIXTURES / "sintetica_adulterada.xls").read_bytes()
    with pytest.raises(ErroLeituraExcel) as exc:
        _processar_upload_excel(_Upload("Fornecedor_X.xls", conteudo))
    assert str(exc.value).startswith("'Fornecedor_X.xls': o arquivo veio corrompido")


def test_upload_com_nome_de_244_caracteres_abre_a_conta(monkeypatch):
    """O nome do upload NAO entra no nome do temporario (limite de 255 por
    componente do SO); o temporario tem nome curto e a conta abre."""
    import tempfile

    from app.main import _processar_upload_excel
    criados = []
    real = tempfile.NamedTemporaryFile

    def _rastreia(*a, **k):
        f = real(*a, **k)
        criados.append(f.name)
        return f

    monkeypatch.setattr("app.main.tempfile.NamedTemporaryFile", _rastreia)
    nome = "n" * 240 + ".xls"
    conteudo = (FIXTURES / "sintetica_integra.xls").read_bytes()
    proc = _processar_upload_excel(_Upload(nome, conteudo))
    assert len(proc.resultados) == 1
    assert len(Path(criados[0]).name) < 50
    assert "nnnn" not in criados[0]


# === dois uploads com o MESMO nome no lote nao dividem a chave ================
# A chave do estado da tela (decisoes manuais) e dos widgets era o nome do
# arquivo: o mesmo nome 2x dava chave repetida (a tela caia com
# StreamlitDuplicateElementKey) e as decisoes de um arquivo valiam pro outro.
# Aqui a funcao REAL que a tela usa pra montar o lote, sem AppTest.

def _decisao_fora_da_composicao():
    """A decisao manual que a tela guarda no estado: o 1o item sem destino da
    sintetica corrompida sai da composicao."""
    from core.modelo import AlocacaoManual, DestinoAlocacao
    antes = processar_excel(FIXTURE_CORROMPIDA).resultados[0]
    return antes, AlocacaoManual(item_id=antes.balde[0].identificador,
                                 destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
                                 rotulo="decisao do 1o arquivo")


def test_decisao_do_1o_arquivo_nao_vaza_pro_2o_de_mesmo_nome(monkeypatch):
    from app import main
    antes, decisao = _decisao_fora_da_composicao()
    estado = {main._chave_alocacoes("razao.xls", antes.conta.codigo): [decisao]}
    monkeypatch.setattr(main.st, "session_state", estado)
    conteudo = FIXTURE_CORROMPIDA.read_bytes()
    lote = main._processar_lote([_Upload("razao.xls", conteudo),
                                 _Upload("razao.xls", conteudo)])
    primeiro, segundo = (e.resultados[0] for e in lote)
    assert len(primeiro.balde) == len(antes.balde) - 1      # a decisao e' dele
    assert len(segundo.balde) == len(antes.balde)           # e nao vaza pro outro
    assert segundo.decisoes == []


def test_chaves_do_lote_sao_unicas_e_o_1o_arquivo_mantem_o_proprio_nome(monkeypatch):
    from app import main
    monkeypatch.setattr(main.st, "session_state", {})
    conteudo = FIXTURE_CORROMPIDA.read_bytes()
    lote = main._processar_lote([_Upload("razao.xls", conteudo),
                                 _Upload("outra.xls", conteudo),
                                 _Upload("razao.xls", conteudo)])
    # a chave do estado da tela; sem o campo `chave` a tela usava o proprio nome
    chaves = [getattr(e, "chave", e.nome) for e in lote]
    assert chaves == ["razao.xls", "outra.xls", "razao_2.xls"]
    assert [e.nome for e in lote] == ["razao.xls", "outra.xls", "razao.xls"]


def test_decisao_guardada_no_nome_antigo_continua_valendo_pro_arquivo_unico(monkeypatch):
    """CONTROLE: arquivo de nome unico mantem a chave de sempre (re-subir o
    mesmo arquivo continua devolvendo as decisoes)."""
    from app import main
    antes, decisao = _decisao_fora_da_composicao()
    monkeypatch.setattr(main.st, "session_state", {
        main._chave_alocacoes("razao.xls", antes.conta.codigo): [decisao]})
    (entrada,) = main._processar_lote(
        [_Upload("razao.xls", FIXTURE_CORROMPIDA.read_bytes())])
    assert len(entrada.resultados[0].balde) == len(antes.balde) - 1


def test_arquivo_com_erro_tambem_leva_a_chave_unica_do_lote(monkeypatch):
    """As 3 saidas de _processar_lote (ok, erro de leitura, erro inesperado) levam
    a chave; o erro de um arquivo nao desloca a chave dos outros."""
    from app import main
    monkeypatch.setattr(main.st, "session_state", {})
    ok = FIXTURE_CORROMPIDA.read_bytes()
    lixo = b"isto nao e um arquivo excel"
    original = main.processar_excel

    def _explode_no_terceiro(caminho, *a, **k):
        if "explode" in str(k.get("nome")):
            raise RuntimeError("falha inesperada")
        return original(caminho, *a, **k)

    monkeypatch.setattr(main, "processar_excel", _explode_no_terceiro)
    lote = main._processar_lote([_Upload("a.xls", ok), _Upload("a.xls", lixo),
                                 _Upload("explode.xls", ok), _Upload("explode.xls", ok)])
    assert [e.erro is None for e in lote] == [True, False, False, False]
    assert [getattr(e, "chave", e.nome) for e in lote] == [
        "a.xls", "a_2.xls", "explode.xls", "explode_2.xls"]


# === duas contas de MESMO codigo no mesmo arquivo ==============================
# No pipeline as decisoes manuais eram indexadas pelo codigo da conta: com o
# codigo repetido (conta emendada 2x), a decisao tomada na 2a valia nas duas.
# A chave de estado de cada conta e' o codigo; o repetido ganha _2, _3...

def _razao_xls_com_contas(caminho, codigos):
    """.xls sintetico no layout do Dominio com UMA conta por codigo (a mesma
    conta emendada se o codigo repete): 1 compra e 1 debito sem destino de
    10,00 (`TARIFA AVULSA`). Dados ficticios."""
    from datetime import date

    import xlwt

    from tests.fixtures.gerar_sinteticas import CNPJ, COL_SALDO, EMPRESA, PERIODO, _serial
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Razão")
    ws.write(0, 0, "Empresa:"); ws.write(0, 2, EMPRESA)
    ws.write(1, 0, "C.N.P.J.:"); ws.write(1, 2, CNPJ)
    ws.write(2, 0, "Período:"); ws.write(2, 2, PERIODO)
    ws.write(3, 0, "RAZÃO")
    ws.write(5, 0, "Data"); ws.write(5, 1, "Número"); ws.write(5, 2, "Histórico")
    ws.write(5, 7, "Cta.C.Part."); ws.write(5, 8, "Débito"); ws.write(5, 9, "Crédito")
    ws.write(5, COL_SALDO, "Saldo-Exercício")
    r = 6
    for codigo in codigos:
        ws.write(r, 0, "Conta:"); ws.write(r, 1, float(codigo))
        ws.write(r, 2, "2.01.01.001.00"); ws.write(r, 5, "FORNECEDOR FICTICIO LTDA")
        ws.write(r + 1, 2, "SALDO ANTERIOR"); ws.write(r + 1, COL_SALDO, 0.0)
        r += 2
        for i, (hist, deb, cred, saldo) in enumerate([
                ("Vr. compras conf. 1234 FORNECEDOR FICTICIO LTDA", None, 1000.0, -1000.0),
                ("TARIFA AVULSA", 10.0, None, -990.0)]):
            ws.write(r, 0, _serial(date(2025, 3, 2 + i))); ws.write(r, 1, float(5000 + i))
            ws.write(r, 2, hist); ws.write(r, 7, 38.0)
            if deb is not None:
                ws.write(r, 8, deb)
            if cred is not None:
                ws.write(r, 9, cred)
            ws.write(r, COL_SALDO, saldo); r += 1
        r += 1
        ws.write(r, 4, "Total da conta:"); ws.write(r, 8, 10.0); ws.write(r, 9, 1000.0)
        r += 2
    wb.save(str(caminho))
    return caminho


def _decisoes_por_conta(caminho, alocacoes):
    return [len(r.decisoes) for r in processar_excel(caminho, alocacoes).resultados]


def _decisao_no_item_sem_destino(caminho):
    from core.modelo import AlocacaoManual, DestinoAlocacao
    item = processar_excel(caminho).resultados[0].balde[0]
    return AlocacaoManual(item_id=item.identificador,
                          destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
                          rotulo="decisao manual")


def test_conta_emendada_2x_tem_o_mesmo_identificador_de_item_nas_duas(tmp_path):
    """Premissa do achado: a mesma conta emendada 2x e' igual campo a campo; o
    item sem destino tem o MESMO identificador nas duas contas."""
    caminho = _razao_xls_com_contas(tmp_path / "emendada.xls", [7001, 7001])
    a, b = processar_excel(caminho).resultados
    assert a.balde[0].identificador == b.balde[0].identificador


def test_decisao_da_2a_conta_de_mesmo_codigo_nao_vale_pra_1a(tmp_path):
    caminho = _razao_xls_com_contas(tmp_path / "emendada.xls", [7001, 7001])
    decisao = _decisao_no_item_sem_destino(caminho)
    assert _decisoes_por_conta(caminho, {"7001_2": [decisao]}) == [0, 1]


def test_decisao_guardada_pelo_codigo_vale_so_pra_1a_conta_de_mesmo_codigo(tmp_path):
    caminho = _razao_xls_com_contas(tmp_path / "emendada.xls", [7001, 7001])
    decisao = _decisao_no_item_sem_destino(caminho)
    assert _decisoes_por_conta(caminho, {"7001": [decisao]}) == [1, 0]


def test_contas_de_codigos_diferentes_seguem_pelo_codigo(tmp_path):
    """CONTROLE: sem codigo repetido, a chave e' o codigo de sempre."""
    caminho = _razao_xls_com_contas(tmp_path / "duas.xls", [7001, 7002])
    decisao = _decisao_no_item_sem_destino(caminho)
    assert _decisoes_por_conta(caminho, {"7001": [decisao]}) == [1, 0]
    assert _decisoes_por_conta(caminho, {"7002": [decisao]}) == [0, 1]


def test_chaves_das_contas_repete_o_codigo_com_sufixo_na_ordem_do_arquivo(tmp_path):
    """A chave que a tela e o pipeline usam: a MESMA funcao."""
    from app.pipeline import chaves_das_contas
    caminho = _razao_xls_com_contas(tmp_path / "tres.xls", [7001, 7002, 7001])
    contas = [r.conta for r in processar_excel(caminho).resultados]
    assert chaves_das_contas(contas) == ["7001", "7002", "7001_2"]

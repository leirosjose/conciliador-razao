"""Nome do Excel de saida: mesmo nome do arquivo de origem com o
SUFIXO _conferencia e extensao .xlsx (o sufixo evita confundir a saida com a
razao que entrou), sanitizado pra Windows; colisao no ZIP ganha sufixo _2/_3
— NUNCA sobrescreve em silencio."""
from relatorio.nomes import nome_excel, nomes_sem_colisao


# --- nome_excel: stem do arquivo de origem + _conferencia.xlsx ---------------

def test_acrescenta_sufixo_de_conferencia_e_altera_a_extensao():
    assert nome_excel("golden_sintetico.xls") == "golden_sintetico_conferencia.xlsx"
    assert nome_excel("razao.XLSX") == "razao_conferencia.xlsx"


def test_sem_extensao_so_acrescenta_o_sufixo():
    assert nome_excel("razao") == "razao_conferencia.xlsx"


def test_preserva_pontos_internos_do_nome():
    # so a ULTIMA extensao cai — ponto no meio do nome e' nome, nao extensao
    assert nome_excel("golden.sintetico.versao2.xls") == "golden.sintetico.versao2_conferencia.xlsx"


def test_sanitiza_caracteres_invalidos_do_windows():
    # <>:"/\|?* e controle nao podem ir pro nome do arquivo no servidor
    assert nome_excel('raz<a>o:"ruim"|?*.xls') == "raz_a_o__ruim_____conferencia.xlsx"
    # o \t vira '_' e fica no fim do stem: o sufixo entra depois dele
    assert nome_excel("com\ncontrole\t.xls") == "com_controle__conferencia.xlsx"


def test_descarta_diretorio_do_nome_de_upload():
    # navegador nao manda caminho, mas nome com separador nunca vira path
    assert nome_excel("C:\\FICTICIA\\golden_sintetico.xls") == "golden_sintetico_conferencia.xlsx"
    assert nome_excel("../fuga/golden_sintetico.xls") == "golden_sintetico_conferencia.xlsx"


def test_nome_vazio_ou_so_lixo_cai_no_fallback():
    assert nome_excel("") == "razao_conferencia.xlsx"
    assert nome_excel("///") == "razao_conferencia.xlsx"


def test_nao_deixa_ponto_ou_espaco_no_fim_do_stem():
    # Windows rejeita nome terminando em ponto/espaco
    assert nome_excel("razao . .xls") == "razao_conferencia.xlsx"


# --- NFC/NFD chegam ao mesmo nome ASCII entregue ---------------------------
# Formas SEMPRE em escape \u explicito: literais NFD/NFC identicos no editor
# esconderiam qual forma esta no fonte (e o teste viraria tautologia).

def test_nome_nfd_do_macos_fica_ascii():
    # upload do macOS chega decomposto (a + til combinante U+0303); as duas
    # formas tem que virar UM nome so, senao o mesmo arquivo baixa duas vezes
    assert nome_excel("Raza\u0303o.xls") == "Razao_conferencia.xlsx"


def test_nome_nfc_fica_ascii_sem_acento():
    assert nome_excel("Raz\u00e3o.xls") == "Razao_conferencia.xlsx"


def test_colisao_entre_nfd_e_nfc_ganha_sufixo():
    # mesmos glifos em forma diferente SAO o mesmo nome: colidem -> _2
    assert nomes_sem_colisao(["Raz\u00e3o.xlsx", "Raza\u0303o.xlsx"]) == \
        ["Raz\u00e3o.xlsx", "Raz\u00e3o_2.xlsx"]


# --- nomes_sem_colisao: sufixo _2/_3 na ordem de chegada ----------------------

def test_sem_colisao_passa_intacto():
    assert nomes_sem_colisao(["a.xlsx", "b.xlsx"]) == ["a.xlsx", "b.xlsx"]


def test_colisao_ganha_sufixo_incremental():
    assert nomes_sem_colisao(["a.xlsx", "a.xlsx", "b.xlsx", "a.xlsx"]) == \
        ["a.xlsx", "a_2.xlsx", "b.xlsx", "a_3.xlsx"]


def test_sufixo_nao_pisa_em_nome_que_ja_existia():
    # o _2 "natural" ja estava na lista: a segunda a.xlsx pula pro _3
    assert nomes_sem_colisao(["a.xlsx", "a_2.xlsx", "a.xlsx"]) == \
        ["a.xlsx", "a_2.xlsx", "a_3.xlsx"]


# --- sufixo nao se empilha --------------------------------------------------

def test_reexportar_uma_conferencia_nao_empilha_o_sufixo():
    """Um caso: o conferente sobe de novo a planilha ja exportada (ela tem
    a aba com a razao original, entao abre normalmente) e o nome saia
    'razao_conferencia_conferencia.xlsx' — e o terceiro ciclo, com tres."""
    assert nome_excel("golden_sintetico_conferencia.xlsx") == "golden_sintetico_conferencia.xlsx"
    assert nome_excel("golden_sintetico_conferencia_conferencia.xlsx") == \
        "golden_sintetico_conferencia.xlsx"


def test_sufixo_so_cai_no_fim_do_nome():
    """'_conferencia' no MEIO e' nome do arquivo do usuario, nao sufixo nosso."""
    assert nome_excel("_conferencia_da_ana.xls") == \
        "_conferencia_da_ana_conferencia.xlsx"


def test_nome_que_e_so_o_sufixo_cai_no_fallback():
    assert nome_excel("_conferencia.xlsx") == "razao_conferencia.xlsx"


# === nomes que so diferem por maiuscula colidem no Windows =================
# O Windows (e o macOS por padrao) nao diferencia caixa: no ZIP, 'Razao_...' e
# 'razao_...' extraidos juntos se sobrescrevem. O nome devolvido guarda a caixa
# original; so a comparacao ignora a caixa.

def test_nomes_que_so_diferem_por_caixa_colidem_e_o_2o_ganha_sufixo():
    assert nomes_sem_colisao(["Razao_conferencia.xlsx", "razao_conferencia.xlsx"]) == \
        ["Razao_conferencia.xlsx", "razao_conferencia_2.xlsx"]


def test_colisao_sem_caixa_com_sufixo_que_ja_existia_e_repeticao_exata():
    assert nomes_sem_colisao(["a.xlsx", "A_2.xlsx", "a.xlsx"]) == \
        ["a.xlsx", "A_2.xlsx", "a_3.xlsx"]


def test_nenhum_par_de_nomes_iguais_sem_diferenciar_caixa():
    saida = nomes_sem_colisao(["Razao_conferencia.xlsx", "razao_conferencia.xlsx",
                               "a.xlsx", "A_2.xlsx", "a.xlsx", "RAZAO_CONFERENCIA.XLSX"])
    assert len({n.casefold() for n in saida}) == len(saida)


def test_zip_com_nomes_que_so_diferem_por_caixa_leva_os_dois_arquivos():
    import io
    import zipfile

    from relatorio.pacote import zip_relatorios
    pacote = zip_relatorios([("Razao_conferencia.xlsx", b"PK1"),
                             ("razao_conferencia.xlsx", b"PK2")])
    with zipfile.ZipFile(io.BytesIO(pacote)) as z:
        assert z.namelist() == ["Razao_conferencia.xlsx", "razao_conferencia_2.xlsx"]
        assert [z.read(n) for n in z.namelist()] == [b"PK1", b"PK2"]


def test_nome_que_nao_repete_nem_por_caixa_passa_intacto_e_com_a_caixa_original():
    """CONTROLE: a caixa do nome devolvido e' a do que entrou."""
    assert nomes_sem_colisao(["Razao.xlsx", "OUTRA.xlsx", "terceira.xlsx"]) == \
        ["Razao.xlsx", "OUTRA.xlsx", "terceira.xlsx"]

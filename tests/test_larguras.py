"""Largura das colunas da composicao pelo texto visivel.

NF pelo maior texto da tabela E do rotulo do TOTAL (as duas grades dividem
as larguras); "Idade" no minimo de 4 digitos ou o cabecalho; "Antes da NF"
com data curta dd/mm/aa na tela (o Excel continua com a data completa).
"""
from datetime import date
from decimal import Decimal

from app.apresentacao import ROTULO_TOTAL_EM_ABERTO, composicao_celulas, composicao_linhas, larguras_composicao
from app.larguras import largura_coluna, largura_texto
from core.modelo import ComposicaoItem, Origem

D = Decimal
ANTES = "Pago antes da NF no razão"


def _item(nf, idade=10, antes=None, origem=Origem.COMPRA_PERIODO):
    return ComposicaoItem(nf_numero=nf, origem=origem, valor_compra=D("10.00"),
                          total_pago=D("0.00"), total_retido=D("0.00"),
                          saldo_aberto=D("10.00"), idade_dias=idade,
                          data_compra=date(2025, 6, 10),
                          pagamento_antes_da_emissao=antes)


def test_largura_texto_segue_a_medida_do_navegador():
    # medido em canvas, Source Sans 14px: 151 (peso 400) a 155 (600)
    assert 150 <= largura_texto("Total das notas em aberto") <= 160
    assert largura_texto("(pago a maior lote 339603)") > largura_texto("603847")


def test_nf_cabe_o_maior_texto_visivel_incluindo_o_rotulo_do_total():
    linhas = composicao_linhas([_item("603847"), _item("(anterior)", None)])
    larg = larguras_composicao(linhas, ROTULO_TOTAL_EM_ABERTO)
    assert larg["NF"] == largura_coluna([ROTULO_TOTAL_EM_ABERTO, "(saldo anterior)"])
    assert larg["NF"] < 120        # o rotulo curto deixou de ser o piso


def test_linha_longa_alarga_a_nf():
    linhas = composicao_linhas([_item("(pago a maior lote 339603)")])
    larg = larguras_composicao(linhas, "TOTAL")
    assert larg["NF"] == largura_coluna(["(pago a maior lote 339603)"])


def test_idade_no_minimo_de_4_digitos_ou_o_cabecalho():
    larg = larguras_composicao(composicao_linhas([_item("1", idade=7)]), "TOTAL")
    assert larg["Idade (dias)"] == largura_coluna(["Idade", "9999"])
    assert larg["Idade (dias)"] < 56


def test_antes_da_nf_curta_na_tela_e_completa_no_excel():
    itens = [_item("41592", antes=date(2025, 5, 15))]
    assert composicao_linhas(itens)[0][ANTES] == "15/05/25"
    assert composicao_celulas(itens)[0][ANTES] == date(2025, 5, 15)
    larg = larguras_composicao(composicao_linhas(itens), "TOTAL")
    assert larg[ANTES] == largura_coluna(["Antes da NF", "15/05/25"])


# --- "Idade" fora da visao padrao (lote ainda rolava) ------------------------

def test_idade_so_entra_com_o_toggle_de_colunas():
    from app.apresentacao import colunas_da_tela
    itens = [_item("603847", idade=30)]
    assert "Idade (dias)" not in colunas_da_tela(itens, todas=False)
    assert "Idade (dias)" in colunas_da_tela(itens, todas=True)
    # o resto segue a regra de sempre (coluna com dado aparece)
    assert "Data NF" in colunas_da_tela(itens, todas=False)


def test_tela_tem_o_toggle_de_colunas_e_a_idade_aparece_com_ele():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    sintetica = Path(__file__).parent / "fixtures" / "sintetica_integra.xls"
    main = Path(__file__).parent.parent / "app" / "main.py"
    at = AppTest.from_file(str(main), default_timeout=60).run()
    at.file_uploader[0].set_value(
        (sintetica.name, sintetica.read_bytes(), "application/vnd.ms-excel")).run()
    assert len(at.exception) == 0
    grade = at.dataframe[0]
    assert "Idade (dias)" not in grade.proto.column_order
    (toggle,) = [t for t in at.toggle if t.label == "Mostrar todas as colunas"]
    toggle.set_value(True).run()
    assert "Idade (dias)" in at.dataframe[0].proto.column_order


def test_rotulos_curtos_do_total_e_o_escopo_no_tooltip():
    """Rotulos curtos "Total em aberto" / "Total com quitadas"; o escopo por extenso
    vai no tooltip da NF da grade do total."""
    from app.apresentacao import ROTULO_TOTAL_COM_QUITADAS, ajuda_total
    assert ROTULO_TOTAL_EM_ABERTO == "Total em aberto"
    assert ROTULO_TOTAL_COM_QUITADAS == "Total com quitadas"
    assert "quitadas não entram" in ajuda_total(ROTULO_TOTAL_EM_ABERTO)
    assert "em aberto e quitadas" in ajuda_total(ROTULO_TOTAL_COM_QUITADAS)

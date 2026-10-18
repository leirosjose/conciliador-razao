"""Na CASCA: linha TOTAL da composicao e bloco "Ponte do saldo".

A casca nao soma nada: os totais e a ponte chegam prontos do core
(res.totais_tabela, res.ponte). Aqui se testa rotulo, ordem, formato e que
a tela/planilha mostram o que o core mandou.
"""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.apresentacao import (
    composicao_linhas,
    itens_da_tabela,
    nota_fora_da_tabela,
    ponte_celulas,
    ponte_linhas,
    status_ponte,
    total_celulas,
    total_linha,
)
from core.conferencia import conferir
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN, identidade_das_linhas
from tests.test_ponte import COMPRA, PAGAMENTO, PAGAMENTO_NF, _conta

D = Decimal
SINTETICA = GOLDEN.parent / "sintetica_integra.xls"

MAIN = Path(__file__).parent.parent / "app" / "main.py"


@pytest.fixture(scope="module")
def golden():
    return conferir(ExcelParser().parse(GOLDEN)[0], ClassificadorHistorico())


@pytest.fixture(scope="module")
def tela_golden():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("golden_sintetico.xls", GOLDEN.read_bytes(), "application/vnd.ms-excel")).run()
    return at


# --- linha TOTAL ---------------------------------------------------------------

def test_linha_total_tem_as_mesmas_colunas_da_tabela(golden):
    colunas = list(composicao_linhas(itens_da_tabela(golden))[0])
    assert list(total_linha(golden.totais_tabela)) == colunas
    assert list(total_celulas(golden.totais_tabela)) == colunas


def test_linha_total_do_golden_soma_cada_coluna_monetaria(golden):
    total = total_linha(golden.totais_tabela)
    assert total["NF"] == "TOTAL"
    assert total["Valor compra"] == "7.100,03"
    assert total["Total pago"] == "2.839,94"
    assert total["Retido"] == total["Baixa adiant."] == "0,00"
    assert total["Alocado à mão"] == "0,00"
    assert total["EM ABERTO"] == "4.260,09"
    identidade_das_linhas([total])          # a conta de olho vale no TOTAL


def test_linha_total_deixa_data_e_idade_vazias(golden):
    total = total_linha(golden.totais_tabela)
    assert total["Data NF"] == total["Última quitação"] == ""
    assert total["Idade (dias)"] == ""
    nativa = total_celulas(golden.totais_tabela)
    assert nativa["Data NF"] is None and nativa["Idade (dias)"] is None
    assert nativa["EM ABERTO"] == golden.ponte.total_em_aberto      # Decimal


def _tabela_do_total(at):
    """O componente do TOTAL: o dataframe de UMA linha cuja NF e' o rotulo do
    total (antes "Total das notas em aberto" na visao padrao; hoje
    "Total em aberto")."""
    return next(d.value for d in at.dataframe
                if list(d.value.get("NF", [])) == ["Total em aberto"])


def test_total_e_componente_proprio_abaixo_da_tabela(tela_golden):
    """Dentro da tabela o TOTAL ficava no fim da rolagem interna e
    entrava na ordenacao por clique. Agora e' o dataframe SEGUINTE ao da
    composicao, com as mesmas colunas, e a composicao nao o contem."""
    assert len(tela_golden.exception) == 0
    composicao = tela_golden.dataframe[0].value
    assert "TOTAL" not in list(composicao["NF"])
    total = tela_golden.dataframe[1].value
    assert list(total.columns) == list(composicao.columns)
    # o rotulo diz o escopo do total (o Excel segue com "TOTAL")
    assert list(total["NF"]) == ["Total em aberto"]
    rodape = total.iloc[0]
    assert rodape["EM ABERTO"] == "4.260,09"
    assert rodape["Valor compra"] == "7.100,03"
    assert rodape["Data NF"] == ""


def test_tabela_e_total_dividem_as_mesmas_larguras_fixas(tela_golden):
    """Duas grades so' alinham coluna a coluna se cada coluna tiver a MESMA
    largura em PIXELS nas duas -- largura por conteudo daria uma largura por
    tabela. Lido do que a tela RENDERIZOU (config de coluna do proto)."""
    import json
    tabela, total = (json.loads(tela_golden.dataframe[i].proto.columns)
                     for i in (0, 1))
    colunas = [c for c in tabela if c != "_index"]
    assert colunas == [c for c in total if c != "_index"]
    for nome in colunas:
        assert isinstance(tabela[nome]["width"], int), nome
        assert total[nome]["width"] == tabela[nome]["width"], nome
        assert total[nome].get("alignment") == tabela[nome].get("alignment")


def test_total_reage_a_alocacao_manual():
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sintetica_integra.xls", SINTETICA.read_bytes(),
         "application/vnd.ms-excel")).run()
    assert _tabela_do_total(at).iloc[0]["Alocado à mão"] == "0,00"
    at.selectbox[0].select_index(0).run()          # lote 3013 (3.000,00) -> NF 1111
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert _tabela_do_total(at).iloc[0]["Alocado à mão"] == "3.000,00"


# --- bloco "Ponte do saldo" ----------------------------------------------------

ROTULOS_PONTE = [
    "Saldo anterior",
    "(+) Compras do período",
    "(+) Transferências de outra conta do fornecedor",
    "(-) Pagamentos casados",
    "(-) Retenções",
    "(-) Baixas de adiantamento",
    "(-) Alocado à mão",
    "(=) Em aberto NF a NF",
    "(-) Pagamentos sem NF em período já zerado",
    "(=) Em aberto pela composição",
    "(-) Débitos sem destino",
    "(+) Créditos sem destino",
    "(-) Declarado fora da composição",
    "(=) Saldo final apurado",
    "Saldo final Domínio",
]


def test_ponte_do_golden_na_ordem_com_os_zeros(golden):
    celulas = ponte_celulas(golden.ponte)
    assert [c["Linha"] for c in celulas] == ROTULOS_PONTE
    valores = {c["Linha"]: c["Valor"] for c in celulas}
    assert valores["Saldo anterior"] == D("429.26")
    assert valores["(+) Compras do período"] == D("7100.03")
    assert valores["(-) Pagamentos casados"] == D("3269.20")
    assert valores["(-) Retenções"] == D("0.00")          # o zero aparece
    assert valores["(=) Em aberto pela composição"] == D("4260.09")
    assert valores["(=) Saldo final apurado"] == D("4260.09")
    assert valores["Saldo final Domínio"] == D("4260.09")


def test_ponte_em_texto_formata_moeda_br(golden):
    linhas = ponte_linhas(golden.ponte)
    assert linhas[1] == {"Linha": "(+) Compras do período", "Valor": "7.100,03"}
    assert linhas[4]["Valor"] == "0,00"


def test_alocado_a_mao_negativo_inverte_o_operador_e_mostra_o_modulo(golden):
    """Credito alocado (compra nova) entra negativo no liquido do core;
    a tela nunca imprime "(-) ... -80,00"."""
    ponte = replace(golden.ponte, total_alocado_manual=D("-80.00"),
                    total_fora_composicao=D("-12.00"))
    valores = {c["Linha"]: c["Valor"] for c in ponte_celulas(ponte)}
    assert valores["(+) Alocado à mão"] == D("80.00")
    assert valores["(+) Declarado fora da composição"] == D("12.00")
    assert "(-) Alocado à mão" not in valores


@pytest.mark.parametrize("erro, com_balde, severidade, texto", [
    ("0.00", False, "OK", "OK"),                 # so' com balde vazio
    ("0.00", True, "PENDENTE", "Fecha — R$ 300,00 sem destino"),
    ("0.01", True, "PENDENTE", "Fecha — R$ 300,00 sem destino; diferença "
                               "de 0,01 dentro da tolerância"),
    ("5.00", True, "DIVERGE", "DIVERGE 5,00"),
    ("0.01", False, "DIVERGE", "DIVERGE 0,01"),
])
def test_status_da_ponte_e_o_do_veredito(erro, com_balde, severidade, texto):
    """Sem juiz proprio -- o rotulo sai do status do self_check e o valor
    da diferenca e' sempre impresso. Identidade fechando COM balde nao
    e' "OK" verde (passava a impressao de conta conciliada); e' "Fecha" na cor
    do INCOMPLETO, dizendo quanto ainda esta no balde."""
    linhas = [(COMPRA.format(nf="5001"), "0.00", "1000.00", 2)]
    if com_balde:
        linhas.append((PAGAMENTO, "300.00", "0.00", 5))
    res = conferir(_conta(linhas, erro_no_saldo_final=erro),
                   ClassificadorHistorico())
    assert status_ponte(res) == (severidade, texto)


def test_status_com_so_decisao_fora_da_composicao_tambem_nao_e_ok():
    """Balde vazio mas item declarado fora: o veredito e' INCOMPLETO
    (ressalva) e a composicao difere do Dominio por esse valor -- nao e'
    conta conciliada."""
    from core.modelo import AlocacaoManual, DestinoAlocacao
    conta = _conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                    (PAGAMENTO, "300.00", "0.00", 5)])
    item = conferir(conta, ClassificadorHistorico()).balde[0]
    res = conferir(conta, ClassificadorHistorico(), [AlocacaoManual(
        item_id=item.identificador, destino=DestinoAlocacao.FORA_DA_COMPOSICAO,
        rotulo="pagamento de outro fornecedor")])
    assert res.balde == []
    assert status_ponte(res) == (
        "PENDENTE", "Fecha — R$ 300,00 declarado fora da composição")


def test_nota_aparece_quando_o_anterior_quitado_some_da_tabela(golden):
    nota = nota_fora_da_tabela(golden.totais_tabela)
    # uma frase so'
    assert nota == ("O saldo anterior de R$ 429,26 foi pago no período: a "
                    "linha zerou e fica fora dos totais de Valor compra e "
                    "Total pago da tabela.")


def test_sem_nota_quando_os_totais_batem_com_a_ponte():
    res = conferir(_conta([(COMPRA.format(nf="5001"), "0.00", "1000.00", 2),
                           (PAGAMENTO_NF.format(nf="4001"), "200.00", "0.00", 5)],
                          saldo_anterior="-700.00"), ClassificadorHistorico())
    assert nota_fora_da_tabela(res.totais_tabela) is None


def test_nota_nomeia_so_a_coluna_que_difere(golden):
    totais = replace(golden.totais_tabela, pago_fora_da_tabela=D("0.00"))
    assert nota_fora_da_tabela(totais) == (
        "O saldo anterior pago no período fica fora do total de Valor compra "
        "da tabela (R$ 429,26): a linha zerou.")


def _textos(at):
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


def _ponte(at):
    """A ponte vive num expander cujo titulo comeca por "Ponte do saldo"."""
    exp = next(e for e in at.expander if e.label.startswith("Ponte do saldo"))
    return exp, next(m.value for m in exp.markdown
                     if "Saldo final apurado" in m.value)


def test_tela_mostra_a_ponte_com_ok_e_a_nota(tela_golden):
    exp, tabela = _ponte(tela_golden)
    assert "| **(=) Saldo final apurado** | **4.260,09** |" in tabela
    # linha zerada so' com o toggle "Mostrar todas as linhas"
    assert "(-) Retenções" not in tabela
    assert ":green[**OK**]" in tabela
    assert any("429,26 foi pago no período" in c.value for c in exp.caption)


def test_ponte_reage_a_alocacao_manual_ao_vivo():
    """d) sem codigo de reatividade: a tela reroda conferir() a cada decisao
    e a ponte sai dele, como o placar."""
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("sintetica_integra.xls", SINTETICA.read_bytes(),
         "application/vnd.ms-excel")).run()
    _, antes = _ponte(at)
    assert "(-) Alocado à mão" not in antes        # zerada fica escondida
    at.selectbox[0].select_index(0).run()          # lote 3013 (3.000,00) -> NF 1111
    next(b for b in at.button if b.label == "Aplicar").click().run()
    assert len(at.exception) == 0
    _, depois = _ponte(at)
    assert "| (-) Alocado à mão | 3.000,00 |" in depois
    # a sintetica ainda tem balde depois da alocacao: fecha, mas nao e' OK
    assert ":yellow[**Fecha** — R\\$" in depois
    assert ":green[" not in depois

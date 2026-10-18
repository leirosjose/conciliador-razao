"""Fixtures SINTETICAS: dado real de cliente NAO entra no git.

Geradas por tests/fixtures/gerar_sinteticas.py (deterministico, commitado):
  - sintetica_integra.xls    ponteiro correto -> rota normal do xlrd
  - sintetica_corrompida.xls o MESMO defeito binario do exportador do Dominio
                             (BLANKs orfaos apos o EOF dos globals, offset do
                             BOUNDSHEET desatualizado — inverso do reparo)
  - sintetica_adulterada.xls corrompida + debito alterado -> gate rejeita

Conteudo (numeros LIMPOS, escolhidos pra asserts ao centavo estaveis):
Conta 7777 FORNECEDOR FICTICIO LTDA, saldo anterior -10.000,00, saldo na COL 11
(coluna movel), Total da conta 18.150,00 D / 13.250,00 C, saldo final -5.100,00.
Cenarios: compra multi-linha (NF 1111 = 1.000 + 2.100), pagamento por numero,
parcelas iguais (2222 = 2x 1.200), retencao com NF (IRRF 150 na 3333), baixa
exata == |saldo anterior| (10.000), baixa parcial (3.000 -> balde), multi-NF
("NF 4444 E NFS: 5555" com soma exata -> casa um-pra-muitos),
estorno, credito nao classificado, debito sem padrao.
Identidade: gap 2.650,00 == Σ(D−C) do balde.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import xlrd

from app.pipeline import processar_excel
from core.modelo import MotivoRevisao, Nivel, Origem
from parser.excel import ErroLeituraExcel, ExcelParser
from tests.helpers import identidade_da_tabela

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"
INTEGRA = FIXTURES / "sintetica_integra.xls"
INTEGRA_XLSX = FIXTURES / "sintetica_integra.xlsx"    # mesmos cenarios, rota openpyxl
CORROMPIDA = FIXTURES / "sintetica_corrompida.xls"
ADULTERADA = FIXTURES / "sintetica_adulterada.xls"

ZERO = D("0.00")


def test_corrompida_estoura_o_xlrd_puro():
    """O defeito binario e o MESMO do Dominio: o ponteiro do BOUNDSHEET cai num
    BLANK (0x0201) orfao -> 'Expected BOF record; found b'\\x01\\x02...'."""
    with pytest.raises(xlrd.XLRDError, match="Expected BOF"):
        xlrd.open_workbook(str(CORROMPIDA))


def test_corrompida_abre_pela_rota_de_reparo_com_self_check_verde():
    parser = ExcelParser()
    contas = parser.parse(CORROMPIDA)      # gate roda: parse aceitou = verde
    assert parser.reparado is True
    assert len(contas) == 1
    conta = contas[0]
    assert conta.codigo == "7777"
    assert conta.nome == "FORNECEDOR FICTICIO LTDA"
    assert conta.saldo_anterior == D("-10000.00")      # saldo na col 11 (movel)
    assert conta.total_debito_dominio == D("18150.00")
    assert conta.total_credito_dominio == D("13250.00")
    assert sum((l.debito for l in conta.lancamentos), ZERO) == D("18150.00")
    assert sum((l.credito for l in conta.lancamentos), ZERO) == D("13250.00")
    assert conta.saldo_final == D("-5100.00")


@pytest.mark.parametrize("caminho", [INTEGRA, INTEGRA_XLSX],
                         ids=["xls-xlrd", "xlsx-openpyxl"])
def test_integra_abre_na_rota_normal(caminho):
    parser = ExcelParser()
    contas = parser.parse(caminho)
    assert parser.reparado is False
    assert contas[0].codigo == "7777"
    assert contas[0].saldo_anterior == D("-10000.00")


def test_adulterada_e_rejeitada_pelo_gate():
    """Corrompida + debito adulterado: repara mas o self-check de totais NAO
    fecha -> ErroLeituraExcel pedindo re-exportacao (nunca aceita em silencio)."""
    with pytest.raises(ErroLeituraExcel) as exc:
        ExcelParser().parse(ADULTERADA)
    msg = str(exc.value)
    assert "self-check" not in msg
    assert "7777" in msg
    assert "reparo não é confiável" in msg         # o fato, sem instrucao


def test_gate_do_reparo_fala_em_frase_e_em_reais_nao_em_codigo_interno():
    """O gate dizia `'self_check_total_debito' (esperado 18150.00,
    encontrado 17150.00)` -- codigo interno e Decimal cru."""
    with pytest.raises(ErroLeituraExcel) as exc:
        ExcelParser().parse(ADULTERADA)
    msg = str(exc.value)
    assert "self_check_" not in msg
    assert "a conta 7777 (FORNECEDOR FICTICIO LTDA): soma dos débitos NÃO confere com 'Total da conta'" in msg
    assert "(esperado 18.150,00, encontrado 17.150,00)" in msg
    assert "18150.00" not in msg


@pytest.mark.parametrize("caminho,reparado", [(CORROMPIDA, True),
                                              (INTEGRA_XLSX, False)],
                         ids=["xls-reparo", "xlsx-openpyxl"])
def test_pipeline_completo_cenarios_e_identidade(caminho, reparado):
    """Os cenarios na sintetica, ate o veredito, com asserts ao centavo
    estaveis. Parametrizado nas DUAS rotas do parser: o core nao sabe qual
    rota alimentou."""
    proc = processar_excel(caminho)
    assert proc.arquivo_reparado is reparado
    res = proc.resultados[0]

    por_nf = {i.nf_numero: i for i in res.itens}
    # compra multi-linha somada + pagamento por numero
    assert por_nf["1111"].valor_compra == D("3100.00")
    assert por_nf["1111"].total_pago == D("1200.00")
    assert por_nf["1111"].saldo_aberto == D("1900.00")
    # parcelas iguais casadas por valor -> 2222 quitada, fora da composicao
    assert "2222" not in por_nf
    # retencao vinculada por numero conta como quitacao
    assert por_nf["3333"].total_retido == D("150.00")
    assert por_nf["3333"].saldo_aberto == D("750.00")
    # multi-NF com soma exata: 1.000,00 = 4444 (650) + 5555 (350) casa
    # um-pra-muitos e as duas NFs saem da composicao, quitadas integralmente
    assert "4444" not in por_nf
    assert "5555" not in por_nf
    assert por_nf["6666"].saldo_aberto == D("5100.00")
    # baixa exata consumiu o saldo anterior, IDENTIFICADA, resto zero
    anterior = por_nf["(anterior)"]
    assert anterior.origem is Origem.SALDO_ANTERIOR
    assert anterior.total_baixado == D("10000.00")
    assert anterior.saldo_aberto == ZERO
    assert anterior.valor_compra == D("10000.00")     # saldo trazido
    identidade_da_tabela(res.itens)                   # em TODA linha

    # a foto completa -- as quitadas em canal proprio, inclusive as
    # duas do um-pra-muitos (4444 + 5555 = 1.000,00), prova de que fecharam juntas
    quitadas = {i.nf_numero: i for i in res.quitadas}
    assert sorted(quitadas) == ["2222", "4444", "5555"]
    assert quitadas["4444"].total_pago == D("650.00")          # alocacao multi-NF
    assert quitadas["2222"].total_pago == D("2400.00")
    assert all(i.saldo_aberto == ZERO for i in res.quitadas)
    identidade_da_tabela(res.quitadas)
    # 4 -> 5 itens: o credito de 250,00 da TRANSFERENCIA DE SALDOS deixou
    # de ser "nao reconhecido" e virou linha propria. Esta fixture e' a UNICA
    # cobertura de CI da regra.
    assert len(res.itens) == 5
    transf = por_nf["(transferência lote 3015)"]
    assert transf.origem is Origem.TRANSFERENCIA_SALDO
    assert transf.valor_compra == D("250.00")
    assert transf.saldo_aberto == D("250.00")
    assert transf.data_compra == date(2025, 3, 3)      # quando chegou AQUI
    # e o alerta irmao do saldo anterior nao detalhado
    transf_alerta = [a for a in res.achados
                     if a.codigo == "transferencia_nao_detalhada"]
    assert len(transf_alerta) == 1
    assert transf_alerta[0].nivel is Nivel.ALERTA
    assert transf_alerta[0].encontrado == D("250.00")

    # balde: baixa parcial + debito sem padrao + estorno (o credito de 250,00
    # saiu ao virar linha propria; o multi-NF ja tinha saido)
    lados = sorted((l.debito - l.credito
                    for item in res.balde for l in item.lancamentos))
    assert lados == [D("-500.00"), D("400.00"), D("3000.00")]
    motivos = {i.motivo for i in res.balde}
    # o estorno de 500,00 tem motivo PROPRIO -- ele nao pareia (a baixa da
    # sintetica e de 3.000,00, valor diferente), entao sobra como ESTORNO_SEM_PAR
    assert motivos == {MotivoRevisao.SEM_VINCULO, MotivoRevisao.NAO_CLASSIFICADO,
                       MotivoRevisao.ESTORNO_SEM_PAR}

    # veredito INCOMPLETO com identidade exata: gap == Σ(D−C) do balde.
    # 2.650,00 -> 2.900,00: os 250,00 migraram de inexplicado (balde) pra
    # explicado (composicao), e a identidade continua fechando ao centavo.
    assert not any(a.nivel is Nivel.ERRO for a in res.achados)
    incompleto = [a for a in res.achados if a.nivel is Nivel.INCOMPLETO][0]
    assert incompleto.encontrado == D("2900.00")
    assert incompleto.esperado == D("2900.00")


@pytest.mark.parametrize("lado", ["debito", "credito", "saldo"])
def test_gate_frase_exata_sem_termo_interno(lado):
    from dataclasses import replace
    conta = ExcelParser().parse(INTEGRA)[0]
    if lado == "debito":
        conta = replace(conta, total_debito_dominio=D("19150.00"))
        detalhe = "soma dos débitos NÃO confere com 'Total da conta' (esperado 19.150,00, encontrado 18.150,00)"
    elif lado == "credito":
        conta = replace(conta, total_credito_dominio=D("14250.00"))
        detalhe = "soma dos créditos NÃO confere com 'Total da conta' (esperado 14.250,00, encontrado 13.250,00)"
    else:
        ultimo = replace(conta.lancamentos[-1], saldo_exercicio=D("-5095.00"))
        conta = replace(conta, lancamentos=[*conta.lancamentos[:-1], ultimo])
        detalhe = "saldo recalculado NÃO confere com a última linha (esperado -5.095,00, encontrado -5.100,00)"
    with pytest.raises(ErroLeituraExcel) as exc:
        ExcelParser._gate_pos_reparo([conta], "x.xls")
    assert str(exc.value) == (
        "'x.xls': o arquivo veio corrompido do Domínio e o reparo não é confiável — "
        "a conta 7777 (FORNECEDOR FICTICIO LTDA): " + detalhe + ".")
    assert "self-check" not in str(exc.value)
    assert "self_check" not in str(exc.value)

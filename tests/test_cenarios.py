"""O golden sintetico e os 6 cenarios de exemplo, ponta a ponta.

Cada planilha (gerada por tests/fixtures/gerar_sinteticas.py) passa pelo MESMO
caminho da tela e da planilha exportada: app.pipeline.processar_excel, e o
veredito/notas pelas funcoes de app.apresentacao que a tela e o Excel usam.
Nada e' recalculado aqui: o teste so compara o resultado com o DECLARADO
(tests/GOLDEN.md explica cada caso). Dinheiro sempre em Decimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from app.apresentacao import notas_composicao_texto, status_conta
from app.pipeline import processar_excel

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal

SELF_CHECKS_OK = (
    ("OK", "self_check_total_debito"),
    ("OK", "self_check_total_credito"),
    ("OK", "self_check_saldo_final"),
    ("OK", "self_check_saldo_corrente"),
    ("OK", "self_check_composicao"),
)


@dataclass(frozen=True)
class Esperado:
    arquivo: str
    lancamentos: int
    status: str
    # (NF, compra, pago, aberto) de cada linha da composicao, na ordem da tabela
    itens: tuple[tuple[str, Decimal, Decimal, Decimal], ...]
    # (NF, compra, pago, retido, aberto, baixado) das NFs quitadas no periodo
    quitadas: tuple[tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal], ...]
    total_em_aberto: Decimal
    saldo_final: Decimal                   # saldo do Dominio (credor = negativo)
    # (motivo, ((debito, credito) de cada lancamento do item))
    balde: tuple[tuple[str, tuple[tuple[Decimal, Decimal], ...]], ...] = ()
    achados: tuple[tuple[str, str], ...] = SELF_CHECKS_OK   # (nivel, codigo), incluindo OK
    notas: tuple[str, ...] = ()


ESPERADOS = {
    "golden": Esperado(
        arquivo="golden_sintetico.xls", lancamentos=12, status="FECHA",
        itens=(("618204", D("4700.00"), D("1880.00"), D("2820.00")),
               ("274591", D("2400.03"), D("959.94"), D("1440.09"))),
        quitadas=(), total_em_aberto=D("4260.09"), saldo_final=D("-4260.09")),
    "1_conciliado": Esperado(
        arquivo="cenario_1_conciliado.xls", lancamentos=7, status="FECHA",
        itens=(("791306", D("4316.80"), D("2877.86"), D("1438.94")),),
        quitadas=(("793018", D("2957.35"), D("2912.99"), D("44.36"), D("0.00"), D("0.00")),),
        total_em_aberto=D("1438.94"), saldo_final=D("-1438.94")),
    "2_centavo": Esperado(
        arquivo="cenario_2_centavo.xls", lancamentos=5, status="FECHA",
        itens=(("802741", D("2853.47"), D("2853.48"), D("-0.01")),
               ("805396", D("1586.90"), D("0.00"), D("1586.90"))),
        quitadas=(), total_em_aberto=D("1586.89"), saldo_final=D("-1586.89"),
        notas=("NF 802741: quitada com arredondamento de 0,01 (dentro da tolerância de centavos)",)),
    "3_sem_par": Esperado(
        arquivo="cenario_3_sem_par.xls", lancamentos=7, status="INCOMPLETO",
        itens=(("889457", D("3419.65"), D("0.00"), D("3419.65")),),
        quitadas=(("886120", D("5827.40"), D("5827.40"), D("0.00"), D("0.00"), D("0.00")),),
        total_em_aberto=D("3419.65"), saldo_final=D("-2155.27"),
        balde=(("SEM_VINCULO", ((D("1264.38"), D("0.00")),)),),
        achados=SELF_CHECKS_OK[:4] + (("INCOMPLETO", "self_check_composicao"),)),
    "4_estorno": Esperado(
        arquivo="cenario_4_estorno.xls", lancamentos=7, status="FECHA",
        itens=(("915270", D("2608.09"), D("1304.05"), D("1304.04")),),
        quitadas=(("912604", D("3684.27"), D("3684.27"), D("0.00"), D("0.00"), D("0.00")),),
        total_em_aberto=D("1304.04"), saldo_final=D("-1304.04"),
        achados=SELF_CHECKS_OK + (("ALERTA", "estorno_pareado"),)),
    "5_duplicidade": Esperado(
        arquivo="cenario_5_duplicidade.xls", lancamentos=6, status="FECHA",
        itens=(("931582", D("4327.88"), D("2163.94"), D("2163.94")),),
        quitadas=(("934027", D("1478.61"), D("1478.61"), D("0.00"), D("0.00"), D("0.00")),),
        total_em_aberto=D("2163.94"), saldo_final=D("-2163.94"),
        achados=SELF_CHECKS_OK + (("ALERTA", "possivel_compra_repetida"),)),
    "6_pago_a_maior": Esperado(
        arquivo="cenario_6_pago_a_maior.xls", lancamentos=5, status="FECHA",
        itens=(("952608", D("4105.72"), D("2052.86"), D("2052.86")),
               ("(pago a maior lote 3133419)", D("0.00"), D("177.38"), D("-177.38"))),
        quitadas=(("947215", D("1837.26"), D("1837.26"), D("0.00"), D("0.00"), D("0.00")),
                  ("947216", D("966.43"), D("966.43"), D("0.00"), D("0.00"), D("0.00"))),
        total_em_aberto=D("1875.48"), saldo_final=D("-1875.48"),
        achados=SELF_CHECKS_OK + (("ALERTA", "pago_a_maior"),)),
}


@pytest.mark.parametrize("caso", list(ESPERADOS))
def test_resultado_declarado(caso):
    esp = ESPERADOS[caso]
    resultados = processar_excel(FIXTURES / esp.arquivo).resultados
    assert len(resultados) == 1
    res = resultados[0]

    assert len(res.conta.lancamentos) == esp.lancamentos
    assert status_conta(res.achados)[0] == esp.status
    assert tuple((i.nf_numero, i.valor_compra, i.total_pago, i.saldo_aberto)
                 for i in res.itens) == esp.itens
    assert tuple((q.nf_numero, q.valor_compra, q.total_pago, q.total_retido,
                  q.saldo_aberto, q.total_baixado)
                 for q in res.quitadas) == esp.quitadas
    assert res.totais_em_aberto.saldo_aberto == esp.total_em_aberto
    assert res.conta.saldo_final == esp.saldo_final
    assert tuple((b.motivo.name, tuple((l.debito, l.credito) for l in b.lancamentos))
                 for b in res.balde) == esp.balde
    assert tuple(sorted((a.nivel.name, a.codigo) for a in res.achados)) == tuple(sorted(esp.achados))
    assert tuple(notas_composicao_texto(res.itens)) == esp.notas

"""Pagamento que CITA NFs e passa da soma delas.

Fase 1.5: todas as citadas em aberto (as travas de sempre) e pago > soma dos
saldos + 0,01 -> cada NF citada e' quitada pelo saldo dela e a sobra vira LINHA
PROPRIA "(pago a maior lote X)", fora do balde, EM ABERTO negativo. A sobra nao
ganha rotulo (juros? adiantamento? outro titulo?): o alerta `pago_a_maior` diz
o fato e fica "nao decidido". Pago < soma segue no balde, como sempre.

Junto (decisao da aprovacao): pagamento anterior a emissao casa e a LINHA diz a
data -- coluna "Pago antes da NF no razao", mesmo tratamento pra todo casamento.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.conferencia import conferir
from core.modelo import Conta, MotivoRevisao, Origem
from parser.historico import ClassificadorHistorico
from tests.helpers import identidade_da_tabela, lanc

D = Decimal
CLF = ClassificadorHistorico()


def _compra(nf, valor, dia=8):
    return lanc(f"Vr. compras conf. {nf} FORN FICTICIO", numero=f"c{nf}",
                data=date(2025, 12, dia), credito=valor)


def _pgto_multi(valor, lote="810116", dia=5, nfs="810111 E NF 810120"):
    return lanc(f"Valor ref. a PGTO A FORN FICTICIO NFS:{nfs}", numero=lote,
                data=date(2025, 12, dia), debito=valor)


def _casar(*lancs):
    return casar([(l, CLF.classificar(l)) for l in lancs])


def _nf(res, numero):
    return next(n for n in res.nfs if n.numero == numero)


# --- o caso (exemplo 810116, sintetico) ------------------------------------------

def test_cita_duas_nfs_e_passa_da_soma_quita_as_duas_e_mostra_a_sobra():
    res = _casar(_compra("810111", "1393.65"), _compra("810120", "7842.30"),
                 _pgto_multi("10206.90"))
    assert res.balde == []
    assert _nf(res, "810111").saldo_aberto == D("0.00")
    assert _nf(res, "810120").saldo_aberto == D("0.00")
    linha = _nf(res, "(pago a maior lote 810116)")
    assert linha.pago_a_maior is True
    assert linha.valor_compra == D("0.00")
    assert linha.saldo_aberto == D("-970.95")
    assert linha.data_compra == date(2025, 12, 5)     # a data do lancamento
    # o dinheiro e' conservado: 1.393,65 + 7.842,30 + 970,95 == 10.206,90
    total = sum((a.valor for n in res.nfs for a in n.alocacoes), D("0.00"))
    assert total == D("10206.90")


def test_alerta_pago_a_maior_traz_os_tres_numeros_e_o_lote():
    res = _casar(_compra("810111", "1393.65"), _compra("810120", "7842.30"),
                 _pgto_multi("10206.90"))
    (a,) = [a for a in res.achados if a.codigo == "pago_a_maior"]
    assert a.referencia == "(pago a maior lote 810116)"
    assert a.valores == {"pagamento": D("10206.90"), "soma": D("9235.95"),
                         "sobra": D("970.95")}
    assert [l.numero for l in a.lancamentos] == ["810116"]


# --- o que NAO muda --------------------------------------------------------------

def test_pago_menor_que_a_soma_continua_no_balde():
    res = _casar(_compra("810111", "1393.65"), _compra("810120", "7842.30"),
                 _pgto_multi("9000.00"))
    assert [i.motivo for i in res.balde] == [MotivoRevisao.MULTI_NF_NAO_CONFERE]
    assert not [n for n in res.nfs if n.pago_a_maior]


def test_nf_citada_fora_da_conta_continua_no_balde():
    """Trava: so' NFs CITADAS e TODAS em aberto. Uma citada sem compra aqui ->
    balde, nunca sobra pra linha propria."""
    res = _casar(_compra("810111", "1393.65"), _pgto_multi("10206.90"))
    assert [i.motivo for i in res.balde] == [MotivoRevisao.MULTI_NF_NAO_CONFERE]
    assert not [n for n in res.nfs if n.pago_a_maior]


def test_sobra_dentro_do_centavo_e_o_casamento_exato_de_sempre():
    res = _casar(_compra("810111", "1393.65"), _compra("810120", "7842.30"),
                 _pgto_multi("9235.96"))
    assert res.balde == []
    assert not [n for n in res.nfs if n.pago_a_maior]
    assert not [a for a in res.achados if a.codigo == "pago_a_maior"]


# --- ponta a ponta: composicao, identidade, ponte --------------------------------

def _conta(*lancs, anterior="0.00"):
    return Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                 data_fim_periodo=date(2025, 12, 31), saldo_anterior=D(anterior),
                 lancamentos=list(lancs))


def _pago_a_maior_com_saldo():
    """Em ordem de data e com o saldo corrente impresso (a ponte compara com o
    saldo final do Dominio, que e' o da ultima linha)."""
    from dataclasses import replace
    return _conta(replace(_pgto_multi("10206.90"), saldo_exercicio=D("10206.90")),
                  replace(_compra("810111", "1393.65"), saldo_exercicio=D("8813.25")),
                  replace(_compra("810120", "7842.30"), saldo_exercicio=D("970.95")),
                  replace(_compra("810112", "2941.92", dia=11),
                          saldo_exercicio=D("-1970.97")))


def test_a_linha_entra_na_composicao_e_a_ponte_fecha():
    res = conferir(_pago_a_maior_com_saldo(), CLF)
    linha = next(i for i in res.itens if i.origem is Origem.PAGO_A_MAIOR)
    assert linha.nf_numero == "(pago a maior lote 810116)"
    assert linha.saldo_aberto == D("-970.95")
    assert linha.total_pago == D("970.95")
    identidade_da_tabela(res.itens)
    # 2.941,92 - 970,95: a composicao soma o negativo
    assert sum((i.saldo_aberto for i in res.itens), D("0.00")) == D("1970.97")
    assert res.ponte.total_pago == D("10206.90")
    assert res.ponte.diferenca == D("0.00")
    # a linha nao e' NF: nao e' quitada, nao alerta juros, nao vira gemea
    assert not [q for q in res.quitadas if q.origem is Origem.PAGO_A_MAIOR]
    assert not [a for a in res.achados if a.codigo == "possivel_juros"]


# --- aviso de data na linha (pagamento anterior a emissao) ----------------------

def test_linha_traz_a_data_do_pagamento_anterior_a_emissao():
    """Pago em 05/12, NFs emitidas em 08/12: as duas linhas dizem quando."""
    res = conferir(_conta(_compra("810111", "1393.65"), _compra("810120", "7842.30"),
                          _pgto_multi("10206.90")), CLF)
    por_nf = {i.nf_numero: i for i in res.itens + res.quitadas}
    assert por_nf["810111"].pagamento_antes_da_emissao == date(2025, 12, 5)
    assert por_nf["810120"].pagamento_antes_da_emissao == date(2025, 12, 5)
    # a linha do pago a maior nao e' nota: nao tem emissao pra comparar
    assert por_nf["(pago a maior lote 810116)"].pagamento_antes_da_emissao is None


def test_aviso_vale_pra_casamento_por_numero_e_por_valor_e_pega_o_primeiro():
    """Mesmo tratamento pra todo casamento (os 41 do corpus): por numero, por
    valor; com 2 anteriores, a coluna leva o PRIMEIRO."""
    res = conferir(_conta(
        lanc("Pago conf. NF 5000", numero="p1", data=date(2025, 3, 1), debito="100.00"),
        lanc("Pago conf. NF 5000", numero="p2", data=date(2025, 3, 5), debito="100.00"),
        lanc("Vr. compras conf. 5000 FORN", numero="c1", data=date(2025, 3, 10),
             credito="300.00"),
        lanc("Pago conf. FORN", numero="p3", data=date(2025, 4, 2), debito="70.00"),
        lanc("Vr. compras conf. 6000 FORN", numero="c2", data=date(2025, 4, 10),
             credito="70.00"),
    ), CLF)
    por_nf = {i.nf_numero: i for i in res.itens + res.quitadas}
    assert por_nf["5000"].pagamento_antes_da_emissao == date(2025, 3, 1)
    assert por_nf["6000"].pagamento_antes_da_emissao == date(2025, 4, 2)


def test_pagamento_depois_da_emissao_nao_marca():
    res = conferir(_conta(
        lanc("Vr. compras conf. 5000 FORN", numero="c1", data=date(2025, 3, 10),
             credito="300.00"),
        lanc("Pago conf. NF 5000", numero="p1", data=date(2025, 3, 10), debito="100.00"),
    ), CLF)
    assert res.itens[0].pagamento_antes_da_emissao is None


# --- casca ---------------------------------------------------------------------

def _res_pago_a_maior_sintetico():
    return conferir(_pago_a_maior_com_saldo(), CLF)


def test_tela_nao_repete_a_marca_na_linha_que_ja_se_chama_pago_a_maior():
    from app.apresentacao import composicao_linhas
    nomes = [l["NF"] for l in composicao_linhas(_res_pago_a_maior_sintetico().itens)]
    assert "(pago a maior lote 810116)" in nomes
    assert not [n for n in nomes if n.count("pago a maior") > 1]


def test_frase_e_classe_do_pago_a_maior():
    from app.apresentacao import NAO_DECIDIDO, classe_alerta, frase_achado
    (a,) = [a for a in _res_pago_a_maior_sintetico().achados if a.codigo == "pago_a_maior"]
    frase = frase_achado(a)
    assert "lote 810116" in frase and "810111" in frase and "810120" in frase
    assert "10.206,90" in frase and "9.235,95" in frase and "970,95" in frase
    assert classe_alerta(a) == NAO_DECIDIDO


def test_coluna_do_aviso_aparece_na_tela_so_quando_alguma_linha_tem_o_dado():
    from app.apresentacao import colunas_visiveis
    res = _res_pago_a_maior_sintetico()
    com = res.itens + res.quitadas
    assert "Pago antes da NF no razão" in colunas_visiveis(com)
    assert "Pago antes da NF no razão" not in colunas_visiveis(res.itens)

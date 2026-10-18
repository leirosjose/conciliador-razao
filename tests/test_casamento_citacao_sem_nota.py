"""Pagamento que cita NF SEM compra na razao, quando as citacoes
desse tipo ja passaram do saldo anterior E existe candidata por valor, perde a
citacao e vai pra Fase 2.

NF citada sem compra no periodo e' NF anterior a janela -- enquanto
o saldo anterior comporta. Quando nao comporta mais, a citacao nao pode ser NF
anterior: e' numero de boleto/documento. So' entao, e so' com
candidata por valor, o valor decide. Dados ficticios.
"""
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.modelo import Nivel
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal


def _compra(nf, valor, numero="c", dia=1):
    return (lanc(f"Vr. compras conf. {nf}", numero=numero, dia=dia, credito=valor),
            Classificacao(Tipo.COMPRA, nf_numero=nf))


def _pgto(nf, valor, numero="p", dia=5):
    return (lanc(f"PGTO NF {nf}", numero=numero, dia=dia, debito=valor),
            Classificacao(Tipo.PAGAMENTO, nf_numero=nf, nfs_citadas=(nf,)))


def _onde(res, l):
    for nf in res.nfs:
        if any(x is l for x in nf.pagamentos):
            return nf.numero
    return "balde" if any(l in i.lancamentos for i in res.balde) else None


def test_citacao_que_estoura_o_anterior_vai_pela_nf_de_mesmo_valor():
    compra, p = _compra("5001", "500.00"), _pgto("9999", "500.00")
    res = casar([compra, p], saldo_anterior=D("-100.00"))
    assert _onde(res, p[0]) == "5001"
    assert "9999" not in {nf.numero for nf in res.nfs}
    (a,) = [a for a in res.achados
            if a.codigo == "casamento_por_valor_citacao_sem_nota"]
    assert a.nivel is Nivel.ALERTA and a.referencia == "5001"
    assert a.valores == {"pagamento": D("500.00")}
    assert "9999" in a.mensagem


def test_citacao_que_cabe_no_anterior_continua_nf_anterior():
    compra, p = _compra("5001", "500.00"), _pgto("9999", "500.00")
    res = casar([compra, p], saldo_anterior=D("-500.00"))
    assert _onde(res, p[0]) == "9999"
    assert not [a for a in res.achados
                if a.codigo == "casamento_por_valor_citacao_sem_nota"]


def test_estourou_mas_sem_candidata_por_valor_a_citacao_fica():
    compra, p = _compra("5001", "500.00"), _pgto("9999", "321.07")
    res = casar([compra, p], saldo_anterior=D("-100.00"))
    assert _onde(res, p[0]) == "9999"


def test_compra_depois_do_pagamento_no_arquivo_nao_e_citacao_sem_nota():
    """A compra pode vir depois do pagamento (um caso tinha 36): o conjunto
    das NFs com compra e' da razao INTEIRA."""
    p, compra = _pgto("5001", "500.00", dia=1), _compra("5001", "500.00", dia=9)
    res = casar([p, compra], saldo_anterior=D("0.00"))
    assert _onde(res, p[0]) == "5001"


def test_so_as_citacoes_depois_do_estouro_perdem_o_numero():
    compra = _compra("5001", "400.00")
    p1 = _pgto("8888", "300.00", numero="p1", dia=2)    # cabe no anterior
    p2 = _pgto("9999", "400.00", numero="p2", dia=3)    # estoura
    res = casar([compra, p1, p2], saldo_anterior=D("-300.00"))
    assert _onde(res, p1[0]) == "8888"
    assert _onde(res, p2[0]) == "5001"


def test_nf_com_milhar_pontuado_nao_cria_nf_curta_nem_consome_o_saldo_anterior():
    """Com o classificador real: "PGTO NF 001.234" 500,00 lia a
    NF "001", que e' citacao sem compra e consumia os 500,00 do saldo anterior
    (veredito FECHA). Sem o numero, o valor decide e quita a NF 1234."""
    compras = [_compra("1234", "500.00"), _compra("9999", "700.00", numero="c2")]
    p = lanc("PGTO NF 001.234", numero="p", dia=5, debito="500.00")
    res = casar(compras + [(p, ClassificadorHistorico().classificar(p))],
                saldo_anterior=D("-500.00"))
    assert _onde(res, p) == "1234"
    assert "001" not in {nf.numero for nf in res.nfs}


def test_formato_pagto_ref_com_milhar_nao_cria_nf_curta_nem_consome_o_saldo_anterior():
    """Com o classificador real: "PAGTO REF. NF.: 1.234.2" lia a
    NF "1" (sem compra) como NF anterior e consumia o saldo anterior."""
    p = lanc("PAGTO REF. NF.: 1.234.2", numero="p", dia=5, debito="100.00")
    res = casar([_compra("1234", "300.00"), (p, ClassificadorHistorico().classificar(p))],
                saldo_anterior=D("-500.00"))
    assert "1" not in {nf.numero for nf in res.nfs}
    assert _onde(res, p) != "1"


# === o item sem NF correspondente guarda o numero que o historico citava ===============
# A regra tira a citacao de um pagamento (NF sem compra na razao, citacoes ja
# acima do saldo anterior) e o valor decide. Se nem o valor acha NF, o item cai em
# SEM_VINCULO: antes ficava sem o numero, e a tela dizia "sem numero de NF no
# historico" -- falso, o historico cita.

def _casa(*pares):
    return casar(list(pares), saldo_anterior=D("0.00"))


def _quitada_e(pgto_historico, valor, nf_clf=None):
    """5001 = 500,00 quitada por 'PGTO NF 5001'; depois o pagamento do teste."""
    quitacao = _pgto("5001", "500.00", numero="p1", dia=5)
    clf = ClassificadorHistorico()
    l = lanc(pgto_historico, numero="p2", dia=9, debito=valor)
    return casar([_compra("5001", "500.00"), quitacao, (l, clf.classificar(l))],
                 saldo_anterior=D("0.00")), l


def _sem_vinculo(res):
    return [i for i in res.balde if i.motivo.name == "SEM_VINCULO"]


def test_item_sem_vinculo_guarda_o_numero_citado():
    res, l = _quitada_e("PGTO NF 9999", "500.00")
    (item,) = _sem_vinculo(res)
    assert item.lancamentos == [l]
    assert getattr(item, "nf_citada", None) == "9999"


def test_pagamento_sem_nf_citada_nao_ganha_numero_citado():
    """CONTROLE: 'PGTO FORNECEDOR' nunca citou NF."""
    res, _ = _quitada_e("PGTO FORNECEDOR", "777.00")
    (item,) = _sem_vinculo(res)
    assert getattr(item, "nf_citada", None) is None


def test_citacao_que_casa_pelo_valor_nao_vira_item_e_segue_com_o_achado_de_sempre():
    """CONTROLE: com NF em aberto de valor compativel, o valor decide."""
    clf = ClassificadorHistorico()
    l = lanc("PGTO NF 9999", numero="p2", dia=9, debito="500.00")
    res = casar([_compra("5001", "500.00"), (l, clf.classificar(l))],
                saldo_anterior=D("0.00"))
    assert _sem_vinculo(res) == []
    assert [a.codigo for a in res.achados] == ["casamento_por_valor_citacao_sem_nota"]
    assert _onde(res, l) == "5001"

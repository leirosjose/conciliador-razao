"""Recebimento do fornecedor reconhecido.

So' o MOTIVO muda. Destino continua o balde, por decisao explicita de produto:
"Mesmo assim ele devera ir para o balde para ser analisado
e conciliar, pois tem subjetividade neste tipo de operacao." Credito ->
motivo RECEBIMENTO; debito com a mesma palavra continua nao reconhecido (debito
nunca e' dinheiro voltando). Nao casa com o pago a maior: a caixinha so'
mostra, como fato, as linhas de pago a maior da mesma conta.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.classifica import Tipo
from core.conferencia import conferir
from core.modelo import Conta, MotivoRevisao
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()
PIX = "Recebimento conf.   RECEBIMENTO PIX 00000000000000 FORN FICTICIO"


def test_recebimento_e_tipo_proprio():
    assert CLF.classificar(lanc(PIX, credito="897.60")).tipo is Tipo.RECEBIMENTO


def test_credito_de_recebimento_fica_no_balde_com_motivo_proprio():
    l = lanc(PIX, credito="897.60")
    res = casar([(l, CLF.classificar(l))])
    (item,) = res.balde
    assert item.motivo is MotivoRevisao.RECEBIMENTO
    assert item.lancamentos == [l]


def test_debito_com_a_palavra_recebimento_continua_nao_reconhecido():
    l = lanc(PIX, debito="897.60")
    res = casar([(l, CLF.classificar(l))])
    assert [i.motivo for i in res.balde] == [MotivoRevisao.NAO_CLASSIFICADO]


def test_recebimento_nao_entra_na_composicao_e_o_gap_e_ele():
    conta = Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                  data_fim_periodo=date(2025, 12, 31),
                  lancamentos=[lanc("Vr. compras conf. 810112 FORN", numero="c1",
                                    data=date(2025, 12, 11), credito="2941.92",
                                    saldo="-2941.92"),
                               lanc(PIX, numero="810117", data=date(2025, 12, 17),
                                    credito="897.60", saldo="-3839.52")])
    res = conferir(conta, CLF)
    assert [i.motivo for i in res.balde] == [MotivoRevisao.RECEBIMENTO]
    assert res.ponte.balde_creditos == D("897.60")
    assert res.ponte.diferenca == D("0.00")


# --- casca -------------------------------------------------------------------

def _pago_a_maior_e_recebimento_sintetico():
    """Pago a maior e o recebimento na mesma conta."""
    rows = [
        (date(2025, 12, 5), "810116", "Valor ref. a PGTO A FORN NFS:810111 E NF 810120",
         "10206.90", "0.00", "10206.90"),
        (date(2025, 12, 8), "c1", "Vr. compras conf. 810111 FORN", "0.00", "1393.65",
         "8813.25"),
        (date(2025, 12, 8), "c2", "Vr. compras conf. 810120 FORN", "0.00", "7842.30",
         "970.95"),
        (date(2025, 12, 17), "810117", PIX, "0.00", "897.60", "73.35"),
    ]
    return conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                          data_fim_periodo=date(2025, 12, 31),
                          lancamentos=[lanc(h, numero=n, data=d, debito=db,
                                            credito=cr, saldo=s)
                                       for d, n, h, db, cr, s in rows]), CLF)


def test_motivo_humano_do_recebimento_diz_o_fato_e_o_limite_do_motor():
    from app.apresentacao import motivo_humano
    (item,) = _pago_a_maior_e_recebimento_sintetico().balde
    texto = motivo_humano(item)
    # so' o fato -- a leitura da devolucao saiu da tela
    assert texto == ("Dinheiro recebido do fornecedor, sem nota fiscal. O "
                     "motor não decide este tipo de operação.")


def test_caixinha_do_recebimento_mostra_o_pago_a_maior_da_conta_sem_casar():
    from app.apresentacao import avisos_do_item, contexto_de_avisos
    res = _pago_a_maior_e_recebimento_sintetico()
    (item,) = res.balde
    aviso = avisos_do_item(item.lancamentos[0], item, contexto_de_avisos(res))
    assert aviso == ("Nesta conta: R$ 970,95 pago a maior na linha "
                     "(pago a maior lote 810116).")


def test_recebimento_sem_pago_a_maior_na_conta_nao_ganha_aviso():
    from app.apresentacao import avisos_do_item, contexto_de_avisos
    l = lanc(PIX, credito="897.60", saldo="-897.60")
    res = conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN",
                         data_fim_periodo=date(2025, 12, 31), lancamentos=[l]), CLF)
    (item,) = res.balde
    assert avisos_do_item(l, item, contexto_de_avisos(res)) == ""

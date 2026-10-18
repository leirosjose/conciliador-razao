"""Casar parcela ORDINAL sem NF pela serie ja ligada a NF.

Pagamento sem NF citada, com "kª PARCELA" declarado, que a Fase 2 deixou
SEM_VINCULO, casa na NF aberta que tem 2+ parcelas CITANDO a NF (ancoras) com
o mesmo valor (+-0,01), quando:
  - o ordinal esta livre na NF;
  - G1 cronologia: ordinal menor <=> data anterior, contra cada ancora e cada
    outra proposta da mesma NF; mesma data com ordinal diferente recusa;
  - G2 disputa: 2+ pagamentos pedindo o MESMO ordinal da MESMA NF -> todos
    ficam no balde;
  - NF candidata unica e comporta o pagamento.
Sai marcado (achado + nota na linha). Pagamento anterior a emissao casa e a
linha diz a data (decisao da aprovacao).

Os cenarios adversariais medidos na spec (pagamento de OUTRO bem com a mesma
parcela) ficam aqui como sinteticos permanentes.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.modelo import MotivoRevisao, RegraCasamento
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()
PARCELA = "56400.00"


def _compra(nf="810107", valor="804000.00", data=date(2025, 6, 10)):
    return lanc(f"Vr. compras conf. {nf} FORN FICTICIO", numero=f"c{nf}",
                data=data, credito=valor)


def _cita(k, data, nf="810107", valor=PARCELA):
    return lanc(f"Valor ref. a Pgto a FORN | {k}ª PARCELA - NF {nf}",
                numero=f"n{nf}-{k}", data=data, debito=valor)


def _solta(k, data, lote, bem="BEM A", valor=PARCELA):
    return lanc(f"Valor ref. a Pgto a FORN | INVESTIMENTOS {k}ª PARCELA - {bem}",
                numero=lote, data=data, debito=valor)


def _ancoras_4_a_8(nf="810107", valor=PARCELA):
    meses = [(2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12)]
    return [_cita(k, date(a, m, 15), nf, valor) for k, (a, m) in zip(range(4, 9), meses)]


def _base(*extras):
    """Caso sintetico: 1a (antes da emissao) e 2a soltas; 4a a 8a pela NF."""
    return [_compra(), _solta(1, date(2025, 5, 15), "810114"),
            _solta(2, date(2025, 6, 16), "810115"), *_ancoras_4_a_8(), *extras]


def _casar(lancs):
    lancs = sorted(lancs, key=lambda l: l.data)
    return casar([(l, CLF.classificar(l)) for l in lancs])


def _nf(res, numero="810107"):
    return next(n for n in res.nfs if n.numero == numero)


def _onde(res, lote):
    for nf in res.nfs:
        if any(l.numero == lote for l in nf.pagamentos):
            return nf.numero
    return "balde" if any(l.numero == lote for i in res.balde
                          for l in i.lancamentos) else None


# --- o caso que a regra existe pra resolver -----------------------------------

def test_1a_e_2a_soltas_casam_na_810107_pela_serie():
    res = _casar(_base())
    assert res.balde == []
    assert _onde(res, "810114") == "810107" and _onde(res, "810115") == "810107"
    assert _nf(res).saldo_aberto == D("409200.00")      # 804.000 - 7 x 56.400


def test_casamento_pela_serie_sai_marcado():
    res = _casar(_base())
    marcados = [a for a in res.achados if a.codigo == "casamento_por_serie_ordinal"]
    assert [a.lancamentos[0].numero for a in marcados] == ["810114", "810115"]
    assert all(a.referencia == "810107" for a in marcados)
    assert marcados[0].valores == {"pagamento": D(PARCELA), "ordinal": D(1),
                                   "ancoras": D(5)}
    assert [r.regra for r in _nf(res).por_regra] == [RegraCasamento.SERIE_ORDINAL] * 2


# --- adversariais da spec (pagamento de OUTRO bem com a mesma parcela) --------

def test_adv_1a_de_outro_bem_depois_da_8a_fica_no_balde():
    res = _casar(_base(_solta(1, date(2026, 1, 15), "999001", "OUTRO BEM")))
    assert _onde(res, "999001") == "balde"


def test_adv_3a_de_outro_bem_depois_da_8a_fica_no_balde():
    """A 3a nao pode vir depois da 4a."""
    res = _casar(_base(_solta(3, date(2026, 1, 15), "999002", "OUTRO BEM")))
    assert _onde(res, "999002") == "balde"
    assert _onde(res, "810114") == "810107"              # o resto nao muda


def test_adv_3a_sem_nf_em_julho_preenche_a_lacuna_e_casa():
    res = _casar(_base(_solta(3, date(2025, 7, 15), "999003")))
    assert _onde(res, "999003") == "810107"


def test_adv_1a_de_outro_bem_antes_de_tudo_disputa_e_as_duas_ficam_no_balde():
    """Sem a guarda, a 1a de outro bem (mar) EMPURRAVA a 1a verdadeira (mai)
    pro balde. Com ela, ninguem escolhe entre as duas."""
    res = _casar(_base(_solta(1, date(2025, 3, 15), "999004", "OUTRO BEM")))
    assert _onde(res, "999004") == "balde"
    assert _onde(res, "810114") == "balde"
    assert _onde(res, "810115") == "810107"              # a 2a nao estava em disputa


def test_adv_4a_repetida_sem_nf_fica_no_balde():
    res = _casar(_base(_solta(4, date(2025, 8, 20), "999005")))
    assert _onde(res, "999005") == "balde"


def test_adv_9a_sem_nf_depois_da_8a_casa():
    res = _casar(_base(_solta(9, date(2026, 1, 15), "999006")))
    assert _onde(res, "999006") == "810107"


# --- demais travas --------------------------------------------------------------

def test_uma_ancora_so_nao_basta():
    res = _casar([_compra(), _solta(1, date(2025, 5, 15), "810114"),
                  _cita(4, date(2025, 8, 15))])
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO]


def test_mesma_data_da_ancora_com_ordinal_diferente_recusa():
    res = _casar(_base(_solta(3, date(2025, 8, 15), "999007")))
    assert _onde(res, "999007") == "balde"


def test_duas_nfs_com_serie_do_mesmo_valor_nao_escolhe():
    outra = [_compra("30000", "804000.00", date(2025, 6, 11)),
             *_ancoras_4_a_8("30000")]
    res = _casar(_base(*outra))
    assert _onde(res, "810114") == "balde" and _onde(res, "810115") == "balde"


def test_valor_diferente_da_ancora_nao_casa():
    res = _casar([_compra(), _solta(1, date(2025, 5, 15), "810114", valor="56397.00"),
                  *_ancoras_4_a_8()])
    assert _onde(res, "810114") == "balde"


def test_nf_que_nao_comporta_nao_recebe():
    res = _casar([_compra(valor="282000.00"),       # 5 x 56.400: as ancoras quitam
                  _solta(1, date(2025, 5, 15), "810114"), *_ancoras_4_a_8()])
    assert _onde(res, "810114") == "balde"


# --- casca ------------------------------------------------------------------------

def _conferido():
    from core.conferencia import conferir
    from core.modelo import Conta
    return conferir(Conta(codigo="9000", classificacao="1.1", nome="FORN",
                          data_fim_periodo=date(2025, 12, 31),
                          lancamentos=sorted(_base(), key=lambda l: l.data)), CLF)


def test_linha_leva_a_nota_e_a_data_anterior_a_emissao():
    from app.apresentacao import notas_composicao_texto
    res = _conferido()
    nf = next(i for i in res.itens if i.nf_numero == "810107")
    assert nf.pagamento_antes_da_emissao == date(2025, 5, 15)
    assert ("NF 810107: 2 quitações casadas pela continuidade da série de "
            "parcelas") in notas_composicao_texto(res.itens)


def test_casamento_pela_serie_e_registrado_e_tem_frase():
    from app.apresentacao import REGISTRADO, classe_alerta, frase_achado
    a = next(a for a in _conferido().achados
             if a.codigo == "casamento_por_serie_ordinal")
    assert classe_alerta(a) == REGISTRADO
    frase = frase_achado(a)
    assert "lote 810114" in frase and "NF 810107" in frase and "56.400,00" in frase

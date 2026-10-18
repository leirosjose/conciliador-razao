"""Alerta "NF lançada 2+ vezes com o mesmo valor".

A composicao NAO tira a copia (seria forcar): a NF continua somando as linhas
de compra, como sempre. O alerta e' fato, nao decide nada -- classe "Não
decidido pelo motor". Nota dividida em linhas de valores DIFERENTES nao
dispara. Os dados sao ficticios (um caso com 13 NFs).
"""
from datetime import date
from decimal import Decimal

from app.apresentacao import NAO_DECIDIDO, classe_alerta, frase_achado, observacoes_tela
from core.classifica import Classificacao, Tipo
from core.conferencia import conferir
from core.modelo import NF, Conta, Nivel
from core.veredito import compra_repetida
from tests.helpers import invariante_de_lugar, lanc

D = Decimal


def _nf(numero, *linhas):
    nf = NF(numero=numero)
    for i, (valor, dia, lote) in enumerate(linhas):
        l = lanc(f"compra {numero}", numero=lote, dia=dia, credito=valor)
        nf.compras.append(l)
        nf.valor_compra += l.credito
    return nf


def test_duas_linhas_de_mesmo_valor_alertam_com_lotes_e_datas():
    nf = _nf("9000001", ("300.00", 5, "70001"), ("300.00", 5, "70002"))
    (a,) = compra_repetida([nf])
    assert (a.nivel, a.codigo, a.referencia) == (
        Nivel.ALERTA, "possivel_compra_repetida", "9000001")
    assert a.valores == {"valor": D("300.00"), "vezes": D("2")}
    assert [l.numero for l in a.lancamentos] == ["70001", "70002"]
    assert nf.valor_compra == D("600.00")         # composicao intacta


def test_nota_dividida_em_valores_diferentes_nao_alerta():
    assert compra_repetida([_nf("9000002", ("596.10", 5, "a"),
                                ("4071.30", 5, "b"))]) == []


def test_tres_linhas_iguais_e_uma_diferente():
    nf = _nf("7", ("10.00", 1, "a"), ("10.00", 2, "b"), ("10.00", 3, "c"),
             ("99.00", 3, "d"))
    (a,) = compra_repetida([nf])
    assert a.valores == {"valor": D("10.00"), "vezes": D("3")}


def test_uma_linha_so_nao_alerta():
    assert compra_repetida([_nf("8", ("10.00", 1, "a"))]) == []


class _Clf:
    def classificar(self, l):
        return Classificacao(Tipo.COMPRA, nf_numero="5001") if l.credito else \
            Classificacao(Tipo.PAGAMENTO, nf_numero="5001", nfs_citadas=("5001",))


def test_conferir_alerta_e_a_nf_continua_somando_as_duas_linhas():
    c1 = lanc("c", numero="70001", data=date(2026, 5, 5), credito="300.00",
              saldo="-300.00")
    c2 = lanc("c", numero="70002", data=date(2026, 5, 5), credito="300.00",
              saldo="-600.00")
    p = lanc("p", numero="70003", data=date(2026, 6, 3), debito="300.00",
             saldo="-300.00")
    conta = Conta(codigo="9", classificacao="", nome="FORN TESTE FICTICIO",
                  data_fim_periodo=date(2026, 6, 30), lancamentos=[c1, c2, p],
                  total_debito_dominio=D("300.00"),
                  total_credito_dominio=D("600.00"))
    res = conferir(conta, _Clf())
    (a,) = [a for a in res.achados if a.codigo == "possivel_compra_repetida"]
    assert classe_alerta(a) == NAO_DECIDIDO
    assert frase_achado(a) == ("NF 5001 lançada 2 vezes com o mesmo valor, "
                               "R$ 300,00: lotes 70001 e 70002 (05/05/2026)")
    (item,) = res.itens
    assert (item.valor_compra, item.saldo_aberto) == (D("600.00"), D("300.00"))
    invariante_de_lugar(res)


def test_tela_agrupa_duas_ou_mais_numa_caixa():
    a1 = compra_repetida([_nf("1", ("300.00", 5, "a"), ("300.00", 5, "b"))])[0]
    a2 = compra_repetida([_nf("2", ("40.00", 6, "c"), ("40.00", 7, "d"))])[0]
    (obs,) = observacoes_tela([a1, a2])
    assert obs.frase == "NF lançada mais de uma vez com o mesmo valor em 2 notas."
    assert obs.lista == ("NF 1: R$ 300,00, lotes a e b (05/01/2025)",
                         "NF 2: R$ 40,00, lotes c e d (06/01/2025 e 07/01/2025)")

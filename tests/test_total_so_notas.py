"""O TOTAL da composicao
soma "Valor compra" e "Total pago" SO das linhas que sao nota. As linhas que
nao sao nota ((saldo anterior), (transferencia ...), (pago a maior lote X))
ficam fora desses dois totais -- o valor delas mora em EM ABERTO.

Nenhum numero de motor muda: EM ABERTO, ponte, veredito e o que a nota do
saldo anterior mede (compra/pago fora da tabela) ficam identicos.

Invariantes (com as quitadas, sobre a tabela inteira):
  compra: total so notas + compras das NFs do periodo zerado
          == "(+) Compras do periodo" + compra nova a mao
  pago:   total so notas + pago das linhas sem nota + pago fora da tabela
          + pago das NFs do periodo zerado == "(-) Pagamentos casados"
"""
from decimal import Decimal


from core.conferencia import conferir
from core.modelo import Origem
from parser.excel import ExcelParser
from parser.historico import ClassificadorHistorico
from tests.helpers import GOLDEN
from tests.test_ponte import COMPRA, PAGAMENTO_NF, TRANSFERENCIA, _conta

D = Decimal
CLASSIFICADOR = ClassificadorHistorico()
PGTO_MULTI = "Valor ref. a PGTO A FORN FICTICIO NFS:{a} E NF {b}"


def _soma(valores):
    return sum(valores, D("0.00"))


def _com_linhas_sem_nota():
    """Saldo anterior de 700 (sem pagamento), transferencia de 40, pagamento
    que cita 5002 e 5003 e passa 647,30 da soma, e a 5001 paga em parte."""
    return conferir(_conta([
        (COMPRA.format(nf="5001"), "0.00", "2000.00", 2),
        (COMPRA.format(nf="5002"), "0.00", "929.10", 3),
        (COMPRA.format(nf="5003"), "0.00", "5228.20", 3),
        (TRANSFERENCIA, "0.00", "80.00", 4),
        (PGTO_MULTI.format(a="5002", b="5003"), "6804.60", "0.00", 5),
        (PAGAMENTO_NF.format(nf="5001"), "400.00", "0.00", 6),
    ], saldo_anterior="-1400.00"), CLASSIFICADOR)


def invariantes_do_total(res) -> None:
    """As duas invariantes do TOTAL da composicao."""
    tabela = list(res.itens) + list(res.quitadas)
    fechados = list(res.fechado.itens) if res.fechado is not None else []
    t, p = res.totais_tabela, res.ponte
    compra_nova = _soma(i.valor_compra for i in tabela + fechados
                        if i.origem is Origem.ALOCACAO_MANUAL)
    assert (t.valor_compra + _soma(i.valor_compra for i in fechados if i.e_nota)
            == p.total_compras + compra_nova)
    assert (t.total_pago + _soma(i.total_pago for i in tabela if not i.e_nota)
            + t.pago_fora_da_tabela + _soma(i.total_pago for i in fechados)
            == p.total_pago)
    # EM ABERTO continua somando TODAS as linhas: e' onde mora o valor delas
    assert t.saldo_aberto == _soma(i.saldo_aberto for i in tabela)
    assert res.totais_em_aberto.saldo_aberto == p.total_em_aberto


def test_e_nota_e_compra_do_periodo_ou_compra_nova_a_mao():
    origens = {i.nf_numero: i.e_nota for i in _com_linhas_sem_nota().itens}
    assert origens["5001"] is True
    assert origens["(anterior)"] is False
    assert not any(v for nf, v in origens.items() if nf.startswith("(trans"))
    assert origens["(pago a maior lote L5)"] is False


def test_total_de_compra_e_pago_sao_so_das_notas():
    res = _com_linhas_sem_nota()
    t = res.totais_tabela
    assert t.valor_compra == D("8157.30")      # 1.000 + 929,10 + 5.228,20
    assert t.total_pago == D("6557.30")        # 200 + 929,10 + 5.228,20
    assert t.saldo_aberto == D("2432.70")      # 800 + 700 + 40 - 647,30
    assert res.ponte.total_compras == D("8157.30")


def test_total_em_aberto_tambem_e_so_das_notas():
    res = _com_linhas_sem_nota()
    t = res.totais_em_aberto
    assert t.valor_compra == D("2000.00")      # so' a 5001 e' nota em aberto
    assert t.total_pago == D("400.00")
    assert t.saldo_aberto == D("2432.70")


def test_o_que_a_nota_do_saldo_anterior_mede_nao_muda():
    """compra/pago fora da tabela seguem sobre TODAS as linhas: sem saldo
    anterior consumido, zero -- a transferencia e o pago a maior nao viram
    "fora da tabela"."""
    t = _com_linhas_sem_nota().totais_tabela
    assert t.compra_fora_da_tabela == t.pago_fora_da_tabela == D("0.00")


def test_invariantes_no_sintetico():
    invariantes_do_total(_com_linhas_sem_nota())


def test_golden_sem_linha_sem_nota_fica_igual():
    res = conferir(ExcelParser().parse(GOLDEN)[0], CLASSIFICADOR)
    t = res.totais_tabela
    assert (t.valor_compra, t.total_pago, t.saldo_aberto) == (
        D("7100.03"), D("2839.94"), D("4260.09"))
    assert t.compra_fora_da_tabela == t.pago_fora_da_tabela == D("429.26")
    invariantes_do_total(res)



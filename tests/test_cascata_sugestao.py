"""A CASCATA da sugestao, em sintetica permanente.

Antes, so' um caso de razao cobria "aceitar uma sugestao do balde atualiza as
demais" -- e, depois que as parcelas dele passaram a casar, nao sobrou caso
nenhum. Aqui o mesmo fenomeno, montado a mao (a sugestao le o saldo de
AGORA, depois das decisoes do contador):

  NF 7000 de 1.000,00, ja com 370,00 pagos pelo numero -> saldo 630,00.
  Tres pagamentos sem NF de 210,00, "Parcela k de 3": 3 x 210,00 = 630,00 =
  o saldo remanescente -> a regra C sugere a 7000 pros tres.
  Aceitar UM tira 210,00 do saldo (420,00): 3 x 210,00 nao bate mais, e as
  outras duas sugestoes EXPIRAM -- o seletor volta em branco.

Uma segunda NF (7001, 500,00) fica aberta o tempo todo pro saldo nunca zerar.
Nenhuma regra de casamento pega os 210,00 (nao e' parcela igual de 1.000,00;
sem valor declarado; sem ancora ordinal citando a NF): ficam no balde.
"""
from datetime import date
from decimal import Decimal

from core.conferencia import conferir
from core.modelo import (AlocacaoManual, Conta, CriterioSugestao,
                         DestinoAlocacao, MotivoRevisao)
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()
E = "FORNECEDOR FICTICIO"

# (data, lote, historico, debito, credito) -- o formato do gerador sintetico
LANCAMENTOS = [
    # NF 7001 aberta o tempo todo: o saldo nunca zera (sem ela, o corte por
    # saldo zero levaria tudo pro periodo zerado). 210,00 nao e' parcela dela.
    (date(2025, 1, 5), 5000, f"Vr. compras conf. 7001 {E} LTDA", None, D("500.00")),
    (date(2025, 1, 10), 5001, f"Vr. compras conf. 7000 {E} LTDA", None, D("1000.00")),
    (date(2025, 1, 20), 5002, f"Pago conf. NF 7000 {E}", D("370.00"), None),
    (date(2025, 2, 10), 5003, f"Pago conf. {E} (Parcela 1 de 3)", D("210.00"), None),
    (date(2025, 3, 10), 5004, f"Pago conf. {E} (Parcela 2 de 3)", D("210.00"), None),
    (date(2025, 4, 10), 5005, f"Pago conf. {E} (Parcela 3 de 3)", D("210.00"), None),
]


def _conta():
    saldo = D("0.00")
    lancs = []
    for d, lote, hist, deb, cred in LANCAMENTOS:
        saldo += (deb or D("0.00")) - (cred or D("0.00"))
        lancs.append(lanc(hist, numero=str(lote), data=d, debito=deb or "0.00",
                          credito=cred or "0.00", saldo=saldo))
    return Conta(codigo="7777", classificacao="1.1", nome=f"{E} LTDA",
                 data_fim_periodo=date(2025, 12, 31), lancamentos=lancs)


# --- core -------------------------------------------------------------------------

def test_os_tres_chegam_ao_balde_com_a_7000_sugerida():
    res = conferir(_conta(), CLF)
    assert [i.motivo for i in res.balde] == [MotivoRevisao.SEM_VINCULO] * 3
    assert [i.sugestao.alvo for i in res.balde] == ["7000"] * 3
    assert {i.sugestao.criterio for i in res.balde} == {
        CriterioSugestao.SERIE_X_SALDO_REMANESCENTE}
    assert next(i for i in res.itens if i.nf_numero == "7000").saldo_aberto == D("630.00")


def test_aceitar_uma_expira_a_sugestao_das_outras():
    conta = _conta()
    res = conferir(conta, CLF)
    primeiro = res.balde[0]
    novo = conferir(conta, CLF, [AlocacaoManual(
        item_id=primeiro.identificador, destino=DestinoAlocacao.LINHA_ABERTA,
        alvo="7000", criterio_sugerido=primeiro.sugestao.criterio)])
    assert novo.erros_alocacao == []
    assert next(i for i in novo.itens if i.nf_numero == "7000").saldo_aberto == D("420.00")
    assert len(novo.balde) == 2
    assert all(i.sugestao is None for i in novo.balde)     # a cascata


# --- tela (AppTest) -----------------------------------------------------------------

def test_cascata_na_tela(monkeypatch):
    """Tres caixinhas chegam com a 7000 pre-selecionada; aplicar UMA deixa as
    outras duas com o seletor em branco -- nenhuma proposta obsoleta presa."""
    from streamlit.testing.v1 import AppTest

    from tests.fixtures import gerar_sinteticas as G
    from tests.test_app_ponte import MAIN
    monkeypatch.setattr(G, "SALDO_ANTERIOR", D("0.00"))
    monkeypatch.setattr(G, "LANCAMENTOS", LANCAMENTOS)
    at = AppTest.from_file(str(MAIN), default_timeout=60).run()
    at.file_uploader[0].set_value(
        ("cascata.xlsx", G.montar_xlsx(),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert len(at.exception) == 0

    sugeridos = [i for i, s in enumerate(at.selectbox)
                 if s.value and "sugerida" in s.value]
    assert len(sugeridos) == 3 and len(at.selectbox) == 3

    aplicar = [b for b in at.button if b.label == "Aplicar"]
    aplicar[sugeridos[0]].click().run()
    assert len(at.exception) == 0

    assert len(at.selectbox) == 2                 # o balde encolheu
    assert not [s for s in at.selectbox if s.value and "sugerida" in s.value]

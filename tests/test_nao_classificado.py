"""Lancamento Tipo.OUTRO NUNCA some em silencio: vai pro balde de
revisao com MotivoRevisao.NAO_CLASSIFICADO levando o historico integral como
evidencia — debito E credito. Veredito com balde =
INCOMPLETO (gap explicado), nunca DIVERGENCIA falsa.

IDENTIDADE (teste proprio): gap == Σ(debitos − creditos) dos
lancamentos do balde INTEIRO, TODOS os motivos (SEM_VINCULO, EMPATE,
NAO_CLASSIFICADO).
"""
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.composicao import compor
from core.modelo import MotivoRevisao, Nivel
from core.veredito import self_check_composicao
from tests.helpers import lanc

D = Decimal


def test_debito_outro_vai_pro_balde_com_historico():
    misterio = lanc("DESPESA MISTERIOSA SEM PADRAO", debito="100.00")
    res = casar([(misterio, Classificacao(Tipo.OUTRO))])
    assert res.nfs == []
    assert len(res.balde) == 1
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.NAO_CLASSIFICADO
    assert "DESPESA MISTERIOSA SEM PADRAO" in item.mensagem   # evidencia integral
    assert item.lancamentos == [misterio]


def test_compra_sem_numero_capturado_vai_pro_balde():
    """Padrao de COMPRA que casou mas nao capturou o numero -> COMPRA com
    nf_numero=None. NUNCA some em silencio: vai pro balde
    NAO_CLASSIFICADO, e nao vira NF fantasma."""
    compra = lanc("Vr. compras conf. FORNECEDOR SEM NUMERO LEGIVEL", credito="500.00")
    res = casar([(compra, Classificacao(Tipo.COMPRA, nf_numero=None))])
    assert res.nfs == []
    assert len(res.balde) == 1
    item = res.balde[0]
    assert item.motivo is MotivoRevisao.NAO_CLASSIFICADO
    assert item.lancamentos == [compra]
    assert "sem numero" in item.mensagem.lower()


def test_credito_outro_tambem_vai_pro_balde():
    """Os DOIS lados. Exemplos: estorno de baixa,
    transferencia de saldos, recebimento PIX — todos creditos sem padrao."""
    recebimento = lanc("Recebimento conf.   RECEBIMENTO PIX 00000000000000", credito="158.92")
    res = casar([(recebimento, Classificacao(Tipo.OUTRO))])
    assert len(res.balde) == 1
    assert res.balde[0].motivo is MotivoRevisao.NAO_CLASSIFICADO


def test_veredito_incompleto_nao_divergencia_falsa():
    # compra aberta 500 + debito nao classificado 100:
    # saldo_final = -(500-100) = -400; Σ itens = 500; gap = 100 = balde
    compra = lanc("Vr. compras conf. 1111 FORN", credito="500.00")
    misterio = lanc("DESPESA MISTERIOSA", debito="100.00")
    res = casar([(compra, Classificacao(Tipo.COMPRA, nf_numero="1111")),
                 (misterio, Classificacao(Tipo.OUTRO))])
    itens = compor(res.nfs, D("0.00"), None)
    achados = self_check_composicao(itens, D("-400.00"), tuple(res.balde))
    assert not any(a.nivel is Nivel.ERRO for a in achados)     # nunca falso ERRO
    incompletos = [a for a in achados if a.nivel is Nivel.INCOMPLETO]
    assert len(incompletos) == 1
    assert incompletos[0].encontrado == D("100.00")            # gap
    assert incompletos[0].esperado == D("100.00")              # explicado pelo balde


def test_identidade_gap_cobre_balde_inteiro_todos_os_motivos():
    """Balde MISTO: debito SEM_VINCULO (30) + debito NAO_CLASSIFICADO (100)
    + credito NAO_CLASSIFICADO (20) -> gap = 30 + 100 - 20 = 110."""
    compra = lanc("Vr. compras conf. 2222 FORN", credito="500.00")
    solto = lanc("Pgto avulso sem NF", debito="30.00")
    misterio_d = lanc("DEBITO MISTERIOSO", debito="100.00")
    misterio_c = lanc("CREDITO MISTERIOSO", credito="20.00")
    res = casar([
        (compra, Classificacao(Tipo.COMPRA, nf_numero="2222")),
        (solto, Classificacao(Tipo.PAGAMENTO)),               # sem numero, nao casa
        (misterio_d, Classificacao(Tipo.OUTRO)),
        (misterio_c, Classificacao(Tipo.OUTRO)),
    ])
    motivos = {i.motivo for i in res.balde}
    assert MotivoRevisao.SEM_VINCULO in motivos
    assert MotivoRevisao.NAO_CLASSIFICADO in motivos
    itens = compor(res.nfs, D("0.00"), None)
    # saldo_final = (30+100) - (500+20) = -390; Σ itens = 500; gap = 110
    achados = self_check_composicao(itens, D("-390.00"), tuple(res.balde))
    incompleto = [a for a in achados if a.nivel is Nivel.INCOMPLETO][0]
    assert incompleto.encontrado == D("110.00")                # gap real
    assert incompleto.esperado == D("110.00")                  # Σ(D − C) do balde

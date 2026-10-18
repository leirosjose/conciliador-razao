"""TRANSFERENCIA DE SALDOS entre contas do mesmo fornecedor.

Fonte: resposta do contador — "pode considerar como baixa normal. Isso
acontece quando o fornecedor tem matriz e filial e no momento do cadastro sao
criadas contas contabeis diferentes do mesmo fornecedor sendo matriz e filial".

"Baixa normal" descreve o lado DEBITO. O caso visto e' CREDITO, e credito nao e'
baixa: e' saldo CHEGANDO de um razao que nao esta neste arquivo. Por isso o
tratamento e' por LADO.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.composicao import compor
from core.modelo import Lancamento, Nivel, Origem
from core.veredito import self_check_composicao

D = Decimal


def _l(lote, deb="0.00", cred="0.00", dia=2, hist="TRANSFERÊNCIA DE SALDOS"):
    return Lancamento(date(2023, 1, dia), lote, hist, "x", D(deb), D(cred), D("0.00"))


def _t(nf=None):
    return Classificacao(Tipo.TRANSFERENCIA_SALDO, nf_numero=nf)


# --- lado CREDITO: saldo chegando (um caso) --------------------

def test_credito_vira_linha_propria_da_composicao():
    """Um caso: lote 860024, 02/01/2023, credito de 5.800,00."""
    r = casar([(_l("860024", cred="5800.00"), _t())])
    assert r.balde == []                       # sai do balde: e' reconhecido
    assert len(r.nfs) == 1
    nf = r.nfs[0]
    assert nf.numero == "(transferência lote 860024)"
    assert nf.valor_compra == D("5800.00")
    assert nf.data_compra == date(2023, 1, 2)
    assert nf.saldo_aberto == D("5800.00")


def test_a_linha_carrega_a_origem_propria():
    r = casar([(_l("860024", cred="5800.00"), _t())])
    itens = compor(r.nfs, D("0.00"), date(2023, 12, 31))
    assert len(itens) == 1
    assert itens[0].origem is Origem.TRANSFERENCIA_SALDO
    assert itens[0].nf_numero == "(transferência lote 860024)"
    assert itens[0].saldo_aberto == D("5800.00")
    # idade conta da chegada AQUI, nao de uma emissao que este razao nao tem
    assert itens[0].idade_dias == 363


def test_o_lote_esta_no_nome_porque_duas_transferencias_nao_podem_colidir():
    r = casar([(_l("860024", cred="5800.00"), _t()),
               (_l("860025", cred="3000.00", dia=9), _t())])
    nomes = sorted(nf.numero for nf in r.nfs)
    assert nomes == ["(transferência lote 860024)", "(transferência lote 860025)"]
    assert sum((nf.valor_compra for nf in r.nfs), D("0.00")) == D("8800.00")


def test_credito_gera_ALERTA_de_saldo_nao_detalhado():
    """Irmao do saldo_anterior_nao_detalhado: valor em
    aberto legitimo cuja composicao vive fora da janela do arquivo."""
    r = casar([(_l("860024", cred="5800.00"), _t())])
    itens = compor(r.nfs, D("0.00"), date(2023, 12, 31))
    achados = self_check_composicao(itens, D("-5800.00"))
    alerta = [a for a in achados if a.codigo == "transferencia_nao_detalhada"]
    assert len(alerta) == 1
    assert alerta[0].nivel is Nivel.ALERTA
    assert alerta[0].encontrado == D("5800.00")
    assert alerta[0].referencia == "(transferência lote 860024)"


def test_a_linha_de_transferencia_pode_ser_quitada_por_numero():
    """Linha aberta como qualquer outra: citada por numero, a Fase 1 quita."""
    pares = [(_l("860024", cred="5800.00"), _t()),
             (_l("860027", deb="5800.00", dia=20, hist="PGTO"),
              Classificacao(Tipo.PAGAMENTO, nf_numero="(transferência lote 860024)"))]
    r = casar(pares)
    assert r.nfs[0].saldo_aberto == D("0.00")


def test_credito_de_transferencia_nao_some_no_saldo_anterior():
    """Descartado: o "(anterior)" e o saldo de ANTES da janela; este
    chegou DENTRO dela, com data e lote proprios."""
    r = casar([(_l("860024", cred="5800.00"), _t())], D("-2000.00"))
    itens = compor(r.nfs, D("-2000.00"), date(2023, 12, 31))
    origens = {i.origem for i in itens}
    assert Origem.TRANSFERENCIA_SALDO in origens
    transf = next(i for i in itens if i.origem is Origem.TRANSFERENCIA_SALDO)
    assert transf.saldo_aberto == D("5800.00")      # inteiro, nao fundido


# --- lado DEBITO: saldo saindo (NAO MEDIDO — nenhum caso visto) -------

def test_debito_que_cita_NF_quita_como_baixa():
    pares = [(_l("c", cred="2000.00", hist="compra"),
              Classificacao(Tipo.COMPRA, nf_numero="77")),
             (_l("860024", deb="2000.00", dia=20), _t(nf="77"))]
    r = casar(pares)
    nf = next(n for n in r.nfs if n.numero == "77")
    assert nf.total_baixado == D("2000.00")      # familia de quitacao SEM numerario
    assert nf.saldo_aberto == D("0.00")
    assert r.balde == []


def test_debito_sem_NF_casa_por_valor_quando_inequivoco():
    pares = [(_l("c", cred="2000.00", hist="compra"),
              Classificacao(Tipo.COMPRA, nf_numero="77")),
             (_l("860024", deb="2000.00", dia=20), _t())]
    r = casar(pares)
    nf = next(n for n in r.nfs if n.numero == "77")
    assert nf.total_baixado == D("2000.00")


def test_debito_sem_candidata_vai_pro_balde_e_nunca_chuta():
    r = casar([(_l("860024", deb="2469.12", dia=20), _t())])
    assert len(r.balde) == 1
    assert r.balde[0].lancamentos[0].numero == "860024"


# --- apresentacao: a linha se chama pelo que ela E' -------------------------

def test_frase_do_alerta_traz_o_valor_em_moeda_br():
    from app.apresentacao import frase_achado
    from core.modelo import Achado
    a = Achado(Nivel.ALERTA, "transferencia_nao_detalhada",
               "saldo transferido de outra conta do mesmo fornecedor "
               "(matriz/filial) não detalhado neste razão; puxar a razão da "
               "conta-irma pra compor NF a NF",
               referencia="(transferência lote 860024)", encontrado=D("5800.00"))
    frase = frase_achado(a)
    assert "R$ 5.800,00" in frase
    assert "sem detalhe de notas neste razão" in frase   # fato


def test_alerta_tem_rotulo_curto_proprio_na_tabela():
    from app.apresentacao import alertas_celulas
    from core.modelo import Achado
    a = Achado(Nivel.ALERTA, "transferencia_nao_detalhada", "m",
               referencia="(transferência lote 860024)", encontrado=D("5800.00"))
    linha = alertas_celulas([a])[0]
    assert linha["Tipo"] == "Saldo transferido não detalhado"   # nunca o codigo cru


def test_a_linha_de_transferencia_nao_se_chama_NF():
    """Regra geral: nome entre parenteses e' rotulo do motor, nao numero de NF.
    "NF (transferencia lote 860024)" seria mentira — e a mesma razao pela qual
    o "(anterior)" nunca levou o prefixo."""
    from app.apresentacao import _texto_destino
    from core.modelo import DestinoAlocacao
    texto = _texto_destino(DestinoAlocacao.LINHA_ABERTA,
                           "(transferência lote 860024)", "")
    assert texto == "(transferência lote 860024)"


def test_seletor_de_alocacao_descreve_a_linha_de_transferencia():
    from app.destinos import opcoes_de_alocacao
    from core.composicao import compor
    r = casar([(_l("860024", cred="5800.00"), _t())])
    itens = compor(r.nfs, D("0.00"), date(2023, 12, 31))
    rotulos = [o.rotulo for o in opcoes_de_alocacao(itens, D("200.00"))]
    alvo = next(r for r in rotulos if "860024" in r)
    assert not alvo.startswith("NF ")
    assert "saldo transferido" in alvo
    assert "5.800,00" in alvo

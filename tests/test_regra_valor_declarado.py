"""Valor DECLARADO da parcela: num caso, 87% do gap estava em 2 itens.

O motor so' conhecia o valor PAGO, entao 2 x 554,07 = 1.108,14 nao achava
ninguem. Com o valor que o historico DECLARA, 2 x 541,37 = 1.082,74 = o valor
de compra exato da NF 43806. A diferenca (12,70 e 52,07 neste exemplo) e juros
de atraso — e e ela que o contador confere antes de aceitar.

Compara contra o valor de COMPRA, nao contra o saldo: a serie declarada foi
definida contra a NOTA quando ela foi emitida. E a mesma conta do casamento pelo valor
declarado: M x valor declarado == valor de compra, com a mesma tolerancia de centavos. Quem
compara contra o saldo e a regra de serie pelo saldo.
"""
from datetime import date
from decimal import Decimal

from core.modelo import (CriterioSugestao, DestinoAlocacao, ItemRevisao,
                         MotivoRevisao, NF)
from core.regras_sugestao import serie_x_valor_declarado
from core.sugestao import ContextoSugestao
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()

DECLARA = ("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ {v} "
           "(Parcela {k} de {m}). Despesa referente ao plano de conta 20.03.05")


def _nf(numero, compra, quitado="0.00", dia=17):
    nf = NF(numero=numero, valor_compra=D(compra), data_compra=date(2025, 1, dia))
    if D(quitado) > 0:
        nf.pagamentos.append(lanc("pgto", debito=quitado))
    return nf


def _item(v="541,37", k=1, m=2, pago="554.07", candidatos=(), lote="319460"):
    l = lanc(DECLARA.format(v=v, k=k, m=m), numero=lote, debito=pago)
    return ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       candidatos=list(candidatos), identificador=lote)


def _sugere(item, nfs, balde=None):
    balde = balde or [item]
    pares = [(l, CLF.classificar(l)) for i in balde for l in i.lancamentos]
    return serie_x_valor_declarado(item, ContextoSugestao.montar(balde, nfs, pares))


def _cenario_real():
    """As NFs abertas do caso quando `sugerir` roda. So' a 43806 vale 1.082,74."""
    return [_nf("43806", "1082.74"), _nf("50264", "3315.48", dia=8),
            _nf("52739", "2241.83", dia=11), _nf("45120", "287.91"),
            _nf("57316", "1708.35"), _nf("45122", "689.53")]


# --- o caso que a regra existe pra resolver -----------------------------------

def test_sugere_a_nf_cujo_valor_de_compra_fecha_com_a_serie_declarada():
    s = _sugere(_item(), _cenario_real())
    assert s is not None
    assert s.destino is DestinoAlocacao.LINHA_ABERTA
    assert s.alvo == "43806"
    assert s.criterio is CriterioSugestao.SERIE_X_VALOR_DECLARADO


def test_evidencia_traz_declarado_pago_e_a_DIFERENCA():
    """A diferenca vai explicita, nao deduzida: e o numero que o contador
    confere antes de aceitar."""
    s = _sugere(_item(), _cenario_real())
    assert s.evidencia["parcela_declarada"] == D("541.37")
    assert s.evidencia["parcelas"] == D("2")
    assert s.evidencia["valor_compra"] == D("1082.74")
    assert s.evidencia["pago"] == D("554.07")
    assert s.evidencia["diferenca"] == D("12.70")


def test_pago_igual_ao_declarado_zera_a_diferenca():
    s = _sugere(_item(pago="541.37"), _cenario_real())
    assert s.evidencia["diferenca"] == D("0.00")


# --- matriz de RECUSA ---------------------------------------------------------

def test_sem_valor_declarado_nao_sugere():
    """A regra inteira pende do numero que o historico declara.

    O historico traz "Parcela 1 de 2" (entao parcela_de EXISTE e a guarda
    anterior nao morde) mas nao declara o valor — e so' esta condicao que pode
    barrar. Sem esse cuidado o teste passaria pelo motivo errado, como a
    mutacao mostrou."""
    l = lanc("Valor ref. a PGTO A FORN FICTICIO | (Parcela 1 de 2) do acordo",
             numero="1", debito="554.07")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO)
    assert CLF.classificar(l).parcela_de == 2            # a guarda anterior passa
    assert CLF.classificar(l).valor_parcela is None      # esta e que barra
    assert _sugere(item, _cenario_real()) is None


def test_ordinal_sem_M_tambem_nao_sugere():
    """"7ª PARCELA" declara k mas nao M: outra condicao, outro teste."""
    l = lanc("Valor ref. a PGTO A FORN FICTICIO | 1ª PARCELA",
             numero="1", debito="554.07")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO)
    assert _sugere(item, _cenario_real()) is None


def test_sem_M_declarado_nao_sugere():
    l = lanc("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ 541,37 pago",
             numero="1", debito="554.07")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO)
    assert _sugere(item, _cenario_real()) is None


def test_duas_nfs_com_o_mesmo_valor_de_compra_nao_desempatam():
    nfs = [_nf("A", "1082.74"), _nf("B", "1082.74")]
    assert _sugere(_item(), nfs) is None


def test_nenhuma_nf_fechando_nao_sugere():
    assert _sugere(_item(), [_nf("A", "999.99")]) is None


def test_nf_ja_quitada_nao_e_alvo():
    """"NF aberta" e condicao: titulo fechado nao recebe proposta."""
    assert _sugere(_item(), [_nf("43806", "1082.74", "1082.74")]) is None


def test_nf_sem_compra_no_periodo_nao_e_alvo():
    assert _sugere(_item(), [NF(numero="A", valor_compra=D("1082.74"))]) is None


def test_credito_nao_e_parcela():
    l = lanc(DECLARA.format(v="541,37", k=1, m=2), numero="1", credito="554.07")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO)
    assert _sugere(item, _cenario_real()) is None


def test_item_agregado_nao_sugere():
    a = lanc(DECLARA.format(v="541,37", k=1, m=2), numero="1", debito="554.07")
    b = lanc(DECLARA.format(v="541,37", k=2, m=2), numero="2", debito="593.44")
    item = ItemRevisao(lancamentos=[a, b],
                       motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE)
    assert _sugere(item, _cenario_real()) is None


def _fora_dos_candidatos():
    return [_nf("99999", "1082.74"), _nf("52739", "2241.83", dia=11)]


def test_nf_fora_dos_candidatos_do_empate_nao_e_sugerida():
    """Mesma guarda da regra de serie pelo saldo, pelo mesmo motivo: nao contradizer a analise da
    Fase 2 sem evidencia nova."""
    item = _item(candidatos=("52739", "50264"))
    assert _sugere(item, _fora_dos_candidatos()) is None


def test_a_MESMA_nf_dentro_dos_candidatos_e_sugerida():
    """Controle positivo: mesmo cenario, mesma aritmetica, so' muda a lista."""
    item = _item(candidatos=("99999", "52739"))
    assert _sugere(item, _fora_dos_candidatos()).alvo == "99999"


def test_tolerancia_de_centavos_e_a_da_casa():
    dentro = [_nf("A", "1082.75")]           # 1 centavo, M x 0,01 = 0,02
    assert _sugere(_item(), dentro).alvo == "A"
    fora = [_nf("A", "1082.86")]
    assert _sugere(_item(), fora) is None


# --- fronteira com a regra de serie pelo saldo ---------------------------------

def test_quando_saldo_e_declarado_respondem_ganha_o_saldo():
    """Numa NF sem nenhuma quitacao, valor_compra == saldo_aberto; se o pago for
    igual ao declarado, as DUAS regras apontam pra ela. A ordem da tupla decide,
    e o criterio e "mais proximo da tela ganha": a regra do saldo fala do saldo, que e o numero
    que o contador tem diante dos olhos na composicao."""
    from core.sugestao import sugerir

    item = _item(v="541,37", pago="541.37")          # declarado == pago
    nfs = [_nf("43806", "1082.74")]                  # compra == saldo (intacta)
    pares = [(l, CLF.classificar(l)) for l in item.lancamentos]

    # as duas, isoladas, respondem a mesma coisa
    ctx = ContextoSugestao.montar([item], nfs, pares)
    from core.regras_sugestao import serie_x_saldo_remanescente
    assert serie_x_saldo_remanescente(item, ctx).alvo == "43806"
    assert serie_x_valor_declarado(item, ctx).alvo == "43806"

    # pelo registro, quem responde e C
    sugerir([item], nfs, pares)
    assert item.sugestao.criterio is CriterioSugestao.SERIE_X_SALDO_REMANESCENTE


def test_declarado_responde_quando_o_saldo_nao_tem_resposta():
    """No caso: o pago (554,07) nao fecha com saldo nenhum, entao a regra do saldo passa a
    vez e a do declarado acerta."""
    from core.sugestao import sugerir

    item = _item()                                   # pago 554,07, declarado 541,37
    nfs = _cenario_real()
    pares = [(l, CLF.classificar(l)) for l in item.lancamentos]
    sugerir([item], nfs, pares)
    assert item.sugestao.criterio is CriterioSugestao.SERIE_X_VALOR_DECLARADO
    assert item.sugestao.alvo == "43806"


# --- cobertura de CI -----------------------------------------------------------
# Sem isto, nem a regra nem o caminho do estouro teriam prova
# no CI — e o estouro e justamente o efeito que esta regra aceita de olhos abertos.

def _conta_com_serie_declarada():
    from core.modelo import Conta
    pgtos = [lanc(DECLARA.format(v="541,37", k=k, m=2), numero=lote,
                  dia=dia, debito=pago, saldo="0.00")
             for k, lote, dia, pago in [(1, "319460", 10, "554.07"),
                                        (2, "319924", 20, "593.44")]]
    return Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                 data_fim_periodo=date(2025, 12, 31),
                 total_debito_dominio=D("1147.51"),
                 total_credito_dominio=D("1082.74"),
                 lancamentos=[lanc("Vr. compras conf. 43806 FORN TESTE",
                                   numero="c1", dia=1, credito="1082.74",
                                   saldo="-1082.74"), *pgtos])


def test_ponta_a_ponta_o_motor_casa_pelo_declarado():
    """Antes: classificador -> casar (desiste) -> sugerir
    (acerta pelo declarado), 2 itens SEM_VINCULO no balde (lotes 319460 e
    319924) com sugestao 43806. Depois: o casamento automatico resolve pela
    serie declarada; balde vazio, a sobra e' o possivel_juros AUTOMATICO."""
    from core.conferencia import conferir

    res = conferir(_conta_com_serie_declarada(), CLF)
    assert res.balde == []
    nf = next(i for i in res.itens if i.nf_numero == "43806")
    assert nf.saldo_aberto == D("-64.77")                # 1.082,74 - 1.147,51
    (juros,) = [a for a in res.achados if a.codigo == "possivel_juros"]
    assert juros.valores["diferenca"] == D("64.77")
    assert not [a for a in res.achados if a.codigo == "possivel_juros_manual"]


def test_ponta_a_ponta_a_sugestao_continua_onde_o_casamento_recusa():
    """O que o casamento pelo declarado recusa (pago MENOR que o declarado) segue com a sugestao:
    a regra de sugestao nao compara pago com declarado, o casamento sim."""
    from core.conferencia import conferir
    from core.modelo import Conta

    pgtos = [lanc(DECLARA.format(v="541,37", k=k, m=2), numero=lote, dia=dia,
                  debito="500.00")
             for k, lote, dia in [(1, "319460", 10), (2, "319924", 20)]]
    conta = Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                  data_fim_periodo=date(2025, 12, 31),
                  total_debito_dominio=D("1000.00"),
                  total_credito_dominio=D("1082.74"),
                  lancamentos=[lanc("Vr. compras conf. 43806 FORN TESTE",
                                    numero="c1", dia=1, credito="1082.74",
                                    saldo="-1082.74"), *pgtos])
    res = conferir(conta, CLF)
    assert len(res.balde) == 2
    assert all(i.sugestao.alvo == "43806" for i in res.balde)
    assert all(i.sugestao.criterio is CriterioSugestao.SERIE_X_VALOR_DECLARADO
               for i in res.balde)

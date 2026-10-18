"""Serie declarada x SALDO REMANESCENTE: a regra de maior
rendimento medido — 4 itens, R$ 104.000,00.

"Parcela k de M" declarada no historico, e M x parcela bate com o saldo em
aberto de EXATAMENTE UMA candidata. Metadado declarado + aritmetica: o mesmo
espirito do casamento por serie declarada, contra outro numero (o casamento compara com o valor de
COMPRA e roda dentro do casamento; esta compara com o SALDO e roda depois).

E SUGESTAO, nao casamento: o conjunto medido e internamente inconsistente (ha uma
parcela declarada duas vezes), e casar esconderia a duplicidade dentro da
composicao do cliente.
"""
from datetime import date
from decimal import Decimal

import pytest

from core.modelo import NF, CriterioSugestao, DestinoAlocacao, ItemRevisao, MotivoRevisao
from core.regras_sugestao import serie_x_saldo_remanescente
from core.sugestao import ContextoSugestao
from parser.historico import ClassificadorHistorico
from tests.helpers import lanc

D = Decimal
CLF = ClassificadorHistorico()

# "Parcela 3 de 5" de 26.000,00 — a forma do historico que declara a parcela
PARCELA = ("Valor ref. a PGTO A FORN FICTICIO | Valor de R$ 26.000,00 "
           "(Parcela {k} de {m}). Despesa referente ao plano de conta 20.03.05")


def _nf(numero, compra, quitado="0.00", dia=25):
    """NF com saldo em aberto = compra - quitado (via um pagamento avulso)."""
    nf = NF(numero=numero, valor_compra=D(compra), data_compra=date(2024, 9, dia))
    if D(quitado) > 0:
        nf.pagamentos.append(lanc("pgto", debito=quitado))
    return nf


def _item(k=3, m=5, valor="26000.00", candidatos=("40317", "40318"), lote="1"):
    l = lanc(PARCELA.format(k=k, m=m), numero=lote, debito=valor)
    return ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.EMPATE,
                       candidatos=list(candidatos), identificador=lote)


def _ctx(itens, nfs):
    pares = [(l, CLF.classificar(l)) for i in itens for l in i.lancamentos]
    return ContextoSugestao.montar(itens, nfs, pares)


def _sugere(item, nfs, balde=None):
    balde = balde or [item]
    return serie_x_saldo_remanescente(item, _ctx(balde, nfs))


# --- o caso que a regra existe pra resolver -----------------------------------

def _cenario_real():
    """As tres NFs abertas de um caso no momento em que `sugerir` roda:
    40317 = 130.000 (= 5 x 26.000), 40318 = 182.000 (= 7 x), 41592 = 174.000."""
    return [_nf("40317", "234000.00", "104000.00"),
            _nf("40318", "234000.00", "52000.00"),
            _nf("41592", "268000.00", "94000.00", dia=26)]


def test_sugere_a_unica_candidata_cujo_saldo_fecha_com_a_serie():
    s = _sugere(_item(), _cenario_real())
    assert s is not None
    assert s.destino is DestinoAlocacao.LINHA_ABERTA
    assert s.alvo == "40317"
    assert s.criterio is CriterioSugestao.SERIE_X_SALDO_REMANESCENTE


def test_evidencia_traz_os_numeros_que_sustentam_a_proposta():
    """Numeros CRUS: a frase com R$ nasce na apresentacao. Sem o saldo
    aqui, o sumico da sugestao quando a conta muda ficaria ilegivel."""
    s = _sugere(_item(), _cenario_real())
    assert s.evidencia["parcela_declarada"] == D("26000.00")
    assert s.evidencia["parcelas"] == D("5")
    assert s.evidencia["saldo_remanescente"] == D("130000.00")


def test_candidatos_guardam_as_descartadas_pra_frase_mostrar():
    s = _sugere(_item(), _cenario_real())
    assert "40317" in s.candidatos and "40318" in s.candidatos


# --- matriz de RECUSA ---------------------------------------------------------

def test_sem_serie_declarada_nao_sugere():
    """Sem o M nao ha aritmetica: e o metadado declarado que faz a regra."""
    l = lanc("Valor ref. a Pgto a FORN FICTICIO", numero="1", debito="26000.00")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       candidatos=["40317", "40318"])
    assert _sugere(item, _cenario_real()) is None


def test_duas_candidatas_fechando_nao_desempatam():
    """Unicidade e a prova: 2+ fechando e ambiguidade, e ambiguidade fica no
    balde — nem sugestao o motor arrisca."""
    nfs = [_nf("A", "234000.00", "104000.00"),      # 130.000 = 5 x 26.000
           _nf("B", "200000.00", "70000.00")]       # 130.000 tambem
    assert _sugere(_item(candidatos=("A", "B")), nfs) is None


def test_nenhuma_candidata_fechando_nao_sugere():
    nfs = [_nf("A", "234000.00", "52000.00")]       # 182.000 = 7 x 26.000
    assert _sugere(_item(candidatos=("A",)), nfs) is None


def _fora_dos_candidatos():
    """UMA unica NF fecha a serie (99999), e ela NAO esta entre os candidatos
    que a Fase 2 apurou. A unicidade passa; so' a guarda dos candidatos barra —
    e e isso que este cenario precisa isolar."""
    return [_nf("40317", "234000.00", "52000.00"),        # 182.000 = 7 x, nao fecha
            _nf("99999", "130000.00")]                    # 130.000 = 5 x, fecha


def test_nf_fora_dos_candidatos_do_empate_nao_e_sugerida():
    """A Fase 2 ja julgou quais NFs sao plausiveis pra este pagamento. Apontar
    pra fora disso seria contradizer a analise do proprio motor sem evidencia
    nova."""
    item = _item(candidatos=("40317", "40318"))           # 99999 nao esta na lista
    assert _sugere(item, _fora_dos_candidatos()) is None


def test_a_MESMA_nf_dentro_dos_candidatos_e_sugerida():
    """Controle positivo do teste acima: mesmo cenario, mesma aritmetica, so'
    muda a lista de candidatos. Sem este par, o teste de recusa poderia estar
    passando por qualquer outro motivo."""
    item = _item(candidatos=("99999", "40317"))
    assert _sugere(item, _fora_dos_candidatos()).alvo == "99999"


def test_item_sem_candidatos_pode_ser_sugerido():
    """SEM_VINCULO nao teve candidatos apurados pela Fase 2: nao ha analise
    anterior pra contradizer, entao a regra pode apontar."""
    l = lanc(PARCELA.format(k=3, m=5), numero="1", debito="26000.00")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO,
                       candidatos=[], identificador="1")
    assert _sugere(item, _cenario_real()).alvo == "40317"


def test_nf_ja_quitada_nao_entra_na_conta():
    nfs = [_nf("A", "130000.00", "130000.00")]      # saldo zero
    assert _sugere(_item(candidatos=("A",)), nfs) is None


def test_nf_sem_compra_no_periodo_nao_entra_na_conta():
    """NF sem data de compra nao e linha da composicao por compra do periodo —
    a regra so' olha o que esta aberto ali."""
    nf = NF(numero="A", valor_compra=D("130000.00"))     # sem data_compra
    assert _sugere(_item(candidatos=("A",)), [nf]) is None


def test_credito_nao_e_parcela():
    l = lanc(PARCELA.format(k=3, m=5), numero="1", credito="26000.00")
    item = ItemRevisao(lancamentos=[l], motivo=MotivoRevisao.SEM_VINCULO)
    assert _sugere(item, _cenario_real()) is None


def test_item_agregado_nao_sugere():
    a = lanc(PARCELA.format(k=3, m=5), numero="1", debito="26000.00")
    b = lanc(PARCELA.format(k=4, m=5), numero="2", debito="26000.00")
    item = ItemRevisao(lancamentos=[a, b],
                       motivo=MotivoRevisao.MULTI_NF_NAO_CONFERE)
    assert _sugere(item, _cenario_real()) is None


def test_tolerancia_de_centavos_e_a_da_casa():
    """M x 0,01, a mesma convencao do _tol_parcela do casamento — a serie que o casamento
    compara ja usa essa tolerancia, e as duas falam da mesma serie."""
    dentro = [_nf("A", "234000.00", "104000.03")]        # saldo 129.999,97
    assert _sugere(_item(candidatos=("A",)), dentro).alvo == "A"
    fora = [_nf("A", "234000.00", "104000.20")]          # saldo 129.999,80
    assert _sugere(_item(candidatos=("A",)), fora) is None


# --- a 5a duplicada: o conflito aparece NA CAIXINHA ---------------------------
# Os dois lotes "Parcela 5 de 5" recebem sugestao pra a mesma NF. O contador
# tem que ver o conflito ONDE ELE DECIDE, e nao a tres secoes de distancia no
# painel de achados. Contrato preservado: numero no core, frase na apresentacao.

def test_serie_declarada_duas_vezes_marca_a_ocorrencia():
    balde = [_item(k=5, m=5, lote="319455"), _item(k=5, m=5, lote="322117")]
    nfs = _cenario_real()
    for item in balde:
        item.sugestao = serie_x_saldo_remanescente(item, _ctx(balde, nfs))
    assert all(i.sugestao.evidencia["ocorrencias_da_serie"] == D("2")
               for i in balde)


def test_parcela_unica_na_razao_nao_ganha_ressalva():
    """Ressalva so' quando ha conflito: um aviso que aparece sempre nao avisa
    nada."""
    balde = [_item(k=3, m=5, lote="1"), _item(k=4, m=5, lote="2")]
    nfs = _cenario_real()
    for item in balde:
        item.sugestao = serie_x_saldo_remanescente(item, _ctx(balde, nfs))
    assert all("ocorrencias_da_serie" not in i.sugestao.evidencia for i in balde)


def test_mesma_parcela_com_valor_DIFERENTE_nao_e_a_mesma_ocorrencia():
    """A duplicidade de parcela e (parcela k de M, VALOR). Series
    homonimas de compras diferentes nao sao conflito."""
    balde = [_item(k=5, m=5, valor="26000.00", lote="1"),
             _item(k=5, m=5, valor="30000.00", candidatos=("A",), lote="2")]
    nfs = _cenario_real()
    s = serie_x_saldo_remanescente(balde[0], _ctx(balde, nfs))
    assert "ocorrencias_da_serie" not in s.evidencia


def test_frase_da_ressalva_aponta_o_conflito_e_o_alerta():
    from app.apresentacao import frase_sugestao

    balde = [_item(k=5, m=5, lote="319455"), _item(k=5, m=5, lote="322117")]
    s = serie_x_saldo_remanescente(balde[0], _ctx(balde, _cenario_real()))
    frase = frase_sugestao(s)
    assert "2 vezes" in frase
    assert "duplicidade" in frase.lower()


# --- fronteira com o casamento por serie, e cobertura da regra -------------------
# Estes dois rodam sempre:
# um prova que a regra FUNCIONA ponta a ponta, o outro que ela nao invade o
# territorio do casamento.

def _conta(*lancamentos, debito, credito):
    from core.modelo import Conta
    return Conta(codigo="9000", classificacao="1.1", nome="FORN TESTE",
                 data_fim_periodo=date(2025, 12, 31),
                 total_debito_dominio=D(debito),
                 total_credito_dominio=D(credito),
                 lancamentos=list(lancamentos))


def _compra(nf, valor, dia, saldo):
    return lanc(f"Vr. compras conf. {nf} FORN TESTE", numero=f"c{nf}",
                dia=dia, credito=valor, saldo=saldo)


def test_ponta_a_ponta_a_regra_sugere_o_que_o_casamento_deixou():
    """Prova ponta a ponta: classificador -> casar (falha) -> sugerir (acerta).
    Reproduz a estrutura de um caso: duas NFs iguais, mesma data de emissao, uma
    ja mais quitada que a outra."""
    from core.conferencia import conferir

    pgtos = [lanc("Valor ref. a PGTO A FORN TESTE NF 11111", numero=f"p{i}",
                  dia=10 + i, debito="26000.00", saldo="0.00")
             for i in range(4)]
    pgtos += [lanc("Valor ref. a PGTO A FORN TESTE NF 22222", numero=f"q{i}",
                   dia=20 + i, debito="26000.00", saldo="0.00")
              for i in range(2)]
    empatado = lanc(PARCELA.format(k=3, m=5), numero="318841", dia=28,
                    debito="26000.00", saldo="-312000.00")
    conta = _conta(_compra("11111", "234000.00", 1, "-234000.00"),
                   _compra("22222", "234000.00", 1, "-468000.00"),
                   *pgtos, empatado,
                   debito="182000.00", credito="468000.00")

    res = conferir(conta, CLF)
    (item,) = [i for i in res.balde if i.lancamentos[0].numero == "318841"]
    assert item.motivo is MotivoRevisao.EMPATE          # o casamento desistiu
    assert item.sugestao.alvo == "11111"                # 130.000 = 5 x 26.000
    assert item.sugestao.criterio is CriterioSugestao.SERIE_X_SALDO_REMANESCENTE


def test_quando_o_casamento_por_serie_resolve_a_regra_nem_ve_o_item():
    """Fronteira ESTRUTURAL, nao convencional: o casamento por serie CASA e roda dentro de
    `casar`; `sugerir` so' ve o que sobrou no balde. Aqui 2 x 1.000,00 bate com
    o valor de COMPRA da 22222 — o casamento casa por serie declarada e o item nunca
    chega ao balde, entao nao ha o que sugerir."""
    from core.conferencia import conferir

    pgto = lanc("Valor ref. a PGTO A FORN TESTE | Valor de R$ 1.000,00 "
                "(Parcela 1 de 2). Despesa do plano de conta 20.03.05",
                numero="500", dia=10, debito="1000.00", saldo="-2000.00")
    conta = _conta(_compra("11111", "1000.00", 1, "-1000.00"),
                   _compra("22222", "2000.00", 1, "-3000.00"),
                   pgto, debito="1000.00", credito="3000.00")

    res = conferir(conta, CLF)
    assert res.balde == []                              # o casamento por serie casou
    nf = next(i for i in res.itens if i.nf_numero == "22222")
    assert nf.saldo_aberto == D("1000.00")              # 2.000 - 1.000
    assert not any(i.sugestao for i in res.balde)

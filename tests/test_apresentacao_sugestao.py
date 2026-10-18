"""Como a sugestao APARECE: frase, coluna do balde e origem.

O core entrega numeros crus; a frase com R$ nasce aqui. Estes testes
travam que a evidencia chega legivel ao conferente — e que ela e DERIVADA de
`item.sugestao`, nunca calculada duas vezes.
"""
from decimal import Decimal

from app.apresentacao import (balde_celulas, decisoes_celulas, frase_sugestao)
from core.modelo import (CriterioSugestao, DecisaoManual, DestinoAlocacao,
                         ItemRevisao, MotivoRevisao, Sugestao)
from tests.helpers import lanc

D = Decimal
_VAZIO = "—"


def _item(sugestao=None, historico="Valor ref. a pgto", debito="1946.37"):
    return ItemRevisao(lancamentos=[lanc(historico, numero="810113",
                                         debito=debito)],
                       motivo=MotivoRevisao.SEM_VINCULO,
                       identificador="abc", sugestao=sugestao)


def _sugestao(**kw):
    base = dict(destino=DestinoAlocacao.LINHA_ABERTA,
                criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO,
                alvo="810108",
                evidencia={"parcela_declarada": D("1908.27"),
                           "parcelas": D("2"),
                           "valor_compra": D("3816.54"),
                           "pago": D("1908.27"),
                           "diferenca": D("0.00")})
    return Sugestao(**{**base, **kw})


# --- frase da evidencia -------------------------------------------------------

def test_frase_do_valor_declarado_mostra_a_conta_que_sustenta():
    """O conferente tem que conseguir refazer a conta de cabeca antes de
    aceitar: 2 x 1.908,27 = 3.816,54, que e a NF 810108."""
    frase = frase_sugestao(_sugestao())
    assert "810108" in frase
    assert "1.908,27" in frase and "3.816,54" in frase


def test_frase_do_saldo_remanescente_contrasta_com_a_descartada():
    """O criterio de C so vale por UNICIDADE: a frase mostra a candidata que
    NAO fechou, senao o contador nao tem como julgar a proposta."""
    frase = frase_sugestao(_sugestao(
        criterio=CriterioSugestao.SERIE_X_SALDO_REMANESCENTE,
        alvo="810104", candidatos=("810104", "810105"),
        evidencia={"parcela_declarada": D("78000.00"), "parcelas": D("5"),
                   "saldo_remanescente": D("390000.00")}))
    assert "810104" in frase and "390.000,00" in frase


def test_criterio_sem_template_cai_em_fallback_visivel():
    """Nunca frase pela metade nem excecao: criterio sem texto mapeado ainda
    diz o destino provavel."""
    class _Criterio:
        pass
    frase = frase_sugestao(_sugestao(criterio=_Criterio()))
    assert "810108" in frase


def test_frase_do_saldo_anterior_nao_vira_nf_anterior():
    """O alvo "(anterior)" e uma linha, nao uma nota fiscal."""
    frase = frase_sugestao(_sugestao(alvo="(anterior)"))
    assert "NF (anterior)" not in frase


# --- coluna do balde (tela E Excel, mesma fonte) ------------------------------

def test_coluna_da_sugestao_traz_a_frase_no_item_que_tem_uma():
    (celula,) = balde_celulas([_item(sugestao=_sugestao())])
    assert "810108" in celula["Sugestão do motor"]


def test_coluna_da_sugestao_fica_vazia_sem_sugestao():
    (celula,) = balde_celulas([_item()])
    assert celula["Sugestão do motor"] == _VAZIO


def test_coluna_da_sugestao_vem_antes_das_colunas_de_preenchimento():
    """No Excel a coluna cai imediatamente a esquerda de Classificacao, que e
    onde quem confere trabalha: proposta e dropdown lado a lado. Como as colunas
    em branco sao concatenadas DEPOIS das celulas, basta esta ser a ultima."""
    (celula,) = balde_celulas([_item(sugestao=_sugestao())])
    assert list(celula)[-1] == "Sugestão do motor"


# --- origem da decisao --------------------------------------------------------

def _decisao(criterio=None):
    return DecisaoManual(item=_item(), destino=DestinoAlocacao.LINHA_ABERTA,
                         alvo="810108", criterio_sugerido=criterio)


def test_origem_declara_a_sugestao_aceita():
    (celula,) = decisoes_celulas(
        [_decisao(CriterioSugestao.SERIE_X_VALOR_DECLARADO)])
    assert celula["Origem"] == "sugestão do motor aceita"


def test_origem_fica_vazia_quando_a_escolha_foi_do_conferente():
    """Origem so se declara quando existe — decisao propria dele nao ganha
    carimbo de nada."""
    (celula,) = decisoes_celulas([_decisao()])
    assert celula["Origem"] == _VAZIO


# === a frase do par anulado =================================================
# O par nao deixa linha na composicao: esta frase e a UNICA resposta a "cade a
# baixa?". Por isso ela carrega os dois historicos INTEIROS, e nao so' os lotes.

def _achado_par():
    from core.modelo import Achado, Nivel
    baixa = lanc("Valor ref. a BAIXA DE ADIANTAMENTO - FORN", numero="810109",
                 dia=1, debito="2403.87")
    estorno = lanc("Valor ref. estorno de  BAIXA DE ADIANTAMENTO indevida - FORN",
                   numero="810110", dia=20, credito="2403.87")
    return Achado(nivel=Nivel.ALERTA, codigo="estorno_pareado",
                  mensagem="par anulado: lote 810109 estornado pelo lote 810110",
                  valores={"valor": D("2403.87")},
                  lancamentos=(baixa, estorno))


def test_frase_do_par_traz_lotes_datas_e_valor():
    from app.apresentacao import frase_achado

    frase = frase_achado(_achado_par())
    assert "810109" in frase and "810110" in frase
    assert "2.403,87" in frase
    assert "01/01/2025" in frase and "20/01/2025" in frase


def test_frase_do_par_traz_os_DOIS_historicos_integrais():
    """A resposta a "cade a baixa?" mora inteira no achado — historico
    truncado obrigaria o conferente a voltar ao Dominio."""
    from app.apresentacao import frase_achado

    frase = frase_achado(_achado_par())
    assert "Valor ref. a BAIXA DE ADIANTAMENTO - FORN" in frase
    assert "estorno de  BAIXA DE ADIANTAMENTO indevida - FORN" in frase


def test_frase_do_par_diz_que_os_dois_sairam_da_revisao():
    """O conferente tem que SABER que dois lancamentos sairam sem passar por
    ele, e que o liquido e zero."""
    from app.apresentacao import frase_achado

    frase = frase_achado(_achado_par())
    assert "revisão" in frase.lower()
    assert "zero" in frase.lower()


def test_achado_sem_lancamentos_cai_no_fallback_sem_estourar():
    from core.modelo import Achado, Nivel

    from app.apresentacao import frase_achado

    a = Achado(nivel=Nivel.ALERTA, codigo="estorno_pareado", mensagem="par anulado")
    assert frase_achado(a) == "par anulado"


# === a frase do valor declarado =============================================

def _sug_d(**kw):
    from core.modelo import Sugestao
    base = dict(destino=DestinoAlocacao.LINHA_ABERTA, alvo="810108",
                criterio=CriterioSugestao.SERIE_X_VALOR_DECLARADO,
                evidencia={"parcela_declarada": D("1908.27"), "parcelas": D("2"),
                           "valor_compra": D("3816.54"), "pago": D("1946.37"),
                           "diferenca": D("38.10")})
    return Sugestao(**{**base, **kw})


def test_frase_mostra_a_conta_do_declarado():
    frase = frase_sugestao(_sug_d())
    assert "810108" in frase
    assert "1.908,27" in frase and "3.816,54" in frase


def test_frase_expoe_o_pago_e_a_diferenca():
    """O contador confere a diferenca ANTES de aceitar: aceitar aloca o pago,
    nao o declarado, e pode estourar o titulo no fim da serie."""
    frase = frase_sugestao(_sug_d())
    assert "1.946,37" in frase
    assert "38,10" in frase
    assert "juros" in frase.lower()


def test_sem_diferenca_a_ressalva_some():
    """Aviso que aparece sempre nao avisa nada — mesma regra da ressalva de
    duplicidade."""
    frase = frase_sugestao(_sug_d(
        evidencia={"parcela_declarada": D("1908.27"), "parcelas": D("2"),
                   "valor_compra": D("3816.54"), "pago": D("1908.27"),
                   "diferenca": D("0.00")}))
    assert "juros" not in frase.lower()
    assert "3.816,54" in frase


def test_pago_ABAIXO_do_declarado_nao_fala_em_juros():
    """Diferenca negativa e desconto ou retencao, nao juros — a frase nao pode
    afirmar a causa errada."""
    frase = frase_sugestao(_sug_d(
        evidencia={"parcela_declarada": D("1908.27"), "parcelas": D("2"),
                   "valor_compra": D("3816.54"), "pago": D("1800.00"),
                   "diferenca": D("-108.27")}))
    assert "juros" not in frase.lower()
    assert "108,27" in frase


# --- continuidade de serie ordinal --------------------------------------------

def test_frase_da_continuidade_mostra_a_serie_os_ordinais_e_o_saldo():
    """Os numeros que o contador refaz de cabeca: quantas ja casaram, de que
    ordinal a que ordinal, qual e' esta, e se cabe no que esta em aberto."""
    from core.modelo import CriterioSugestao

    s = Sugestao(destino=DestinoAlocacao.LINHA_ABERTA, alvo="810107",
                 criterio=CriterioSugestao.CONTINUIDADE_SERIE_ORDINAL,
                 evidencia={"parcela": Decimal("56400.00"),
                            "ordinal": Decimal(1),
                            "casadas": Decimal(5),
                            "primeiro_ordinal": Decimal(4),
                            "ultimo_ordinal": Decimal(8),
                            "saldo_aberto": Decimal("522000.00")})
    frase = frase_sugestao(s)
    assert frase == ("provável NF 810107: ela já tem 5 parcelas de R$ 56.400,00 "
                     "casadas por número (4ª a 8ª) e esta é a 1ª, ainda livre — "
                     "cabe no saldo em aberto de R$ 522.000,00")

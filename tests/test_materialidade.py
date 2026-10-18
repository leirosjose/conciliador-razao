"""Materialidade do balde: dos N itens em revisao, quais poucos
respondem pela maior parte do gap — o conferente ataca esses primeiro.

Ajuda de LEITURA sobre numeros que o core ja fechou: nao muda composicao,
veredito nem casamento. Por isso vive fora do core (app/materialidade.py).
"""
from decimal import Decimal

from app.apresentacao import balde_celulas
from app.materialidade import frase_contagem_motivos, frase_materialidade, resumo_materialidade
from core.modelo import ItemRevisao, MotivoRevisao
from tests.helpers import lanc

D = Decimal


def _item(valor, *, dia=1, numero="1", motivo=MotivoRevisao.SEM_VINCULO,
          credito=False):
    quantia = {"credito" if credito else "debito": valor}
    return ItemRevisao(lancamentos=[lanc(numero=numero, dia=dia, **quantia)],
                       motivo=motivo)


# --- os N maiores (N <= 5) ----------------------------------------------------

def test_resumo_pega_os_cinco_maiores_e_soma_ao_centavo():
    balde = [_item(str(v), numero=str(v)) for v in
             (100, 700, 250, 1000, 50, 900, 800)]
    resumo = resumo_materialidade(balde, D("3000.00"))
    assert [i["Valor"] for i in resumo.itens] == [D("1000.00"), D("900.00"),
                                                 D("800.00"), D("700.00"),
                                                 D("250.00")]
    assert resumo.soma == D("3650.00")
    assert resumo.total == 7


def test_resumo_com_menos_de_cinco_itens_usa_todos():
    resumo = resumo_materialidade([_item("10.00"), _item("30.00")], D("40.00"))
    assert resumo.soma == D("40.00")
    assert resumo.total == 2


def test_percentual_e_decimal_sobre_o_gap():
    resumo = resumo_materialidade([_item("300.00"), _item("100.00")], D("800.00"))
    assert resumo.percentual == D("50.0")           # 400 de 800
    assert isinstance(resumo.percentual, Decimal)


def test_percentual_usa_o_tamanho_do_gap_mesmo_com_gap_negativo():
    """Conta devedora deixa o gap negativo: o percentual e' PESO
    sobre o tamanho do gap — sinal negativo nao vira percentual negativo."""
    resumo = resumo_materialidade([_item("50.00")], D("-100.00"))
    assert resumo.percentual == D("50.0")


def test_sem_gap_nao_ha_percentual():
    assert resumo_materialidade([_item("50.00")], D("0.00")).percentual is None
    assert resumo_materialidade([_item("50.00")], None).percentual is None


def test_balde_vazio_da_resumo_vazio():
    resumo = resumo_materialidade([], D("100.00"))
    assert resumo.itens == ()
    assert resumo.soma == D("0.00")
    assert resumo.total == 0


# --- credito no balde PESA CONTRA o gap ---------------------------------------

def test_credito_no_balde_reduz_a_soma_em_vez_de_inflar():
    """Um credito de 500,00 no balde REDUZ o gap em 500,00 — soma-lo como +500
    dizia que os itens explicavam mais do que o gap inteiro. A conta e' pela
    CONTRIBUICAO (debito - credito), a mesma identidade do veredito."""
    balde = [_item("3000.00", numero="1"), _item("500.00", numero="2", credito=True)]
    assert resumo_materialidade(balde, D("2500.00")).soma == D("2500.00")


def test_o_balde_inteiro_responde_por_exatamente_o_gap():
    """Invariante que amarra esta camada ao core: gap == Σ(D-C) do balde
    (identidade do INCOMPLETO). Com o balde todo dentro do resumo a soma bate
    ao centavo e o percentual NUNCA passa de 100% — era exatamente isso que a
    soma da coluna Valor quebrava (dava 156,6% neste mesmo balde)."""
    balde = [_item("3000.00", numero="1"), _item("400.00", numero="2"),
             _item("500.00", numero="3", credito=True),
             _item("250.00", numero="4", credito=True)]
    resumo = resumo_materialidade(balde, D("2650.00"))
    assert resumo.soma == D("2650.00")
    assert resumo.percentual == D("100.0")
    assert resumo.percentual <= D("100.0")


def test_subconjunto_pode_passar_de_cem_por_cento():
    """Os 2 maiores debitos excedem um gap que os creditos reduzem: verdade,
    nao defeito — o balde inteiro continua fechando em 100%."""
    balde = [_item("3000.00", numero="1"), _item("400.00", numero="2"),
             _item("500.00", numero="3", credito=True),
             _item("250.00", numero="4", credito=True)]
    from app.materialidade import MAX_ITENS
    assert MAX_ITENS == 5                    # o corte nao mascarou o caso
    resumo = resumo_materialidade(balde[:2], D("2650.00"))
    assert resumo.percentual == D("128.3")   # 3.400 / 2.650


# --- a frase (so com 3+ itens) ------------------------------------------------

def test_frase_nao_aparece_com_menos_de_tres_itens():
    """Com 1 ou 2 itens a lista JA e o resumo — a linha so ocuparia espaco."""
    assert frase_materialidade([_item("10.00"), _item("20.00")], D("30.00")) is None


def test_frase_traz_soma_gap_e_percentual_em_moeda_br():
    balde = [_item("1500.00", numero="1"), _item("1000.00", numero="2"),
             _item("500.00", numero="3"), _item("1000.00", numero="4"),
             _item("700.00", numero="5"), _item("300.00", numero="6")]
    frase = frase_materialidade(balde, D("5000.00"))
    assert frase == ("Os 5 maiores itens respondem por R$ 4.700,00 da diferença de "
                     "R$ 5.000,00 (94,0%)")


def test_frase_some_quando_os_n_maiores_sao_o_balde_inteiro():
    """Com 4 itens, "os 4 maiores respondem por 100%" so' repete o
    total do balde. A frase so' existe quando ha itens FORA dos N."""
    balde = [_item("1500.00", numero="1"), _item("1000.00", numero="2"),
             _item("500.00", numero="3"), _item("1000.00", numero="4")]
    assert frase_materialidade(balde, D("4000.00")) is None
    cinco = balde + [_item("10.00", numero="5")]
    assert frase_materialidade(cinco, D("4010.00")) is None


def test_frase_sem_gap_nao_aparece():
    balde = [_item("10.00"), _item("20.00"), _item("30.00")]
    assert frase_materialidade(balde, None) is None


# --- contagem por motivo ------------------------------------------------------

def test_contagem_por_motivo_do_maior_pro_menor():
    balde = ([_item("10.00", motivo=MotivoRevisao.EMPATE) for _ in range(4)]
             + [_item("10.00", motivo=MotivoRevisao.SEM_VINCULO) for _ in range(3)]
             + [_item("10.00", motivo=MotivoRevisao.NAO_CLASSIFICADO) for _ in range(2)])
    assert frase_contagem_motivos(balde) == ("9 itens: 4 Empate, 3 Sem NF, "
                                             "2 Não reconhecido")


def test_contagem_de_um_item_fala_no_singular():
    assert frase_contagem_motivos([_item("10.00")]) == "1 item: 1 Sem NF"


def test_contagem_de_balde_vazio_nao_existe():
    assert frase_contagem_motivos([]) is None


# --- ordenacao por valor: DETERMINISTICA --------------------------------------

def test_balde_por_valor_ordena_decrescente():
    balde = [_item("100.00", numero="a"), _item("900.00", numero="b"),
             _item("500.00", numero="c")]
    assert [c["Lote"] for c in balde_celulas(balde, por_valor=True)] == ["b", "c", "a"]


def test_empate_de_valor_desempata_por_data_depois_por_lote():
    """Mesmo arquivo = mesma ordem, sempre (requisito de produto): valor, depois
    data, depois lote — nenhum par fica na ordem do acaso."""
    balde = [_item("100.00", dia=5, numero="222"),
             _item("100.00", dia=2, numero="999"),
             _item("100.00", dia=5, numero="111")]
    assert [c["Lote"] for c in balde_celulas(balde, por_valor=True)] == ["999", "111", "222"]


def test_ordem_por_valor_e_estavel_entre_execucoes():
    balde = [_item("100.00", dia=3, numero="7"), _item("100.00", dia=3, numero="7"),
             _item("250.00", dia=1, numero="8"), _item("250.00", dia=1, numero="8")]
    uma = [tuple(c.values()) for c in balde_celulas(balde, por_valor=True)]
    outra = [tuple(c.values()) for c in balde_celulas(balde, por_valor=True)]
    assert uma == outra


def test_a_tela_continua_cronologica():
    """#28 wont-fix vale pra TELA: a ordem de trabalho do conferente e
    cronologica. So o Excel sai por valor (la ele reordena como quiser)."""
    balde = [_item("100.00", dia=9, numero="tarde"),
             _item("900.00", dia=1, numero="cedo")]
    assert [l["Lote"] for l in balde_celulas(balde)] == ["cedo", "tarde"]

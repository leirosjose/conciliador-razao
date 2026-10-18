"""Identificador estavel do item do balde.

O contador aloca um item do balde pela tela; o id volta pro motor na proxima
execucao. Se o id mudar quando o MOTOR evolui, a alocacao vira lixo silencioso —
por isso ele deriva do CONTEUDO DA RAZAO (campos do lancamento + ordinal da
chave na ordem da razao), nunca da posicao na lista do balde.

A prova de que posicao nao serve: a ordem do balde ja mudou (empates
foram pro fim, no passe 2b) sem que uma virgula da razao mudasse.
"""
from datetime import date
from decimal import Decimal

from core.casamento import casar
from core.classifica import Classificacao, Tipo
from core.identificacao import id_item, ids_da_razao
from tests.helpers import lanc

D = Decimal


def _compra(numero, valor, dia=10):
    return (lanc(f"Vr. compras conf. {numero}", numero=f"C{numero}",
                 data=date(2024, 1, dia), credito=valor),
            Classificacao(tipo=Tipo.COMPRA, nf_numero=numero))


def _solto(lote, valor, dia=5):
    return (lanc("Valor ref. a PGTO A FORNECEDOR FICTICIO", numero=lote,
                 data=date(2024, 2, dia), debito=valor),
            Classificacao(tipo=Tipo.PAGAMENTO))


def _nao_classificado(lote, valor, dia=1):
    return (lanc("Valor ref. a ALGO QUE O MOTOR NAO RECONHECE", numero=lote,
                 data=date(2024, 1, dia), credito=valor),
            Classificacao(tipo=Tipo.OUTRO))


# --- a funcao pura -----------------------------------------------------------

def test_id_e_hex_de_12_e_deterministico():
    l = lanc("historico qualquer", numero="L1", debito="200.00")
    (primeiro,) = ids_da_razao([l])
    (segundo,) = ids_da_razao([l])
    assert primeiro == segundo
    assert len(primeiro) == 12
    assert all(c in "0123456789abcdef" for c in primeiro)


def test_id_nao_usa_o_hash_embutido_do_python():
    """`hash()` e randomizado por PYTHONHASHSEED: daria id diferente a cada
    processo e quebraria a alocacao entre reruns. Trava do ALGORITMO — mudar o
    calculo do id e decisao consciente, nao efeito colateral."""
    l = lanc("Valor ref. a PGTO A FORNECEDOR FICTICIO", numero="860024",
             data=date(2023, 1, 2), debito="5800.00", cta_part="1.1.1")
    assert ids_da_razao([l]) == ["a647942f25a4"]


def test_linhas_identicas_recebem_ids_diferentes():
    """Ordinal desempata: duas linhas iguais na razao sao itens DISTINTOS."""
    l = lanc("mesmo historico", numero="L1", debito="52000.00")
    outro = lanc("mesmo historico", numero="L1", debito="52000.00")
    primeiro, segundo = ids_da_razao([l, outro])
    assert primeiro != segundo


def test_id_muda_quando_o_lancamento_muda():
    base = lanc("historico", numero="L1", debito="200.00")
    valor_outro = lanc("historico", numero="L1", debito="200.01")
    historico_outro = lanc("historico X", numero="L1", debito="200.00")
    assert ids_da_razao([base]) != ids_da_razao([valor_outro])
    assert ids_da_razao([base]) != ids_da_razao([historico_outro])


def test_id_de_item_com_um_lancamento_e_o_do_proprio_lancamento():
    (unico,) = ids_da_razao([lanc("h", numero="L1")])
    assert id_item([unico]) == unico


def test_id_de_item_com_varios_lancamentos_combina_os_dois():
    a, b = ids_da_razao([lanc("h1", numero="L1"), lanc("h2", numero="L2")])
    combinado = id_item([a, b])
    assert combinado not in (a, b)
    assert len(combinado) == 12
    assert id_item([a, b]) != id_item([b, a])      # ordem importa, e e estavel


# --- integrado com o casamento ----------------------------------------------

def test_todo_item_do_balde_sai_com_identificador_unico():
    # a compra casa por numero e NAO vai pro balde: sobram o pagamento sem
    # vinculo e o historico nao reconhecido
    res = casar([_compra("X", "200.00"), _solto("PG1", "600.00"),
                 _nao_classificado("N1", "100.00")])
    ids = [i.identificador for i in res.balde]
    assert len(ids) == 2
    assert all(len(i) == 12 for i in ids)
    assert len(set(ids)) == 2


def test_id_nao_depende_da_posicao_do_item_no_balde():
    """O MESMO pagamento, em duas razoes onde ele cai em posicoes diferentes do
    balde, tem o mesmo id. E o teste que amarra o contrato."""
    pagamento = _solto("PG1", "600.00")
    sozinho = casar([_compra("X", "200.00"), pagamento])
    acompanhado = casar([_nao_classificado("N1", "100.00"),
                         _compra("X", "200.00"), pagamento])

    (item_sozinho,) = [i for i in sozinho.balde
                       if i.lancamentos[0].numero == "PG1"]
    (item_acompanhado,) = [i for i in acompanhado.balde
                           if i.lancamentos[0].numero == "PG1"]
    assert sozinho.balde.index(item_sozinho) == 0
    assert acompanhado.balde.index(item_acompanhado) == 1      # posicao mudou
    assert item_sozinho.identificador == item_acompanhado.identificador


def test_id_de_um_item_nao_muda_quando_outro_lancamento_entra_na_razao():
    """Razao com um lancamento a mais (que nem vai pro balde): o id do item
    existente continua o mesmo."""
    pagamento = _solto("PG1", "600.00")
    antes = casar([_compra("X", "200.00"), pagamento])
    depois = casar([_compra("X", "200.00"), _compra("Y", "1400.00"), pagamento])
    assert antes.balde[0].identificador == depois.balde[0].identificador


def test_dois_pagamentos_identicos_no_balde_tem_ids_distintos():
    """Forma de um caso (duas 'Parcela 5 de 5' de 52.000,00): mesmo
    valor, mesmo historico, lotes diferentes — e mesmo se o lote fosse igual,
    o ordinal separa."""
    igual = ("Valor ref. a PGTO A FORNECEDOR FICTICIO", "52000.00")
    pares = [_compra("X", "200.00")]
    pares.append((lanc(igual[0], numero="L", data=date(2024, 2, 5),
                       debito=igual[1]), Classificacao(tipo=Tipo.PAGAMENTO)))
    pares.append((lanc(igual[0], numero="L", data=date(2024, 2, 5),
                       debito=igual[1]), Classificacao(tipo=Tipo.PAGAMENTO)))
    res = casar(pares)
    ids = [i.identificador for i in res.balde]
    assert len(ids) == 2
    assert ids[0] != ids[1]

"""Fabrica unica de Lancamento pros testes.

Antes, seis arquivos de teste definiam cada um seu proprio `_lanc` com
assinaturas divergentes. Aqui vive UMA fabrica com argumentos nomeados e
defaults inertes que cobrem todos os usos.

Dinheiro (`debito`/`credito`/`saldo`) aceita str (ou Decimal) e e convertido
com Decimal(...) — nunca float.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

from core.modelo import Lancamento

# Golden sintetico (tests/fixtures/gerar_sinteticas.py) usado por varios testes de composicao.
GOLDEN = Path(__file__).parent / "fixtures" / "golden_sintetico.xls"


def lanc(historico="x", *, numero="1", dia=1, data=None,
         debito="0.00", credito="0.00", cta_part="x", saldo="0.00"):
    """Constroi um Lancamento com defaults inertes.

    - `data` default = date(2025, 1, dia); passe `data=` pra uma data explicita
      (nesse caso `dia` e ignorado).
    - `debito`/`credito`/`saldo` aceitam str e sao convertidos com Decimal(...).
    """
    return Lancamento(
        data=data if data is not None else date(2025, 1, dia),
        numero=numero,
        historico=historico,
        cta_part=cta_part,
        debito=Decimal(debito),
        credito=Decimal(credito),
        saldo_exercicio=Decimal(saldo),
    )


def identidade_da_tabela(itens) -> None:
    """A identidade da TABELA da composicao: em TODO item,
    compra − pago − retido − baixa − alocado a mao == EM ABERTO.

    Outro teste confere a identidade do GAP (gap == Σ balde + Σ fora); esta e a da
    LINHA — a conta que o conferente faz de olho na tabela. Se uma familia de
    quitacao nova nascer na NF sem chegar ao ComposicaoItem, cai aqui."""
    for i in itens:
        soma = (i.valor_compra - i.total_pago - i.total_retido - i.total_baixado
                - i.total_manual)
        assert soma == i.saldo_aberto, (i.nf_numero, str(soma), str(i.saldo_aberto))


def de_moeda_br(texto: str) -> Decimal:
    """Desfaz moeda_br ('1.234,56' -> Decimal('1234.56')) — aritmetica SO no
    teste: a casca nunca reconverte o que formatou. Celula vazia (
    "Valor compra" de linha que nao e' nota) vale zero."""
    if texto == "":
        return Decimal("0.00")
    return Decimal(texto.replace(".", "").replace(",", "."))


COLUNAS_DA_IDENTIDADE = ("Valor compra", "Total pago", "Retido", "Baixa adiant.",
                         "Alocado à mão", "EM ABERTO")


def _vazia(valor) -> bool:
    return valor is None or valor == ""


def _sem_nota(linha) -> bool:
    """Linha do motor na tabela renderizada: nome entre parenteses (menos a
    compra nova a mao com o rotulo padrao, que e' nota)."""
    nf = str(linha.get("NF", ""))
    return nf.startswith("(") and not nf.startswith("(manual:")


def _e_total(linha) -> bool:
    nf = str(linha.get("NF", ""))
    return nf == "TOTAL" or nf.startswith("Total ")


def identidade_das_linhas(linhas, de=de_moeda_br) -> None:
    """A identidade da TABELA nas LINHAS renderizadas: em toda linha de
    NOTA, compra − pago − retido − baixa − alocado a mao == EM ABERTO. `linhas`
    sao dicts coluna -> valor; `de` converte o valor da celula em Decimal
    (texto BR na tela, numero no Excel).

    A linha que nao e' nota mostra "Valor compra" e "Total pago"
    VAZIOS -- o valor dela mora em EM ABERTO, e ela fica fora dos totais
    dessas duas colunas. Entao: linha sem nota com compra vazia nao tem
    identidade propria; e no TOTAL a conta fecha devolvendo o que as linhas
    sem nota levaram em EM ABERTO e nas demais colunas."""
    assert linhas, "tabela vazia"
    sem_nota = [l for l in linhas if _sem_nota(l)]
    for linha in linhas:
        if _sem_nota(linha) and _vazia(linha["Valor compra"]):
            continue
        compra, pago, retido, baixa, manual, aberto = (
            de(linha[c]) for c in COLUNAS_DA_IDENTIDADE)
        devolvido = Decimal("0.00")
        if _e_total(linha):
            devolvido = sum((de(l["EM ABERTO"]) + de(l["Retido"])
                             + de(l["Baixa adiant."]) + de(l["Alocado à mão"])
                             for l in sem_nota), Decimal("0.00"))
        assert compra - pago - retido - baixa - manual + devolvido == aberto, (
            linha.get("NF"), {c: str(linha[c]) for c in COLUNAS_DA_IDENTIDADE})


# --- invariante de LUGAR -------------------------------------------------
# Todo lancamento da razao termina em EXATAMENTE um lugar -- composicao, balde,
# anulado (par de estorno) ou fora (decisao do contador) -- e, na composicao,
# do lado certo: compra so' em credito, pagamento/retencao/baixa so' em
# debito. Nasceu de um erro: compra em debito somava 0 a NF e quitacao em credito
# entrava na NF sem quitar nada -- o dinheiro sumia e o veredito acusava a
# composicao em vez do lancamento.

def lugares_dos_lancamentos(res) -> dict[int, list[str]]:
    """id(lancamento) -> os lugares em que ele aparece (com repeticao)."""
    from core.modelo import DestinoAlocacao
    lugares: dict[int, list[str]] = {}

    def marca(l, onde):
        lugares.setdefault(id(l), []).append(onde)

    for nf in res.nfs:
        for l in nf.compras:
            marca(l, "composicao")
        for l in nf.pagamentos + nf.retencoes + nf.baixas + nf.manuais:
            marca(l, "composicao")
        for a in nf.alocacoes:                  # multi-NF: 1 lancamento, N NFs
            marca(a.lancamento, "alocacao")
    baldes = list(res.balde) + (list(res.fechado.balde) if res.fechado else [])
    for item in baldes:
        for l in item.lancamentos:
            marca(l, "balde")
    for a in res.achados:
        if a.codigo == "estorno_pareado":
            for l in a.lancamentos:
                marca(l, "anulado")
    for d in res.decisoes:
        if d.destino is DestinoAlocacao.FORA_DA_COMPOSICAO:
            for l in d.item.lancamentos:
                marca(l, "fora")
    return lugares


def invariante_de_lugar(res) -> None:
    """Falha dizendo QUAL lancamento quebrou e por que."""
    lugares = lugares_dos_lancamentos(res)
    ids = {id(l) for l in res.conta.lancamentos}
    assert set(lugares) <= ids, "lugar com lancamento que nao e' da razao"
    alocado: dict[int, Decimal] = {}
    for nf in res.nfs:
        for a in nf.alocacoes:
            alocado[id(a.lancamento)] = alocado.get(id(a.lancamento),
                                                    Decimal("0.00")) + a.valor
    for l in res.conta.lancamentos:
        onde = lugares.get(id(l), [])
        quem = f"lote {l.numero} (D {l.debito} C {l.credito})"
        assert onde, f"{quem} nao esta em lugar nenhum"
        distintos = {"composicao" if o == "alocacao" else o for o in onde}
        assert len(distintos) == 1, f"{quem} esta em {sorted(distintos)}"
        if "alocacao" in onde:
            assert onde.count("composicao") == 0, f"{quem} alocado e casado"
            assert alocado[id(l)] == l.debito, f"{quem} alocado {alocado[id(l)]}"
        elif distintos == {"composicao"}:
            assert len(onde) == 1, f"{quem} em {len(onde)} linhas da composicao"
    for nf in res.nfs:
        for l in nf.compras:
            assert l.debito == 0, (f"compra em debito na NF {nf.numero}: "
                                   f"lote {l.numero}")
        for l in nf.pagamentos + nf.retencoes + nf.baixas:
            assert l.credito == 0, (f"quitacao em credito na NF {nf.numero}: "
                                    f"lote {l.numero}")

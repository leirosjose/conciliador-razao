"""Nome do Excel de saida: mesmo nome do arquivo de origem, com o sufixo
_conferencia e extensao .xlsx.

Sanitiza pro WINDOWS (o servidor do escritorio e o navegador do conferente):
<>:"/\\|?* e caracteres de controle viram '_'; nome nao termina em ponto ou
espaco (o Windows rejeita). Colisao (dois uploads com o mesmo nome, ou que so
diferem na caixa: o Windows trata como o mesmo arquivo) ganha sufixo _2/_3 na
ordem de chegada — NUNCA sobrescreve em silencio.
"""
from __future__ import annotations

import re
import unicodedata

# invalidos em nome de arquivo no Windows + controle (inclui \n \t de upload)
_INVALIDO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FALLBACK = "razao"
# a saida tem a MESMA extensao da entrada (.xlsx): sem o sufixo, o arquivo
# conferido se confundiria com a razao que entrou na pasta do conferente
SUFIXO_CONFERENCIA = "_conferencia"


def nfc(texto: str) -> str:
    """Normaliza pra NFC: upload do macOS/browser chega DECOMPOSTO
    (a + til combinante U+0303) — o combinante nao existe no cp1252 (glifo
    quebrado no PDF) e confunde a sanitizacao. NFC e' a forma que o resto do
    mundo (Dominio, Windows, cp1252) fala. TODA entrada de nome passa aqui
    ANTES de qualquer outra coisa."""
    return unicodedata.normalize("NFC", str(texto))


def nome_excel(nome_origem: str) -> str:
    """'Fornecedor_Razao.xls' -> 'Fornecedor_Razao_conferencia.xlsx'. So a ULTIMA extensao
    cai (ponto no meio e' nome); eventual diretorio no nome de upload e'
    descartado.

    O sufixo NAO se empilha. A planilha exportada abre na ferramenta (a
    aba 1 e' a razao original fiel), entao reexportar era comum em campo e
    produzia 'razao_conferencia_conferencia.xlsx' — e mais um a cada ciclo. Os
    sufixos ja existentes caem antes de acrescentar UM; so' no FIM do nome, que
    e' onde este modulo o poe: '_conferencia' no meio e' nome do usuario."""
    base = nfc(nome_origem).replace("\\", "/").rsplit("/", 1)[-1]
    raiz, ponto, _ = base.rpartition(".")
    stem = raiz if ponto else base
    # ASCII só no nome entregue, depois de separar pasta/extensão e antes de limpar.
    stem = "".join(c if c.isascii() else "_"
                   for c in unicodedata.normalize("NFKD", stem)
                   if not unicodedata.combining(c))
    stem = _INVALIDO.sub("_", stem).strip().rstrip(". ")
    while stem.endswith(SUFIXO_CONFERENCIA):
        stem = stem[:-len(SUFIXO_CONFERENCIA)]
    return f"{stem or _FALLBACK}{SUFIXO_CONFERENCIA}.xlsx"


def nomes_sem_colisao(nomes: list[str]) -> list[str]:
    """Mesma lista, na mesma ordem, com sufixo _2/_3... onde houver repeticao.
    Repeticao ignora a caixa: 'Razao.xlsx' e 'razao.xlsx' sao o mesmo
    arquivo no Windows; a caixa de cada nome e' preservada. O sufixo tambem
    nao pisa em nome que ja existia na lista. Nomes que so divergem em
    NFD/NFC sao o MESMO nome (mesmos glifos): normaliza antes."""
    vistos: set[str] = set()
    saida: list[str] = []
    for nome in map(nfc, nomes):
        raiz, ponto, ext = nome.rpartition(".")
        candidato, n = nome, 1
        while candidato.casefold() in vistos:      # Windows ignora caixa
            n += 1
            candidato = f"{raiz}_{n}{ponto}{ext}" if ponto else f"{nome}_{n}"
        vistos.add(candidato.casefold())
        saida.append(candidato)
    return saida
